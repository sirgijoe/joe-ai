"""Lifetime stats from Output/.joe (runs.jsonl + job state files)."""
from __future__ import annotations

import json
from pathlib import Path

from .config import Settings
from .sandbox import Sandbox


def collect(settings: Settings, sb: Sandbox) -> dict:
    meta = sb.meta
    calls = ok = tin = tout = 0
    secs = 0.0
    nights: set[str] = set()
    per_model: dict[str, int] = {}
    runs = meta / "runs.jsonl"
    if runs.exists():
        for line in runs.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            calls += 1
            if r.get("ok"):
                ok += 1
                tin += r.get("tokens_in", 0)
                tout += r.get("tokens_out", 0)
                secs += r.get("seconds", 0.0)
                per_model[r.get("model", "?")] = per_model.get(r.get("model", "?"), 0) + 1
            nights.add(str(r.get("ts", ""))[:10])

    items = words = tasks = retries = parts = 0
    for p in (meta / "state").glob("*.json") if (meta / "state").exists() else []:
        try:
            s = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        tasks += 1
        items += s.get("items", 0)
        words += s.get("words", 0)
        retries += s.get("retries", 0)
        parts += s.get("parts_done", 0)

    files = sum(1 for f in sb.output.rglob("*")
                if f.is_file() and ".joe" not in f.parts and not f.name.startswith("_"))
    pictures, video_s = media_made(sb.output)
    code_lines = sum(_lines(f) for f in sb.output.rglob("*")
                     if f.suffix.lower() in {".py", ".cs", ".cpp", ".h", ".js", ".ts", ".ps1", ".gd"})

    st = settings.stats
    cloud_text = tin / 1e6 * st.cloud_price_in_per_mtok + tout / 1e6 * st.cloud_price_out_per_mtok
    cloud_pics = pictures * st.cloud_price_image
    cloud_video = video_s * st.cloud_price_video_second
    cloud = cloud_text + cloud_pics + cloud_video
    watts = st.gpu_watts
    if not watts:                            # automatic: this GPU's power reading, else a typical card
        from .hardware import gpu
        g = gpu()
        watts = (g or {}).get("power_w") or 200
        watts = max(watts, 120)              # idle readings understate a working night
    power = secs / 3600 * watts / 1000 * st.kwh_price
    return {
        "words": words, "items": items, "files": files, "code_lines": code_lines,
        "tasks": tasks, "parts": parts, "retries": retries,
        "calls": calls, "calls_ok": ok, "tokens_in": tin, "tokens_out": tout,
        "model_hours": round(secs / 3600, 2), "nights": len(nights - {""}),
        "cloud_cost_avoided": round(cloud, 2), "electricity_cost": round(power, 2),
        "cloud_cost_parts": {"text": round(cloud_text, 2), "pictures": round(cloud_pics, 2),
                             "video": round(cloud_video, 2)},
        "pictures": pictures, "video_seconds": round(video_s),
        "models": per_model,
    }


def media_made(output: Path) -> tuple[int, float]:
    """Pictures and seconds of video Joe made, from each folder's _media.json (one entry per
    finished file). Coloring '_example' copies aren't counted twice. Video length: the entry's
    own seconds when it has them, else 5 s."""
    pics, secs = 0, 0.0
    for mj in output.rglob("_media.json"):
        if ".joe" in mj.parts:
            continue
        try:
            d = json.loads(mj.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        items = d.get("items") if isinstance(d, dict) else None
        for name, r in (items.items() if isinstance(items, dict) else []):
            r = r if isinstance(r, dict) else {}
            if "_example." in name:
                continue
            low = name.lower()
            if low.endswith((".mp4", ".webm", ".mov", ".gif")):
                try:
                    secs += float(r.get("seconds") or 5)
                except (TypeError, ValueError):
                    secs += 5
            elif low.endswith((".png", ".jpg", ".jpeg", ".webp")):
                pics += 1
    return pics, secs


def _lines(p: Path) -> int:
    try:
        return sum(1 for ln in p.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip())
    except OSError:
        return 0


# --------------------------------------------------------------------------- learned speeds
DEFAULT_SPEEDS = {"part": 25.0, "image": 30.0, "video": 240.0,
                  "transcribe": 0.8,      # transcribe: seconds of work per second of sound
                  "read-aloud": 0.5,      # read aloud: seconds of work per second of speech
                  "vision": 20.0}         # one look at a picture
_speed_cache: dict = {}


def speeds(sb: Sandbox, recent: int = 300) -> dict:
    """Seconds per text part, picture and video clip on THIS PC, from the latest runs
    (and the speed test). Falls back to rough defaults until there are a few samples."""
    runs = sb.meta / "runs.jsonl"
    try:
        st = runs.stat()
    except OSError:
        return dict(DEFAULT_SPEEDS, learned=[])
    key = (str(runs), st.st_mtime_ns, st.st_size)
    if _speed_cache.get("key") == key:
        return _speed_cache["val"]
    with open(runs, "rb") as f:                      # only the tail: the file can get long
        f.seek(max(0, st.st_size - 400_000))
        tail = f.read().decode("utf-8", "replace").splitlines()[1:] if st.st_size > 400_000 else \
            f.read().decode("utf-8", "replace").splitlines()
    got: dict[str, list[float]] = {"write": [], "speedtest": [], "image": [], "video": [],
                                   "transcribe": [], "read-aloud": [], "vision": []}
    for line in tail[-recent * 3:]:
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        k = r.get("kind")
        if r.get("ok") and k in ("transcribe", "read-aloud") and r.get("seconds") and r.get("audio_seconds"):
            got[k].append(float(r["seconds"]) / max(1.0, float(r["audio_seconds"])))
        elif r.get("ok") and k in ("photo-listing", "read-scans", "sort-photos") and r.get("seconds"):
            got["vision"].append(float(r["seconds"]))
        elif r.get("ok") and k in got and r.get("seconds"):
            got[k].append(float(r["seconds"]))
    out = dict(DEFAULT_SPEEDS, learned=[])
    text = got["write"][-recent:] or got["speedtest"][-5:]
    if len(text) >= 3 or got["speedtest"]:
        out["part"] = round(_median(text) * 1.15, 1)       # + the odd retry / expansion
        out["learned"].append("part")
    for k in ("image", "video", "transcribe", "read-aloud", "vision"):
        if len(got[k]) >= 2:
            out[k] = round(_median(got[k][-recent:]), 1)
            out["learned"].append(k)
    _speed_cache.update(key=key, val=out)
    return out


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2
