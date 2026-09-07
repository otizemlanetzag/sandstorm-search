from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import urlparse

MAX_QUERY = 300
MAX_TERMS = 24
MAX_TERM = 64
MAX_RESULTS = 50
MAX_TITLE = 500
MAX_DESCRIPTION = 1000
MAX_CONTENT = 500_000

_TOKEN_RE = re.compile(r"[\w\-]+", re.UNICODE)
_SAFE_SCHEMES = {"http", "https"}


def tokenize(query: str) -> list[str]:
    return [term.lower() for term in _TOKEN_RE.findall(query)[:MAX_TERMS] if len(term) <= MAX_TERM]


def safe_page(page: Any) -> dict[str, str] | None:
    if not isinstance(page, dict):
        return None
    raw_url = page.get("url")
    if not isinstance(raw_url, str):
        return None
    try:
        parsed = urlparse(raw_url)
    except ValueError:
        return None
    if parsed.scheme.lower() not in _SAFE_SCHEMES or not parsed.netloc:
        return None
    return {
        "url": raw_url,
        "title": str(page.get("title", ""))[:MAX_TITLE],
        "description": str(page.get("description", ""))[:MAX_DESCRIPTION],
        "content": str(page.get("content", ""))[:MAX_CONTENT],
    }


def score_page(page: dict[str, str], terms: list[str]) -> int:
    title = page["title"].lower()
    description = page["description"].lower()
    content = page["content"].lower()
    page_url = page["url"].lower()
    score = 0
    for term in terms:
        if term in title:
            score += 12
        if term in description:
            score += 5
        if term in content:
            score += 1
        if term in page_url:
            score += 2
    return score


def search_pages(pages: list[Any], query: str, limit: int = 10) -> list[dict[str, str]]:
    if len(query) > MAX_QUERY:
        raise ValueError("Query too long.")
    if not 1 <= limit <= MAX_RESULTS:
        raise ValueError("Invalid result limit.")
    query = query.strip()
    terms = tokenize(query)
    if not query or not terms:
        return []
    ranked: list[tuple[int, dict[str, str]]] = []
    for raw_page in pages:
        page = safe_page(raw_page)
        if page is None:
            continue
        score = score_page(page, terms)
        if score > 0:
            ranked.append((score, page))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [page for _, page in ranked[:limit]]


def escape_html(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)
