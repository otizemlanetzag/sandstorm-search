from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qsl, urlencode, urlparse

from api.account import handler as AccountHandler
from api.search import handler as SearchHandler


def _routed_path(path):
    parsed = urlparse(path)
    params = parse_qsl(parsed.query, keep_blank_values=True)
    route = next((v for k, v in params if k == "route"), "")
    if not route:
        return parsed.path, parsed.query

    remaining = [(k, v) for k, v in params if k != "route"]
    clean_path = "/" + route.lstrip("/")
    query = urlencode(remaining)
    return "/api/" + clean_path.lstrip("/"), query


class handler(BaseHTTPRequestHandler):
    def _dispatch(self, method):
        original_path = self.path
        path, query = _routed_path(original_path)
        self.path = path + (("?" + query) if query else "")

        if self.path.startswith("/api/account/"):
            target = AccountHandler
        else:
            target = SearchHandler

        try:
            getattr(target, method)(self)
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
