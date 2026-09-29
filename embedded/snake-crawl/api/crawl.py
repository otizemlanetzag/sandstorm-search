import json
import re
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urldefrag, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from .security import safe_public_url, valid_session

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 OPR/120.0.0.0"

class Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title=[]; self.description=""; self.text=[]; self.links=[]
        self.in_title=False; self.skip=0
    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if tag=="title": self.in_title=True
        if tag in ("script","style","noscript","svg","template"): self.skip+=1
        if tag=="meta" and a.get("name","").lower()=="description": self.description=a.get("content","")
        if tag=="a" and a.get("href"): self.links.append(a["href"])
    def handle_endtag(self, tag):
        if tag=="title": self.in_title=False
        if tag in ("script","style","noscript","svg","template") and self.skip: self.skip-=1
    def handle_data(self,data):
        if self.in_title:self.title.append(data)
        if not self.skip:self.text.append(data)

def clean(v, limit):
    return re.sub(r"\s+"," ",v or "").strip()[:limit]

def normalize(u):
    u,_=urldefrag(u)
    p=urlparse(u)
    if p.scheme not in ("http","https") or not p.netloc:return None
    return p._replace(scheme=p.scheme.lower(),netloc=p.netloc.lower()).geturl()

def row(url, final_url, status, ctype, title="", desc="", text="", links=None, depth=0):
    return {"url":url,"final_url":final_url,"status":status,"content_type":ctype,
            "title":clean(title,500),"description":clean(desc,1000),"text":clean(text,10000),
            "links":links or [],"depth":depth,"crawled_at":time.strftime("%Y-%m-%d %H:%M:%S")}

def crawl_one(url, max_depth, same_domain, seed_host):
    url=normalize(url)
    if url and not safe_public_url(url):
        return row(url,url,"blocked","",text="Private or local address blocked"),[]
    if not url:return row(url or "",url or "","error","error",text="Invalid URL"),[]
    if same_domain and urlparse(url).netloc!=seed_host:return row(url,url,"blocked","",text="Outside selected domain"),[]
    try:
        req=Request(url,headers={"User-Agent":USER_AGENT,"Accept":"text/html,application/xhtml+xml;q=0.9,*/*;q=0.1"})
        with urlopen(req,timeout=10) as r:
            status=r.status; final=r.geturl(); ctype=r.headers.get_content_type()
            charset=r.headers.get_content_charset() or "utf-8"
            raw=r.read(1_500_000)
        if "html" not in ctype and "xhtml" not in ctype:
            return row(url,final,status,ctype,text=raw[:10000].decode(charset,errors="replace")),[]
        p=Parser();p.feed(raw.decode(charset,errors="replace"))
        links=[]
        for href in p.links[:300]:
            n=normalize(urljoin(final,href))
            if n and (not same_domain or urlparse(n).netloc==seed_host):links.append(n)
        links=list(dict.fromkeys(links))
        return row(url,final,status,ctype," ".join(p.title),p.description," ".join(p.text),links),links
    except (HTTPError,URLError,TimeoutError,Exception) as e:
        return row(url,url,"error","error",text=str(e)),[]

def _handle_request(request):
    if request.method!="POST":
        return {"statusCode":405,"headers":{"Content-Type":"application/json"},"body":json.dumps({"error":"POST only"})}
    if not valid_session(request):
        return {"statusCode":401,"headers":{"Content-Type":"application/json","Cache-Control":"no-store"},"body":json.dumps({"error":"Authentication required"})}
    try:
        body=request.body if isinstance(request.body,dict) else json.loads(request.body or "{}")
        urls=body.get("urls",[])
        if not isinstance(urls,list) or not urls or len(urls)>8:return {"statusCode":400,"headers":{"Content-Type":"application/json"},"body":json.dumps({"error":"Provide 1-8 URLs"})}
        seed_host=body.get("seed_host","")
        same=bool(body.get("same_domain",True))
        max_depth=int(body.get("max_depth",2))
        results=[]; all_links=[]
        for u in urls:
            r,links=crawl_one(u,max_depth,same,seed_host)
            r["depth"]=int(body.get("depths",{}).get(u,0)) if isinstance(body.get("depths",{}),dict) else 0
            results.append(r);all_links.extend(links)
        return {"statusCode":200,"headers":{"Content-Type":"application/json","Cache-Control":"no-store"},"body":json.dumps({"results":results})}
    except Exception as e:
        return {"statusCode":500,"headers":{"Content-Type":"application/json"},"body":json.dumps({"error":str(e)})}

