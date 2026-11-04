"""System check ("doctor"): what's installed, what's running, which models fit this PC.

Nothing is installed or downloaded without the user saying yes: the UI asks first and
only then calls install()/pull_ollama_model()/download_image_model() with approved=True.
Installs use winget (built into Windows 10/11) with the publishers' official packages;
without winget we open the official download page instead.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import threading
import urllib.request
import webbrowser
from pathlib import Path
from typing import Callable

from . import comfy as comfy_mod
from . import hardware
from .config import Settings
from .http import HttpError, request_json
from .services import ServiceManager, find_ollama_exe

Log = Callable[[str], None]

TOOLS = {
    "ollama": {"winget": "Ollama.Ollama", "page": "https://ollama.com/download",
               "label": "Ollama (runs the text models)"},
    "comfyui": {"winget": "Comfy.ComfyUI-Desktop", "page": "https://www.comfy.org/download",
                "label": "ComfyUI Desktop (makes images and video)"},
    "ffmpeg": {"winget": "Gyan.FFmpeg", "page": "https://ffmpeg.org/download.html",
               "label": "FFmpeg (turns frames into MP4 video)"},
}

# Ollama text models by VRAM (GB). Sizes are the default q4 downloads.
OLLAMA_PICKS = [
    (22, "qwen3:32b", 20.0),
    (10, "qwen3:14b", 9.3),
    (6.5, "qwen3:8b", 5.2),
    (3.5, "qwen3:4b", 2.6),
    (0, "qwen3:1.7b", 1.4),
]
NOT_WRITERS = re.compile(r"embed|bge|minilm|nomic|rerank|whisper|llava|moondream|-vision|clip|vl:|-vl", re.I)

# One known-good image model to offer when none are installed (official Stability AI release,
# CreativeML Open RAIL++-M license; ~6.9 GB).
STARTER_IMAGE_MODEL = {
    "name": "sd_xl_base_1.0.safetensors",
    "url": "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors",
    "size_gb": 6.9, "license": "CreativeML Open RAIL++-M",
}


def winget() -> str | None:
    return shutil.which("winget") if sys.platform == "win32" else None


def ffmpeg_exe(configured: str = "") -> str | None:
    from .finder import ffmpeg_exe as _f
    return _f(configured)


# --------------------------------------------------------------------------- ollama models
def ollama_models(sm: ServiceManager) -> list[dict]:
    try:
        r = request_json("GET", f"{sm.ollama.base}/api/tags", timeout=5)
    except HttpError:
        return []
    out = []
    for m in r.get("models", []):
        d = m.get("details", {}) or {}
        out.append({"name": m["name"], "size_gb": round(m.get("size", 0) / 2**30, 1),
                    "params": d.get("parameter_size", ""), "family": d.get("family", ""),
                    "writer": not NOT_WRITERS.search(m["name"])})
    return out


def _params_b(p: str) -> float:
    m = re.match(r"([\d.]+)\s*([BM])", p or "", re.I)
    if not m:
        return 0.0
    return float(m.group(1)) / (1000 if m.group(2).upper() == "M" else 1)


def best_ollama_model(models: list[dict], vram_gb: float) -> str | None:
    """Biggest installed writing model that fits in VRAM with room for context."""
    writers = [m for m in models if m["writer"]]
    if not writers:
        return None
    budget = (vram_gb or 8) - 1.5
    fits = [m for m in writers if m["size_gb"] <= budget] or [min(writers, key=lambda m: m["size_gb"])]
    return max(fits, key=lambda m: (_params_b(m["params"]), m["size_gb"]))["name"]


def smaller_text_model(sm: ServiceManager, current: str) -> str | None:
    """Writing quality Low: the next smaller installed writing model than `current`."""
    models = [m for m in ollama_models(sm) if m["writer"]]
    cur = next((m for m in models if m["name"] in (current, f"{current}:latest")), None)
    if not cur:
        return None
    key = lambda m: (_params_b(m["params"]), m["size_gb"])   # noqa: E731
    smaller = [m for m in models if key(m) < key(cur) and _params_b(m["params"]) >= 1]
    return max(smaller, key=key)["name"] if smaller else None


def recommended_download(vram_gb: float) -> dict:
    for need, name, gb in OLLAMA_PICKS:
        if (vram_gb or 0) >= need:
            return {"name": name, "size_gb": gb}
    return {"name": OLLAMA_PICKS[-1][1], "size_gb": OLLAMA_PICKS[-1][2]}


def resolve_text_model(settings: Settings, sm: ServiceManager, log: Log) -> str:
    """The configured model if installed; otherwise the best installed fit."""
    want = settings.ollama.text_model
    models = ollama_models(sm)
    names = {m["name"] for m in models}
    if want and (want in names or f"{want}:latest" in names):
        return want
    pick = best_ollama_model(models, hardware.vram_total_gb())
    if pick:
        log(f"Using {pick}, the best installed model for this PC." if not want else
            f"Model '{want}' isn't installed; using best fit '{pick}' instead.")
        return pick
    return want or recommended_download(hardware.vram_total_gb())["name"]


# --------------------------------------------------------------------------- comfy models
def comfy_models_dir(settings: Settings) -> Path | None:
    """Setup's Models folder if it exists, else the models folder of whatever ComfyUI is found."""
    from .finder import find_comfy
    c = settings.comfy
    inst = find_comfy(c.start_command, c.start_dir, c.models_dir)
    return inst.models_dir if inst else None


def image_models(settings: Settings) -> list[comfy_mod.ImageModel]:
    return comfy_mod.scan_models(comfy_models_dir(settings))


# --------------------------------------------------------------------------- report
def check(settings: Settings, sm: ServiceManager) -> dict:
    g = hardware.gpu()
    vram = hardware.vram_total_gb()
    oll_exe = find_ollama_exe(settings.ollama.exe)
    oll_up = sm.ollama_up()
    omodels = ollama_models(sm) if oll_up else []
    comfy_exe = sm.comfy_exe()
    comfy_up = sm.comfy_up()
    imodels = image_models(settings)
    best_text = best_ollama_model(omodels, vram)
    best_img = comfy_mod.best_image_model(imodels, vram, "image")
    best_vid = comfy_mod.best_image_model(imodels, vram, "video")
    text_ok = not settings.ollama.text_model or settings.ollama.text_model in {m["name"] for m in omodels}
    issues = []
    if not oll_exe and not oll_up:
        issues.append({"id": "install-ollama", "text": "Ollama is not installed. It runs the text models.",
                       "action": "install", "tool": "ollama"})
    elif not oll_up:
        issues.append({"id": "start-ollama", "text": "Ollama is installed but not running.",
                       "action": "start", "tool": "ollama"})
    elif not [m for m in omodels if m["writer"]]:
        rec = recommended_download(vram)
        issues.append({"id": "pull-model", "text": f"No text model installed. Best fit for this PC: "
                       f"{rec['name']} ({rec['size_gb']} GB download).",
                       "action": "pull", "model": rec["name"]})
    elif not text_ok and best_text:
        issues.append({"id": "use-model", "text": f"Setup model '{settings.ollama.text_model}' isn't "
                       f"installed. Best installed fit: {best_text}.", "action": "use", "model": best_text})
    if not comfy_exe and not comfy_up:
        issues.append({"id": "install-comfyui", "text": "ComfyUI is not installed (only needed for "
                       "image/video tasks).", "action": "install", "tool": "comfyui", "optional": True})
    elif (comfy_exe or comfy_up) and not imodels and comfy_models_dir(settings):
        issues.append({"id": "get-image-model", "text": f"No image model found. Offer: "
                       f"{STARTER_IMAGE_MODEL['name']} ({STARTER_IMAGE_MODEL['size_gb']} GB, "
                       f"{STARTER_IMAGE_MODEL['license']}).", "action": "download-image-model",
                       "optional": True})
    mdir = comfy_models_dir(settings)
    if (comfy_exe or comfy_up) and mdir and g and vram >= 8 and comfy_mod.wan_missing(mdir):
        w = comfy_mod.WAN_VIDEO
        issues.append({"id": "get-video-model", "text": f"No built-in video model. Offer: {w['label']} "
                       f"(about {w['size_gb']:.0f} GB, {w['license']}). Makes TYPE: video tasks work "
                       "without a workflow file (about 5-second clips).",
                       "action": "download-video-model", "optional": True})
    if (comfy_exe or comfy_up) and mdir and not comfy_mod.wan_missing(mdir) \
            and not comfy_mod.wan_turbo_installed(mdir):
        t = comfy_mod.WAN_TURBO
        issues.append({"id": "get-video-turbo", "text": f"Faster video: the {t['label']} (under 1 GB, "
                       f"{t['license']}) makes a video in 4 steps instead of 20, several times faster. "
                       "Used for Low and Medium video quality (Setup > Quality); High keeps the full model.",
                       "action": "download-video-turbo", "optional": True})
    from . import addons as addons_mod
    if oll_up and omodels:
        from .attach import vision_model
        if not vision_model(omodels):
            vm = "qwen2.5vl:7b" if vram >= 10 else "qwen2.5vl:3b"
            issues.append({"id": "pull-vision", "text": f"No vision model (only needed so Joe can look at pictures "
                           f"you drop into Talk). Best fit: {vm}.", "action": "pull", "model": vm,
                           "optional": True})
    if not addons_mod.voice_ready():
        issues.append({"id": "install-voice", "text": "Joe's voice isn't set up (talk with F6, hear replies "
                       "and reports). About 500 MB: uv, a private Python 3.12, faster-whisper and Kokoro, "
                       "all running on the CPU.", "action": "install-voice", "optional": True})
    elif not addons_mod.clone_ready() and g and vram >= addons_mod.CLONE_MIN_VRAM_GB:
        issues.append({"id": "install-clone", "text": "Voice copy isn't set up (optional: make Joe sound like "
                       "YOU, on this PC only). About 3 GB, uses the graphics card when he talks during the day.",
                       "action": "install-clone", "optional": True})
    if not addons_mod.pandoc_exe(settings.pandoc):
        issues.append({"id": "install-pandoc", "text": "Pandoc isn't installed (only needed for EXPORT: "
                       "finished Word, PDF and EPUB copies).", "action": "install-pandoc", "optional": True})
    if not ffmpeg_exe(settings.comfy.ffmpeg):
        issues.append({"id": "install-ffmpeg", "text": "FFmpeg not found (only needed to turn "
                       "frames/GIFs into MP4).", "action": "install", "tool": "ffmpeg", "optional": True})
    return {
        "gpu": g, "vram_gb": vram, "ram_gb": hardware.ram_total_gb(), "winget": bool(winget()),
        "ollama": {"installed": bool(oll_exe) or oll_up, "running": oll_up, "exe": oll_exe or "",
                   "models": omodels, "best": best_text,
                   "configured": settings.ollama.text_model or f"auto ({best_text or 'none yet'})",
                   "recommended": recommended_download(vram)},
        "comfyui": {"installed": bool(comfy_exe) or comfy_up,
                    "running": comfy_up, "url": sm.comfy_base, "exe": str(comfy_exe or ""),
                    "found": (sm.comfy_install().as_dict() if sm.comfy_install() else None),
                    "models_dir": str(comfy_models_dir(settings) or ""),
                    "models": [{"name": m.name, "family": m.family, "size_gb": m.size_gb,
                                "kind": m.kind} for m in imodels],
                    "best_image": best_img.name if best_img else None,
                    "best_video": best_vid.name if best_vid else None},
        "ffmpeg": ffmpeg_exe(settings.comfy.ffmpeg) or "",
        "voice": addons_mod.voice_ready(), "pandoc": addons_mod.pandoc_exe(settings.pandoc) or "",
        "issues": issues,
    }


# --------------------------------------------------------------------------- actions
def install(tool: str, log: Log, approved: bool = False) -> bool:
    """Install a tool with winget (the user already said yes in the UI)."""
    if not approved:
        raise PermissionError("install needs the user's approval")
    t = TOOLS.get(tool)
    if not t:
        log(f"Unknown tool: {tool}")
        return False
    wg = winget()
    if not wg:
        log(f"winget not available; opening the {tool} download page instead.")
        webbrowser.open(t["page"])
        return False
    log(f"Installing {t['label']} with winget (Windows may ask for permission)...")
    cmd = [wg, "install", "-e", "--id", t["winget"], "--accept-package-agreements",
           "--accept-source-agreements", "--disable-interactivity"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=1800,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as e:
        log(f"winget failed to run: {e}")
        return False
    tail = (p.stdout or p.stderr or "").strip().splitlines()[-3:]
    for ln in tail:
        log("  winget: " + ln.strip()[:160])
    ok = p.returncode == 0 or "already installed" in (p.stdout or "").lower()
    log(f"{t['label']}: {'installed' if ok else 'install failed (code ' + str(p.returncode) + ')'}")
    if ok and tool == "comfyui":
        log("ComfyUI Desktop runs a one-time setup the first time it opens. Finish that, then "
            "Joe can start it by itself.")
    return ok


def pull_ollama_model(sm: ServiceManager, name: str, log: Log, approved: bool = False,
                      progress: Callable[[float], None] | None = None) -> bool:
    if not approved:
        raise PermissionError("download needs the user's approval")
    if not sm.ensure_ollama():
        log("Ollama isn't running, can't download a model.")
        return False
    log(f"Downloading model {name} (this can take a while)...")
    req = urllib.request.Request(f"{sm.ollama.base}/api/pull", method="POST",
                                 data=json.dumps({"model": name, "stream": True}).encode(),
                                 headers={"Content-Type": "application/json"})
    last = -10.0
    try:
        with urllib.request.urlopen(req, timeout=3600) as r:
            for raw in r:
                try:
                    ev = json.loads(raw)
                except ValueError:
                    continue
                if ev.get("error"):
                    log(f"  pull error: {ev['error']}")
                    return False
                if ev.get("total"):
                    pct = 100 * ev.get("completed", 0) / ev["total"]
                    if progress:
                        progress(pct)
                    if pct - last >= 10:
                        log(f"  {name}: {pct:.0f}%")
                        last = pct
                if ev.get("status") == "success":
                    log(f"Model {name} is ready.")
                    return True
    except OSError as e:
        log(f"  download failed: {e}")
        return False
    return True


def _download(url: str, dest: Path, log: Log, progress: Callable[[float], None] | None = None,
              done_bytes: int = 0, all_bytes: int = 0) -> bool:
    """Download to dest via a .part file (resumes nothing; a failed file is removed)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    try:
        with urllib.request.urlopen(url, timeout=60) as r, open(part, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            got, last = 0, -10.0
            while chunk := r.read(1 << 20):
                f.write(chunk)
                got += len(chunk)
                if total:
                    pct = 100 * got / total
                    if progress:
                        progress(100 * (done_bytes + got) / all_bytes if all_bytes else pct)
                    if pct - last >= 10:
                        log(f"  {dest.name}: {pct:.0f}%")
                        last = pct
        part.replace(dest)
        return True
    except OSError as e:
        log(f"  download failed: {e}")
        try:
            part.unlink()
        except OSError:
            pass
        return False


def download_video_model(settings: Settings, log: Log, approved: bool = False,
                         progress: Callable[[float], None] | None = None) -> bool:
    """Wan 2.2 5B: three files into ComfyUI's models folders."""
    if not approved:
        raise PermissionError("download needs the user's approval")
    mdir = comfy_models_dir(settings)
    if not mdir:
        log("Can't find ComfyUI's models folder. Set it in Setup (F10).")
        return False
    w = comfy_mod.WAN_VIDEO
    missing = comfy_mod.wan_missing(mdir)
    if not missing:
        log(f"{w['label']} is already installed.")
        return True
    log(f"Downloading the video model {w['label']} ({w['license']}), about {w['size_gb']:.0f} GB "
        "in 3 files. This takes a while.")
    sizes = {"diffusion_models": 10.0, "text_encoders": 6.3, "vae": 1.3}     # GB, for one progress bar
    all_b = sum(sizes[f[0]] for f in missing) * 2**30
    done = 0.0
    for folder, name, url in missing:
        log(f"  {name} -> models\\{folder}")
        if not _download(url, mdir / folder / name, log, progress, int(done), int(all_b)):
            return False
        done += sizes[folder] * 2**30
    log(f"{w['label']} is ready. Restart ComfyUI so it sees the new files, then TYPE: video tasks work.")
    return True


def download_video_turbo(settings: Settings, log: Log, approved: bool = False,
                         progress: Callable[[float], None] | None = None) -> bool:
    """The Turbo add-on (a LoRA) for Wan 2.2 5B, into ComfyUI's models\\loras."""
    if not approved:
        raise PermissionError("download needs the user's approval")
    mdir = comfy_models_dir(settings)
    if not mdir:
        log("Can't find ComfyUI's models folder. Set it in Setup (F10).")
        return False
    t = comfy_mod.WAN_TURBO
    if comfy_mod.wan_turbo_installed(mdir):
        log(f"The {t['label']} is already installed.")
        return True
    folder, name, url = t["file"]
    log(f"Downloading the {t['label']} ({t['license']}).")
    if not _download(url, mdir / folder / name, log, progress, 0, int(t["size_gb"] * 2**30)):
        return False
    log(f"The {t['label']} is ready. Restart ComfyUI so it sees the new file.")
    return True


def download_image_model(settings: Settings, log: Log, approved: bool = False,
                         progress: Callable[[float], None] | None = None) -> bool:
    if not approved:
        raise PermissionError("download needs the user's approval")
    mdir = comfy_models_dir(settings)
    if not mdir:
        log("Can't find ComfyUI's models folder. Set it in Setup (F10).")
        return False
    m = STARTER_IMAGE_MODEL
    dest = mdir / "checkpoints" / m["name"]
    if dest.exists():
        log(f"{m['name']} is already there.")
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    log(f"Downloading {m['name']} ({m['size_gb']} GB, {m['license']})...")
    try:
        with urllib.request.urlopen(m["url"], timeout=60) as r, open(part, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            got, last = 0, -10.0
            while chunk := r.read(1 << 20):
                f.write(chunk)
                got += len(chunk)
                if total:
                    pct = 100 * got / total
                    if progress:
                        progress(pct)
                    if pct - last >= 10:
                        log(f"  {pct:.0f}%")
                        last = pct
        part.replace(dest)
    except OSError as e:
        log(f"  download failed: {e}")
        try:
            part.unlink()
        except OSError:
            pass
        return False
    log(f"{m['name']} saved to {dest.parent}")
    return True


def run_in_thread(fn, *a, **kw) -> threading.Thread:
    t = threading.Thread(target=fn, args=a, kwargs=kw, daemon=True, name="joe-doctor")
    t.start()
    return t
