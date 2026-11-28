from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, utcnow


class ThreatBlacklist(TimestampMixin, Base):
    __tablename__ = "threat_blacklist"
    __table_args__ = (UniqueConstraint("entity_type", "entity_value"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(16))
    entity_value: Mapped[str] = mapped_column(String(500), index=True)
    report_count: Mapped[int] = mapped_column(Integer, default=1)
    scam_pattern: Mapped[str] = mapped_column(String(100), default="")
    status: Mapped[str] = mapped_column(String(24), default="suspected")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
