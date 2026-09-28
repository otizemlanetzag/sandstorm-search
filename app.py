from __future__ import annotations

import io
import mimetypes
import os
from pathlib import Path
from urllib.parse import urlsplit

from api.search import handler as SearchHandler
from api.account import handler as AccountHandler

BASE_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = BASE_DIR / "public"
PORT = int(os.environ.get("PORT", "8080"))


class WSGIRequestAdapter:
    """Small BaseHTTPRequestHandler-compatible adapter for the existing APIs."""

    def __init__(self, environ, start_response):
        self.environ = environ
        self._start_response = start_response
        self.command = environ.get("REQUEST_METHOD", "GET").upper()
        self.path = environ.get("RAW_URI") or environ.get("PATH_INFO", "/")
        if environ.get("QUERY_STRING") and "?" not in self.path:
            self.path += "?" + environ["QUERY_STRING"]
        self.client_address = (environ.get("REMOTE_ADDR", "unknown"), 0)
        self.headers = {
            k[5:].replace("_", "-"): v
            for k, v in environ.items()
            if k.startswith("HTTP_")
        }
        if environ.get("CONTENT_LENGTH"):
            self.headers["Content-Length"] = environ["CONTENT_LENGTH"]
        if environ.get("CONTENT_TYPE"):
            self.headers["Content-Type"] = environ["CONTENT_TYPE"]
        length = int(environ.get("CONTENT_LENGTH") or 0)
        self.rfile = environ["wsgi.input"]
        self.wfile = io.BytesIO()
        self._status = "200 OK"
        self._headers = []

    def send_response(self, status, message=None):
        reason = message or {
            200: "OK", 201: "Created", 204: "No Content",
            400: "Bad Request", 401: "Unauthorized", 403: "Forbidden",
            404: "Not Found", 409: "Conflict", 413: "Payload Too Large",
            414: "URI Too Long", 429: "Too Many Requests",
            500: "Internal Server Error", 502: "Bad Gateway",
            503: "Service Unavailable",
        }.get(status, "OK")
        self._status = f"{status} {reason}"

    def send_header(self, key, value):
        self._headers.append((key, str(value)))

    def end_headers(self):
        pass

    def finish(self):
        body = self.wfile.getvalue()
        self._start_response(self._status, self._headers)
        return [body]


def _dispatch_api(environ, start_response):
    path = urlsplit(environ.get("RAW_URI") or environ.get("PATH_INFO", "/")).path
    cls = AccountHandler if path.startswith("/api/account/") else SearchHandler
    adapter = WSGIRequestAdapter(environ, start_response)
    try:
        if adapter.command == "GET":
            cls.do_GET(adapter)
        elif adapter.command == "POST":
            cls.do_POST(adapter)
        elif adapter.command == "PUT":
            cls.do_PUT(adapter)
        elif adapter.command == "DELETE" and hasattr(cls, "do_DELETE"):
            cls.do_DELETE(adapter)
        else:
            adapter.send_response(405)
            adapter.send_header("Content-Type", "application/json; charset=utf-8")
            adapter.wfile.write(b'{"error":"Method not allowed"}')
    except Exception:
        adapter.send_response(500)
        adapter.send_header("Content-Type", "application/json; charset=utf-8")
        adapter.wfile.write(b'{"error":"Internal server error."}')
    return adapter.finish()


def app(environ, start_response):
    path = urlsplit(environ.get("RAW_URI") or environ.get("PATH_INFO", "/")).path

    if path.startswith("/api/"):
        return _dispatch_api(environ, start_response)

    if path == "/" or path == "":
        path = "/index.html"

    relative = Path(path.lstrip("/"))
    if ".." in relative.parts:
        start_response("404 Not Found", [("Content-Type", "text/plain; charset=utf-8")])
        return [b"Not found"]

    target = (PUBLIC_DIR / relative).resolve()
    try:
        target.relative_to(PUBLIC_DIR.resolve())
    except ValueError:
        start_response("404 Not Found", [("Content-Type", "text/plain; charset=utf-8")])
        return [b"Not found"]

    if not target.is_file():
        start_response("404 Not Found", [("Content-Type", "text/plain; charset=utf-8")])
        return [b"Not found"]

    content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
    if target.suffix.lower() == ".html":
        content_type = "text/html; charset=utf-8"

    data = target.read_bytes()
    start_response("200 OK", [
        ("Content-Type", content_type),
        ("Content-Length", str(len(data))),
        ("X-Content-Type-Options", "nosniff"),
        ("Cache-Control", "no-cache" if target.name == "index.html" else "public, max-age=3600"),
    ])
    return [data]


if __name__ == "__main__":
    from wsgiref.simple_server import make_server
    with make_server("0.0.0.0", PORT, app) as server:
        print(f"Sandstorm Search listening on 0.0.0.0:{PORT}")
        server.serve_forever()
