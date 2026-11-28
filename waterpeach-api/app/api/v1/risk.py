from fastapi import APIRouter, Depends

from app.api.deps import DbSession
from app.core.security import require_b2b_api_key
from app.schemas.banking import RiskEvaluateRequest, RiskEvaluateResponse
from app.services import transaction_service

router = APIRouter(
    prefix="/risk", tags=["B2B Risk API"], dependencies=[Depends(require_b2b_api_key)]
)


@router.post("/evaluate", response_model=RiskEvaluateResponse)
async def evaluate(payload: RiskEvaluateRequest, db: DbSession) -> RiskEvaluateResponse:
    """Core Banking integration: score a transfer before disbursement (header X-API-Key)."""
    outcome = await transaction_service.create_transfer(
        db, payload, source="b2b", partner_tx_ref=payload.partner_tx_ref
    )
    detail = transaction_service.to_detail(outcome.transaction)
    return RiskEvaluateResponse(
        tx_id=detail.tx_id,
        partner_tx_ref=payload.partner_tx_ref,
        status=detail.status,
        cooling_off_seconds=outcome.analysis.cooling_off_seconds,
        blacklist_hit=detail.blacklist_hit,
        ai_analysis=detail.ai_analysis,
        guardian_notified=outcome.guardian_notified,
    )
