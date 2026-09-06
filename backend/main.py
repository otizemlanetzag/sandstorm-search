from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from bs4 import BeautifulSoup
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse

from .private_store import router as private_router

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
DB = DATA / "search.db"

app = FastAPI(title="Sandstorm Search", version="0.2.0")
app.include_router(private_router)


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS pages USING fts5(
        url UNINDEXED, title, description, content,
        domain UNINDEXED, crawled_at UNINDEXED,
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
        terms = re.findall(r"[\w\-]+", q, flags=re.UNICODE)
        if not terms:
            return {"query": q, "results": []}
        match = " AND ".join('"' + t.replace('"', '""') + '"' for t in terms)
        rows = conn.execute(
            "SELECT url,title,description,domain,crawled_at,bm25(pages,8.0,4.0,1.0,0.5) AS score "
            "FROM pages WHERE pages MATCH ? ORDER BY score LIMIT ?", (match, limit)
        ).fetchall()
        return {"query": q, "results": [dict(r) for r in rows]}
    finally:
        conn.close()


@app.get("/health")
def health():
    conn = db()
    try:
        return {"ok": True, "indexed_pages": conn.execute("SELECT count(*) FROM pages").fetchone()[0]}
    finally:
        conn.close()


@app.get("/", response_class=HTMLResponse)
def home():
    return HTMLResponse("""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sandstorm Search</title><style>
body{font-family:system-ui,sans-serif;max-width:900px;margin:10vh auto;padding:24px;background:#f5f2eb;color:#3e2723}h1{font-size:3rem;margin-bottom:.2rem}p{opacity:.75}.search{display:flex;gap:8px}input{flex:1;padding:15px;border:1px solid #c2a67d;border-radius:12px;font-size:18px}button{padding:0 24px;border:0;border-radius:12px;background:#3e2723;color:white;font-size:17px;cursor:pointer}.result{padding:18px 0;border-bottom:1px solid #d8cbb8}.result a{font-size:20px;color:#704214}.url{font-size:13px;opacity:.65}.desc{margin-top:7px;line-height:1.5}.private{margin-top:28px;padding:18px;border:1px solid #c2a67d;border-radius:14px;background:#efeae0}
</style></head><body><h1>Sandstorm</h1><p>Search pages indexed from Common Crawl.</p>
<form class="search" onsubmit="search(event)"><input id="q" autofocus placeholder="Search the web..."><button>Search</button></form><main id="results"></main>
<section class="private"><strong>Zero-Knowledge Private Storage</strong><p>Private data is encrypted in your browser before upload. Sandstorm stores only ciphertext and never receives your encryption key.</p><button type="button" onclick="createPrivateBlob()">Create encrypted test blob</button><pre id="privateStatus"></pre></section>
<script>
const enc=new TextEncoder();const dec=new TextDecoder();
function b64(bytes){let s='';for(const b of bytes)s+=String.fromCharCode(b);return btoa(s).replaceAll('+','-').replaceAll('/','_').replaceAll('=','');}
function ub64(s){s=s.replaceAll('-','+').replaceAll('_','/');while(s.length%4)s+='=';const x=atob(s);return Uint8Array.from(x,c=>c.charCodeAt(0));}
async function createPrivateBlob(){const out=document.getElementById('privateStatus');try{const key=crypto.getRandomValues(new Uint8Array(32));const nonce=crypto.getRandomValues(new Uint8Array(12));const plaintext=prompt('Text to encrypt locally:');if(plaintext===null)return;const k=await crypto.subtle.importKey('raw',key,{name:'AES-GCM'},false,['encrypt']);const ct=new Uint8Array(await crypto.subtle.encrypt({name:'AES-GCM',iv:nonce},k,enc.encode(plaintext)));const token=b64(new Uint8Array([...nonce,...ct]));const r=await fetch('/api/private/blobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({blob:token})});const d=await r.json();if(!r.ok)throw new Error(d.detail||'Upload failed');localStorage.setItem('sandstorm_private_key',b64(key));out.textContent='Encrypted blob stored. ID: '+d.id+'\nThe server never received the key. Keep your key safe.';}catch(e){out.textContent='Error: '+e.message;}}
async function search(e){e.preventDefault();const q=document.getElementById('q').value.trim();if(!q)return;const box=document.getElementById('results');box.innerHTML='<p>Searching...</p>';const r=await fetch('/api/search?q='+encodeURIComponent(q));const d=await r.json();box.innerHTML=d.results.length?d.results.map(x=>`<article class="result"><a href="${x.url}" target="_blank" rel="noopener">${escapeHtml(x.title||x.url)}</a><div class="url">${escapeHtml(x.url)}</div><div class="desc">${escapeHtml(x.description||'')}</div></article>`).join(''):'<p>No indexed results yet.</p>';}
function escapeHtml(s){return String(s).replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]));}
</script></body></html>""")
