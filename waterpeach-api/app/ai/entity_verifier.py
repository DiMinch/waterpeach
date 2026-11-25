import re
import time
from urllib.parse import urlparse

import httpx

from app.ai.knowledge_base import (
    CORPORATE_NAME_MARKERS,
    MERCHANT_HKD_MARKERS,
    OFFICIAL_VN_ALLOWLIST_SUFFIXES,
    PHISHVN_IMPERSONATED_BRANDS,
    PHISHVN_SUSPICIOUS_TLDS,
)
from app.ai.security import fold_vietnamese_accents
from app.core.config import get_settings
from app.schemas.ai import (
    ExtractedEntities,
    RecipientEntityType,
    TaxLookupResult,
    UrlRiskResult,
)

VN_PHONE_RE = re.compile(r"(?<!\d)(?:\+?84|0)(?:3|5|7|8|9)\d{8}(?!\d)")
DIGIT_SEQ_RE = re.compile(r"(?<!\d)\d{8,16}(?!\d)")
URL_RE = re.compile(r"(?:https?://[^\s<>\"']+|(?:[a-zA-Z0-9-]+\.)+(?:xyz|top|vip|cc|click|icu|buzz|loan|work|shop|site|online|vn|com))(?:/[^\s<>\"']*)?", re.IGNORECASE)
IPV4_HOST_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")

_TAX_CACHE: dict[str, tuple[float, TaxLookupResult]] = {}
_TAX_CACHE_TTL_SECONDS = 3600.0


def classify_recipient_entity(recipient_name: str) -> RecipientEntityType:
    """Classify recipient account holder name as CORPORATION, MERCHANT_HKD, or INDIVIDUAL."""
    if not recipient_name or not recipient_name.strip():
        return RecipientEntityType.UNKNOWN

    normalized = fold_vietnamese_accents(recipient_name).upper()
    if any(marker in normalized for marker in CORPORATE_NAME_MARKERS):
        return RecipientEntityType.CORPORATION
    if any(marker in normalized for marker in MERCHANT_HKD_MARKERS):
        return RecipientEntityType.MERCHANT_HKD
    return RecipientEntityType.INDIVIDUAL


async def lookup_vietqr_tax_code(
    tax_code: str,
    http_client: httpx.AsyncClient | None = None,
) -> TaxLookupResult:
    """Query live VietQR Business Tax Code API (sourced from General Dept. of Taxation)."""
    clean_tax = re.sub(r"[^0-9\-]", "", tax_code.strip())
    if not clean_tax:
        return TaxLookupResult(found=False, tax_code=tax_code, error="Invalid tax code format")

    now = time.monotonic()
    cached = _TAX_CACHE.get(clean_tax)
    if cached and (now - cached[0]) < _TAX_CACHE_TTL_SECONDS:
        return cached[1]

    url = f"{get_settings().VIETQR_BUSINESS_API_URL}/{clean_tax}"
    try:
        if http_client is not None:
            resp = await http_client.get(url, timeout=4.0)
        else:
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.get(url)

        if resp.status_code != 200:
            return TaxLookupResult(
                found=False,
                tax_code=clean_tax,
                error=f"Upstream HTTP {resp.status_code}",
            )

        payload = resp.json()
        if payload.get("code") == "00" and isinstance(payload.get("data"), dict):
            data = payload["data"]
            result = TaxLookupResult(
                found=True,
                tax_code=clean_tax,
                legal_name=data.get("name"),
                status=data.get("status"),
                address=data.get("address"),
            )
        else:
            result = TaxLookupResult(
                found=False,
                tax_code=clean_tax,
                error=payload.get("desc", "Tax code not found"),
            )
        _TAX_CACHE[clean_tax] = (now, result)
        return result
    except Exception as exc:
        return TaxLookupResult(found=False, tax_code=clean_tax, error=str(exc))


def analyze_url_phishvn(url: str) -> UrlRiskResult:
    """Analyze a URL using PhishVN lexical feature heuristics."""
    raw = url.strip()
    candidate = raw if raw.startswith(("http://", "https://")) else f"http://{raw}"
    parsed = urlparse(candidate)
    host = (parsed.hostname or "").lower()
    full_lower = candidate.lower()

    score = 0
    features: list[str] = []

    if not host:
        return UrlRiskResult(url=raw, risk_score=0, is_suspicious=False, triggered_features=[])

    if any(host.endswith(safe) for safe in OFFICIAL_VN_ALLOWLIST_SUFFIXES):
        return UrlRiskResult(url=raw, risk_score=0, is_suspicious=False, triggered_features=[])

    if IPV4_HOST_RE.match(host):
        score += 45
        features.append("IP_HOST_URL")

    if "xn--" in host:
        score += 35
        features.append("PUNYCODE_HOMOGRAPH")

    if any(host.endswith(tld) for tld in PHISHVN_SUSPICIOUS_TLDS):
        score += 35
        features.append("SUSPICIOUS_TLD")

    if any(brand in full_lower for brand in PHISHVN_IMPERSONATED_BRANDS):
        score += 35
        features.append("BRAND_IMPERSONATION_KEYWORD")

    if host.count("-") >= 2:
        score += 15
        features.append("EXCESSIVE_HYPHENS")

    if host.count(".") >= 3:
        score += 15
        features.append("DEEP_SUBDOMAIN")

    if candidate.startswith("http://"):
        score += 10
        features.append("INSECURE_HTTP")

    if "@" in raw or len(raw) > 85:
        score += 15
        features.append("OBFUSCATED_OR_LONG_URL")

    clamped = min(100, score)
    return UrlRiskResult(
        url=raw,
        risk_score=clamped,
        is_suspicious=clamped >= 40,
        triggered_features=features,
    )


def extract_iocs_regex(text: str) -> ExtractedEntities:
    """Deterministically extract bank accounts, VN phone numbers, and URLs from text."""
    if not text:
        return ExtractedEntities()

    phones = list(dict.fromkeys(VN_PHONE_RE.findall(text)))
    phone_digits = {re.sub(r"^\+?84", "0", p) for p in phones}

    urls = list(dict.fromkeys(u.rstrip(".,;:)") for u in URL_RE.findall(text)))

    bank_accounts: list[str] = []
    for match in DIGIT_SEQ_RE.finditer(text):
        num = match.group(0)
        # Skip VN phone numbers already captured
        if num in phone_digits or num in phones:
            continue
        # Skip round currency amounts (e.g. 25000000, 100000000) unless near account keyword
        if num.endswith("00000"):
            prefix = text[max(0, match.start() - 20) : match.start()].lower()
            if not any(kw in prefix for kw in ("stk", "tk", "tai khoan", "account")):
                continue
        if num not in bank_accounts:
            bank_accounts.append(num)

    return ExtractedEntities(bank_accounts=bank_accounts, phones=phones, urls=urls)
