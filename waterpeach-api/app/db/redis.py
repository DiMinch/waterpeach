import logging

from redis.asyncio import Redis

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_client: Redis | None = None


def get_redis() -> Redis | None:
    """Shared Redis client, or None when REDIS_URL is empty (Redis disabled)."""
    global _client
    url = get_settings().REDIS_URL
    if not url:
        return None
    if _client is None:
        _client = Redis.from_url(url, decode_responses=True)
    return _client


async def check_redis() -> bool | None:
    """True/False for reachable/unreachable, None when Redis is disabled."""
    client = get_redis()
    if client is None:
        return None
    try:
        await client.ping()
    except Exception as exc:  # readiness must report, not raise
        logger.warning("Redis check failed: %s", exc)
        return False
    return True


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
