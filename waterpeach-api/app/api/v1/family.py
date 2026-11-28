from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import DbSession
from app.schemas.family import (
    AddMemberRequest,
    DeleteMemberResponse,
    FamilyLinkOut,
    GuardianAlertsResponse,
    GuardianDecisionRequest,
    GuardianDecisionResponse,
    ProtectionSettings,
    SafetyFeedResponse,
    TrustedCircleResponse,
    UpdateSettingsRequest,
)
from app.services import family_service

router = APIRouter(tags=["Trusted Circle & Guardian Hub"])


@router.get("/family/trusted-circle", response_model=TrustedCircleResponse)
async def trusted_circle(
    db: DbSession, victim_id: Annotated[str, Query(max_length=32)]
) -> TrustedCircleResponse:
    return await family_service.get_trusted_circle(db, victim_id)


@router.post("/family/members", response_model=FamilyLinkOut, status_code=status.HTTP_201_CREATED)
async def add_member(payload: AddMemberRequest, db: DbSession) -> FamilyLinkOut:
    return await family_service.add_member(db, payload)


@router.delete("/family/members/{link_id}", response_model=DeleteMemberResponse)
async def remove_member(link_id: str, db: DbSession) -> DeleteMemberResponse:
    return await family_service.remove_member(db, link_id)


@router.put("/family/settings", response_model=ProtectionSettings)
async def update_settings(payload: UpdateSettingsRequest, db: DbSession) -> ProtectionSettings:
    return await family_service.update_settings(db, payload)


@router.get("/family/safety-feed", response_model=SafetyFeedResponse)
async def safety_feed(
    db: DbSession, family_member_id: Annotated[str, Query(max_length=32)]
) -> SafetyFeedResponse:
    return await family_service.get_safety_feed(db, family_member_id)


@router.get("/guardian/alerts", response_model=GuardianAlertsResponse)
async def guardian_alerts(
    db: DbSession, guardian_id: Annotated[str, Query(max_length=32)]
) -> GuardianAlertsResponse:
    """Privacy-First alerts: no balance, no normal completed transactions."""
    return await family_service.get_alerts(db, guardian_id)


@router.post("/guardian/transactions/{tx_id}/decision", response_model=GuardianDecisionResponse)
async def guardian_decision(
    tx_id: str, payload: GuardianDecisionRequest, db: DbSession
) -> GuardianDecisionResponse:
    """1-tap decision: flag_scam (Đỏ), approve_safe (Xanh), hold_verify (Vàng)."""
    return await family_service.decide(db, tx_id, payload)
