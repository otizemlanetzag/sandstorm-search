from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from ask import load_data


PATTERNS = {
    "ads": [
        r"\badvertis", r"\badvertisement", r"\bsponsored\b", r"\bbanner\b",
        r"\bgoogle[- ]?ads\b", r"\badsense\b", r"\badchoices\b"
    ],
    "data_selling": [
        r"sell(ing)?\s+(your|user|personal)\s+data", r"data\s+broker",
        r"\bsell\s+data\b", r"\bpersonal data\s+for sale\b",
        r"بيع\s+البيانات", r"מכירת\s+נתונים", r"מוכר(?:ים)?\s+נתונים"
    ],
    "black": [
        r"\bracist\b", r"\bracism\b", r"\bhate speech\b", r"\bneo[- ]?nazi\b",
        r"\bwhite suprem", r"\bterrorist propaganda\b", r"\bviolent extremist\b",
        r"\bexplicit sexual\b", r"\bpornograph", r"\bgore\b",
        r"גזענ", r"אלימות", r"תוכן בוטה", r"תוכן מיני"
    ],
    "harmful": [
        r"\bmalware\b", r"\bransomware\b", r"\bphishing\b",
        r"\bcredential stealer\b", r"\bkeylogger\b", r"\bexploit kit\b",
        r"\bdrive[- ]by download\b", r"\bscam\b",
        r"תוכנה זדונית", r"נוזקה", r"פישינג", r"הונאה"
    ],
}


def classify(row):
    text = " ".join(str(row.get(field, "") or "") for field in
                    ("title", "description", "text", "url", "final_url")).casefold()
    flags = []
    for category, patterns in PATTERNS.items():
        if any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns):
            flags.append(category)

    # Harmful content takes precedence over the other warning levels.
    level = "harmful" if "harmful" in flags else (
        "black" if "black" in flags else (
            "data_selling" if "data_selling" in flags else (
                "ads" if "ads" in flags else "none"
            )
        )
    )
    return level


def search_rows(rows, query: str, limit: int = 20):
    terms = [term.casefold() for term in query.split() if term.strip()]
    results = []

    for row in rows:
        searchable = " ".join(
            str(row.get(field, "") or "")
            for field in ("title", "description", "text", "url", "final_url")
        ).casefold()
        score = sum(searchable.count(term) for term in terms)
        if score == 0:
            continue

        title = row.get("title") or row.get("url") or row.get("final_url") or "ללא כותרת"
        url = row.get("final_url") or row.get("url") or ""
        text = row.get("text") or row.get("description") or ""
        snippet = " ".join(text.split())
        if len(snippet) > 420:
            snippet = snippet[:420].rsplit(" ", 1)[0] + "…"

        results.append({
            "title": title,
            "url": url,
            "snippet": snippet,
            "score": score,
            "warning": classify(row),
        })

    results.sort(key=lambda item: item["score"], reverse=True)
    return results[:limit]


class handler(BaseHTTPRequestHandler):
    def _send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/api/search":
            query = parse_qs(parsed.query).get("q", [""])[0].strip()
            if not query:
                return self._send_json({"results": [], "query": ""})
            try:
                rows = load_data()
                return self._send_json({
                    "results": search_rows(rows, query),
                    "query": query,
                    "total_indexed": len(rows),
                })
            except Exception as exc:
                return self._send_json({
                    "error": "Unable to load the Sandstorm data index.",
                    "details": str(exc),
                    "results": [],
                }, 500)

        if parsed.path == "/api/status":
            try:
                rows = load_data()
                return self._send_json({"total_crawled": len(rows)})
            except Exception as exc:
                return self._send_json({"total_crawled": 0, "error": str(exc)}, 500)

        self._send_json({"error": "Not found"}, 404)
