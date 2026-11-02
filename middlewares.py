from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.core.database import AsyncSessionLocal
from app.core.redis import get_redis
from app.models.entities import ActivityLog
from app.services.dynamic_config_service import DynamicConfigService
from app.services.rbac_service import RBACGuard
from app.bot.keyboards import build_unauthorized_keyboard

# Map callback prefixes to section permissions
CALLBACK_SECTION_MAP = {
    "nav:ai": "ai",
    "ai:": "ai",
    "nav:projects": "projects",
    "prj:": "projects",
    "nav:links": "links",
    "lnk:": "links",
    "nav:notes": "notes",
    "note:": "notes",
    "nav:tasks": "tasks",
    "task:": "tasks",
    "nav:reminders": "reminders",
    "rem:": "reminders",
    "nav:favorites": "favorites",
    "fav:": "favorites",
    "nav:search": "search",
    " nav:account": "account",
    "nav:settings": "settings",
}


class ZeroTrustRBACMiddleware(BaseMiddleware):
    """
    Intercepts every incoming Message and CallbackQuery.
    If the sender is not authorized or disabled, immediately returns the exact mandated
    Arabic denial message with the 'Contact Owner' inline button and halts execution.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        if tg_user is None:
            return await handler(event, data)

        required_section = None
        if isinstance(event, CallbackQuery) and event.data:
            for prefix, sec in CALLBACK_SECTION_MAP.items():
                if event.data.startswith(prefix):
                    required_section = sec
                    break

        redis_client = None
        try:
            redis_client = await get_redis()
        except Exception:
            pass

        async with AsyncSessionLocal() as db:
            cfg_service = DynamicConfigService(db, redis_client)
            guard = RBACGuard(db, cfg_service)
            full_name = f"{tg_user.first_name or ''} {tg_user.last_name or ''}".strip() or "Telegram User"

            check = await guard.verify_telegram_access(
                telegram_id=tg_user.id,
                username=tg_user.username,
                full_name=full_name,
                required_section=required_section,
            )

            if not check.allowed:
                db.add(
                    ActivityLog(
                        actor_telegram_id=tg_user.id,
                        actor_username=tg_user.username or str(tg_user.id),
                        action="ACCESS_DENIED",
                        section=required_section or "auth",
                        details=f"رفض وصول ({check.reason}) للمعرف {tg_user.id}",
                    )
                )
                await db.commit()

                kb = build_unauthorized_keyboard(check.owner_contact_url)
                if isinstance(event, Message):
                    await event.answer(check.denial_message, reply_markup=kb)
                elif isinstance(event, CallbackQuery):
                    await event.answer(check.denial_message[:190], show_alert=True)
                    if event.message:
                        await event.message.answer(check.denial_message, reply_markup=kb)
                return None

            data["db"] = db
            data["cfg_service"] = cfg_service
            data["auth_user"] = check.user
            result = await handler(event, data)
            await db.commit()
            return result
