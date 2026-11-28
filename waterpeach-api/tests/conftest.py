from collections.abc import AsyncIterator, Callable, Iterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.ai.client import get_gemini_client
from app.core.config import get_settings
from app.db.session import get_db_session
from app.main import app
from app.models import Base
from app.services import demo_service, transaction_service
from app.services.realtime import get_event_bus


@pytest.fixture
async def db_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def session_factory(db_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(db_engine, expire_on_commit=False)


@pytest.fixture
async def api(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncClient]:
    """HTTP client against a freshly seeded in-memory DB, Gemini forced onto fallbacks."""
    monkeypatch.setattr(get_settings(), "GEMINI_API_KEY", "")
    monkeypatch.setattr(transaction_service, "is_sensitive_hour", lambda _user: False)
    get_gemini_client().reset_state()
    async with session_factory() as session:
        await demo_service.reset(session)

    async def override() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def events() -> Iterator[Callable[[], list[str]]]:
    """Collect names of realtime events published during the test."""
    bus = get_event_bus()
    sub = bus.subscribe(None)
    names: list[str] = []

    def drain() -> list[str]:
        while not sub.queue.empty():
            names.append(sub.queue.get_nowait().event)
        return names

    yield drain
    bus.unsubscribe(sub)
