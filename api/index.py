from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qsl, urlencode, urlparse


class handler(BaseHTTPRequestHandler):
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
            elif self.path == "/api/snake-crawl/background":
                from api.snake_crawl import BackgroundCrawlHandler
                getattr(BackgroundCrawlHandler, method)(self)
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
