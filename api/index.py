from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qsl, urlencode, urlparse
import json
import csv
import random
import time
from pathlib import Path

_BACKGROUND_LAST = {}


class handler(BaseHTTPRequestHandler):
    def _send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _guard(self):
        from api.search import _rate_limited, _client_ip, MAX_REQUEST_TARGET
        if len(self.path) > MAX_REQUEST_TARGET:
            self._send_json({"error": "Request is too large."}, 414)
            return False
        if _rate_limited(_client_ip(self)):
            self._send_json({"error": "Too many requests. Please try again shortly."}, 429)
            return False
        return True

    def _route(self):
        parsed = urlparse(self.path)
        params = parse_qsl(parsed.query, keep_blank_values=True)
        route = next((value for key, value in params if key == "route"), "")
        remaining = [(key, value) for key, value in params if key != "route"]
        path = "/api/" + route.lstrip("/") if route else parsed.path
        query = urlencode(remaining)
        return path, query

    def _dispatch(self, method):
        original_path = self.path
        path, query = self._route()
        self.path = path + (("?" + query) if query else "")
        try:
            if self.path.startswith("/api/account/"):
                from api.account import AccountHandler
                getattr(AccountHandler, method)(self)
            elif self.path == "/api/snake-crawl/background" and method == "do_GET":
                from api.snake_crawl import _safe_public_url, _crawl_one
                client = self.client_address[0] if self.client_address else "unknown"
                now = time.time()
                if now - _BACKGROUND_LAST.get(client, 0) < 30:
                    body = b'{"error":"Background crawl is rate limited"}'
                    self.send_response(429)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers(); self.wfile.write(body)
                else:
                    _BACKGROUND_LAST[client] = now
                    data_path = Path(__file__).resolve().parent.parent / "embedded" / "snake-crawl" / "DATA.CSV"
                    urls = []
                    with data_path.open("r", encoding="utf-8-sig", newline="") as f:
                        for row in csv.DictReader(f):
                            url = (row.get("url") or row.get("final_url") or "").strip()
                            if url:
                                try:
                                    if _safe_public_url(url): urls.append(url)
                                except Exception: pass
                    if not urls:
                        body = b'{"error":"No crawl targets available"}'
                        self.send_response(503); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
                    else:
                        url = random.choice(urls)
                        row, _ = _crawl_one(url, 0, True, urlparse(url).netloc)
                        import json
                        body = json.dumps({"ok": True, "result": row}, ensure_ascii=False).encode("utf-8")
                        self.send_response(200); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
            elif self.path == "/api/status":
                import csv
                from pathlib import Path
                data_path = Path(__file__).resolve().parent.parent / "embedded" / "snake-crawl" / "DATA.CSV"
                try:
                    with data_path.open("r", encoding="utf-8-sig", newline="") as f:
                        total = max(0, sum(1 for _ in csv.DictReader(f)))
                    body = ('{"total_crawled":' + str(total) + '}').encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except Exception:
                    body = b'{"error":"Status unavailable."}'
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
            elif self.path.startswith("/api/snake-crawl-files/"):
                from api.snake_crawl_files import SnakeCrawlFilesHandler
                getattr(SnakeCrawlFilesHandler, method)(self)
            elif self.path.startswith("/api/snake-crawl/"):
                from api.snake_crawl import SnakeCrawlHandler
                getattr(SnakeCrawlHandler, method)(self)
            else:
                from api.search import SearchHandler
                getattr(SearchHandler, method)(self)
        except Exception as exc:
            if not self.wfile:
                raise
            self.send_response(500)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(("Function error: " + str(exc)).encode("utf-8", "replace"))
        finally:
            self.path = original_path

    def do_GET(self):
        self._dispatch("do_GET")

    def do_POST(self):
        self._dispatch("do_POST")

    def do_PUT(self):
        self._dispatch("do_PUT")

    def log_message(self, format, *args):
        return
