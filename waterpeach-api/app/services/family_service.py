"""Trusted Circle management, Guardian Hub decisions and the family safety feed."""

from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.security import fold_vietnamese_accents
from app.core.errors import conflict, forbidden, not_found
from app.models import FamilyLink, ScamReport, Transaction, User, ensure_utc, new_id, utcnow
from app.schemas.ai import GuardianDecision, GuardianRelationship, TransactionStatus
from app.schemas.common import OpsDecision, UserRole
from app.schemas.family import (
    AddMemberRequest,
    DeleteMemberResponse,
    FamilyLinkOut,
    GuardianAlert,
    GuardianAlertsResponse,
    GuardianDecisionRequest,
    GuardianDecisionResponse,
    ProtectionSettings,
    SafetyFeedItem,
    SafetyFeedResponse,
    TrustedCircleResponse,
    UpdateSettingsRequest,
)
from app.services import ops_service, transaction_service
from app.services.realtime import EventType, get_event_bus
from app.services.transaction_service import event_payload, get_transaction, get_user

HOLD_VERIFY_EXTENSION = timedelta(minutes=30)

_RELATIONSHIP_KEYWORDS: tuple[tuple[tuple[str, ...], GuardianRelationship], ...] = (
    (("con", "chau"), GuardianRelationship.CHILD_OF_VICTIM),
    (("bo", "me", "ba", "cha"), GuardianRelationship.PARENT_OF_VICTIM),
    (("vo", "chong"), GuardianRelationship.SPOUSE),
)


def infer_guardian_relationship(label: str) -> GuardianRelationship:
    """Map a free-text label such as "Con gái" (guardian's relation to the victim)."""
    words = fold_vietnamese_accents(label).lower().split()
    if not words:
        return GuardianRelationship.OTHER
    for keywords, relationship in _RELATIONSHIP_KEYWORDS:
        if words[0] in keywords:
            return relationship
    return GuardianRelationship.OTHER


def _link_out(link: FamilyLink) -> FamilyLinkOut:
    return FamilyLinkOut(
        link_id=link.id,
        guardian_id=link.guardian_id,
        guardian_name=link.guardian.name,
        guardian_phone=link.guardian.phone,
        relationship=link.relationship,
        privacy_mode=link.privacy_mode,
    )


async def _get_victim(db: AsyncSession, victim_id: str) -> User:
    user = await get_user(db, victim_id)
    if user.role != UserRole.VICTIM.value:
        raise forbidden("ROLE_NOT_ALLOWED", "Trusted Circle belongs to a protected member")
    return user


async def _get_guardian(db: AsyncSession, guardian_id: str) -> User:
    user = await get_user(db, guardian_id)
    if user.role != UserRole.GUARDIAN.value:
        raise forbidden("ROLE_NOT_ALLOWED", "Only guardians can use the Guardian Hub")
    return user


# ----------------------------------------------------------------------------- trusted circle


async def get_trusted_circle(db: AsyncSession, victim_id: str) -> TrustedCircleResponse:
    victim = await _get_victim(db, victim_id)
    links = await transaction_service.active_links_for_victim(db, victim_id)
    return TrustedCircleResponse(
        victim_id=victim.id,
        victim_name=victim.name,
        members=[_link_out(link) for link in links],
        settings=ProtectionSettings(
            protection_threshold=victim.protection_threshold,
            sensitive_hours_enabled=victim.sensitive_hours_enabled,
            auto_trigger_high_risk=victim.auto_trigger_high_risk,
        ),
    )


async def add_member(db: AsyncSession, req: AddMemberRequest) -> FamilyLinkOut:
    victim = await _get_victim(db, req.victim_id)
    guardian = await db.scalar(select(User).where(User.phone == req.guardian_phone))
    if guardian is None:
        guardian = User(
            id=new_id("usr"),
            name=req.guardian_name,
            role=UserRole.GUARDIAN.value,
            phone=req.guardian_phone,
            age_group="26_55_adult",
        )
        db.add(guardian)
    elif guardian.role != UserRole.GUARDIAN.value:
        raise conflict("PHONE_IN_USE", "This phone number belongs to a non-guardian account")
    if guardian.id == victim.id:
        raise conflict("PHONE_IN_USE", "A member cannot guard themselves")

    link = FamilyLink(
        id=new_id("lnk"),
        victim_id=victim.id,
        guardian_id=guardian.id,
        relationship=req.relationship,
        guardian_relationship=infer_guardian_relationship(req.relationship).value,
    )
    link.guardian = guardian
    link.victim = victim
    db.add(link)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise conflict("MEMBER_EXISTS", "Guardian is already in this Trusted Circle") from exc
    return _link_out(link)


async def remove_member(db: AsyncSession, link_id: str) -> DeleteMemberResponse:
    link = await db.get(FamilyLink, link_id)
    if link is None:
        raise not_found("LINK_NOT_FOUND", "Family link not found")
    await db.delete(link)
    await db.commit()
    return DeleteMemberResponse(deleted=True, link_id=link_id)


async def update_settings(db: AsyncSession, req: UpdateSettingsRequest) -> ProtectionSettings:
    victim = await _get_victim(db, req.victim_id)
    if req.protection_threshold is not None:
        victim.protection_threshold = req.protection_threshold
    if req.sensitive_hours_enabled is not None:
        victim.sensitive_hours_enabled = req.sensitive_hours_enabled
    if req.auto_trigger_high_risk is not None:
        victim.auto_trigger_high_risk = req.auto_trigger_high_risk
    await db.commit()
    return ProtectionSettings(
        protection_threshold=victim.protection_threshold,
        sensitive_hours_enabled=victim.sensitive_hours_enabled,
        auto_trigger_high_risk=victim.auto_trigger_high_risk,
    )


# ----------------------------------------------------------------------------- guardian hub


async def _guardian_links(db: AsyncSession, guardian_id: str) -> list[FamilyLink]:
    rows = await db.scalars(
        select(FamilyLink).where(
            FamilyLink.guardian_id == guardian_id, FamilyLink.status == "active"
        )
    )
    return list(rows.unique().all())


async def get_alerts(db: AsyncSession, guardian_id: str) -> GuardianAlertsResponse:
    await _get_guardian(db, guardian_id)
    links = {link.victim_id: link for link in await _guardian_links(db, guardian_id)}
    if not links:
        return GuardianAlertsResponse(alerts=[])
    rows = await db.scalars(
        select(Transaction)
        .where(
            Transaction.sender_id.in_(links.keys()),
            Transaction.status != TransactionStatus.COMPLETED.value,
        )
        .order_by(Transaction.created_at.desc())
        .limit(50)
    )
    alerts: list[GuardianAlert] = []
    for tx in rows.unique().all():
        analysis = transaction_service.to_ai_analysis(tx)
        alerts.append(
            GuardianAlert(
                tx_id=tx.id,
                victim_id=tx.sender_id,
                victim_name=tx.sender.name,
                relationship=links[tx.sender_id].relationship,
                amount=tx.amount,
                recipient_name=tx.recipient_name,
                recipient_account=tx.recipient_account,
                recipient_bank=tx.recipient_bank,
                is_new_recipient=tx.is_new_recipient,
                status=TransactionStatus(tx.status),
                cooling_off_expires_at=tx.cooling_off_expires_at,
                ai_risk_score=tx.ai_risk_score,
                risk_level=analysis.risk_level,
                reasoning_for_guardian=analysis.reasoning_for_guardian,
                guardian_decision=GuardianDecision(tx.guardian_decision),
                created_at=tx.created_at,
            )
        )
    return GuardianAlertsResponse(alerts=alerts)


async def decide(
    db: AsyncSession, tx_id: str, req: GuardianDecisionRequest
) -> GuardianDecisionResponse:
    await _get_guardian(db, req.guardian_id)
    tx = await get_transaction(db, tx_id, for_update=True)
    if tx.sender_id not in {link.victim_id for link in await _guardian_links(db, req.guardian_id)}:
        raise forbidden("NOT_GUARDIAN_OF_SENDER", "Guardian is not in the sender's Trusted Circle")
    if tx.status != TransactionStatus.COOLING_OFF.value:
        raise conflict("TX_NOT_PENDING", "Transaction is not waiting for a guardian decision")
    if req.decision == GuardianDecision.PENDING:
        raise conflict("INVALID_DECISION", "Decision must be flag_scam, approve_safe or hold_verify")

    tx.guardian_decision = req.decision.value
    tx.guardian_note = req.note
    questions: list[str] = []
    bus = get_event_bus()

    if req.decision == GuardianDecision.FLAG_SCAM:
        await transaction_service.release_hold(db, tx)
        tx.status = TransactionStatus.BLOCKED.value
    elif req.decision == GuardianDecision.APPROVE_SAFE:
        await transaction_service.settle_hold(db, tx)
        tx.status = TransactionStatus.RELEASED.value
        tx.ops_decision = OpsDecision.FALSE_POSITIVE.value
    else:
        current = ensure_utc(tx.cooling_off_expires_at) if tx.cooling_off_expires_at else utcnow()
        base = max(current, utcnow())
        tx.cooling_off_expires_at = base + HOLD_VERIFY_EXTENSION
        brief = await ops_service.generate_brief(db, tx)
        questions = brief.deescalation_copilot.verification_questions

    await db.commit()
    bus.publish(EventType.GUARDIAN_DECISION_MADE, event_payload(tx))
    if req.decision == GuardianDecision.FLAG_SCAM:
        bus.publish(EventType.OPS_INCIDENT_ESCALATED, event_payload(tx), [UserRole.FRAUD_OPS])
    return GuardianDecisionResponse(
        tx_id=tx.id,
        status=TransactionStatus(tx.status),
        guardian_decision=GuardianDecision(tx.guardian_decision),
        ops_decision=OpsDecision(tx.ops_decision),
        cooling_off_expires_at=tx.cooling_off_expires_at,
        suggested_verification_questions=questions,
    )


# ----------------------------------------------------------------------------- safety feed


async def family_member_ids(db: AsyncSession, user: User) -> set[str]:
    if user.role == UserRole.VICTIM.value:
        victim_ids = {user.id}
    elif user.role == UserRole.GUARDIAN.value:
        victim_ids = {link.victim_id for link in await _guardian_links(db, user.id)}
    else:
        raise forbidden("ROLE_NOT_ALLOWED", "Safety feed is only for family members")
    rows = await db.scalars(
        select(FamilyLink).where(
            FamilyLink.victim_id.in_(victim_ids), FamilyLink.status == "active"
        )
    )
    return victim_ids | {link.guardian_id for link in rows.unique().all()} | {user.id}


async def get_safety_feed(db: AsyncSession, family_member_id: str) -> SafetyFeedResponse:
    user = await get_user(db, family_member_id)
    member_ids = await family_member_ids(db, user)
    rows = await db.scalars(
        select(ScamReport)
        .where(
            ScamReport.submitted_by.in_(member_ids),
            or_(ScamReport.shared_to_family.is_(True), ScamReport.submitted_by == user.id),
        )
        .order_by(ScamReport.created_at.desc())
        .limit(50)
    )
    return SafetyFeedResponse(
        items=[
            SafetyFeedItem(
                report_id=r.id,
                submitted_by=r.submitted_by,
                submitted_by_name=r.submitter.name,
                verdict=r.ai_verdict,
                risk_score=r.risk_score,
                scam_category=r.scam_category,
                summary=r.summary,
                advice_for_family=r.advice_for_family,
                tactics_detected=r.tactics_detected,
                created_at=r.created_at,
            )
            for r in rows.unique().all()
        ]
    )
