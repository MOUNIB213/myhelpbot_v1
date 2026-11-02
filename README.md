# 🤖 ملفات بوت المساعد الشخصي الذكي الخاص عبر تلغرام (نسخة البوت فقط — بدون واجهة ويب)
**Private Telegram Assistant & Enterprise Vault (Pure Python 3.12 + aiogram 3.x + PostgreSQL + Gemini AI)**

هذه الحزمة مخصصة **حصرياً لملفات البوت وقاعدة البيانات** دون أي ملفات موقع أو واجهات ويب خارجية، مع تضمين **لوحة تحكم الأدمن كاملةً داخل البوت نفسه** عبر الأمر `/admin` أو زر `⚙️ Settings`.

## 1. هيكل ملفات البوت (Project Structure)

- `botmi.py` — الملف الرئيسي لتشغيل البوت (`aiogram 3.x`) وعامل التذكيرات والإرسال الجماعي الخلفي.
- `requirements.txt` — مكتبات البوت فقط (`aiogram`, `sqlalchemy`, `asyncpg`, `alembic`, `redis`, `google-genai`, `cryptography`, `argon2-cffi`).
- `.env.example` — نموذج متغيرات البيئة لتشغيل البوت.
- `Dockerfile` و `docker-compose.yml` — تشغيل البوت مع `PostgreSQL 16` و `Redis 7` مباشرة.
- `app/core/` — الإعدادات (`config.py`)، التشفير والأمان (`security.py`)، قاعدة البيانات (`database.py`)، و `redis.py`.
- `app/models/entities.py` — جداول قاعدة البيانات (`TelegramUser`, `DynamicConfig`, `AISession`, `AIMessage`, `AIUsageQuota`, `Project`, `ProjectFile`, `ImportantLink`, `Note`, `TaskItem`, `Reminder`, `FavoriteItem`, `BroadcastJob`, `BackupRecord`).
- `app/services/` — خدمات الذكاء الاصطناعي `Gemini`، خزنة المشاريع وقناة التخزين الخاصة، الروابط والملاحظات والمهام، ونظام الصلاحيات والإعدادات الديناميكية.
- `app/bot/middlewares.py` — حارس الصلاحيات (`Zero-Trust RBAC`) الذي يمنع غير المصرح لهم ويعرض الرسالة الإلزامية مع زر التواصل مع المالك.
- `app/bot/handlers.py` — معالجات الأقسام العشرة (الذكاء الاصطناعي، المشاريع، الروابط، الملاحظات، المهام، التذكيرات، المفضلة، البحث الشامل، الحساب).
- `app/bot/admin_handlers.py` — **لوحة تحكم الأدمن المدمجة داخل البوت (`/admin`)** لإدارة المستخدمين، تفعيل/إيقاف Gemini، تحديث مفتاح API بأمان، الإرسال الجماعي، وإنشاء النسخ الاحتياطية وتنزيلها كملف داخل محادثة تلغرام.
- `alembic/` — ملفات ترقية قاعدة البيانات (`Database Migrations`).
- `tests/test_enterprise_suite.py` — اختبارات التحقق والأمان.

## 2. طريقة التشغيل على VPS

```bash
cp .env.example .env
nano .env
docker compose up -d --build
```
