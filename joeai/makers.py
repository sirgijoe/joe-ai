"""Batch 3 tools on new model families (dev123): sketch to picture and hidden-picture illusions
(ControlNet on the SDXL models Joe already uses), restyle a video (Wan 2.2 Fun Control 5B) and
picture to 3D model (Hunyuan3D 2.1, a .glb file).

Like the other ComfyUI tools, every graph uses only ComfyUI's own built-in nodes and follows
ComfyUI's official templates (video_wan2_2_5B_fun_control, 3d_hunyuan3d-v2.1). The models are
offered first with their size and license (picturetools.PACKS); nothing downloads by itself.
picturetools.run() does the ComfyUI round trips; this module plans the items, builds each
graph and finishes the files.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from . import comfy as comfy_mod

TOOLS = ("sketch-to-picture", "illusion-art", "restyle-video", "make-3d")
NO_INPUT_OK = ("illusion-art", "brainstorm")          # can make its own hidden pattern
SDXL_TOOLS = ("sketch-to-picture", "illusion-art")
VIDEO_EXT = (".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v")

# look -> (label, picture style id)
LOOKS = {"auto": ("Joe decides from your words", ""), "photo": ("Photo", "photo"),
         "illustration": ("Illustration", "illustration"), "anime": ("Anime", "anime"),
         "cartoon": ("Cartoon", "cartoon"), "painting": ("Painting", "painting"),
         "watercolor": ("Watercolor", "watercolor"), "render3d": ("3D render", "render3d"),
         "fantasy": ("Fantasy art", "fantasy"), "pixel": ("Pixel art", "pixel"),
         "coloring": ("Coloring page", "coloring")}
# sketch: how closely to follow the lines -> (ControlNet strength, stop at this share of the steps)
FOLLOW = {"close": (0.95, 0.9), "some": (0.75, 0.75), "loose": (0.55, 0.6)}
# illusion: how strongly the hidden picture shows -> (strength, stop share)
SHOW = {"hidden": (0.9, 0.8), "clear": (1.15, 0.9), "bold": (1.45, 1.0)}
# built-in hidden patterns (FFmpeg draws them; white shows as light, black as dark)
PATTERNS = {"spiral": ("Spiral", "255*gt(sin(7*atan2(Y-512,X-512)+hypot(X-512,Y-512)/20),0)"),
            "circles": ("Circles", "255*gt(sin(hypot(X-512,Y-512)/24),0)"),
            "checker": ("Checkerboard", "255*mod(floor(X/128)+floor(Y/128),2)"),
            "waves": ("Waves", "255*gt(sin(X/42+5*sin(Y/95)),0)"),
            "word": ("A word (write it as word: YOUR WORD)", ""),
            "picture": ("My picture (black and white shape or logo)", "")}
SEGMENT_S = 5                              # Wan makes about 5 seconds (121 frames at 24 a second)
SEGMENT_FRAMES = 121
VIDEO_FPS = 24


# --------------------------------------------------------------------------- small helpers
def _ffmpeg(engine) -> str | None:
    from .doctor import ffmpeg_exe
    return ffmpeg_exe(engine.s.comfy.ffmpeg)


def _flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _run(cmd: list[str], timeout: int = 1800) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, creationflags=_flags())
    except (OSError, subprocess.SubprocessError):
        return None


def _work(engine) -> Path:
    d = engine.sb.meta / "work"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _picks():
    try:
        from .upkeep import picks
        return picks()
    except Exception:                          # noqa: BLE001  (offline: built-in hints)
        return None


def style_for(job):
    """The picture style: OPTIONS look, else the task's STYLE, else a guess from its words."""
    from . import styles
    from .tools import option_value
    look = option_value(job, "look") or "auto"
    sid = LOOKS.get(look, ("", ""))[1]
    return styles.STYLES[sid] if sid else styles.pick(job)


def sdxl_model(engine, job) -> tuple[str, str]:
    """(checkpoint file name, '') of the best installed SDXL model for this job's style, or
    ('', why not). Setup > Workflows > Sketch and illusions can name one."""
    from . import styles, workflowprefs as wfp
    from .doctor import image_models
    models = [m for m in image_models(engine.s) if m.family == "sdxl" and m.folder == "checkpoints"]
    if not models:
        return "", ("needs an SDXL picture model (ControlNet works with SDXL). Setup (F10) > Models "
                    "offers one")
    want = wfp.get(engine.s, "controlnet").get("model", "")
    if want:
        hit = comfy_mod.best_image_model(models, 0, "image", want=want)
        if hit:
            return hit.name, ""
        engine.log(f"  Your Setup > Workflows model '{want}' isn't an installed SDXL model; Joe picks one.")
    style = style_for(job)
    suited = styles.choose_model(models, style.id, _picks()) if style.id != "general" else []
    m = comfy_mod.best_image_model(suited or models, 0, "image")
    return m.name, ""


def api_name(client, name: str) -> str:
    """The name ComfyUI uses for a checkpoint file (it may sit in a subfolder)."""
    try:
        names = client.checkpoints()
    except Exception:                          # noqa: BLE001
        names = []
    base = name.replace("\\", "/").split("/")[-1].lower()
    for n in names:
        if n.replace("\\", "/").split("/")[-1].lower() == base:
            return n
    return name


def mean_gray(ff: str, src: Path) -> float:
    """Average brightness 0-255 of a picture (from a 64x64 gray copy)."""
    try:
        p = subprocess.run([ff, "-v", "error", "-i", str(src), "-vf", "format=gray,scale=64:64",
                            "-frames:v", "1", "-f", "rawvideo", "-"], capture_output=True, timeout=120,
                           creationflags=_flags())
    except (OSError, subprocess.SubprocessError):
        return 255.0
    px = p.stdout or b""
    return sum(px) / len(px) if px else 255.0


def frame_count(ff: str, video: Path) -> int:
    r = _run([ff, "-hide_banner", "-i", str(video), "-map", "0:v:0", "-f", "null", "-"], timeout=900)
    found = re.findall(r"frame=\s*(\d+)", (r.stderr or "") if r else "")
    return int(found[-1]) if found else 0


def duration_s(ff: str, video: Path) -> float:
    r = _run([ff, "-hide_banner", "-i", str(video)], timeout=120)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", (r.stderr or "") if r else "")
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0


def safe_word(text: str) -> str:
    """A word FFmpeg can draw without escaping trouble (letters, digits, a few marks; 14 max)."""
    return re.sub(r"[^A-Za-z0-9 !?&#+-]", "", text or "").strip()[:14]


def word_from(extra: str) -> tuple[str, str]:
    """'a forest at dawn\\nword: JOE' (or the same on one line, as the Tools form sends it)
    -> ('a forest at dawn', 'JOE')."""
    word, keep = "", []
    for line in (extra or "").splitlines():
        m = re.search(r"(?:^|\s)(?:hidden\s+)?word\s*[:=]\s*(.+)$", line, re.I)
        if m and not word:
            word = safe_word(m.group(1))
            line = line[:m.start()]
        keep.append(line)
    return " ".join(" ".join(keep).split()).rstrip(" ,;."), word


def font_file() -> Path:
    return Path(__file__).parent / "ui" / "fonts" / "AtkinsonHyperlegible-Bold.ttf"


# A bold 5x7 block font for the hidden word when FFmpeg can't draw text itself (some FFmpeg builds
# have no drawtext/freetype). Blurred afterwards, the blocks read as soft, bold letters.
BLOCK_FONT = {
    "A": "01110 10001 10001 11111 10001 10001 10001", "B": "11110 10001 10001 11110 10001 10001 11110",
    "C": "01111 10000 10000 10000 10000 10000 01111", "D": "11110 10001 10001 10001 10001 10001 11110",
    "E": "11111 10000 10000 11110 10000 10000 11111", "F": "11111 10000 10000 11110 10000 10000 10000",
    "G": "01111 10000 10000 10111 10001 10001 01111", "H": "10001 10001 10001 11111 10001 10001 10001",
    "I": "11111 00100 00100 00100 00100 00100 11111", "J": "00111 00010 00010 00010 00010 10010 01100",
    "K": "10001 10010 10100 11000 10100 10010 10001", "L": "10000 10000 10000 10000 10000 10000 11111",
    "M": "10001 11011 10101 10101 10001 10001 10001", "N": "10001 11001 10101 10011 10001 10001 10001",
    "O": "01110 10001 10001 10001 10001 10001 01110", "P": "11110 10001 10001 11110 10000 10000 10000",
    "Q": "01110 10001 10001 10001 10101 10010 01101", "R": "11110 10001 10001 11110 10100 10010 10001",
    "S": "01111 10000 10000 01110 00001 00001 11110", "T": "11111 00100 00100 00100 00100 00100 00100",
    "U": "10001 10001 10001 10001 10001 10001 01110", "V": "10001 10001 10001 10001 10001 01010 00100",
    "W": "10001 10001 10001 10101 10101 10101 01010", "X": "10001 10001 01010 00100 01010 10001 10001",
    "Y": "10001 10001 01010 00100 00100 00100 00100", "Z": "11111 00001 00010 00100 01000 10000 11111",
    "0": "01110 10001 10011 10101 11001 10001 01110", "1": "00100 01100 00100 00100 00100 00100 01110",
    "2": "01110 10001 00001 00010 00100 01000 11111", "3": "11110 00001 00001 01110 00001 00001 11110",
    "4": "00010 00110 01010 10010 11111 00010 00010", "5": "11111 10000 11110 00001 00001 10001 01110",
    "6": "00110 01000 10000 11110 10001 10001 01110", "7": "11111 00001 00010 00100 01000 01000 01000",
    "8": "01110 10001 10001 01110 10001 10001 01110", "9": "01110 10001 10001 01111 00001 00010 01100",
    "!": "00100 00100 00100 00100 00100 00000 00100", "?": "01110 10001 00001 00010 00100 00000 00100",
    "&": "01100 10010 10100 01000 10101 10010 01101", "#": "01010 01010 11111 01010 11111 01010 01010",
    "+": "00000 00100 00100 11111 00100 00100 00000", "-": "00000 00000 00000 11111 00000 00000 00000",
    " ": "00000 00000 00000 00000 00000 00000 00000",
}


def block_word_pgm(word: str, size: int = 1024) -> bytes:
    """The word in BLOCK_FONT, white on black, centered, as a binary PGM (FFmpeg reads it anywhere)."""
    glyphs = [BLOCK_FONT.get(c, BLOCK_FONT["?"]).split() for c in word.upper()]
    cols = len(glyphs) * 6 - 1                        # 5 wide + 1 gap
    cell = max(4, min(int(size * 0.86 / cols), int(size * 0.5 / 7)))
    left, top = (size - cols * cell) // 2, (size - 7 * cell) // 2
    img = bytearray(size * size)
    for gi, rows in enumerate(glyphs):
        for ry, row in enumerate(rows):
            for rx, bit in enumerate(row):
                if bit != "1":
                    continue
                pad = cell // 4                       # a bit wider than the cell: bold strokes
                x0 = max(0, left + (gi * 6 + rx) * cell - pad)
                x1 = min(size, left + (gi * 6 + rx + 1) * cell + pad)
                for y in range(max(0, top + ry * cell - pad), min(size, top + (ry + 1) * cell + pad)):
                    img[y * size + x0:y * size + x1] = b"\xff" * (x1 - x0)
    return f"P5 {size} {size} 255\n".encode() + bytes(img)


def make_pattern(ff: str, kind: str, dest: Path, word: str = "", why: list | None = None) -> Path | None:
    """A 1024x1024 black-and-white pattern for the illusion (softened edges blend better).
    A word is drawn with FFmpeg's drawtext and Joe's font; if that FFmpeg can't (no drawtext in the
    build, or the font path trips it up on Windows), Joe's own block letters are used instead.
    FFmpeg's complaint goes into `why` for the log."""
    if kind == "word":
        word = safe_word(word)
        if not word:
            return None
        size = max(110, min(520, int(1700 / max(1, len(word)))))
        # FFmpeg's filter options split on ':' -> escape the Windows drive colon (C\:/...)
        font = font_file().as_posix().replace(":", "\\:")
        vf = (f"drawtext=fontfile='{font}':text='{word}':fontcolor=white:fontsize={size}:"
              "x=(w-text_w)/2:y=(h-text_h)/2,gblur=sigma=5,format=gray")
        r = _run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=1024x1024", "-vf", vf,
                  "-frames:v", "1", str(dest)], timeout=120)
        if r is not None and r.returncode == 0 and dest.exists():
            return dest
        if why is not None:
            why.append(((r.stderr or "").strip().splitlines() or ["FFmpeg didn't start"])[-1][:200]
                       if r is not None else "FFmpeg didn't start")
        pgm = dest.with_suffix(".pgm")
        pgm.write_bytes(block_word_pgm(word))
        r = _run([ff, "-y", "-v", "error", "-i", str(pgm), "-vf", "gblur=sigma=9,format=gray",
                  "-frames:v", "1", str(dest)], timeout=120)
        pgm.unlink(missing_ok=True)
        return dest if r is not None and r.returncode == 0 and dest.exists() else None
    expr = PATTERNS.get(kind, PATTERNS["spiral"])[1] or PATTERNS["spiral"][1]
    vf = f"format=gray,geq=lum='{expr}',gblur=sigma=5"
    r = _run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=1024x1024", "-vf", vf,
              "-frames:v", "1", str(dest)], timeout=120)
    return dest if r is not None and r.returncode == 0 and dest.exists() else None


def square_on_white(ff: str, src: Path, dest: Path) -> Path | None:
    """Pad a picture to a square on white (see-through parts turn white too), for 3D."""
    fc = ("[0]format=rgba,pad=w='max(iw,ih)':h='max(iw,ih)':x='(ow-iw)/2':y='(oh-ih)/2':color=white@0[p];"
          "color=white:s=16x16[c];[c][p]scale2ref[c2][p2];[c2][p2]overlay=format=auto,format=rgb24")
    r = _run([ff, "-y", "-v", "error", "-i", str(src), "-filter_complex", fc, "-frames:v", "1", str(dest)],
             timeout=300)
    return dest if r is not None and r.returncode == 0 and dest.exists() else None


def cut_segment(ff: str, src: Path, start: float, dest: Path, size: tuple[int, int]) -> Path | None:
    """One 5-second piece at 24 frames a second, filled and cropped to Wan's size, no sound."""
    w, h = size
    r = _run([ff, "-y", "-v", "error", "-ss", f"{start:.3f}", "-i", str(src), "-t", f"{SEGMENT_S + 0.1:.2f}",
              "-vf", f"fps={VIDEO_FPS},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1",
              "-frames:v", str(SEGMENT_FRAMES), "-an", "-pix_fmt", "yuv420p", "-c:v", "libx264",
              "-preset", "veryfast", "-crf", "16", str(dest)])
    return dest if r is not None and r.returncode == 0 and dest.exists() else None


def wan_length(frames: int) -> int:
    """Wan wants 4n+1 frames, never more than the piece has."""
    frames = min(frames, SEGMENT_FRAMES)
    return (frames - 1) // 4 * 4 + 1 if frames >= 5 else 0


def restyle_size(engine, w: int, h: int) -> tuple[int, int]:
    from . import quality
    from .picturetools import video_size
    size = video_size(w, h)
    gentle = getattr(engine.s.engine, "keep_pc_usable", False) or quality.level(engine.s, "video") != "high"
    if gentle and max(size) > 960:
        size = (960, 544) if size[0] > size[1] else (544, 960)
    return size


# --------------------------------------------------------------------------- graphs
def controlnet_graph(ckpt: str, image: str, prompt: str, negative: str, seed: int, controlnet: str,
                     strength: float, end: float, steps: int = 28, cfg: float = 6.0, invert: bool = False,
                     union_type: str = "", prefix: str = "Joe/tool") -> dict:
    """SDXL picture guided by a control picture (a sketch or a hidden pattern). The control
    picture is also encoded, only so the new picture gets its shape (denoise 1 = all new)."""
    g = {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["4", 1]}},
        "1": {"class_type": "LoadImage", "inputs": {"image": image}},
        "2": {"class_type": "ImageScaleToTotalPixels", "inputs": {
            "image": ["1", 0], "upscale_method": "lanczos", "megapixels": 1.0, "resolution_steps": 64}},
        "10": {"class_type": "ControlNetLoader", "inputs": {"control_net_name": controlnet}},
        "12": {"class_type": "ControlNetApplyAdvanced", "inputs": {
            "positive": ["6", 0], "negative": ["7", 0], "control_net": ["10", 0], "image": ["2", 0],
            "strength": strength, "start_percent": 0.0, "end_percent": end, "vae": ["4", 2]}},
        "13": {"class_type": "VAEEncode", "inputs": {"pixels": ["2", 0], "vae": ["4", 2]}},
        "5": {"class_type": "KSampler", "inputs": {
            "seed": seed, "steps": steps, "cfg": cfg, "sampler_name": "dpmpp_2m", "scheduler": "karras",
            "denoise": 1.0, "model": ["4", 0], "positive": ["12", 0], "negative": ["12", 1],
            "latent_image": ["13", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": prefix}},
    }
    if invert:                                 # dark lines on paper -> light lines on black
        g["3"] = {"class_type": "ImageInvert", "inputs": {"image": ["2", 0]}}
        g["12"]["inputs"]["image"] = ["3", 0]
    if union_type:
        g["11"] = {"class_type": "SetUnionControlNetType", "inputs": {"control_net": ["10", 0], "type": union_type}}
        g["12"]["inputs"]["control_net"] = ["11", 0]
    return g


def restyle_video_graph(video: str, prompt: str, negative: str, seed: int, width: int, height: int,
                        length: int, steps: int = 20, cfg: float = 5.0, edges: tuple[float, float] = (0.1, 0.4),
                        ref_image: str = "", prefix: str = "Joe/tool") -> dict:
    """ComfyUI's Wan 2.2 5B Fun Control template: the video's outlines (Canny, every frame) steer
    a new video made from the prompt, so the motion stays and the look changes."""
    from .picturetools import PACKS
    unet, clip, vae = (f[1] for f in PACKS["video-restyle"].files)
    g = {
        "37": {"class_type": "UNETLoader", "inputs": {"unet_name": unet, "weight_dtype": "default"}},
        "38": {"class_type": "CLIPLoader", "inputs": {"clip_name": clip, "type": "wan", "device": "default"}},
        "39": {"class_type": "VAELoader", "inputs": {"vae_name": vae}},
        "48": {"class_type": "ModelSamplingSD3", "inputs": {"shift": 8.0, "model": ["37", 0]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["38", 0]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["38", 0]}},
        "66": {"class_type": "LoadVideo", "inputs": {"file": video}},
        "67": {"class_type": "GetVideoComponents", "inputs": {"video": ["66", 0]}},
        "68": {"class_type": "Canny", "inputs": {"image": ["67", 0], "low_threshold": edges[0],
                                                 "high_threshold": edges[1]}},
        "60": {"class_type": "Wan22FunControlToVideo", "inputs": {
            "positive": ["6", 0], "negative": ["7", 0], "vae": ["39", 0], "width": width, "height": height,
            "length": length, "batch_size": 1, "control_video": ["68", 0]}},
        "3": {"class_type": "KSampler", "inputs": {
            "seed": seed, "steps": steps, "cfg": cfg, "sampler_name": "uni_pc", "scheduler": "simple",
            "denoise": 1.0, "model": ["48", 0], "positive": ["60", 0], "negative": ["60", 1],
            "latent_image": ["60", 2]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["39", 0]}},
        "57": {"class_type": "CreateVideo", "inputs": {"images": ["8", 0], "fps": float(VIDEO_FPS)}},
        "58": {"class_type": "SaveVideo", "inputs": {"video": ["57", 0], "filename_prefix": prefix,
                                                     "format": "auto", "codec": "auto"}},
    }
    if ref_image:
        g["70"] = {"class_type": "LoadImage", "inputs": {"image": ref_image}}
        g["60"]["inputs"]["ref_image"] = ["70", 0]
    return g


def model3d_graph(image: str, ckpt: str, seed: int, steps: int = 30, cfg: float = 5.0,
                  cut_out: bool = False, octree: int = 256, prefix: str = "Joe/tool") -> dict:
    """ComfyUI's Hunyuan3D 2.1 template (picture -> shape -> .glb). cut_out: BiRefNet takes the
    background away first and the object is put on plain white, which Hunyuan3D wants."""
    from .picturetools import PACKS
    g = {
        "1": {"class_type": "LoadImage", "inputs": {"image": image}},
        "2": {"class_type": "ImageScale", "inputs": {"image": ["1", 0], "upscale_method": "lanczos",
                                                     "width": 1024, "height": 1024, "crop": "center"}},
        "30": {"class_type": "ImageOnlyCheckpointLoader", "inputs": {"ckpt_name": ckpt}},
        "31": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["30", 0], "shift": 1.0}},
        "32": {"class_type": "CLIPVisionEncode", "inputs": {"clip_vision": ["30", 1], "image": ["2", 0],
                                                            "crop": "center"}},
        "33": {"class_type": "Hunyuan3Dv2Conditioning", "inputs": {"clip_vision_output": ["32", 0]}},
        "34": {"class_type": "EmptyLatentHunyuan3Dv2", "inputs": {"resolution": 4096, "batch_size": 1}},
        "35": {"class_type": "KSampler", "inputs": {
            "seed": seed, "steps": steps, "cfg": cfg, "sampler_name": "euler", "scheduler": "normal",
            "denoise": 1.0, "model": ["31", 0], "positive": ["33", 0], "negative": ["33", 1],
            "latent_image": ["34", 0]}},
        "36": {"class_type": "VAEDecodeHunyuan3D", "inputs": {"samples": ["35", 0], "vae": ["30", 2],
                                                              "num_chunks": 8000, "octree_resolution": octree}},
        "37": {"class_type": "VoxelToMesh", "inputs": {"voxel": ["36", 0], "algorithm": "surface net",
                                                       "threshold": 0.6}},
        "9": {"class_type": "SaveGLB", "inputs": {"mesh": ["37", 0], "filename_prefix": prefix}},
    }
    if cut_out:
        g["20"] = {"class_type": "LoadBackgroundRemovalModel", "inputs": {"bg_removal_name": PACKS["bg"].files[0][1]}}
        g["21"] = {"class_type": "RemoveBackground", "inputs": {"bg_removal_model": ["20", 0], "image": ["2", 0]}}
        g["22"] = {"class_type": "EmptyImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1,
                                                          "color": 0xFFFFFF}}
        g["23"] = {"class_type": "ImageCompositeMasked", "inputs": {
            "destination": ["22", 0], "source": ["2", 0], "x": 0, "y": 0, "resize_source": False,
            "mask": ["21", 0]}}
        g["32"]["inputs"]["image"] = ["23", 0]
    return g


# --------------------------------------------------------------------------- planning
def plan_items(engine, job, tid: str, files: list[Path]) -> tuple[list[dict], list[str], str]:
    """Inputs -> one dict per thing to make (src, stem, label, key and what the graph needs).
    ([], [], why) when it can't run."""
    from .mission import slug
    from .tools import option_value
    extra = (job.format or "").strip()
    ff = _ffmpeg(engine)
    items: list[dict] = []
    if tid in SDXL_TOOLS:
        ckpt, why = sdxl_model(engine, job)
        if not ckpt:
            return [], [], why
    if tid == "sketch-to-picture":
        what = extra or "a detailed, finished, colorful picture of what the drawing shows"
        kind = option_value(job, "lines") or "rough"
        for f in files:
            invert = (mean_gray(ff, f) > 127) if ff else True
            items.append({"maker": True, "src": f, "ckpt": ckpt, "stem": slug(f.stem) + "-finished",
                          "label": f.name, "key": f"sketch {f.name}", "invert": invert,
                          "union": "canny/lineart/anime_lineart/mlsd" if kind == "clean" else "hed/pidi/scribble/ted",
                          "prompt": what})
        if not extra:
            engine.log("  No words about the sketch: Joe asks for a finished, colorful picture of it. "
                       "Saying what it shows gives much better results.")
    elif tid == "illusion-art":
        scene, word = word_from(extra)
        scene = scene or "a sweeping fantasy landscape with mountains, forests, rivers and clouds, highly detailed"
        hidden = option_value(job, "hidden") or ("word" if word else ("picture" if files else "spiral"))
        sources: list[tuple[Path, str]] = []
        if hidden == "picture" or (files and hidden not in PATTERNS):
            sources = [(f, f.stem) for f in files]
            if not sources:
                return [], [], "add the picture to hide (a black-and-white shape, logo or word works best)"
        else:
            if not ff:
                return [], [], "needs FFmpeg to draw the hidden pattern (Setup > System check installs it)"
            if hidden == "word" and not word:
                return [], [], "write the hidden word on its own line, like: word: JOE"
            why: list = []
            pat = make_pattern(ff, hidden, _work(engine) / f"pattern-{hidden}-{slug(word) or 'x'}.png", word, why)
            if why:
                engine.log(f"  FFmpeg couldn't write the word with a font ({why[0]}); using Joe's block letters")
            if not pat:
                return [], [], "couldn't draw the hidden pattern with FFmpeg" + (f" ({why[0]})" if why else "")
            sources = [(pat, word or hidden)]
        count = int(option_value(job, "versions") or 2)
        for src, name in sources:
            for v in range(1, count + 1):
                items.append({"maker": True, "src": src, "ckpt": ckpt, "label": f"{name} {v}",
                              "stem": f"{slug(name)[:30] or 'illusion'}-illusion-{v}",
                              "key": f"illusion {name} {scene[:40]} {v}", "prompt": scene})
    elif tid == "restyle-video":
        if not ff:
            return [], [], "needs FFmpeg to cut the video (Setup > System check installs it)"
        from .tools import RESTYLES
        videos = [f for f in files if f.suffix.lower() in VIDEO_EXT]
        pics = [f for f in files if f.suffix.lower() not in VIDEO_EXT]
        if not videos:
            return [], [], "add the video to restyle"
        want = option_value(job, "style") or "anime"
        look = extra if (want == "own" or not want) else RESTYLES.get(want, RESTYLES["anime"])[1]
        if want != "own" and extra:
            look = f"{look}, {extra}"
        if not look:
            return [], [], "say what the new look should be"
        secs = int(option_value(job, "length") or SEGMENT_S)
        from .picturetools import unique_stems, wkey
        vbases = [it["stem"] for it in unique_stems([{"stem": slug(v.stem)} for v in videos])]
        for vi, v in enumerate(videos):
            from . import media
            size = restyle_size(engine, *(media.size_of(ff, v) or (0, 0)))
            total = duration_s(ff, v)
            parts = max(1, min(-(-int(min(total or SEGMENT_S, secs)) // SEGMENT_S), secs // SEGMENT_S))
            for k in range(parts):
                seg = cut_segment(ff, v, k * SEGMENT_S, _work(engine) / f"{wkey(v)}-part{k + 1:02d}.mp4", size)
                n = frame_count(ff, seg) if seg else 0
                length = wan_length(n)
                if not length:
                    if k == 0:
                        engine.log(f"  Couldn't read {v.name}; skipped.")
                    break
                items.append({"maker": True, "src": seg, "video": v, "part": k + 1, "size": size,
                              "length": length, "ref": pics[0] if pics else None,
                              "stem": f"{vbases[vi]}-restyled-part{k + 1:02d}",
                              "label": f"{v.name} part {k + 1}" if parts > 1 else v.name,
                              "key": f"restyle-video {v.name} {want} {k + 1}",
                              "prompt": f"{look}. Keep the same motion, people, objects and camera movement as "
                                        "the original video; smooth, natural movement."})
            if total > secs + 0.5:
                engine.log(f"  {v.name}: restyling the first {secs} s of {total:.0f} s (OPTIONS length for more).")
        if not items:
            return [], [], "couldn't read the video(s)"
    elif tid == "make-3d":
        for f in files:
            from .picturetools import wkey
            sq = square_on_white(ff, f, _work(engine) / f"{wkey(f)}-square.png") if ff else None
            items.append({"maker": True, "src": sq or f, "stem": slug(f.stem) + "-3d", "label": f.name,
                          "key": f"3d {f.name}"})
    else:
        return [], [], f"unknown tool {tid}"
    return items, [it["key"] for it in items], ""


def graph_for(engine, job, tid: str, item: dict, i: int, prefix: str, client) -> tuple[dict, str, str]:
    """(graph, output stem, fallback extension) for one planned item."""
    from . import quality, styles, workflowprefs as wfp
    from .picturetools import PACKS, _seed, pack_ready, upload_image
    from .tools import option_value
    seed = _seed(job, i)
    if tid in SDXL_TOOLS:
        style = style_for(job)
        pref = wfp.get(engine.s, "controlnet")
        prompt = wfp.with_add(styles.add(item["prompt"], style), pref)
        anatomy = style.id not in ("surreal", "abstract")
        negative = wfp.with_avoid(comfy_mod.negative_for("sdxl", engine.s.comfy.negative, style.negative, anatomy), pref)
        steps = pref.get("steps") or quality.pictures(engine.s).steps("sdxl")
        name = upload_image(client.base, item["src"])
        ckpt = api_name(client, item["ckpt"])
        if tid == "sketch-to-picture":
            strength, end = FOLLOW.get(option_value(job, "follow") or "some", FOLLOW["some"])
            return (controlnet_graph(ckpt, name, prompt, negative, seed, PACKS["sketch"].files[0][1], strength, end,
                                     steps, 6.0 + style.cfg, invert=item.get("invert", True),
                                     union_type=item.get("union", ""), prefix=prefix), item["stem"], ".png")
        strength, end = SHOW.get(option_value(job, "show") or "clear", SHOW["clear"])
        return (controlnet_graph(ckpt, name, prompt, negative, seed, PACKS["illusion"].files[0][1], strength, end,
                                 steps, 7.0, prefix=prefix), item["stem"], ".png")
    if tid == "restyle-video":
        pref = wfp.get(engine.s, "restyle-video")
        name = upload_image(client.base, item["src"])
        ref = upload_image(client.base, item["ref"]) if item.get("ref") else ""
        follow = option_value(job, "follow") or "close"
        edges = (0.08, 0.3) if follow == "close" else (0.2, 0.6)
        steps = 20 if quality.level(engine.s, "video") == "high" else 14
        w, h = item["size"]
        return (restyle_video_graph(name, wfp.with_add(item["prompt"], pref),
                                    wfp.with_avoid(comfy_mod.WAN_NEGATIVE, pref), seed, w, h, item["length"],
                                    steps=steps, edges=edges, ref_image=ref, prefix=prefix), item["stem"], ".mp4")
    if tid == "make-3d":
        from .doctor import comfy_models_dir
        hi = quality.level(engine.s, "pictures") == "high"
        name = upload_image(client.base, item["src"])
        cut = pack_ready(comfy_models_dir(engine.s), "bg")
        if i == 0 and not cut:
            engine.log("  Tip: with the background remover installed (System check, 900 MB) Joe cuts the "
                       "object out first, which gives cleaner 3D models.")
        return (model3d_graph(name, api_name(client, PACKS["3d"].files[0][1]), seed, steps=30 if hi else 20,
                              cut_out=cut, prefix=prefix), item["stem"], ".glb")
    raise comfy_mod.WorkflowError(f"unknown tool {tid}")


# --------------------------------------------------------------------------- finishing
def after(engine, job, tid: str, item: dict, folder: Path, made: list[str]) -> list[str]:
    """Per item: a restyled video piece gets its original sound back (when it had any)."""
    ff = _ffmpeg(engine)
    if tid != "restyle-video" or not ff or not made or not made[0].endswith(".mp4"):
        return made
    out = folder / made[0]
    tmp = out.with_name(out.stem + ".tmp.mp4")
    start = (item.get("part", 1) - 1) * SEGMENT_S
    secs = item.get("length", SEGMENT_FRAMES) / VIDEO_FPS
    r = _run([ff, "-y", "-v", "error", "-i", str(out), "-ss", f"{start:.3f}", "-t", f"{secs:.3f}",
              "-i", str(item["video"]), "-map", "0:v:0", "-map", "1:a:0?", "-c:v", "copy", "-c:a", "aac",
              "-shortest", "-movflags", "+faststart", str(tmp)])
    if r is not None and r.returncode == 0 and tmp.exists():
        tmp.replace(out)
    else:
        tmp.unlink(missing_ok=True)
    return made


def finish(engine, job, tid: str, folder: Path, st) -> None:
    """After every item: the pieces of each restyled video are joined into one file."""
    ff = _ffmpeg(engine)
    if tid != "restyle-video" or not ff:
        return
    groups: dict[str, list[str]] = {}
    for name in st.media_files:
        m = re.match(r"(.+)-restyled-part(\d+)\.mp4$", Path(name).name)
        if m:
            groups.setdefault(m.group(1), []).append(Path(name).name)
    for stem, parts in groups.items():
        parts = sorted(parts)
        final = folder / f"{stem}-restyled.mp4"
        if len(parts) == 1:
            (folder / parts[0]).replace(final)
        else:
            lst = folder / f".{stem}-parts.txt"
            lst.write_text("".join(f"file '{p}'\n" for p in parts), encoding="utf-8")
            r = _run([ff, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
                      "-movflags", "+faststart", str(final)])
            lst.unlink(missing_ok=True)
            if r is None or r.returncode != 0 or not final.exists():
                engine.log(f"  Couldn't join the pieces of {stem}; they're kept as separate files.")
                continue
            for p in parts:
                (folder / p).unlink(missing_ok=True)
            engine.log(f"  Joined {len(parts)} pieces into {final.name}.")
        st.media_files = [n for n in st.media_files if Path(n).name not in parts] + [final.name]
