"""Screen savers: Joe's built-in ones and ones the local model designs from your words.

Like custom themes, a saver is only a few checked settings (which animation, three colors,
speed, how busy, a short line of text, whether Joe's work status shows), never code, so a saver
file can't break the window. The window draws the animation itself (app.js, drawSaver).
Custom ones live in <workspace>/Themes/savers/<slug>.json.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .fsutil import atomic_write_text
from .mission import slug

# kind -> what it looks like (also told to the model)
KINDS = {
    "drift": "Joe's name and status drifting slowly around a dark screen",
    "binary": "Joe's real name in ones and zeros (01000001 01001001) falling like rain",
    "stars": "flying through a starfield",
    "bounce": "a word bouncing off the edges, changing color at each wall",
    "waves": "glowing oscilloscope waves rolling across the screen",
    "coffee": "a steaming coffee mug and a blinking cursor typing a line (how Joe was born)",
    "fireflies": "soft glowing dots wandering and fading",
    "snow": "gentle snowfall",
    "pipes": "colored pipes growing across the screen in right angles",
    "clock": "a big retro clock with the date",
}
BUILTIN = [
    {"id": "joe", "name": "Joe (classic)", "kind": "drift", "colors": ["#000000", "#33ff66", "#ffb000"],
     "speed": 2, "density": 3, "text": "JOE", "status": True},
    {"id": "binary", "name": "Binary rain", "kind": "binary", "colors": ["#000000", "#33ff66", "#d7ffd9"],
     "speed": 3, "density": 3, "text": "01000001 01001001", "status": True},
    {"id": "coffee", "name": "Coffee break", "kind": "coffee", "colors": ["#0b0b0b", "#e8d5b5", "#ffb000"],
     "speed": 2, "density": 2, "text": "brewing ideas...", "status": True},
    {"id": "stars", "name": "Starfield", "kind": "stars", "colors": ["#000000", "#ffffff", "#7fb2ff"],
     "speed": 3, "density": 3, "text": "", "status": True},
    {"id": "bounce", "name": "Bouncing Joe", "kind": "bounce", "colors": ["#000000", "#33ff66", "#ff5fd7"],
     "speed": 3, "density": 1, "text": "JOE", "status": False},
    {"id": "waves", "name": "Phosphor waves", "kind": "waves", "colors": ["#000000", "#33ff66", "#ffb000"],
     "speed": 2, "density": 3, "text": "", "status": True},
    {"id": "fireflies", "name": "Fireflies", "kind": "fireflies", "colors": ["#05070d", "#fff3a0", "#9dff8a"],
     "speed": 2, "density": 3, "text": "", "status": True},
    {"id": "snow", "name": "Snowfall", "kind": "snow", "colors": ["#08111e", "#ffffff", "#9cc9ff"],
     "speed": 2, "density": 3, "text": "", "status": True},
    {"id": "pipes", "name": "Pipes", "kind": "pipes", "colors": ["#000000", "#33ccff", "#ff9933"],
     "speed": 3, "density": 2, "text": "", "status": False},
    {"id": "clock", "name": "Retro clock", "kind": "clock", "colors": ["#000000", "#ffb000", "#33ff66"],
     "speed": 1, "density": 1, "text": "", "status": True},
]
_HEX = re.compile(r"^#([0-9a-f]{3}|[0-9a-f]{6})$", re.I)

PROMPT = """Design a screen saver for a friendly retro-style desktop helper named Joe, from this description:
"{desc}"
Pick the animation that fits best:
{kinds}
Reply with ONLY one JSON object, no other text:
{{"name": "<2-3 word name>", "kind": one of {kind_ids}, "colors": ["#background", "#main", "#accent"],
  "speed": 1-5, "density": 1-5, "text": "<up to 24 characters to show, or empty>", "status": true or false}}
The background is usually dark (screen savers protect screens). status = show Joe's work status line."""


def _color(v, fallback: str) -> str:
    v = str(v or "").strip()
    if not _HEX.match(v):
        return fallback
    if len(v) == 4:
        v = "#" + "".join(c * 2 for c in v[1:])
    return v.lower()


def validate(d: dict) -> dict:
    if not isinstance(d, dict):
        raise ValueError("not a saver")
    kind = str(d.get("kind") or "").strip().lower()
    if kind not in KINDS:
        raise ValueError(f"unknown animation '{kind}'")
    base = next(b for b in BUILTIN if b["kind"] == kind)
    cols = d.get("colors") if isinstance(d.get("colors"), list) else []
    colors = [_color(cols[i] if i < len(cols) else "", base["colors"][i]) for i in range(3)]
    from .themes import contrast
    if contrast(colors[0], colors[1]) < 3:          # keep the main color visible on the background
        colors[1] = "#ffffff" if contrast(colors[0], "#ffffff") >= contrast(colors[0], "#000000") else "#000000"

    def num(k):
        try:
            return max(1, min(5, int(round(float(d.get(k))))))
        except (TypeError, ValueError):
            return base[k]
    text = re.sub(r"[<>{}\\]", "", " ".join(str(d.get("text") or "").split()))[:24]
    name = " ".join(re.sub(r"[<>{}\\]", "", str(d.get("name") or "")).split())[:40] or "My screen saver"
    return {"name": name, "kind": kind, "colors": colors, "speed": num("speed"), "density": num("density"),
            "text": text, "status": bool(d.get("status", True))}


def folder(themes_dir: Path) -> Path:
    return themes_dir / "savers"


def list_savers(themes_dir: Path) -> list[dict]:
    out = [dict(b, builtin=True) for b in BUILTIN]
    d = folder(themes_dir)
    for f in sorted(d.glob("*.json")) if d.is_dir() else []:
        try:
            s = validate(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
        out.append({**s, "id": "custom:" + f.stem, "builtin": False})
    return out


def save(themes_dir: Path, s: dict) -> str:
    d = folder(themes_dir)
    d.mkdir(parents=True, exist_ok=True)
    base = slug(s["name"]) or "saver"
    sid, n = base, 2
    while (d / f"{sid}.json").exists():
        sid, n = f"{base}-{n}", n + 1
    atomic_write_text(d / f"{sid}.json", json.dumps(s, indent=2))
    return "custom:" + sid


def delete(themes_dir: Path, sid: str) -> bool:
    if not sid.startswith("custom:"):
        return False
    f = folder(themes_dir) / f"{slug(sid[7:])}.json"
    try:
        f.unlink()
        return True
    except OSError:
        return False


def generate(client, model: str, description: str) -> dict:
    desc = " ".join(description.split())[:300]
    if not desc:
        raise ValueError("describe the screen saver first")
    msg = PROMPT.format(desc=desc, kinds="\n".join(f"- {k}: {v}" for k, v in KINDS.items()),
                        kind_ids=json.dumps(list(KINDS)))
    last = None
    for _ in range(3):
        r = client.chat([{"role": "user", "content": msg}], model=model, think=False)
        m = re.search(r"\{.*\}", r.text, re.S)
        if not m:
            last = "no JSON in reply"
            continue
        try:
            return validate(json.loads(m.group(0)))
        except ValueError as e:
            last = str(e)
    raise ValueError(f"the model didn't make a usable screen saver ({last}); try again")
