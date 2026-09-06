from __future__ import annotations

import html
import re
import sqlite3
from pathlib import Path
from urllib.parse import quote_plus

from bs4 import BeautifulSoup
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
DB = DATA / "search.db"

app = FastAPI(title="Sandstorm Search", version="0.1.0")


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS pages USING fts5(
        url UNINDEXED,
        title,
        description,
        content,
        domain UNINDEXED,
        crawled_at UNINDEXED,
        tokenize='unicode61'
    )""")
    return conn


def clean_html(raw: str) -> tuple[str, str, str]:
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    meta = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    description = meta.get("content", "").strip() if meta else ""
    text = soup.get_text(" ", strip=True)
    return title[:500], description[:1000], text[:500000]


@app.get("/api/search")
def search(q: str = Query(min_length=1, max_length=300), limit: int = Query(10, ge=1, le=50)):
    conn = db()
    try:
        # FTS5 MATCH syntax is deliberately constrained to plain terms.
        terms = re.findall(r"[\w\-]+", q, flags=re.UNICODE)
        if not terms:
            return {"query": q, "results": []}
        match = " AND ".join('"' + t.replace('"', '""') + '"' for t in terms)
        rows = conn.execute(
            "SELECT url,title,description,domain,crawled_at,bm25(pages, 8.0, 4.0, 1.0, 0.5) AS score "
            "FROM pages WHERE pages MATCH ? ORDER BY score LIMIT ?",
            (match, limit),
        ).fetchall()
        return {"query": q, "results": [dict(r) for r in rows]}
    finally:
        conn.close()


@app.get("/health")
def health():
    conn = db()
    try:
        count = conn.execute("SELECT count(*) FROM pages").fetchone()[0]
        return {"ok": True, "indexed_pages": count}
    finally:
        conn.close()


@app.get("/", response_class=HTMLResponse)
def home():
    return HTMLResponse("""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sandstorm Search</title><style>
body{font-family:system-ui,sans-serif;max-width:900px;margin:10vh auto;padding:24px;background:#f5f2eb;color:#3e2723}
h1{font-size:3rem;margin-bottom:.2rem}p{opacity:.75}.search{display:flex;gap:8px}input{flex:1;padding:15px;border:1px solid #c2a67d;border-radius:12px;font-size:18px;background:white}button{padding:0 24px;border:0;border-radius:12px;background:#3e2723;color:white;font-size:17px;cursor:pointer}.result{padding:18px 0;border-bottom:1px solid #d8cbb8}.result a{font-size:20px;color:#704214}.url{font-size:13px;opacity:.65}.desc{margin-top:7px;line-height:1.5}
</style></head><body><h1>Sandstorm</h1><p>Search indexed pages from the Common Crawl dataset.</p>
<form class="search" onsubmit="search(event)"><input id="q" autofocus placeholder="Search the web..."><button>Search</button></form><main id="results"></main>
<script>
async function search(e){e.preventDefault();const q=document.getElementById('q').value.trim();if(!q)return;const box=document.getElementById('results');box.innerHTML='<p>Searching...</p>';const r=await fetch('/api/search?q='+encodeURIComponent(q));const d=await r.json();box.innerHTML=d.results.length?d.results.map(x=>`<article class="result"><a href="${x.url}" target="_blank" rel="noopener">${escapeHtml(x.title||x.url)}</a><div class="url">${escapeHtml(x.url)}</div><div class="desc">${escapeHtml(x.description||'')}</div></article>`).join(''):'<p>No indexed results yet.</p>';}
function escapeHtml(s){return String(s).replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]));}
</script></body></html>""")
"""
