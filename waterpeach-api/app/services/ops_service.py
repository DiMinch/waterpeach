"""Fraud Ops Workspace: triaged incident queue, AI Case Brief, containment and blacklist."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.ops_copilot import compute_priority_badge, generate_ops_copilot_brief
from app.core.errors import conflict, forbidden
from app.models import FamilyLink, ScamReport, Transaction, new_id, utcnow
from app.schemas.ai import (
    GuardianDecision,
    GuardianRelationship,
    OpsCopilotRequest,
    PersonaContext,
    PriorityBadge,
    TransactionStatus,
    VictimAgeGroup,
)
from app.schemas.common import (
    BlacklistStatus,
    EntityType,
    IncidentFilter,
    OpsAction,
    OpsDecision,
    UserRole,
    to_vn_time,
)
from app.schemas.ops import (
    BlacklistCreateRequest,
    BlacklistEntry,
    Incident,
    IncidentBrief,
    IncidentQueueResponse,
    NetworkThreatIntel,
    OpsActionRequest,
    OpsActionResponse,
    OpsStats,
)
from app.services import blacklist_service, transaction_service
from app.services.realtime import EventType, get_event_bus

OPEN_STATUSES = (TransactionStatus.COOLING_OFF.value, TransactionStatus.BLOCKED.value)
_REPORT_SCAN_LIMIT = 500


def _persona(tx: Transaction, link: FamilyLink | None) -> PersonaContext:
    return PersonaContext(
        victim_age_group=VictimAgeGroup(tx.sender.age_group),
        guardian_relationship=(
            GuardianRelationship(link.guardian_relationship)
            if link
            else GuardianRelationship.OTHER
        ),
    )


def _copilot_request(
    tx: Transaction, *, link: FamilyLink | None = None, matched_reports_count: int = 0
) -> OpsCopilotRequest:
    analysis = transaction_service.to_ai_analysis(tx)
    return OpsCopilotRequest(
        tx_id=tx.id,
        victim_name=tx.sender.name,
        amount=tx.amount,
        recipient_name=tx.recipient_name,
        recipient_account=tx.recipient_account,
        transfer_note=tx.transfer_note,
        ai_risk_score=tx.ai_risk_score,
        scam_category=analysis.scam_category or "SUSPICIOUS_TRANSFER",
        guardian_decision=GuardianDecision(tx.guardian_decision),
        guardian_note=tx.guardian_note,
        matched_reports_count=matched_reports_count,
        persona_context=_persona(tx, link),
    )


async def network_threat_intel(db: AsyncSession, tx: Transaction) -> NetworkThreatIntel:
    account = blacklist_service.normalize_entity(EntityType.BANK_ACCOUNT, tx.recipient_account)
    reports = (
        await db.scalars(
            select(ScamReport).order_by(ScamReport.created_at.desc()).limit(_REPORT_SCAN_LIMIT)
        )
    ).unique().all()
    matched = [
        r
        for r in reports
        if account
        in {
            blacklist_service.normalize_entity(EntityType.BANK_ACCOUNT, a)
            for a in (r.extracted_entities_json or {}).get("bank_accounts", [])
        }
    ]
    entry = await blacklist_service.find(db, EntityType.BANK_ACCOUNT, account)
    family = {tx.sender_id} | {
        link.guardian_id for link in await transaction_service.active_links_for_victim(db, tx.sender_id)
    }
    return NetworkThreatIntel(
        matched_reports_count=len(matched),
        matched_entities=[tx.recipient_account] if matched or entry else [],
        cross_family_alert=any(r.submitted_by not in family for r in matched),
        blacklist_status=BlacklistStatus(entry.status) if entry else BlacklistStatus.NONE,
    )


async def generate_brief(db: AsyncSession, tx: Transaction) -> IncidentBrief:
    intel = await network_threat_intel(db, tx)
    links = await transaction_service.active_links_for_victim(db, tx.sender_id)
    brief = await generate_ops_copilot_brief(
        _copilot_request(
            tx, link=links[0] if links else None, matched_reports_count=intel.matched_reports_count
        )
    )
    return IncidentBrief(
        tx_id=tx.id,
        priority_badge=brief.priority_badge,
        case_summary=brief.case_summary,
        recommended_action=brief.recommended_action,
        confidence_score=brief.confidence_score,
        network_threat_intel=intel,
        deescalation_copilot=brief.deescalation_copilot,
        used_fallback=brief.used_fallback,
    )


async def get_brief(db: AsyncSession, tx_id: str) -> IncidentBrief:
    return await generate_brief(db, await transaction_service.get_transaction(db, tx_id))


def _is_active(tx: Transaction) -> bool:
    return tx.status in OPEN_STATUSES and tx.ops_decision == OpsDecision.PENDING.value


def _is_auto_resolved(tx: Transaction) -> bool:
    return tx.guardian_decision == GuardianDecision.APPROVE_SAFE.value


async def list_incidents(
    db: AsyncSession, filter_: IncidentFilter = IncidentFilter.ALL
) -> IncidentQueueResponse:
    rows = (
        await db.scalars(
            select(Transaction).where(Transaction.status != TransactionStatus.COMPLETED.value)
        )
    ).unique().all()
    incidents: list[tuple[Transaction, PriorityBadge]] = [
        (tx, compute_priority_badge(_copilot_request(tx))) for tx in rows
    ]
    active = [item for item in incidents if _is_active(item[0])]
    auto_resolved = [item for item in incidents if _is_auto_resolved(item[0])]
    stats = OpsStats(
        critical_queue_count=sum(
            1
            for _, badge in active
            if badge in (PriorityBadge.CRITICAL_GUARDIAN_FLAGGED, PriorityBadge.HIGH_RISK_PENDING)
        ),
        auto_resolved_count=len(auto_resolved),
        false_positive_reduction_pct=(
            round(len(auto_resolved) / len(incidents) * 100, 1) if incidents else 0.0
        ),
    )
    selected = {
        IncidentFilter.ALL: incidents,
        IncidentFilter.ACTIVE: active,
        IncidentFilter.AUTO_RESOLVED: auto_resolved,
    }[filter_]
    selected = sorted(
        selected,
        key=lambda item: (
            item[0].guardian_decision != GuardianDecision.FLAG_SCAM.value,
            -item[0].ai_risk_score,
            -item[0].created_at.timestamp(),
        ),
    )
    return IncidentQueueResponse(
        stats=stats,
        incidents=[
            Incident(
                tx_id=tx.id,
                priority_badge=badge,
                victim_name=tx.sender.name,
                victim_age_group=tx.sender.age_group,
                amount=tx.amount,
                recipient_name=tx.recipient_name,
                recipient_account=tx.recipient_account,
                ai_risk_score=tx.ai_risk_score,
                guardian_decision=GuardianDecision(tx.guardian_decision),
                ops_decision=OpsDecision(tx.ops_decision),
                status=TransactionStatus(tx.status),
                created_at=tx.created_at,
            )
            for tx, badge in selected
        ],
    )


async def _confirm_blacklist(db: AsyncSession, tx: Transaction) -> BlacklistEntry:
    analysis = transaction_service.to_ai_analysis(tx)
    row = await blacklist_service.upsert(
        db,
        EntityType.BANK_ACCOUNT,
        tx.recipient_account,
        scam_pattern=analysis.scam_category or "OPS_CONFIRMED_FRAUD",
        status=BlacklistStatus.CONFIRMED_BLACKLISTED,
    )
    return blacklist_service.to_entry(row)


async def _block(db: AsyncSession, tx: Transaction) -> None:
    if tx.status == TransactionStatus.COOLING_OFF.value:
        await transaction_service.release_hold(db, tx)
        tx.status = TransactionStatus.BLOCKED.value


async def execute_action(
    db: AsyncSession, tx_id: str, req: OpsActionRequest
) -> OpsActionResponse:
    ops_user = await transaction_service.get_user(db, req.ops_id)
    if ops_user.role != UserRole.FRAUD_OPS.value:
        raise forbidden("ROLE_NOT_ALLOWED", "Only Fraud Ops can execute containment actions")
    tx = await transaction_service.get_transaction(db, tx_id, for_update=True)
    if req.action != OpsAction.EXPORT_REPORT and tx.status == TransactionStatus.COMPLETED.value:
        raise conflict("TX_NOT_AN_INCIDENT", "Completed transactions cannot be contained")

    entry: BlacklistEntry | None = None
    if req.action == OpsAction.CANCEL_AND_REFUND:
        if tx.status not in OPEN_STATUSES:
            raise conflict("TX_ALREADY_RESOLVED", "Transaction was already released")
        await _block(db, tx)
        tx.ops_decision = OpsDecision.CONFIRMED_FRAUD.value
    elif req.action == OpsAction.BLACKLIST_RECIPIENT:
        await _block(db, tx)
        tx.ops_decision = OpsDecision.CONFIRMED_FRAUD.value
        entry = await _confirm_blacklist(db, tx)
    elif req.action == OpsAction.RELEASE_TRANSACTION:
        if tx.status not in OPEN_STATUSES:
            raise conflict("TX_ALREADY_RESOLVED", "Transaction was already released")
        await transaction_service.settle_hold(db, tx)
        tx.status = TransactionStatus.RELEASED.value
        tx.ops_decision = OpsDecision.FALSE_POSITIVE.value

    if req.add_to_blacklist and entry is None:
        entry = await _confirm_blacklist(db, tx)
    if req.notes:
        tx.ops_notes = req.notes
    await db.commit()

    detail = transaction_service.to_detail(tx)
    intel = await network_threat_intel(db, tx)
    if req.action != OpsAction.EXPORT_REPORT or req.add_to_blacklist:
        get_event_bus().publish(
            EventType.OPS_CONTAINMENT_EXECUTED,
            {**transaction_service.event_payload(tx), "action": req.action.value},
        )
    report: dict[str, Any] = {
        "report_id": new_id("ir"),
        "generated_at": to_vn_time(utcnow()),
        "ops_id": ops_user.id,
        "ops_name": ops_user.name,
        "action": req.action.value,
        "notes": req.notes,
        "transaction": detail.model_dump(mode="json"),
        "network_threat_intel": intel.model_dump(mode="json"),
        "blacklist_entry": entry.model_dump(mode="json") if entry else None,
    }
    return OpsActionResponse(transaction=detail, blacklist_entry=entry, incident_report=report)


async def add_blacklist_entry(db: AsyncSession, req: BlacklistCreateRequest) -> BlacklistEntry:
    if req.status == BlacklistStatus.NONE:
        raise conflict("INVALID_STATUS", "Status must be suspected or confirmed_blacklisted")
    row = await blacklist_service.upsert(
        db, req.entity_type, req.entity_value, scam_pattern=req.scam_pattern, status=req.status
    )
    await db.commit()
    return blacklist_service.to_entry(row)
