"""Comfort: quiet hours and an optional phone ping when a run is done.

The phone ping uses ntfy (free, open source): install the ntfy app on your phone, subscribe
to a topic name only you know, and type the same name in Setup. It is OFF until you do, and
it is the only thing Joe ever sends off this PC: one short line ("Joe is done: 3 of 3 tasks,
48 items, 16 pictures"). Nothing from your files goes with it.
"""
from __future__ import annotations

import re
import urllib.error
import urllib.request
from datetime import datetime, time as dtime


def _hhmm(s: str) -> dtime | None:
    m = re.fullmatch(r"\s*(\d{1,2})(?::(\d{2}))?\s*", s or "")
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    return dtime(h, mi) if h < 24 and mi < 60 else None


def in_quiet_hours(start: str, end: str, now: datetime | None = None) -> bool:
    """True between start and end (e.g. 22:00-07:00 wraps past midnight). Blank = never."""
    a, b = _hhmm(start), _hhmm(end)
    if a is None or b is None or a == b:
        return False
    t = (now or datetime.now()).time()
    return a <= t < b if a < b else (t >= a or t < b)


def summary_line(chain: list) -> str:
    """One plain line for the phone, from [(mission, states), ...]."""
    states = [s for _, st in chain for s in st]
    done = sum(1 for s in states if s.status == "done")
    items = sum(s.items for s in states if not s.media_files)
    pics = sum(len(s.media_files) for s in states)
    flags = sum(len(s.flags) for s in states)
    bits = [f"{done} of {len(states)} task{'s' if len(states) != 1 else ''} done"]
    if items:
        bits.append(f"{items} item{'s' if items != 1 else ''}")
    if pics:
        bits.append(f"{pics} picture{'s' if pics != 1 else ''}/video{'s' if pics != 1 else ''}")
    tail = f" {flags} thing{'s' if flags != 1 else ''} to check." if flags else ""
    return "Joe is done: " + ", ".join(bits) + "." + tail


def valid_topic(topic: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{6,64}", topic or ""))


def send_ntfy(server: str, topic: str, message: str, title: str = "Joe", timeout: float = 10,
              at: int | None = None, priority: str = "") -> str:
    """Post a message to ntfy. Returns '' on success, else a short reason. `at` (Unix time) = ntfy
    holds it and delivers it then (scheduled delivery, up to 3 days ahead), even if this PC is off."""
    if not valid_topic(topic):
        return "the topic name must be 6-64 letters, numbers, - or _"
    server = (server or "https://ntfy.sh").rstrip("/")
    if not re.match(r"^https?://", server):
        return "the ntfy server must start with https://"
    headers = {"Title": title, "Tags": "robot", "Content-Type": "text/plain"}
    if at:
        headers["At"] = str(int(at))
    if priority:
        headers["Priority"] = priority                  # "high": pops up with sound, like an alarm
    req = urllib.request.Request(f"{server}/{topic}", data=message[:2000].encode("utf-8"), method="POST",
                                 headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read()
        return ""
    except urllib.error.HTTPError as e:
        return f"ntfy said HTTP {e.code}"
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        if "CERTIFICATE_VERIFY_FAILED" in str(e):
            # Python's copy of the computer's trusted certificates can be out of date (common on Windows
            # with Let's Encrypt sites like ntfy.sh). The computer's own curl uses the system's up-to-date
            # list, so try that before giving up. Still a fully checked, secure connection.
            if not _curl_post(f"{server}/{topic}", message[:2000], headers, timeout + 5):
                return ""
        return f"couldn't reach {server} ({e})"


def _curl_post(url: str, body: str, headers: dict, timeout: float) -> str:
    """POST with the system's curl (Windows 10+, Mac and Linux have it). '' = sent."""
    import shutil
    import subprocess
    curl = shutil.which("curl")
    if not curl:
        return "no curl"
    cmd = [curl, "-sS", "-f", "--max-time", str(int(timeout)), "-X", "POST", "--data-binary", "@-"]
    for k, v in headers.items():
        cmd += ["-H", f"{k}: {v}"]
    try:
        from .system import no_window_flags
        r = subprocess.run(cmd + [url], input=body.encode("utf-8"), capture_output=True, timeout=timeout + 5,
                           creationflags=no_window_flags())
    except (OSError, subprocess.SubprocessError) as e:
        return str(e)
    return "" if r.returncode == 0 else (r.stderr.decode("utf-8", "replace").strip()[:200] or "curl failed")
