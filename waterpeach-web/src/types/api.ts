// TypeScript mirror of docs/API_CONTRACT.md and waterpeach-api/app/schemas/.
// Timestamps are ISO-8601 strings in UTC+07:00.

export type UserRole = "victim" | "guardian" | "fraud_ops";
export type RiskLevel = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type TransactionStatus = "completed" | "cooling_off" | "blocked" | "released";
export type GuardianDecision = "pending" | "flag_scam" | "approve_safe" | "hold_verify";
export type OpsDecision = "pending" | "confirmed_fraud" | "false_positive";
export type PsychologicalTactic =
  | "AUTHORITY"
  | "URGENCY"
  | "FEAR"
  | "GREED"
  | "RECIPROCITY_COMMITMENT";
export type VictimAgeGroup = "under_18" | "18_25_student" | "26_55_adult" | "55_plus_senior";
export type EntityType = "bank_account" | "phone" | "url";
export type BlacklistStatus = "none" | "suspected" | "confirmed_blacklisted";
export type ScamVerdict = "SAFE" | "SUSPICIOUS" | "HIGH_RISK_SCAM";
export type PriorityBadge =
  | "CRITICAL_GUARDIAN_FLAGGED"
  | "HIGH_RISK_PENDING"
  | "MEDIUM_REVIEW"
  | "AUTO_RESOLVED_SAFE";
export type OpsAction =
  | "cancel_and_refund"
  | "blacklist_recipient"
  | "release_transaction"
  | "export_report";
export type IncidentFilter = "all" | "active" | "auto_resolved";

export interface ApiError {
  detail: string;
  error_code: string;
}

// ---------------------------------------------------------------- Mobile Banking

export interface RecentTransaction {
  tx_id: string;
  recipient_name: string;
  amount: number;
  status: TransactionStatus;
  created_at: string;
}

export interface UserProfile {
  user_id: string;
  name: string;
  role: UserRole;
  phone: string;
  account_number: string | null;
  bank_name: string | null;
  balance: number;
  protection_threshold: number;
  sensitive_hours_enabled: boolean;
  recent_transactions: RecentTransaction[];
}

export interface AccountLookupResponse {
  account_number: string;
  bank_name: string;
  account_holder_name: string;
  is_familiar_recipient: boolean;
  blacklist_status: BlacklistStatus;
  warning_banner: string | null;
}

export interface TransferRequest {
  sender_id: string;
  recipient_name: string;
  recipient_account: string;
  recipient_bank?: string;
  amount: number;
  transfer_note?: string;
  device_id?: string | null;
  timestamp?: string | null;
  in_active_call?: boolean;
  is_copy_pasted_account?: boolean;
}

export interface RiskEvaluateRequest extends TransferRequest {
  partner_tx_ref: string;
}

export interface TxAiAnalysis {
  risk_score: number;
  risk_level: RiskLevel;
  scam_category: string;
  reasoning_for_victim: string;
  reasoning_for_guardian: string;
  detected_signals: string[];
  used_fallback: boolean;
}

export interface TransactionDetail {
  tx_id: string;
  sender_id: string;
  sender_name: string;
  recipient_name: string;
  recipient_account: string;
  recipient_bank: string;
  amount: number;
  transfer_note: string;
  status: TransactionStatus;
  cooling_off_expires_at: string | null;
  ai_risk_score: number;
  ai_analysis: TxAiAnalysis;
  guardian_decision: GuardianDecision;
  ops_decision: OpsDecision;
  blacklist_hit: boolean;
  guardian_notified: boolean;
  created_at: string;
}

export interface RiskEvaluateResponse {
  tx_id: string;
  partner_tx_ref: string;
  status: TransactionStatus;
  cooling_off_seconds: number;
  blacklist_hit: boolean;
  ai_analysis: TxAiAnalysis;
  guardian_notified: boolean;
}

// ---------------------------------------------------------------- Trusted Circle & Guardian

export interface FamilyLink {
  link_id: string;
  guardian_id: string;
  guardian_name: string;
  guardian_phone: string;
  relationship: string;
  privacy_mode: "alert_only";
  status: "active";
}

export interface ProtectionSettings {
  protection_threshold: number;
  sensitive_hours_enabled: boolean;
  auto_trigger_high_risk: boolean;
}

export interface TrustedCircleResponse {
  victim_id: string;
  victim_name: string;
  members: FamilyLink[];
  settings: ProtectionSettings;
  privacy_commitment: string;
}

export interface AddMemberRequest {
  victim_id: string;
  guardian_name: string;
  guardian_phone: string;
  relationship: string;
}

export interface DeleteMemberResponse {
  deleted: boolean;
  link_id: string;
}

export interface UpdateSettingsRequest {
  victim_id: string;
  protection_threshold?: number;
  sensitive_hours_enabled?: boolean;
  auto_trigger_high_risk?: boolean;
}

/** Privacy-First: never contains balance or normal completed transactions. */
export interface GuardianAlert {
  tx_id: string;
  victim_id: string;
  victim_name: string;
  relationship: string;
  amount: number;
  recipient_name: string;
  recipient_account: string;
  recipient_bank: string;
  is_new_recipient: boolean;
  status: TransactionStatus;
  cooling_off_expires_at: string | null;
  ai_risk_score: number;
  risk_level: RiskLevel;
  reasoning_for_guardian: string;
  guardian_decision: GuardianDecision;
  created_at: string;
}

export interface GuardianAlertsResponse {
  alerts: GuardianAlert[];
}

export interface GuardianDecisionRequest {
  guardian_id: string;
  decision: Exclude<GuardianDecision, "pending">;
  note?: string | null;
}

export interface GuardianDecisionResponse {
  tx_id: string;
  status: TransactionStatus;
  guardian_decision: GuardianDecision;
  ops_decision: OpsDecision;
  cooling_off_expires_at: string | null;
  suggested_verification_questions: string[];
}

export interface TacticDetected {
  tactic: PsychologicalTactic;
  evidence: string;
}

export interface SafetyFeedItem {
  report_id: string;
  submitted_by: string;
  submitted_by_name: string;
  verdict: ScamVerdict;
  risk_score: number;
  scam_category: string;
  summary: string;
  advice_for_family: string;
  tactics_detected: TacticDetected[];
  created_at: string;
}

export interface SafetyFeedResponse {
  items: SafetyFeedItem[];
}

// ---------------------------------------------------------------- Scam Check

export interface ExtractedEntities {
  bank_accounts: string[];
  phones: string[];
  urls: string[];
}

export interface ForensicAnalysis {
  software_signature: string | null;
  ela_anomaly_score: number;
  tampering_suspected: boolean;
  forensic_note: string;
}

export interface ScamCheckResponse {
  report_id: string;
  verdict: ScamVerdict;
  risk_score: number;
  scam_category: string;
  summary: string;
  tactics_detected: TacticDetected[];
  extracted_entities: ExtractedEntities;
  forensic_analysis: ForensicAnalysis | null;
  advice_for_family: string;
  blacklisted_entities_count: number;
  shared_to_family: boolean;
  used_fallback: boolean;
  created_at: string;
}

// ---------------------------------------------------------------- Fraud Ops

export interface OpsStats {
  critical_queue_count: number;
  auto_resolved_count: number;
  false_positive_reduction_pct: number;
}

export interface Incident {
  tx_id: string;
  priority_badge: PriorityBadge;
  victim_name: string;
  victim_age_group: VictimAgeGroup;
  amount: number;
  recipient_name: string;
  recipient_account: string;
  ai_risk_score: number;
  guardian_decision: GuardianDecision;
  ops_decision: OpsDecision;
  status: TransactionStatus;
  created_at: string;
}

export interface IncidentQueueResponse {
  stats: OpsStats;
  incidents: Incident[];
}

export interface NetworkThreatIntel {
  matched_reports_count: number;
  matched_entities: string[];
  cross_family_alert: boolean;
  blacklist_status: BlacklistStatus;
}

export interface DeescalationCopilot {
  victim_psychological_state: string;
  call_script: string;
  guidance_sms: string;
  verification_questions: string[];
}

export interface IncidentBrief {
  tx_id: string;
  priority_badge: PriorityBadge;
  case_summary: string;
  recommended_action: string;
  confidence_score: number;
  network_threat_intel: NetworkThreatIntel;
  deescalation_copilot: DeescalationCopilot;
  used_fallback: boolean;
}

export interface OpsActionRequest {
  ops_id: string;
  action: OpsAction;
  add_to_blacklist?: boolean;
  notes?: string | null;
}

export interface BlacklistEntry {
  id: string;
  entity_type: EntityType;
  entity_value: string;
  report_count: number;
  scam_pattern: string;
  status: Exclude<BlacklistStatus, "none">;
  created_at: string;
  updated_at: string;
}

export interface BlacklistListResponse {
  entries: BlacklistEntry[];
}

export interface BlacklistCreateRequest {
  entity_type: EntityType;
  entity_value: string;
  scam_pattern?: string;
  status?: Exclude<BlacklistStatus, "none">;
}

export interface IncidentReport {
  report_id: string;
  generated_at: string;
  ops_id: string;
  ops_name: string;
  action: OpsAction;
  notes: string | null;
  transaction: TransactionDetail;
  network_threat_intel: NetworkThreatIntel;
  blacklist_entry: BlacklistEntry | null;
}

export interface OpsActionResponse {
  transaction: TransactionDetail;
  blacklist_entry: BlacklistEntry | null;
  incident_report: IncidentReport;
}

// ---------------------------------------------------------------- Demo & Realtime

export interface DemoScenarioResponse {
  scenario_id: 1 | 2 | 3;
  title: string;
  next_step: string;
  transaction: TransactionDetail | null;
  scam_report: ScamCheckResponse | null;
}

export interface DemoResetResponse {
  reset: boolean;
  users: number;
  transactions: number;
}

export type RealtimeEventName =
  | "TX_COOLING_OFF_TRIGGERED"
  | "GUARDIAN_DECISION_MADE"
  | "OPS_INCIDENT_ESCALATED"
  | "OPS_CONTAINMENT_EXECUTED"
  | "FAMILY_SCAM_ALERT_SHARED"
  | "DEMO_DATA_RESET";

export interface TxEventPayload {
  tx_id: string;
  status: TransactionStatus;
  risk_level: RiskLevel;
  victim_id: string;
  amount: number;
  guardian_decision: GuardianDecision;
  ops_decision: OpsDecision;
  action?: OpsAction;
}

export interface ScamSharedPayload {
  report_id: string;
  submitted_by: string;
  submitted_by_name: string;
  verdict: ScamVerdict;
  risk_score: number;
  summary: string;
}

export interface DemoResetPayload {
  users: number;
  transactions: number;
}

interface EventEnvelope<E extends RealtimeEventName, P> {
  event: E;
  timestamp: string;
  target_roles: UserRole[];
  payload: P;
}

export type RealtimeEvent =
  | EventEnvelope<
      | "TX_COOLING_OFF_TRIGGERED"
      | "GUARDIAN_DECISION_MADE"
      | "OPS_INCIDENT_ESCALATED"
      | "OPS_CONTAINMENT_EXECUTED",
      TxEventPayload
    >
  | EventEnvelope<"FAMILY_SCAM_ALERT_SHARED", ScamSharedPayload>
  | EventEnvelope<"DEMO_DATA_RESET", DemoResetPayload>;
