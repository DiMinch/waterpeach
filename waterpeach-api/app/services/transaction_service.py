"""Mobile Banking core: profile, account lookup and the transaction state machine.

State machine::

    completed                          (low risk, settled immediately)
    cooling_off -> blocked | released  (Social Circuit Breaker, funds held on the sender)
    blocked                            (confirmed blacklist hit, nothing debited)

When the cooling-off window expires without a decision the transaction stays
``cooling_off`` (funds remain held) until a guardian or Fraud Ops acts.
"""

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.risk_engine import analyze_transaction_risk
from app.core.errors import bad_request, forbidden, not_found
from app.models import FamilyLink, Transaction, User, new_id, utcnow
from app.schemas.ai import (
    GuardianRelationship,
    PersonaContext,
    RelationshipContext,
    TelemetryContext,
    TransactionStatus,
    TxRiskAnalysis,
    TxRiskRequest,
    VelocityContext,
    VictimAgeGroup,
)
from app.schemas.banking import (
    AccountLookupResponse,
    RecentTransaction,
    TransactionDetail,
    TransferRequest,
    TxAiAnalysis,
    UserProfile,
)
from app.schemas.common import VN_TZ, BlacklistStatus, EntityType, UserRole
from app.services import blacklist_service
from app.services.realtime import EventType, get_event_bus

SETTLED_STATUSES = (TransactionStatus.COMPLETED.value, TransactionStatus.RELEASED.value)
SENSITIVE_HOURS = (22, 6)  # 22:00 -> 06:00 Vietnam time

# Mock NAPAS account-name directory used by the demo; unknown accounts get a masked name.
ACCOUNT_DIRECTORY: dict[str, str] = {
    "190388889999": "NGUYEN VAN A",
    "0071000123456": "CUA HANG XE MAY HONDA PHAT TIEN",
    "1903456789012": "NGUYEN THI LAN",
    "0451000654321": "SIEU THI CO.OPMART",
}

BLACKLIST_BANNERS = {
    BlacklistStatus.SUSPECTED: (
        "Tài khoản này từng bị cộng đồng báo cáo nghi lừa đảo. Bác hãy hỏi người thân trước khi chuyển."
    ),
    BlacklistStatus.CONFIRMED_BLACKLISTED: (
        "Tài khoản này đã bị xác nhận lừa đảo. Giao dịch tới tài khoản này sẽ bị chặn."
    ),
}


@dataclass
class TransferOutcome:
    transaction: Transaction
    analysis: TxRiskAnalysis
    guardian_notified: bool


def resolve_holder_name(account: str) -> str:
    digits = blacklist_service.normalize_entity(EntityType.BANK_ACCOUNT, account)
    return ACCOUNT_DIRECTORY.get(digits, f"CHU TAI KHOAN ****{digits[-4:]}")


async def get_user(db: AsyncSession, user_id: str, *, for_update: bool = False) -> User:
    stmt = select(User).where(User.id == user_id)
    if for_update:
        stmt = stmt.with_for_update()
    user = await db.scalar(stmt)
    if user is None:
        raise not_found("USER_NOT_FOUND", f"User {user_id} not found")
    return user


async def get_transaction(
    db: AsyncSession, tx_id: str, *, for_update: bool = False
) -> Transaction:
    """Load a transaction; ``for_update`` locks its row so concurrent decisions serialize."""
    stmt = select(Transaction).where(Transaction.id == tx_id)
    if for_update:
        stmt = stmt.with_for_update(of=Transaction)
    tx = await db.scalar(stmt)
    if tx is None:
        raise not_found("TX_NOT_FOUND", "Transaction not found")
    return tx


async def active_links_for_victim(db: AsyncSession, victim_id: str) -> list[FamilyLink]:
    rows = await db.scalars(
        select(FamilyLink)
        .where(FamilyLink.victim_id == victim_id, FamilyLink.status == "active")
        .order_by(FamilyLink.created_at)
    )
    return list(rows.unique().all())


async def count_prior_transfers(db: AsyncSession, sender_id: str, account: str) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(Transaction)
            .where(
                Transaction.sender_id == sender_id,
                Transaction.recipient_account == account,
                Transaction.status.in_(SETTLED_STATUSES),
            )
        )
        or 0
    )


def to_ai_analysis(tx: Transaction) -> TxAiAnalysis:
    data = tx.ai_analysis_json or {}
    return TxAiAnalysis(
        risk_score=data.get("risk_score", tx.ai_risk_score),
        risk_level=data.get("risk_level", "LOW"),
        scam_category=data.get("scam_category", ""),
        reasoning_for_victim=data.get("reasoning_for_victim", ""),
        reasoning_for_guardian=data.get("reasoning_for_guardian", ""),
        detected_signals=data.get("detected_signals", []),
        used_fallback=data.get("used_fallback", False),
    )


def to_detail(tx: Transaction, *, guardian_notified: bool = False) -> TransactionDetail:
    analysis = to_ai_analysis(tx)
    return TransactionDetail(
        tx_id=tx.id,
        sender_id=tx.sender_id,
        sender_name=tx.sender.name,
        recipient_name=tx.recipient_name,
        recipient_account=tx.recipient_account,
        recipient_bank=tx.recipient_bank,
        amount=tx.amount,
        transfer_note=tx.transfer_note,
        status=TransactionStatus(tx.status),
        cooling_off_expires_at=tx.cooling_off_expires_at,
        ai_risk_score=tx.ai_risk_score,
        ai_analysis=analysis,
        guardian_decision=tx.guardian_decision,
        ops_decision=tx.ops_decision,
        blacklist_hit="CONFIRMED_BLACKLIST_HIT" in analysis.detected_signals,
        guardian_notified=guardian_notified,
        created_at=tx.created_at,
    )


def event_payload(tx: Transaction) -> dict[str, object]:
    return {
        "tx_id": tx.id,
        "status": tx.status,
        "risk_level": to_ai_analysis(tx).risk_level.value,
        "victim_id": tx.sender_id,
        "amount": tx.amount,
        "guardian_decision": tx.guardian_decision,
        "ops_decision": tx.ops_decision,
    }


async def adjust_balance(db: AsyncSession, user_id: str, delta: int) -> bool:
    """Atomic ``balance += delta``; a debit is refused (False) if it would overdraw."""
    stmt = update(User).where(User.id == user_id).values(balance=User.balance + delta)
    if delta < 0:
        stmt = stmt.where(User.balance >= -delta)
    result = await db.execute(stmt.execution_options(synchronize_session=False))
    return result.rowcount == 1  # type: ignore[attr-defined]


async def release_hold(db: AsyncSession, tx: Transaction) -> None:
    """Return held funds to the sender (blocked / refunded). Call with ``tx`` row-locked."""
    if tx.funds_held:
        await adjust_balance(db, tx.sender_id, tx.amount)
        tx.funds_held = False


async def settle_hold(db: AsyncSession, tx: Transaction) -> None:
    """Held funds leave the account (released to the recipient). Call with ``tx`` row-locked."""
    if tx.funds_held:
        tx.funds_held = False
    elif tx.status == TransactionStatus.BLOCKED.value and not await adjust_balance(
        db, tx.sender_id, -tx.amount
    ):
        raise bad_request("INSUFFICIENT_BALANCE", "Insufficient balance to release funds")


def is_sensitive_hour(user: User) -> bool:
    if not user.sensitive_hours_enabled:
        return False
    hour = utcnow().astimezone(VN_TZ).hour
    start, end = SENSITIVE_HOURS
    return hour >= start or hour < end


async def get_profile(db: AsyncSession, user_id: str) -> UserProfile:
    user = await get_user(db, user_id)
    if user.role != UserRole.VICTIM.value:
        raise forbidden("PROFILE_VICTIM_ONLY", "Mobile Banking profile is only for the account owner")
    rows = await db.scalars(
        select(Transaction)
        .where(Transaction.sender_id == user_id)
        .order_by(Transaction.created_at.desc())
        .limit(10)
    )
    return UserProfile(
        user_id=user.id,
        name=user.name,
        role=UserRole(user.role),
        phone=user.phone,
        account_number=user.account_number,
        bank_name=user.bank_name,
        balance=user.balance,
        protection_threshold=user.protection_threshold,
        sensitive_hours_enabled=user.sensitive_hours_enabled,
        recent_transactions=[
            RecentTransaction(
                tx_id=t.id,
                recipient_name=t.recipient_name,
                amount=t.amount,
                status=TransactionStatus(t.status),
                created_at=t.created_at,
            )
            for t in rows.unique().all()
        ],
    )


async def lookup_account(
    db: AsyncSession, *, sender_id: str, bank: str, account: str
) -> AccountLookupResponse:
    await get_user(db, sender_id)
    status = await blacklist_service.get_status(db, EntityType.BANK_ACCOUNT, account)
    prior = await count_prior_transfers(db, sender_id, account)
    return AccountLookupResponse(
        account_number=account,
        bank_name=bank,
        account_holder_name=resolve_holder_name(account),
        is_familiar_recipient=prior > 0,
        blacklist_status=status,
        warning_banner=BLACKLIST_BANNERS.get(status),
    )


async def create_transfer(
    db: AsyncSession,
    req: TransferRequest,
    *,
    source: str = "web",
    partner_tx_ref: str | None = None,
) -> TransferOutcome:
    sender = await get_user(db, req.sender_id, for_update=True)
    if sender.role != UserRole.VICTIM.value:
        raise forbidden("ROLE_NOT_ALLOWED", "Only account owners can transfer money")
    if req.amount > sender.balance:
        raise bad_request("INSUFFICIENT_BALANCE", "Insufficient balance")

    links = await active_links_for_victim(db, sender.id)
    blacklist_status = await blacklist_service.get_status(
        db, EntityType.BANK_ACCOUNT, req.recipient_account
    )
    prior = await count_prior_transfers(db, sender.id, req.recipient_account)

    analysis = await analyze_transaction_risk(
        TxRiskRequest(
            sender_id=sender.id,
            amount=req.amount,
            balance=sender.balance,
            recipient_name=req.recipient_name,
            recipient_account=req.recipient_account,
            recipient_bank=req.recipient_bank,
            transfer_note=req.transfer_note,
            persona_context=PersonaContext(
                victim_age_group=VictimAgeGroup(sender.age_group),
                guardian_relationship=(
                    GuardianRelationship(links[0].guardian_relationship)
                    if links
                    else GuardianRelationship.OTHER
                ),
            ),
            relationship_context=RelationshipContext(
                prior_tx_count=prior,
                protection_threshold=sender.protection_threshold,
                blacklist_hit=blacklist_status == BlacklistStatus.CONFIRMED_BLACKLISTED,
                blacklist_status=blacklist_status.value,
            ),
            velocity_context=VelocityContext(is_sensitive_hours=is_sensitive_hour(sender)),
            telemetry_context=TelemetryContext(
                in_active_call=req.in_active_call,
                is_copy_pasted_account=req.is_copy_pasted_account,
            ),
            track_velocity=True,
        )
    )

    status = analysis.recommended_status
    tx = Transaction(
        id=new_id("tx"),
        sender_id=sender.id,
        recipient_name=req.recipient_name,
        recipient_account=req.recipient_account,
        recipient_bank=req.recipient_bank,
        amount=req.amount,
        transfer_note=req.transfer_note,
        status=status.value,
        is_new_recipient=prior == 0,
        ai_risk_score=analysis.risk_score,
        ai_analysis_json=analysis.model_dump(mode="json"),
        partner_tx_ref=partner_tx_ref,
        source=source,
    )
    tx.sender = sender
    if status in (TransactionStatus.COMPLETED, TransactionStatus.COOLING_OFF):
        sender.balance -= req.amount
        tx.funds_held = status == TransactionStatus.COOLING_OFF
    if status == TransactionStatus.COOLING_OFF:
        tx.cooling_off_expires_at = utcnow() + timedelta(seconds=analysis.cooling_off_seconds)
    db.add(tx)
    await db.commit()

    guardian_notified = status == TransactionStatus.COOLING_OFF and bool(links)
    bus = get_event_bus()
    if status == TransactionStatus.COOLING_OFF:
        bus.publish(EventType.TX_COOLING_OFF_TRIGGERED, event_payload(tx))
    elif status == TransactionStatus.BLOCKED:
        bus.publish(EventType.OPS_INCIDENT_ESCALATED, event_payload(tx))
    return TransferOutcome(transaction=tx, analysis=analysis, guardian_notified=guardian_notified)
