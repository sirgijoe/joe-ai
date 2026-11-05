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
import shutil
from pathlib import Path
from typing import Callable

from . import styles

Log = Callable[[str], None]
MODEL_EXT = (".safetensors", ".ckpt")
MIN_BYTES = 500 * 1024 * 1024          # smaller files are LoRAs/embeddings, not full models
PAGE_HOSTS = ("https://civitai.com/", "https://huggingface.co/")

# Built-in recommendations (model_picks.json on GitHub replaces this list when it has one).
BUILTIN = [
    {"style": "photo", "name": "Juggernaut XL", "page": "https://civitai.com/models/133005/juggernaut-xl",
     "base": "sdxl", "size_gb": 7, "note": "realistic photos and product shots"},
    {"style": "illustration", "name": "DreamShaper XL", "page": "https://civitai.com/models/112902/dreamshaper-xl",
     "base": "sdxl", "size_gb": 7, "note": "illustrations, painted and drawn looks, also decent photos"},
    {"style": "anime", "name": "Animagine XL 4.0", "page": "https://huggingface.co/cagliostrolab/animagine-xl-4.0",
     "base": "sdxl", "size_gb": 7, "note": "anime and manga"},
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


def offers(models: list, picks: dict | None = None) -> list[dict]:
    """System-check items: one per style that has a recommendation but no suitable model installed."""
    out, seen = [], set()
    for r in recommendations(picks):
        s = r["style"]
        if s in seen or styles.choose_model(models, s, picks):
            continue
        seen.add(s)
        label = styles.STYLES[s].label
        out.append({"id": f"style-{s}", "group": "styles", "optional": True, "action": "import-models",
                    "page": r["page"], "style": s,
                    "text": f"For {label} pictures: {r['name']} (about {r['size_gb']:g} GB, "
                            f"{r.get('note') or 'free community model'}) draws them better than the model you "
                            f"have. Its page has the license terms; you download it there and Joe moves it "
                            f"into ComfyUI.",
                    "what": f"{r['name']} (about {r['size_gb']:g} GB)"})
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
    return [p for p in files if p.stat().st_size >= MIN_BYTES and p.name.lower() not in have]


def style_of(name: str, picks: dict | None = None) -> str:
    """The style a model file suits, judged by its name ('general' when unknown)."""
    n = name.lower()
    for s in ("anime", "pixel", "photo", "cartoon", "illustration", "painting", "render3d"):
        if any(w in n for w in styles.hints(s, picks)[:6]):
            return s
    return "general"


def import_downloads(models_dir: Path | None, log: Log, folder: Path | None = None,
                     picks: dict | None = None) -> int:
    """Move the waiting model files into ComfyUI's checkpoints folder. Returns how many."""
    if not models_dir:
        log("Can't find ComfyUI's models folder. Set it in Setup (F10).")
        return 0
    files = found(models_dir, folder)
    dest = models_dir / "checkpoints"
    dest.mkdir(parents=True, exist_ok=True)
    moved = 0
    for f in files:
        size = round(f.stat().st_size / 1e9, 1)
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
