from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.entities import (
    Project,
    ProjectFile,
    ProjectRevision,
    TelegramUser,
    UserRole,
)
from app.services.code_generator import format_project_code
from app.services.dynamic_config_service import DynamicConfigService


class ProjectVaultService:
    """
    Enterprise Project Vault & Telegram Storage Channel Service.
    1. Forwards/uploads files to the private Telegram storage channel.
    2. Persists message_id and telegram_file_id in PostgreSQL.
    3. Links files to projects via project_id.
    4. Retrieves files directly from Telegram storage channel without re-uploading.
    5. Enforces strict per-request user authorization before any file retrieval.
    """

    def __init__(self, db: AsyncSession, config_service: DynamicConfigService):
        self.db = db
        self.config_service = config_service

    async def create_project(
        self,
        owner: TelegramUser,
        name: str,
        description: str = "",
        category: str = "عام",
        keywords: Optional[List[str]] = None,
        notes: str = "",
    ) -> Project:
        max_id_stmt = select(func.coalesce(func.max(Project.id), 0))
        next_seq = int((await self.db.execute(max_id_stmt)).scalar_one()) + 1
        code = format_project_code(next_seq)

        project = Project(
            code=code,
            owner_id=owner.id,
            name=name.strip(),
            description=description.strip(),
            category=category.strip() or "عام",
            keywords=keywords or [],
            notes=notes.strip(),
        )
        self.db.add(project)
        await self.db.flush()

        rev = ProjectRevision(
            project_id=project.id,
            actor_name=owner.username or str(owner.telegram_id),
            action="CREATE_PROJECT",
            changes_summary=f"إنشاء المشروع بكود {code} تحت تصنيف {project.category}",
        )
        self.db.add(rev)
        await self.db.flush()
        return project

    async def get_project_authorized(
        self,
        requester: TelegramUser,
        project_id: Optional[int] = None,
        project_code: Optional[str] = None,
    ) -> Optional[Project]:
        stmt = select(Project).options(selectinload(Project.files), selectinload(Project.revisions))
        if project_id is not None:
            stmt = stmt.where(Project.id == project_id)
        elif project_code is not None:
            stmt = stmt.where(Project.code == project_code.strip().upper())
        else:
            return None

        project = (await self.db.execute(stmt)).scalar_one_or_none()
        if project is None:
            return None

        if requester.role not in (UserRole.OWNER, UserRole.ADMIN) and project.owner_id != requester.id:
            raise PermissionError("⛔ لا تملك صلاحية الوصول إلى هذا المشروع أو ملفاته.")

        return project

    async def register_channel_stored_file(
        self,
        requester: TelegramUser,
        project_id: int,
        file_name: str,
        file_type: str,
        mime_type: str,
        file_size_bytes: int,
        telegram_file_id: str,
        telegram_unique_id: str,
        storage_channel_id: int,
        storage_message_id: int,
        caption: str = "",
    ) -> ProjectFile:
        project = await self.get_project_authorized(requester, project_id=project_id)
        if project is None:
            raise ValueError("المشروع غير موجود.")

        # Check user's file quota
        count_stmt = (
            select(func.count(ProjectFile.id))
            .join(Project, ProjectFile.project_id == Project.id)
            .where(Project.owner_id == requester.id)
        )
        total_files = int((await self.db.execute(count_stmt)).scalar_one())
        if total_files >= requester.max_storage_files and requester.role != UserRole.OWNER:
            raise PermissionError(f"⚠️ تجاوزت الحد الأقصى لعدد الملفات المسموح به ({requester.max_storage_files} ملف).")

        pf = ProjectFile(
            project_id=project.id,
            file_name=file_name,
            file_type=file_type,
            mime_type=mime_type,
            file_size_bytes=file_size_bytes,
            telegram_file_id=telegram_file_id,
            telegram_unique_id=telegram_unique_id,
            storage_channel_id=storage_channel_id,
            storage_message_id=storage_message_id,
            caption=caption,
            uploaded_by_telegram_id=requester.telegram_id,
        )
        self.db.add(pf)

        rev = ProjectRevision(
            project_id=project.id,
            actor_name=requester.username or str(requester.telegram_id),
            action="ADD_FILE",
            changes_summary=f"إضافة ملف {file_name} (رسالة القناة #{storage_message_id})",
        )
        self.db.add(rev)
        await self.db.flush()
        return pf

    async def authorize_file_retrieval(
        self, requester: TelegramUser, file_id: int
    ) -> ProjectFile:
        stmt = (
            select(ProjectFile)
            .options(selectinload(ProjectFile.project))
            .where(ProjectFile.id == file_id)
        )
        pf = (await self.db.execute(stmt)).scalar_one_or_none()
        if pf is None:
            raise ValueError("الملف المطلوب غير موجود.")

        if requester.role not in (UserRole.OWNER, UserRole.ADMIN) and pf.project.owner_id != requester.id:
            raise PermissionError("⛔ غير مصرح لك باسترجاع أو تحميل هذا الملف.")

        return pf

    async def mark_file_missing_in_channel(self, file_id: int) -> None:
        stmt = select(ProjectFile).where(ProjectFile.id == file_id)
        pf = (await self.db.execute(stmt)).scalar_one_or_none()
        if pf:
            pf.is_missing_in_channel = True
            await self.db.flush()

    async def search_projects(
        self,
        requester: TelegramUser,
        query: str = "",
        category: Optional[str] = None,
        offset: int = 0,
        limit: int = 10,
    ) -> Tuple[List[Project], int]:
        stmt = select(Project).options(selectinload(Project.files))
        count_stmt = select(func.count(Project.id))

        if requester.role not in (UserRole.OWNER, UserRole.ADMIN):
            stmt = stmt.where(Project.owner_id == requester.id)
            count_stmt = count_stmt.where(Project.owner_id == requester.id)

        if category:
            stmt = stmt.where(Project.category == category)
            count_stmt = count_stmt.where(Project.category == category)

        if query.strip():
            q = f"%{query.strip()}%"
            cond = or_(
                Project.code.ilike(q),
                Project.name.ilike(q),
                Project.description.ilike(q),
                Project.category.ilike(q),
            )
            stmt = stmt.where(cond)
            count_stmt = count_stmt.where(cond)

        total = int((await self.db.execute(count_stmt)).scalar_one())
        rows = (
            await self.db.execute(
                stmt.order_by(Project.created_at.desc()).offset(offset).limit(limit)
            )
        ).scalars().all()
        return list(rows), total

    async def update_project(
        self,
        requester: TelegramUser,
        project_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
        category: Optional[str] = None,
        keywords: Optional[List[str]] = None,
        notes: Optional[str] = None,
    ) -> Project:
        project = await self.get_project_authorized(requester, project_id=project_id)
        if project is None:
            raise ValueError("المشروع غير موجود.")

        changed_fields = []
        if name is not None and name.strip() != project.name:
            project.name = name.strip()
            changed_fields.append("الاسم")
        if description is not None and description != project.description:
            project.description = description
            changed_fields.append("الوصف")
        if category is not None and category != project.category:
            project.category = category
            changed_fields.append("التصنيف")
        if keywords is not None:
            project.keywords = keywords
            changed_fields.append("الكلمات المفتاحية")
        if notes is not None and notes != project.notes:
            project.notes = notes
            changed_fields.append("الملاحظات")

        if changed_fields:
            rev = ProjectRevision(
                project_id=project.id,
                actor_name=requester.username or str(requester.telegram_id),
                action="UPDATE_PROJECT",
                changes_summary="تعديل الحقول: " + "، ".join(changed_fields),
            )
            self.db.add(rev)
            await self.db.flush()

        return project

    async def delete_project(self, requester: TelegramUser, project_id: int) -> bool:
        project = await self.get_project_authorized(requester, project_id=project_id)
        if project is None:
            return False
        await self.db.delete(project)
        await self.db.flush()
        return True

    async def export_projects_manifest(self, requester: TelegramUser) -> List[Dict[str, Any]]:
        projects, _ = await self.search_projects(requester, limit=1000)
        export_data = []
        for p in projects:
            export_data.append({
                "code": p.code,
                "name": p.name,
                "description": p.description,
                "category": p.category,
                "keywords": p.keywords,
                "notes": p.notes,
                "created_at": p.created_at.isoformat() if p.created_at else None,
                "files": [
                    {
                        "file_name": f.file_name,
                        "file_type": f.file_type,
                        "file_size_bytes": f.file_size_bytes,
                        "storage_channel_id": f.storage_channel_id,
                        "storage_message_id": f.storage_message_id,
                        "telegram_file_id": f.telegram_file_id,
                    }
                    for f in p.files
                ],
            })
        return export_data
