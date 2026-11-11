"""Joe Phone: pairing, refusals, what a paired phone can and can't do."""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request

import pytest

from joeai import phone, qr

from test_tools import app  # noqa: F401


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def ph(app, monkeypatch):  # noqa: F811
    monkeypatch.setattr(phone, "lan_ip", lambda: "127.0.0.1")
    app.settings.phone.enabled = True
    app.settings.phone.port = _free_port()
    app.phone.apply()
    assert app.phone.httpd, app.phone.error
    yield app
    app.phone.stop()


def _call(app, path, body=None, key=""):
    url = app.phone.address.rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"X-Joe-Phone": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if r.headers.get("Content-Type", "").startswith("application/json") else raw)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw


def _pair(app) -> str:
    code = app.phone.new_pairing()["code"]
    st, r = _call(app, "/api/pair", {"code": code, "name": "Test phone"})
    assert st == 200 and r["ok"], r
    return r["token"]


def test_home_addresses_only():
    assert phone.is_home("192.168.1.20") and phone.is_home("10.0.0.5") and phone.is_home("127.0.0.1")
    assert phone.is_home("fe80::1") and not phone.is_home("8.8.8.8") and not phone.is_home("nonsense")


def test_pairing_once_and_unpaired_refused(ph):
    st, page = _call(ph, "/")
    assert st == 200 and b"Pair this phone" in page
    st, r = _call(ph, "/api/status")
    assert st == 401 and r["unpaired"]
    p = ph.phone.new_pairing()
    assert p["ok"] and p["url"].startswith(ph.phone.address) and p["qr"].startswith("<svg")
    st, r = _call(ph, "/api/pair", {"code": "wrong", "name": "x"})
    assert not r["ok"]
    st, r = _call(ph, "/api/pair", {"code": p["code"], "name": "Kitchen phone"})
    assert r["ok"] and len(r["token"]) > 30
    st, again = _call(ph, "/api/pair", {"code": p["code"], "name": "Second"})   # one phone per code
    assert not again["ok"]
    st, s = _call(ph, "/api/status", key=r["token"])
    assert st == 200 and s["ok"] and s["running"] is False
    saved = json.loads(phone._store_path().read_text())
    assert r["token"] not in json.dumps(saved)                 # only a fingerprint is kept
    info = ph.phone.info()
    assert info["on"] and info["devices"][0]["name"] == "Kitchen phone"
    assert phone.remove_device(info["devices"][0]["id"])
    st, s = _call(ph, "/api/status", key=r["token"])
    assert st == 401


def test_too_many_wrong_codes_pause_pairing(ph):
    for _ in range(phone.MAX_BAD_PAIRS):
        ph.phone.pair("nope", "x")
    code = ph.phone.new_pairing()["code"]
    assert "Too many" in ph.phone.pair(code, "x")["error"]


def test_lists_reminders_quick_answers(ph):
    key = _pair(ph)
    _, r = _call(ph, "/api/list", {"name": "shopping", "add": "milk and eggs"}, key)
    assert r["ok"]
    _, r = _call(ph, "/api/lists", key=key)
    shop = next(x for x in r["lists"] if x["name"] == "shopping")
    assert shop["items"] == ["milk", "eggs"]
    _, r = _call(ph, "/api/list", {"name": "shopping", "done": "milk"}, key)
    assert r["ok"]
    _, r = _call(ph, "/api/ask", {"text": "what is 15% of 80"}, key)
    assert r["say"].endswith("= 12")
    _, r = _call(ph, "/api/ask", {"text": "add bread to my shopping list"}, key)
    assert r["ok"] and "bread" in r["say"]
    _, r = _call(ph, "/api/remind", {"text": "remind me in 2 hours to feed the horses"}, key)
    assert "say" in r or "error" in r
    _, r = _call(ph, "/api/reminders", key=key)
    assert r["ok"] and any("feed the horses" in x["what"] for x in r["reminders"])


def test_results_and_file_safety(ph):
    key = _pair(ph)
    out = ph.sb.output / "pics"
    out.mkdir(parents=True)
    (out / "cat.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 20)
    (out / "notes.md").write_text("# hi", encoding="utf-8")
    (ph.sb.inbox / "secret.txt").write_text("private", encoding="utf-8")
    _, r = _call(ph, "/api/results", key=key)
    paths = [f["path"] for f in r["files"]]
    assert "pics/cat.png" in paths and "pics/notes.md" in paths
    st, raw = _call(ph, "/api/file?p=pics/cat.png", key=key)
    assert st == 200 and raw.startswith(b"\x89PNG")
    for bad in ("../Inbox/secret.txt", "Inbox/secret.txt", "/etc/passwd", "C:/Windows/win.ini"):
        st, r = _call(ph, "/api/file?p=" + bad, key=key)
        assert st == 404, bad


def test_plan_needs_run_it(ph, monkeypatch):
    key = _pair(ph)
    started = []
    monkeypatch.setattr(ph, "plan_now", lambda text: {"ok": True, "time": "about 2 min", "summary": "3 captions",
                                                       "mission": "=== JOE MISSION ===\nTASK: Caps\nCHUNKS: 1 x 3\n=== END ==="})
    monkeypatch.setattr(ph, "run", lambda text: started.append(text) or {"ok": True, "queued": 0})
    _, r = _call(ph, "/api/ask", {"text": "write 3 captions for my candle shop"}, key)
    assert r["ok"] and r["mission"].startswith("=== JOE MISSION") and not started     # nothing runs yet
    _, bad = _call(ph, "/api/run", {"mission": r["mission"], "plan": "not-a-plan"}, key)
    assert not bad["ok"] and not started                       # mission text from a phone is never run
    _, r = _call(ph, "/api/run", {"plan": r["plan"]}, key)
    assert r["ok"] and started and "Started" in r["say"]
    _, r = _call(ph, "/api/stop", {}, key)
    assert r["say"] == "Nothing is running."


def test_qr_codes_are_well_formed():
    g = qr.matrix("http://192.168.1.25:8770/#pair=abcdefghijkl")
    n = len(g)
    assert n in (29, 33) and all(len(row) == n for row in g)
    for r0, c0 in ((0, 0), (0, n - 7), (n - 7, 0)):            # the three corner squares
        assert all(g[r0][c0 + i] for i in range(7)) and all(g[r0 + 6][c0 + i] for i in range(7))
        assert not g[r0 + 1][c0 + 1] and g[r0 + 3][c0 + 3]
    with pytest.raises(ValueError):
        qr.matrix("x" * 400)
