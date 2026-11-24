"""Joe notices when his own files were changed while he runs (a copied-over folder, an edit in a
source copy), and never for an installed Joe."""
from __future__ import annotations

import json
import os

import pytest

from joeai import app as app_mod
from joeai import server

from test_core import env  # noqa: F401

SENTENCE = "Joe's files changed since this window opened. Restart Joe to use them."


@pytest.fixture
def joe_dir(tmp_path, monkeypatch):
    d = tmp_path / "joeai"
    (d / "ui").mkdir(parents=True)
    (d / "server.py").write_text("x = 1\n", encoding="utf-8")
    (d / "ui" / "app.js").write_text("let a = 1;\n", encoding="utf-8")
    (d / "ui" / "notes.txt").write_text("not part of the stamp\n", encoding="utf-8")
    monkeypatch.setattr(app_mod, "JOE_DIR", d)
    return d


def _touch(p, bump_ns=5_000_000_000):
    st = p.stat()
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + bump_ns))


def test_stamp_changes_with_a_files_modification_time(joe_dir):
    a = app_mod.build_stamp()
    assert len(a) == 12 and all(c in "0123456789abcdef" for c in a)
    assert app_mod.build_stamp() == a                         # nothing changed: same stamp
    _touch(joe_dir / "server.py")
    b = app_mod.build_stamp()
    assert b != a
    _touch(joe_dir / "ui" / "app.js")
    assert app_mod.build_stamp() != b
    c = app_mod.build_stamp()
    _touch(joe_dir / "ui" / "notes.txt")                      # not a .py/.js/.html/.css file
    assert app_mod.build_stamp() == c


def test_no_stamp_for_an_installed_joe(joe_dir):
    (joe_dir / "_install.json").write_text('{"kind": "windows-installer"}', encoding="utf-8")
    assert app_mod.build_stamp() == ""
    assert app_mod.build_stamp(joe_dir) == ""


def test_restart_advice_after_files_change(env, joe_dir):  # noqa: F811
    s, _, _ = env
    a = server.App(s)
    assert a.stamp == app_mod.build_stamp()
    a._disk_checked = 0
    assert a.restart_advice() == ""
    _touch(joe_dir / "server.py")
    assert a.restart_advice() == ""                            # looked again only after 30 s
    a._disk_checked = 0
    assert a.restart_advice() == SENTENCE


def test_installed_joe_never_says_files_changed(env, joe_dir):  # noqa: F811
    s, _, _ = env
    (joe_dir / "_install.json").write_text("{}", encoding="utf-8")
    a = server.App(s)
    assert a.stamp == ""
    _touch(joe_dir / "server.py")
    a._disk_checked = 0
    assert a.restart_advice() == ""


def test_ping_carries_the_stamp(env, joe_dir):  # noqa: F811
    import threading
    import urllib.request
    s, _, _ = env
    a = server.App(s)
    httpd = server.serve(a)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{httpd.server_address[1]}/api/ping",
                                     headers={"X-NR-Token": a.token})
        with urllib.request.urlopen(req, timeout=5) as r:
            assert json.loads(r.read())["stamp"] == a.stamp != ""
    finally:
        httpd.shutdown()
        httpd.server_close()


class _Resp:
    def __init__(self, body: bytes):
        self.body = body

    def read(self):
        return self.body

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def lock(tmp_path, monkeypatch, joe_dir):
    monkeypatch.setattr(app_mod, "config_dir", lambda: tmp_path / "cfg")
    monkeypatch.delenv("JOE_CONFIG", raising=False)
    (tmp_path / "cfg").mkdir()
    app_mod._lock_path().write_text(json.dumps({"port": 9, "token": "tok", "pid": 1}), encoding="utf-8")
    monkeypatch.setattr("time.sleep", lambda s: None)
    calls = []

    def ping_says(**info):
        def fake(req, timeout=0):
            calls.append(req.full_url)
            return _Resp(json.dumps(info).encode() if req.full_url.endswith("/api/ping") else b"{}")
        monkeypatch.setattr(app_mod.urllib.request, "urlopen", fake)
    return ping_says, calls


@pytest.mark.parametrize("theirs, running, reused", [
    ("same", False, True),          # same version, same files: reopen it
    ("", False, True),              # the old Joe has no stamp (installed, or older): reopen it
    ("other", False, False),        # files changed since that Joe started: ask it to quit
    ("other", True, True),          # ... unless it's mid-run
])
def test_existing_url_checks_the_stamp(lock, theirs, running, reused):
    ping_says, calls = lock
    mine = app_mod.build_stamp()
    stamp = mine if theirs == "same" else ("0" * 12 if theirs == "other" else "")
    ping_says(ok=True, version=server.__version__,
              running=running, stamp=stamp)
    url = app_mod._existing_url()
    if reused:
        assert url and url.endswith("#t=tok") and not any(c.endswith("/api/quit") for c in calls)
    else:
        assert url is None and calls[-1].endswith("/api/quit")


def test_existing_url_reuses_when_this_copy_has_no_stamp(lock, joe_dir):
    ping_says, _ = lock
    (joe_dir / "_install.json").write_text("{}", encoding="utf-8")
    ping_says(ok=True, version=server.__version__, running=False, stamp="0" * 12)
    assert app_mod._existing_url()
