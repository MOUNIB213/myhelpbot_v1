from functools import lru_cache
from typing import List
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    APP_ENV: str = "production"
    APP_NAME: str = "Private Telegram Assistant"
    LOG_LEVEL: str = "INFO"

    SECRET_KEY: str = Field(default="E7Biry3gYL1WDF6RSO4tdp6bfWnGLFqmeWoGVsenh5s7WfHKJUwaFdwLs60Gzqck", min_length=16)
    MASTER_ENCRYPTION_KEY: str = Field(default="ZC18_BR3f5a4g-7CxLlPFutL3LZwQk5eLlx1Tm84GBI=", min_length=32)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    ALLOWED_ORIGINS: str = "http://localhost:5173,http://localhost:8000"

    INITIAL_ADMIN_USERNAME: str = "mounibkhaldi"
    INITIAL_ADMIN_PASSWORD: str = Field(default="0PCZBCshxHbjrD-EIDh7xg", min_length=8)

    TELEGRAM_BOT_TOKEN: str = Field(default="9148501232:AAEQynI2iAFiSlhozYideyrG8zWLiOsi1lg", min_length=10)
    TELEGRAM_OWNER_ID: int = Field(default=8456971230)
    TELEGRAM_OWNER_USERNAME: str = Field(default="mounibkhaldi")
    TELEGRAM_STORAGE_CHANNEL_ID: int = Field(default=-1004221077545)

    GEMINI_API_KEY: str = Field(default="")
    GEMINI_DEFAULT_MODEL: str = "gemini-2.5-flash"

    DATABASE_URL: str = Field(default="sqlite+aiosqlite:///./botvault.db")
    REDIS_URL: str = Field(default="redis://localhost:6379/0")

    BACKUP_DIR: str = "./backups"
    BACKUP_RETENTION_DAYS: int = 30

    @property
    def cors_origins(self) -> List[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    @field_validator("TELEGRAM_STORAGE_CHANNEL_ID")
    @classmethod
    def validate_channel_id(cls, v: int) -> int:
        if v >= 0:
            raise ValueError("TELEGRAM_STORAGE_CHANNEL_ID must be a negative supergroup/channel ID (e.g. -100...)")
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
