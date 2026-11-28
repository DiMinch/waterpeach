from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile

from app.api.deps import DbSession
from app.core.config import get_settings
from app.core.errors import bad_request
from app.schemas.ops import ScamCheckResponse
from app.services import scam_check_service

router = APIRouter(prefix="/scam-check", tags=["Scam Check"])


@router.post("/analyze", response_model=ScamCheckResponse)
async def analyze(
    db: DbSession,
    submitted_by: Annotated[str, Form(max_length=32)],
    raw_text: Annotated[str | None, Form(max_length=4000)] = None,
    share_to_family: Annotated[bool, Form()] = False,
    file: Annotated[UploadFile | None, File()] = None,
) -> ScamCheckResponse:
    """Analyze a screenshot / text, store the report and feed the Threat Blacklist."""
    file_bytes: bytes | None = None
    if file is not None:
        limit = get_settings().AI_MAX_UPLOAD_BYTES
        file_bytes = await file.read(limit + 1)
        if len(file_bytes) > limit:
            raise bad_request("FILE_TOO_LARGE", f"File exceeds {limit} bytes")
    return await scam_check_service.analyze(
        db,
        submitted_by=submitted_by,
        raw_text=raw_text,
        file_bytes=file_bytes,
        share_to_family=share_to_family,
    )
