"""Are the model files whole? (Setup > Models > CHECK MY MODEL FILES)

A download that stops part way leaves a file that looks fine to a folder listing but makes
ComfyUI fail later with a confusing error. Almost every picture, video and sound model is a
.safetensors file, and that format says in its own first bytes how big the rest must be:
8 bytes = the header's length, then a JSON header listing every piece with its byte range.
So Joe can tell a cut-short file without the internet and without reading gigabytes: he reads
the header and compares the size the file should be with the size it is.

Nothing is changed here. A short file is reported; MOVE IT TO THE RECYCLE BIN (with your OK)
moves it, and System check then offers the download again.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

MAX_HEADER = 100 * 1024 * 1024        # a real header is kilobytes to a few MB


def expected_size(p: Path) -> int | None:
    """The size a .safetensors file must have, from its own header (None = can't tell / not one)."""
    try:
        with open(p, "rb") as f:
            raw = f.read(8)
            if len(raw) < 8:
                return 8                       # not even the start: certainly cut short
            n = struct.unpack("<Q", raw)[0]
            if n <= 0 or n > MAX_HEADER:
                return None
            head = f.read(n)
    except OSError:
        return None
    if len(head) < n:
        return 8 + n                           # the header itself is cut short
    try:
        meta = json.loads(head.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(meta, dict):
        return None
    end = 0
    for k, v in meta.items():
        if k == "__metadata__" or not isinstance(v, dict):
            continue
        offs = v.get("data_offsets")
        if isinstance(offs, list) and len(offs) == 2 and all(isinstance(x, int) for x in offs):
            end = max(end, offs[1])
    return 8 + n + end


def check_file(p: Path) -> dict | None:
    """{path, name, have, want} when the file is shorter than its header says, else None."""
    want = expected_size(p)
    try:
        have = p.stat().st_size
    except OSError:
        return None
    if want is None or have >= want:
        return None
    return {"path": str(p), "name": p.name, "have": have, "want": want,
            "pct": round(100 * have / want, 1) if want else 0}


def model_roots(models_dir: Path | None) -> list[Path]:
    """ComfyUI's models folder plus the A1111/Forge folders it was told to share."""
    roots: list[Path] = []
    if models_dir and Path(models_dir).is_dir():
        roots.append(Path(models_dir))
        try:
            from .sharedmodels import extra_dirs
            for folder in ("checkpoints", "loras", "diffusion_models", "unet", "vae", "controlnet",
                           "text_encoders", "upscale_models"):
                roots += [d for d in extra_dirs(Path(models_dir), folder) if d.is_dir()]
        except Exception:                      # noqa: BLE001 (sharing is optional)
            pass
    return roots


def scan(models_dir: Path | None, extra: list[Path] | None = None) -> dict:
    """Every .safetensors under the model folders: {checked, short: [...], checked_gb}."""
    seen: set[str] = set()
    short: list[dict] = []
    checked, total = 0, 0
    for root in model_roots(models_dir) + list(extra or []):
        if not root.is_dir():
            continue
        for f in root.rglob("*.safetensors"):
            key = str(f.resolve()).lower()
            if key in seen or not f.is_file():
                continue
            seen.add(key)
            checked += 1
            try:
                total += f.stat().st_size
            except OSError:
                pass
            bad = check_file(f)
            if bad:
                short.append(bad)
    return {"checked": checked, "checked_gb": round(total / 1e9, 1), "short": short}


def plain(result: dict) -> str:
    if not result["checked"]:
        return "No model files found to check (is ComfyUI's models folder set? System check finds it)."
    if not result["short"]:
        return (f"All {result['checked']} model files are whole ({result['checked_gb']} GB checked). "
                "Nothing to download again.")
    lines = [f"{len(result['short'])} of {result['checked']} model files are cut short (the download "
             "stopped part way). Move them to the Recycle Bin, then System check / Setup > Models offers "
             "them again:"]
    for s in result["short"]:
        lines.append(f"- {s['name']}: {s['have'] / 1e9:.2f} of {s['want'] / 1e9:.2f} GB ({s['pct']}%)")
    return "\n".join(lines)
