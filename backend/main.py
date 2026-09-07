from __future__ import annotations

import html
import re
import sqlite3
from pathlib import Path

from bs4 import BeautifulSoup
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse

from .private_store import router as private_router
from .safesearch import filter_safe_pages

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
DB = DATA / "search.db"

app = FastAPI(title="Sandstorm Search", version="0.6.0")
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


def search_rows(q: str, limit: int = 10, safesearch: bool = True):
    conn = db()
    try:
        terms = re.findall(r"[\w\-]+", q, flags=re.UNICODE)
        if not terms:
            return []
        match = " AND ".join('"' + t.replace('"', '""') + '"' for t in terms)
        rows = conn.execute(
            "SELECT url,title,description,domain,crawled_at,bm25(pages,8.0,4.0,1.0,0.5) AS score "
            "FROM pages WHERE pages MATCH ? ORDER BY score LIMIT ?", (match, min(limit * 5, 250))
        ).fetchall()
        pages = [dict(r) for r in rows]
        pages = filter_safe_pages(pages, safesearch)
        return pages[:limit]
    finally:
        conn.close()


@app.get("/api/search")
def search_api(q: str = Query(min_length=1, max_length=300), limit: int = Query(10, ge=1, le=50), safesearch: bool = True):
    return {"query": q, "safesearch": safesearch, "results": search_rows(q, limit, safesearch)}


@app.get("/search", response_class=HTMLResponse)
def search_page(q: str = Query(default="", max_length=300), safesearch: bool = True):
    results = search_rows(q, 20, safesearch) if q.strip() else []
    cards = "".join(
        f'<article class="result"><a href="{html.escape(str(r["url"]), quote=True)}" target="_blank" rel="noopener">'
        f'{html.escape(r["title"] or r["url"])}</a>'
        f'<div class="url">{html.escape(r["url"])}</div>'
        f'<div class="desc">{html.escape(r["description"] or "")}</div></article>'
        for r in results
    )
    if q.strip() and not results:
        cards = '<p class="empty">No indexed results yet, or SafeSearch filtered the available results.</p>'
    return HTMLResponse(PAGE.replace("__QUERY__", html.escape(q)).replace("__RESULTS__", cards).replace("__SAFESEARCH__", "checked" if safesearch else ""))


@app.get("/health")
def health():
    conn = db()
    try:
        return {"ok": True, "indexed_pages": conn.execute("SELECT count(*) FROM pages").fetchone()[0]}
    finally:
        conn.close()


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sandstorm Search</title><style>
:root{--sand-0:#fbf7ef;--sand-1:#f5f2eb;--sand-2:#efe5d2;--sand-3:#e2cfad;--sand-4:#c9ad7a;--sand-5:#a88455;--brown:#4b3426;--brown-2:#704a2c;--line:#d8c5a5;--white:#fffdf8}
*{box-sizing:border-box}body{font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;max-width:980px;margin:0 auto;padding:7vh 24px 60px;background:linear-gradient(180deg,var(--sand-0),var(--sand-1));color:var(--brown);min-height:100vh}header{text-align:center;margin-bottom:34px}h1{font-size:clamp(2.6rem,8vw,4.8rem);letter-spacing:-.06em;margin:0;background:linear-gradient(135deg,var(--brown),var(--brown-2),var(--sand-5));-webkit-background-clip:text;background-clip:text;color:transparent}header p{margin:5px 0 0;color:#806b54}.search{display:flex;gap:10px;max-width:800px;margin:auto;padding:9px;background:var(--sand-2);border:1px solid var(--line);border-radius:18px;box-shadow:0 8px 30px #8d704020}.search input{background:var(--white);border:1px solid var(--line)}input{width:100%;padding:15px 17px;border:1px solid var(--line);border-radius:12px;font-size:17px;color:var(--brown);background:var(--white);outline:none}input:focus{border-color:var(--sand-5);box-shadow:0 0 0 3px #c9ad7a33}button{padding:12px 21px;border:1px solid #4b3426;background:var(--brown);color:#fffaf0;border-radius:12px;font-size:15px;font-weight:650;cursor:pointer;transition:.15s}button:hover{background:var(--brown-2);transform:translateY(-1px)}button:disabled{opacity:.45;cursor:not-allowed;transform:none}.result{padding:20px 8px;border-bottom:1px solid var(--line)}.result a{font-size:20px;color:var(--brown-2);font-weight:650}.url{font-size:13px;color:#8a745c;margin-top:3px;overflow:hidden;text-overflow:ellipsis}.desc{margin-top:8px;line-height:1.55;color:#665444}.empty{padding:20px 8px;color:#806b54}.private{margin-top:34px;padding:24px;border:1px solid var(--line);border-radius:20px;background:linear-gradient(145deg,#f0e5d2,#e8dac1);box-shadow:0 10px 35px #8d704018}.private-title{display:flex;align-items:center;gap:10px;font-size:20px;font-weight:750}.lock-icon{display:grid;place-items:center;width:36px;height:36px;border-radius:50%;background:var(--sand-5);color:#fff8ed}.warning{font-size:13px;line-height:1.55;color:#76614b;max-width:760px}.private input{margin:8px 0;background:#fffaf2}.private-actions{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0}.private-actions button:nth-child(2){background:var(--sand-5);border-color:var(--sand-5)}.private-result{padding:12px 4px;border-top:1px solid var(--line);line-height:1.5}.private-result small{color:#927b60}.status{white-space:pre-wrap;color:#725d46;font-size:13px;margin-top:10px}.locked{opacity:.75}.settings-link{display:block;text-align:center;margin-top:20px;color:var(--brown-2);font-weight:650}.safesearch{display:flex;justify-content:center;align-items:center;gap:8px;margin:14px auto 0;font-size:14px}.safesearch input{width:auto;padding:0}
</style></head><body><header><h1>Sandstorm</h1><p>Search pages indexed from Common Crawl · private by design</p></header>
<form class="search" method="get" action="/search"><input id="q" name="q" value="__QUERY__" autofocus placeholder="Search the web..."><button type="submit">Search</button></form>
<label class="safesearch"><input id="safesearch" type="checkbox" __SAFESEARCH__> SafeSearch</label>
<a class="settings-link" href="/settings.html">⚙ Settings</a>
<main id="results">__RESULTS__</main>
<section class="private"><div class="private-title"><span class="lock-icon">🔒</span>Zero-Knowledge Private Search</div><p class="warning">Private data is encrypted locally with AES-256-GCM. The server receives ciphertext only. The private key is kept as a non-extractable WebCrypto key in this browser session — it is never written to localStorage, cookies, URLs, or the server.</p><div class="private-actions"><button type="button" onclick="unlockPrivate()">Unlock / create session key</button><button type="button" onclick="lockPrivate()">Lock now</button></div><input id="privateText" placeholder="Private note to encrypt" disabled><div class="private-actions"><button type="button" onclick="savePrivate()" disabled id="saveButton">Encrypt &amp; save</button><button type="button" onclick="loadPrivate()" disabled id="loadButton">Load &amp; search locally</button></div><input id="privateQuery" placeholder="Search your private notes..." disabled><div id="privateStatus" class="status">Locked. The private key is not available to this page.</div><div id="privateResults"></div></section>
<script>
const ss=document.getElementById('safesearch');const form=document.querySelector('.search');const params=new URLSearchParams(location.search);const urlSetting=params.has('safesearch')?params.get('safesearch')!=='false':(localStorage.getItem('sandstorm.safesearch')!=='off');ss.checked=urlSetting;ss.addEventListener('change',()=>{localStorage.setItem('sandstorm.safesearch',ss.checked?'on':'off');});form.addEventListener('submit',()=>{const input=document.createElement('input');input.type='hidden';input.name='safesearch';input.value=ss.checked?'true':'false';form.appendChild(input);});
const enc=new TextEncoder(),dec=new TextDecoder();let privateKey=null;const AUTO_LOCK_MS=5*60*1000;let lastActivity=Date.now();
function b64(bytes){let s='';for(const b of bytes)s+=String.fromCharCode(b);return btoa(s).replaceAll('+','-').replaceAll('/','_').replaceAll('=','');}function ub64(s){s=s.replaceAll('-','+').replaceAll('_','/');while(s.length%4)s+='=';const x=atob(s);return Uint8Array.from(x,c=>c.charCodeAt(0));}
async function unlockPrivate(){try{privateKey=await crypto.subtle.generateKey({name:'AES-GCM',length:256},false,['encrypt','decrypt']);lastActivity=Date.now();setPrivateUI(true);document.getElementById('privateStatus').textContent='Unlocked for this browser session. Auto-lock: 5 minutes of inactivity.';}catch(e){document.getElementById('privateStatus').textContent='Cannot create secure session key: '+e.message;}}
function lockPrivate(reason='Locked. The private key was removed from the active session.'){privateKey=null;setPrivateUI(false);document.getElementById('privateResults').textContent='';document.getElementById('privateStatus').textContent=reason;}
function setPrivateUI(unlocked){for(const id of ['privateText','privateQuery','saveButton','loadButton'])document.getElementById(id).disabled=!unlocked;document.querySelector('.private').classList.toggle('locked',!unlocked);}
function touch(){if(privateKey)lastActivity=Date.now();}['pointerdown','keydown','mousemove','touchstart'].forEach(e=>document.addEventListener(e,touch,{passive:true}));setInterval(()=>{if(privateKey&&Date.now()-lastActivity>AUTO_LOCK_MS)lockPrivate('Auto-locked after 5 minutes of inactivity.');},15000);document.addEventListener('visibilitychange',()=>{if(document.hidden&&privateKey)lockPrivate('Locked because the page was hidden. Unlock again when you return.');});window.addEventListener('pagehide',()=>lockPrivate('Session ended.'));
async function encryptLocal(text){if(!privateKey)throw new Error('Private search is locked.');touch();const nonce=crypto.getRandomValues(new Uint8Array(12));const ct=new Uint8Array(await crypto.subtle.encrypt({name:'AES-GCM',iv:nonce},privateKey,enc.encode(text)));return b64(new Uint8Array([...nonce,...ct]));}async function decryptLocal(token){if(!privateKey)throw new Error('Private search is locked.');touch();const data=ub64(token);if(data.length<=12)throw new Error('Invalid encrypted blob');return dec.decode(await crypto.subtle.decrypt({name:'AES-GCM',iv:data.slice(0,12)},privateKey,data.slice(12)));}
async function savePrivate(){const status=document.getElementById('privateStatus'),text=document.getElementById('privateText').value;if(!text)return;try{const blob=await encryptLocal(text);const r=await fetch('/api/private/blobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({blob})});const d=await r.json();if(!r.ok)throw new Error(d.detail||'Upload failed');document.getElementById('privateText').value='';status.textContent='Saved encrypted blob '+d.id+'. The server never received the key.';await loadPrivate();}catch(e){status.textContent='Error: '+e.message;}}
async function loadPrivate(){const status=document.getElementById('privateStatus'),box=document.getElementById('privateResults');try{const r=await fetch('/api/private/blobs');const d=await r.json();if(!r.ok)throw new Error(d.detail||'Load failed');const notes=[];for(const item of d.results){try{notes.push({id:item.id,text:await decryptLocal(item.blob)});}catch(_){}}const q=document.getElementById('privateQuery').value.trim().toLowerCase();const hits=q?notes.filter(n=>n.text.toLowerCase().includes(q)):notes;box.innerHTML=hits.length?hits.map(n=>`<div class="private-result"><small>${escapeHtml(n.id)}</small><br>${escapeHtml(n.text)}</div>`).join(''):'<p>No matching private notes.</p>';status.textContent=`Loaded ${notes.length} decryptable private note(s). Search is local.`;}catch(e){status.textContent='Error: '+e.message;box.innerHTML='';}}
document.getElementById('privateQuery').addEventListener('input',loadPrivate);function escapeHtml(s){return String(s).replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]));}
</script></body></html>"""
