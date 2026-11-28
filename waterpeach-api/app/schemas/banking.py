"""DTOs for Phân hệ 1 (Mobile Banking) and the B2B Risk API."""

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.ai import GuardianDecision, RiskLevel, TransactionStatus
from app.schemas.common import BlacklistStatus, OpsDecision, UserRole, VNDateTime


class RecentTransaction(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tx_id: str
    recipient_name: str
    amount: int
    status: TransactionStatus
    created_at: VNDateTime


class UserProfile(BaseModel):
    """Victim-only Mobile Banking home screen (includes balance)."""

    model_config = ConfigDict(from_attributes=True)

    user_id: str
    name: str
    role: UserRole
    phone: str
    account_number: str | None
    bank_name: str | None
    balance: int
    protection_threshold: int
    sensitive_hours_enabled: bool
    recent_transactions: list[RecentTransaction] = Field(default_factory=list)


class AccountLookupResponse(BaseModel):
    account_number: str
    bank_name: str
    account_holder_name: str
    is_familiar_recipient: bool
    blacklist_status: BlacklistStatus
    warning_banner: str | None = None


class TransferRequest(BaseModel):
    """Shared by ``POST /transactions/transfer`` and ``POST /risk/evaluate``."""

    sender_id: str = Field(..., min_length=1, max_length=32)
    recipient_name: str = Field(..., min_length=1, max_length=200)
    recipient_account: str = Field(..., min_length=4, max_length=32)
    recipient_bank: str = Field(default="", max_length=100)
    amount: int = Field(..., gt=0, description="Transfer amount in VND")
    transfer_note: str = Field(default="", max_length=500)
    device_id: str | None = Field(default=None, max_length=64)
    timestamp: str | None = Field(default=None, description="Client timestamp (informational)")
    in_active_call: bool = Field(default=False, description="Telemetry: sender is on a call")
    is_copy_pasted_account: bool = Field(default=False, description="Telemetry: pasted account")


class RiskEvaluateRequest(TransferRequest):
    partner_tx_ref: str = Field(..., min_length=1, max_length=64)


class TxAiAnalysis(BaseModel):
    risk_score: int = 0
    risk_level: RiskLevel = RiskLevel.LOW
    scam_category: str = ""
    reasoning_for_victim: str = ""
    reasoning_for_guardian: str = ""
    detected_signals: list[str] = Field(default_factory=list)
    used_fallback: bool = False


class TransactionDetail(BaseModel):
    tx_id: str
    sender_id: str
    sender_name: str
    recipient_name: str
    recipient_account: str
    recipient_bank: str
    amount: int
    transfer_note: str
    status: TransactionStatus
    cooling_off_expires_at: VNDateTime | None = None
    ai_risk_score: int
    ai_analysis: TxAiAnalysis
    guardian_decision: GuardianDecision
    ops_decision: OpsDecision
    blacklist_hit: bool = False
    guardian_notified: bool = False
    created_at: VNDateTime


class RiskEvaluateResponse(BaseModel):
    tx_id: str
    partner_tx_ref: str
    status: TransactionStatus
    cooling_off_seconds: int
    blacklist_hit: bool
    ai_analysis: TxAiAnalysis
    guardian_notified: bool
