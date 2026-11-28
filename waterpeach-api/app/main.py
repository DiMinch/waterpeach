from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_v1_router
from app.core.config import get_settings
from app.db.redis import check_redis, close_redis
from app.db.session import check_database, dispose_engine

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await dispose_engine()
    await close_redis()


app = FastAPI(
    title="waterpeach API",
    description="Unified Backend Gateway & AI Engine for waterpeach (MoMo TechDay 2026)",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_v1_router)


@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, str]:
    """Basic health check endpoint for container orchestration and readiness probes."""
    return {"status": "ok", "service": "waterpeach-api"}


@app.get("/health/ready", tags=["Health"])
async def readiness_check() -> JSONResponse:
    """Readiness probe: database must be reachable; Redis is checked only when enabled."""
    db_ok = await check_database()
    redis_ok = await check_redis()
    checks = {
        "database": "ok" if db_ok else "fail",
        "redis": "skipped" if redis_ok is None else ("ok" if redis_ok else "fail"),
    }
    healthy = "fail" not in checks.values()
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "status": "ok" if healthy else "degraded",
            "env": get_settings().APP_ENV,
            "checks": checks,
        },
    )
