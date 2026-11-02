from dataclasses import dataclass
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.entities import TelegramUser, UserRole
from app.services.dynamic_config_service import DynamicConfigService

REQUIRED_UNAUTHORIZED_MESSAGE = (
    "هذا البوت خاص ولا تملك صلاحية استخدامه. يرجى التواصل مع مالك البوت للحصول على إمكانية الوصول."
)


@dataclass
class AccessCheckResult:
    allowed: bool
    user: Optional[TelegramUser]
    denial_message: str
    owner_contact_url: str
    reason: str = "ok"


class RBACGuard:
    """
    Zero-Trust Authorization & Section Permission Verifier.
    Evaluated on every single Telegram message/callback and REST request.
    """

    def __init__(self, db: AsyncSession, config_service: DynamicConfigService):
        self.db = db
        self.config_service = config_service

    async def verify_telegram_access(
        self,
        telegram_id: int,
        username: Optional[str] = None,
        full_name: str = "Telegram User",
        required_section: Optional[str] = None,
        require_admin: bool = False,
    ) -> AccessCheckResult:
        owner_id = await self.config_service.get_raw("bot.owner_telegram_id", 0)
        owner_username = await self.config_service.get_raw("bot.owner_contact_username", "owner")
        owner_username_clean = str(owner_username).lstrip("@").strip() or "owner"
        contact_url = f"https://t.me/{owner_username_clean}"

        stmt = select(TelegramUser).where(TelegramUser.telegram_id == telegram_id)
        user = (await self.db.execute(stmt)).scalar_one_or_none()

        # Auto-provision Owner if matching configured TELEGRAM_OWNER_ID
        if user is None and int(owner_id) != 0 and telegram_id == int(owner_id):
            user = TelegramUser(
                telegram_id=telegram_id,
                username=username,
                full_name=full_name or "Bot Owner",
                role=UserRole.OWNER,
                is_active=True,
            )
            self.db.add(user)
            await self.db.flush()

        if user is None or not user.is_active:
            return AccessCheckResult(
                allowed=False,
                user=user,
                denial_message=REQUIRED_UNAUTHORIZED_MESSAGE,
                owner_contact_url=contact_url,
                reason="unauthorized_or_inactive",
            )

        # Update metadata on activity
        if username and user.username != username:
            user.username = username
        if full_name and user.full_name != full_name:
            user.full_name = full_name

        # Owner bypasses section restrictions
        if user.role == UserRole.OWNER:
            return AccessCheckResult(
                allowed=True,
                user=user,
                denial_message="",
                owner_contact_url=contact_url,
                reason="owner_granted",
            )

        if require_admin and user.role not in (UserRole.OWNER, UserRole.ADMIN):
            return AccessCheckResult(
                allowed=False,
                user=user,
                denial_message="⛔ هذه العملية تتطلب صلاحية مشرف (Admin) أو مالك (Owner).",
                owner_contact_url=contact_url,
                reason="insufficient_role",
            )

        if required_section:
            global_sections = await self.config_service.get_raw("sections.enabled_map", {})
            if isinstance(global_sections, dict) and not global_sections.get(required_section, True):
                return AccessCheckResult(
                    allowed=False,
                    user=user,
                    denial_message="⚠️ هذا القسم متوقف مؤقتاً من قِبل إدارة النظام.",
                    owner_contact_url=contact_url,
                    reason="section_globally_disabled",
                )

            if required_section not in (user.allowed_sections or []):
                return AccessCheckResult(
                    allowed=False,
                    user=user,
                    denial_message=f"⛔ لا تملك صلاحية الوصول إلى قسم ({required_section}). تواصل مع المالك لتفعيل القسم لحسابك.",
                    owner_contact_url=contact_url,
                    reason="section_forbidden_for_user",
                )

        return AccessCheckResult(
            allowed=True,
            user=user,
            denial_message="",
            owner_contact_url=contact_url,
            reason="granted",
        )
