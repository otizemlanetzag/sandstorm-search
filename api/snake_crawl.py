import csv
import random
from pathlib import Path
import io
import ipaddress
import json
import os
import re
import socket
import time
import urllib.request
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler
from html.parser import HTMLParser
from urllib.parse import urljoin, urldefrag, urlparse

SESSION_COOKIE = "snake_session"
SESSION_TTL = 3600
USER_AGENT = "ServoShell/1.0 (or Opera) AppleWebKit/537.36"
FIELDS = ["url","final_url","status","content_type","title","description","text","links","depth","crawled_at","content"]

def _secret():
    return os.environ.get("SNAKE_CRAWL_SECRET", "").strip()

def _sign(value):
    import hmac, hashlib
    return hmac.new(_secret().encode(), value.encode(), hashlib.sha256).hexdigest()

def _session_cookie():
    stamp=str(int(time.time()))
    return f"{SESSION_COOKIE}={stamp}.{_sign(stamp)}; Path=/; Max-Age={SESSION_TTL}; HttpOnly; Secure; SameSite=Strict"

def _valid_session(h):
    if not _secret(): return False
    import hmac
    c=SimpleCookie()
    try:
        c.load(h.headers.get("Cookie",""))
        value=c[SESSION_COOKIE].value
        stamp,sig=value.split(".",1)
        return abs(int(time.time())-int(stamp))<=SESSION_TTL and hmac.compare_digest(sig,_sign(stamp))
    except Exception:
        return False

def _safe_public_url(url):
    try:
        p=urlparse(url)
        if p.scheme not in ("http","https") or not p.hostname: return False
        if p.hostname.lower() in ("localhost","localhost.localdomain"): return False
        for info in socket.getaddrinfo(p.hostname,None):
            ip=ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified: return False
        return True
    except Exception: return False

class Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.title=[]; self.description=""; self.text=[]; self.links=[]; self.in_title=False; self.skip=0
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=="title": self.in_title=True
        if tag in ("script","style","noscript","svg","template"): self.skip+=1
        if tag=="meta" and a.get("name","").lower()=="description": self.description=a.get("content","")
        if tag=="a" and a.get("href"): self.links.append(a["href"])
    def handle_endtag(self,tag):
        if tag=="title": self.in_title=False
        if tag in ("script","style","noscript","svg","template") and self.skip: self.skip-=1
    def handle_data(self,data):
        if self.in_title: self.title.append(data)
        if not self.skip: self.text.append(data)

def _clean(v,n): return re.sub(r"\s+"," ",v or "").strip()[:n]

def _normalize(u):
    u,_=urldefrag(u); p=urlparse(u)
    if p.scheme not in ("http","https") or not p.netloc: return None
    return p._replace(scheme=p.scheme.lower(),netloc=p.netloc.lower()).geturl()

def _crawl_one(url,max_depth,same_domain,seed_host):
    url=_normalize(url)
    if not url: return {"url":"","final_url":"","status":"error","content_type":"error","text":"Invalid URL"},[]
    if not _safe_public_url(url): return {"url":url,"final_url":url,"status":"blocked","content_type":"","text":"Private or local address blocked"},[]
    if same_domain and urlparse(url).netloc!=seed_host: return {"url":url,"final_url":url,"status":"blocked","content_type":"","text":"Outside selected domain"},[]
    try:
        req=urllib.request.Request(url,headers={"User-Agent":USER_AGENT,"Accept":"text/html,application/xhtml+xml;q=0.9,*/*;q=0.1"})
        with urllib.request.urlopen(req,timeout=10) as r:
            raw=r.read(1500000); final=r.geturl(); ctype=r.headers.get_content_type(); charset=r.headers.get_content_charset() or "utf-8"; status=r.status
        if "html" not in ctype and "xhtml" not in ctype:
            return {"url":url,"final_url":final,"status":status,"content_type":ctype,"text":raw[:10000].decode(charset,errors="replace"),"links":[],"depth":0,"crawled_at":time.strftime("%Y-%m-%d %H:%M:%S")},[]
        p=Parser(); p.feed(raw.decode(charset,errors="replace"))
        links=[]
        for href in p.links[:300]:
            n=_normalize(urljoin(final,href))
            if n and (not same_domain or urlparse(n).netloc==seed_host): links.append(n)
        links=list(dict.fromkeys(links))
        row={"url":url,"final_url":final,"status":status,"content_type":ctype,"title":_clean(" ".join(p.title),500),"description":_clean(p.description,1000),"text":_clean(" ".join(p.text),10000),"links":links,"depth":0,"crawled_at":time.strftime("%Y-%m-%d %H:%M:%S")}
        return row,links
    except Exception as e:
        return {"url":url,"final_url":url,"status":"error","content_type":"error","text":str(e),"links":[],"depth":0,"crawled_at":time.strftime("%Y-%m-%d %H:%M:%S")},[]

def _body(h):
    n=int(h.headers.get("Content-Length","0"))
    return json.loads(h.rfile.read(min(n,65536)).decode("utf-8","replace") or "{}")

def _json(h,status,payload,extra=None):
    raw=json.dumps(payload,ensure_ascii=False).encode()
    h.send_response(status); h.send_header("Content-Type","application/json; charset=utf-8"); h.send_header("Cache-Control","no-store")
    for k,v in (extra or {}).items(): h.send_header(k,v)
    h.send_header("Content-Length",str(len(raw))); h.end_headers(); h.wfile.write(raw)

class BackgroundCrawlHandler(BaseHTTPRequestHandler):
    """Small public, opt-out browser-driven slice of the normal crawler.

    It never accepts a user-supplied target. It selects one public URL from
    Sandstorm's local shared DATA.CSV and crawls exactly one page.
    """

    def do_GET(self):
        if urlparse(self.path).path.rstrip("/") != "/api/snake-crawl/background":
            _json(self, 404, {"error": "Unknown endpoint"})
            return

        now = time.time()
        client = self.client_address[0] if self.client_address else "unknown"
        last = getattr(self.server, "_background_last", {})
        if now - last.get(client, 0) < 30:
            _json(self, 429, {"error": "Background crawl is rate limited"})
            return
        last[client] = now
        self.server._background_last = last

        data_path = Path(__file__).resolve().parent.parent / "embedded" / "snake-crawl" / "DATA.CSV"
        try:
            with data_path.open("r", encoding="utf-8-sig", newline="") as f:
                urls = []
                for row in csv.DictReader(f):
                    url = (row.get("url") or row.get("final_url") or "").strip()
                    if url and _safe_public_url(url):
                        urls.append(url)

            if not urls:
                _json(self, 503, {"error": "No crawl targets available"})
                return

            url = random.choice(urls)
            row, _ = _crawl_one(
                url,
                max_depth=0,
                same_domain=True,
                seed_host=urlparse(url).netloc,
            )
            _json(self, 200, {"ok": True, "result": row})
        except Exception as exc:
            _json(self, 502, {"error": "Background crawl failed", "detail": str(exc)})

    def log_message(self, *args):
        return


class SnakeCrawlHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        path=urlparse(self.path).path.rstrip("/")
        if path=="/api/snake-crawl/auth":
            try:
                body=_body(self); ok=bool(_secret()) and str(body.get("code","")).strip()==_secret()
                _json(self,200 if ok else 401,{"authenticated":ok},{"Set-Cookie":_session_cookie()} if ok else None)
            except Exception: _json(self,400,{"authenticated":False})
            return
        if not _valid_session(self): _json(self,401,{"error":"Authentication required"}); return
        try:
            body=_body(self)
            if path=="/api/snake-crawl/crawl":
                urls=body.get("urls",[])
                if not isinstance(urls,list) or not urls or len(urls)>8: _json(self,400,{"error":"Provide 1-8 URLs"}); return
                seed=body.get("seed_host",""); same=bool(body.get("same_domain",True))
                rows=[]
                for u in urls:
                    row,_=_crawl_one(u,int(body.get("max_depth",2)),same,seed)
                    row["depth"]=int(body.get("depths",{}).get(u,0)) if isinstance(body.get("depths",{}),dict) else 0
                    rows.append(row)
                _json(self,200,{"results":rows}); return
            if path=="/api/snake-crawl/advanced":
                import random,string
                tlds=["com","org","net","io","ai","dev","app"]
                count=max(1,min(10,int(body.get("count",5)))); maxchars=max(1,min(20,int(body.get("max_characters",20))))
                results=[]
                for _ in range(count):
                    label="".join(random.choice(string.ascii_lowercase+string.digits+"-") for _ in range(random.randint(1,maxchars))).strip("-") or "a"
                    u="https://"+label+"."+random.choice(tlds)
                    try:
                        req=urllib.request.Request(u,headers={"User-Agent":USER_AGENT})
                        with urllib.request.urlopen(req,timeout=5) as r: results.append({"url":u,"final_url":r.geturl(),"status":r.status,"content_type":r.headers.get("Content-Type",""),"content":re.sub(r"\s+"," ",r.read(100000).decode("utf-8","replace"))[:100000]})
                    except Exception as e: results.append({"url":u,"status":"error","error":str(e)})
                _json(self,200,{"results":results}); return
            if path=="/api/snake-crawl/save_csv":
                rows=body.get("rows",[])
                if not isinstance(rows,list): _json(self,400,{"error":"rows must be a list"}); return
                _json(self,200,{"saved":len(rows),"total":len(rows)}); return
            _json(self,404,{"error":"Unknown Snake Crawl endpoint"})
        except Exception as e: _json(self,500,{"error":"Request failed"})
    def log_message(self,*args): return
