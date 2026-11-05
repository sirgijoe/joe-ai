"""system.py: the one place where Windows, Mac and Linux differ."""
from __future__ import annotations

from pathlib import Path

import pytest

from joeai import system


def _as(monkeypatch, osname: str):
    monkeypatch.setattr(system, "WINDOWS", osname == "windows")
    monkeypatch.setattr(system, "MAC", osname == "mac")
    monkeypatch.setattr(system, "LINUX", osname == "linux")


@pytest.mark.parametrize("osname", ["windows", "mac", "linux"])
def test_folders_are_per_system(monkeypatch, tmp_path, osname):
    _as(monkeypatch, osname)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    for var in ("APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME", "XDG_DATA_HOME"):
        monkeypatch.delenv(var, raising=False)
    cfg, data = system.config_dir(), system.data_dir()
    assert cfg.name == "joe-ai" and data.name == "joe-ai"
    assert str(cfg).startswith(str(tmp_path)) and str(data).startswith(str(tmp_path))
    if osname == "mac":
        assert "Library" in cfg.parts
    if osname == "linux":
        assert cfg.parent.name == ".config" and data.parent.name == "share"
    assert system.name() == osname


def test_default_workspace_prefers_documents(monkeypatch, tmp_path):
    _as(monkeypatch, "mac")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert system.default_workspace() == tmp_path / "Joe-ai"          # no Documents folder
    (tmp_path / "Documents").mkdir()
    assert system.default_workspace() == tmp_path / "Documents" / "Joe-ai"


@pytest.mark.parametrize("osname,pm,kind,first", [
    ("windows", "winget", "run", None),
    ("mac", "brew", "run", None),
    ("linux", "apt", "command", "sudo"),
    ("linux", "dnf", "command", "sudo"),
    ("linux", "pacman", "command", "sudo"),
])
def test_install_plan_ffmpeg(monkeypatch, osname, pm, kind, first):
    _as(monkeypatch, osname)
    monkeypatch.setattr(system, "package_manager", lambda: pm)
    plan = system.install_plan("ffmpeg")
    assert plan["kind"] == kind and plan["manager"] == pm
    if first:
        assert plan["cmd"][0] == first             # Linux: shown to the user, never run by Joe
    assert plan["cmd"][-1] in ("ffmpeg", "Gyan.FFmpeg") or "Gyan.FFmpeg" in plan["cmd"]


def test_install_plan_falls_back_to_the_download_page(monkeypatch):
    _as(monkeypatch, "linux")
    monkeypatch.setattr(system, "package_manager", lambda: "apt")
    assert system.install_plan("comfyui")["kind"] == "joe"     # no apt package: Joe sets up his own copy
    monkeypatch.setattr(system, "package_manager", lambda: None)
    assert system.install_plan("ffmpeg")["kind"] == "page"


def test_ollama_is_a_cask_on_mac(monkeypatch):
    _as(monkeypatch, "mac")
    monkeypatch.setattr(system, "package_manager", lambda: "brew")
    assert "--cask" in system.install_plan("ollama")["cmd"]
    assert "--cask" not in system.install_plan("ffmpeg")["cmd"]


def test_run_install_linux_shows_the_command_and_runs_nothing(monkeypatch):
    from joeai import doctor
    _as(monkeypatch, "linux")
    monkeypatch.setattr(system, "package_manager", lambda: "apt")
    ran = []
    monkeypatch.setattr(doctor.subprocess, "run", lambda *a, **k: ran.append(a))
    logs: list[str] = []
    assert doctor.run_install("ffmpeg", "FFmpeg", "", logs.append) is False
    assert not ran
    assert any("sudo apt-get install -y ffmpeg" in ln for ln in logs)
    assert any("never asks for passwords" in ln for ln in logs)


def test_run_install_opens_page_when_no_package(monkeypatch):
    from joeai import doctor
    _as(monkeypatch, "linux")
    monkeypatch.setattr(system, "package_manager", lambda: None)
    opened = []
    monkeypatch.setattr(doctor.webbrowser, "open", opened.append)
    assert doctor.run_install("ffmpeg", "FFmpeg", "", lambda s: None) is False
    assert opened == ["https://ffmpeg.org/download.html"]


def test_open_window_without_app_browser_uses_default(monkeypatch, tmp_path):
    monkeypatch.setattr(system, "app_browser", lambda: None)
    opened = []
    monkeypatch.setattr(system.webbrowser, "open", opened.append)
    system.open_window("http://127.0.0.1:1/", tmp_path)
    assert opened == ["http://127.0.0.1:1/"]


def test_open_window_uses_app_mode(monkeypatch, tmp_path):
    monkeypatch.setattr(system, "app_browser", lambda: "/usr/bin/chromium")
    seen = []
    monkeypatch.setattr(system, "popen_detached", lambda cmd, cwd=None: seen.append(cmd))
    system.open_window("http://127.0.0.1:1/", tmp_path)
    assert seen and seen[0][0] == "/usr/bin/chromium" and "--app=http://127.0.0.1:1/" in seen[0]


def test_keep_awake_off_does_nothing():
    with system.keep_awake(False):
        pass


def test_keep_awake_linux_without_tool_warns(monkeypatch):
    _as(monkeypatch, "linux")
    monkeypatch.setattr(system.shutil, "which", lambda name: None)
    logs: list[str] = []
    with system.keep_awake(True, logs.append):
        pass
    assert logs and "keep the computer awake" in logs[0]


@pytest.mark.parametrize("osname,action,first", [
    ("windows", "shutdown", "shutdown"), ("windows", "sleep", "rundll32.exe"),
    ("mac", "shutdown", "osascript"), ("mac", "sleep", "pmset"),
    ("linux", "shutdown", "shutdown"), ("linux", "sleep", "systemctl"),
])
def test_when_finished_commands(monkeypatch, osname, action, first):
    _as(monkeypatch, osname)
    ran = []
    monkeypatch.setattr(system.subprocess, "run", lambda cmd, **k: ran.append(cmd))
    system.when_finished(action, lambda s: None)
    assert ran and ran[0][0] == first


def test_when_finished_nothing(monkeypatch):
    ran = []
    monkeypatch.setattr(system.subprocess, "run", lambda cmd, **k: ran.append(cmd))
    system.when_finished("nothing", lambda s: None)
    assert not ran


def test_ram_is_a_number():
    assert system.ram_total_gb() >= 0


def test_uv_download_name_per_computer():
    from joeai.addons import uv_asset
    assert uv_asset("win32", "AMD64") == "uv-x86_64-pc-windows-msvc.zip"
    assert uv_asset("win32", "ARM64") == "uv-aarch64-pc-windows-msvc.zip"
    assert uv_asset("darwin", "arm64") == "uv-aarch64-apple-darwin.tar.gz"
    assert uv_asset("darwin", "x86_64") == "uv-x86_64-apple-darwin.tar.gz"
    assert uv_asset("linux", "x86_64") == "uv-x86_64-unknown-linux-gnu.tar.gz"
    assert uv_asset("linux", "riscv64") is None


def test_uv_unpacks_from_tar_and_zip(tmp_path):
    import io, tarfile, zipfile
    from joeai.addons import _unpack_uv
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for n in ("uv-x86_64-unknown-linux-gnu/uv", "uv-x86_64-unknown-linux-gnu/uvx",
                  "uv-x86_64-unknown-linux-gnu/README"):
            data = b"#!/bin/sh\n"
            info = tarfile.TarInfo(n)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    _unpack_uv(buf.getvalue(), "x.tar.gz", tmp_path / "a")
    assert sorted(p.name for p in (tmp_path / "a").iterdir()) == ["uv", "uvx"]
    assert (tmp_path / "a" / "uv").stat().st_mode & 0o100
    zb = io.BytesIO()
    with zipfile.ZipFile(zb, "w") as z:
        z.writestr("uv.exe", b"MZ")
        z.writestr("other.txt", b"x")
    _unpack_uv(zb.getvalue(), "x.zip", tmp_path / "b")
    assert [p.name for p in (tmp_path / "b").iterdir()] == ["uv.exe"]
