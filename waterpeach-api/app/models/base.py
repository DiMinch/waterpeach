from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import DateTime, MetaData
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """SQLite drops tzinfo; treat naive datetimes as UTC."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def new_id(prefix: str) -> str:
    """Short prefixed identifiers matching the contract, e.g. ``tx_9f8a7b6c``."""
    return f"{prefix}_{uuid4().hex[:8]}"


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
