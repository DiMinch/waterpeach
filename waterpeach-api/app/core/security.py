import secrets

from fastapi import Header, HTTPException, status

from app.core.config import get_settings


async def require_b2b_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    """Reject B2B requests (``/api/v1/risk/*``) without a valid ``X-API-Key`` header."""
    expected = get_settings().B2B_API_KEY
    if not expected or not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
