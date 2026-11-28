from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, utcnow
from app.models.user import User


class Transaction(TimestampMixin, Base):
    __tablename__ = "transactions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    sender_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    recipient_name: Mapped[str] = mapped_column(String(200))
    recipient_account: Mapped[str] = mapped_column(String(32), index=True)
    recipient_bank: Mapped[str] = mapped_column(String(100), default="")
    amount: Mapped[int] = mapped_column(BigInteger)
    transfer_note: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(16), index=True)
    is_new_recipient: Mapped[bool] = mapped_column(Boolean, default=True)
    funds_held: Mapped[bool] = mapped_column(Boolean, default=False)
    cooling_off_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ai_risk_score: Mapped[int] = mapped_column(Integer, default=0)
    ai_analysis_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    guardian_decision: Mapped[str] = mapped_column(String(16), default="pending")
    guardian_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ops_decision: Mapped[str] = mapped_column(String(20), default="pending")
    ops_notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    partner_tx_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str] = mapped_column(String(8), default="web")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    sender: Mapped[User] = relationship(lazy="joined")
