from urllib.parse import parse_qsl, urlencode, urlparse

from api.account import AccountHandler
from api.search import SearchHandler
from api.snake_crawl import SnakeCrawlHandler
from api.snake_crawl_files import SnakeCrawlFilesHandler


class handler(SearchHandler):
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
                getattr(AccountHandler, method)(self)
            elif self.path.startswith("/api/snake-crawl-files/"):
                getattr(SnakeCrawlFilesHandler, method)(self)
            elif self.path.startswith("/api/snake-crawl/"):
                getattr(SnakeCrawlHandler, method)(self)
            else:
                getattr(SearchHandler, method)(self)
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
