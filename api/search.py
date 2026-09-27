from __future__ import annotations

import ipaddress
import json
import re
import socket
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler

from ask import load_data
from sandbox import run_in_sandbox


EU_COUNTRIES = {
    "AT":"🇦🇹","BE":"🇧🇪","BG":"🇧🇬","HR":"🇭🇷","CY":"🇨🇾","CZ":"🇨🇿",
    "DK":"🇩🇰","EE":"🇪🇪","FI":"🇫🇮","FR":"🇫🇷","DE":"🇩🇪","GR":"🇬🇷",
    "HU":"🇭🇺","IE":"🇮🇪","IT":"🇮🇹","LV":"🇱🇻","LT":"🇱🇹","LU":"🇱🇺",
    "MT":"🇲🇹","NL":"🇳🇱","PL":"🇵🇱","PT":"🇵🇹","RO":"🇷🇴","SK":"🇸🇰",
    "SI":"🇸🇮","ES":"🇪🇸","SE":"🇸🇪"
}
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

def scan_site(url):
    _safe_url(url)
    req=urllib.request.Request(url,headers={"User-Agent":"Sandstorm Security Scanner/1.0"})
    with urllib.request.urlopen(req,timeout=10) as response:
        final_url=response.geturl(); content_type=response.headers.get("Content-Type",""); body=response.read(2_000_000)
    text=body.decode("utf-8",errors="replace"); parser=ScriptParser()
    if "html" in content_type.lower() or "<html" in text[:1000].lower(): parser.feed(text)
    sources=[text]
    for src in parser.scripts:
        if not src or src.startswith(("data:","blob:")): continue
        try:
            script_url=urllib.parse.urljoin(final_url,src); _safe_url(script_url)
            req=urllib.request.Request(script_url,headers={"User-Agent":"Sandstorm Security Scanner/1.0"})
            with urllib.request.urlopen(req,timeout=5) as response: sources.append(response.read(1_000_000).decode("utf-8",errors="replace"))
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

class handler(BaseHTTPRequestHandler):
    def _send_json(self,payload,status=200):
        body=json.dumps(payload,ensure_ascii=False).encode("utf-8"); self.send_response(status)
        self.send_header("Content-Type","application/json; charset=utf-8"); self.send_header("Cache-Control","no-store"); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        parsed=urllib.parse.urlparse(self.path)
        if parsed.path=="/api/dictionary":
            query=urllib.parse.parse_qs(parsed.query).get("q",[""])[0].strip()
            if not query:return self._send_json({"found":False,"word":"","entries":[]})
            try:return self._send_json(dictionary_lookup(query))
            except Exception as exc:return self._send_json({"found":False,"word":query,"entries":[],"error":str(exc)},502)
        if parsed.path=="/api/search":
            query=urllib.parse.parse_qs(parsed.query).get("q",[""])[0].strip()\n            location=urllib.parse.parse_qs(parsed.query).get("location",[""])[0].strip()
            if not query:return self._send_json({"results":[],"query":""})
            try:
                rows=load_data(); return self._send_json({"results":search_rows(rows,query,location),"query":query,"total_indexed":len(rows)})
            except Exception as exc:return self._send_json({"error":"Unable to load the Sandstorm data index.","details":str(exc),"results":[]},500)
        if parsed.path=="/api/scan":
            url=urllib.parse.parse_qs(parsed.query).get("url",[""])[0].strip()
            try:return self._send_json(run_in_sandbox(scan_site,url))
            except Exception as exc:return self._send_json({"error":"Site scan failed.","details":str(exc)},502)
        if parsed.path=="/api/status":
            try:return self._send_json({"total_crawled":len(load_data())})
            except Exception as exc:return self._send_json({"total_crawled":0,"error":str(exc)},500)
        self._send_json({"error":"Not found"},404)
