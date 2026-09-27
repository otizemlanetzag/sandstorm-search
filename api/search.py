from __future__ import annotations

import ipaddress
import json
import re
import socket
import urllib.parse
import urllib.request
from html.parser import HTMLParser

try:
    import argostranslate.package
    import argostranslate.translate
except ImportError:
    argostranslate = None
from http.server import BaseHTTPRequestHandler
import time
from collections import defaultdict, deque

from ask import load_data
from sandbox import run_in_sandbox


EU_COUNTRIES = {
    "AT":"🇦🇹","BE":"🇧🇪","BG":"🇧🇬","HR":"🇭🇷","CY":"🇨🇾","CZ":"🇨🇿",
    "DK":"🇩🇰","EE":"🇪🇪","FI":"🇫🇮","FR":"🇫🇷","DE":"🇩🇪","GR":"🇬🇷",
    "HU":"🇭🇺","IE":"🇮🇪","IT":"🇮🇹","LV":"🇱🇻","LT":"🇱🇹","LU":"🇱🇺",
    "MT":"🇲🇹","NL":"🇳🇱","PL":"🇵🇱","PT":"🇵🇹","RO":"🇷🇴","SK":"🇸🇰",
    "SI":"🇸🇮","ES":"🇪🇸","SE":"🇸🇪"
}
MAX_QUERY_LENGTH = 500
MAX_LOCATION_LENGTH = 120
MAX_REQUEST_TARGET = 4096
RATE_WINDOW_SECONDS = 60
RATE_MAX_REQUESTS = 60
_rate_log = defaultdict(deque)

def _client_ip(handler):
    return handler.client_address[0] if handler.client_address else "unknown"

def _rate_limited(ip):
    now = time.monotonic()
    bucket = _rate_log[ip]
    while bucket and now - bucket[0] > RATE_WINDOW_SECONDS:
        bucket.popleft()
    if len(bucket) >= RATE_MAX_REQUESTS:
        return True
    bucket.append(now)
    return False

def _clean_query(value, maximum=MAX_QUERY_LENGTH):
    value = (value or "").strip()
    if len(value) > maximum:
        raise ValueError("Input is too long.")
    return value

COUNTRY_FLAGS = {**EU_COUNTRIES, "IL":"🇮🇱","US":"🇺🇸","GB":"🇬🇧","CA":"🇨🇦","CH":"🇨🇭",
                 "NO":"🇳🇴","IS":"🇮🇸","AU":"🇦🇺","NZ":"🇳🇿","JP":"🇯🇵","CN":"🇨🇳",
                 "IN":"🇮🇳","BR":"🇧🇷","MX":"🇲🇽","RU":"🇷🇺","UA":"🇺🇦","TR":"🇹🇷"}

PATTERNS = {
    "ads":[r"\badvertis",r"\badvertisement",r"\bsponsored\b",r"\bbanner\b",r"\bgoogle[- ]?ads\b",r"\badsense\b",r"\badchoices\b"],
    "data_selling":[r"sell(ing)?\s+(your|user|personal)\s+data",r"data\s+broker",r"\bsell\s+data\b",r"\bpersonal data\s+for sale\b",r"بيع\s+البيانات",r"מכירת\s+נתונים",r"מוכר(?:ים)?\s+נתונים"],
    "black":[r"\bracist\b",r"\bracism\b",r"\bhate speech\b",r"\bneo[- ]?nazi\b",r"\bwhite suprem",r"\bterrorist propaganda\b",r"\bviolent extremist\b",r"\bexplicit sexual\b",r"\bpornograph",r"\bgore\b",r"גזענ",r"אלימות",r"תוכן בוטה",r"תוכן מיני"],
    "harmful":[r"\bmalware\b",r"\bransomware\b",r"\bphishing\b",r"\bcredential stealer\b",r"\bkeylogger\b",r"\bexploit kit\b",r"\bdrive[- ]by download\b",r"\bscam\b",r"תוכנה זדונית",r"נוזקה",r"פישינג",r"הונאה"],
    "suspicious_code":[r"eval\s*\(",r"new\s+Function\s*\(",r"document\.write\s*\(",r"atob\s*\(",r"fromCharCode\s*\(",r"powershell",r"cmd\.exe",r"mshta",r"javascript:\s*",r"crypto(?:miner|nightmare)",r"coinhive",r"\bminer\b"]
}

class ScriptParser(HTMLParser):
    def __init__(self): super().__init__(); self.scripts=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag.lower()=="script": self.scripts.append(attrs.get("src"))

def classify_text(text):
    flags=[category for category,patterns in PATTERNS.items() if any(re.search(p,text,re.I) for p in patterns)]
    level="harmful" if "harmful" in flags or "suspicious_code" in flags else "black" if "black" in flags else "data_selling" if "data_selling" in flags else "ads" if "ads" in flags else "none"
    return level,flags

def classify(row):
    text=" ".join(str(row.get(f,"") or "") for f in ("title","description","text","url","final_url")).casefold()
    return classify_text(text)[0]

def _safe_url(url):
    parsed=urllib.parse.urlparse(url)
    if parsed.scheme not in ("http","https") or not parsed.hostname: raise ValueError("Only HTTP and HTTPS URLs can be scanned.")
    try:
        for info in socket.getaddrinfo(parsed.hostname,None):
            if not ipaddress.ip_address(info[4][0]).is_global: raise ValueError("Private or local network addresses cannot be scanned.")
    except socket.gaierror as exc: raise ValueError("The host could not be resolved.") from exc

def country_from_url(url, content=""):
    host=(urllib.parse.urlparse(url).hostname or "").lower()
    parts=host.split(".")
    tld=parts[-1].upper() if parts else ""

    # .ai is primarily a technology/AI domain now, not a country indicator.
    # Determine its likely location from the site's actual content instead.
    if tld == "AI":
        return country_from_content(content)

    if tld in COUNTRY_FLAGS:
        return {"code":tld,"flag":COUNTRY_FLAGS[tld],"eu":tld in EU_COUNTRIES}
    if tld == "EU":
        return {"code":"EU","flag":"🇪🇺","eu":True}
    return country_from_content(content)


def country_from_content(content):
    text=content.casefold()
    hints=[
        ("IL", ["israel","ישראל","hebrew","עברית"]),
        ("FR", ["france","français","français","france"]),
        ("DE", ["germany","deutschland","german"]),
        ("ES", ["spain","españa","spanish"]),
        ("IT", ["italy","italia","italiano"]),
        ("NL", ["netherlands","nederland","dutch"]),
        ("US", ["united states","usa","american"]),
        ("GB", ["united kingdom","england","british"]),
        ("CA", ["canada","canadian"]),
        ("JP", ["japan","日本","japanese"]),
        ("CN", ["china","中国","chinese"]),
        ("IN", ["india","भारत","indian"]),
        ("BR", ["brazil","brasil","brazilian"]),
    ]
    for code,words in hints:
        if any(word in text for word in words):
            return {"code":code,"flag":COUNTRY_FLAGS[code],"eu":code in EU_COUNTRIES}
    return {"code":"","flag":"🌐","eu":False}

class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _safe_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)

_SAFE_OPENER = urllib.request.build_opener(_SafeRedirectHandler)

def scan_site(url):
    _safe_url(url)
    req=urllib.request.Request(url,headers={"User-Agent":"Sandstorm Security Scanner/1.0"})
    with _SAFE_OPENER.open(req,timeout=10) as response:
        final_url=response.geturl(); _safe_url(final_url); content_type=response.headers.get("Content-Type",""); body=response.read(2_000_000)
    text=body.decode("utf-8",errors="replace"); parser=ScriptParser()
    if "html" in content_type.lower() or "<html" in text[:1000].lower(): parser.feed(text)
    sources=[text]
    for src in parser.scripts:
        if not src or src.startswith(("data:","blob:")): continue
        try:
            script_url=urllib.parse.urljoin(final_url,src); _safe_url(script_url)
            req=urllib.request.Request(script_url,headers={"User-Agent":"Sandstorm Security Scanner/1.0"})
            with _SAFE_OPENER.open(req,timeout=5) as response: sources.append(response.read(1_000_000).decode("utf-8",errors="replace"))
        except Exception: continue
    level,flags=classify_text("\n".join(sources))
    return {"url":url,"final_url":final_url,"level":level,"flags":flags,"country":country_from_url(final_url,text),"scanned_bytes":sum(len(s.encode("utf-8",errors="ignore")) for s in sources),"scripts_scanned":len(sources)-1,"note":"Static inspection only; the site code was not executed."}

def location_score(row, location):
    if not location:
        return 0
    needle=location.casefold().strip()
    hay=" ".join(str(row.get(f,"") or "") for f in ("title","description","text","url","final_url")).casefold()
    return 4 if needle in hay else 0

def search_rows(rows,query,location="",limit=20):
    terms=[t.casefold() for t in query.split() if t.strip()]; results=[]
    for row in rows:
        searchable=" ".join(str(row.get(f,"") or "") for f in ("title","description","text","url","final_url")).casefold()
        score=sum(searchable.count(t) for t in terms)\n        score += location_score(row, location)
        if not score: continue
        title=row.get("title") or row.get("url") or row.get("final_url") or "ללא כותרת"; url=row.get("final_url") or row.get("url") or ""
        text=row.get("text") or row.get("description") or ""; snippet=" ".join(text.split())
        if len(snippet)>420: snippet=snippet[:420].rsplit(" ",1)[0]+"…"
        results.append({"title":title,"url":url,"snippet":snippet,"score":score,"warning":classify(row),"country":country_from_url(url,text)})
    results.sort(key=lambda x:x["score"],reverse=True); return results[:limit]


def _translation_language(text):
    return "en" if re.search(r"[\\u0590-\\u05FF]", text) else "he"

def dictionary_lookup(query):
    """Translate short queries locally with Argos Translate models."""
    query = query.strip()
    if not query or len(query) > 500:
        return {"found": False, "word": query, "entries": []}
    if argostranslate is None:
        return {"found": False, "word": query, "entries": [], "error": "Argos Translate is not installed."}
    source = _translation_language(query)
    target = "en" if source == "he" else "he"
    try:
        translated = argostranslate.translate.translate(query, source, target)
    except Exception as exc:
        return {
            "found": False,
            "word": query,
            "entries": [],
            "error": "No local Argos translation model is installed.",
            "details": str(exc)
        }
    return {
        "found": bool(translated),
        "word": query,
        "source_language": source,
        "target_language": target,
        "entries": [{"translation": translated}],
        "provider": "Argos Translate (local)"
    }


class handler(BaseHTTPRequestHandler):
    server_version = "SandstormSearch"
    sys_version = ""

    def _send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _guard(self):
        if len(self.path) > MAX_REQUEST_TARGET:
            self._send_json({"error": "Request is too large."}, 414)
            return False
        if _rate_limited(_client_ip(self)):
            self._send_json({"error": "Too many requests. Please try again shortly."}, 429)
            return False
        return True

    def do_GET(self):
        if not self._guard():
            return
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query, keep_blank_values=False)

        if parsed.path == "/api/dictionary":
            try:
                query = _clean_query(params.get("q", [""])[0])
            except ValueError:
                return self._send_json({"error": "Query is too long."}, 400)
            if not query:
                return self._send_json({"found": False, "word": "", "entries": []})
            try:
                return self._send_json(dictionary_lookup(query))
            except Exception:
                return self._send_json({"found": False, "word": query, "entries": [], "error": "Translation failed."}, 502)

        if parsed.path == "/api/search":
            try:
                query = _clean_query(params.get("q", [""])[0])
                location = _clean_query(params.get("location", [""])[0], MAX_LOCATION_LENGTH)
            except ValueError:
                return self._send_json({"error": "Input is too long.", "results": []}, 400)
            if not query:
                return self._send_json({"results": [], "query": ""})
            try:
                rows = load_data()
                return self._send_json({"results": search_rows(rows, query, location), "query": query, "total_indexed": len(rows)})
            except Exception:
                return self._send_json({"error": "Unable to load the Sandstorm data index.", "results": []}, 500)

        if parsed.path == "/api/scan":
            try:
                url = _clean_query(params.get("url", [""])[0], 2048)
                if not url:
                    return self._send_json({"error": "URL is required."}, 400)
                return self._send_json(run_in_sandbox(scan_site, url))
            except Exception:
                return self._send_json({"error": "Site scan failed."}, 502)

        if parsed.path == "/api/status":
            try:
                return self._send_json({"total_crawled": len(load_data())})
            except Exception:
                return self._send_json({"total_crawled": 0, "error": "Status unavailable."}, 500)

        return self._send_json({"error": "Not found"}, 404)

    def log_message(self, format, *args):
        return
