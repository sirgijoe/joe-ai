"""Hardware readings: GPU (nvidia-smi) and system memory. No extra packages.

gpu() is cheap to call often: results are cached for a couple of seconds.
"""
from __future__ import annotations

import shutil
import subprocess
import threading
import time

_FIELDS = ("name", "temperature.gpu", "utilization.gpu", "memory.used", "memory.total",
           "power.draw", "fan.speed")
_cache: dict = {"t": 0.0, "v": None}
_lock = threading.Lock()
CACHE_S = 2.0


def _num(s: str):
    s = s.strip()
    try:
        return float(s) if "." in s else int(s)
    except ValueError:
        return None                      # "[N/A]" etc.


def gpu() -> dict | None:
    """First NVIDIA GPU: name, temp_c, util_pct, vram_used_mb, vram_total_mb, power_w, fan_pct."""
    with _lock:
        if time.monotonic() - _cache["t"] < CACHE_S:
            return _cache["v"]
        _cache["t"] = time.monotonic()
        smi = shutil.which("nvidia-smi")
        val = None
        if smi:
            try:
                out = subprocess.run(
                    [smi, "--query-gpu=" + ",".join(_FIELDS), "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=5,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                cells = out.stdout.strip().splitlines()[0].split(",")
                if len(cells) == len(_FIELDS):
                    val = {"name": cells[0].strip(), "temp_c": _num(cells[1]),
                           "util_pct": _num(cells[2]), "vram_used_mb": _num(cells[3]),
                           "vram_total_mb": _num(cells[4]), "power_w": _num(cells[5]),
                           "fan_pct": _num(cells[6])}
            except (OSError, IndexError, subprocess.SubprocessError):
                val = None
        _cache["v"] = val
        return val


def gpu_temperature_c() -> int | None:
    g = gpu()
    return g["temp_c"] if g else None


def vram_total_gb() -> float:
    g = gpu()
    return round((g["vram_total_mb"] or 0) / 1024, 1) if g else 0.0


def ram_total_gb() -> float:
    from .system import ram_total_gb as _ram
    return _ram()