"""A stand-in for the internet in the online-lookups tests (websearch.py, pagereader.py).

One local web server; each test says what each path answers. Nothing here reaches the real internet.
    with FakeWeb() as web:
        web.route("/api/web_search", {"results": [...]})            # JSON
        web.route("/page", "<html>...</html>", ctype="text/html")
        web.route("/busy", {"error": "slow down"}, status=429)
        web.route("/go", "", status=302, headers={"Location": "http://127.0.0.1:1/x"})
        web.url("/page")  ->  http://127.0.0.1:<port>/page
    web.hits: every request as (method, path with query, body text, headers dict)
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeWeb:
    def __init__(self):
        self.routes: dict[str, tuple] = {}
        self.hits: list[tuple[str, str, str, dict]] = []
        web = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _answer(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n).decode("utf-8", "replace") if n else ""
                web.hits.append((self.command, self.path, body, dict(self.headers)))
                path = self.path.split("?")[0]
                r = web.routes.get(self.path) or web.routes.get(path)
                if r is None:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                status, ctype, data, headers, delay = r
                if callable(data):
                    data = data(self.path, body)
                if delay:
                    time.sleep(delay)
                if isinstance(data, (dict, list)):
                    data = json.dumps(data)
                raw = data.encode("utf-8") if isinstance(data, str) else data
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                try:
                    self.wfile.write(raw)
                except OSError:
                    pass

            do_GET = do_POST = _answer

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]

    def route(self, path, data, status=200, ctype=None, headers=None, delay=0.0):
        if ctype is None:
            ctype = "application/json" if isinstance(data, (dict, list)) else "text/html; charset=utf-8"
        self.routes[path] = (status, ctype, data, headers, delay)

    def url(self, path="/"):
        return f"http://127.0.0.1:{self.port}{path}"

    def __enter__(self):
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *a):
        self.httpd.shutdown()
        self.httpd.server_close()
