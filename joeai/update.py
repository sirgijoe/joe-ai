"""Update check: compares this version with the newest release on GitHub.

Only reads the public releases page (no account, nothing about this PC is sent beyond a
normal web request). Never installs anything by itself: it tells you, and the download
button opens the release page.
"""
from __future__ import annotations

import re
import time

from . import REPO, __version__
from .http import HttpError, request_json

_CACHE: dict = {}
CACHE_S = 6 * 3600


def parse_version(v: str) -> tuple:
    """'v2.1.0' / '2.0.0.dev27' / '2.0.0rc1' -> comparable tuple. Dev/rc sort before the release."""
    v = v.strip().lstrip("vV")
    m = re.match(r"^(\d+(?:\.\d+)*)(?:[.-]?(dev|a|b|rc)(\d*))?", v)
    if not m:
        return (0,)
    nums = [int(x) for x in m.group(1).split(".")]
    while len(nums) < 3:
        nums.append(0)
    pre = {"dev": 0, "a": 1, "b": 2, "rc": 3, None: 9}[m.group(2)]
    return (*nums, pre, int(m.group(3) or 0))


def check(force: bool = False, fetch=request_json) -> dict:
    now = time.time()
    if not force and _CACHE.get("t", 0) > now - CACHE_S:
        return _CACHE["r"]
    url = f"https://api.github.com/repos/{REPO}/releases/latest"
    try:
        rel = fetch("GET", url, timeout=8)
    except HttpError as e:
        msg = "No releases published yet." if "HTTP 404" in str(e) else "Couldn't reach GitHub."
        r = {"ok": False, "current": __version__, "error": msg}
    else:
        latest = str(rel.get("tag_name") or rel.get("name") or "")
        r = {"ok": True, "current": __version__, "latest": latest.lstrip("vV"),
             "newer": parse_version(latest) > parse_version(__version__),
             "url": rel.get("html_url") or f"https://github.com/{REPO}/releases/latest",
             "notes": str(rel.get("body") or "")[:1500]}
    _CACHE.update(t=now, r=r)
    return r
