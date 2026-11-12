"""Picture models for each style: what Joe recommends, and moving models you downloaded
yourself into ComfyUI.

Community models (Civitai and similar) come with their own license terms and sometimes need a
sign-in, so Joe never downloads them: he opens the model's page, you accept its terms and
download it there, and Joe then moves the file from your Downloads folder into ComfyUI's
checkpoints folder and says which style it suits. The list of recommendations lives in
model_picks.json ("style_models") so it can change on GitHub without a new version.
"""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Callable

from . import styles

Log = Callable[[str], None]
MODEL_EXT = (".safetensors",)        # Joe never moves in an older-format (pickle) model
MIN_BYTES = 500 * 1024 * 1024          # full picture models are bigger than this
LORA_BYTES = 8 * 1024 * 1024           # style add-ons (LoRAs): 8 MB up to MIN_BYTES
PAGE_HOSTS = ("https://civitai.com/", "https://huggingface.co/")

# Built-in recommendations (model_picks.json on GitHub replaces this list when it has one).
BUILTIN = [
    # full picture models (checkpoints, ~7 GB each, SDXL: fine on 8-12 GB cards)
    {"style": "photo", "name": "Juggernaut XL", "page": "https://civitai.com/models/133005/juggernaut-xl",
     "kind": "model", "base": "sdxl", "size_gb": 7, "note": "realistic photos, people, places"},
    {"style": "product", "name": "RealVisXL V5", "page": "https://huggingface.co/SG161222/RealVisXL_V5.0",
     "kind": "model", "base": "sdxl", "size_gb": 7, "note": "clean realistic product and studio shots"},
    {"style": "illustration", "name": "DreamShaper XL", "page": "https://civitai.com/models/112902/dreamshaper-xl",
     "kind": "model", "base": "sdxl", "size_gb": 7,
     "pick": "On its page choose the version called alpha2, not Turbo or Lightning (those need other settings).",
     "note": "one model for illustration, painting, concept art, fantasy, cartoon, 3D and more"},
    {"style": "anime", "name": "Animagine XL 4.0", "page": "https://huggingface.co/cagliostrolab/animagine-xl-4.0",
     "file": "animagine-xl-4.0.safetensors", "kind": "model", "base": "sdxl", "size_gb": 7, "note": "anime and manga"},
    # style add-ons (LoRAs, small; they work on top of any SDXL model)
    {"style": "pixel", "name": "Pixel Art XL", "page": "https://huggingface.co/nerijs/pixel-art-xl",
     "kind": "lora", "base": "sdxl", "size_gb": 0.2, "note": "retro pixel art"},
    {"style": "coloring", "name": "ColoringBookRedmond V2",
     "page": "https://huggingface.co/artificialguybr/ColoringBookRedmond-V2",
     "file": "ColoringBookRedmond-ColoringBook-ColoringBookAF.safetensors",
     "kind": "lora", "base": "sdxl", "size_gb": 0.2, "note": "clean coloring-book line art"},
    {"style": "watercolor", "name": "Watercolor SDXL", "page": "https://huggingface.co/cbo305/Watercolor_SDXL",
     "kind": "lora", "base": "sdxl", "size_gb": 0.2, "note": "soft watercolor paintings"},
]


def _ok(r) -> bool:
    try:
        return (r["style"] in styles.STYLES and 0 < len(str(r["name"])) <= 80
                and str(r["page"]).startswith(PAGE_HOSTS) and 0 < float(r.get("size_gb", 1)) <= 60)
    except (KeyError, TypeError, ValueError):
        return False


def recommendations(picks: dict | None = None) -> list[dict]:
    rows = (picks or {}).get("style_models")
    rows = rows if isinstance(rows, list) and rows else BUILTIN
    return [r for r in rows if _ok(r)]


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def has_model(models: list, rec: dict) -> bool:
    """Is the recommended model itself installed? Its name (or its file's name) is in a picture
    checkpoint's file name: 'DreamShaper XL' = dreamshaperXL_v21.safetensors.
    (Until 2.3.0.dev16 any model that "suited" the style counted, and for art styles that was any
    model that isn't a photo model: so with only SDXL base installed, DreamShaper and Animagine were
    never offered, and Juggernaut hid RealVisXL. Found on Joseph's PC.)"""
    keys = {_key(str(rec.get("match") or str(rec.get("name", "")).split(" ")[0]))}
    if rec.get("file"):
        keys.add(_key(Path(str(rec["file"])).stem))
    keys = {k for k in keys if len(k) >= 4}
    for m in models:
        if getattr(m, "family", "sdxl") in ("svd", "video"):
            continue
        name = _key(Path(str(m.name).replace("\\", "/")).stem)
        if any(k in name for k in keys):
            return True
    return False


def offers(models: list, picks: dict | None = None, loras: list[str] | None = None) -> list[dict]:
    """System-check items: one per style whose recommended model (or style add-on) isn't installed."""
    out, seen = [], set()
    for r in recommendations(picks):
        s = r["style"]
        if s in seen:
            continue
        if r.get("kind") == "lora":
            if loras is None or styles.pick_lora(styles.STYLES[s], loras):
                continue
        elif has_model(models, r):
            continue
        seen.add(s)
        label = styles.STYLES[s].label
        try:
            gb = float(r.get("size_gb", 1))
        except (TypeError, ValueError):
            gb = 1.0
        out.append({"id": f"style-{s}", "group": "styles", "optional": True, "action": "import-models",
                    "page": r["page"], "style": s, "file": str(r.get("file") or ""), "base": r.get("base", "sdxl"),
                    "text": f"For {label} pictures: {r['name']} ("
                            + (f"about {gb:g} GB" if gb >= 1 else "a small style add-on")
                            + f", {r.get('note') or 'free community model'}) "
                            + ("gives that look on top of your model. " if r.get("kind") == "lora"
                               else "draws them better than the model you have. ")
                            + "It is a free model made by other people, with its own license, so Joe can't "
                              "download it for you: GET IT opens its page and you download the file there. "
                            + (str(r["pick"]).strip()[:200] + " " if str(r.get("pick") or "").strip() else "")
                            + "When the download has finished Joe asks to move it into ComfyUI (or press GET IT again).",
                    "what": f"{r['name']} (about {gb:g} GB)"})
    return out


def downloads_dir() -> Path:
    return Path(os.environ.get("JOE_DOWNLOADS") or Path.home() / "Downloads")


def found(models_dir: Path | None, folder: Path | None = None) -> list[Path]:
    """Picture model files waiting in Downloads that ComfyUI doesn't have yet."""
    folder = folder or downloads_dir()
    have = set()
    if models_dir and (models_dir / "checkpoints").is_dir():
        have = {p.name.lower() for p in (models_dir / "checkpoints").rglob("*") if p.is_file()}
    try:
        files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in MODEL_EXT]
    except OSError:
        return []
    if models_dir and (models_dir / "loras").is_dir():
        have |= {p.name.lower() for p in (models_dir / "loras").rglob("*") if p.is_file()}
    return [p for p in files if p.stat().st_size >= LORA_BYTES and p.name.lower() not in have
            and (p.stat().st_size >= MIN_BYTES or is_lora_name(p.name))]


def is_lora_name(name: str) -> bool:
    """A small file Joe recognizes as a style add-on (by name: 'lora' or a recommended one)."""
    n = name.lower()
    words = ["lora"] + [w for r in BUILTIN if r.get("kind") == "lora" for w in styles.STYLES[r["style"]].lora]
    return any(w in n for w in words)


def style_of(name: str, picks: dict | None = None) -> str:
    """The style a model file suits, judged by its name ('general' when unknown)."""
    n = name.lower()
    for s in ("anime", "pixel", "photo", "cartoon", "illustration", "painting", "render3d"):
        if any(w in n for w in styles.hints(s, picks)[:6]):
            return s
    return "general"


def hf_repo(page: str) -> str:
    """'https://huggingface.co/owner/name' -> 'owner/name' ('' for other sites)."""
    if not page.startswith("https://huggingface.co/"):
        return ""
    parts = page[len("https://huggingface.co/"):].split("/")
    return "/".join(parts[:2]) if len(parts) >= 2 and all(parts[:2]) else ""


def hf_pick_file(siblings: list[dict]) -> str:
    """The model file to download from a Hugging Face repo listing: the biggest .safetensors in the
    top folder (sub-folders hold the split 'diffusers' copy ComfyUI doesn't use)."""
    files = [s for s in siblings or [] if isinstance(s, dict)
             and str(s.get("rfilename", "")).lower().endswith(".safetensors") and "/" not in s["rfilename"]]
    # A half-size copy (fp16) draws the same pictures as the full-size one and is half the download
    # (Joseph's PC got the 13.9 GB RealVisXL file where a 7 GB one would do): take it when there is one.
    half = [s for s in files if "fp16" in str(s["rfilename"]).lower()]
    files = half or files
    files.sort(key=lambda s: s.get("size") or 0, reverse=True)
    return files[0]["rfilename"] if files else ""


def download_link(page: str, timeout: float = 15, file: str = "") -> str:
    """A direct download link for a Hugging Face pick (the browser saves it to Downloads), or the
    repo's file list when the file can't be found; other sites: the page itself."""
    repo = hf_repo(page)
    if not repo:
        return page
    import urllib.parse
    if file and "/" not in file and file.lower().endswith(".safetensors"):
        return f"https://huggingface.co/{repo}/resolve/main/{urllib.parse.quote(file)}?download=true"
    import json
    import urllib.parse
    import urllib.request
    try:
        with urllib.request.urlopen(f"https://huggingface.co/api/models/{repo}?blobs=true",
                                    timeout=timeout) as r:
            name = hf_pick_file(json.loads(r.read().decode("utf-8")).get("siblings", []))
    except (OSError, ValueError):
        name = ""
    if not name:
        return f"https://huggingface.co/{repo}/tree/main"
    return f"https://huggingface.co/{repo}/resolve/main/{urllib.parse.quote(name)}?download=true"


def import_downloads(models_dir: Path | None, log: Log, folder: Path | None = None,
                     picks: dict | None = None) -> int:
    """Move the waiting model files into ComfyUI's checkpoints folder. Returns how many."""
    if not models_dir:
        log("Can't find ComfyUI's models folder. Set it in Setup (F10).")
        return 0
    files = found(models_dir, folder)
    moved = 0
    for f in files:
        size = round(f.stat().st_size / 1e9, 1)
        dest = models_dir / ("checkpoints" if f.stat().st_size >= MIN_BYTES else "loras")
        dest.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(f), str(dest / f.name))
        except OSError as e:
            log(f"Couldn't move {f.name}: {e}")
            continue
        moved += 1
        s = style_of(f.name, picks)
        use = "" if s == "general" else f"; Joe will use it for {styles.STYLES[s].label} pictures"
        log(f"Moved {f.name} ({size} GB) into ComfyUI{use}.")
    return moved


OTHER_FOLDERS = {"vae": "Picture decoder (VAE)", "text_encoders": "Text reader", "clip": "Text reader",
                 "upscale_models": "Upscaler", "clip_vision": "Picture reader", "controlnet": "ControlNet",
                 "embeddings": "Embedding", "audio_encoders": "Sound", "diffusion_models": "Main model",
                 "unet": "Main model"}


def inventory(models_dir: Path | None, ollama: list[dict], picks: dict | None = None) -> dict:
    """What's installed, for Setup > System check > Your models."""
    from . import comfy
    pics = []
    for m in comfy.scan_models(models_dir):
        if m.folder != "checkpoints":
            continue
        # only models Joe really draws pictures with (never a video model like SVD), and never an
        # SD 1.5 model for a style whose add-on is made for SDXL (pixel art, watercolor, coloring page)
        good = [s for s in styles.NAMES if s != "general" and m.family in ("sdxl", "sd15", "other")
                and not (m.family == "sd15" and styles.STYLES[s].lora)
                and m in styles.choose_model([m], s, picks)]
        pics.append({"name": m.name, "size_gb": m.size_gb, "family": m.family,
                     "styles": [styles.STYLES[s].label for s in good]})
    addons = []
    for name in comfy.list_loras(models_dir):
        use = [styles.STYLES[s].label for s in styles.NAMES
               if styles.STYLES[s].lora and styles.pick_lora(styles.STYLES[s], [name])]
        size = 0.0
        try:
            size = round((models_dir / "loras" / name).stat().st_size / 2**30, 2)
        except (OSError, TypeError):
            pass
        addons.append({"name": name, "size_gb": size, "styles": use})
    other = []
    for folder, what in OTHER_FOLDERS.items():
        root = (models_dir / folder) if models_dir else None
        if not root or not root.is_dir():
            continue
        for f in sorted(root.rglob("*")):
            if f.is_file() and (f.suffix.lower() in (".safetensors", ".gguf") or comfy.is_pickle(f.name)):
                try:
                    gb = round(f.stat().st_size / 2**30, 2)
                except OSError:
                    gb = 0.0
                other.append({"name": f.relative_to(root).as_posix(), "what": what, "size_gb": gb})
    ck = (models_dir / "checkpoints") if models_dir else None
    if ck and ck.is_dir():                       # music, sound and 3D models live with the checkpoints
        for f in sorted(ck.rglob("*")):
            if f.is_file() and comfy.is_tool_model(f.name):
                try:
                    gb = round(f.stat().st_size / 2**30, 2)
                except OSError:
                    gb = 0.0
                other.append({"name": f.relative_to(ck).as_posix(), "what": "Tool model (music, sound or 3D)",
                              "size_gb": gb})
    unsafe = [x["name"] for x in pics + addons + other if comfy.is_pickle(x["name"])]
    ok = [n for n in unsafe if comfy.pickle_allowed(n, models_dir)]
    return {"unsafe": unsafe, "allowed": ok,
            "writing": [{"name": m["name"], "size_gb": m["size_gb"], "params": m.get("params", ""),
                         "writer": m.get("writer", True)} for m in ollama],
            "pictures": pics, "addons": addons, "other": other,
            "folder": str(models_dir) if models_dir else ""}
