"""Security review of 2026-11-24 (Opus): what it found, one test each."""
import http.server
import threading

from joeai import http as jh


def _serve(handler):
    s = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


def test_a_key_never_follows_a_redirect_to_another_site():
    """Python's own redirect handler sent every header on to wherever a redirect pointed, so a search source
    (LangSearch, your own search source, Ollama web search) or a writing service could hand Joe's key to
    another site, or down to plain http, just by answering with a redirect."""
    seen = []

    class Other(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append((self.path, self.headers.get("Authorization"), self.headers.get("X-Api-Key"),
                         self.headers.get("User-Agent")))
            if self.path == "/hop":                     # a redirect that stays on the same site
                self.send_response(302)
                self.send_header("Location", "/final")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *a):
            pass

    other = _serve(Other)

    class Source(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{other.server_port}/elsewhere")
            self.end_headers()

        def log_message(self, *a):
            pass

    source = _serve(Source)
    try:
        jh.install()
        keys = {"Authorization": "Bearer SECRET", "X-Api-Key": "K2", "User-Agent": "Joe"}
        jh.request_json("GET", f"http://127.0.0.1:{source.server_port}/search", headers=keys)
        jh.request_json("GET", f"http://127.0.0.1:{other.server_port}/hop", headers=keys)
    finally:
        source.shutdown()
        other.shutdown()
    assert seen[0] == ("/elsewhere", None, None, "Joe")             # another site (another port): no keys
    assert seen[1] == ("/hop", "Bearer SECRET", "K2", "Joe")
    assert seen[2] == ("/final", "Bearer SECRET", "K2", "Joe")      # the same site: kept



def test_update_uses_the_computers_own_tools_when_the_connection_is_cut(tmp_path, monkeypatch):
    """The UPDATE button had never worked on Joseph's PC: Python's secure connection failed, and the backup
    only ran on the exact words "certificate verify failed". Now a cut-off connection counts too (antivirus
    and firewalls that check web traffic do this), and on Windows PowerShell is tried when curl fails."""
    from joeai import update
    from joeai.http import HttpError
    monkeypatch.setattr(update, "updates_dir", lambda: tmp_path)
    for err in (HttpError("can't reach https://api.github.com: connection reset", "dropped"),
                HttpError("can't reach https://api.github.com: [SSL: UNEXPECTED_EOF_WHILE_READING]", ""),
                ConnectionResetError(10054, "An existing connection was forcibly closed by the remote host")):
        assert update._needs_backup(err), err
    assert not update._needs_backup(OSError("network is down"))
    assert not update._needs_backup(HttpError("HTTP 404 Not Found", ""))

    def dropped(*a, **k):
        raise HttpError("can't reach https://api.github.com: connection reset", "dropped")
    tried = []

    def no_curl(url, dest=None, timeout=60, headers=None):
        tried.append("curl")
        raise OSError("curl: (35) schannel: failed to receive handshake")

    def ps(url, dest, timeout, headers):
        tried.append("powershell")
        dest.write_bytes(b'{"tag_name": "v9.9.9", "assets": []}')
    monkeypatch.setattr(update, "_curl", no_curl)
    monkeypatch.setattr(update, "_powershell", ps)
    monkeypatch.setattr(update.os, "name", "nt")
    update._CACHE.clear()
    try:
        r = update.check(force=True, fetch=dropped)
    finally:
        update._CACHE.clear()
    assert r["ok"] and r["latest"] == "9.9.9" and tried == ["curl", "powershell"]
    assert not list(tmp_path.glob("_fetch_*"))                      # the scratch file is gone
