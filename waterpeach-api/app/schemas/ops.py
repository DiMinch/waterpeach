"""DTOs for Scam Check, Fraud Ops Workspace, Threat Blacklist, demo and realtime events."""

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.ai import (
    DeescalationCopilot,
    ExtractedEntities,
    ForensicAnalysis,
    GuardianDecision,
    PriorityBadge,
    ScamVerdict,
    TacticDetected,
    TransactionStatus,
)
from app.schemas.banking import TransactionDetail
from app.schemas.common import (
    BlacklistStatus,
    EntityType,
    OpsAction,
    OpsDecision,
    UserRole,
    VNDateTime,
)


class ScamCheckResponse(BaseModel):
    report_id: str
    verdict: ScamVerdict
    risk_score: int
    scam_category: str
    summary: str
    tactics_detected: list[TacticDetected] = Field(default_factory=list)
    extracted_entities: ExtractedEntities = Field(default_factory=ExtractedEntities)
    forensic_analysis: ForensicAnalysis | None = None
    advice_for_family: str
    blacklisted_entities_count: int = 0
    shared_to_family: bool
    used_fallback: bool = False
    created_at: VNDateTime


class OpsStats(BaseModel):
    critical_queue_count: int
    auto_resolved_count: int
    false_positive_reduction_pct: float


class Incident(BaseModel):
    tx_id: str
    priority_badge: PriorityBadge
    victim_name: str
    victim_age_group: str
    amount: int
    recipient_name: str
    recipient_account: str
    ai_risk_score: int
    guardian_decision: GuardianDecision
    ops_decision: OpsDecision
    status: TransactionStatus
    created_at: VNDateTime


class IncidentQueueResponse(BaseModel):
    stats: OpsStats
    incidents: list[Incident]


class NetworkThreatIntel(BaseModel):
    matched_reports_count: int
    matched_entities: list[str]
    cross_family_alert: bool
    blacklist_status: BlacklistStatus


class IncidentBrief(BaseModel):
    tx_id: str
    priority_badge: PriorityBadge
    case_summary: str
    recommended_action: str
    confidence_score: float
    network_threat_intel: NetworkThreatIntel
    deescalation_copilot: DeescalationCopilot
    used_fallback: bool = False


class OpsActionRequest(BaseModel):
    ops_id: str = Field(..., min_length=1, max_length=32)
    action: OpsAction
    add_to_blacklist: bool = False
    notes: str | None = Field(default=None, max_length=1000)


class BlacklistEntry(BaseModel):
    id: str
    entity_type: EntityType
    entity_value: str
    report_count: int
    scam_pattern: str
    status: BlacklistStatus
    created_at: VNDateTime
    updated_at: VNDateTime


class BlacklistListResponse(BaseModel):
    entries: list[BlacklistEntry]


class BlacklistCreateRequest(BaseModel):
    entity_type: EntityType
    entity_value: str = Field(..., min_length=3, max_length=500)
    scam_pattern: str = Field(default="MANUAL_REPORT", max_length=100)
    status: BlacklistStatus = BlacklistStatus.CONFIRMED_BLACKLISTED


class OpsActionResponse(BaseModel):
    transaction: TransactionDetail
    blacklist_entry: BlacklistEntry | None = None
    incident_report: dict[str, Any]


class DemoScenarioResponse(BaseModel):
    scenario_id: int
    title: str
    next_step: str
    transaction: TransactionDetail | None = None
    scam_report: ScamCheckResponse | None = None


class DemoResetResponse(BaseModel):
    reset: bool
    users: int
    transactions: int


class RealtimeEvent(BaseModel):
    event: str
    timestamp: VNDateTime
    target_roles: list[UserRole]
    payload: dict[str, Any]
