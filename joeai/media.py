"""Generated media bookkeeping: per-folder manifest, review marks, FFmpeg to MP4.

Each folder of AI images/videos gets a `_media.json`:
    {"ai_generated": true, "note": "...", "items": {"001_kiln_1.png": {prompt, seed, model,
     workflow, created, review: "keep"|"reject"|"star"|""}}}
Review marks for files Joe didn't make are stored there too (ai_generated unknown).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from .fsutil import atomic_write_text

MANIFEST = "_media.json"
AI_NOTE = ("AI-GENERATED. These images/videos were made by an AI model. Do not present them as "
           "photos of real products, real places or real people.")
REVIEWS = ("keep", "reject", "star", "")
STILL = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
ANIMATED = {".gif", ".webp"}
VIDEO = {".mp4", ".webm", ".mov", ".mkv"}


def load(folder: Path) -> dict:
    p = folder / MANIFEST
    if p.exists():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                d.setdefault("items", {})
                return d
        except (OSError, ValueError):
            pass
    return {"items": {}}


def save(folder: Path, data: dict) -> None:
    atomic_write_text(folder / MANIFEST, json.dumps(data, indent=1, ensure_ascii=False))


def record(folder: Path, filename: str, meta: dict, job: str = "") -> None:
    d = load(folder)
    d["ai_generated"] = True
    d["note"] = AI_NOTE
    if job:
        d["job"] = job
    meta = {**meta, "ai_generated": True,
            "created": datetime.now().isoformat(timespec="seconds"), "review": ""}
    d["items"][filename] = meta
    save(folder, d)


def set_review(folder: Path, filename: str, mark: str) -> str:
    if mark not in REVIEWS:
        raise ValueError("bad review mark")
    d = load(folder)
    item = d["items"].setdefault(filename, {})
    item["review"] = "" if item.get("review") == mark else mark      # pressing again clears
    save(folder, d)
    return item["review"]


def info(folder: Path, filename: str) -> dict:
    d = load(folder)
    item = d["items"].get(filename)
    if item is None:
        return {}
    return {**item, "ai_generated": item.get("ai_generated", d.get("ai_generated", False))}


def reviews(folder: Path) -> dict[str, str]:
    d = load(folder)
    return {k: v.get("review", "") for k, v in d["items"].items() if v.get("review")}


# --------------------------------------------------------------------------- ffmpeg
def _run(cmd: list[str]) -> bool:
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=1800,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return p.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


# Coloring pages (models often add color or shading to a "line art" page anyway):
#  - already mostly white with dark lines: every gray turns pure black or white (strips stray tint);
#  - a filled-in picture: its outlines are found (color-aware), drawn black on white, thickened.
LINES_VF = "format=gray,lut=c0='if(lt(val,140),0,255)'"
EDGES_VF = ("format=gbrp,gblur=sigma=1.2,edgedetect=low=0.06:high=0.18,format=gray,"
            "lut=c0='if(gt(val,30),0,255)',erosion")


def white_share(ffmpeg: str, src: Path) -> float:
    """How much of the picture is near-white (0-1), from a 64x64 gray copy."""
    try:
        p = subprocess.run([ffmpeg, "-v", "error", "-i", str(src), "-vf", "format=gray,scale=64:64",
                            "-frames:v", "1", "-f", "rawvideo", "-"], capture_output=True, timeout=120,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return 0.0
    px = p.stdout or b""
    return sum(1 for v in px if v > 200) / len(px) if px else 0.0


# Kids' pages: blur more first so only the big shapes get outlines (no speckle and grass noise).
EDGES_SIMPLE_VF = ("format=gbrp,gblur=sigma=3.5,edgedetect=low=0.12:high=0.30,format=gray,"
                   "lut=c0='if(gt(val,30),0,255)',erosion,erosion")


def color_share(ffmpeg: str, src: Path) -> tuple[float, float]:
    """(near-white share 0-1, average color strength 0-255) from a 256x256 copy. At 64x64 thin
    lines blur into gray, so a finished line drawing looked 'filled in' (big test 2026-11-05:
    the outline step then drew lines around every line: far too heavy)."""
    try:
        p = subprocess.run([ffmpeg, "-v", "error", "-i", str(src), "-vf", "scale=256:256,format=rgb24",
                            "-frames:v", "1", "-f", "rawvideo", "-"], capture_output=True, timeout=120,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return 0.0, 255.0
    px = p.stdout or b""
    n = len(px) // 3
    if not n:
        return 0.0, 255.0
    white = sat = 0
    for i in range(0, n * 3, 3):
        r, g, b = px[i], px[i + 1], px[i + 2]
        if r * 299 + g * 587 + b * 114 > 200_000:
            white += 1
        sat += max(r, g, b) - min(r, g, b)
    return white / n, sat / n


def is_line_drawing(ffmpeg: str, src: Path) -> bool:
    """Already black lines on white (keep its lines, only strip gray/tint)."""
    white, sat = color_share(ffmpeg, src)
    return white >= 0.55 or (white >= 0.35 and sat < 12)


def line_art(ffmpeg: str, src: Path, dest: Path, simple: bool = False) -> bool:
    """Make a black-and-white coloring page from a picture with FFmpeg (simple: kids' pages)."""
    vf = LINES_VF if is_line_drawing(ffmpeg, src) else (EDGES_SIMPLE_VF if simple else EDGES_VF)
    return _run([ffmpeg, "-y", "-v", "error", "-i", str(src), "-vf", vf, "-frames:v", "1", str(dest)]) \
        and dest.exists()


def to_mp4(ffmpeg: str, src: Path, dest: Path | None = None, fps: int = 16) -> Path | None:
    """Animated GIF/WebP or another video -> H.264 MP4 that plays everywhere."""
    dest = dest or src.with_suffix(".mp4")
    if dest == src:
        dest = src.with_name(src.stem + "_h264.mp4")
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-i", str(src), "-movflags", "+faststart",
           "-pix_fmt", "yuv420p", "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-an", str(dest)]
    return dest if _run(cmd) and dest.exists() else None


# Black-and-white video look, applied by FFmpeg after Wan makes the clip in color: no color
# at all, a gentle contrast curve (deeper blacks, brighter highlights) and fine moving grain.
BW_VIDEO_VF = ("format=yuv420p,hue=s=0,curves=all='0/0.03 0.25/0.24 0.5/0.52 0.75/0.79 1/1',"
               "noise=c0s=6:c0f=t+u")
# A gentle S-curve: mids and highlights get a little more snap, the deepest shadows are lifted a
# touch so dark scenes keep their detail (dev112's increase_contrast crushed them to black).


def video_bw(ffmpeg: str, src: Path, dest: Path) -> Path | None:
    """Turn a color video into a black-and-white film look (sound, if any, is kept)."""
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-i", str(src), "-vf", BW_VIDEO_VF,
           "-movflags", "+faststart", "-pix_fmt", "yuv420p", "-c:v", "libx264",
           "-preset", "veryfast", "-crf", "18", "-c:a", "copy", str(dest)]
    return dest if _run(cmd) and dest.exists() else None


def frames_to_mp4(ffmpeg: str, frames: list[Path], dest: Path, fps: int = 16) -> Path | None:
    if not frames:
        return None
    with tempfile.TemporaryDirectory(prefix="nr_frames_") as td:
        for i, f in enumerate(frames):
            shutil.copyfile(f, Path(td) / f"f_{i:05d}{f.suffix.lower()}")
        pattern = str(Path(td) / f"f_%05d{frames[0].suffix.lower()}")
        cmd = [ffmpeg, "-y", "-loglevel", "error", "-framerate", str(fps), "-i", pattern,
               "-movflags", "+faststart", "-pix_fmt", "yuv420p",
               "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-c:v", "libx264",
               "-preset", "veryfast", "-crf", "20", str(dest)]
        return dest if _run(cmd) and dest.exists() else None
