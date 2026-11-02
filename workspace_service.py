import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.entities import (
    ActivityLog,
    BackupRecord,
    FavoriteItem,
    ImportantLink,
    Note,
    Project,
    Reminder,
    TaskItem,
    TaskPriority,
    TaskStatus,
    TelegramUser,
    UserRole,
)
from app.services.code_generator import format_link_code


class WorkspaceService:
    """
    Handles Important Links (LNK-2026-B001), Notes, Tasks, Reminders,
    Favorites, Global Search across all modules, Personal Statistics,
    and Checksum-Verified Backup & Restore.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.settings = get_settings()

    # --- Important Links ---
    async def create_link(
        self,
        user: TelegramUser,
        title: str,
        url: str,
        description: str = "",
        category: str = "عام",
        keywords: Optional[List[str]] = None,
        is_favorite: bool = False,
    ) -> ImportantLink:
        if not (url.startswith("http://") or url.startswith("https://")):
            raise ValueError("يجب أن يبدأ الرابط بـ http:// أو https://")

        max_id_stmt = select(func.coalesce(func.max(ImportantLink.id), 0))
        next_seq = int((await self.db.execute(max_id_stmt)).scalar_one()) + 1
        code = format_link_code(next_seq)

        link = ImportantLink(
            code=code,
            user_id=user.id,
            title=title.strip(),
            url=url.strip(),
            description=description.strip(),
            category=category.strip() or "عام",
            keywords=keywords or [],
            is_favorite=is_favorite,
        )
        self.db.add(link)
        await self.db.flush()
        return link

    async def list_links(
        self,
        user: TelegramUser,
        query: str = "",
        category: Optional[str] = None,
        favorites_only: bool = False,
        offset: int = 0,
        limit: int = 10,
    ) -> Tuple[List[ImportantLink], int]:
        stmt = select(ImportantLink)
        count_stmt = select(func.count(ImportantLink.id))

        if user.role not in (UserRole.OWNER, UserRole.ADMIN):
            stmt = stmt.where(ImportantLink.user_id == user.id)
            count_stmt = count_stmt.where(ImportantLink.user_id == user.id)

        if category:
            stmt = stmt.where(ImportantLink.category == category)
            count_stmt = count_stmt.where(ImportantLink.category == category)

        if favorites_only:
            stmt = stmt.where(ImportantLink.is_favorite.is_(True))
            count_stmt = count_stmt.where(ImportantLink.is_favorite.is_(True))

        if query.strip():
            q = f"%{query.strip()}%"
            cond = or_(
                ImportantLink.code.ilike(q),
                ImportantLink.title.ilike(q),
                ImportantLink.url.ilike(q),
                ImportantLink.description.ilike(q),
                ImportantLink.category.ilike(q),
            )
            stmt = stmt.where(cond)
            count_stmt = count_stmt.where(cond)

        total = int((await self.db.execute(count_stmt)).scalar_one())
        rows = (
            await self.db.execute(
                stmt.order_by(ImportantLink.is_favorite.desc(), ImportantLink.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
        ).scalars().all()
        return list(rows), total

    # --- Notes ---
    async def create_note(
        self,
        user: TelegramUser,
        title: str,
        content: str,
        tags: Optional[List[str]] = None,
        is_pinned: bool = False,
    ) -> Note:
        note = Note(
            user_id=user.id,
            title=title.strip(),
            content=content.strip(),
            tags=tags or [],
            is_pinned=is_pinned,
        )
        self.db.add(note)
        await self.db.flush()
        return note

    # --- Tasks ---
    async def create_task(
        self,
        user: TelegramUser,
        title: str,
        description: str = "",
        priority: TaskPriority = TaskPriority.MEDIUM,
        due_date: Optional[datetime] = None,
    ) -> TaskItem:
        task = TaskItem(
            user_id=user.id,
            title=title.strip(),
            description=description.strip(),
            priority=priority,
            status=TaskStatus.TODO,
            due_date=due_date,
        )
        self.db.add(task)
        await self.db.flush()
        return task

    async def toggle_task_status(self, user: TelegramUser, task_id: int) -> Optional[TaskItem]:
        stmt = select(TaskItem).where(TaskItem.id == task_id, TaskItem.user_id == user.id)
        task = (await self.db.execute(stmt)).scalar_one_or_none()
        if task is None:
            return None
        if task.status == TaskStatus.DONE:
            task.status = TaskStatus.TODO
            task.completed_at = None
        else:
            task.status = TaskStatus.DONE
            task.completed_at = datetime.now(timezone.utc)
        await self.db.flush()
        return task

    # --- Reminders ---
    async def create_reminder(
        self,
        user: TelegramUser,
        message: str,
        remind_at: datetime,
    ) -> Reminder:
        rem = Reminder(
            user_id=user.id,
            telegram_id=user.telegram_id,
            message=message.strip(),
            remind_at=remind_at,
            is_sent=False,
        )
        self.db.add(rem)
        await self.db.flush()
        return rem

    # --- Favorites ---
    async def toggle_favorite(
        self,
        user: TelegramUser,
        entity_type: str,
        entity_id: int,
        title_snapshot: str,
        code_snapshot: Optional[str] = None,
    ) -> bool:
        stmt = select(FavoriteItem).where(
            FavoriteItem.user_id == user.id,
            FavoriteItem.entity_type == entity_type,
            FavoriteItem.entity_id == entity_id,
        )
        existing = (await self.db.execute(stmt)).scalar_one_or_none()
        if existing:
            await self.db.delete(existing)
            await self.db.flush()
            return False
        fav = FavoriteItem(
            user_id=user.id,
            entity_type=entity_type,
            entity_id=entity_id,
            title_snapshot=title_snapshot[:250],
            code_snapshot=code_snapshot,
        )
        self.db.add(fav)
        await self.db.flush()
        return True

    # --- Global Search ---
    async def global_search(self, user: TelegramUser, query: str) -> Dict[str, List[Dict[str, Any]]]:
        q = f"%{query.strip()}%"
        is_privileged = user.role in (UserRole.OWNER, UserRole.ADMIN)

        # Projects
        p_stmt = select(Project).where(
            or_(Project.code.ilike(q), Project.name.ilike(q), Project.description.ilike(q), Project.category.ilike(q))
        )
        if not is_privileged:
            p_stmt = p_stmt.where(Project.owner_id == user.id)
        projects = (await self.db.execute(p_stmt.limit(10))).scalars().all()

        # Links
        l_stmt = select(ImportantLink).where(
            or_(ImportantLink.code.ilike(q), ImportantLink.title.ilike(q), ImportantLink.url.ilike(q), ImportantLink.description.ilike(q))
        )
        if not is_privileged:
            l_stmt = l_stmt.where(ImportantLink.user_id == user.id)
        links = (await self.db.execute(l_stmt.limit(10))).scalars().all()

        # Notes
        n_stmt = select(Note).where(
            Note.user_id == user.id,
            or_(Note.title.ilike(q), Note.content.ilike(q)),
        )
        notes = (await self.db.execute(n_stmt.limit(10))).scalars().all()

        # Tasks
        t_stmt = select(TaskItem).where(
            TaskItem.user_id == user.id,
            or_(TaskItem.title.ilike(q), TaskItem.description.ilike(q)),
        )
        tasks = (await self.db.execute(t_stmt.limit(10))).scalars().all()

        return {
            "projects": [{"id": p.id, "code": p.code, "name": p.name, "category": p.category} for p in projects],
            "links": [{"id": l.id, "code": l.code, "title": l.title, "url": l.url} for l in links],
            "notes": [{"id": n.id, "title": n.title, "pinned": n.is_pinned} for n in notes],
            "tasks": [{"id": t.id, "title": t.title, "status": t.status.value} for t in tasks],
        }

    # --- Verified Backup & Restore ---
    async def create_verified_backup(self, created_by: str = "admin", backup_type: str = "manual") -> BackupRecord:
        backup_dir = Path(self.settings.BACKUP_DIR)
        backup_dir.mkdir(parents=True, exist_ok=True)

        projects = (await self.db.execute(select(Project))).scalars().all()
        links = (await self.db.execute(select(ImportantLink))).scalars().all()
        notes = (await self.db.execute(select(Note))).scalars().all()
        tasks = (await self.db.execute(select(TaskItem))).scalars().all()

        payload = {
            "version": "2.0.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "created_by": created_by,
            "counts": {
                "projects": len(projects),
                "links": len(links),
                "notes": len(notes),
                "tasks": len(tasks),
            },
            "projects": [
                {
                    "code": p.code,
                    "owner_id": p.owner_id,
                    "name": p.name,
                    "description": p.description,
                    "category": p.category,
                    "keywords": p.keywords,
                    "notes": p.notes,
                }
                for p in projects
            ],
            "links": [
                {
                    "code": l.code,
                    "user_id": l.user_id,
                    "title": l.title,
                    "url": l.url,
                    "description": l.description,
                    "category": l.category,
                    "keywords": l.keywords,
                    "is_favorite": l.is_favorite,
                }
                for l in links
            ],
            "notes": [
                {
                    "user_id": n.user_id,
                    "title": n.title,
                    "content": n.content,
                    "tags": n.tags,
                    "is_pinned": n.is_pinned,
                }
                for n in notes
            ],
        }

        raw_bytes = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        sha256_hash = hashlib.sha256(raw_bytes).hexdigest()
        ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        file_name = f"vault_backup_{ts_str}_{sha256_hash[:8]}.json"
        file_path = backup_dir / file_name
        file_path.write_bytes(raw_bytes)

        record = BackupRecord(
            file_name=file_name,
            file_path=str(file_path),
            file_size_bytes=len(raw_bytes),
            sha256_checksum=sha256_hash,
            backup_type=backup_type,
            created_by=created_by,
            is_verified=True,
        )
        self.db.add(record)
        await self.db.flush()
        return record

    @staticmethod
    def verify_backup_integrity(file_path: str, expected_sha256: str) -> bool:
        p = Path(file_path)
        if not p.exists() or not p.is_file():
            return False
        actual = hashlib.sha256(p.read_bytes()).hexdigest()
        if actual != expected_sha256:
            return False
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return "version" in data and "projects" in data and "links" in data
        except Exception:
            return False
