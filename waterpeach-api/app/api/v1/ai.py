from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.ai.client import get_gemini_client
from app.ai.entity_verifier import (
    analyze_url_phishvn,
    classify_recipient_entity,
    lookup_vietqr_tax_code,
)
from app.ai.ops_copilot import generate_ops_copilot_brief
from app.ai.risk_engine import analyze_transaction_risk
from app.ai.scam_analyzer import analyze_multimodal_scam
from app.schemas.ai import (
    GuardianRelationship,
    OpsCopilotBrief,
    OpsCopilotRequest,
    PersonaContext,
    RecipientEntityType,
    ScamAnalysisResult,
    ScamAnalyzeRequest,
    TxRiskAnalysis,
    TxRiskRequest,
    VerifyEntityRequest,
    VerifyEntityResponse,
    VictimAgeGroup,
)

router = APIRouter(prefix="/ai", tags=["AI Engines"])


@router.post(
    "/analyze-tx",
    response_model=TxRiskAnalysis,
    summary="Engine 1: Contextual Transaction Risk Engine",
)
async def analyze_transaction_endpoint(payload: TxRiskRequest) -> TxRiskAnalysis:
    """Evaluate transaction risk using the 5-Dimensional Matrix and Gemini semantic analysis."""
    return await analyze_transaction_risk(payload)


@router.post(
    "/analyze-scam",
    response_model=ScamAnalysisResult,
    summary="Engine 2: Multimodal Scam Analyzer (JSON payload)",
)
async def analyze_scam_json_endpoint(payload: ScamAnalyzeRequest) -> ScamAnalysisResult:
    """Analyze suspicious messages or base64-encoded screenshots/documents."""
    try:
        return await analyze_multimodal_scam(payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post(
    "/analyze-scam/upload",
    response_model=ScamAnalysisResult,
    summary="Engine 2: Multimodal Scam Analyzer (Multipart File Upload)",
)
async def analyze_scam_upload_endpoint(
    raw_text: Annotated[str | None, Form()] = None,
    victim_age_group: Annotated[VictimAgeGroup, Form()] = VictimAgeGroup.SENIOR_55_PLUS,
    guardian_relationship: Annotated[
        GuardianRelationship, Form()
    ] = GuardianRelationship.CHILD_OF_VICTIM,
    enable_web_search: Annotated[bool, Form()] = False,
    file: Annotated[UploadFile | None, File()] = None,
) -> ScamAnalysisResult:
    """Analyze uploaded screenshot/audio evidence combined with optional text."""
    file_bytes: bytes | None = None
    if file is not None:
        file_bytes = await file.read()

    req = ScamAnalyzeRequest(
        raw_text=raw_text,
        persona_context=PersonaContext(
            victim_age_group=victim_age_group,
            guardian_relationship=guardian_relationship,
        ),
        enable_web_search=enable_web_search,
    )
    try:
        return await analyze_multimodal_scam(req, image_bytes=file_bytes)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post(
    "/ops-copilot",
    response_model=OpsCopilotBrief,
    summary="Engine 3: Agentic Fraud Ops Copilot",
)
async def ops_copilot_endpoint(payload: OpsCopilotRequest) -> OpsCopilotBrief:
    """Generate AI Case Brief and adaptive De-escalation Copilot script for Fraud Ops."""
    return await generate_ops_copilot_brief(payload)


@router.post(
    "/verify-entity",
    response_model=VerifyEntityResponse,
    summary="Verify recipient entity, live VietQR Tax Code, URL PhishVN risk & Web Grounding",
)
async def verify_entity_endpoint(payload: VerifyEntityRequest) -> VerifyEntityResponse:
    """Enrich recipient entity context via MST lookup, PhishVN URL check, and Google Search."""
    entity_type = (
        classify_recipient_entity(payload.recipient_name)
        if payload.recipient_name
        else RecipientEntityType.UNKNOWN
    )
    tax_lookup = (
        await lookup_vietqr_tax_code(payload.tax_code) if payload.tax_code else None
    )
    url_risk = analyze_url_phishvn(payload.url) if payload.url else None

    grounding = None
    if payload.enable_web_search:
        parts = [
            p
            for p in (payload.recipient_name, payload.tax_code, payload.url, payload.phone)
            if p
        ]
        if parts:
            grounding = await get_gemini_client().search_grounding(" ".join(parts))

    return VerifyEntityResponse(
        recipient_entity_type=entity_type,
        tax_lookup=tax_lookup,
        url_risk=url_risk,
        web_grounding_intel=grounding,
    )
