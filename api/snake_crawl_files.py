import time
import urllib.request
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse

RAW="https://raw.githubusercontent.com/otizemlanetzag/snake-crawl/main/DATA.CSV"
WINDOW=300
_last={}

class SnakeCrawlFilesHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if urlparse(self.path).path.rstrip("/")!="/api/snake-crawl-files/download":
            self.send_error(404); return
        key=self.client_address[0]
        now=time.time()
        if now-_last.get(key,0)<WINDOW:
            self.send_response(429)
            self.send_header("Content-Type","text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Download limited to once every 5 minutes.")
            return
        try:
            req=urllib.request.Request(RAW,headers={"User-Agent":"Sandstorm-Snake-Crawl-Files/1.0"})
            with urllib.request.urlopen(req,timeout=30) as r: data=r.read()
            _last[key]=now
            self.send_response(200)
            self.send_header("Content-Type","text/csv; charset=utf-8")
            self.send_header("Content-Disposition",'attachment; filename="DATA.CSV"')
            self.send_header("Cache-Control","no-store")
            self.send_header("Content-Length",str(len(data)))
            self.end_headers(); self.wfile.write(data)
        except Exception:
            self.send_error(502,"Unable to fetch DATA.CSV")
    def log_message(self,*args): return
