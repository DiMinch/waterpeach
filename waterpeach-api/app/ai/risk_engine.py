from app.ai.client import GeminiAIClient, get_gemini_client
from app.ai.entity_verifier import classify_recipient_entity, lookup_vietqr_tax_code
from app.ai.fallbacks import fallback_tx_semantic
from app.ai.prompts import build_tx_risk_system_prompt
from app.ai.security import PromptInjectionGuard, VietnameseTextNormalizer
from app.ai.velocity_tracker import evaluate_velocity_and_structuring, get_velocity_tracker
from app.schemas.ai import (
    LLMTxSemanticOutput,
    RecipientEntityType,
    RiskLevel,
    TransactionStatus,
    TxRiskAnalysis,
    TxRiskRequest,
    VelocityContext,
)


def _merge_velocity_context(request: TxRiskRequest) -> VelocityContext:
    """Use tracked sliding-window metrics when track_velocity=True, merged with explicit fields."""
    if not request.track_velocity:
        return request.velocity_context

    tracked = get_velocity_tracker().record_and_summarize(
        sender_id=request.sender_id,
        amount=request.amount,
        recipient_account=request.recipient_account,
        is_familiar=request.relationship_context.prior_tx_count > 0,
    )
    return VelocityContext(
        tx_count_15m=max(tracked.tx_count_15m, request.velocity_context.tx_count_15m),
        cumulative_unfamiliar_amount_60m=max(
            tracked.cumulative_unfamiliar_amount_60m,
            request.velocity_context.cumulative_unfamiliar_amount_60m,
        ),
        seconds_since_last_tx=(
            request.velocity_context.seconds_since_last_tx
            if request.velocity_context.seconds_since_last_tx is not None
            else tracked.seconds_since_last_tx
        ),
        is_sensitive_hours=request.velocity_context.is_sensitive_hours,
    )


async def analyze_transaction_risk(
    request: TxRiskRequest,
    ai_client: GeminiAIClient | None = None,
) -> TxRiskAnalysis:
    """Evaluate transaction risk using the 5-Dimensional Matrix + Gemini Semantic Calibration."""
    client = ai_client or get_gemini_client()
    signals: list[str] = []
    score = 0

    # Dimension 5 (Hard-stop): Threat Blacklist
    rel = request.relationship_context
    if rel.blacklist_hit or rel.blacklist_status == "confirmed_blacklisted":
        score += 85
        signals.append("CONFIRMED_BLACKLIST_HIT")
    elif rel.blacklist_status == "suspected":
        score += 45
        signals.append("SUSPECTED_BLACKLIST_HIT")

    # Security Guard: Prompt Injection detection on transfer_note
    injection_detected = PromptInjectionGuard.detect(request.transfer_note)
    if injection_detected:
        score += 50
        signals.append("PROMPT_INJECTION_ATTEMPT")

    # Dimension 2: Payee Relationship Graph & Entity Classification (+ optional live MST check)
    recipient_type = classify_recipient_entity(request.recipient_name)
    is_unfamiliar = rel.prior_tx_count == 0
    if is_unfamiliar:
        score += 15
        signals.append("FIRST_TIME_PAYEE")

    merchant_verified = False
    if request.recipient_tax_code:
        tax_result = await lookup_vietqr_tax_code(request.recipient_tax_code)
        if tax_result.found and tax_result.status and "hoạt động" in tax_result.status.lower():
            merchant_verified = True
            signals.append("VERIFIED_ACTIVE_TAX_CODE")
        elif not tax_result.found:
            score += 20
            signals.append("INVALID_TAX_CODE")

    # Dimension 1: RFM Sliding-Window Velocity & Structuring
    vel_ctx = _merge_velocity_context(request)
    vel_score, vel_signals = evaluate_velocity_and_structuring(request.amount, rel, vel_ctx)
    score += vel_score
    signals.extend(vel_signals)

    if request.balance and request.balance > 0 and (request.amount / request.balance) >= 0.70 and is_unfamiliar:
        score += 15
        signals.append("HIGH_BALANCE_DRAIN_RATIO")

    # Dimension 3: Behavioral Coercion Telemetry
    tel = request.telemetry_context
    if tel.in_active_call:
        score += 20
        signals.append("IN_ACTIVE_CALL")
    if tel.is_copy_pasted_account:
        score += 10
        signals.append("COPY_PASTED_ACCOUNT")

    # Dimension 4: Semantic NLP (Gemini Structured Output with Fast Heuristic Fallback)
    norm_note = VietnameseTextNormalizer.normalize(request.transfer_note)
    llm_input = (
        f"Số tiền: {request.amount:,} VNĐ (Ngưỡng gia đình: {rel.protection_threshold:,} VNĐ)\n"
        f"Người nhận: {request.recipient_name} (Loại: {recipient_type.value}, "
        f"Số lần chuyển trước đây: {rel.prior_tx_count})\n"
        f"Đang trong cuộc gọi: {tel.in_active_call}\n"
        f"Nội dung chuyển khoản:\n{PromptInjectionGuard.wrap_untrusted(request.transfer_note)}"
    )
    cache_key = f"tx:{client.compute_hash(f'{request.amount}:{recipient_type}:{rel.prior_tx_count}:{norm_note}:{request.persona_context.victim_age_group}')}"

    llm_semantic = await client.generate_structured(
        system_instruction=build_tx_risk_system_prompt(request.persona_context),
        input_content=llm_input,
        schema_cls=LLMTxSemanticOutput,
        cache_key=cache_key,
        rate_limit_key=request.sender_id,
    )
    used_fallback = llm_semantic is None
    semantic = llm_semantic or fallback_tx_semantic(request, recipient_type)

    score += semantic.semantic_risk_score

    # Non-linear Interaction Factor (Phi_interaction)
    # 1. Entity-Context Mismatch: Authority/tax/police jargon to unfamiliar INDIVIDUAL >= 2M VND
    if (
        semantic.is_coercive_authority_jargon
        and recipient_type == RecipientEntityType.INDIVIDUAL
        and is_unfamiliar
        and request.amount >= 2_000_000
    ):
        score += 35
        signals.append("ENTITY_CONTEXT_MISMATCH")

    # 2. Active Coercion Signature: active call + first-time payee + >= 50% threshold
    if (
        tel.in_active_call
        and is_unfamiliar
        and request.amount >= int(0.5 * rel.protection_threshold)
    ):
        score += 25
        signals.append("ACTIVE_CALL_COERCION_SIGNATURE")

    # Trust Mitigation Factor (Psi_trust) - eliminate peer/bill-splitting false positives
    if rel.prior_tx_count >= 2 and not tel.in_active_call and not injection_detected:
        mitigation = 30 if semantic.is_casual_peer_note else 20
        score -= mitigation
        signals.append("FAMILIAR_PAYEE_TRUST_MITIGATION")

    # Verified Merchant High-Value Calibration (prevent CRITICAL scam label on verified HKD purchase)
    if (
        merchant_verified
        and recipient_type in (RecipientEntityType.MERCHANT_HKD, RecipientEntityType.CORPORATION)
        and not semantic.is_coercive_authority_jargon
        and not tel.in_active_call
        and not injection_detected
    ):
        score = min(score, 62)
        signals.append("VERIFIED_MERCHANT_HIGH_VALUE")

    final_score = max(0, min(100, score))

    if final_score >= 80:
        risk_level = RiskLevel.CRITICAL
        status = TransactionStatus.BLOCKED if rel.blacklist_hit else TransactionStatus.COOLING_OFF
        cooling_seconds = 0 if status == TransactionStatus.BLOCKED else 900
    elif final_score >= 60:
        risk_level = RiskLevel.HIGH
        status = TransactionStatus.COOLING_OFF
        cooling_seconds = 900
    elif final_score >= 35:
        risk_level = RiskLevel.MEDIUM
        # Trigger guardian verification when exceeding protection threshold on unfamiliar payee
        if is_unfamiliar and ("THRESHOLD_EXCEEDED" in signals or "CUMULATIVE_THRESHOLD_EXCEEDED" in signals):
            status = TransactionStatus.COOLING_OFF
            cooling_seconds = 900
        else:
            status = TransactionStatus.COMPLETED
            cooling_seconds = 0
    else:
        risk_level = RiskLevel.LOW
        status = TransactionStatus.COMPLETED
        cooling_seconds = 0

    return TxRiskAnalysis(
        risk_score=final_score,
        risk_level=risk_level,
        recommended_status=status,
        cooling_off_seconds=cooling_seconds,
        scam_category=semantic.scam_category,
        recipient_entity_type=recipient_type,
        merchant_verified=merchant_verified,
        detected_signals=list(dict.fromkeys(signals)),
        reasoning_for_victim=semantic.reasoning_for_victim,
        reasoning_for_guardian=semantic.reasoning_for_guardian,
        used_fallback=used_fallback,
    )
