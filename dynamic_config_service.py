import json
from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import get_settings
from app.core.security import SecretVaultCipher
from app.models.entities import ConfigAuditLog, DynamicConfig


DEFAULT_DYNAMIC_CONFIGS: List[Dict[str, Any]] = [
    {
        "key": "bot.name",
        "value": "مساعدك الشخصي الذكي — VaultBot",
        "value_type": "str",
        "category": "bot",
        "is_secret": False,
        "description": "اسم البوت المعروض في القوائم والرسائل",
    },
    {
        "key": "bot.description",
        "value": "مركز متكامل لإدارة المشاريع والملفات والروابط والمهام والذكاء الاصطناعي Gemini.",
        "value_type": "str",
        "category": "bot",
        "is_secret": False,
        "description": "وصف البوت الرسمي",
    },
    {
        "key": "bot.welcome_message",
        "value": "مرحباً بك في مساعدك الذكي الخاص 🌟\nاختر القسم المطلوب من القائمة التفاعلية أدناه:",
        "value_type": "str",
        "category": "bot",
        "is_secret": False,
        "description": "رسالة الترحيب عند إرسال /start للمصرح لهم",
    },
    {
        "key": "bot.unauthorized_message",
        "value": "هذا البوت خاص ولا تملك صلاحية استخدامه. يرجى التواصل مع مالك البوت للحصول على إمكانية الوصول.",
        "value_type": "str",
        "category": "security",
        "is_secret": False,
        "description": "الرسالة الإلزامية لغير المصرح لهم",
    },
    {
        "key": "bot.owner_telegram_id",
        "value": "0",
        "value_type": "int",
        "category": "security",
        "is_secret": False,
        "description": "المعرف الرقمي لمالك البوت على تلغرام (Telegram Owner ID)",
    },
    {
        "key": "bot.owner_contact_username",
        "value": "owner",
        "value_type": "str",
        "category": "security",
        "is_secret": False,
        "description": "معرف تلغرام للتواصل مع المالك عند الضغط على الزر",
    },
    {
        "key": "storage.channel_id",
        "value": "-1001234567890",
        "value_type": "int",
        "category": "storage",
        "is_secret": False,
        "description": "معرف قناة تلغرام الخاصة بتخزين ملفات المشاريع",
    },
    {
        "key": "storage.max_file_size_mb",
        "value": "50",
        "value_type": "int",
        "category": "storage",
        "is_secret": False,
        "description": "الحد الأقصى لحجم الملف الواحد بالميجابايت",
    },
    {
        "key": "ai.enabled",
        "value": "true",
        "value_type": "bool",
        "category": "ai",
        "is_secret": False,
        "description": "تفعيل أو إيقاف خدمة الذكاء الاصطناعي Gemini فوراً",
    },
    {
        "key": "ai.gemini_api_key",
        "value": "",
        "value_type": "str",
        "category": "ai",
        "is_secret": True,
        "description": "مفتاح Gemini API الرسمي (مشفر في قاعدة البيانات)",
    },
    {
        "key": "ai.model_name",
        "value": "gemini-2.5-flash",
        "value_type": "str",
        "category": "ai",
        "is_secret": False,
        "description": "نموذج Gemini المعتمد (gemini-2.5-flash / gemini-2.5-pro)",
    },
    {
        "key": "ai.system_instruction",
        "value": "أنت مساعد ذكي شخصي ومهندس برمجيات خبير. أجب بدقة ووضوح وباللغة العربية أو لغة السائل مع تنسيق الأكواد.",
        "value_type": "str",
        "category": "ai",
        "is_secret": False,
        "description": "التعليمات النظامية لـ Gemini",
    },
    {
        "key": "ai.temperature",
        "value": "0.7",
        "value_type": "float",
        "category": "ai",
        "is_secret": False,
        "description": "درجة الإبداع (Temperature) من 0.0 إلى 2.0",
    },
    {
        "key": "ai.default_daily_requests_limit",
        "value": "50",
        "value_type": "int",
        "category": "ai",
        "is_secret": False,
        "description": "الحد اليومي الافتراضي لطلبات الذكاء الاصطناعي لكل مستخدم",
    },
    {
        "key": "ai.default_daily_tokens_limit",
        "value": "100000",
        "value_type": "int",
        "category": "ai",
        "is_secret": False,
        "description": "الحد اليومي الافتراضي للتوكنات لكل مستخدم",
    },
    {
        "key": "sections.enabled_map",
        "value": json.dumps({
            "ai": True,
            "projects": True,
            "links": True,
            "notes": True,
            "tasks": True,
            "reminders": True,
            "favorites": True,
            "search": True,
            "account": True,
            "settings": True,
        }),
        "value_type": "json",
        "category": "sections",
        "is_secret": False,
        "description": "تفعيل أو تعطيل أقسام البوت على مستوى النظام بالكامل",
    },
    {
        "key": "backup.auto_daily_enabled",
        "value": "true",
        "value_type": "bool",
        "category": "backup",
        "is_secret": False,
        "description": "تفعيل النسخ الاحتياطي التلقائي المجدول يومياً",
    },
    {
        "key": "notifications.admin_alerts_enabled",
        "value": "true",
        "value_type": "bool",
        "category": "notifications",
        "is_secret": False,
        "description": "إرسال تنبيهات فورية للمالك عند محاولات الدخول غير المصرحة أو الأخطاء الحرجة",
    },
]


class DynamicConfigService:
    """
    Centralized Dynamic Configuration Manager with Fernet encryption for secrets,
    Redis hot-reload pub/sub notifications, and full audit trail.
    """

    def __init__(self, db: AsyncSession, redis_client: Optional[Any] = None):
        self.db = db
        self.redis = redis_client
        settings = get_settings()
        self.cipher = SecretVaultCipher(settings.MASTER_ENCRYPTION_KEY)
        self.settings = settings

    async def seed_defaults(self) -> None:
        for item in DEFAULT_DYNAMIC_CONFIGS:
            stmt = select(DynamicConfig).where(DynamicConfig.key == item["key"])
            existing = (await self.db.execute(stmt)).scalar_one_or_none()
            if existing is None:
                val = item["value"]
                if item["key"] == "bot.owner_telegram_id":
                    val = str(self.settings.TELEGRAM_OWNER_ID)
                elif item["key"] == "bot.owner_contact_username":
                    val = self.settings.TELEGRAM_OWNER_USERNAME
                elif item["key"] == "storage.channel_id":
                    val = str(self.settings.TELEGRAM_STORAGE_CHANNEL_ID)
                elif item["key"] == "ai.gemini_api_key" and self.settings.GEMINI_API_KEY:
                    val = self.cipher.encrypt(self.settings.GEMINI_API_KEY)

                cfg = DynamicConfig(
                    key=item["key"],
                    value=val,
                    value_type=item["value_type"],
                    category=item["category"],
                    is_secret=item["is_secret"],
                    description=item["description"],
                    updated_by="system_seed",
                )
                self.db.add(cfg)
        await self.db.flush()

    async def get_raw(self, key: str, default: Any = None) -> Any:
        # Check Redis cache first if available
        if self.redis:
            try:
                cached = await self.redis.get(f"dyn_cfg:{key}")
                if cached is not None:
                    data = json.loads(cached)
                    return self._cast_value(data["value"], data["value_type"], data["is_secret"])
            except Exception:
                pass

        stmt = select(DynamicConfig).where(DynamicConfig.key == key)
        cfg = (await self.db.execute(stmt)).scalar_one_or_none()
        if cfg is None:
            return default

        if self.redis:
            try:
                await self.redis.setex(
                    f"dyn_cfg:{key}",
                    300,
                    json.dumps({
                        "value": cfg.value,
                        "value_type": cfg.value_type,
                        "is_secret": cfg.is_secret,
                    }),
                )
            except Exception:
                pass

        return self._cast_value(cfg.value, cfg.value_type, cfg.is_secret)

    def _cast_value(self, raw_val: str, value_type: str, is_secret: bool) -> Any:
        val = self.cipher.decrypt(raw_val) if (is_secret and raw_val) else raw_val
        if value_type == "int":
            return int(val) if val else 0
        if value_type == "float":
            return float(val) if val else 0.0
        if value_type == "bool":
            return str(val).lower() in ("true", "1", "yes", "on")
        if value_type == "json":
            return json.loads(val) if val else {}
        return val

    async def set_config(self, key: str, new_value: Any, actor: str = "admin") -> DynamicConfig:
        stmt = select(DynamicConfig).where(DynamicConfig.key == key)
        cfg = (await self.db.execute(stmt)).scalar_one_or_none()
        if cfg is None:
            raise ValueError(f"Configuration key '{key}' does not exist.")

        old_display = SecretVaultCipher.mask_secret(self.cipher.decrypt(cfg.value)) if (cfg.is_secret and cfg.value) else cfg.value

        if cfg.value_type == "json" and not isinstance(new_value, str):
            serialized = json.dumps(new_value, ensure_ascii=False)
        elif cfg.value_type == "bool":
            serialized = "true" if str(new_value).lower() in ("true", "1", "yes", "on") else "false"
        else:
            serialized = str(new_value)

        if cfg.is_secret:
            stored_value = self.cipher.encrypt(serialized) if serialized else ""
            new_display = SecretVaultCipher.mask_secret(serialized)
        else:
            stored_value = serialized
            new_display = serialized

        cfg.value = stored_value
        cfg.updated_by = actor

        audit = ConfigAuditLog(
            config_key=key,
            old_value_masked=old_display,
            new_value_masked=new_display,
            changed_by=actor,
        )
        self.db.add(audit)
        await self.db.flush()

        if self.redis:
            try:
                await self.redis.delete(f"dyn_cfg:{key}")
                await self.redis.publish("config_updates", json.dumps({"key": key, "updated_by": actor}))
            except Exception:
                pass

        return cfg

    async def list_all_for_dashboard(self) -> List[Dict[str, Any]]:
        stmt = select(DynamicConfig).order_by(DynamicConfig.category, DynamicConfig.key)
        rows = (await self.db.execute(stmt)).scalars().all()
        result = []
        for r in rows:
            if r.is_secret:
                decrypted = self.cipher.decrypt(r.value) if r.value else ""
                display_val = SecretVaultCipher.mask_secret(decrypted) if decrypted else ""
            else:
                display_val = r.value
            result.append({
                "key": r.key,
                "value": display_val,
                "value_type": r.value_type,
                "category": r.category,
                "is_secret": r.is_secret,
                "has_secret_set": bool(r.value) if r.is_secret else True,
                "description": r.description,
                "updated_by": r.updated_by,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            })
        return result
