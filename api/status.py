from http.server import BaseHTTPRequestHandler
from pathlib import Path
import csv
import json

DATA_PATH = Path(__file__).resolve().parent.parent / "embedded" / "snake-crawl" / "DATA.CSV"

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            with DATA_PATH.open("r", encoding="utf-8-sig", newline="") as f:
                total = sum(1 for _ in csv.DictReader(f))
            payload = {"ok": True, "total_crawled": total}
            status = 200
        except Exception as exc:
            payload = {"ok": False, "total_crawled": 0, "error": "DATA.CSV unavailable"}
            status = 500

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()

    def log_message(self, format, *args):
        return
