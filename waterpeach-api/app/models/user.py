from sqlalchemy import BigInteger, Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(16), index=True)
    phone: Mapped[str] = mapped_column(String(20), unique=True)
    account_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    balance: Mapped[int] = mapped_column(BigInteger, default=0)
    age_group: Mapped[str] = mapped_column(String(20), default="26_55_adult")
    avatar: Mapped[str | None] = mapped_column(String(255), nullable=True)
    protection_threshold: Mapped[int] = mapped_column(BigInteger, default=5_000_000)
    sensitive_hours_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_trigger_high_risk: Mapped[bool] = mapped_column(Boolean, default=True)
