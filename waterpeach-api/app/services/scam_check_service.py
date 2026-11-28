"""Multimodal Scam Check: run Engine 2, persist the report, feed the Threat Blacklist."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.scam_analyzer import analyze_multimodal_scam
from app.core.errors import bad_request
from app.models import ScamReport, new_id
from app.schemas.ai import (
    GuardianRelationship,
    PersonaContext,
    ScamAnalyzeRequest,
    ScamVerdict,
    VictimAgeGroup,
)
from app.schemas.common import UserRole
from app.schemas.ops import ScamCheckResponse
from app.services import blacklist_service, transaction_service
from app.services.realtime import EventType, get_event_bus


async def analyze(
    db: AsyncSession,
    *,
    submitted_by: str,
    raw_text: str | None,
    file_bytes: bytes | None,
    share_to_family: bool,
) -> ScamCheckResponse:
    user = await transaction_service.get_user(db, submitted_by)
    links = await transaction_service.active_links_for_victim(db, user.id)
    persona = PersonaContext(
        victim_age_group=VictimAgeGroup(user.age_group),
        guardian_relationship=(
            GuardianRelationship(links[0].guardian_relationship)
            if links
            else GuardianRelationship.OTHER
        ),
    )
    try:
        result = await analyze_multimodal_scam(
            ScamAnalyzeRequest(raw_text=raw_text or None, persona_context=persona),
            image_bytes=file_bytes or None,
        )
    except ValueError as exc:
        raise bad_request("INVALID_SCAM_INPUT", str(exc)) from exc

    blacklisted = 0
    if result.verdict != ScamVerdict.SAFE:
        blacklisted = await blacklist_service.upsert_entities(
            db, result.extracted_entities, scam_pattern=result.scam_category
        )

    report = ScamReport(
        id=new_id("rep"),
        submitted_by=user.id,
        raw_text=raw_text,
        ai_verdict=result.verdict.value,
        risk_score=result.risk_score,
        scam_category=result.scam_category,
        summary=result.summary,
        advice_for_family=result.advice_for_family,
        tactics_detected=[t.model_dump(mode="json") for t in result.tactics_detected],
        extracted_entities_json=result.extracted_entities.model_dump(mode="json"),
        shared_to_family=share_to_family,
    )
    db.add(report)
    await db.commit()

    if share_to_family:
        get_event_bus().publish(
            EventType.FAMILY_SCAM_ALERT_SHARED,
            {
                "report_id": report.id,
                "submitted_by": user.id,
                "submitted_by_name": user.name,
                "verdict": report.ai_verdict,
                "risk_score": report.risk_score,
                "summary": report.summary,
            },
            [UserRole.VICTIM, UserRole.GUARDIAN],
        )

    return ScamCheckResponse(
        report_id=report.id,
        verdict=result.verdict,
        risk_score=result.risk_score,
        scam_category=result.scam_category,
        summary=result.summary,
        tactics_detected=result.tactics_detected,
        extracted_entities=result.extracted_entities,
        forensic_analysis=result.forensic_analysis,
        advice_for_family=result.advice_for_family,
        blacklisted_entities_count=blacklisted,
        shared_to_family=share_to_family,
        used_fallback=result.used_fallback,
        created_at=report.created_at,
    )
