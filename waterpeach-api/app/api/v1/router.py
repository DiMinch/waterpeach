from fastapi import APIRouter

from app.api.v1 import banking, demo, events, family, ops, risk, scam_check
from app.api.v1.ai import router as ai_router

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(ai_router)
api_v1_router.include_router(risk.router)
api_v1_router.include_router(banking.router)
api_v1_router.include_router(family.router)
api_v1_router.include_router(scam_check.router)
api_v1_router.include_router(ops.router)
api_v1_router.include_router(demo.router)
api_v1_router.include_router(events.router)
