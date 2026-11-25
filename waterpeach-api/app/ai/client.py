import asyncio
import hashlib
import time
from collections import defaultdict, deque
from typing import Any, TypeVar

from google import genai
from pydantic import BaseModel

from app.core.config import get_settings
from app.schemas.ai import CitationItem, WebGroundingIntel

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class GeminiAIClient:
    """Async Gemini Interactions API wrapper with deduplication cache, rate limiting, and timeout."""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, BaseModel]] = {}
        self._rate_windows: dict[str, deque[float]] = defaultdict(deque)
        self._sdk_client: genai.Client | None = None

    def _get_client(self) -> genai.Client | None:
        settings = get_settings()
        if not settings.GEMINI_API_KEY:
            return None
        if self._sdk_client is None:
            self._sdk_client = genai.Client(api_key=settings.GEMINI_API_KEY)
        return self._sdk_client

    def _is_rate_limited(self, key: str) -> bool:
        settings = get_settings()
        now = time.monotonic()
        q = self._rate_windows[key]
        cutoff = now - 60.0
        while q and q[0] < cutoff:
            q.popleft()
        if len(q) >= settings.AI_RATE_LIMIT_PER_MIN:
            return True
        q.append(now)
        return False

    @staticmethod
    def compute_hash(payload: str | bytes) -> str:
        """Compute deterministic SHA-256 hash for content deduplication."""
        raw = payload.encode("utf-8") if isinstance(payload, str) else payload
        return hashlib.sha256(raw).hexdigest()

    def _get_cached(self, cache_key: str, schema_cls: type[SchemaT]) -> SchemaT | None:
        settings = get_settings()
        entry = self._cache.get(cache_key)
        if not entry:
            return None
        ts, value = entry
        if (time.monotonic() - ts) >= settings.AI_CACHE_TTL_SECONDS:
            self._cache.pop(cache_key, None)
            return None
        if isinstance(value, schema_cls):
            return value
        return None

    def _set_cached(self, cache_key: str, value: BaseModel) -> None:
        self._cache[cache_key] = (time.monotonic(), value)

    async def generate_structured(
        self,
        *,
        system_instruction: str,
        input_content: str | list[dict[str, Any]],
        schema_cls: type[SchemaT],
        cache_key: str | None = None,
        rate_limit_key: str = "global",
    ) -> SchemaT | None:
        """Call Gemini Interactions API with structured output; return None on fallback trigger."""
        if cache_key:
            cached = self._get_cached(cache_key, schema_cls)
            if cached is not None:
                return cached

        if self._is_rate_limited(rate_limit_key):
            return None

        client = self._get_client()
        if client is None:
            return None

        settings = get_settings()
        try:
            interaction = await asyncio.wait_for(
                client.aio.interactions.create(
                    model=settings.GEMINI_MODEL,
                    system_instruction=system_instruction,
                    input=input_content,
                    response_format={
                        "type": "text",
                        "mime_type": "application/json",
                        "schema": schema_cls.model_json_schema(),
                    },
                    store=False,
                ),
                timeout=settings.AI_TIMEOUT_SECONDS,
            )
            output_text = getattr(interaction, "output_text", None)
            if not output_text:
                return None
            parsed = schema_cls.model_validate_json(output_text)
            if cache_key:
                self._set_cached(cache_key, parsed)
            return parsed
        except Exception:
            return None

    async def search_grounding(self, query: str, rate_limit_key: str = "search") -> WebGroundingIntel:
        """Query Google Search grounding via Gemini Interactions API for entity/scam OSINT."""
        cache_key = f"search:{self.compute_hash(query)}"
        cached = self._get_cached(cache_key, WebGroundingIntel)
        if cached is not None:
            return cached

        if self._is_rate_limited(rate_limit_key):
            return WebGroundingIntel(searched=False, summary="", citations=[])

        client = self._get_client()
        if client is None:
            return WebGroundingIntel(searched=False, summary="", citations=[])

        settings = get_settings()
        prompt = (
            "Tìm kiếm và tóm tắt ngắn gọn (tối đa 3 câu tiếng Việt) thông tin uy tín hoặc "
            f"cảnh báo lừa đảo liên quan đến thực thể sau tại Việt Nam: {query}"
        )
        try:
            interaction = await asyncio.wait_for(
                client.aio.interactions.create(
                    model=settings.GEMINI_MODEL,
                    input=prompt,
                    tools=[{"type": "google_search"}],
                    store=False,
                ),
                timeout=settings.AI_TIMEOUT_SECONDS,
            )
            summary = getattr(interaction, "output_text", "") or ""
            citations: list[CitationItem] = []
            seen_urls: set[str] = set()

            for step in getattr(interaction, "steps", []) or []:
                for block in getattr(step, "content", []) or []:
                    for ann in getattr(block, "annotations", []) or []:
                        url = getattr(ann, "url", None)
                        title = getattr(ann, "title", None) or "Nguồn tham khảo"
                        if url and url not in seen_urls:
                            seen_urls.add(url)
                            citations.append(CitationItem(title=title, url=url))

            result = WebGroundingIntel(
                searched=True,
                summary=summary.strip(),
                citations=citations[:5],
            )
            self._set_cached(cache_key, result)
            return result
        except Exception:
            return WebGroundingIntel(searched=False, summary="", citations=[])

    def reset_state(self) -> None:
        """Clear in-memory cache and rate-limit windows (for tests)."""
        self._cache.clear()
        self._rate_windows.clear()


_gemini_client = GeminiAIClient()


def get_gemini_client() -> GeminiAIClient:
    """Return global GeminiAIClient singleton."""
    return _gemini_client
