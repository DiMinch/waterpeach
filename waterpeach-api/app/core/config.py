from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "waterpeach-api"
    APP_ENV: str = "development"
    DEBUG: bool = True

    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-4-hydrogen"
    AI_TIMEOUT_SECONDS: float = 8.0
    AI_MAX_UPLOAD_BYTES: int = 5 * 1024 * 1024
    AI_RATE_LIMIT_PER_MIN: int = 30
    AI_CACHE_TTL_SECONDS: int = 300

    VIETQR_BUSINESS_API_URL: str = "https://api.vietqr.io/v2/business"
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    """Return cached Settings instance."""
    return Settings()
