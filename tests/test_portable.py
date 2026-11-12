"""Portable Joe (batch 5): drive mode, {JOE} paths, relinking, MAKE A PORTABLE JOE, Ollama on the drive."""
import io
import json
import zipfile
from pathlib import Path

import pytest

from joeai import portable, system
from joeai.config import Settings


@pytest.fixture
def drive(tmp_path, monkeypatch):
    root = tmp_path / "E" / "Joe"
    root.mkdir(parents=True)
    monkeypatch.setenv("JOE_PORTABLE", str(root))
    monkeypatch.delenv("JOE_CONFIG", raising=False)
    for k in list(portable.ENV_DIRS) + ["OLLAMA_MODELS", "OLLAMA_HOST", "UV_PYTHON_PREFERENCE"]:
        monkeypatch.delenv(k, raising=False)
    return root


def test_off_by_default(monkeypatch):
    monkeypatch.setenv("JOE_PORTABLE", "0")
    assert not portable.active()
    assert portable.pack({"a": "x"}) == {"a": "x"}


def test_marker_needs_the_word(tmp_path, monkeypatch):
    monkeypatch.delenv("JOE_PORTABLE", raising=False)
    (tmp_path / portable.MARKER).write_text("hello", encoding="utf-8")
    assert not portable._has_marker(tmp_path)
    (tmp_path / portable.MARKER).write_text(portable.MARKER_TEXT, encoding="utf-8")
    assert portable._has_marker(tmp_path)


def test_folders_live_on_the_drive(drive):
    assert system.config_dir() == drive / "JoeData" / "settings"
    assert system.data_dir() == drive / "JoeData" / "data"
    assert system.default_workspace() == drive / "Joe-ai"
    assert system.install_plan("ollama")["kind"] == "joe"
    assert system.install_plan("comfyui")["kind"] == "joe"


def test_paths_saved_as_token_and_loaded_back(drive):
    s = Settings()
    s.workspace = str(drive / "Joe-ai")
    s.comfy.models_dir = str(drive / "JoeData" / "models")
    p = s.save()
    assert p == drive / "JoeData" / "settings" / "settings.json"
    raw = p.read_text(encoding="utf-8")
    assert "{JOE}" in raw and str(drive) not in raw
    s2 = Settings.load()
    assert s2.workspace == str(drive / "Joe-ai")
    assert s2.comfy.models_dir == str(drive / "JoeData" / "models")


def test_drive_ollama_gets_its_own_port(drive):
    s = Settings()
    portable.adjust_settings(s)
    assert s.ollama.url == "http://127.0.0.1:11434"
    exe = portable.ollama_dir() / ("ollama.exe" if portable.WIN else "ollama")
    exe.parent.mkdir(parents=True)
    exe.write_text("x")
    portable.adjust_settings(s)
    assert s.ollama.url == portable.ollama_url()
    portable.apply_env()
    import os
    assert os.environ["OLLAMA_HOST"].endswith(":11435")
    assert os.environ["OLLAMA_MODELS"] == str(portable.ollama_models_dir())
    assert os.environ["UV_PYTHON_PREFERENCE"] == "only-managed"
    from joeai import finder
    assert finder.ollama_exe() == str(exe)
    exe.unlink()
    portable.adjust_settings(s)               # Ollama taken off the drive: back to the PC's
    assert s.ollama.url == "http://127.0.0.1:11434"


def test_relink_when_the_drive_moves(drive):
    venv = drive / "JoeData" / "data" / "addons" / "voice" / ".venv"
    venv.mkdir(parents=True)
    old = "F:\\Old\\Joe" if portable.WIN else "/media/old/Joe"
    (venv / "pyvenv.cfg").write_text(f"home = {old}/JoeData/data/uv-python/cpython\nversion = 3.12\n",
                                     encoding="utf-8")
    (drive / "JoeData" / "last_place.txt").write_text(old, encoding="utf-8")
    assert portable.relink() == 1
    assert str(drive) in (venv / "pyvenv.cfg").read_text(encoding="utf-8")
    assert (drive / "JoeData" / "last_place.txt").read_text(encoding="utf-8") == str(drive)
    assert portable.relink() == 0


def test_night_shift_never_touches_the_pc(drive, monkeypatch):
    from joeai import schedule
    called = []
    monkeypatch.setattr(schedule, "remove", lambda log: called.append(1) or {"ok": True})
    s = Settings()
    assert schedule.apply(s)["ok"] and not called          # off: doesn't remove the PC's Joe's task
    s.schedule.enabled = True
    r = schedule.apply(s)
    assert not r["ok"] and "drive" in r["error"]


def test_unpack_refuses_unsafe(tmp_path):
    z = tmp_path / "bad.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("../evil.txt", "x")
    with pytest.raises(ValueError):
        portable.unpack_archive(z, tmp_path / "out")


def test_install_ollama_from_release(drive, monkeypatch):
    plat = portable._plat()
    name = portable.OLLAMA_ASSETS[plat][0]
    if name.endswith(".tar.zst"):
        pytest.skip("zst")

    def fetch(method, url, **kw):
        return {"tag_name": "v0.20.0", "assets": [{"name": name, "size": 1000,
                                                   "browser_download_url": "https://x/" + name}]}

    def download(url, dest, log, *a, **k):
        exe = "ollama.exe" if portable.WIN else "bin/ollama"
        if name.endswith(".zip"):
            with zipfile.ZipFile(dest, "w") as f:
                f.writestr(exe if portable.WIN else "Ollama.app/Contents/Resources/ollama", "bin")
        else:
            import tarfile
            data = b"bin"
            with tarfile.open(dest, "w:gz") as t:
                ti = tarfile.TarInfo(exe if not portable.MAC else "ollama")
                ti.size = len(data)
                t.addfile(ti, io.BytesIO(data))
        return True

    logs = []
    assert portable.install_ollama(logs.append, fetch=fetch, download=download)
    assert portable.drive_ollama()
    assert (drive / "JoeData" / "data" / "ollama-models").is_dir()


def test_make_a_portable_joe(tmp_path, monkeypatch):
    monkeypatch.setenv("JOE_PORTABLE", "0")
    ws = tmp_path / "ws"
    (ws / "Output").mkdir(parents=True)
    (ws / "Output" / "a.txt").write_text("hi", encoding="utf-8")
    s = Settings()
    s.workspace = str(ws)
    s.comfy.start_command = r"C:\Program Files\ComfyUI\ComfyUI.exe"
    s.schedule.enabled = True
    usb = tmp_path / "usb"
    usb.mkdir()
    err, target = portable.check_dest(str(usb))
    assert not err and target == usb / "Joe"
    assert portable.check_dest("")[0]
    assert portable.check_dest(str(tmp_path / "nope"))[0]
    assert portable.check_dest(str(portable.program_root()))[0]       # not inside Joe himself
    portable.make(s, target, {"settings": True, "work": True}, lambda m: None)
    assert (target / "app" / "Joe.pyw").exists() and (target / "app" / "joeai" / "portable.py").exists()
    assert not (target / "app" / "tests").exists()
    assert not list((target / "app").rglob("__pycache__"))
    assert portable._has_marker(target)
    assert (target / "Start Joe.bat").exists() and (target / "start-joe.sh").exists()
    st = json.loads((target / "JoeData" / "settings" / "settings.json").read_text(encoding="utf-8"))
    assert st["workspace"] == "" and st["comfy"]["start_command"] == "" and not st["schedule"]["enabled"]
    assert (target / "Joe-ai" / "Output" / "a.txt").read_text(encoding="utf-8") == "hi"
    assert portable.check_dest(str(target)) == ("", target)            # again: carries on in place


def test_job_reports_progress(tmp_path, monkeypatch):
    monkeypatch.setenv("JOE_PORTABLE", "0")
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    usb = tmp_path / "usb"
    usb.mkdir()
    job = portable.Job()
    r = job.start(s, str(usb), {"settings": True}, lambda m: None)
    assert r["ok"]
    job.thread.join(600)                 # wait for the copy itself, however slow the machine is
    st = job.status()
    assert st["finished"] and not st["error"] and st["done"] > 0
