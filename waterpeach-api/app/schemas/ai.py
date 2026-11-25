from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class TransactionStatus(StrEnum):
    COMPLETED = "completed"
    COOLING_OFF = "cooling_off"
    BLOCKED = "blocked"
    RELEASED = "released"


class PsychologicalTactic(StrEnum):
    AUTHORITY = "AUTHORITY"
    URGENCY = "URGENCY"
    FEAR = "FEAR"
    GREED = "GREED"
    RECIPROCITY_COMMITMENT = "RECIPROCITY_COMMITMENT"


class VictimAgeGroup(StrEnum):
    UNDER_18 = "under_18"
    STUDENT_18_25 = "18_25_student"
    ADULT_26_55 = "26_55_adult"
    SENIOR_55_PLUS = "55_plus_senior"


class GuardianRelationship(StrEnum):
    PARENT_OF_VICTIM = "parent_of_victim"
    CHILD_OF_VICTIM = "child_of_victim"
    SPOUSE = "spouse"
    OTHER = "other"


class RecipientEntityType(StrEnum):
    INDIVIDUAL = "INDIVIDUAL"
    MERCHANT_HKD = "MERCHANT_HKD"
    CORPORATION = "CORPORATION"
    UNKNOWN = "UNKNOWN"


class ScamVerdict(StrEnum):
    SAFE = "SAFE"
    SUSPICIOUS = "SUSPICIOUS"
    HIGH_RISK_SCAM = "HIGH_RISK_SCAM"


class GuardianDecision(StrEnum):
    PENDING = "pending"
    FLAG_SCAM = "flag_scam"
    APPROVE_SAFE = "approve_safe"
    HOLD_VERIFY = "hold_verify"


class PriorityBadge(StrEnum):
    CRITICAL_GUARDIAN_FLAGGED = "CRITICAL_GUARDIAN_FLAGGED"
    HIGH_RISK_PENDING = "HIGH_RISK_PENDING"
    MEDIUM_REVIEW = "MEDIUM_REVIEW"
    AUTO_RESOLVED_SAFE = "AUTO_RESOLVED_SAFE"


class PersonaContext(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    victim_age_group: VictimAgeGroup = VictimAgeGroup.SENIOR_55_PLUS
    guardian_relationship: GuardianRelationship = GuardianRelationship.CHILD_OF_VICTIM


class RelationshipContext(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    prior_tx_count: int = Field(default=0, ge=0)
    protection_threshold: int = Field(default=5_000_000, gt=0)
    blacklist_hit: bool = False
    blacklist_status: str = "none"


class VelocityContext(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tx_count_15m: int = Field(default=1, ge=0)
    cumulative_unfamiliar_amount_60m: int = Field(default=0, ge=0)
    seconds_since_last_tx: int | None = Field(default=None, ge=0)
    is_sensitive_hours: bool = False


class TelemetryContext(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    in_active_call: bool = False
    is_copy_pasted_account: bool = False


class TxRiskRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sender_id: str = Field(default="usr_minh_01", max_length=64)
    amount: int = Field(..., gt=0, description="Transfer amount in VND")
    balance: int | None = Field(default=None, ge=0, description="Sender balance in VND")
    recipient_name: str = Field(..., min_length=1, max_length=200)
    recipient_account: str = Field(..., min_length=4, max_length=32)
    recipient_bank: str = Field(default="", max_length=100)
    recipient_tax_code: str | None = Field(default=None, max_length=32)
    transfer_note: str = Field(default="", max_length=500)
    persona_context: PersonaContext = Field(default_factory=PersonaContext)
    relationship_context: RelationshipContext = Field(default_factory=RelationshipContext)
    velocity_context: VelocityContext = Field(default_factory=VelocityContext)
    telemetry_context: TelemetryContext = Field(default_factory=TelemetryContext)
    track_velocity: bool = Field(
        default=False,
        description="Whether to record this evaluation in the in-memory sliding-window tracker",
    )


class TxRiskAnalysis(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    risk_score: int = Field(..., ge=0, le=100)
    risk_level: RiskLevel
    recommended_status: TransactionStatus
    cooling_off_seconds: int = Field(default=0, ge=0)
    scam_category: str
    recipient_entity_type: RecipientEntityType
    merchant_verified: bool = False
    detected_signals: list[str] = Field(default_factory=list)
    reasoning_for_victim: str
    reasoning_for_guardian: str
    used_fallback: bool = False


class ForensicAnalysis(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    software_signature: str | None = None
    ela_anomaly_score: float = Field(default=0.0, ge=0.0, le=100.0)
    tampering_suspected: bool = False
    forensic_note: str = "Không phát hiện dấu hiệu chỉnh sửa ảnh bất thường."


class TacticDetected(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tactic: PsychologicalTactic
    evidence: str


class ExtractedEntities(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    bank_accounts: list[str] = Field(default_factory=list)
    phones: list[str] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)


class CitationItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    title: str
    url: str


class WebGroundingIntel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    searched: bool = False
    summary: str = ""
    citations: list[CitationItem] = Field(default_factory=list)


class ScamAnalyzeRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    raw_text: str | None = Field(default=None, max_length=4000)
    image_base64: str | None = None
    image_mime_type: str | None = None
    persona_context: PersonaContext = Field(default_factory=PersonaContext)
    enable_web_search: bool = False


class ScamAnalysisResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    verdict: ScamVerdict
    risk_score: int = Field(..., ge=0, le=100)
    scam_category: str
    summary: str
    forensic_analysis: ForensicAnalysis | None = None
    tactics_detected: list[TacticDetected] = Field(default_factory=list)
    extracted_entities: ExtractedEntities = Field(default_factory=ExtractedEntities)
    web_grounding_intel: WebGroundingIntel | None = None
    advice_for_family: str
    used_fallback: bool = False


class OpsCopilotRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tx_id: str = Field(..., min_length=1, max_length=64)
    victim_name: str = Field(default="Khách hàng", max_length=100)
    amount: int = Field(..., gt=0)
    recipient_name: str = Field(..., max_length=200)
    recipient_account: str = Field(..., max_length=32)
    transfer_note: str = Field(default="", max_length=500)
    ai_risk_score: int = Field(..., ge=0, le=100)
    scam_category: str = "SUSPICIOUS_TRANSFER"
    guardian_decision: GuardianDecision = GuardianDecision.PENDING
    guardian_note: str | None = None
    matched_reports_count: int = Field(default=0, ge=0)
    persona_context: PersonaContext = Field(default_factory=PersonaContext)
    scam_summary: str | None = None


class DeescalationCopilot(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    victim_psychological_state: str
    call_script: str
    guidance_sms: str
    verification_questions: list[str] = Field(default_factory=list)


class OpsCopilotBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tx_id: str
    priority_badge: PriorityBadge
    case_summary: str
    recommended_action: str
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    deescalation_copilot: DeescalationCopilot
    used_fallback: bool = False


class TaxLookupResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    found: bool = False
    tax_code: str
    legal_name: str | None = None
    status: str | None = None
    address: str | None = None
    error: str | None = None


class UrlRiskResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    url: str
    risk_score: int = Field(default=0, ge=0, le=100)
    is_suspicious: bool = False
    triggered_features: list[str] = Field(default_factory=list)


class VerifyEntityRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    recipient_name: str | None = Field(default=None, max_length=200)
    tax_code: str | None = Field(default=None, max_length=32)
    url: str | None = Field(default=None, max_length=500)
    phone: str | None = Field(default=None, max_length=32)
    enable_web_search: bool = False


class VerifyEntityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    recipient_entity_type: RecipientEntityType = RecipientEntityType.UNKNOWN
    tax_lookup: TaxLookupResult | None = None
    url_risk: UrlRiskResult | None = None
    web_grounding_intel: WebGroundingIntel | None = None


# --- Internal Gemini Structured Output Schemas ---


class LLMTxSemanticOutput(BaseModel):
    semantic_risk_score: int = Field(..., ge=0, le=45)
    scam_category: str
    is_coercive_authority_jargon: bool = False
    is_casual_peer_note: bool = False
    reasoning_for_victim: str
    reasoning_for_guardian: str


class LLMScamOutput(BaseModel):
    verdict: ScamVerdict
    risk_score: int = Field(..., ge=0, le=100)
    scam_category: str
    summary: str
    tactics_detected: list[TacticDetected] = Field(default_factory=list)
    extracted_entities: ExtractedEntities = Field(default_factory=ExtractedEntities)
    advice_for_family: str


class LLMOpsCopilotOutput(BaseModel):
    case_summary: str
    recommended_action: str
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    deescalation_copilot: DeescalationCopilot
