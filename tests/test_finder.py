"""Finding ComfyUI, its models, and the other programs on a fake Windows PC."""
import json
import os
import socket

import pytest

from joeai import finder
from joeai.config import Settings


@pytest.fixture
def pc(tmp_path, monkeypatch):
    """A fake Windows user folder; nothing real on this machine is looked at."""
    home = tmp_path / "home"
    local, roaming = home / "AppData" / "Local", home / "AppData" / "Roaming"
    for d in (local, roaming):
        d.mkdir(parents=True)
    monkeypatch.setattr(finder, "WINDOWS", True)
    monkeypatch.setattr(finder, "MAC", False)
    monkeypatch.setattr(finder, "_home", lambda: home)
    monkeypatch.setattr(finder, "_drives", lambda: [])
    monkeypatch.setattr(finder, "_installed_apps", lambda pattern: [])
    monkeypatch.setattr(finder.shutil, "which", lambda name: None)
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("APPDATA", str(roaming))
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf"))
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    return home


def touch(p, mtime=None):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")
    if mtime:
        os.utime(p, (mtime, mtime))
    return p


def desktop_app(home, base):
    app = home / "AppData" / "Local" / "Programs" / "@comfyorgcomfyui-electron"
    touch(app / "ComfyUI.exe", 1_754_400_000)            # left behind by an older version
    touch(app / "Uninstall ComfyUI.exe", 1_754_400_000)
    touch(app / "Uninstall Comfy Desktop.exe", 1_792_691_000)
    new = touch(app / "Comfy Desktop.exe", 1_792_691_000)
    (base / "models" / "checkpoints").mkdir(parents=True)
    (base / "output").mkdir()
    cfg = home / "AppData" / "Roaming" / "ComfyUI" / "config.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"basePath": str(base)}), encoding="utf-8")
    return new


def test_desktop_newest_program_and_data_folder(pc):
    base = pc / "Documents" / "ComfyUI"
    new = desktop_app(pc, base)
    inst = finder.find_comfy()
    assert inst.kind == "desktop"
    assert inst.command == [str(new)]                    # not the old ComfyUI.exe, not an uninstaller
    assert inst.models_dir == base / "models"
    assert inst.output_dir == base / "output"


def test_data_folder_from_extra_models_yaml(pc, tmp_path):
    base = tmp_path / "D-drive" / "ComfyData"
    (base / "models").mkdir(parents=True)
    y = pc / "AppData" / "Roaming" / "ComfyUI" / "extra_models_config.yaml"
    y.parent.mkdir(parents=True)
    y.write_text(f"comfyui_desktop:\n  base_path: '{base}'\n  checkpoints: models/checkpoints/\n")
    assert finder.desktop_base_path() == base


def test_stale_start_command_searches_again(pc):
    desktop_app(pc, pc / "Documents" / "ComfyUI")
    gone = pc / "old" / "ComfyUI.exe"
    inst = finder.find_comfy(start_command=f'"{gone}"')
    assert inst.kind == "desktop"


def test_working_start_command_wins(pc):
    desktop_app(pc, pc / "Documents" / "ComfyUI")
    port = pc / "Desktop" / "ComfyUI_windows_portable"
    bat = touch(port / "run_nvidia_gpu.bat")
    (port / "ComfyUI" / "models").mkdir(parents=True)
    inst = finder.find_comfy(start_command=f'"{bat}"')
    assert inst.kind == "custom" and inst.port == 8188
    assert inst.models_dir == port / "ComfyUI" / "models"


def test_portable_and_own_install(pc):
    port = pc / "Desktop" / "ComfyUI_windows_portable"
    touch(port / "run_nvidia_gpu.bat")
    (port / "ComfyUI" / "models").mkdir(parents=True)
    inst = finder.find_comfy()
    assert inst.kind == "portable" and inst.cwd == str(port) and inst.port == 8188
    assert inst.models_dir == port / "ComfyUI" / "models"

    own = pc / "Documents" / "AI" / "ComfyUI"        # git clone + venv, inside an "AI" folder
    touch(own / "main.py")
    (own / "comfy").mkdir()
    touch(own / "venv" / "Scripts" / "python.exe")
    kinds = {i.kind: i for i in finder.portable_installs()}
    assert kinds["manual"].command == [str(own / "venv" / "Scripts" / "python.exe"), "main.py"]


def test_models_folder_from_setup(pc, tmp_path):
    desktop_app(pc, pc / "Documents" / "ComfyUI")
    mine = tmp_path / "BigDrive" / "SD-models"
    mine.mkdir(parents=True)
    assert finder.find_comfy(models_dir=str(mine)).models_dir == mine
    # a Setup folder that no longer exists is ignored
    assert finder.find_comfy(models_dir=str(tmp_path / "nope")).models_dir == pc / "Documents" / "ComfyUI" / "models"


def test_nothing_installed(pc):
    assert finder.find_comfy() is None
    assert finder.ffmpeg_exe() is None and finder.pandoc_exe() is None and finder.ollama_exe() is None


def test_tools_in_usual_places(pc, tmp_path):
    local = pc / "AppData" / "Local"
    ff = touch(local / "Microsoft" / "WinGet" / "Packages" / "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
               / "ffmpeg-8.0-full_build" / "bin" / "ffmpeg.exe")
    pd = touch(local / "Pandoc" / "pandoc.exe")
    ol = touch(local / "Programs" / "Ollama" / "ollama.exe")
    assert finder.ffmpeg_exe() == str(ff)
    assert finder.pandoc_exe() == str(pd)
    assert finder.ollama_exe() == str(ol)
    typed = touch(tmp_path / "tools" / "ffmpeg.exe")
    assert finder.ffmpeg_exe(str(typed)) == str(typed)                     # Setup wins
    assert finder.ffmpeg_exe(str(tmp_path / "gone.exe")) == str(ff)      # unless it's gone


def test_start_comfy_runs_what_was_found_and_logs(pc, monkeypatch):
    from joeai import services as svc
    new = desktop_app(pc, pc / "Documents" / "ComfyUI")
    started, lines = [], []
    monkeypatch.setattr(svc, "_popen", lambda cmd, cwd=None: started.append((cmd, cwd)))
    sm = svc.ServiceManager(Settings(), log=lines.append)
    calls = {"n": 0}

    def up():
        calls["n"] += 1
        return calls["n"] > 3
    monkeypatch.setattr(sm, "comfy_up", up)
    monkeypatch.setattr(svc.time, "sleep", lambda s: None)
    assert sm.start_comfy()
    assert started == [([str(new)], str(new.parent))]
    assert any("Starting ComfyUI Desktop" in ln for ln in lines)
    assert sm.comfy_exe() == new


def test_wait_reports_progress(monkeypatch):
    from joeai import services as svc
    lines = []
    sm = svc.ServiceManager(Settings(), log=lines.append)
    clock = {"t": 0.0}
    monkeypatch.setattr(svc.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(svc.time, "sleep", lambda s: clock.__setitem__("t", clock["t"] + s))
    assert not sm._wait(lambda: False, 95, "ComfyUI to open")
    notes = [ln for ln in lines if "still waiting for ComfyUI" in ln]
    assert len(notes) == 3 and "(0:30 of 1:35)" in notes[0]


def test_window_keeps_one_address(monkeypatch):
    """Same port every start, so the window remembers the microphone permission."""
    from joeai import app as app_mod
    from joeai.server import App
    blocker = socket.socket()
    try:
        blocker.bind(("127.0.0.1", app_mod.STABLE_PORTS[0]))
    except OSError:
        pytest.skip("first port busy on this machine")
    try:
        a = App.__new__(App)
        import joeai.server as srv
        got = []
        monkeypatch.setattr(srv, "serve", lambda app, port=0: got.append(port) or _bind(port))
        h = app_mod._serve_stable(a)
        assert got[0] == app_mod.STABLE_PORTS[0] and h.server_address[1] == app_mod.STABLE_PORTS[1]
        h.server_close()
    finally:
        blocker.close()


def _bind(port):
    from http.server import HTTPServer, BaseHTTPRequestHandler
    return HTTPServer(("127.0.0.1", port), BaseHTTPRequestHandler)
