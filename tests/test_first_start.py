"""A brand-new computer: no Ollama, no ComfyUI, no models, no voice add-on, no internet.
Every screen's data must load with plain messages, never a crash."""
import json
import threading
import urllib.error
import urllib.request
import zipfile

import pytest

from joeai import hardware, update
from joeai.config import Settings
from joeai.server import App, serve

GETS = ["/api/ping", "/api/state", "/api/mission", "/api/files?path=", "/api/report",
        "/api/settings", "/api/storage", "/api/stats", "/api/chats", "/api/history", "/api/lists",
        "/api/doctor", "/api/tools", "/api/themes", "/api/voice/status"]


@pytest.fixture
def bare(tmp_path, monkeypatch):
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "cfg" / "settings.json"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))      # no ollama, ffmpeg, pandoc, uv
    monkeypatch.setattr(hardware, "gpu", lambda: None)            # no graphics card
    monkeypatch.setattr(update, "check", lambda force=False: {"ok": False, "current": "x",
                                                              "error": "Couldn't reach GitHub."})
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    s.ollama.url = "http://127.0.0.1:9"                 # nothing listens here
    s.comfy.url = "http://127.0.0.1:9"
    s.ui.check_updates = False
    app = App(s)
    httpd = serve(app)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    def call(path, body=None):
        req = urllib.request.Request(base + path, headers={"X-NR-Token": app.token,
                                                           "Content-Type": "application/json"},
                                     data=None if body is None else json.dumps(body).encode())
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    yield app, call, tmp_path
    httpd.shutdown()


def test_every_screen_loads_on_a_bare_computer(bare):
    app, call, _ = bare
    for path in GETS:
        status, data = call(path)
        assert status == 200, path
        assert isinstance(data, (dict, list)), path


def test_system_check_explains_whats_missing(bare):
    _, call, _ = bare
    _, d = call("/api/doctor")
    ids = {i["id"] for i in d["issues"]}
    assert "install-ollama" in ids and d["gpu"] is None
    assert "processor" in d["gpu_advice"]                       # honest about no graphics card
    assert all(i["text"] for i in d["issues"])


def test_describe_and_talk_without_ollama_say_so(bare):
    _, call, _ = bare
    _, r = call("/api/describe", {"text": "write 10 product blurbs"})
    assert r.get("ok") is False and r.get("error")
    try:
        status, r = call("/api/talk", {"text": "hello"})
        assert status == 200 and (r.get("error") or r.get("reply"))
    except urllib.error.HTTPError as e:
        assert e.code < 500


def test_a_run_without_ollama_fails_gently(bare):
    app, call, _ = bare
    _, r = call("/api/check", {"text": "TASK: Tips\nCHUNKS: 1 x 3\nFORMAT: one tip each"})
    assert r.get("ok"), r


def test_help_file_never_holds_secrets_or_home(bare):
    app, call, tmp = bare
    app.settings.web.ollama_key = "sk-secret-123"
    app.settings.comfort.ntfy_topic = "my-private-topic"
    (app.sb.output / "_log.txt").write_text(f"started from {tmp / 'home'}\nhello\n", encoding="utf-8")
    _, r = call("/api/help-file", {"show": False})
    z = zipfile.ZipFile(app.sb.output / r["path"])
    names = z.namelist()
    assert {"README.txt", "about.txt", "system-check.json", "settings.json"} <= set(names)
    blob = "".join(z.read(n).decode("utf-8", "replace") for n in names)
    assert "sk-secret-123" not in blob and "my-private-topic" not in blob
    assert str(tmp / "home") not in blob
