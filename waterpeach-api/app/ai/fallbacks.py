from app.ai.knowledge_base import (
    CASUAL_PEER_PATTERNS,
    COERCIVE_AUTHORITY_PATTERNS,
    FAKE_DELIVERY_OR_BILL_PATTERNS,
    FEAR_MARKERS,
    MERCHANT_PURCHASE_PATTERNS,
    TASK_SCAM_AND_GREED_PATTERNS,
    URGENCY_MARKERS,
)
from app.ai.prompts import describe_persona_tone
from app.ai.security import VietnameseTextNormalizer
from app.schemas.ai import (
    DeescalationCopilot,
    ExtractedEntities,
    ForensicAnalysis,
    GuardianDecision,
    LLMOpsCopilotOutput,
    LLMScamOutput,
    LLMTxSemanticOutput,
    OpsCopilotRequest,
    PersonaContext,
    PsychologicalTactic,
    RecipientEntityType,
    ScamVerdict,
    TacticDetected,
    TxRiskRequest,
    VictimAgeGroup,
)


def fallback_tx_semantic(
    request: TxRiskRequest,
    recipient_type: RecipientEntityType,
) -> LLMTxSemanticOutput:
    """Deterministic Vietnamese semantic fallback for Engine 1."""
    norm_note = VietnameseTextNormalizer.normalize(request.transfer_note)
    pronoun, _ = describe_persona_tone(request.persona_context)

    authority_hits = [p for p in COERCIVE_AUTHORITY_PATTERNS if p in norm_note]
    task_hits = [p for p in TASK_SCAM_AND_GREED_PATTERNS if p in norm_note]
    delivery_hits = [p for p in FAKE_DELIVERY_OR_BILL_PATTERNS if p in norm_note]
    casual_hits = [p for p in CASUAL_PEER_PATTERNS if p in norm_note]
    merchant_hits = [p for p in MERCHANT_PURCHASE_PATTERNS if p in norm_note]

    is_familiar = request.relationship_context.prior_tx_count > 0

    if authority_hits:
        return LLMTxSemanticOutput(
            semantic_risk_score=42,
            scam_category="POLICE_OR_AUTHORITY_IMPERSONATION",
            is_coercive_authority_jargon=True,
            is_casual_peer_note=False,
            reasoning_for_victim=(
                f"{pronoun} ơi, nội dung chuyển khoản này có dấu hiệu giống kịch bản giả danh "
                "cơ quan chức năng yêu cầu nộp tiền xác minh. Hệ thống tạm giữ để gia đình cùng kiểm tra giúp nhé."
            ),
            reasoning_for_guardian=(
                f"Phát hiện nội dung chuyển khoản chứa cụm từ nhạy cảm ({', '.join(authority_hits[:2])}) "
                "thường gặp trong kịch bản giả danh cơ quan công quyền."
            ),
        )

    if task_hits:
        if request.persona_context.victim_age_group in (
            VictimAgeGroup.UNDER_18,
            VictimAgeGroup.STUDENT_18_25,
        ):
            victim_msg = (
                f"{pronoun} ơi, nội dung này rất giống bẫy làm nhiệm vụ hoàn tiền / hoa hồng trên mạng xã hội. "
                "Đừng nạp thêm tiền để 'rút gốc' nhé — hãy dừng lại kiểm tra cùng gia đình."
            )
        else:
            victim_msg = (
                f"{pronoun} ơi, nội dung chuyển khoản có dấu hiệu liên quan đến bẫy làm nhiệm vụ / "
                "đầu tư hoàn tiền rủi ro cao. Hệ thống tạm giữ để người thân kiểm tra cùng."
            )
        return LLMTxSemanticOutput(
            semantic_risk_score=38,
            scam_category="TASK_OR_INVESTMENT_SCAM",
            is_coercive_authority_jargon=False,
            is_casual_peer_note=False,
            reasoning_for_victim=victim_msg,
            reasoning_for_guardian=(
                "Nội dung chuyển khoản mang dấu hiệu làm nhiệm vụ nhận hoa hồng hoặc hoàn tiền rủi ro cao."
            ),
        )

    if delivery_hits and not (is_familiar and casual_hits):
        return LLMTxSemanticOutput(
            semantic_risk_score=30,
            scam_category="FAKE_DELIVERY_OR_UTILITY_SCAM",
            is_coercive_authority_jargon=True,
            is_casual_peer_note=False,
            reasoning_for_victim=(
                f"{pronoun} ơi, giao dịch này có dấu hiệu giống kịch bản giả mạo giao hàng hoặc đóng phí dịch vụ. "
                "Hệ thống tạm giữ để người thân kiểm tra giúp."
            ),
            reasoning_for_guardian=(
                "Nội dung chuyển khoản có dấu hiệu giả mạo đơn vị vận chuyển/dịch vụ thu phí."
            ),
        )

    if casual_hits and (is_familiar or request.amount < request.relationship_context.protection_threshold):
        return LLMTxSemanticOutput(
            semantic_risk_score=5,
            scam_category="SAFE_CASUAL_PEER",
            is_coercive_authority_jargon=False,
            is_casual_peer_note=True,
            reasoning_for_victim="Giao dịch sinh hoạt cá nhân thông thường, an toàn.",
            reasoning_for_guardian="Giao dịch cá nhân bình thường.",
        )

    if merchant_hits or recipient_type in (RecipientEntityType.MERCHANT_HKD, RecipientEntityType.CORPORATION):
        return LLMTxSemanticOutput(
            semantic_risk_score=10,
            scam_category="MERCHANT_PURCHASE",
            is_coercive_authority_jargon=False,
            is_casual_peer_note=False,
            reasoning_for_victim=(
                f"{pronoun} đang thực hiện giao dịch thanh toán mua sắm giá trị lớn. "
                "Hệ thống gửi thông báo để người thân xác nhận nhanh."
            ),
            reasoning_for_guardian=(
                f"Giao dịch thanh toán tới đơn vị '{request.recipient_name}' số tiền {request.amount:,}đ."
            ),
        )

    return LLMTxSemanticOutput(
        semantic_risk_score=8,
        scam_category="GENERAL_TRANSFER",
        is_coercive_authority_jargon=False,
        is_casual_peer_note=False,
        reasoning_for_victim=(
            f"{pronoun} đang thực hiện chuyển khoản {request.amount:,}đ. "
            "Nếu có dấu hiệu vượt ngưỡng bảo vệ, hệ thống sẽ nhờ người thân xác nhận giúp."
        ),
        reasoning_for_guardian=(
            f"Giao dịch chuyển {request.amount:,}đ tới {request.recipient_name}."
        ),
    )


def fallback_scam_analysis(
    raw_text: str,
    entities: ExtractedEntities,
    forensic: ForensicAnalysis | None,
    url_is_malicious: bool,
    persona: PersonaContext,
) -> LLMScamOutput:
    """Deterministic Vietnamese heuristic fallback for Engine 2."""
    norm_text = VietnameseTextNormalizer.normalize(raw_text)
    tactics: list[TacticDetected] = []

    if any(p in norm_text for p in COERCIVE_AUTHORITY_PATTERNS):
        tactics.append(
            TacticDetected(
                tactic=PsychologicalTactic.AUTHORITY,
                evidence="Mạo danh cơ quan công an, thuế, tòa án hoặc tổ chức có thẩm quyền.",
            )
        )
    if any(p in norm_text for p in URGENCY_MARKERS):
        tactics.append(
            TacticDetected(
                tactic=PsychologicalTactic.URGENCY,
                evidence="Thúc ép xử lý gấp trong thời gian ngắn để gây áp lực tâm lý.",
            )
        )
    if any(p in norm_text for p in FEAR_MARKERS):
        tactics.append(
            TacticDetected(
                tactic=PsychologicalTactic.FEAR,
                evidence="Đe dọa bắt giữ, phong tỏa tài sản hoặc khóa tài khoản.",
            )
        )
    if any(p in norm_text for p in TASK_SCAM_AND_GREED_PATTERNS):
        tactics.append(
            TacticDetected(
                tactic=PsychologicalTactic.GREED,
                evidence="Hứa hẹn hoa hồng, lợi nhuận cao hoặc trúng thưởng.",
            )
        )
        if "nap" in norm_text or "rut" in norm_text or "nhiem vu" in norm_text:
            tactics.append(
                TacticDetected(
                    tactic=PsychologicalTactic.RECIPROCITY_COMMITMENT,
                    evidence="Dụ thực hiện nhiệm vụ nhận thưởng nhỏ rồi yêu cầu nạp tiền lớn hơn để rút gốc.",
                )
            )

    score = 15
    score += len(tactics) * 20
    if url_is_malicious:
        score += 30
    if entities.bank_accounts:
        score += 15
    if forensic and forensic.tampering_suspected:
        score += 30
    score = min(100, score)

    if score >= 70:
        verdict = ScamVerdict.HIGH_RISK_SCAM
        category = "IMPERSONATION_OR_PHISHING_SCAM"
    elif score >= 40:
        verdict = ScamVerdict.SUSPICIOUS
        category = "SUSPICIOUS_MESSAGE"
    else:
        verdict = ScamVerdict.SAFE
        category = "LOW_RISK_CONTENT"

    pronoun, _ = describe_persona_tone(persona)
    summary = (
        "Phát hiện dấu hiệu thao túng tâm lý hoặc tài liệu chỉnh sửa đáng ngờ."
        if verdict != ScamVerdict.SAFE
        else "Chưa ghi nhận dấu hiệu lừa đảo rõ ràng trong nội dung cung cấp."
    )
    advice = (
        f"{pronoun} và gia đình tuyệt đối không chuyển tiền hay bấm vào đường link lạ từ tin nhắn này."
        if verdict != ScamVerdict.SAFE
        else "Vẫn nên kiểm tra kỹ thông tin người gửi trước khi thực hiện giao dịch tài chính."
    )
    return LLMScamOutput(
        verdict=verdict,
        risk_score=score,
        scam_category=category,
        summary=summary,
        tactics_detected=tactics,
        extracted_entities=entities,
        advice_for_family=advice,
    )


def fallback_ops_copilot(request: OpsCopilotRequest) -> LLMOpsCopilotOutput:
    """Deterministic fallback for Engine 3 (Ops Copilot) with adaptive persona script."""
    pronoun, _ = describe_persona_tone(request.persona_context)

    if request.guardian_decision == GuardianDecision.APPROVE_SAFE:
        return LLMOpsCopilotOutput(
            case_summary=(
                f"Giao dịch {request.amount:,}đ của {request.victim_name} tới {request.recipient_name} "
                "đã được người giám hộ xác nhận an toàn trực tiếp."
            ),
            recommended_action="auto_resolve_false_positive",
            confidence_score=0.95,
            deescalation_copilot=DeescalationCopilot(
                victim_psychological_state="Bình tĩnh, giao dịch hợp lệ đã có người thân xác nhận.",
                call_script=(
                    f"Chào {pronoun}, hệ thống ghi nhận người thân của {pronoun} đã xác nhận giao dịch "
                    f"{request.amount:,}đ là an toàn và đã giải ngân thành công."
                ),
                guidance_sms="Giao dịch của bạn đã được xác nhận an toàn và hoàn tất.",
                verification_questions=[
                    "Người thân đã xác nhận đúng cửa hàng/người nhận chưa?",
                    "Bạn có cần điều chỉnh hạn mức bảo vệ gia đình không?",
                    "Bạn có nhận được tin nhắn lạ nào đi kèm giao dịch này không?",
                ],
            ),
        )

    is_flagged = request.guardian_decision == GuardianDecision.FLAG_SCAM
    return LLMOpsCopilotOutput(
        case_summary=(
            f"{request.victim_name} thực hiện chuyển {request.amount:,}đ tới {request.recipient_name} "
            f"({request.recipient_account}) với nội dung '{request.transfer_note}'. "
            + (
                "Người giám hộ đã bấm CHẶN KHẨN CẤP nghi ngờ lừa đảo."
                if is_flagged
                else f"Điểm rủi ro AI đạt {request.ai_risk_score}/100 ({request.scam_category})."
            )
        ),
        recommended_action="confirm_fraud_and_blacklist" if is_flagged or request.ai_risk_score >= 75 else "hold_and_call_customer",
        confidence_score=0.96 if is_flagged else 0.85,
        deescalation_copilot=DeescalationCopilot(
            victim_psychological_state=(
                "Có dấu hiệu lo âu hoặc bị thao túng tâm lý, cần trấn an nhẹ nhàng trước khi xác minh."
            ),
            call_script=(
                f"Chào {pronoun} {request.victim_name}, cháu là nhân viên Bộ phận Bảo vệ Tài sản Khách hàng. "
                f"Giao dịch {request.amount:,}đ của {pronoun} đang được hệ thống và người thân tạm giữ an toàn. "
                f"{pronoun} yên tâm mình không bị mất tiền, mình cùng kiểm tra lại danh tính người nhận trong 1 phút nhé."
            ),
            guidance_sms=(
                "Cảnh báo an toàn: Ngân hàng & Cơ quan chức năng KHÔNG bao giờ yêu cầu chuyển tiền "
                "vào tài khoản cá nhân để xác minh hồ sơ hoặc làm nhiệm vụ nhận thưởng."
            ),
            verification_questions=[
                f"{pronoun} có đang nói chuyện điện thoại với người lạ trong lúc bấm chuyển khoản không?",
                f"Người yêu cầu chuyển tiền có dặn {pronoun} giữ bí mật hoặc không được hỏi người thân không?",
                f"{pronoun} đã từng gặp mặt trực tiếp người nhận '{request.recipient_name}' ngoài đời chưa?",
            ],
        ),
    )
