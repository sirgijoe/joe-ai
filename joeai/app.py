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
            return f"{url}/#t={info['token']}"     # same version, or mid-run: reuse it
        quit_req = urllib.request.Request(url + "/api/quit", data=b"{}", method="POST",
                                          headers={"X-NR-Token": info["token"],
                                                   "Content-Type": "application/json"})
        urllib.request.urlopen(quit_req, timeout=2).close()
        import time
        time.sleep(2)                              # old version shuts down; start the new one
    except (OSError, KeyError, ValueError):
        pass
    return None


def wait_for_old(seconds: float = 60) -> None:
    """RESTART JOE: the new copy waits until the old one has closed (its lock file is gone)."""
    import time
    end = time.monotonic() + seconds
    while _lock_path().exists() and time.monotonic() < end:
        time.sleep(0.5)


def restart(log=print) -> bool:
    """Start a fresh Joe that waits for this one to close (the caller then quits)."""
    from .system import joe_command, popen_detached
    try:
        popen_detached(joe_command("restart", console=False))
        return True
    except OSError as e:
        log(f"Couldn't restart Joe: {e}. Close him and open him again.")
        return False


def open_window(url: str) -> None:
    if os.environ.get("JOE_NO_WINDOW"):      # installer tests: run the server, show nothing
        return
    from .system import open_window as _ow
    _ow(url, config_dir() / "window")


def main() -> int:
    from . import portable
    portable.start()
    config_dir().mkdir(parents=True, exist_ok=True)
    url = _existing_url()
    if url:                                  # already running (maybe mid-run): just reopen
        open_window(url)
        return 0
    from .server import App
    app = App()
    httpd = _serve_stable(app)
    port = httpd.server_address[1]
    from .fsutil import atomic_write_text
    atomic_write_text(_lock_path(), json.dumps({"port": port, "token": app.token, "pid": os.getpid()}))
    try:                                     # the token is only for this user (mkstemp already makes 0600)
        if os.name != "nt":
            os.chmod(config_dir(), 0o700)
    except OSError:
        pass
    open_window(f"http://127.0.0.1:{port}/#t={app.token}")   # the window's key rides in the #part
    try:
        httpd.serve_forever()
    finally:
        if app.thread:
            app.thread.join()
        app.voice.close()
        app.tool_voice.close()
        app.clone.close()
        try:                                 # only our own lock: a newer Joe may already have written its own
            if json.loads(_lock_path().read_text(encoding="utf-8")).get("pid") == os.getpid():
                _lock_path().unlink()
        except (OSError, ValueError):
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
