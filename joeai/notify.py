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
              at: int | None = None) -> str:
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
    req = urllib.request.Request(f"{server}/{topic}", data=message[:2000].encode("utf-8"), method="POST",
                                 headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read()
        return ""
    except urllib.error.HTTPError as e:
        return f"ntfy said HTTP {e.code}"
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        return f"couldn't reach {server} ({e})"
