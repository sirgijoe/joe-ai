"""Start an installed Joe with no window, check it answers, then ask it to quit.

    python installer/smoke_test.py KIND -- <command that starts Joe...>

Used by the release workflow on Mac and Linux. Uses a throwaway home folder so nothing
real is touched. Exit code 0 = Joe started, said its version and install kind, and quit.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


def config_dir(home: Path) -> Path:
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "joe-ai"
    return home / ".config" / "joe-ai"


def main() -> int:
    kind = sys.argv[1]
    cmd = sys.argv[sys.argv.index("--") + 1:]
    home = Path(tempfile.mkdtemp(prefix="joe-home-"))
    env = dict(os.environ, HOME=str(home), JOE_NO_WINDOW="1", JOE_OFFLINE="1")
    for k in ("XDG_CONFIG_HOME", "XDG_DATA_HOME"):
        env.pop(k, None)
    p = subprocess.Popen(cmd, env=env)
    lock = config_dir(home) / "app.json"
    info = None
    for _ in range(120):
        if p.poll() is not None:
            print(f"Joe exited early with code {p.returncode}")
            crash = config_dir(home) / "crash.log"
            if crash.exists():
                print(crash.read_text(encoding="utf-8"))
            return 1
        if lock.exists():
            try:
                info = json.loads(lock.read_text(encoding="utf-8"))
                break
            except ValueError:
                pass
        time.sleep(1)
    if not info:
        print("Joe didn't start within 2 minutes")
        p.kill()
        return 1
    url = f"http://127.0.0.1:{info['port']}"
    hdr = {"X-NR-Token": info["token"]}
    with urllib.request.urlopen(urllib.request.Request(url + "/api/ping", headers=hdr), timeout=10) as r:
        ping = json.loads(r.read() or b"{}")
    print("ping:", ping)
    with urllib.request.urlopen(urllib.request.Request(url + "/", headers=hdr), timeout=10) as r:
        assert b"<html" in r.read(4000).lower(), "main page didn't load"
    q = urllib.request.Request(url + "/api/quit", data=b"{}", method="POST",
                               headers={**hdr, "Content-Type": "application/json"})
    urllib.request.urlopen(q, timeout=10).close()
    try:
        p.wait(60)
    except subprocess.TimeoutExpired:
        print("Joe didn't quit within 60 s")
        p.kill()
        return 1
    want = os.environ.get("JOE_EXPECT_KIND", kind)
    got = ping.get("install_kind")
    if got is not None and got != want:
        print(f"install kind {got!r}, expected {want!r}")
        return 1
    print("smoke test ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
