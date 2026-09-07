from __future__ import annotations

import re
import unicodedata
from typing import Any
from urllib.parse import urlparse

# SafeSearch is fail-closed when enabled. It combines multiple independent
# signals so a single obfuscated spelling is less likely to bypass filtering.
MAX_SCAN = 20_000
MAX_TERM_SCAN = 2_000

# Strong adult-content indicators. These are intentionally conservative: the
# filter blocks strong signals rather than attempting to classify every page.
BLOCKED_TERMS = frozenset({
    "porn", "porno", "pornography", "xxx", "nsfw", "sexcam", "webcamsex",
    "adultvideo", "adultvideos", "adultcontent", "explicitvideo", "hentai",
    "nude", "nudity", "erotic", "sexshop", "escort", "prostitute",
    "prostitution", "onlyfans", "xvideos", "pornhub", "redtube", "xhamster",
})

BLOCKED_PHRASES = frozenset({
    "adult content", "adult video", "explicit content", "explicit video",
    "porn video", "porn videos", "free porn", "sex video", "sex videos",
})

_WORD_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_LETTER_RE = re.compile(r"[a-z]+", re.IGNORECASE)


def _normalize(value: Any) -> str:
    # NFKC folds common compatibility/width tricks before scanning.
    text = unicodedata.normalize("NFKC", str(value or ""))
    return text[:MAX_SCAN].lower()


def _tokens(value: Any) -> set[str]:
    return set(_WORD_RE.findall(_normalize(value)))


def _compact(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", _normalize(value))


def _contains_obfuscated_term(value: Any) -> bool:
    """Catch separators/punctuation inserted into long blocked terms."""
    compact = _compact(value)
    return any(len(term) >= 6 and term in compact for term in BLOCKED_TERMS)


def _has_strong_signal(page: dict[str, Any]) -> bool:
    url = _normalize(page.get("url", ""))
    parsed = urlparse(url)
    domain = (parsed.hostname or "").lower()
    path_query = f"{parsed.path} {parsed.query}"
    title = _normalize(page.get("title", ""))
    description = _normalize(page.get("description", ""))
    content = _normalize(page.get("content", ""))

    # URL/domain signals are stronger than ordinary body text.
    url_tokens = _tokens(f"{domain} {path_query}")
    if BLOCKED_TERMS.intersection(url_tokens):
        return True
    if _contains_obfuscated_term(f"{domain} {path_query}"):
        return True

    # Strong exact phrases catch pages whose individual words are split apart
    # by tokenization. Keep this list small to avoid false positives.
    combined = f"{title} {description} {content}"
    if any(phrase in combined for phrase in BLOCKED_PHRASES):
        return True

    # A blocked term in title/description is a strong signal. Body-only terms
    # are checked too, but only as exact normalized tokens or compact matches.
    metadata_tokens = _tokens(f"{title} {description}")
    if BLOCKED_TERMS.intersection(metadata_tokens):
        return True

    body_tokens = _tokens(content)
    if BLOCKED_TERMS.intersection(body_tokens):
        return True
    return _contains_obfuscated_term(combined)


def is_safe_page(page: dict[str, Any]) -> bool:
    """Return False when multiple SafeSearch heuristics identify strong risk."""
    if not isinstance(page, dict):
        return False
    return not _has_strong_signal(page)


def filter_safe_pages(pages: list[dict[str, Any]], enabled: bool) -> list[dict[str, Any]]:
    if not enabled:
        return pages
    return [page for page in pages if is_safe_page(page)]
