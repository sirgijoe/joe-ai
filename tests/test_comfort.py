"""Quiet hours and the phone ping when a run is done."""
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from joeai import notify
from joeai.config import Settings
from joeai.server import App

from fake_ollama import FakeOllama


class FakeNtfy:
    def __init__(self):
        self.got = []
        me = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                me.got.append((self.path, self.headers.get("Title"), self.rfile.read(n).decode()))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"{}")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


def test_quiet_hours():
    at = lambda h, m=0: datetime(2026, 1, 1, h, m)
    assert notify.in_quiet_hours("22:00", "07:00", at(23))
    assert notify.in_quiet_hours("22:00", "07:00", at(3))
    assert not notify.in_quiet_hours("22:00", "07:00", at(7))
    assert not notify.in_quiet_hours("22:00", "07:00", at(12))
    assert notify.in_quiet_hours("13", "14:30", at(14, 10))
    assert not notify.in_quiet_hours("", "07:00", at(3))
    assert not notify.in_quiet_hours("25:00", "07:00", at(3))


def test_topic_rules():
    assert notify.valid_topic("joe-pings-8f2k")
    assert not notify.valid_topic("abc")
    assert not notify.valid_topic("has space here")
    assert "6-64" in notify.send_ntfy("https://ntfy.sh", "x", "hi")


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "settings.json"))
    fake = FakeOllama()
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    s.ollama.url = fake.url
    s.comfy.url = "http://127.0.0.1:9"
    s.engine.retry_backoff_s = 0
    s.engine.gpu_temp_pause_c = 0
    s.engine.keep_awake = False
    a = App(settings=s)
    yield a
    if a.thread:
        a.thread.join(30)
    fake.close()


def _run(app):
    assert app.enqueue("TASK: Tips  CHUNKS: 1 x 3")["ok"]
    for _ in range(300):
        if not app.running:
            return
        time.sleep(0.1)
    raise AssertionError("run never finished")


def test_ping_when_done(app):
    n = FakeNtfy()
    app.settings.comfort.ntfy_server = n.url
    app.settings.comfort.ntfy_topic = "joe-test-topic"
    _run(app)
    assert app.finished["n"] == 1
    assert len(n.got) == 1
    path, title, body = n.got[0]
    assert path == "/joe-test-topic" and title == "Joe"
    assert body.startswith("Joe is done: 1 of 1 task done")


def test_ping_waits_for_quiet_hours(app, monkeypatch):
    n = FakeNtfy()
    app.settings.comfort.ntfy_server = n.url
    app.settings.comfort.ntfy_topic = "joe-test-topic"
    quiet = [True]
    monkeypatch.setattr(App, "quiet", lambda self: quiet[0])
    _run(app)
    assert n.got == [] and app.pending_ping.startswith("Joe is done")
    app.ping_tick()
    assert n.got == []
    quiet[0] = False
    app.ping_tick()
    assert len(n.got) == 1 and app.pending_ping == ""


def test_no_ping_without_topic(app):
    _run(app)
    assert app.finished["n"] == 1 and app.pending_ping == ""
