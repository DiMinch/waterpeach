from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.user import User


class ScamReport(TimestampMixin, Base):
    __tablename__ = "scam_reports"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    submitted_by: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_verdict: Mapped[str] = mapped_column(String(20))
    risk_score: Mapped[int] = mapped_column(Integer, default=0)
    scam_category: Mapped[str] = mapped_column(String(64), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    advice_for_family: Mapped[str] = mapped_column(Text, default="")
    tactics_detected: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    extracted_entities_json: Mapped[dict[str, list[str]]] = mapped_column(JSON, default=dict)
    shared_to_family: Mapped[bool] = mapped_column(Boolean, default=False)

    submitter: Mapped[User] = relationship(lazy="joined")
