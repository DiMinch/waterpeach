"""Realtime bus (WebSocket + SSE), sensitive-hour rule and the seed CLI."""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.testclient import TestClient

from app import seed
from app.api.v1.events import sse_stream
from app.main import app
from app.models import User
from app.schemas.common import UserRole, to_vn_time
from app.services import demo_service, transaction_service
from app.services.realtime import EventBus, EventType, get_event_bus


def test_event_bus_filters_by_role_and_drops_oldest_when_full() -> None:
    bus = EventBus()
    guardian = bus.subscribe(UserRole.GUARDIAN)
    everyone = bus.subscribe(None)
    bus.publish(EventType.OPS_INCIDENT_ESCALATED, {"n": 0}, [UserRole.FRAUD_OPS])
    assert guardian.queue.empty()
    assert everyone.queue.qsize() == 1

    for n in range(1, 101):
        bus.publish(EventType.GUARDIAN_DECISION_MADE, {"n": n})
    assert guardian.queue.qsize() == 100
    assert guardian.queue.get_nowait().payload == {"n": 1}
    assert everyone.queue.get_nowait().payload == {"n": 1}  # n=0 dropped

    bus.unsubscribe(guardian)
    bus.unsubscribe(everyone)
    assert bus.subscriber_count == 0


def test_websocket_streams_role_filtered_envelopes() -> None:
    bus = get_event_bus()
    with TestClient(app) as client:
        with client.websocket_connect("/api/v1/ws/events?role=guardian") as ws:
            assert bus.subscriber_count >= 1
            client.portal.call(
                bus.publish, EventType.OPS_INCIDENT_ESCALATED, {"tx_id": "a"}, [UserRole.FRAUD_OPS]
            )
            client.portal.call(bus.publish, EventType.TX_COOLING_OFF_TRIGGERED, {"tx_id": "b"})
            message = json.loads(ws.receive_text())
    assert message["event"] == "TX_COOLING_OFF_TRIGGERED"
    assert message["payload"] == {"tx_id": "b"}
    assert message["target_roles"] == ["victim", "guardian", "fraud_ops"]
    assert message["timestamp"].endswith("+07:00")
    assert bus.subscriber_count == 0


async def test_sse_stream_emits_events_and_keepalive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.v1.events.SSE_KEEPALIVE_SECONDS", 0.01)
    bus = get_event_bus()
    sub = bus.subscribe(UserRole.VICTIM)
    request = MagicMock()
    request.is_disconnected = AsyncMock(side_effect=[False, False, True])
    bus.publish(EventType.DEMO_DATA_RESET, {"users": 3})

    chunks = [chunk async for chunk in sse_stream(request, sub)]
    assert chunks[0] == ": connected\n\n"
    assert chunks[1].startswith("event: DEMO_DATA_RESET\ndata: ")
    assert chunks[2] == ": keep-alive\n\n"
    assert bus.subscriber_count == 0


def test_sse_endpoint_is_registered() -> None:
    paths = app.openapi()["paths"]
    assert "get" in paths["/api/v1/events/stream"]


@pytest.mark.parametrize(
    ("utc_hour", "enabled", "expected"),
    [(16, True, True), (22, True, True), (3, True, False), (16, False, False)],
)
def test_sensitive_hours_use_vietnam_time(utc_hour: int, enabled: bool, expected: bool) -> None:
    # 16:00 UTC = 23:00 VN, 22:00 UTC = 05:00 VN, 03:00 UTC = 10:00 VN
    user = User(sensitive_hours_enabled=enabled)
    fixed = datetime(2026, 11, 25, utc_hour, 0, tzinfo=UTC)
    with patch.object(transaction_service, "utcnow", return_value=fixed):
        assert transaction_service.is_sensitive_hour(user) is expected


def test_to_vn_time_handles_naive_values() -> None:
    assert to_vn_time(datetime(2026, 11, 25, 7, 30)) == "2026-11-25T14:30:00+07:00"


async def test_seed_cli_seeds_once_then_resets(
    session_factory: async_sessionmaker[AsyncSession], capsys: pytest.CaptureFixture[str]
) -> None:
    with (
        patch.object(seed, "get_sessionmaker", return_value=session_factory),
        patch.object(seed, "dispose_engine", AsyncMock()),
    ):
        await seed.main(force_reset=False)
        await seed.main(force_reset=False)
        await seed.main(force_reset=True)
    out = capsys.readouterr().out.splitlines()
    assert out == [
        "Seeded demo data",
        "Demo data already present (use --reset to wipe)",
        "Reset demo data: 3 users, 3 transactions",
    ]
    async with session_factory() as db:
        assert await db.get(User, demo_service.VICTIM_ID) is not None
