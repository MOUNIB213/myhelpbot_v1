import time
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import (
    AIErrorLog,
    AIMessage,
    AISession,
    AIUsageQuota,
    TelegramUser,
)
from app.services.code_generator import generate_ai_session_code
from app.services.dynamic_config_service import DynamicConfigService
from app.services.text_utils import split_telegram_markdown_chunks

try:
    from google import genai
    from google.genai import types as genai_types
    _HAS_GOOGLE_GENAI = True
except ImportError:
    _HAS_GOOGLE_GENAI = False


# Pricing estimation per 1M tokens (USD) for dashboard telemetry
MODEL_PRICING_PER_1M = {
    "gemini-2.5-flash": {"input": 0.15, "output": 0.60},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
}


class GeminiAIService:
    """
    Enterprise Gemini AI Assistant Service using official google-genai SDK.
    Supports multi-turn context per session, daily per-user request & token quotas,
    automatic Markdown chunking for Telegram limits, cost telemetry, and safe error logging
    without ever exposing API keys.
    """

    def __init__(self, db: AsyncSession, config_service: DynamicConfigService):
        self.db = db
        self.config_service = config_service

    async def start_new_session(self, user: TelegramUser, title: str = "محادثة ذكية جديدة") -> AISession:
        # Close any currently active sessions for this user
        stmt = select(AISession).where(AISession.user_id == user.id, AISession.is_active.is_(True))
        active_sessions = (await self.db.execute(stmt)).scalars().all()
        now = datetime.now(timezone.utc)
        for s in active_sessions:
            s.is_active = False
            s.ended_at = now

        model_name = await self.config_service.get_raw("ai.model_name", "gemini-2.5-flash")
        session = AISession(
            session_code=generate_ai_session_code(),
            user_id=user.id,
            title=title[:250],
            model_name=str(model_name),
            is_active=True,
        )
        self.db.add(session)
        await self.db.flush()
        return session

    async def get_or_create_active_session(self, user: TelegramUser) -> AISession:
        stmt = (
            select(AISession)
            .where(AISession.user_id == user.id, AISession.is_active.is_(True))
            .order_by(AISession.created_at.desc())
        )
        session = (await self.db.execute(stmt)).scalar_one_or_none()
        if session is not None:
            return session
        return await self.start_new_session(user)

    async def end_session_by_code_or_active(
        self, user: TelegramUser, session_code: Optional[str] = None
    ) -> Optional[AISession]:
        if session_code:
            stmt = select(AISession).where(
                AISession.user_id == user.id,
                AISession.session_code == session_code.strip().upper(),
            )
        else:
            stmt = select(AISession).where(
                AISession.user_id == user.id,
                AISession.is_active.is_(True),
            )
        session = (await self.db.execute(stmt)).scalar_one_or_none()
        if session is None:
            return None
        session.is_active = False
        session.ended_at = datetime.now(timezone.utc)
        await self.db.flush()
        return session

    async def delete_session(self, user: TelegramUser, session_code: str) -> bool:
        stmt = select(AISession).where(
            AISession.user_id == user.id,
            AISession.session_code == session_code.strip().upper(),
        )
        session = (await self.db.execute(stmt)).scalar_one_or_none()
        if session is None:
            return False
        await self.db.delete(session)
        await self.db.flush()
        return True

    async def check_and_get_quota(self, user: TelegramUser) -> Tuple[bool, str, AIUsageQuota]:
        today = date.today()
        stmt = select(AIUsageQuota).where(
            AIUsageQuota.user_id == user.id,
            AIUsageQuota.usage_date == today,
        )
        quota = (await self.db.execute(stmt)).scalar_one_or_none()
        if quota is None:
            quota = AIUsageQuota(
                user_id=user.id,
                usage_date=today,
                requests_count=0,
                tokens_count=0,
                estimated_cost_usd=0.0,
            )
            self.db.add(quota)
            await self.db.flush()

        if quota.requests_count >= user.daily_ai_requests_limit:
            return (
                False,
                f"⚠️ لقد استنفدت حد الطلبات اليومي المسموح به ({user.daily_ai_requests_limit} طلب/يوم).",
                quota,
            )
        if quota.tokens_count >= user.daily_ai_tokens_limit:
            return (
                False,
                f"⚠️ لقد استنفدت حد التوكنات اليومي المسموح به ({user.daily_ai_tokens_limit:,} توكن/يوم).",
                quota,
            )
        return True, "ok", quota

    async def send_Prompt(
        self,
        user: TelegramUser,
        user_prompt: str,
        session_code: Optional[str] = None,
    ) -> Dict[str, Any]:
        ai_enabled = await self.config_service.get_raw("ai.enabled", True)
        if not ai_enabled:
            return {
                "ok": False,
                "error": "⏸️ خدمة المساعد الذكي متوقفة مؤقتاً للصيانة من قِبل الإدارة.",
                "chunks": ["⏸️ خدمة المساعد الذكي متوقفة مؤقتاً للصيانة من قِبل الإدارة."],
            }

        allowed, quota_msg, quota = await self.check_and_get_quota(user)
        if not allowed:
            return {"ok": False, "error": quota_msg, "chunks": [quota_msg]}

        if session_code:
            stmt = select(AISession).where(
                AISession.user_id == user.id,
                AISession.session_code == session_code,
            )
            session = (await self.db.execute(stmt)).scalar_one_or_none()
            if session is None:
                session = await self.get_or_create_active_session(user)
        else:
            session = await self.get_or_create_active_session(user)

        if session.title == "محادثة ذكية جديدة" and user_prompt.strip():
            session.title = user_prompt.strip()[:80]

        # Retrieve conversation history (last 16 messages for context window efficiency)
        hist_stmt = (
            select(AIMessage)
            .where(AIMessage.session_id == session.id)
            .order_by(AIMessage.created_at.asc())
        )
        history_msgs = (await self.db.execute(hist_stmt)).scalars().all()[-16:]

        api_key = await self.config_service.get_raw("ai.gemini_api_key", "")
        model_name = await self.config_service.get_raw("ai.model_name", "gemini-2.5-flash")
        sys_instruction = await self.config_service.get_raw(
            "ai.system_instruction",
            "أنت مساعد ذكي شخصي متقدم. أجب بوضوح ودقة.",
        )
        temperature = float(await self.config_service.get_raw("ai.temperature", 0.7))

        if not api_key:
            err_text = "⚠️ لم يتم ضبط مفتاح Gemini API في لوحة التحكم بعد. يرجى إضافته من قسم AI Management."
            return {"ok": False, "error": err_text, "chunks": [err_text]}

        start_ts = time.perf_counter()
        try:
            reply_text, in_tokens, out_tokens = await self._invoke_gemini_sdk(
                api_key=str(api_key),
                model_name=str(model_name),
                system_instruction=str(sys_instruction),
                temperature=temperature,
                history=history_msgs,
                user_prompt=user_prompt,
            )
        except Exception as exc:
            sanitized_err = self._sanitize_error(str(exc), str(api_key))
            err_log = AIErrorLog(
                user_id=user.id,
                session_code=session.session_code,
                model_name=str(model_name),
                error_type=type(exc).__name__,
                error_message=sanitized_err,
            )
            self.db.add(err_log)
            await self.db.flush()
            friendly = "❌ تعذر الاتصال بخدمة الذكاء الاصطناعي حالياً. تم تسجيل الخطأ للنظام وسنعاود المحاولة قريباً."
            return {"ok": False, "error": friendly, "chunks": [friendly]}

        latency_ms = int((time.perf_counter() - start_ts) * 1000)
        total_tokens = in_tokens + out_tokens
        cost_usd = self._estimate_cost(str(model_name), in_tokens, out_tokens)

        user_msg = AIMessage(
            session_id=session.id,
            role="user",
            content=user_prompt,
            tokens_used=in_tokens,
            latency_ms=0,
        )
        model_msg = AIMessage(
            session_id=session.id,
            role="model",
            content=reply_text,
            tokens_used=out_tokens,
            latency_ms=latency_ms,
        )
        self.db.add_all([user_msg, model_msg])

        session.total_Input_tokens += in_tokens
        session.total_output_tokens += out_tokens
        session.estimated_cost_usd = round(session.estimated_cost_usd + cost_usd, 6)

        quota.requests_count += 1
        quota.tokens_count += total_tokens
        quota.estimated_cost_usd = round(quota.estimated_cost_usd + cost_usd, 6)

        await self.db.flush()

        chunks = split_telegram_markdown_chunks(reply_text)
        return {
            "ok": True,
            "session_code": session.session_code,
            "model_name": str(model_name),
            "reply": reply_text,
            "chunks": chunks,
            "tokens_used": total_tokens,
            "estimated_cost_usd": cost_usd,
            "latency_ms": latency_ms,
            "remaining_requests_today": max(0, user.daily_ai_requests_limit - quota.requests_count),
        }

    async def _invoke_gemini_sdk(
        self,
        api_key: str,
        model_name: str,
        system_instruction: str,
        temperature: float,
        history: List[AIMessage],
        user_prompt: str,
    ) -> Tuple[str, int, int]:
        if not _HAS_GOOGLE_GENAI:
            raise RuntimeError("google-genai SDK is not installed in the runtime environment.")

        client = genai.Client(api_key=api_key)
        contents: List[Any] = []
        for m in history:
            contents.append(
                genai_types.Content(
                    role="user" if m.role == "user" else "model",
                    parts=[genai_types.Part.from_text(text=m.content)],
                )
            )
        contents.append(
            genai_types.Content(
                role="user",
                parts=[genai_types.Part.from_text(text=user_prompt)],
            )
        )

        config = genai_types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature,
        )
        response = await client.aio.models.generate_content(
            model=model_name,
            contents=contents,
            config=config,
        )
        text = response.text or "لم يتم توليد نص."
        usage = getattr(response, "usage_metadata", None)
        in_tok = getattr(usage, "prompt_token_count", None) or max(1, len(user_prompt) // 4)
        out_tok = getattr(usage, "candidates_token_count", None) or max(1, len(text) // 4)
        return text, int(in_tok), int(out_tok)

    @staticmethod
    def _estimate_cost(model_name: str, in_tokens: int, out_tokens: int) -> float:
        rates = MODEL_PRICING_PER_1M.get(model_name, {"input": 0.15, "output": 0.60})
        return ((in_tokens / 1_000_000) * rates["input"]) + ((out_tokens / 1_000_000) * rates["output"])

    @staticmethod
    def _sanitize_error(error_msg: str, api_key: str) -> str:
        if api_key and len(api_key) > 4:
            error_msg = error_msg.replace(api_key, "[REDACTED_GEMINI_KEY]")
        return error_msg[:1000]
