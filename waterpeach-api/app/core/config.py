import os
from functools import lru_cache
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_B2B_API_KEY = "wp_dev_b2b_api_key"
LOCAL_DATABASE_URL = "postgresql+asyncpg://waterpeach:waterpeach_dev_password@localhost:5432/waterpeach"
SUPABASE_TRANSACTION_POOLER_PORT = 6543
_LOCAL_DB_HOSTS = {"localhost", "127.0.0.1", "postgres", "host.docker.internal"}


class Settings(BaseSettings):
    """Application configuration loaded from environment variables.

    Two environments are supported:
    - ``local``: Postgres + Redis from docker-compose, permissive defaults.
    - ``cloud``: Supabase + Cloud Run + Vercel; unsafe local values are rejected at startup.

    The env file defaults to ``.env`` and can be switched with ``ENV_FILE`` (e.g. ``.env.cloud``).
    Real environment variables always take precedence over the file.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "waterpeach-api"
    APP_ENV: Literal["local", "cloud"] = "local"
    DEBUG: bool = True

    SUPABASE_URL: str = ""
    SUPABASE_ANON_KEY: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""

    DATABASE_URL: str = LOCAL_DATABASE_URL
    DIRECT_URL: str = ""
    DB_CHECK_TIMEOUT_SECONDS: float = 3.0

    REDIS_URL: str = "redis://localhost:6379/0"

    B2B_API_KEY: str = DEV_B2B_API_KEY

    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-4-hydrogen"
    AI_TIMEOUT_SECONDS: float = 8.0
    AI_MAX_UPLOAD_BYTES: int = 5 * 1024 * 1024
    AI_RATE_LIMIT_PER_MIN: int = 30
    AI_CACHE_TTL_SECONDS: int = 300

    VIETQR_BUSINESS_API_URL: str = "https://api.vietqr.io/v2/business"
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    @property
    def is_cloud(self) -> bool:
        return self.APP_ENV == "cloud"

    @property
    def migration_database_url(self) -> str:
        """URL for Alembic: Supabase direct connection (5432) when set, else runtime URL."""
        return self.DIRECT_URL or self.DATABASE_URL

    @property
    def uses_transaction_pooler(self) -> bool:
        """True when DATABASE_URL targets the Supabase transaction pooler (port 6543)."""
        return urlsplit(self.DATABASE_URL).port == SUPABASE_TRANSACTION_POOLER_PORT

    @model_validator(mode="after")
    def _validate_cloud(self) -> Self:
        if not self.is_cloud:
            return self
        problems: list[str] = []
        if not self.B2B_API_KEY or self.B2B_API_KEY == DEV_B2B_API_KEY:
            problems.append("B2B_API_KEY must be set to a non-default secret")
        if (urlsplit(self.DATABASE_URL).hostname or "") in _LOCAL_DB_HOSTS:
            problems.append("DATABASE_URL must point to Supabase, not a local host")
        if self.DEBUG:
            problems.append("DEBUG must be false")
        if any("localhost" in origin or "127.0.0.1" in origin for origin in self.CORS_ORIGINS):
            problems.append("CORS_ORIGINS must list the deployed web origin(s) only")
        if problems:
            raise ValueError("Invalid cloud configuration: " + "; ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    """Return cached Settings instance (env file chosen by ``ENV_FILE``, default ``.env``)."""
    return Settings(_env_file=os.getenv("ENV_FILE", ".env"))  # type: ignore[call-arg]
