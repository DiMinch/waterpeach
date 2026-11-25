from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="waterpeach API",
    description="Unified Backend Gateway & AI Engine for waterpeach (MoMo TechDay 2026)",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, str]:
    """Basic health check endpoint for container orchestration and readiness probes."""
    return {"status": "ok", "service": "waterpeach-api"}
