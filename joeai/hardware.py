"""Hardware readings: the graphics card and system memory. No extra packages.

gpu() describes the best graphics card on this computer:
  NVIDIA          nvidia-smi (name, temperature, load, memory, power, fan)
  AMD on Linux    the amdgpu driver's files in /sys (name, temperature, load, memory)
  AMD / Intel on Windows   the display driver's registry entry (name, memory; no live readings)
  Intel on Linux  name only
  Apple Silicon   the chip name; graphics share the main memory ("unified")
Live readings (temp_c, util_pct, ...) are None when the card doesn't report them, so nothing
(like the cool-down pause) assumes NVIDIA. gpu() is cheap to call often: NVIDIA results are
cached for a couple of seconds, the rest is looked up once.
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

_FIELDS = ("name", "temperature.gpu", "utilization.gpu", "memory.used", "memory.total",
           "power.draw", "fan.speed")
_cache: dict = {"t": 0.0, "v": None, "static": "unset"}
_lock = threading.Lock()
CACHE_S = 2.0
MIN_DEDICATED_MB = 1536          # less than this is a built-in (shared) chip, not a real card
APPLE_GPU_SHARE = 0.66           # macOS lets the graphics use about two thirds of the memory

VENDORS = {"0x10de": "nvidia", "0x1002": "amd", "0x8086": "intel"}


def _num(s: str):
    s = s.strip()
    try:
        return float(s) if "." in s else int(s)
    except ValueError:
        return None                      # "[N/A]" etc.


def _card(name: str, vendor: str, total_mb=None, **live) -> dict:
    d = {"name": name, "vendor": vendor, "unified": False, "temp_c": None, "util_pct": None,
         "vram_used_mb": None, "vram_total_mb": total_mb, "power_w": None, "fan_pct": None}
    d.update(live)
    return d


# --------------------------------------------------------------------------- NVIDIA
def _nvidia() -> dict | None:
    smi = shutil.which("nvidia-smi")
    if not smi:
        return None
    try:
        out = subprocess.run(
            [smi, "--query-gpu=" + ",".join(_FIELDS), "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        cells = out.stdout.strip().splitlines()[0].split(",")
    except (OSError, IndexError, subprocess.SubprocessError):
        return None
    if len(cells) != len(_FIELDS):
        return None
    return _card(cells[0].strip(), "nvidia", _num(cells[4]), temp_c=_num(cells[1]),
                 util_pct=_num(cells[2]), vram_used_mb=_num(cells[3]), power_w=_num(cells[5]),
                 fan_pct=_num(cells[6]))


# --------------------------------------------------------------------------- Linux (/sys)
def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _linux_name(dev: Path, vendor: str) -> str:
    """A readable card name from lspci when it's there, else a plain one."""
    slot = dev.resolve().name                      # e.g. 0000:03:00.0
    lspci = shutil.which("lspci")
    if lspci:
        try:
            out = subprocess.run([lspci, "-s", slot], capture_output=True, text=True, timeout=3).stdout
            m = re.search(r"(?:VGA compatible controller|Display controller|3D controller):\s*(.+)", out)
            if m:
                name = re.sub(r"\s*\(rev [0-9a-f]+\)\s*$", "", m.group(1).strip())
                b = re.findall(r"\[([^\]]+)\]", name)          # "... Navi 31 [Radeon RX 7900 XTX]"
                return ("AMD " + b[-1]) if vendor == "amd" and b else name
        except (OSError, subprocess.SubprocessError):
            pass
    return {"amd": "AMD graphics", "intel": "Intel graphics"}.get(vendor, "Graphics card")


def linux_cards(root: Path = Path("/sys/class/drm")) -> list[dict]:
    """AMD and Intel cards the Linux driver lists (NVIDIA comes from nvidia-smi)."""
    cards = []
    try:
        entries = sorted(root.glob("card[0-9]*"))
    except OSError:
        return cards
    for c in entries:
        if "-" in c.name:                          # card0-HDMI-A-1 etc. are outputs
            continue
        dev = c / "device"
        vendor = VENDORS.get(_read(dev / "vendor").lower())
        if vendor not in ("amd", "intel"):
            continue
        total = _num(_read(dev / "mem_info_vram_total")) if vendor == "amd" else None
        cards.append({"dev": dev, "vendor": vendor,
                      "total_mb": round(total / 1024 / 1024) if total else None})
    return cards


def _amd_live(dev: Path) -> dict:
    used = _num(_read(dev / "mem_info_vram_used"))
    temp = None
    for h in sorted((dev / "hwmon").glob("hwmon*")) if (dev / "hwmon").exists() else []:
        t = _num(_read(h / "temp1_input"))
        if t is not None:
            temp = round(t / 1000)
            break
    return {"vram_used_mb": round(used / 1024 / 1024) if used is not None else None,
            "util_pct": _num(_read(dev / "gpu_busy_percent")), "temp_c": temp}


def _linux() -> dict | None:
    cards = linux_cards()
    if not cards:
        return None
    best = max(cards, key=lambda c: (c["vendor"] == "amd", c["total_mb"] or 0))
    name = _linux_name(best["dev"], best["vendor"])
    total = best["total_mb"]
    if total is not None and total < MIN_DEDICATED_MB:
        total = None                               # an APU's small carve-out, not real card memory
    return _card(name, best["vendor"], total, _dev=str(best["dev"]))


# --------------------------------------------------------------------------- Windows
DISPLAY_CLASS = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"


def windows_cards() -> list[dict]:
    """Display adapters from the registry: name and dedicated memory (64-bit, so cards over
    4 GB read right, unlike WMI's AdapterRAM)."""
    try:
        import winreg
    except ImportError:
        return []
    out = []
    try:
        cls = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, DISPLAY_CLASS)
    except OSError:
        return []
    i = 0
    while True:
        try:
            sub = winreg.EnumKey(cls, i)
        except OSError:
            break
        i += 1
        if not sub.isdigit():
            continue
        try:
            k = winreg.OpenKey(cls, sub)
        except OSError:
            continue

        def val(n):
            try:
                return winreg.QueryValueEx(k, n)[0]
            except OSError:
                return None
        name = val("DriverDesc") or ""
        mem = val("HardwareInformation.qwMemorySize") or val("HardwareInformation.MemorySize")
        if isinstance(mem, (bytes, bytearray)):
            mem = int.from_bytes(mem[:8], "little")
        out.append({"name": str(name), "total_mb": round(mem / 1024 / 1024) if isinstance(mem, int) and mem else None})
    return out


def vendor_of(name: str) -> str:
    n = name.lower()
    if "nvidia" in n or "geforce" in n or "quadro" in n or "rtx" in n:
        return "nvidia"
    if "amd" in n or "radeon" in n or "ati " in n:
        return "amd"
    if "intel" in n or " arc" in n:
        return "intel"
    if "apple" in n:
        return "apple"
    return "other"


def _windows() -> dict | None:
    cards = [c for c in windows_cards() if c["name"] and "basic" not in c["name"].lower()
             and "remote" not in c["name"].lower() and "virtual" not in c["name"].lower()]
    if not cards:
        return None
    best = max(cards, key=lambda c: c["total_mb"] or 0)
    total = best["total_mb"]
    if total is not None and total < MIN_DEDICATED_MB:
        total = None                               # built-in chip: shares the main memory
    return _card(best["name"], vendor_of(best["name"]), total)


# --------------------------------------------------------------------------- Mac
def _mac() -> dict | None:
    if platform.machine() != "arm64":
        return None                                # Intel Macs: too slow for local models to matter
    name = "Apple Silicon"
    try:
        out = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"],
                             capture_output=True, text=True, timeout=3).stdout.strip()
        if out:
            name = out
    except (OSError, subprocess.SubprocessError):
        pass
    from .system import ram_total_gb
    share = round(ram_total_gb() * 1024 * APPLE_GPU_SHARE)
    d = _card(name, "apple", share or None)
    d["unified"] = True
    return d


# --------------------------------------------------------------------------- public
def _static() -> dict | None:
    """The non-NVIDIA card, looked up once (it doesn't change while Joe runs)."""
    if _cache["static"] == "unset":
        try:
            if sys.platform == "win32":
                v = _windows()
            elif sys.platform == "darwin":
                v = _mac()
            else:
                v = _linux()
        except Exception:                          # noqa: BLE001 (never break Joe over a reading)
            v = None
        _cache["static"] = v
    return _cache["static"]


def gpu() -> dict | None:
    """The best graphics card: name, vendor (nvidia|amd|intel|apple|other), unified (shares
    main memory), vram_total_mb, and live readings when the card gives them (else None):
    temp_c, util_pct, vram_used_mb, power_w, fan_pct. None = no usable card found."""
    with _lock:
        if time.monotonic() - _cache["t"] < CACHE_S:
            return _cache["v"]
        _cache["t"] = time.monotonic()
        val = _nvidia()
        if val is None:
            s = _static()
            if s is not None:
                val = {k: v for k, v in s.items() if not k.startswith("_")}
                if s.get("_dev"):
                    val.update(_amd_live(Path(s["_dev"])) if s["vendor"] == "amd" else {})
                if val["vendor"] == "nvidia":
                    val["vendor"] = "nvidia-no-smi"       # card found but its tools are missing
        _cache["v"] = val
        return val


def reset_cache() -> None:
    with _lock:
        _cache.update(t=0.0, v=None, static="unset")


def gpu_temperature_c() -> int | None:
    g = gpu()
    return g["temp_c"] if g else None


def vram_total_gb() -> float:
    """Memory the graphics can use for models (0 when there's no usable card)."""
    g = gpu()
    return round((g["vram_total_mb"] or 0) / 1024, 1) if g else 0.0


def vendor() -> str:
    g = gpu()
    return g["vendor"] if g else "none"


def is_nvidia() -> bool:
    return vendor() == "nvidia"


def gpu_advice(g: dict | None, os_name: str = "") -> str:
    """One honest paragraph about what this graphics setup means for Joe ('' for NVIDIA)."""
    os_name = os_name or {"win32": "windows", "darwin": "mac"}.get(sys.platform, "linux")
    if g is None:
        return ("No graphics card Joe can use was found. Writing still works on the processor, "
                "just much slower (pick a small writing model). Pictures and video need a card.")
    v = g.get("vendor")
    if v == "nvidia":
        return ""
    if v == "nvidia-no-smi":
        return ("An NVIDIA card was found, but its driver tools (nvidia-smi) weren't. Install or "
                "update the NVIDIA driver so Joe can see its memory and temperature.")
    if v == "apple":
        return ("Apple Silicon: Ollama uses the graphics for writing, and the memory is shared, so "
                "bigger models fit than on most cards. Pictures work in ComfyUI but are several "
                "times slower than on NVIDIA; video is very slow. Joe can't read the chip's "
                "temperature, so the cool-down pause is off.")
    if v == "amd":
        tail = ("ComfyUI on Windows with AMD is shaky: ComfyUI Desktop doesn't support AMD cards, "
                "so pictures need a separate AMD setup and may not work. "
                if os_name == "windows" else
                "Pictures in ComfyUI need its AMD (ROCm) setup and are slower than on NVIDIA; video is slow. ")
        temp = ("Joe can read this card's temperature, so the cool-down pause works."
                if g.get("temp_c") is not None else
                "Joe can't read this card's temperature, so the cool-down pause is off.")
        return ("AMD graphics: Ollama runs writing on many recent Radeon cards (RX 6000 and newer); "
                "older ones fall back to the processor. " + tail + temp)
    if v == "intel":
        return ("Intel graphics: Ollama mostly runs on the processor here, so writing is slower "
                "(pick a small model). Pictures and video aren't practical. Joe can't read the "
                "temperature, so the cool-down pause is off.")
    return ("This graphics card isn't one Joe knows. Writing works (maybe on the processor); "
            "pictures and video may not.")


def ram_total_gb() -> float:
    from .system import ram_total_gb as _ram
    return _ram()


# --------------------------------------------------------------------------- CPU load
# Shown when hovering the GPU readout. Measured from the system's own counters between two
# readings (no extra programs, no install), so the first reading after start is None.
_cpu_last: dict = {"busy": None, "total": None, "t": 0.0, "pct": None}


def _cpu_counters() -> tuple[float, float] | None:
    """(busy, total) time counters since boot, or None."""
    try:
        if sys.platform == "win32":
            import ctypes

            class FT(ctypes.Structure):
                _fields_ = [("lo", ctypes.c_uint32), ("hi", ctypes.c_uint32)]

            idle, kern, user = FT(), FT(), FT()
            if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern),  # type: ignore[attr-defined]
                                                         ctypes.byref(user)):
                return None
            v = lambda f: (f.hi << 32) | f.lo  # noqa: E731
            total = v(kern) + v(user)               # kernel time includes idle time
            return float(total - v(idle)), float(total)
        if sys.platform.startswith("linux"):
            with open("/proc/stat", encoding="ascii") as f:
                nums = [float(x) for x in f.readline().split()[1:]]
            idle = nums[3] + (nums[4] if len(nums) > 4 else 0)
            return sum(nums) - idle, sum(nums)
    except (OSError, ValueError, AttributeError):
        return None
    return None


def cpu_pct() -> int | None:
    """Whole-PC CPU load in percent (0-100), averaged since the last call (at most every 2 s)."""
    now = time.monotonic()
    if now - _cpu_last["t"] < 2 and _cpu_last["pct"] is not None:
        return _cpu_last["pct"]
    if sys.platform == "darwin":
        try:
            out = subprocess.run(["ps", "-A", "-o", "%cpu"], capture_output=True, text=True, timeout=5).stdout
            pct = sum(float(x) for x in out.split()[1:] if re.match(r"^[\d.]+$", x)) / (os.cpu_count() or 1)
            _cpu_last.update(t=now, pct=max(0, min(100, round(pct))))
            return _cpu_last["pct"]
        except (OSError, subprocess.SubprocessError, ValueError):
            return None
    c = _cpu_counters()
    if not c:
        return None
    busy, total = c
    pct = None
    if _cpu_last["total"] is not None and total > _cpu_last["total"]:
        pct = max(0, min(100, round(100 * (busy - _cpu_last["busy"]) / (total - _cpu_last["total"]))))
    _cpu_last.update(busy=busy, total=total, t=now, pct=pct if pct is not None else _cpu_last["pct"])
    return _cpu_last["pct"]
