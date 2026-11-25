import base64
from typing import Any

from app.ai.client import GeminiAIClient, get_gemini_client
from app.ai.entity_verifier import analyze_url_phishvn, extract_iocs_regex
from app.ai.fallbacks import fallback_scam_analysis
from app.ai.image_forensics import analyze_image_forensics
from app.ai.prompts import build_scam_analyzer_system_prompt
from app.ai.security import PromptInjectionGuard, validate_media_upload
from app.schemas.ai import (
    ExtractedEntities,
    ForensicAnalysis,
    LLMScamOutput,
    ScamAnalysisResult,
    ScamAnalyzeRequest,
    ScamVerdict,
    WebGroundingIntel,
)


async def analyze_multimodal_scam(
    request: ScamAnalyzeRequest,
    *,
    image_bytes: bytes | None = None,
    ai_client: GeminiAIClient | None = None,
) -> ScamAnalysisResult:
    """Analyze suspicious messages, documents, or screenshots using ELA Forensics + Gemini VLM."""
    client = ai_client or get_gemini_client()
    raw_text = (request.raw_text or "").strip()

    decoded_bytes = image_bytes
    mime_type = request.image_mime_type

    if decoded_bytes is None and request.image_base64:
        try:
            decoded_bytes = base64.b64decode(request.image_base64, validate=True)
        except Exception as exc:
            raise ValueError("Invalid base64 image payload.") from exc

    forensic: ForensicAnalysis | None = None
    if decoded_bytes is not None:
        mime_type = validate_media_upload(decoded_bytes)
        forensic = analyze_image_forensics(decoded_bytes, mime_type=mime_type)

    if not raw_text and decoded_bytes is None:
        raise ValueError("At least one of raw_text or image/media file must be provided.")

    injection_detected = PromptInjectionGuard.detect(raw_text)
    regex_entities = extract_iocs_regex(raw_text)
    url_results = [analyze_url_phishvn(u) for u in regex_entities.urls]
    url_is_malicious = any(r.is_suspicious for r in url_results)

    # Build multimodal input payload for Gemini Interactions API
    prompt_parts: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                "Phân tích bằng chứng nghi ngờ lừa đảo sau đây.\n"
                + (
                    f"Kết quả giám định kỹ thuật số (ELA/Metadata): {forensic.forensic_note}\n"
                    if forensic
                    else ""
                )
                + f"Nội dung văn bản (nếu có):\n{PromptInjectionGuard.wrap_untrusted(raw_text)}"
            ),
        }
    ]
    if decoded_bytes is not None and mime_type and mime_type.startswith("image/"):
        prompt_parts.append(
            {
                "type": "image",
                "data": base64.b64encode(decoded_bytes).decode("ascii"),
                "mime_type": mime_type,
            }
        )

    hash_source = raw_text.encode("utf-8") + (decoded_bytes or b"")
    cache_key = f"scam:{client.compute_hash(hash_source)}"

    llm_result = await client.generate_structured(
        system_instruction=build_scam_analyzer_system_prompt(request.persona_context),
        input_content=prompt_parts,
        schema_cls=LLMScamOutput,
        cache_key=cache_key,
        rate_limit_key="scam_analyzer",
    )

    used_fallback = llm_result is None
    parsed = llm_result or fallback_scam_analysis(
        raw_text=raw_text,
        entities=regex_entities,
        forensic=forensic,
        url_is_malicious=url_is_malicious,
        persona=request.persona_context,
    )

    # Merge deterministic Regex IOCs with LLM-extracted IOCs (e.g. from image OCR)
    merged_accounts = list(
        dict.fromkeys([*regex_entities.bank_accounts, *parsed.extracted_entities.bank_accounts])
    )
    merged_phones = list(
        dict.fromkeys([*regex_entities.phones, *parsed.extracted_entities.phones])
    )
    merged_urls = list(dict.fromkeys([*regex_entities.urls, *parsed.extracted_entities.urls]))
    merged_entities = ExtractedEntities(
        bank_accounts=merged_accounts,
        phones=merged_phones,
        urls=merged_urls,
    )

    # Re-evaluate URLs discovered via VLM OCR
    if not url_is_malicious and merged_urls:
        url_is_malicious = any(analyze_url_phishvn(u).is_suspicious for u in merged_urls)

    risk_score = parsed.risk_score
    if injection_detected:
        risk_score = max(risk_score, 85)
    if forensic and forensic.tampering_suspected:
        risk_score = min(100, max(risk_score, 75))
    if url_is_malicious:
        risk_score = min(100, max(risk_score, 80))

    verdict = parsed.verdict
    if risk_score >= 70:
        verdict = ScamVerdict.HIGH_RISK_SCAM
    elif risk_score >= 40 and verdict == ScamVerdict.SAFE:
        verdict = ScamVerdict.SUSPICIOUS

    grounding: WebGroundingIntel | None = None
    if request.enable_web_search and (merged_urls or merged_phones):
        query_targets = " ".join(merged_urls[:2] + merged_phones[:2])
        grounding = await client.search_grounding(query_targets)

    return ScamAnalysisResult(
        verdict=verdict,
        risk_score=risk_score,
        scam_category=parsed.scam_category,
        summary=parsed.summary,
        forensic_analysis=forensic,
        tactics_detected=parsed.tactics_detected,
        extracted_entities=merged_entities,
        web_grounding_intel=grounding,
        advice_for_family=parsed.advice_for_family,
        used_fallback=used_fallback,
    )
