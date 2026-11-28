from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import DbSession
from app.schemas.common import BlacklistStatus, EntityType, IncidentFilter
from app.schemas.ops import (
    BlacklistCreateRequest,
    BlacklistEntry,
    BlacklistListResponse,
    IncidentBrief,
    IncidentQueueResponse,
    OpsActionRequest,
    OpsActionResponse,
)
from app.services import blacklist_service, ops_service

router = APIRouter(prefix="/ops", tags=["Fraud Ops Workspace"])


@router.get("/incidents", response_model=IncidentQueueResponse)
async def incidents(
    db: DbSession,
    filter_: Annotated[IncidentFilter, Query(alias="filter")] = IncidentFilter.ALL,
) -> IncidentQueueResponse:
    """AI-triaged queue: guardian-flagged first, then by AI risk score."""
    return await ops_service.list_incidents(db, filter_)


@router.get("/incidents/{tx_id}/brief", response_model=IncidentBrief)
async def incident_brief(tx_id: str, db: DbSession) -> IncidentBrief:
    """AI Case Brief + Network Threat Intelligence + De-escalation Copilot."""
    return await ops_service.get_brief(db, tx_id)


@router.post("/incidents/{tx_id}/action", response_model=OpsActionResponse)
async def incident_action(
    tx_id: str, payload: OpsActionRequest, db: DbSession
) -> OpsActionResponse:
    """1-Click containment: cancel_and_refund, blacklist_recipient, release, export_report."""
    return await ops_service.execute_action(db, tx_id, payload)


@router.get("/blacklist", response_model=BlacklistListResponse)
async def list_blacklist(
    db: DbSession,
    entity_type: EntityType | None = None,
    status_: Annotated[BlacklistStatus | None, Query(alias="status")] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> BlacklistListResponse:
    entries = await blacklist_service.list_entries(
        db, entity_type=entity_type, status=status_, q=q
    )
    return BlacklistListResponse(entries=entries)


@router.post("/blacklist", response_model=BlacklistEntry, status_code=status.HTTP_201_CREATED)
async def add_blacklist(payload: BlacklistCreateRequest, db: DbSession) -> BlacklistEntry:
    return await ops_service.add_blacklist_entry(db, payload)
