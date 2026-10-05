import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

DATA_PATH = Path(__file__).resolve().parent.parent / "embedded" / "snake-crawl" / "DATA.CSV"
WINDOW = 300
_last = {}


class SnakeCrawlFilesHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/")
        if path != "/api/snake-crawl-files/download":
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Not found")
            return

        key = self.client_address[0] if self.client_address else "unknown"
        now = time.time()

        if now - _last.get(key, 0) < WINDOW:
            self.send_response(429)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Download limited to once every 5 minutes.")
            return

        try:
            data = DATA_PATH.read_bytes()
        except OSError as exc:
            self.send_response(500)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(("DATA.CSV unavailable: " + str(exc)).encode("utf-8", "replace"))
            return

        _last[key] = now
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", 'attachment; filename="DATA.CSV"')
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        self.do_GET()

    def log_message(self, format, *args):
        return
