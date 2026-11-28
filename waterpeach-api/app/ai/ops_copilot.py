from app.ai.client import GeminiAIClient, get_gemini_client
from app.ai.fallbacks import fallback_ops_copilot
from app.ai.prompts import build_ops_copilot_system_prompt
from app.ai.security import PromptInjectionGuard
from app.schemas.ai import (
    GuardianDecision,
    LLMOpsCopilotOutput,
    OpsCopilotBrief,
    OpsCopilotRequest,
    PriorityBadge,
)


def compute_priority_badge(request: OpsCopilotRequest) -> PriorityBadge:
    """Deterministically triage incident priority using Guardian signal + AI score."""
    if request.guardian_decision == GuardianDecision.APPROVE_SAFE:
        return PriorityBadge.AUTO_RESOLVED_SAFE
    if request.guardian_decision == GuardianDecision.FLAG_SCAM:
        return PriorityBadge.CRITICAL_GUARDIAN_FLAGGED
    if request.ai_risk_score >= 75 or request.matched_reports_count > 0:
        return PriorityBadge.HIGH_RISK_PENDING
    return PriorityBadge.MEDIUM_REVIEW


async def generate_ops_copilot_brief(
    request: OpsCopilotRequest,
    ai_client: GeminiAIClient | None = None,
) -> OpsCopilotBrief:
    """Generate AI Case Brief and adaptive De-escalation Copilot script for Fraud Ops."""
    client = ai_client or get_gemini_client()
    priority_badge = compute_priority_badge(request)

    llm_input = (
        f"Mã giao dịch: {request.tx_id}\n"
        f"Khách hàng: {request.victim_name} | Số tiền: {request.amount:,} VNĐ\n"
        f"Người nhận: {request.recipient_name} ({request.recipient_account})\n"
        f"Điểm rủi ro AI: {request.ai_risk_score}/100 | Nhóm kịch bản: {request.scam_category}\n"
        f"Phản hồi người giám hộ: {request.guardian_decision.value}\n"
        f"Ghi chú người giám hộ: {PromptInjectionGuard.wrap_untrusted(request.guardian_note or '')}\n"
        f"Số báo cáo trùng khớp trên mạng lưới: {request.matched_reports_count}\n"
        f"Nội dung chuyển khoản: {PromptInjectionGuard.wrap_untrusted(request.transfer_note)}\n"
        f"Tóm tắt bằng chứng đa phương thức: {PromptInjectionGuard.wrap_untrusted(request.scam_summary or '')}"
    )

    cache_key = (
        f"ops:{client.compute_hash(f'{request.tx_id}:{request.guardian_decision}:{request.ai_risk_score}:{request.persona_context.victim_age_group}')}"
    )

    llm_output = await client.generate_structured(
        system_instruction=build_ops_copilot_system_prompt(request.persona_context),
        input_content=llm_input,
        schema_cls=LLMOpsCopilotOutput,
        cache_key=cache_key,
        rate_limit_key=f"ops:{request.tx_id}",
    )

    used_fallback = llm_output is None
    parsed = llm_output or fallback_ops_copilot(request)

    return OpsCopilotBrief(
        tx_id=request.tx_id,
        priority_badge=priority_badge,
        case_summary=parsed.case_summary,
        recommended_action=parsed.recommended_action,
        confidence_score=parsed.confidence_score,
        deescalation_copilot=parsed.deescalation_copilot,
        used_fallback=used_fallback,
    )
