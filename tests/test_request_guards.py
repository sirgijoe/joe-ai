"""Requests with a missing, wrong or huge Content-Length (or a strange key) get a plain answer,
never a dropped connection or a read that waits for ever."""
from __future__ import annotations

import http.client
import io
import json
import threading

import pytest

from joeai import phone, server

from test_core import env  # noqa: F401


@pytest.fixture
def joe(env):  # noqa: F811
    s, _, _ = env
    s.mcp_key = "right-key"
    app = server.App(s)
    httpd = server.serve(app)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield app, httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


def _raw(port: int, method: str, path: str, headers: dict, body: bytes = b""):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        c.putrequest(method, path, skip_accept_encoding=True)
        for k, v in headers.items():
            c.putheader(k, v)
        c.endheaders(body or None)
        r = c.getresponse()
        return r.status, r.getheader("Content-Type", ""), r.read()
    finally:
        c.close()


def _handler(H, headers: dict, body: bytes = b""):
    h = H.__new__(H)                          # no socket: just the methods that read the request
    h.headers = headers
    h.rfile = io.BytesIO(body)
    return h


@pytest.mark.parametrize("value, want", [
    (None, None), ("", None), ("abc", None), ("-5", None), ("101", None), ("1e3", None),
    ("0", 0), ("42", 42), ("100", 100), (" 7 ", 7),
])
def test_length_is_a_whole_number_within_the_limit(env, value, want):  # noqa: F811
    s, _, _ = env
    H = server.make_handler(server.App(s))
    h = _handler(H, {} if value is None else {"Content-Length": value})
    assert h._length(100) == want


def test_mcp_key_with_a_non_ascii_character_is_refused(joe):
    _, port = joe
    st, ctype, raw = _raw(port, "POST", "/mcp", {"Host": "127.0.0.1", "Authorization": "Bearer é",
                                                 "Content-Length": "2"}, b"{}")
    assert st == 401 and ctype.startswith("application/json") and "error" in json.loads(raw)


def test_mcp_with_a_length_that_is_not_a_number_is_400(joe):
    _, port = joe
    st, ctype, raw = _raw(port, "POST", "/mcp", {"Host": "127.0.0.1", "Authorization": "Bearer right-key",
                                                 "Content-Length": "abc"})
    assert st == 400 and ctype.startswith("application/json") and json.loads(raw)["error"]


@pytest.mark.parametrize("path", ["/api/addons/upload", "/api/voice/myvoice", "/api/voice/memory",
                                  "/api/restore", "/api/tools/upload?tool=x", "/api/talk/attach",
                                  "/api/voice/listen", "/api/tools/mission"])
@pytest.mark.parametrize("length", ["abc", "-1", "999999999999"])
def test_raw_body_routes_answer_ok_false(joe, path, length):
    app, port = joe
    st, ctype, raw = _raw(port, "POST", path, {"Host": "127.0.0.1", "X-NR-Token": app.token,
                                               "Content-Length": length})
    assert st == 200 and ctype.startswith("application/json")
    assert json.loads(raw)["ok"] is False


def test_addon_upload_with_no_length(joe):
    app, port = joe
    st, _, raw = _raw(port, "POST", "/api/addons/upload", {"Host": "127.0.0.1", "X-NR-Token": app.token})
    assert st == 200 and json.loads(raw)["ok"] is False


def test_phone_body_with_a_bad_length_is_empty(env):  # noqa: F811
    s, _, _ = env
    H = phone.make_handler(server.App(s).phone)
    for bad in ("abc", "-3", "300000", ""):
        assert _handler(H, {"Content-Length": bad}, b'{"a": 1}')._body() == {}
    assert _handler(H, {"Content-Length": "8"}, b'{"a": 1}')._body() == {"a": 1}


@pytest.mark.parametrize("path", ["/agent", "/app.js", "/sounds/intro.wav"])
def test_a_missing_ui_file_is_404(joe, tmp_path, monkeypatch, path):
    _, port = joe
    monkeypatch.setattr(server, "UI_DIR", tmp_path / "no-ui")
    st, _, _ = _raw(port, "GET", path, {"Host": "127.0.0.1"})
    assert st == 404
