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


def video_gif(ffmpeg: str, src: Path, dest: Path, width: int = 480, fps: int = 12) -> Path | None:
    """A looping GIF of a clip (made with its own color palette, so it stays sharp and small)."""
    vf = (f"fps={fps},scale={width}:-2:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];"
          f"[b][p]paletteuse=dither=bayer:bayer_scale=4")
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-i", str(src), "-filter_complex", vf, "-loop", "0", str(dest)]
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


# --------------------------------------------------------------------------- masks and blending
# Used by the picture tools so the AI only changes what it should: "fix one spot" keeps
# everything outside the marked area, "keep faces" puts the real faces back, "make it bigger"
# keeps the original picture untouched in the middle. White in a mask = take the new picture.
def size_of(ffmpeg: str, p: Path) -> tuple[int, int] | None:
    import re as _re
    try:
        r = subprocess.run([ffmpeg, "-hide_banner", "-i", str(p)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
                           creationflags=_flags())
    except (OSError, subprocess.SubprocessError):
        return None
    m = _re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", r.stderr or "")
    if not m:
        return None
    w, h = int(m.group(1)), int(m.group(2))
    rot = _re.search(r"(?:rotation of|rotate\s*:)\s*(-?\d+)", r.stderr or "")
    if rot and abs(int(rot.group(1))) % 180 == 90:     # phone video filmed upright: frames come out turned
        w, h = h, w
    return w, h


def _flags() -> int:
    from .system import no_window_flags
    return no_window_flags()


def box_mask(ffmpeg: str, size: tuple[int, int], boxes: list[tuple[float, float, float, float]],
             dest: Path, grow: float = 0.25) -> Path | None:
    """A black picture with white boxes (x, y, w, h as 0-1 fractions), each grown by `grow`."""
    w, h = size
    draws = []
    for x, y, bw, bh in boxes:
        gx, gy = bw * grow, bh * grow
        x0, y0 = max(0, int((x - gx) * w)), max(0, int((y - gy) * h))
        x1, y1 = min(w, int((x + bw + gx) * w)), min(h, int((y + bh + gy) * h))
        if x1 > x0 and y1 > y0:
            draws.append(f"drawbox=x={x0}:y={y0}:w={x1 - x0}:h={y1 - y0}:color=white:t=fill")
    if not draws:
        return None
    cmd = [ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", f"color=black:s={w}x{h}", "-vf",
           ",".join(draws) + ",format=gray", "-frames:v", "1", str(dest)]
    return dest if _run(cmd) and dest.exists() else None


def rect_mask(ffmpeg: str, size: tuple[int, int], inner: tuple[int, int, int, int], dest: Path) -> Path | None:
    """White everywhere except a black rectangle (x, y, w, h in pixels): the part to keep."""
    w, h = size
    x, y, iw, ih = inner
    cmd = [ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", f"color=white:s={w}x{h}", "-vf",
           f"drawbox=x={x}:y={y}:w={iw}:h={ih}:color=black:t=fill,format=gray", "-frames:v", "1", str(dest)]
    return dest if _run(cmd) and dest.exists() else None


def blend(ffmpeg: str, base: Path, new: Path, mask: Path, dest: Path, feather: float = 0.0) -> Path | None:
    """base where the mask is black, new where it's white, soft edges (feather in pixels; 0 =
    about 1% of the picture). Everything is sized to `base`."""
    size = size_of(ffmpeg, base)
    if not size:
        return None
    w, h = size
    f = feather or max(2.0, min(w, h) / 100)
    fc = (f"[1]scale={w}:{h}:flags=lanczos,format=gbrp[n];[0]format=gbrp[b];"
          f"[2]scale={w}:{h},format=gray,gblur=sigma={f:.1f},format=gbrp[m];[b][n][m]maskedmerge,format=rgb24")
    cmd = [ffmpeg, "-y", "-v", "error", "-noautorotate", "-i", str(base), "-i", str(new), "-i", str(mask),
           "-filter_complex", fc, "-frames:v", "1", str(dest)]
    return dest if _run(cmd) and dest.exists() else None


def pad_for_outpaint(ffmpeg: str, src: Path, dest: Path, shape: str) -> tuple[Path, tuple[int, int, int, int]] | None:
    """A bigger canvas with the picture in the middle and its edge colours smeared around it (a
    head start for the editor). Returns (file, where the original sits: x, y, w, h)."""
    size = size_of(ffmpeg, src)
    if not size:
        return None
    w, h = size
    if shape == "taller":
        W, H = w, int(h * 1.5)
    elif shape == "square":
        W = H = max(w, h)
    elif shape == "around":
        W, H = int(w * 1.5), int(h * 1.5)
    else:                                           # wider
        W, H = int(w * 1.5), h
    W, H = W // 2 * 2, H // 2 * 2
    x, y = (W - w) // 2, (H - h) // 2
    # The new space starts as the picture's own edge colours smeared outwards and blurred. (A
    # blurred stretch of the WHOLE picture put a ghost copy of the subject there, which the editor
    # painted as a second dragon: QC 2026-11-09.)
    r, b = W - w - x, H - h - y
    fc = (f"[0]format=gbrp,pad={W}:{H}:{x}:{y},fillborders=left={x}:right={r}:top={y}:bottom={b}:mode=smear,"
          f"boxblur=luma_radius=40:luma_power=2:chroma_radius=40:chroma_power=2[bg];"
          f"[bg][0]overlay={x}:{y},format=rgb24")
    cmd = [ffmpeg, "-y", "-v", "error", "-noautorotate", "-i", str(src), "-filter_complex", fc,
           "-frames:v", "1", str(dest)]
    return (dest, (x, y, w, h)) if _run(cmd) and dest.exists() else None


def border_is_flat(ffmpeg: str, img: Path, inner: tuple[int, int, int, int], size: tuple[int, int]) -> bool:
    """True when the new space around the kept picture is one flat colour (the editor left it
    blank, e.g. a white frame), so Joe reports a failure instead of 'done'."""
    W, H = size
    x, y, w, h = inner
    gw, gh = 64, 64
    try:
        r = subprocess.run([ffmpeg, "-v", "error", "-noautorotate", "-i", str(img), "-vf",
                            f"scale={gw}:{gh}:flags=area,format=gray", "-frames:v", "1", "-f", "rawvideo", "-"],
                           capture_output=True, timeout=120, creationflags=_flags())
    except (OSError, subprocess.SubprocessError):
        return False
    px = r.stdout
    if len(px) < gw * gh:
        return False
    x0, x1 = x * gw / W, (x + w) * gw / W
    y0, y1 = y * gh / H, (y + h) * gh / H
    def stats(vals):
        mean = sum(vals) / len(vals)
        return mean, (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
    new = [px[j * gw + i] for j in range(gh) for i in range(gw)
           if not (x0 - 1 <= i <= x1 and y0 - 1 <= j <= y1)]           # only the new space
    if len(new) < 20:
        return False
    mean, sd = stats(new)
    if sd >= 4.0:
        return False
    # A plain backdrop that really continues (a product on white) is flat too: that's fine.
    band = [px[j * gw + i] for j in range(gh) for i in range(gw)
            if x0 + 1 <= i <= x1 - 2 and y0 + 1 <= j <= y1 - 2
            and min(i - x0, x1 - i, j - y0, y1 - j) < 4]
    if band:
        bmean, bsd = stats(band)
        if bsd < 8.0 and abs(bmean - mean) < 12:
            return False
    return True


def outline_spot(ffmpeg: str, src: Path, mask: Path, dest: Path) -> Path | None:
    """The picture with the marked spot tinted red, so the editor can see where to work."""
    size = size_of(ffmpeg, src)
    if not size:
        return None
    w, h = size
    fc = (f"[0]format=gbrp[b];color=red:s={w}x{h},format=gbrp[r];[1]scale={w}:{h},format=gray,"
          f"geq=lum='p(X,Y)*0.55',format=gbrp[m];[b][r][m]maskedmerge,format=rgb24")
    cmd = [ffmpeg, "-y", "-v", "error", "-noautorotate", "-i", str(src), "-i", str(mask), "-filter_complex", fc,
           "-frames:v", "1", str(dest)]
    return dest if _run(cmd) and dest.exists() else None


def side_by_side(ffmpeg: str, pictures: list[Path], dest: Path, height: int = 768) -> Path | None:
    """Pictures in one row, all the same height (a character sheet)."""
    if not pictures:
        return None
    ins = []
    for p in pictures:
        ins += ["-i", str(p)]
    fc = "".join(f"[{i}]scale=-2:{height},setsar=1[v{i}];" for i in range(len(pictures)))
    fc += "".join(f"[v{i}]" for i in range(len(pictures))) + f"hstack=inputs={len(pictures)}" \
        if len(pictures) > 1 else "[v0]null"
    cmd = [ffmpeg, "-y", "-v", "error", *ins, "-filter_complex", fc, "-frames:v", "1", str(dest)]
    return dest if _run(cmd) and dest.exists() else None
