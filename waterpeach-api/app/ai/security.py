import re
import unicodedata

from app.core.config import get_settings

ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\ufeff]")
SEPARATOR_OBFUSCATION_RE = re.compile(r"(?<=[a-zA-ZÀ-ỹ0-9])[._\-*]+(?=[a-zA-ZÀ-ỹ0-9])")
MULTI_SPACE_RE = re.compile(r"\s+")

LEET_MAP = str.maketrans(
    {
        "0": "o",
        "1": "i",
        "3": "e",
        "4": "a",
        "5": "s",
        "@": "a",
        "$": "s",
    }
)

PROMPT_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions|rules|prompts?)",
    r"disregard\s+(all\s+)?(previous|prior|above)",
    r"forget\s+(everything|all\s+rules)",
    r"bo\s+qua\s+(tat\s+ca\s+|moi\s+)?(huong\s+dan|quy\s+tac|chi\s+dan)",
    r"risk[_\s]*score\s*[:=]\s*0",
    r"system\s*prompt",
    r"</untrusted_user_content>",
    r"return\s+(safe|completed|low)\b",
]
INJECTION_REGEX = re.compile("|".join(PROMPT_INJECTION_PATTERNS), re.IGNORECASE)


def fold_vietnamese_accents(text: str) -> str:
    """Convert Vietnamese accented text to unaccented ASCII lowercase."""
    replaced = text.replace("đ", "d").replace("Đ", "D")
    nfkd = unicodedata.normalize("NFKD", replaced)
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch)).lower()


class VietnameseTextNormalizer:
    """Normalize obfuscated Vietnamese text (zero-width chars, separators, leetspeak)."""

    @staticmethod
    def normalize(text: str) -> str:
        """Return unaccented normalized lowercase text resilient to keyword evasion."""
        if not text:
            return ""
        cleaned = ZERO_WIDTH_RE.sub("", text)
        # Collapse single-letter obfuscation like "n.o.p t_i_e_n" -> "nop tien"
        # Preserve URLs/domains by only collapsing between single word chars when repeated
        tokens = cleaned.split()
        normalized_tokens: list[str] = []
        for token in tokens:
            if "." in token and ("http" in token.lower() or "/" in token):
                normalized_tokens.append(token.lower())
            else:
                collapsed = SEPARATOR_OBFUSCATION_RE.sub("", token)
                normalized_tokens.append(collapsed)
        joined = " ".join(normalized_tokens)
        unaccented = fold_vietnamese_accents(joined)
        de_leeted = unaccented.translate(LEET_MAP)
        return MULTI_SPACE_RE.sub(" ", de_leeted).strip()


class PromptInjectionGuard:
    """Detect prompt injection attempts and isolate untrusted user text."""

    @staticmethod
    def detect(text: str) -> bool:
        """Return True if text contains prompt injection indicators."""
        if not text:
            return False
        normalized = VietnameseTextNormalizer.normalize(text)
        return bool(INJECTION_REGEX.search(text) or INJECTION_REGEX.search(normalized))

    @staticmethod
    def wrap_untrusted(text: str) -> str:
        """Sanitize tag breakouts and wrap text in XML delimiters."""
        safe_text = text.replace("<untrusted_user_content>", "").replace(
            "</untrusted_user_content>", ""
        )
        return f"<untrusted_user_content>\n{safe_text}\n</untrusted_user_content>"


def validate_media_upload(data: bytes, max_bytes: int | None = None) -> str:
    """Validate file size and magic bytes; return canonical MIME type or raise ValueError."""
    limit = max_bytes if max_bytes is not None else get_settings().AI_MAX_UPLOAD_BYTES
    if not data:
        raise ValueError("Uploaded file is empty.")
    if len(data) > limit:
        raise ValueError(f"Uploaded file exceeds maximum allowed size of {limit} bytes.")

    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
        return "audio/wav"
    if data.startswith(b"ID3") or data[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "audio/mpeg"

    raise ValueError("Unsupported or spoofed file format based on magic bytes.")
