"""Zero-Friction demo: seed data (Bác Minh, Anh Nam, Chị Linh), reset and 3 sample scenarios."""

from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import get_gemini_client
from app.ai.velocity_tracker import get_velocity_tracker
from app.core.errors import not_found
from app.models import FamilyLink, ScamReport, ThreatBlacklist, Transaction, User, utcnow
from app.schemas.banking import TransferRequest
from app.schemas.ops import DemoResetResponse, DemoScenarioResponse
from app.services import scam_check_service, transaction_service
from app.services.realtime import EventType, get_event_bus

VICTIM_ID = "usr_minh_01"
GUARDIAN_ID = "usr_nam_02"
OPS_ID = "usr_linh_03"
SEED_BALANCE = 85_000_000

SCENARIO_3_TEXT = (
    "[GHN] Don hang cua ban bi giu tai kho do sai dia chi. Vui long truy cap "
    "http://thue-xacminh-vn.xyz de cap nhat va thanh toan phi luu kho 25.000d trong vong 2 gio, "
    "neu khong don hang se bi huy va phat theo quy dinh cua Cuc Thue. Lien he 0987654321 "
    "hoac chuyen khoan STK 190388889999 Techcombank."
)


def _seed_users() -> list[User]:
    return [
        User(
            id=VICTIM_ID,
            name="Bác Minh",
            role="victim",
            phone="0901234567",
            account_number="1012345678",
            bank_name="MoMo / Vietcombank",
            balance=SEED_BALANCE,
            age_group="55_plus_senior",
            avatar="/avatars/minh.png",
            protection_threshold=5_000_000,
            sensitive_hours_enabled=True,
        ),
        User(
            id=GUARDIAN_ID,
            name="Anh Nam",
            role="guardian",
            phone="0987001122",
            age_group="26_55_adult",
            avatar="/avatars/nam.png",
        ),
        User(
            id=OPS_ID,
            name="Chị Linh",
            role="fraud_ops",
            phone="0909888777",
            age_group="26_55_adult",
            avatar="/avatars/linh.png",
        ),
    ]


def _seed_transactions() -> list[Transaction]:
    now = utcnow()
    rows = [
        ("tx_seed_01", "SIEU THI CO.OPMART", "0451000654321", "BIDV", 450_000, "Thanh toan Co.opmart", 2),
        ("tx_seed_02", "NGUYEN THI LAN", "1903456789012", "Techcombank", 2_000_000, "Tien cho chau di hoc", 4),
        ("tx_seed_03", "EVN HCMC", "0011002233445", "Vietcombank", 850_000, "Tien dien thang 11", 6),
    ]
    return [
        Transaction(
            id=tx_id,
            sender_id=VICTIM_ID,
            recipient_name=name,
            recipient_account=account,
            recipient_bank=bank,
            amount=amount,
            transfer_note=note,
            status="completed",
            is_new_recipient=False,
            ai_risk_score=5,
            ai_analysis_json={"risk_score": 5, "risk_level": "LOW", "scam_category": "NONE"},
            created_at=now - timedelta(days=days_ago),
        )
        for tx_id, name, account, bank, amount, note, days_ago in rows
    ]


async def reset(db: AsyncSession) -> DemoResetResponse:
    for model in (ScamReport, Transaction, FamilyLink, ThreatBlacklist, User):
        await db.execute(delete(model))
    db.add_all(_seed_users())
    await db.flush()
    db.add(
        FamilyLink(
            id="lnk_01",
            victim_id=VICTIM_ID,
            guardian_id=GUARDIAN_ID,
            relationship="Con trai",
            guardian_relationship="child_of_victim",
        )
    )
    db.add_all(_seed_transactions())
    db.add(
        ThreatBlacklist(
            id="bl_seed_01",
            entity_type="bank_account",
            entity_value="0123456789999",
            report_count=7,
            scam_pattern="INVESTMENT_SCAM",
            status="confirmed_blacklisted",
        )
    )
    await db.commit()
    get_velocity_tracker().clear()
    get_gemini_client().reset_state()

    users = int(await db.scalar(select(func.count()).select_from(User)) or 0)
    txs = int(await db.scalar(select(func.count()).select_from(Transaction)) or 0)
    get_event_bus().publish(EventType.DEMO_DATA_RESET, {"users": users, "transactions": txs})
    return DemoResetResponse(reset=True, users=users, transactions=txs)


async def seed_if_empty(db: AsyncSession) -> bool:
    if await db.get(User, VICTIM_ID) is not None:
        return False
    await reset(db)
    return True


async def run_scenario(db: AsyncSession, scenario_id: int) -> DemoScenarioResponse:
    if scenario_id == 1:
        outcome = await transaction_service.create_transfer(
            db,
            TransferRequest(
                sender_id=VICTIM_ID,
                recipient_name="NGUYEN VAN A",
                recipient_account="190388889999",
                recipient_bank="Techcombank",
                amount=25_000_000,
                transfer_note="Nop tien tam giu xac minh ho so",
                in_active_call=True,
                is_copy_pasted_account=True,
            ),
        )
        return DemoScenarioResponse(
            scenario_id=1,
            title="Lừa đảo mạo danh Công an",
            next_step="Anh Nam bấm Chặn (flag_scam), Chị Linh xác nhận lừa đảo và đưa STK vào Blacklist.",
            transaction=transaction_service.to_detail(
                outcome.transaction, guardian_notified=outcome.guardian_notified
            ),
        )
    if scenario_id == 2:
        outcome = await transaction_service.create_transfer(
            db,
            TransferRequest(
                sender_id=VICTIM_ID,
                recipient_name="CUA HANG XE MAY HONDA PHAT TIEN",
                recipient_account="0071000123456",
                recipient_bank="Agribank",
                amount=18_000_000,
                transfer_note="Thanh toan mua xe may Vision",
            ),
        )
        return DemoScenarioResponse(
            scenario_id=2,
            title="Giao dịch hợp lệ — giảm cảnh báo giả",
            next_step="Anh Nam bấm An toàn (approve_safe): giải ngân ngay, Fraud Ops tự đóng case.",
            transaction=transaction_service.to_detail(
                outcome.transaction, guardian_notified=outcome.guardian_notified
            ),
        )
    if scenario_id == 3:
        report = await scam_check_service.analyze(
            db,
            submitted_by=VICTIM_ID,
            raw_text=SCENARIO_3_TEXT,
            file_bytes=None,
            share_to_family=True,
        )
        return DemoScenarioResponse(
            scenario_id=3,
            title="Quét tin nhắn lừa đảo shipper/thuế",
            next_step="Xem Bảng tin an toàn gia đình và Threat Blacklist của Chị Linh.",
            scam_report=report,
        )
    raise not_found("SCENARIO_NOT_FOUND", "Scenario must be 1, 2 or 3")
