"""In-process realtime event bus feeding WebSocket and SSE subscribers (contract 9.2).

Events are delivered to subscribers of the same process only; deploy the API with a single
instance (Cloud Run ``--max-instances 1``) so every screen sees every event.
"""

import asyncio
import logging
from collections.abc import Iterable
from enum import StrEnum
from typing import Any

from app.models.base import utcnow
from app.schemas.common import UserRole
from app.schemas.ops import RealtimeEvent

logger = logging.getLogger(__name__)

ALL_ROLES: tuple[UserRole, ...] = (UserRole.VICTIM, UserRole.GUARDIAN, UserRole.FRAUD_OPS)
_QUEUE_SIZE = 100


class EventType(StrEnum):
    TX_COOLING_OFF_TRIGGERED = "TX_COOLING_OFF_TRIGGERED"
    GUARDIAN_DECISION_MADE = "GUARDIAN_DECISION_MADE"
    OPS_INCIDENT_ESCALATED = "OPS_INCIDENT_ESCALATED"
    OPS_CONTAINMENT_EXECUTED = "OPS_CONTAINMENT_EXECUTED"
    FAMILY_SCAM_ALERT_SHARED = "FAMILY_SCAM_ALERT_SHARED"
    DEMO_DATA_RESET = "DEMO_DATA_RESET"


class Subscription:
    def __init__(self, role: UserRole | None) -> None:
        self.role = role
        self.queue: asyncio.Queue[RealtimeEvent] = asyncio.Queue(maxsize=_QUEUE_SIZE)

    def wants(self, event: RealtimeEvent) -> bool:
        return self.role is None or self.role in event.target_roles


class EventBus:
    def __init__(self) -> None:
        self._subscriptions: set[Subscription] = set()

    @property
    def subscriber_count(self) -> int:
        return len(self._subscriptions)

    def subscribe(self, role: UserRole | None = None) -> Subscription:
        sub = Subscription(role)
        self._subscriptions.add(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        self._subscriptions.discard(sub)

    def publish(
        self,
        event: EventType,
        payload: dict[str, Any],
        target_roles: Iterable[UserRole] = ALL_ROLES,
    ) -> RealtimeEvent:
        message = RealtimeEvent(
            event=event.value,
            timestamp=utcnow(),
            target_roles=list(target_roles),
            payload=payload,
        )
        for sub in list(self._subscriptions):
            if not sub.wants(message):
                continue
            if sub.queue.full():  # slow consumer: drop the oldest event
                sub.queue.get_nowait()
                logger.warning("Realtime subscriber queue full; dropped oldest event")
            sub.queue.put_nowait(message)
        return message


_bus = EventBus()


def get_event_bus() -> EventBus:
    return _bus
