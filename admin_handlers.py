from pathlib import Path
from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards import build_inbot_admin_panel_keyboard, build_main_menu_keyboard
from app.bot.states import InBotAdminStates
from app.models.entities import (
    AISession,
    AIUsageQuota,
    BroadcastJob,
    BroadcastStatus,
    ImportantLink,
    Note,
    Project,
    ProjectFile,
    TaskItem,
    TelegramUser,
    UserRole,
)
from app.services.dynamic_config_service import DynamicConfigService
from app.services.workspace_service import WorkspaceService

admin_router = Router(name="inbot_admin_control_router")


def _is_admin_or_owner(user: TelegramUser) -> bool:
    return user.role in (UserRole.OWNER, UserRole.ADMIN)


@admin_router.message(Command("admin"))
@admin_router.callback_query(F.data == "nav:settings")
async def open_inbot_admin_center(
    event: Message | CallbackQuery,
    state: FSMContext,
    auth_user: TelegramUser,
    cfg_service: DynamicConfigService,
) -> None:
    await state.clear()
    if not _is_admin_or_owner(auth_user):
        msg = "⚙️ <b>إعدادات الحساب</b>\nاللغة: العربية (RTL)\nالإشعارات: مفعلة ✅"
        if isinstance(event, CallbackQuery):
            await event.answer("إعدادات المستخدم", show_alert=False)
            if event.message:
                await event.message.edit_text(
                    msg,
                    reply_markup=build_main_menu_keyboard(auth_user.allowed_sections),
                    parse_mode=ParseMode.HTML,
                )
        else:
            await event.answer(msg, reply_markup=build_main_menu_keyboard(auth_user.allowed_sections), parse_mode=ParseMode.HTML)
        return

    ai_enabled = bool(await cfg_service.get_raw("ai.enabled", True))
    model_name = await cfg_service.get_raw("ai.model_name", "gemini-2.5-flash")
    channel_id = await cfg_service.get_raw("storage.channel_id", 0)

    text = (
        f"🛡️ <b>لوحة تحكم الأدمن داخل البوت (Admin Control Panel)</b>\n\n"
        f"• صلاحيتك: <b>{auth_user.role.value}</b>\n"
        f"• حالة Gemini AI: <b>{'🟢 مفعل' if ai_enabled else '🔴 متوقف'}</b> (<code>{model_name}</code>)\n"
        f"• قناة التخزين الخاصة: <code>{channel_id}</code>\n\n"
        f"اختر العملية الإدارية المطلوبة:"
    )
    kb = build_inbot_admin_panel_keyboard(ai_enabled=ai_enabled)
    if isinstance(event, CallbackQuery):
        if event.message:
            await event.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        await event.answer()
    else:
        await event.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@admin_router.callback_query(F.data == "adm:stats")
async def cb_adm_stats(
    callback: CallbackQuery,
    db: AsyncSession,
    auth_user: TelegramUser,
    cfg_service: DynamicConfigService,
) -> None:
    if not _is_admin_or_owner(auth_user):
        await callback.answer("⛔ غير مصرح", show_alert=True)
        return

    total_users = int((await db.execute(select(func.count(TelegramUser.id)))).scalar_one())
    total_projects = int((await db.execute(select(func.count(Project.id)))).scalar_one())
    total_files = int((await db.execute(select(func.count(ProjectFile.id)))).scalar_one())
    total_links = int((await db.execute(select(func.count(ImportantLink.id)))).scalar_one())
    total_sessions = int((await db.execute(select(func.count(AISession.id)))).scalar_one())
    total_tokens = int((await db.execute(select(func.coalesce(func.sum(AIUsageQuota.tokens_count), 0)))).scalar_one())
    total_cost = float((await db.execute(select(func.coalesce(func.sum(AIUsageQuota.estimated_cost_usd), 0.0)))).scalar_one())

    ai_enabled = bool(await cfg_service.get_raw("ai.enabled", True))
    stats_text = (
        f"📊 <b>إحصائيات النظام الشاملة:</b>\n\n"
        f"👥 إجمالي المستخدمين: <b>{total_users}</b>\n"
        f"📁 إجمالي المشاريع: <b>{total_projects}</b>\n"
        f"📦 الملفات في قناة التخزين: <b>{total_files}</b>\n"
        f"🔗 الروابط المهمة: <b>{total_links}</b>\n"
        f"🤖 جلسات الذكاء الاصطناعي: <b>{total_sessions}</b>\n"
        f"🪙 إجمالي استهلاك التوكنات: <b>{total_tokens:,}</b>\n"
        f"💵 التكلفة التقديرية لـ Gemini: <b>${total_cost:.4f}</b>"
    )
    if callback.message:
        await callback.message.edit_text(
            stats_text,
            reply_markup=build_inbot_admin_panel_keyboard(ai_enabled=ai_enabled),
            parse_mode=ParseMode.HTML,
        )
    await callback.answer()


@admin_router.callback_query(F.data == "adm:users")
async def cb_adm_list_users(
    callback: CallbackQuery,
    db: AsyncSession,
    auth_user: TelegramUser,
    cfg_service: DynamicConfigService,
) -> None:
    if not _is_admin_or_owner(auth_user):
        await callback.answer("⛔ غير مصرح", show_alert=True)
        return

    users = (await db.execute(select(TelegramUser).order_by(TelegramUser.joined_at.desc()).limit(25))).scalars().all()
    lines = ["👥 <b>قائمة المستخدمين المصرح لهم:</b>\n"]
    for u in users:
        status_icon = "🟢" if u.is_active else "🔴"
        lines.append(
            f"{status_icon} <code>{u.telegram_id}</code> | @{u.username or 'N/A'} | <b>{u.role.value}</b> (حد AI: {u.daily_ai_requests_limit}/يوم)"
        )
    ai_enabled = bool(await cfg_service.get_raw("ai.enabled", True))
    if callback.message:
        await callback.message.edit_text(
            "\n".join(lines),
            reply_markup=build_inbot_admin_panel_keyboard(ai_enabled=ai_enabled),
            parse_mode=ParseMode.HTML,
        )
    await callback.answer()


@admin_router.callback_query(F.data == "adm:user_add")
async def cb_adm_user_add_prompt(callback: CallbackQuery, state: FSMContext, auth_user: TelegramUser) -> None:
    if not _is_admin_or_owner(auth_user):
        await callback.answer("⛔ غير مصرح", show_alert=True)
        return
    await state.set_state(InBotAdminStates.adding_user_id)
    if callback.message:
        await callback.message.answer(
            "➕ أرسل <b>المعرف الرقمي (Telegram ID)</b> للمستخدم الجديد متبوعاً بالصلاحية (USER أو ADMIN):\n"
            "مثال: <code>618392011 USER</code>",
            parse_mode=ParseMode.HTML,
        )
    await callback.answer()


@admin_router.message(InBotAdminStates.adding_user_id, F.text)
async def handle_adm_user_add(
    message: Message,
    state: FSMContext,
    db: AsyncSession,
    auth_user: TelegramUser,
    cfg_service: DynamicConfigService,
) -> None:
    parts = (message.text or "").strip().split()
    if not parts or not parts[0].isdigit():
        await message.answer("⚠️ يرجى إرسال معرف تلغرام رقمي صحيح (مثال: <code>618392011 USER</code>).", parse_mode=ParseMode.HTML)
        return

    tg_id = int(parts[0])
    role_str = parts[1].upper() if len(parts) > 1 and parts[1].upper() in ("USER", "ADMIN") else "USER"
    stmt = select(TelegramUser).where(TelegramUser.telegram_id == tg_id)
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        existing.is_active = True
        existing.role = UserRole(role_str)
    else:
        db.add(
            TelegramUser(
                telegram_id=tg_id,
                full_name=f"User {tg_id}",
                role=UserRole(role_str),
                is_active=True,
            )
        )
    await db.flush()
    await state.clear()
    ai_enabled = bool(await cfg_service.get_raw("ai.enabled", True))
    await message.answer(
        f"✅ تم تفعيل وإضافة المستخدم <code>{tg_id}</code> بصلاحية <b>{role_str}</b> بنجاح.",
        reply_markup=build_inbot_admin_panel_keyboard(ai_enabled=ai_enabled),
        parse_mode=ParseMode.HTML,
    )


@admin_router.callback_query(F.data == "adm:user_del")
async def cb_adm_user_del_prompt(callback: CallbackQuery, state: FSMContext, auth_user: TelegramUser) -> None:
    if not _is_admin_or_owner(auth_user):
        await callback.answer("⛔ غير مصرح", show_alert=True)
        return
    await state.set_state(InBotAdminStates.removing_user_id)
    if callback.message:
        await callback.message.answer("🚫 أرسل <b>Telegram ID</b> للمستخدم المراد تعطيله أو حذفه:", parse_mode=ParseMode.HTML)
    await callback.answer()


@admin_router.message(InBotAdminStates.removing_user_id, F.text)
async def handle_adm_user_del(
    message: Message,
    state: FSMContext,
    db: AsyncSession,
    auth_user: TelegramUser,
    cfg_service: DynamicConfigService,
) -> None:
    raw_id = (message.text or "").strip()
    if not raw_id.isdigit():
        await message.answer("⚠️ يرجى إرسال معرف رقمي صحيح.")
        return
    tg_id = int(raw_id)
    stmt = select(TelegramUser).where(TelegramUser.telegram_id == tg_id)
    u = (await db.execute(stmt)).scalar_one_or_none()
    await state.clear()
    ai_enabled = bool(await cfg_service.get_raw("ai.enabled", True))
    if not u:
        await message.answer("❌ المستخدم غير موجود.", reply_markup=build_inbot_admin_panel_keyboard(ai_enabled=ai_enabled))
        return
    if u.role == UserRole.OWNER:
        await message.answer("⛔ لا يمكن حذف أو تعطيل مالك البوت الأساسي.", reply_markup=build_inbot_admin_panel_keyboard(ai_enabled=ai_enabled))
        return
    u.is_active = False
    await db.flush()
    await message.answer(
        f"🚫 تم تعطيل صلاحية المستخدم <code>{tg_id}</code> فوراً.",
        reply_markup=build_inbot_admin_panel_keyboard(ai_enabled=ai_enabled),
        parse_mode=ParseMode.HTML,
    )


@admin_router.callback_query(F.data == "adm:ai_toggle")
async def cb_adm_ai_toggle(
    callback: CallbackQuery,
    auth_user: TelegramUser,
    cfg_service: DynamicConfigService,
) -> None:
    if not _is_admin_or_owner(auth_user):
        await callback.answer("⛔ غير مصرح", show_alert=True)
        return
    current = bool(await cfg_service.get_raw("ai.enabled", True))
    new_state = not current
    await cfg_service.set_config("ai.enabled", new_state, actor=auth_user.username or str(auth_user.telegram_id))
    await callback.answer("تم تحديث حالة خدمة Gemini AI")
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=build_inbot_admin_panel_keyboard(ai_enabled=new_state))


@admin_router.callback_query(F.data == "adm:ai_model")
async def cb_adm_ai_model_switch(
    callback: CallbackQuery,
    auth_user: TelegramUser,
    cfg_service: DynamicConfigService,
) -> None:
    if not _is_admin_or_owner(auth_user):
        await callback.answer("⛔ غير مصرح", show_alert=True)
        return
    curr_model = str(await cfg_service.get_raw("ai.model_name", "gemini-2.5-flash"))
    next_model = "gemini-2.5-pro" if curr_model == "gemini-2.5-flash" else "gemini-2.5-flash"
    await cfg_service.set_config("ai.model_name", next_model, actor=auth_user.username or str(auth_user.telegram_id))
    await callback.answer(f"🧠 تم التبديل إلى {next_model}", show_alert=True)


@admin_router.callback_query(F.data == "adm:ai_key")
async def cb_adm_ai_key_prompt(callback: CallbackQuery, state: FSMContext, auth_user: TelegramUser) -> None:
    if auth_user.role != UserRole.OWNER:
        await callback.answer("⛔ تغيير مفتاح API متاح للمالك (OWNER) فقط.", show_alert=True)
        return
    await state.set_state(InBotAdminStates.updating_gemini_key)
    if callback.message:
        await callback.message.answer(
            "🔑 أرسل <b>مفتاح Gemini API الجديد</b> الآن (سيتم تشفيره بـ Fernet وحذف رسالتك فوراً لحماية المفتاح):",
            parse_mode=ParseMode.HTML,
        )
    await callback.answer()


@admin_router.message(InBotAdminStates.updating_gemini_key, F.text)
async def handle_adm_ai_key_save(
    message: Message,
    state: FSMContext,
    auth_user: TelegramUser,
    cfg_service: DynamicConfigService,
) -> None:
    new_key = (message.text or "").strip()
    try:
        await message.delete()  # Delete sensitive key message from chat history immediately
    except Exception:
        pass
    await cfg_service.set_config("ai.gemini_api_key", new_key, actor=auth_user.username or str(auth_user.telegram_id))
    await state.clear()
    ai_enabled = bool(await cfg_service.get_raw("ai.enabled", True))
    await message.answer(
        "🔐 تم تشفير وحفظ مفتاح Gemini API الجديد في قاعدة البيانات وحذف رسالتك من الدردشة للأمان.",
        reply_markup=build_inbot_admin_panel_keyboard(ai_enabled=ai_enabled),
    )


@admin_router.callback_query(F.data == "adm:broadcast")
async def cb_adm_broadcast_prompt(callback: CallbackQuery, state: FSMContext, auth_user: TelegramUser) -> None:
    if not _is_admin_or_owner(auth_user):
        await callback.answer("⛔ غير مصرح", show_alert=True)
        return
    await state.set_state(InBotAdminStates.sending_broadcast_text)
    if callback.message:
        await callback.message.answer("📢 أرسل <b>نص الرسالة الجماعية</b> ليتم إرسالها لجميع المستخدمين المصرح لهم:", parse_mode=ParseMode.HTML)
    await callback.answer()


@admin_router.message(InBotAdminStates.sending_broadcast_text, F.text)
async def handle_adm_broadcast_queue(
    message: Message,
    state: FSMContext,
    db: AsyncSession,
    auth_user: TelegramUser,
    cfg_service: DynamicConfigService,
) -> None:
    job = BroadcastJob(
        created_by=auth_user.username or str(auth_user.telegram_id),
        message_text=message.text.strip(),
        rate_limit_per_sec=15,
        status=BroadcastStatus.PENDING,
    )
    db.add(job)
    await db.flush()
    await state.clear()
    ai_enabled = bool(await cfg_service.get_raw("ai.enabled", True))
    await message.answer(
        "✅ تمت جدولة الرسالة الجماعية وسيقوم عامل البث بإرسالها لجميع المستخدمين الآن.",
        reply_markup=build_inbot_admin_panel_keyboard(ai_enabled=ai_enabled),
    )


@admin_router.callback_query(F.data == "adm:backup")
async def cb_adm_create_and_send_backup(
    callback: CallbackQuery,
    db: AsyncSession,
    auth_user: TelegramUser,
) -> None:
    if not _is_admin_or_owner(auth_user):
        await callback.answer("⛔ غير مصرح", show_alert=True)
        return
    ws = WorkspaceService(db)
    rec = await ws.create_verified_backup(created_by=auth_user.username or str(auth_user.telegram_id), backup_type="manual")
    raw_bytes = Path(rec.file_path).read_bytes()
    doc = BufferedInputFile(raw_bytes, filename=rec.file_name)
    if callback.message:
        await callback.message.answer_document(
            doc,
            caption=(
                f"💾 <b>نسخة احتياطية كاملة وموثقة</b>\n"
                f"🔐 SHA-256: <code>{rec.sha256_checksum[:32]}...</code>\n"
                f"📦 الحجم: {rec.file_size_bytes} بايت"
            ),
            parse_mode=ParseMode.HTML,
        )
    await callback.answer("تم إنشاء النسخة الاحتياطية")
