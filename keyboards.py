from typing import List, Optional
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Technical Note on Telegram Button Styling & Colors:
# Official Telegram Bot API InlineKeyboardButton does NOT allow arbitrary CSS hex colors
# on standard callback_data buttons across all clients. Instead, we combine:
# 1. Semantic Unicode Emoji Status Indicators (🟢, 🔴, 🔵, ⭐, ⚠️) compatible with 100% of clients.
# 2. Native Telegram Bot API ReplyKeyboardMarkup / WebAppInfo / LoginUrl & CopyTextButton
#    where supported in modern Telegram Bot API 7.x/8.x releases, with graceful fallback.


def build_unauthorized_keyboard(owner_contact_url: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="💬 تواصل مع مالك البوت (طلب صلاحية الوصول)",
            url=owner_contact_url,
        )
    )
    return builder.as_markup()


def build_main_menu_keyboard(allowed_sections: Optional[List[str]] = None) -> InlineKeyboardMarkup:
    sections = set(allowed_sections or [
        "ai", "projects", "links", "notes", "tasks",
        "reminders", "favorites", "search", "account", "settings"
    ])
    builder = InlineKeyboardBuilder()

    if "ai" in sections:
        builder.button(text="🤖 AI Assistant", callback_data="nav:ai")
    if "projects" in sections:
        builder.button(text="📁 My Projects", callback_data="nav:projects")
    if "links" in sections:
        builder.button(text="🔗 Important Links", callback_data="nav:links")
    if "notes" in sections:
        builder.button(text="📝 My Notes", callback_data="nav:notes")
    if "tasks" in sections:
        builder.button(text="✅ My Tasks", callback_data="nav:tasks")
    if "reminders" in sections:
        builder.button(text="⏰ Reminders", callback_data="nav:reminders")
    if "favorites" in sections:
        builder.button(text="⭐ Favorites", callback_data="nav:favorites")
    if "search" in sections:
        builder.button(text="🔍 Global Search", callback_data="nav:search")
    if "account" in sections:
        builder.button(text="👤 My Account", callback_data="nav:account")
    if "settings" in sections:
        builder.button(text="⚙️ Settings", callback_data="nav:settings")

    builder.adjust(2)
    return builder.as_markup()


def build_inbot_admin_panel_keyboard(ai_enabled: bool = True) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📊 إحصائيات النظام الشاملة", callback_data="adm:stats"),
        InlineKeyboardButton(text="👥 إدارة المستخدمين والصلاحيات", callback_data="adm:users"),
    )
    builder.row(
        InlineKeyboardButton(text="➕ إضافة مستخدم مصرح له", callback_data="adm:user_add"),
        InlineKeyboardButton(text="🚫 حذف / تعطيل مستخدم", callback_data="adm:user_del"),
    )
    ai_status_label = "⏸️ إيقاف خدمة Gemini AI" if ai_enabled else "🟢 تشغيل خدمة Gemini AI"
    builder.row(
        InlineKeyboardButton(text=ai_status_label, callback_data="adm:ai_toggle"),
        InlineKeyboardButton(text="🔑 تحديث مفتاح Gemini API", callback_data="adm:ai_key"),
    )
    builder.row(
        InlineKeyboardButton(text="🧠 تبديل نموذج Gemini (Flash/Pro)", callback_data="adm:ai_model"),
        InlineKeyboardButton(text="⚙️ الإعدادات الديناميكية للبوت", callback_data="adm:configs"),
    )
    builder.row(
        InlineKeyboardButton(text="📢 إرسال رسالة جماعية (Broadcast)", callback_data="adm:broadcast"),
        InlineKeyboardButton(text="💾 إنشاء وتنزيل نسخة احتياطية", callback_data="adm:backup"),
    )
    builder.row(InlineKeyboardButton(text="🔙 الرجوع للقائمة الرئيسية", callback_data="nav:home"))
    return builder.as_markup()


def build_ai_assistant_keyboard(active_session_code: Optional[str] = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🟢 بدء محادثة جديدة", callback_data="ai:new"),
        InlineKeyboardButton(text="🔴 إنهاء المحادثة الحالية", callback_data="ai:end_active"),
    )
    builder.row(
        InlineKeyboardButton(text="🔢 إنهاء محادثة بكود الجلسة", callback_data="ai:end_by_code"),
        InlineKeyboardButton(text="📜 سجل المحادثات السابقة", callback_data="ai:history:0"),
    )
    if active_session_code:
        builder.row(
            InlineKeyboardButton(
                text=f"🗑️ حذف الجلسة ({active_session_code})",
                callback_data=f"ai:del_confirm:{active_session_code}",
            )
        )
    builder.row(InlineKeyboardButton(text="🔙 الرجوع للقائمة الرئيسية", callback_data="nav:home"))
    return builder.as_markup()


def build_projects_menu_keyboard(page: int = 0, total_pages: int = 1, projects: Optional[list] = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="➕ إضافة مشروع جديد", callback_data="prj:create"),
        InlineKeyboardButton(text="🔍 بحث بالكود أو الاسم", callback_data="prj:search"),
    )
    builder.row(
        InlineKeyboardButton(text="🏷️ تصفح حسب التصنيف", callback_data="prj:categories"),
        InlineKeyboardButton(text="📤 تصدير بيانات المشاريع", callback_data="prj:export"),
    )

    if projects:
        for p in projects:
            builder.row(
                InlineKeyboardButton(
                    text=f"📁 [{p.code}] {p.name} ({len(p.files)} ملف)",
                    callback_data=f"prj:view:{p.id}",
                )
            )

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️ السابق", callback_data=f"prj:page:{page - 1}"))
    nav_row.append(InlineKeyboardButton(text=f"📄 {page + 1}/{max(1, total_pages)}", callback_data="noop"))
    if page + 1 < total_pages:
        nav_row.append(InlineKeyboardButton(text="التالي ➡️", callback_data=f"prj:page:{page + 1}"))
    builder.row(*nav_row)

    builder.row(InlineKeyboardButton(text="🔙 الرجوع للقائمة الرئيسية", callback_data="nav:home"))
    return builder.as_markup()


def build_project_detail_keyboard(project_id: int, project_code: str, files: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📤 رفع وإرفاق ملفات للمشروع", callback_data=f"prj:upload:{project_id}"),
        InlineKeyboardButton(text="⭐ إضافة/إزالة من المفضلة", callback_data=f"fav:toggle:project:{project_id}"),
    )
    for f in files:
        status_icon = "⚠️" if f.is_missing_in_channel else "📥"
        builder.row(
            InlineKeyboardButton(
                text=f"{status_icon} استرجاع: {f.file_name[:32]}",
                callback_data=f"prj:getfile:{f.id}",
            )
        )
    builder.row(
        InlineKeyboardButton(text="🕒 سجل التعديلات", callback_data=f"prj:revs:{project_id}"),
        InlineKeyboardButton(text="🗑️ حذف المشروع", callback_data=f"prj:del_confirm:{project_id}"),
    )
    builder.row(InlineKeyboardButton(text="🔙 الرجوع للمشاريع", callback_data="nav:projects"))
    return builder.as_markup()


def build_links_menu_keyboard(links: list, page: int = 0, total_pages: int = 1) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="➕ إضافة رابط مهم", callback_data="lnk:create"),
        InlineKeyboardButton(text="🔍 بحث في الروابط", callback_data="lnk:search"),
    )
    builder.row(
        InlineKeyboardButton(text="⭐ الروابط المفضلة", callback_data="lnk:favs"),
        InlineKeyboardButton(text="🏷️ ترتيب حسب التصنيف", callback_data="lnk:by_cat"),
    )
    for l in links:
        star = "⭐ " if l.is_favorite else "🔗 "
        builder.row(
            InlineKeyboardButton(text=f"{star}[{l.code}] {l.title}", callback_data=f"lnk:view:{l.id}"),
            InlineKeyboardButton(text="🌐 فتح مباشر", url=l.url),
        )
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️ السابق", callback_data=f"lnk:page:{page - 1}"))
    nav_row.append(InlineKeyboardButton(text=f"📄 {page + 1}/{max(1, total_pages)}", callback_data="noop"))
    if page + 1 < total_pages:
        nav_row.append(InlineKeyboardButton(text="التالي ➡️", callback_data=f"lnk:page:{page + 1}"))
    builder.row(*nav_row)
    builder.row(InlineKeyboardButton(text="🔙 الرجوع للقائمة الرئيسية", callback_data="nav:home"))
    return builder.as_markup()


def build_confirmation_keyboard(confirm_callback: str, cancel_callback: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ نعم، تأكيد التنفيذ", callback_data=confirm_callback),
        InlineKeyboardButton(text="❌ إلغاء وتراجع", callback_data=cancel_callback),
    )
    return builder.as_markup()
