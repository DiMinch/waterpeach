from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm import relationship as orm_relationship

from app.models.base import Base, TimestampMixin
from app.models.user import User


class FamilyLink(TimestampMixin, Base):
    __tablename__ = "family_links"
    __table_args__ = (UniqueConstraint("victim_id", "guardian_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    victim_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    guardian_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    relationship: Mapped[str] = mapped_column(String(50))
    guardian_relationship: Mapped[str] = mapped_column(String(20), default="other")
    privacy_mode: Mapped[str] = mapped_column(String(20), default="alert_only")
    status: Mapped[str] = mapped_column(String(16), default="active")

    victim: Mapped[User] = orm_relationship(foreign_keys=[victim_id], lazy="joined")
    guardian: Mapped[User] = orm_relationship(foreign_keys=[guardian_id], lazy="joined")
