import time
from collections import defaultdict, deque
from dataclasses import dataclass

from app.schemas.ai import RelationshipContext, VelocityContext


@dataclass
class _TxRecord:
    timestamp: float
    amount: int
    recipient_account: str
    is_familiar: bool


class InMemoryVelocityTracker:
    """Sliding-window tracker to detect structuring (smurfing) and rapid burst transfers."""

    def __init__(self, window_seconds: int = 3600) -> None:
        self._window_seconds = window_seconds
        self._history: dict[str, deque[_TxRecord]] = defaultdict(deque)

    def _prune(self, sender_id: str, now: float) -> deque[_TxRecord]:
        q = self._history[sender_id]
        cutoff = now - self._window_seconds
        while q and q[0].timestamp < cutoff:
            q.popleft()
        return q

    def record_and_summarize(
        self,
        sender_id: str,
        amount: int,
        recipient_account: str,
        is_familiar: bool,
        now: float | None = None,
    ) -> VelocityContext:
        """Record a transaction and return 15m/60m sliding-window velocity metrics."""
        ts = now if now is not None else time.monotonic()
        q = self._prune(sender_id, ts)

        seconds_since_last: int | None = None
        if q:
            seconds_since_last = max(0, int(ts - q[-1].timestamp))

        q.append(
            _TxRecord(
                timestamp=ts,
                amount=amount,
                recipient_account=recipient_account,
                is_familiar=is_familiar,
            )
        )

        cutoff_15m = ts - 900
        tx_count_15m = sum(1 for item in q if item.timestamp >= cutoff_15m and not item.is_familiar)
        cumulative_unfamiliar_60m = sum(item.amount for item in q if not item.is_familiar)

        return VelocityContext(
            tx_count_15m=tx_count_15m,
            cumulative_unfamiliar_amount_60m=cumulative_unfamiliar_60m,
            seconds_since_last_tx=seconds_since_last,
            is_sensitive_hours=False,
        )

    def clear(self) -> None:
        """Reset all tracked history (useful for demo reset and tests)."""
        self._history.clear()


_velocity_tracker = InMemoryVelocityTracker()


def get_velocity_tracker() -> InMemoryVelocityTracker:
    """Return global velocity tracker instance."""
    return _velocity_tracker


def evaluate_velocity_and_structuring(
    amount: int,
    relationship_ctx: RelationshipContext,
    velocity_ctx: VelocityContext,
) -> tuple[int, list[str]]:
    """Evaluate RFM sliding-window velocity and sub-threshold structuring (smurfing)."""
    score = 0
    signals: list[str] = []
    threshold = relationship_ctx.protection_threshold
    is_unfamiliar = relationship_ctx.prior_tx_count == 0

    cumulative_60m = max(velocity_ctx.cumulative_unfamiliar_amount_60m, amount if is_unfamiliar else 0)

    if is_unfamiliar and amount >= threshold:
        ratio = amount / threshold
        score += 30 if ratio >= 2.0 else 22
        signals.append("THRESHOLD_EXCEEDED")
    elif is_unfamiliar and cumulative_60m >= threshold:
        score += 30
        signals.append("CUMULATIVE_THRESHOLD_EXCEEDED")

    # Detect deliberate structuring just below threshold (e.g., 3M + 2.5M within 15-60 mins)
    is_sub_threshold_slice = (0.4 * threshold) <= amount < threshold
    if is_unfamiliar and is_sub_threshold_slice and (
        cumulative_60m >= threshold or velocity_ctx.tx_count_15m >= 2
    ):
        score += 35
        signals.append("STRUCTURING_SPLIT_TX_DETECTED")

    if (
        velocity_ctx.seconds_since_last_tx is not None
        and velocity_ctx.seconds_since_last_tx < 180
        and is_unfamiliar
    ) or velocity_ctx.tx_count_15m >= 3:
        score += 15
        signals.append("RAPID_BURST_VELOCITY")

    if velocity_ctx.is_sensitive_hours:
        score += 12
        signals.append("SENSITIVE_NIGHT_HOURS")

    return score, signals
