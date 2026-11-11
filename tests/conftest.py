import os

import pytest

os.environ.setdefault("JOE_OFFLINE", "1")      # no update checks or model-list fetches in tests
os.environ.setdefault("JOE_VAULT", "file")     # tests never touch this computer's real keychain (vault.py)


@pytest.fixture(autouse=True)
def _no_real_graphics_card(request, monkeypatch):
    """Tests behave the same on every machine: the test PC's own graphics card (an Apple chip on
    the Mac runner, an NVIDIA card on a developer's PC) is never seen. Tests that need a card
    set one themselves; test_hardware checks the detection code itself."""
    if request.module.__name__.endswith("test_hardware"):
        yield
        return
    from joeai import hardware
    hardware.reset_cache()
    monkeypatch.setattr(hardware, "_nvidia", lambda: None)
    monkeypatch.setattr(hardware, "_static", lambda: None)
    yield
    hardware.reset_cache()


@pytest.fixture(autouse=True)
def _flat_filing_for_older_tests(request, monkeypatch):
    """Tests written before 2.3 check where things land with the old "flat" filing (still a Setup
    choice). Tests of the dated mission folders (test_filing.py, test_dev23*) use the real choice."""
    name = request.module.__name__
    if name.endswith("test_filing") or "test_dev23" in name:
        yield
        return
    from joeai import filing
    monkeypatch.setattr(filing, "how", lambda settings: "flat")
    yield


# The programs and services usually on a Joe user's own computer. Tests never see the real ones
# (13 tests failed on a PC with Ollama, ComfyUI and Claude Desktop installed, and passed on GitHub):
# connections to their usual addresses on this computer are refused, home and app-data folders
# point at an empty folder, and the PATH folders holding them are left out. A test that needs one
# makes its own (a fake server on a free port, a folder in tmp_path).
SERVICE_PORTS = {11434, 8000, 8188, 1234, 8080, 5001, 1337}       # Ollama, ComfyUI, LM Studio, llama.cpp, ...
_LOOPBACK = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}
_HIDE_ON_PATH = ("ollama", "ollama.exe", "comfyui", "comfyui.exe", "lms", "lms.exe", "llama-server",
                 "llama-server.exe")


@pytest.fixture(autouse=True, scope="session")
def _no_real_programs(tmp_path_factory):
    import socket
    from pathlib import Path
    home = tmp_path_factory.mktemp("home")
    for d in ("AppData/Roaming", "AppData/Local", "Documents", ".config", ".local/share", "Programs"):
        (home / d).mkdir(parents=True, exist_ok=True)
    mp = pytest.MonkeyPatch()
    for k, v in {"HOME": home, "USERPROFILE": home, "APPDATA": home / "AppData/Roaming",
                 "LOCALAPPDATA": home / "AppData/Local", "XDG_CONFIG_HOME": home / ".config",
                 "XDG_DATA_HOME": home / ".local/share", "ProgramFiles": home / "Programs",
                 "ProgramFiles(x86)": home / "Programs", "ProgramW6432": home / "Programs"}.items():
        mp.setenv(k, str(v))
    path = [p for p in os.environ.get("PATH", "").split(os.pathsep)
            if p and not any((Path(p) / n).is_file() for n in _HIDE_ON_PATH)]
    mp.setenv("PATH", os.pathsep.join(path))
    real_connect = socket.socket.connect

    def connect(self, address):
        if isinstance(address, tuple) and len(address) >= 2 and str(address[0]).lower() in _LOOPBACK \
                and address[1] in SERVICE_PORTS:
            raise ConnectionRefusedError(f"tests don't use the real service on port {address[1]}")
        return real_connect(self, address)
    real_connect_ex = socket.socket.connect_ex

    def connect_ex(self, address):
        if isinstance(address, tuple) and len(address) >= 2 and str(address[0]).lower() in _LOOPBACK \
                and address[1] in SERVICE_PORTS:
            import errno
            return errno.ECONNREFUSED
        return real_connect_ex(self, address)
    mp.setattr(socket.socket, "connect", connect)
    mp.setattr(socket.socket, "connect_ex", connect_ex)
    from joeai import finder
    mp.setattr(finder, "_drives", lambda: [])
    mp.setattr(finder, "_installed_apps", lambda pattern: [])
    # An AI app that happens to be open on this computer (Claude Desktop, ChatGPT) isn't "running" as
    # far as the tests go: connect() would refuse with "close it first". A test that passes its own
    # process list (run=) still gets the real check.
    from joeai import connect
    real_running = connect.app_running
    mp.setattr(connect, "app_running", lambda app_id, run=None: real_running(app_id, run) if run else False)
    yield
    mp.undo()
