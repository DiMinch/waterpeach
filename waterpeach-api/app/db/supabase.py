from supabase import AsyncClient, acreate_client

from app.core.config import get_settings

_client: AsyncClient | None = None


async def get_supabase() -> AsyncClient | None:
    """Server-side Supabase client (service role), or None when Supabase is not configured."""
    global _client
    settings = get_settings()
    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
        return None
    if _client is None:
        _client = await acreate_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    return _client
