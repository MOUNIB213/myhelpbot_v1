import json
from datetime import datetime, timedelta, timezone
from aiogram import Bot, F, Router
from aiogram.enums import ChatAction, ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards import (
    build_ai_assistant_keyboard,
    build_confirmation_keyboard,
    build_links_menu_keyboard,
    build_main_menu_keyboard,
    build_project_detail_keyboard,
    build_projects_menu_keyboard,
)
from app.bot.states import (
    AIChatStates,
    GlobalSearchStates,
    LinkVaultStates,
    NoteStates,
    ProjectVaultStates,
    ReminderStates,
    TaskStates,
)
from app.models.entities import (
    AISession,
    FavoriteItem,
    ImportantLink,
    Note,
    Project,
    Reminder,
    TaskItem,
    TaskPriority,
    TelegramUser,
)
from app.services.ai_service import GeminiAIService
from app.services.dynamic_config_service import DynamicConfigService
from app.services.project_vault_service import ProjectVaultService
from app.services.workspace_service import WorkspaceService

router = Router(name="main_private_assistant_router")


# --- 1. /start & Main Navigation ---
@router.message(CommandStart())
async def cmd_start(
    message: Message,
    state: FSMContext,
    auth_user: TelegramUser,
    cfg_service: DynamicConfigService,
) -> None:
    await state.clear()
    welcome = await cfg_service.get_raw(
        "bot.welcome_message",
        "مرحباً بك في مساعدك الشخصي الذكي 🌟\nاختر القسم المطلوب من القائمة أدناه:",
    )
    kb = build_main_menu_keyboard(auth_user.allowed_sections)
    await message.answer(
        f"👋 أهلاً بك <b>{auth_user.full_name}</b>\n\n{welcome}",
        reply_markup=kb,
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(F.data == "nav:home")
async def cb_nav_home(
    callback: CallbackQuery,
    state: FSMContext,
    auth_user: TelegramUser,
    cfg_service: DynamicConfigService,
) -> None:
    await state.clear()
    welcome = await cfg_service.get_raw("bot.welcome_message", "القائمة الرئيسية للمساعد الذكي:")
    kb = build_main_menu_keyboard(auth_user.allowed_sections)
    if callback.message:
        await callback.message.edit_text(
            f"🏠 <b>القائمة الرئيسية</b>\n\n{welcome}",
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
        )
    await callback.answer()


# --- 2. AI Assistant (Gemini) ---
@router.callback_query(F.data == "nav:ai")
async def cb_nav_ai(
    callback: CallbackQuery,
    state: FSMContext,
    db: AsyncSession,
    auth_user: TelegramUser,
    cfg_service: DynamicConfigService,
) -> None:
    ai_svc = GeminiAIService(db, cfg_service)
    session = await ai_svc.get_or_create_active_session(auth_user)
    await state.set_state(AIChatStates.chatting)
    await state.update_data(active_session_code=session.session_code)

    text = (
        f"🤖 <b>قسم الذكاء الاصطناعي (Gemini AI)</b>\n\n"
        f"🆔 كود الجلسة النشطة: <code>{session.session_code}</code>\n"
        f"🧠 النموذج المعتمد: <code>{session.model_name}</code>\n"
        f"💬 أرسل سؤالك أو الكود البرمجي الآن مباشرة، أو استخدم <code>/end</code> لإنهاء الجلسة."
    )
    if callback.message:
        await callback.message.edit_text(
            text,
            reply_markup=build_ai_assistant_keyboard(session.session_code),
            parse_mode=ParseMode.HTML,
        )
    await callback.answer()


@router.callback_query(F.data == "ai:new")
async def cb_ai_new_session(
    callback: CallbackQuery,
    state: FSMContext,
    db: AsyncSession,
    auth_user: TelegramUser,
    cfg_service: DynamicConfigService,
) -> None:
    ai_svc = GeminiAIService(db, cfg_service)
    session = await ai_svc.start_new_session(auth_user)
    await state.set_state(AIChatStates.chatting)
    await state.update_data(active_session_code=session.session_code)
    if callback.message:
        await callback.message.edit_text(
            f"🟢 <b>تم بدء جلسة ذكاء اصطناعي جديدة بنجاح!</b>\n"
            f"🆔 كود الجلسة: <code>{session.session_code}</code>\n\n"
            f"أرسل رسالتك الأولى الآن:",
            reply_markup=build_ai_assistant_keyboard(session.session_code),
            parse_mode=ParseMode.HTML,
        )
    await callback.answer("تم فتح جلسة جديدة")


@router.message(Command("end"))
async def cmd_end_ai_session(
    message: Message,
    state: FSMContext,
    db: AsyncSession,
    auth_user: TelegramUser,
    cfg_service: DynamicConfigService,
) -> None:
    parts = (message.text or "").split(maxsplit=1)
    code_arg = parts[1].strip() if len(parts) > 1 else None
    ai_svc = GeminiAIService(db, cfg_service)
    ended = await ai_svc.end_session_by_code_or_active(auth_user, code_arg)
    await state.clear()
    if ended:
        await message.answer(
            f"🔴 تم إنهاء جلسة الذكاء الاصطناعي <code>{ended.session_code}</code> بنجاح.",
            reply_markup=build_ai_assistant_keyboard(None),
            parse_mode=ParseMode.HTML,
        )
    else:
        await message.answer("⚠️ لا توجد جلسة نشطة حالياً لإنهائها.", reply_markup=build_ai_assistant_keyboard(None))


@router.callback_query(F.data == "ai:end_active")
async def cb_ai_end_active(
    callback: CallbackQuery,
    state: FSMContext,
    db: AsyncSession,
    auth_user: TelegramUser,
    cfg_service: DynamicConfigService,
) -> None:
    ai_svc = GeminiAIService(db, cfg_service)
    ended = await ai_svc.end_session_by_code_or_active(auth_user, None)
    await state.clear()
    msg_txt = (
        f"🔴 تم إغلاق الجلسة <code>{ended.session_code}</code> وحفظ السجل."
        if ended
        else "ℹ️ لا توجد جلسة مفتوحة حالياً."
    )
    if callback.message:
        await callback.message.edit_text(msg_txt, reply_markup=build_ai_assistant_keyboard(None), parse_mode=ParseMode.HTML)
    await callback.answer()


@router.callback_query(F.data == "ai:end_by_code")
async def cb_ai_end_by_code_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AIChatStates.entering_end_code)
    if callback.message:
        await callback.message.answer("🔢 أرسل كود الجلسة التي ترغب في إنهائها (مثال: <code>AIS-2026-A1B2C3</code>):", parse_mode=ParseMode.HTML)
    await callback.answer()


@router.message(AIChatStates.entering_end_code)
async def handle_ai_end_code_input(
    message: Message,
    state: FSMContext,
    db: AsyncSession,
    auth_user: TelegramUser,
    cfg_service: DynamicConfigService,
) -> None:
    code = (message.text or "").strip().upper()
    ai_svc = GeminiAIService(db, cfg_service)
    ended = await ai_svc.end_session_by_code_or_active(auth_user, code)
    await state.clear()
    if ended:
        await message.answer(
            f"✅ تم إنهاء الجلسة <code>{ended.session_code}</code> بنجاح.",
            reply_markup=build_ai_assistant_keyboard(None),
            parse_mode=ParseMode.HTML,
        )
    else:
        await message.answer("❌ لم يتم العثور على جلسة بهذا الكود.", reply_markup=build_ai_assistant_keyboard(None))


@router.message(AIChatStates.chatting, F.text)
async def handle_ai_conversation_turn(
    message: Message,
    state: FSMContext,
    bot: Bot,
    db: AsyncSession,
    auth_user: TelegramUser,
    cfg_service: DynamicConfigService,
) -> None:
    data = await state.get_data()
    session_code = data.get("active_session_code")

    # Show typing indicator during Gemini processing
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)

    ai_svc = GeminiAIService(db, cfg_service)
    result = await ai_svc.send_Prompt(
        user=auth_user,
        user_prompt=message.text or "",
        session_code=session_code,
    )

    chunks = result.get("chunks", [""])
    for idx, chunk in enumerate(chunks):
        is_last = idx == len(chunks) - 1
        footer = ""
        if is_last and result.get("ok"):
            footer = (
                f"\n\n—\n🆔 <code>{result['session_code']}</code> | "
                f"🪙 {result['tokens_used']} توكن | "
                f"⏱️ {result['latency_ms']}ms"
            )
        try:
            await message.answer(
                chunk + footer,
                reply_markup=build_ai_assistant_keyboard(result.get("session_code")) if is_last else None,
                parse_mode=ParseMode.HTML if not ("```" in chunk) else None,
            )
        except Exception:
            await message.answer(chunk + footer)


# --- 3. Project Vault & Private Storage Channel ---
@router.callback_query(F.data == "nav:projects")
async def cb_nav_projects(
    callback: CallbackQuery,
    state: FSMContext,
    db: AsyncSession,
    auth_user: TelegramUser,
    cfg_service: DynamicConfigService,
) -> None:
    await state.clear()
    vault = ProjectVaultService(db, cfg_service)
    projects, total = await vault.search_projects(auth_user, offset=0, limit=6)
    total_pages = max(1, (total + 5) // 6)
    kb = build_projects_menu_keyboard(page=0, total_pages=total_pages, projects=projects)
    if callback.message:
        await callback.message.edit_text(
            f"📁 <b>خزنة المشاريع (Project Vault)</b>\n"
            f"إجمالي المشاريع المحفوظة: <b>{total}</b>\n\n"
            f"اختر مشروعاً لعرض ملفاته أو أنشئ مشروعاً جديداً:",
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
        )
    await callback.answer()


@router.callback_query(F.data == "prj:create")
async def cb_prj_create_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ProjectVaultStates.entering_name)
    if callback.message:
        await callback.message.answer("📁 أدخل <b>اسم المشروع الجديد</b>:", parse_mode=ParseMode.HTML)
    await callback.answer()


@router.message(ProjectVaultStates.entering_name, F.text)
async def handle_prj_name(message: Message, state: FSMContext) -> None:
    await state.update_data(prj_name=message.text.strip())
    await state.set_state(ProjectVaultStates.entering_category)
    await message.answer("🏷️ أدخل <b>تصنيف المشروع</b> (مثال: تطوير ويب، ذكاء اصطناعي، عقود):", parse_mode=ParseMode.HTML)


@router.message(ProjectVaultStates.entering_category, F.text)
async def handle_prj_category(message: Message, state: FSMContext) -> None:
    await state.update_data(prj_category=message.text.strip())
    await state.set_state(ProjectVaultStates.entering_description)
    await message.answer("📝 أدخل <b>وصف المشروع وملاحظاته</b>:", parse_mode=ParseMode.HTML)


@router.message(ProjectVaultStates.entering_description, F.text)
async def handle_prj_description_finalize(
    message: Message,
    state: FSMContext,
    db: AsyncSession,
    auth_user: TelegramUser,
    cfg_service: DynamicConfigService,
) -> None:
    data = await state.get_data()
    vault = ProjectVaultService(db, cfg_service)
    project = await vault.create_project(
        owner=auth_user,
        name=data["prj_name"],
        category=data.get("prj_category", "عام"),
        description=message.text.strip(),
    )
    await state.clear()
    kb = build_project_detail_keyboard(project.id, project.code, [])
    await message.answer(
        f"✅ <b>تم إنشاء المشروع بنجاح!</b>\n\n"
        f"🆔 كود المشروع الفريد: <code>{project.code}</code>\n"
        f"📌 الاسم: <b>{project.name}</b>\n"
        f"🏷️ التصنيف: {project.category}\n\n"
        f"يمكنك الآن رفع الملفات ليتم أرشفتها في قناة التخزين الخاصة تلقائياً:",
        reply_markup=kb,
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(F.data.startswith("prj:upload:"))
async def cb_prj_upload_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    project_id = int(callback.data.split(":")[2])
    await state.set_state(ProjectVaultStates.uploading_files)
    await state.update_data(upload_project_id=project_id)
    if callback.message:
        await callback.message.answer(
            "📤 <b>أرسل الآن الملفات أو الصور أو الفيديوهات أو المستندات</b> (يمكنك إرسال عدة ملفات متتالية).\n"
            "سيقوم البوت بتحويلها إلى قناة التخزين الخاصة وحفظ معرفاتها في قاعدة البيانات.",
            parse_mode=ParseMode.HTML,
        )
    await callback.answer()


@router.message(ProjectVaultStates.uploading_files, F.document | F.photo | F.video | F.audio)
async def handle_prj_file_upload_to_storage_channel(
    message: Message,
    state: FSMContext,
    bot: Bot,
    db: AsyncSession,
    auth_user: TelegramUser,
    cfg_service: DynamicConfigService,
) -> None:
    data = await state.get_data()
    project_id = int(data["upload_project_id"])
    storage_channel_id = int(await cfg_service.get_raw("storage.channel_id", -1001234567890))

    vault = ProjectVaultService(db, cfg_service)
    project = await vault.get_project_authorized(auth_user, project_id=project_id)
    if project is None:
        await message.answer("❌ المشروع غير موجود.")
        return

    # Extract file metadata
    if message.document:
        f_name = message.document.file_name or f"doc_{message.message_id}"
        f_type = "document"
        mime = message.document.mime_type or "application/octet-stream"
        f_size = message.document.file_size or 0
        f_id = message.document.file_id
        f_uid = message.document.file_unique_id
    elif message.photo:
        largest = message.photo[-1]
        f_name = f"photo_{message.message_id}.jpg"
        f_type = "photo"
        mime = "image/jpeg"
        f_size = largest.file_size or 0
        f_id = largest.file_id
        f_uid = largest.file_unique_id
    elif message.video:
        f_name = message.video.file_name or f"video_{message.message_id}.mp4"
        f_type = "video"
        mime = message.video.mime_type or "video/mp4"
        f_size = message.video.file_size or 0
        f_id = message.video.file_id
        f_uid = message.video.file_unique_id
    else:
        f_name = message.audio.file_name or f"audio_{message.message_id}.mp3"
        f_type = "audio"
        mime = message.audio.mime_type or "audio/mpeg"
        f_size = message.audio.file_size or 0
        f_id = message.audio.file_id
        f_uid = message.audio.file_unique_id

    # Step 1: Send/copy file to Private Telegram Storage Channel
    caption_meta = f"📦 [{project.code}] {project.name} | File: {f_name} | By: {auth_user.telegram_id}"
    try:
        channel_msg = await bot.copy_message(
            chat_id=storage_channel_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
            caption=caption_meta[:1024],
        )
        storage_msg_id = channel_msg.message_id
    except Exception as exc:
        await message.answer(
            f"⚠️ تعذر الإرسال إلى قناة التخزين الخاصة (تأكد أن البوت مشرف Admin في القناة <code>{storage_channel_id}</code>).\n"
            f"التفاصيل: {exc}",
            parse_mode=ParseMode.HTML,
        )
        return

    # Step 2 & 3: Save message_id and telegram_file_id in PostgreSQL linked to Project ID
    pf = await vault.register_channel_stored_file(
        requester=auth_user,
        project_id=project.id,
        file_name=f_name,
        file_type=f_type,
        mime_type=mime,
        file_size_bytes=f_size,
        telegram_file_id=f_id,
        telegram_unique_id=f_uid,
        storage_channel_id=storage_channel_id,
        storage_message_id=storage_msg_id,
        caption=message.caption or "",
    )

    await message.answer(
        f"✅ <b>تم أرشفة الملف في قناة التخزين بنجاح!</b>\n"
        f"📄 الاسم: <code>{pf.file_name}</code>\n"
        f"🔗 مشروع: <code>{project.code}</code>\n"
        f"📨 معرف رسالة القناة: <code>#{pf.storage_message_id}</code>",
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(F.data.startswith("prj:getfile:"))
async def cb_prj_retrieve_file_from_channel(
    callback: CallbackQuery,
    bot: Bot,
    db: AsyncSession,
    auth_user: TelegramUser,
    cfg_service: DynamicConfigService,
) -> None:
    # Steps 4, 5, 6: Verify permission -> Retrieve from Storage Channel without re-uploading
    file_id = int(callback.data.split(":")[2])
    vault = ProjectVaultService(db, cfg_service)
    try:
        pf = await vault.authorize_file_retrieval(auth_user, file_id=file_id)
    except PermissionError as p_err:
        await callback.answer(str(p_err), show_alert=True)
        return
    except ValueError as v_err:
        await callback.answer(str(v_err), show_alert=True)
        return

    if not callback.message:
        return

    try:
        # Copy directly from private storage channel using stored message_id (zero re-upload)
        await bot.copy_message(
            chat_id=callback.message.chat.id,
            from_chat_id=pf.storage_channel_id,
            message_id=pf.storage_message_id,
        )
        await callback.answer("📥 تم استرجاع الملف من قناة التخزين")
    except Exception:
        # Fallback to cached telegram_file_id if channel message was manually deleted
        try:
            await bot.send_document(
                chat_id=callback.message.chat.id,
                document=pf.telegram_file_id,
                caption=f"📁 {pf.file_name} (استرجاع عبر File ID)",
            )
            await callback.answer("📥 تم استرجاع الملف")
        except Exception:
            await vault.mark_file_missing_in_channel(pf.id)
            await callback.answer("❌ تعذر العثور على الملف في قناة التخزين؛ تم تعليم السجل كمفقود.", show_alert=True)


@router.callback_query(F.data == "prj:export")
async def cb_prj_export_json(
    callback: CallbackQuery,
    db: AsyncSession,
    auth_user: TelegramUser,
    cfg_service: DynamicConfigService,
) -> None:
    vault = ProjectVaultService(db, cfg_service)
    manifest = await vault.export_projects_manifest(auth_user)
    raw_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    doc = BufferedInputFile(raw_bytes, filename=f"projects_export_{auth_user.telegram_id}.json")
    if callback.message:
        await callback.message.answer_document(doc, caption="📤 تصدير شامل لبيانات مشاريعك وملفاتها المؤرشفة.")
    await callback.answer()


# --- 4. Important Links, Notes, Tasks, Reminders, Global Search, Account ---
@router.callback_query(F.data == "nav:links")
async def cb_nav_links(
    callback: CallbackQuery,
    db: AsyncSession,
    auth_user: TelegramUser,
) -> None:
    ws = WorkspaceService(db)
    links, total = await ws.list_links(auth_user, offset=0, limit=6)
    total_pages = max(1, (total + 5) // 6)
    kb = build_links_menu_keyboard(links, page=0, total_pages=total_pages)
    if callback.message:
        await callback.message.edit_text(
            f"🔗 <b>إدارة الروابط المهمة (Important Links)</b>\n"
            f"إجمالي الروابط: <b>{total}</b>",
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
        )
    await callback.answer()


@router.callback_query(F.data == "nav:search")
async def cb_nav_global_search(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(GlobalSearchStates.entering_query)
    if callback.message:
        await callback.message.answer("🔍 <b>البحث الشامل (Global Search)</b>\nأرسل كلمة البحث للبحث في المشاريع والروابط والملاحظات والمهام:", parse_mode=ParseMode.HTML)
    await callback.answer()


@router.message(GlobalSearchStates.entering_query, F.text)
async def handle_global_search_query(
    message: Message,
    state: FSMContext,
    db: AsyncSession,
    auth_user: TelegramUser,
) -> None:
    ws = WorkspaceService(db)
    res = await ws.global_search(auth_user, message.text or "")
    await state.clear()
    lines = ["🔍 <b>نتائج البحث الشامل:</b>\n"]
    lines.append(f"📁 <b>المشاريع ({len(res['projects'])}):</b>")
    for p in res["projects"]:
        lines.append(f"  • <code>{p['code']}</code> — {p['name']} ({p['category']})")
    lines.append(f"\n🔗 <b>الروابط ({len(res['links'])}):</b>")
    for l in res["links"]:
        lines.append(f"  • <code>{l['code']}</code> — <a href='{l['url']}'>{l['title']}</a>")
    lines.append(f"\n📝 <b>الملاحظات ({len(res['notes'])}):</b>")
    for n in res["notes"]:
        lines.append(f"  • {n['title']}")
    lines.append(f"\n✅ <b>المهام ({len(res['tasks'])}):</b>")
    for t in res["tasks"]:
        lines.append(f"  • {t['title']} [{t['status']}]")

    await message.answer(
        "\n".join(lines),
        reply_markup=build_main_menu_keyboard(auth_user.allowed_sections),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


@router.callback_query(F.data == "nav:account")
async def cb_nav_account(
    callback: CallbackQuery,
    db: AsyncSession,
    auth_user: TelegramUser,
) -> None:
    prj_count = int((await db.execute(select(func.count(Project.id)).where(Project.owner_id == auth_user.id))).scalar_one())
    lnk_count = int((await db.execute(select(func.count(ImportantLink.id)).where(ImportantLink.user_id == auth_user.id))).scalar_one())
    ai_count = int((await db.execute(select(func.count(AISession.id)).where(AISession.user_id == auth_user.id))).scalar_one())

    info = (
        f"👤 <b>ملفي الشخصي وإحصائيات الاستخدام</b>\n\n"
        f"🆔 معرف تلغرام: <code>{auth_user.telegram_id}</code>\n"
        f"🛡️ الصلاحية: <b>{auth_user.role.value}</b>\n"
        f"📅 تاريخ الانضمام: <code>{auth_user.joined_at.strftime('%Y-%m-%d') if auth_user.joined_at else 'N/A'}</code>\n\n"
        f"📊 <b>إحصائياتك:</b>\n"
        f"• المشاريع المحفوظة: <b>{prj_count}</b>\n"
        f"• الروابط المهمة: <b>{lnk_count}</b>\n"
        f"• جلسات الذكاء الاصطناعي: <b>{ai_count}</b>\n"
        f"• الحد اليومي لطلبات Gemini: <b>{auth_user.daily_ai_requests_limit} طلب/يوم</b>\n"
        f"• الحد اليومي للتوكنات: <b>{auth_user.daily_ai_tokens_limit:,} توكن/يوم</b>"
    )
    if callback.message:
        await callback.message.edit_text(
            info,
            reply_markup=build_main_menu_keyboard(auth_user.allowed_sections),
            parse_mode=ParseMode.HTML,
        )
    await callback.answer()
