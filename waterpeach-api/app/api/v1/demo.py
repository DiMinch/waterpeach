from typing import Annotated

from fastapi import APIRouter, Path

from app.api.deps import DbSession
from app.schemas.ops import DemoResetResponse, DemoScenarioResponse
from app.services import demo_service

router = APIRouter(prefix="/demo", tags=["Zero-Friction Demo"])


@router.post("/scenario/{scenario_id}", response_model=DemoScenarioResponse)
async def run_scenario(
    scenario_id: Annotated[int, Path(ge=1, le=3)], db: DbSession
) -> DemoScenarioResponse:
    """Trigger sample scenario 1 (police impersonation), 2 (false positive) or 3 (scam scan)."""
    return await demo_service.run_scenario(db, scenario_id)


@router.post("/reset", response_model=DemoResetResponse)
async def reset(db: DbSession) -> DemoResetResponse:
    """Wipe generated data and reload the seed users (Bác Minh, Anh Nam, Chị Linh)."""
    return await demo_service.reset(db)
