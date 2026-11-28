"""Tests for environment configuration (local / cloud), DB/Redis/Supabase clients,
B2B API key guard and the readiness probe."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy.pool import NullPool

from app.core.config import DEV_B2B_API_KEY, Settings, get_settings
from app.core.security import require_b2b_api_key
from app.db import redis as redis_module
from app.db import session as session_module
from app.db import supabase as supabase_module
from app.main import app

SUPABASE_POOLER_URL = (
    "postgresql+asyncpg://postgres.ref:pw@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres"
)
SUPABASE_DIRECT_URL = "postgresql+asyncpg://postgres:pw@db.ref.supabase.co:5432/postgres"


def make_settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


# --------------------------------------------------------------------------- config


def test_local_defaults_point_to_local_services() -> None:
    s = make_settings()
    assert s.APP_ENV == "local"
    assert "localhost:5432" in s.DATABASE_URL
    assert s.REDIS_URL == "redis://localhost:6379/0"
    assert s.B2B_API_KEY == DEV_B2B_API_KEY
    assert s.GEMINI_MODEL == "gemini-4-hydrogen"
    assert s.is_cloud is False


def test_migration_url_falls_back_to_database_url() -> None:
    assert make_settings().migration_database_url == make_settings().DATABASE_URL
    s = make_settings(DATABASE_URL=SUPABASE_POOLER_URL, DIRECT_URL=SUPABASE_DIRECT_URL)
    assert s.migration_database_url == SUPABASE_DIRECT_URL


def test_transaction_pooler_detection() -> None:
    assert make_settings().uses_transaction_pooler is False
    assert make_settings(DATABASE_URL=SUPABASE_POOLER_URL).uses_transaction_pooler is True


def cloud_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "APP_ENV": "cloud",
        "DEBUG": False,
        "DATABASE_URL": SUPABASE_POOLER_URL,
        "DIRECT_URL": SUPABASE_DIRECT_URL,
        "B2B_API_KEY": "wp_live_strong_random_key",
        "CORS_ORIGINS": ["https://waterpeach.vercel.app"],
    }
    values.update(overrides)
    return make_settings(**values)


def test_valid_cloud_settings() -> None:
    s = cloud_settings()
    assert s.is_cloud is True
    assert s.uses_transaction_pooler is True


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"B2B_API_KEY": DEV_B2B_API_KEY}, "B2B_API_KEY"),
        ({"B2B_API_KEY": ""}, "B2B_API_KEY"),
        ({"DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/db"}, "DATABASE_URL"),
        ({"DATABASE_URL": "postgresql+asyncpg://u:p@postgres:5432/db"}, "DATABASE_URL"),
        ({"DEBUG": True}, "DEBUG"),
        ({"CORS_ORIGINS": ["http://localhost:3000"]}, "CORS_ORIGINS"),
    ],
)
def test_cloud_settings_reject_local_values(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        cloud_settings(**overrides)


def test_empty_redis_url_is_allowed() -> None:
    assert cloud_settings(REDIS_URL="").REDIS_URL == ""


def test_env_file_is_selected_by_env_file_variable(
    tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env.cloud"  # type: ignore[operator]
    env_file.write_text("GEMINI_MODEL=model-from-cloud-file\n", encoding="utf-8")
    monkeypatch.setenv("ENV_FILE", str(env_file))
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    get_settings.cache_clear()
    try:
        assert get_settings().GEMINI_MODEL == "model-from-cloud-file"
    finally:
        monkeypatch.delenv("ENV_FILE")
        get_settings.cache_clear()


# --------------------------------------------------------------------------- db session


def test_engine_kwargs_for_local_postgres() -> None:
    kwargs = session_module.build_engine_kwargs(make_settings())
    assert kwargs["pool_pre_ping"] is True
    assert "poolclass" not in kwargs
    assert "connect_args" not in kwargs


def test_engine_kwargs_for_supabase_transaction_pooler() -> None:
    kwargs = session_module.build_engine_kwargs(make_settings(DATABASE_URL=SUPABASE_POOLER_URL))
    assert kwargs["poolclass"] is NullPool
    connect_args = kwargs["connect_args"]
    assert connect_args["statement_cache_size"] == 0
    assert connect_args["prepared_statement_cache_size"] == 0
    first = connect_args["prepared_statement_name_func"]()
    assert first != connect_args["prepared_statement_name_func"]()


@pytest.fixture
def reset_db_singletons() -> None:
    session_module.get_engine.cache_clear()
    session_module.get_sessionmaker.cache_clear()
    yield
    session_module.get_engine.cache_clear()
    session_module.get_sessionmaker.cache_clear()


@pytest.mark.usefixtures("reset_db_singletons")
async def test_get_db_session_yields_async_session() -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    gen = session_module.get_db_session()
    db = await gen.__anext__()
    assert isinstance(db, AsyncSession)
    await gen.aclose()
    await session_module.dispose_engine()


async def test_check_database_success_and_failure() -> None:
    conn = AsyncMock()
    engine = MagicMock()
    engine.connect.return_value.__aenter__.return_value = conn
    with patch.object(session_module, "get_engine", return_value=engine):
        assert await session_module.check_database() is True
    conn.execute.assert_awaited_once()

    broken = MagicMock()
    broken.connect.side_effect = OSError("connection refused")
    with patch.object(session_module, "get_engine", return_value=broken):
        assert await session_module.check_database() is False


# --------------------------------------------------------------------------- redis


@pytest.fixture
def reset_redis() -> None:
    redis_module._client = None
    yield
    redis_module._client = None


@pytest.mark.usefixtures("reset_redis")
async def test_redis_disabled_when_url_empty() -> None:
    with patch.object(redis_module, "get_settings", return_value=make_settings(REDIS_URL="")):
        assert redis_module.get_redis() is None
        assert await redis_module.check_redis() is None


@pytest.mark.usefixtures("reset_redis")
async def test_redis_client_is_cached_and_checked() -> None:
    fake = MagicMock()
    fake.ping = AsyncMock(return_value=True)
    fake.aclose = AsyncMock()
    with patch.object(redis_module.Redis, "from_url", return_value=fake) as from_url:
        assert redis_module.get_redis() is fake
        assert redis_module.get_redis() is fake
        from_url.assert_called_once()
        assert await redis_module.check_redis() is True
        fake.ping.side_effect = ConnectionError("down")
        assert await redis_module.check_redis() is False
        await redis_module.close_redis()
        fake.aclose.assert_awaited_once()
        assert redis_module._client is None


# --------------------------------------------------------------------------- supabase


@pytest.fixture
def reset_supabase() -> None:
    supabase_module._client = None
    yield
    supabase_module._client = None


@pytest.mark.usefixtures("reset_supabase")
async def test_supabase_none_when_not_configured() -> None:
    with patch.object(supabase_module, "get_settings", return_value=make_settings()):
        assert await supabase_module.get_supabase() is None


@pytest.mark.usefixtures("reset_supabase")
async def test_supabase_client_created_once_with_service_role_key() -> None:
    s = make_settings(SUPABASE_URL="https://ref.supabase.co", SUPABASE_SERVICE_ROLE_KEY="srk")
    fake = object()
    with (
        patch.object(supabase_module, "get_settings", return_value=s),
        patch.object(supabase_module, "acreate_client", AsyncMock(return_value=fake)) as create,
    ):
        assert await supabase_module.get_supabase() is fake
        assert await supabase_module.get_supabase() is fake
        create.assert_awaited_once_with("https://ref.supabase.co", "srk")


# --------------------------------------------------------------------------- b2b guard


def make_guarded_app() -> FastAPI:
    guarded = FastAPI()

    @guarded.get("/guarded", dependencies=[Depends(require_b2b_api_key)])
    async def guarded_route() -> dict[str, str]:
        return {"ok": "yes"}

    return guarded


@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ({}, 401),
        ({"X-API-Key": "wrong"}, 401),
        ({"X-API-Key": DEV_B2B_API_KEY}, 200),
    ],
)
async def test_b2b_api_key_guard(headers: dict[str, str], status: int) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=make_guarded_app()), base_url="http://test"
    ) as client:
        response = await client.get("/guarded", headers=headers)
    assert response.status_code == status


async def test_b2b_api_key_guard_rejects_when_key_not_configured() -> None:
    with patch("app.core.security.get_settings", return_value=make_settings(B2B_API_KEY="")):
        async with AsyncClient(
            transport=ASGITransport(app=make_guarded_app()), base_url="http://test"
        ) as client:
            response = await client.get("/guarded", headers={"X-API-Key": ""})
    assert response.status_code == 401


# --------------------------------------------------------------------------- readiness


@pytest.mark.parametrize(
    ("db_ok", "redis_ok", "status_code", "status", "redis_state"),
    [
        (True, True, 200, "ok", "ok"),
        (True, None, 200, "ok", "skipped"),
        (False, True, 503, "degraded", "ok"),
        (True, False, 503, "degraded", "fail"),
    ],
)
async def test_readiness_probe(
    db_ok: bool, redis_ok: bool | None, status_code: int, status: str, redis_state: str
) -> None:
    with (
        patch("app.main.check_database", AsyncMock(return_value=db_ok)),
        patch("app.main.check_redis", AsyncMock(return_value=redis_ok)),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/health/ready")
    assert response.status_code == status_code
    body = response.json()
    assert body["status"] == status
    assert body["env"] == "local"
    assert body["checks"] == {"database": "ok" if db_ok else "fail", "redis": redis_state}


async def test_lifespan_closes_connections() -> None:
    with (
        patch("app.main.dispose_engine", AsyncMock()) as dispose,
        patch("app.main.close_redis", AsyncMock()) as close,
    ):
        async with app.router.lifespan_context(app):
            pass
    dispose.assert_awaited_once()
    close.assert_awaited_once()
