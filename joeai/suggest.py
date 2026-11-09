"""Better-model suggestions: when Joe sees a model he doesn't have would do a task better AND it
suits this PC's graphics memory, he says so in the run log (once per run) and System check puts
that offer first, marked RECOMMENDED, with the reason. Nothing is ever downloaded without the
person pressing the button.

Keys: "pack:<id>" (picturetools.PACKS, e.g. pack:flux2), "video-turbo", "style:<style id>".
Kept in <Joe>/.joe/suggestions.json: {key: {"why": text, "times": n, "last": iso date}}.
"""
from __future__ import annotations

import json
from datetime import datetime

FILE = "suggestions.json"

# Graphics memory (GB) a model needs to run well on this PC's card. Under it: never suggested at
# run time, and System check says it may be slow or not run.
NEEDS_GB = {"pack:bg": 2, "pack:upscale": 2, "pack:edit": 12, "pack:music": 6, "pack:sfx": 4, "pack:flux2": 8,
            "pack:sketch": 8, "pack:illusion": 8, "pack:video-restyle": 12, "pack:3d": 8, "video-turbo": 8}
BASE_GB = {"sdxl": 8, "sd15": 4, "flux": 12}


def needs_gb(key: str, base: str = "") -> float:
    if key.startswith("style:"):
        return BASE_GB.get(base or "sdxl", 8)
    return float(NEEDS_GB.get(key, 0))


def vram() -> float:
    try:
        from .hardware import vram_total_gb
        return vram_total_gb()
    except Exception:                       # noqa: BLE001
        return 0.0


def fits(key: str, gb: float | None = None, base: str = "") -> bool:
    """Suits this PC: enough graphics memory (unknown card = no)."""
    gb = vram() if gb is None else gb
    return gb > 0 and gb >= needs_gb(key, base)


def _read(sb) -> dict:
    try:
        d = json.loads((sb.meta / FILE).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def note(engine, key: str, label: str, why: str, where: str = "Setup > System check", base: str = "") -> bool:
    """A model would have done this better. Logged once per run (only when it suits this PC) and
    remembered for System check. Returns True when it was suggested."""
    gb = vram()
    if not fits(key, gb, base):
        return False
    sb = engine.sb
    data = _read(sb)
    e = data.get(key) or {}
    data[key] = {"why": why, "times": int(e.get("times", 0)) + 1,
                 "last": datetime.now().isoformat(timespec="seconds")}
    try:
        sb.meta.mkdir(parents=True, exist_ok=True)
        from .fsutil import atomic_write_text
        atomic_write_text(sb.meta / FILE, json.dumps(data, indent=1))
    except OSError:
        pass
    said = getattr(engine, "_suggested", None)
    if said is None:
        said = engine._suggested = set()
    if key not in said:
        said.add(key)
        engine.log(f"  Tip: {label} would do this better ({why}). It suits this PC's {gb:g} GB graphics "
                   f"card; {where} offers it.")
    return True


def pending(sb) -> dict:
    return _read(sb)


def forget(sb, key: str) -> None:
    """Installed (or turned down): stop recommending it."""
    data = _read(sb)
    if data.pop(key, None) is not None:
        try:
            from .fsutil import atomic_write_text
            atomic_write_text(sb.meta / FILE, json.dumps(data, indent=1))
        except OSError:
            pass


def mark(issues: list[dict], sb, gb: float | None = None) -> list[dict]:
    """System check: offers Joe has a reason for go first, marked RECOMMENDED with the reason;
    offers too big for this card say so."""
    gb = vram() if gb is None else gb
    wants = pending(sb)
    out = []
    for it in issues:
        key = ("pack:" + it["pack"] if it.get("pack") else "video-turbo" if it.get("id") == "get-video-turbo"
               else "style:" + it["style"] if it.get("style") else "")
        if not key:
            out.append(it)
            continue
        base = it.get("base", "")
        need = needs_gb(key, base)
        if key in wants and fits(key, gb, base):
            it = dict(it, recommended=True, text="RECOMMENDED for what you make (" + wants[key]["why"] + "): "
                      + it["text"])
            out.append(it)
            continue
        if gb and need and gb < need:
            it = dict(it, text=it["text"] + f" Needs about {need:g} GB of graphics memory; this PC has "
                      f"{gb:g} GB, so it may be very slow or not run.")
        out.append(it)
    # problems stay on top; then the recommended offers; then the other offers (order kept)
    rank = {id(it): (0 if not it.get("optional") else 1 if it.get("recommended") else 2) for it in out}
    return sorted(out, key=lambda it: rank[id(it)])
