from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

# SafeSearch is intentionally fail-closed: when enabled, pages matching
# strong adult-content indicators are excluded from public search results.
# This is a heuristic filter, not a guarantee that every unsafe page is found.
MAX_SCAN = 20_000

BLOCKED_TERMS = frozenset({
    "porn", "porno", "pornography", "xxx", "nsfw", "sexcam", "webcamsex",
    "adultvideo", "adultvideos", "adultcontent", "explicitvideo", "hentai",
    "nude", "nudity", "erotic", "sexshop", "sexshop", "escort", "prostitute",
    "prostitution", "onlyfans", "xvideos", "pornhub", "redtube", "xhamster",
})

_WORD_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def _tokens(value: Any) -> set[str]:
    return set(_WORD_RE.findall(str(value or "")[:MAX_SCAN].lower()))


def is_safe_page(page: dict[str, Any]) -> bool:
    """Return False for pages with strong adult-content indicators."""
    if not isinstance(page, dict):
        return False

    url = str(page.get("url", ""))[:MAX_SCAN]
    parsed = urlparse(url)
    domain = (parsed.hostname or "").lower()
    haystack = " ".join(
        str(page.get(field, ""))[:MAX_SCAN]
        for field in ("title", "description", "content")
    )

    tokens = _tokens(haystack)
    domain_tokens = _tokens(domain.replace(".", " "))
    if BLOCKED_TERMS.intersection(tokens | domain_tokens):
        return False

    compact = re.sub(r"[^a-z0-9]+", "", (domain + " " + haystack).lower())
    return not any(term in compact for term in BLOCKED_TERMS if len(term) >= 6)


def filter_safe_pages(pages: list[dict[str, Any]], enabled: bool) -> list[dict[str, Any]]:
    if not enabled:
        return pages
    return [page for page in pages if is_safe_page(page)]
