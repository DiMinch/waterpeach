"""DTOs for Trusted Circle, Guardian Hub and the family safety feed."""

from pydantic import BaseModel, Field

from app.schemas.ai import (
    GuardianDecision,
    RiskLevel,
    ScamVerdict,
    TacticDetected,
    TransactionStatus,
)
from app.schemas.common import FamilyLinkStatus, OpsDecision, VNDateTime


class FamilyLinkOut(BaseModel):
    link_id: str
    guardian_id: str
    guardian_name: str
    guardian_phone: str
    relationship: str
    privacy_mode: str = "alert_only"
    status: FamilyLinkStatus = FamilyLinkStatus.ACTIVE


class ProtectionSettings(BaseModel):
    protection_threshold: int
    sensitive_hours_enabled: bool
    auto_trigger_high_risk: bool


class TrustedCircleResponse(BaseModel):
    victim_id: str
    victim_name: str
    members: list[FamilyLinkOut]
    settings: ProtectionSettings
    privacy_commitment: str = (
        "Người giám hộ chỉ nhận cảnh báo giao dịch rủi ro, không xem được số dư "
        "hay lịch sử giao dịch thông thường."
    )


class AddMemberRequest(BaseModel):
    victim_id: str = Field(..., min_length=1, max_length=32)
    guardian_name: str = Field(..., min_length=1, max_length=100)
    guardian_phone: str = Field(..., pattern=r"^0\d{9,10}$")
    relationship: str = Field(..., min_length=1, max_length=50)


class DeleteMemberResponse(BaseModel):
    deleted: bool
    link_id: str


class UpdateSettingsRequest(BaseModel):
    victim_id: str = Field(..., min_length=1, max_length=32)
    protection_threshold: int | None = Field(default=None, ge=100_000)
    sensitive_hours_enabled: bool | None = None
    auto_trigger_high_risk: bool | None = None


class GuardianAlert(BaseModel):
    """Privacy-First: no balance, never a normal ``completed`` transaction."""

    tx_id: str
    victim_id: str
    victim_name: str
    relationship: str
    amount: int
    recipient_name: str
    recipient_account: str
    recipient_bank: str
    is_new_recipient: bool
    status: TransactionStatus
    cooling_off_expires_at: VNDateTime | None = None
    ai_risk_score: int
    risk_level: RiskLevel
    reasoning_for_guardian: str
    guardian_decision: GuardianDecision
    created_at: VNDateTime


class GuardianAlertsResponse(BaseModel):
    alerts: list[GuardianAlert]


class GuardianDecisionRequest(BaseModel):
    guardian_id: str = Field(..., min_length=1, max_length=32)
    decision: GuardianDecision
    note: str | None = Field(default=None, max_length=500)


class GuardianDecisionResponse(BaseModel):
    tx_id: str
    status: TransactionStatus
    guardian_decision: GuardianDecision
    ops_decision: OpsDecision
    cooling_off_expires_at: VNDateTime | None = None
    suggested_verification_questions: list[str] = Field(default_factory=list)


class SafetyFeedItem(BaseModel):
    report_id: str
    submitted_by: str
    submitted_by_name: str
    verdict: ScamVerdict
    risk_score: int
    scam_category: str
    summary: str
    advice_for_family: str
    tactics_detected: list[TacticDetected] = Field(default_factory=list)
    created_at: VNDateTime


class SafetyFeedResponse(BaseModel):
    items: list[SafetyFeedItem]
