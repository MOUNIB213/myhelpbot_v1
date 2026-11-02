"""
botmi.py — Ready-to-run Entrypoint for the Private Telegram Assistant Bot.
Configured for Owner: @mounibkhaldi (ID: 8456971230) & Storage Channel: -1004221077545
Uses local SQLite database (botvault.db) out-of-the-box with zero external servers required.
"""
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from app.bot.admin_handlers import admin_router
from app.bot.handlers import router as main_router
from app.bot.middlewares import ZeroTrustRBACMiddleware
from app.core.config import get_settings
from app.core.database import AsyncSessionLocal, Base, engine
from app.core.redis import close_redis, get_redis
from app.models.entities import (
    BroadcastJob,
    BroadcastStatus,
    Reminder,
    TelegramUser,
    UserRole,
)
from app.services.dynamic_config_service import DynamicConfigService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("botmi")


async def background_reminder_and_broadcast_worker(bot: Bot) -> None:
    """Polls due reminders and pending broadcast jobs with strict Telegram rate-limiting."""
    while True:
        try:
            async with AsyncSessionLocal() as db:
                now = datetime.now(timezone.utc)
                # 1. Process Due Reminders
                rem_stmt = (
                    select(Reminder)
                    .where(Reminder.is_sent.is_(False), Reminder.remind_at <= now)
                    .limit(25)
                )
                due_reminders = (await db.execute(rem_stmt)).scalars().all()
                for rem in due_reminders:
                    try:
                        await bot.send_message(
                            chat_id=rem.telegram_id,
                            text=f"⏰ <b>تذكير مجدول:</b>\n\n{rem.message}",
                            parse_mode=ParseMode.HTML,
                        )
                    except Exception as exc:
                        logger.warning("Failed sending reminder %s: %s", rem.id, exc)
                    rem.is_sent = True
                    rem.sent_at = now

                # 2. Process Pending Broadcast Jobs
                b_stmt = (
                    select(BroadcastJob)
                    .where(BroadcastJob.status == BroadcastStatus.PENDING)
                    .order_by(BroadcastJob.created_at.asc())
                    .limit(1)
                )
                job = (await db.execute(b_stmt)).scalar_one_or_none()
                if job is not None:
                    job.status = BroadcastStatus.RUNNING
                    await db.commit()

                    u_stmt = select(TelegramUser).where(TelegramUser.is_active.is_(True))
                    if job.target_role:
                        u_stmt = u_stmt.where(TelegramUser.role == UserRole(job.target_role.upper()))
                    users = (await db.execute(u_stmt)).scalars().all()

                    delay = 1.0 / max(1, min(25, job.rate_limit_per_sec))
                    kb = None
                    if job.button_text and job.button_url:
                        kb = InlineKeyboardMarkup(
                            inline_keyboard=[[InlineKeyboardButton(text=job.button_text, url=job.button_url)]]
                        )

                    sent, failed = 0, 0
                    for u in users:
                        try:
                            await bot.send_message(
                                chat_id=u.telegram_id,
                                text=f"📢 <b>إشعار إداري عام:</b>\n\n{job.message_text}",
                                reply_markup=kb,
                                parse_mode=ParseMode.HTML,
                            )
                            sent += 1
                        except Exception:
                            failed += 1
                        await asyncio.sleep(delay)

                    job.sent_count = sent
                    job.failed_count = failed
                    job.status = BroadcastStatus.COMPLETED
                    job.completed_at = datetime.now(timezone.utc)

                await db.commit()
        except Exception as worker_err:
            logger.error("Background worker error: %s", worker_err)

        await asyncio.sleep(5)


async def main() -> None:
    settings = get_settings()
    Path(settings.BACKUP_DIR).mkdir(parents=True, exist_ok=True)

    # Create local SQLite database tables automatically on first boot
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    redis_client = None
    try:
        r = await get_redis()
        await r.ping()
        redis_client = r
    except Exception:
        logger.info("Redis not running locally — falling back to SQLite + in-memory cache seamlessly.")

    async with AsyncSessionLocal() as db:
        cfg_svc = DynamicConfigService(db, redis_client)
        await cfg_svc.seed_defaults()

        # Ensure Owner (@mounibkhaldi / 8456971230) is seeded with OWNER role
        stmt = select(TelegramUser).where(TelegramUser.telegram_id == settings.TELEGRAM_OWNER_ID)
        owner = (await db.execute(stmt)).scalar_one_or_none()
        if owner is None:
            owner = TelegramUser(
                telegram_id=settings.TELEGRAM_OWNER_ID,
                username=settings.TELEGRAM_OWNER_USERNAME,
                full_name="Mounib Khaldi (Owner)",
                role=UserRole.OWNER,
                is_active=True,
                daily_ai_requests_limit=1000,
                daily_ai_tokens_limit=2000000,
                max_storage_files=5000,
            )
            db.add(owner)
        await db.commit()

    bot = Bot(
        token=settings.TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Register Zero-Trust RBAC Middleware
    rbac_mw = ZeroTrustRBACMiddleware()
    dp.message.outer_middleware(rbac_mw)
    dp.callback_query.outer_middleware(rbac_mw)

    dp.include_router(admin_router)
    dp.include_router(main_router)

    worker_task = asyncio.create_task(background_reminder_and_broadcast_worker(bot))
    logger.info("Bot is live! Owner ID: %s (@%s) | Storage Channel: %s",
                settings.TELEGRAM_OWNER_ID, settings.TELEGRAM_OWNER_USERNAME, settings.TELEGRAM_STORAGE_CHANNEL_ID)
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        worker_task.cancel()
        await bot.session.close()
        await close_redis()


if __name__ == "__main__":
    asyncio.run(main())
