from datetime import UTC, datetime, timedelta, timezone
from enum import StrEnum
from typing import Annotated

from pydantic import PlainSerializer

VN_TZ = timezone(timedelta(hours=7), name="Asia/Ho_Chi_Minh")


def to_vn_time(value: datetime) -> str:
    """Serialize as ISO-8601 in UTC+7; naive values (SQLite) are treated as UTC."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(VN_TZ).isoformat(timespec="seconds")


VNDateTime = Annotated[datetime, PlainSerializer(to_vn_time, return_type=str)]


class UserRole(StrEnum):
    VICTIM = "victim"
    GUARDIAN = "guardian"
    FRAUD_OPS = "fraud_ops"


class OpsDecision(StrEnum):
    PENDING = "pending"
    CONFIRMED_FRAUD = "confirmed_fraud"
    FALSE_POSITIVE = "false_positive"


class EntityType(StrEnum):
    BANK_ACCOUNT = "bank_account"
    PHONE = "phone"
    URL = "url"


class BlacklistStatus(StrEnum):
    NONE = "none"
    SUSPECTED = "suspected"
    CONFIRMED_BLACKLISTED = "confirmed_blacklisted"


class FamilyLinkStatus(StrEnum):
    ACTIVE = "active"


class OpsAction(StrEnum):
    CANCEL_AND_REFUND = "cancel_and_refund"
    BLACKLIST_RECIPIENT = "blacklist_recipient"
    RELEASE_TRANSACTION = "release_transaction"
    EXPORT_REPORT = "export_report"


class IncidentFilter(StrEnum):
    ALL = "all"
    ACTIVE = "active"
    AUTO_RESOLVED = "auto_resolved"
