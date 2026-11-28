"""Threat Blacklist (Network Threat Intelligence) lookups and upserts."""

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ThreatBlacklist, new_id
from app.schemas.ai import ExtractedEntities
from app.schemas.common import BlacklistStatus, EntityType
from app.schemas.ops import BlacklistEntry

_STATUS_RANK = {
    BlacklistStatus.NONE: 0,
    BlacklistStatus.SUSPECTED: 1,
    BlacklistStatus.CONFIRMED_BLACKLISTED: 2,
}


def normalize_entity(entity_type: EntityType, value: str) -> str:
    value = value.strip()
    if entity_type == EntityType.URL:
        return value.lower().rstrip("/")
    digits = re.sub(r"\D", "", value)
    if entity_type == EntityType.PHONE and digits.startswith("84"):
        digits = "0" + digits[2:]
    return digits


def to_entry(row: ThreatBlacklist) -> BlacklistEntry:
    return BlacklistEntry(
        id=row.id,
        entity_type=EntityType(row.entity_type),
        entity_value=row.entity_value,
        report_count=row.report_count,
        scam_pattern=row.scam_pattern,
        status=BlacklistStatus(row.status),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def find(
    db: AsyncSession, entity_type: EntityType, value: str
) -> ThreatBlacklist | None:
    return await db.scalar(
        select(ThreatBlacklist).where(
            ThreatBlacklist.entity_type == entity_type.value,
            ThreatBlacklist.entity_value == normalize_entity(entity_type, value),
        )
    )


async def get_status(db: AsyncSession, entity_type: EntityType, value: str) -> BlacklistStatus:
    row = await find(db, entity_type, value)
    return BlacklistStatus(row.status) if row else BlacklistStatus.NONE


async def upsert(
    db: AsyncSession,
    entity_type: EntityType,
    value: str,
    *,
    scam_pattern: str,
    status: BlacklistStatus,
    count_report: bool = True,
) -> ThreatBlacklist:
    """Insert or update an entity; status only ever escalates (suspected -> confirmed)."""
    row = await find(db, entity_type, value)
    if row is None:
        row = ThreatBlacklist(
            id=new_id("bl"),
            entity_type=entity_type.value,
            entity_value=normalize_entity(entity_type, value),
            report_count=1,
            scam_pattern=scam_pattern,
            status=status.value,
        )
        db.add(row)
    else:
        if count_report:
            row.report_count += 1
        if _STATUS_RANK[status] > _STATUS_RANK[BlacklistStatus(row.status)]:
            row.status = status.value
        row.scam_pattern = scam_pattern or row.scam_pattern
    await db.flush()
    return row


async def upsert_entities(
    db: AsyncSession, entities: ExtractedEntities, *, scam_pattern: str
) -> int:
    pairs = (
        [(EntityType.BANK_ACCOUNT, v) for v in entities.bank_accounts]
        + [(EntityType.PHONE, v) for v in entities.phones]
        + [(EntityType.URL, v) for v in entities.urls]
    )
    seen: set[tuple[EntityType, str]] = set()
    for entity_type, value in pairs:
        key = (entity_type, normalize_entity(entity_type, value))
        if not key[1] or key in seen:
            continue
        seen.add(key)
        await upsert(
            db, entity_type, value, scam_pattern=scam_pattern, status=BlacklistStatus.SUSPECTED
        )
    return len(seen)


async def list_entries(
    db: AsyncSession,
    *,
    entity_type: EntityType | None = None,
    status: BlacklistStatus | None = None,
    q: str | None = None,
) -> list[BlacklistEntry]:
    stmt = select(ThreatBlacklist).order_by(
        ThreatBlacklist.report_count.desc(), ThreatBlacklist.updated_at.desc()
    )
    if entity_type:
        stmt = stmt.where(ThreatBlacklist.entity_type == entity_type.value)
    if status:
        stmt = stmt.where(ThreatBlacklist.status == status.value)
    if q:
        stmt = stmt.where(ThreatBlacklist.entity_value.contains(q.strip().lower()))
    rows = (await db.scalars(stmt)).all()
    return [to_entry(r) for r in rows]
