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
    code_lines = sum(_lines(f) for f in sb.output.rglob("*")
                     if f.suffix.lower() in {".py", ".cs", ".cpp", ".h", ".js", ".ts", ".ps1", ".gd"})

    st = settings.stats
    cloud = tin / 1e6 * st.cloud_price_in_per_mtok + tout / 1e6 * st.cloud_price_out_per_mtok
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
        "models": per_model,
    }


def _lines(p: Path) -> int:
    try:
        return sum(1 for ln in p.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip())
    except OSError:
        return 0
