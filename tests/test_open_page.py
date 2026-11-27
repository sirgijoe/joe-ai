"""system.open_page: outside web pages open in a Joe window (his own profile), never the everyday browser.
The owner's rule (2026-11-27): "Joe must only ever use his own window." """
from __future__ import annotations

import pytest

from joeai import system


@pytest.fixture
def seen(monkeypatch):
    """Nothing real starts: the browser start and the default browser are both caught."""
    monkeypatch.delenv("JOE_NO_WINDOW", raising=False)     # conftest sets it for every test
    out = {"started": [], "default": []}
    monkeypatch.setattr(system, "popen_detached", lambda cmd, cwd=None: out["started"].append(cmd))
    monkeypatch.setattr(system.webbrowser, "open", lambda url, *a, **k: out["default"].append(url))
    return out


def test_opens_in_app_mode_with_joes_profile(seen, monkeypatch, tmp_path):
    monkeypatch.setattr(system, "app_browser", lambda: "/usr/bin/chromium")
    monkeypatch.setattr(system, "config_dir", lambda: tmp_path)
    system.open_page("https://ffmpeg.org/download.html")
    assert seen["default"] == []
    assert len(seen["started"]) == 1
    cmd = seen["started"][0]
    assert cmd[0] == "/usr/bin/chromium"
    assert "--app=https://ffmpeg.org/download.html" in cmd
    assert f"--user-data-dir={tmp_path / 'window'}" in cmd
    assert "--window-size=1100,800" in cmd


def test_same_profile_as_joes_own_window(seen, monkeypatch, tmp_path):
    from joeai import app
    monkeypatch.setattr(system, "app_browser", lambda: "/usr/bin/chromium")
    monkeypatch.setattr(system, "config_dir", lambda: tmp_path)
    monkeypatch.setattr(app, "config_dir", lambda: tmp_path)
    app.open_window("http://127.0.0.1:1/")
    system.open_page("http://example.com/")
    prof = [{a for a in cmd if a.startswith("--user-data-dir=")} for cmd in seen["started"]]
    assert len(prof) == 2 and prof[0] == prof[1]


def test_no_app_browser_falls_back_to_default(seen, monkeypatch):
    monkeypatch.setattr(system, "app_browser", lambda: None)
    system.open_page("http://example.com/x")
    assert seen["default"] == ["http://example.com/x"] and seen["started"] == []


@pytest.mark.parametrize("bad", ["file:///c:/x", "--remote-debugging-port=9222", "javascript:alert(1)", "",
                                 "https://", "https://x.com/\n--flag", " https://x.com/", None, "ftp://x.com/"])
@pytest.mark.parametrize("browser", ["/usr/bin/chromium", None])
def test_only_web_addresses(seen, monkeypatch, bad, browser):
    monkeypatch.setattr(system, "app_browser", lambda: browser)
    system.open_page(bad)
    assert seen["started"] == [] and seen["default"] == []


def test_no_window_setting_opens_nothing(seen, monkeypatch):
    monkeypatch.setenv("JOE_NO_WINDOW", "1")
    monkeypatch.setattr(system, "app_browser", lambda: "/usr/bin/chromium")
    system.open_page("https://example.com/")
    monkeypatch.setattr(system, "app_browser", lambda: None)
    system.open_page("https://example.com/")
    assert seen["started"] == [] and seen["default"] == []


# --------------------------------------------------------------------------- every caller goes through it
@pytest.fixture
def pages(monkeypatch):
    got = []
    monkeypatch.setattr(system, "open_page", got.append)
    monkeypatch.setattr(system.webbrowser, "open", lambda *a, **k: pytest.fail("everyday browser opened"))
    return got


def test_doctor_download_page(pages, monkeypatch):
    from joeai import doctor
    monkeypatch.setattr(system, "install_plan", lambda tool: {"kind": "page"})
    logs = []
    assert doctor.run_install("ffmpeg", "FFmpeg", "https://ffmpeg.org/download.html", logs.append) is False
    assert pages == ["https://ffmpeg.org/download.html"]
    assert any("in a Joe window" in ln for ln in logs)


def test_upkeep_mac_dmg(pages, monkeypatch):
    from joeai import upkeep
    rel = {"tag_name": "v1", "assets": [{"name": "Ollama.dmg", "browser_download_url": "https://github.com/o/r/Ollama.dmg"}]}
    assert upkeep.install_ollama_mac(lambda s: None, fetch=lambda *a, **k: rel) is False
    assert pages == ["https://github.com/o/r/Ollama.dmg"]


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "settings.json"))
    from joeai.config import Settings
    from joeai.server import App
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    return App(s)


def test_get_engine_page(pages, monkeypatch, tmp_path):
    app = _app(tmp_path, monkeypatch)
    app.settings.ollama.engine = "lmstudio"
    logs = []
    monkeypatch.setattr(app, "log", logs.append)
    r = app.doctor_fix({"action": "get-engine", "approved": True})
    assert r["ok"] and len(pages) == 1 and pages[0].startswith("https://lmstudio.ai")
    assert any("in a Joe window" in ln for ln in logs)


def test_model_page_and_download(pages, monkeypatch, tmp_path):
    from joeai import doctor, stylemodels
    app = _app(tmp_path, monkeypatch)
    monkeypatch.setattr(doctor, "comfy_models_dir", lambda s: tmp_path / "models")
    monkeypatch.setattr(stylemodels, "found", lambda mdir, *a: [])
    page = "https://huggingface.co/someone/model"
    link = page + "/resolve/main/model.safetensors"
    monkeypatch.setattr(stylemodels, "download_link", lambda p, timeout=15, file="": link)
    started = []
    monkeypatch.setattr(doctor, "run_in_thread", started.append)
    r = app.doctor_fix({"action": "import-models", "approved": True, "page": page})
    assert r.get("ok") and len(started) == 1
    started[0]()
    assert pages == [page, link]
