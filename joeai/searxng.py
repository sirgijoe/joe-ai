"""Help with running your own SearXNG (the free way to search the whole web; websearch.py asks it).

SearXNG is a search engine you run yourself. Joe doesn't install it: the person installs Docker
Desktop and runs one command. Joe does the two fiddly parts:
  - make_folder(): a folder in the Joe folder with the settings file SearXNG needs (JSON answers
    switched on, which is off as SearXNG comes), and the command that starts it for this PC only.
  - check(): one search at the address, and what is wrong in plain words when it doesn't work.
Nothing here goes online except check(), which only asks the address the person typed.
"""
from __future__ import annotations

import secrets
import urllib.parse
from pathlib import Path

from .http import HttpError, request_json
from .websearch import AGENT, REASONS, searxng_base

FOLDER = "SearXNG"
PORT = 8888
ADDRESS = f"http://localhost:{PORT}"
IMAGE = "docker.io/searxng/searxng:latest"
SETTINGS = """# Made by Joe for your own SearXNG. SearXNG's own settings are used for everything not listed here.
use_default_settings: true

server:
  # A random secret only this SearXNG knows.
  secret_key: "{secret}"
  # No "too many searches" limit: only this PC can reach it.
  limiter: false

search:
  # json is what lets Joe read the results. As SearXNG comes, only html is on.
  formats:
    - html
    - json
"""
JSON_OFF = ("Something answers there, but its JSON answers are switched off. In its settings.yml, under search: "
            "and formats:, add a line with - json (below - html), then start it again: docker restart searxng")


def command(folder: Path) -> str:
    """The one line that starts SearXNG: this PC only (127.0.0.1), and again whenever Docker starts."""
    return (f'docker run -d --name searxng --restart unless-stopped -p 127.0.0.1:{PORT}:8080 '
            f'-v "{folder / "config"}:/etc/searxng" -v "{folder / "data"}:/var/cache/searxng" {IMAGE}')


def make_folder(workspace) -> dict:
    """Make <Joe folder>/SearXNG with config/settings.yml and data/. A settings file that is already
    there is left exactly as it is."""
    folder = Path(workspace) / FOLDER
    conf = folder / "config" / "settings.yml"
    try:
        (folder / "config").mkdir(parents=True, exist_ok=True)
        (folder / "data").mkdir(parents=True, exist_ok=True)
        made = not conf.exists()
        if made:
            conf.write_text(SETTINGS.format(secret=secrets.token_hex(32)), encoding="utf-8", newline="\n")
    except OSError as e:
        return {"ok": False, "text": f"Joe couldn't make the folder {folder} ({e.strerror or e})."}
    return {"ok": True, "made": made, "folder": str(folder), "command": command(folder), "address": ADDRESS,
            "text": (f"Made {folder}." if made else f"{folder} is already there; Joe left its settings as they are.")}


def check(address: str) -> dict:
    """One search at the person's SearXNG: {"ok", "text"}, the text saying what to do next."""
    base = searxng_base(address)
    if not base:
        return {"ok": False, "text": f"Type its address first, like {ADDRESS} (with http:// in front)."}
    q = urllib.parse.urlencode({"q": "pottery", "format": "json", "safesearch": 1})
    try:
        d = request_json("GET", f"{base}/search?{q}", timeout=20, headers=AGENT)
    except HttpError as e:
        said = str(e)
        if said.startswith("HTTP 403"):
            return {"ok": False, "text": JSON_OFF}
        if said.startswith("HTTP 429"):
            return {"ok": False, "text": "It says too many searches: its limiter is on. In its settings.yml, under "
                                         "server:, set limiter: false, then start it again: docker restart searxng"}
        if said.startswith("HTTP "):
            return {"ok": False, "text": f"It answered with an error ({said[5:8]}). Is that the right address?"}
        if "bad JSON" in said:
            return {"ok": False, "text": "Something answers there, but it isn't SearXNG's JSON. "
                                         "Is that the right address and port?"}
        why = REASONS.get(getattr(e, "kind", ""), "")
        return {"ok": False, "text": "Nothing answers at that address" + (f" ({why})" if why else "")
                + ". Is Docker Desktop running, and has SearXNG been started? To start it again: docker start searxng"}
    results = d.get("results") if isinstance(d, dict) else None
    if not isinstance(results, list):
        return {"ok": False, "text": "Something answers there, but it isn't SearXNG's JSON. "
                                     "Is that the right address and port?"}
    if not results:
        down = [f"{x[0]} ({x[1]})" for x in (d.get("unresponsive_engines") or [])
                if isinstance(x, (list, tuple)) and len(x) >= 2][:4]
        return {"ok": False, "text": "Your SearXNG answers, but its search engines found nothing"
                + (": " + ", ".join(down) if down else "") + ". Try again in a minute."}
    n = len(results)
    return {"ok": True, "text": f"Your SearXNG works ({n} result{'s' if n != 1 else ''}). "
                                "Tick 'Your own SearXNG' in the list and SAVE."}
