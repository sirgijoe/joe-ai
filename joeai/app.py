"""Double-click launcher: start (or reuse) the local server and open the app window.

The window is a Chromium browser in "app mode" (no tabs or address bar): Edge, which ships
with every Windows 10/11 PC, or Edge/Chrome/Chromium/Brave on Mac and Linux (system.py).
Without one, Joe opens in the default browser.
"""
from __future__ import annotations

import json
import os
import sys
import traceback
import urllib.request
from pathlib import Path

from .config import config_dir


# The window remembers permissions (like the microphone) per address, and the address includes
# the port. A random port each start made Edge ask for the mic every time, so Joe keeps one port.
STABLE_PORTS = (47317, 47318, 47319, 47320)


def _serve_stable(app):
    from .server import serve
    for port in STABLE_PORTS:
        try:
            return serve(app, port)
        except OSError:                   # taken by another program: try the next one
            continue
    return serve(app, 0)


def _lock_path() -> Path:
    return config_dir() / "app.json"


def _existing_url() -> str | None:
    p = _lock_path()
    if not p.exists():
        return None
    try:
        info = json.loads(p.read_text(encoding="utf-8"))
        url = f"http://127.0.0.1:{info['port']}"
        req = urllib.request.Request(url + "/api/ping", headers={"X-NR-Token": info["token"]})
        with urllib.request.urlopen(req, timeout=2) as r:
            info2 = json.loads(r.read() or b"{}")
        from . import __version__
        if info2.get("version") == __version__ or info2.get("running"):
            return url + "/"                       # same version, or mid-run: reuse it
        quit_req = urllib.request.Request(url + "/api/quit", data=b"{}", method="POST",
                                          headers={"X-NR-Token": info["token"],
                                                   "Content-Type": "application/json"})
        urllib.request.urlopen(quit_req, timeout=2).close()
        import time
        time.sleep(2)                              # old version shuts down; start the new one
    except (OSError, KeyError, ValueError):
        pass
    return None


def open_window(url: str) -> None:
    from .system import open_window as _ow
    _ow(url, config_dir() / "window")


def main() -> int:
    config_dir().mkdir(parents=True, exist_ok=True)
    url = _existing_url()
    if url:                                  # already running (maybe mid-run): just reopen
        open_window(url)
        return 0
    from .server import App
    app = App()
    httpd = _serve_stable(app)
    port = httpd.server_address[1]
    _lock_path().write_text(json.dumps({"port": port, "token": app.token, "pid": os.getpid()}),
                            encoding="utf-8")
    open_window(f"http://127.0.0.1:{port}/")
    try:
        httpd.serve_forever()
    finally:
        if app.thread:
            app.thread.join()
        app.voice.close()
        app.clone.close()
        try:
            _lock_path().unlink()
        except OSError:
            pass
    return 0


def run_logged() -> None:
    """Entry for pythonw (no console): write crashes to a log file instead."""
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        config_dir().mkdir(parents=True, exist_ok=True)
        (config_dir() / "crash.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
