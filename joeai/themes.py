"""Custom themes: <workspace>/Themes/<slug>.json, made by hand or by the local model.

A theme is only a handful of checked tokens (colors, a font from a safe list, CRT level),
never raw CSS, so a theme file can't break the window or load anything from the web.
Text must stay readable: low-contrast palettes are fixed up before saving.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .fsutil import atomic_write_text
from .mission import slug

FONTS = {"VT323": '"VT323", monospace', "Cascadia Mono": '"Cascadia Mono", Consolas, monospace',
         "Consolas": "Consolas, monospace", "Lucida Console": '"Lucida Console", monospace',
         "Courier New": '"Courier New", monospace', "Segoe UI": '"Segoe UI", system-ui, sans-serif'}
COLOR_KEYS = ("bg", "fg", "accent")
_HEX = re.compile(r"^#([0-9a-f]{3}|[0-9a-f]{6})$", re.I)

PROMPT = """Design a color theme for a retro-style terminal app from this description:
"{desc}"
Reply with ONLY one JSON object, no other text:
{{"name": "<2-3 word theme name>", "bg": "#rrggbb", "fg": "#rrggbb", "accent": "#rrggbb",
  "font": one of {fonts}, "crt": 0-3}}
bg is the background, fg the main text (must be easy to read on bg), accent for highlights.
crt is the scanline/glow strength (0 none, 3 heavy)."""


def _rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _hex(rgb) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c))):02x}" for c in rgb)


def _lum(h: str) -> float:
    def ch(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = _rgb(h)
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _toward(h: str, target: tuple[int, int, int], t: float) -> str:
    r = _rgb(h)
    return _hex(tuple(c + (x - c) * t for c, x in zip(r, target)))


def validate(d: dict) -> dict:
    """Clean a theme dict; raises ValueError if it can't be used."""
    if not isinstance(d, dict):
        raise ValueError("theme must be a JSON object")
    out = {"name": str(d.get("name") or "Custom")[:40].strip() or "Custom"}
    for k in COLOR_KEYS:
        v = str(d.get(k, "")).strip()
        if not _HEX.match(v):
            raise ValueError(f"'{k}' must be a color like #1a2b3c")
        out[k] = _hex(_rgb(v))
    font = str(d.get("font", "VT323"))
    out["font"] = font if font in FONTS else "VT323"
    try:
        out["crt"] = max(0, min(3, int(d.get("crt", 1))))
    except (TypeError, ValueError):
        out["crt"] = 1
    # Keep text readable: push fg away from bg until contrast >= 7 (accent >= 4.5).
    dark_bg = _lum(out["bg"]) < 0.4
    target = (255, 255, 255) if dark_bg else (0, 0, 0)
    for key, need in (("fg", 7.0), ("accent", 4.5)):
        t = 0.0
        while contrast(out[key], out["bg"]) < need and t < 1:
            t += 0.1
            out[key] = _toward(out[key], target, t)
    return out


def css_vars(t: dict) -> dict:
    """The CSS custom properties the UI sets for a theme."""
    r, g, b = _rgb(t["fg"])
    return {"--ph": t["fg"], "--ph-dim": f"rgba({r},{g},{b},.5)", "--ph-faint": f"rgba({r},{g},{b},.12)",
            "--bg": t["bg"], "--glow": f"rgba({r},{g},{b},.45)", "--accent": t["accent"],
            "--font": FONTS[t["font"]]}


def list_themes(folder: Path) -> list[dict]:
    out = []
    if folder.is_dir():
        for p in sorted(folder.glob("*.json")):
            try:
                t = validate(json.loads(p.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
            out.append({"id": p.stem, **t, "vars": css_vars(t)})
    return out


def save(folder: Path, t: dict) -> str:
    t = validate(t)
    base = slug(t["name"]) or "custom"
    sid, n = base, 2
    while (folder / f"{sid}.json").exists():
        sid, n = f"{base}-{n}", n + 1
    atomic_write_text(folder / f"{sid}.json", json.dumps(t, indent=1))
    return sid


def generate(client, model: str, description: str) -> dict:
    """Ask the local model for a palette; returns a validated theme dict."""
    desc = " ".join(description.split())[:300]
    if not desc:
        raise ValueError("describe the theme first")
    msg = PROMPT.format(desc=desc, fonts=json.dumps(list(FONTS)))
    last = None
    for _ in range(3):
        r = client.chat([{"role": "user", "content": msg}], model=model)
        m = re.search(r"\{.*\}", r.text, re.S)
        if not m:
            last = "no JSON in reply"
            continue
        try:
            return validate(json.loads(m.group(0)))
        except ValueError as e:
            last = str(e)
    raise ValueError(f"the model didn't make a usable theme ({last}); try again")
