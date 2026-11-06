"""Share model folders from Stable Diffusion WebUI (A1111), Forge and reForge with ComfyUI.

Many people already have gigabytes of checkpoints and LoRAs in a WebUI folder. ComfyUI can
use them where they are through its "extra model paths" file, so nothing is downloaded or
copied twice. Joe finds those folders, and (only after a yes) adds a section for each to
the right file:

- ComfyUI Desktop: extra_models_config.yaml in its settings folder
- portable / own install / Joe's own copy: extra_model_paths.yaml next to ComfyUI's main.py

The old file is kept as <name>.joe-backup. Joe's own sections start with a "# joe-ai" line, so
they're easy to spot and remove. Joe also reads every extra folder (his or yours) when he looks
for picture models, so a model in a WebUI folder can be picked like any other.
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import finder

MARK = "# joe-ai: shared model folders"
WEBUI_NAMES = re.compile(r"webui|forge|automatic1111|a1111|stable.?diffusion", re.I)

# ComfyUI folder name -> folders inside a WebUI install (first one that exists is used)
A1111_MAP: list[tuple[str, tuple[str, ...]]] = [
    ("checkpoints", ("models/Stable-diffusion",)),
    ("vae", ("models/VAE",)),
    ("loras", ("models/Lora", "models/LyCORIS")),
    ("upscale_models", ("models/ESRGAN", "models/RealESRGAN", "models/SwinIR", "models/DAT")),
    ("embeddings", ("embeddings", "models/embeddings")),
    ("hypernetworks", ("models/hypernetworks",)),
    ("controlnet", ("models/ControlNet", "models/controlnet", "extensions/sd-webui-controlnet/models")),
    ("clip", ("models/text_encoder",)),
    ("text_encoders", ("models/text_encoder",)),
]
MODEL_EXTS = {".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".gguf", ".sft"}


@dataclass
class WebUI:
    folder: Path
    label: str
    models: int          # checkpoint files found

    def as_dict(self) -> dict:
        return {"folder": str(self.folder), "label": self.label, "models": self.models}


def _label(folder: Path) -> str:
    n = folder.name.lower()
    if "reforge" in n:
        return "Stable Diffusion WebUI reForge"
    if "forge" in n or (folder / "modules_forge").is_dir():
        return "Stable Diffusion WebUI Forge"
    return "Stable Diffusion WebUI (AUTOMATIC1111)"


def _count(d: Path) -> int:
    try:
        return sum(1 for f in d.rglob("*") if f.suffix.lower() in MODEL_EXTS and f.is_file())
    except OSError:
        return 0


def is_webui(folder: Path) -> bool:
    try:
        return (folder / "models" / "Stable-diffusion").is_dir() and \
            any((folder / f).exists() for f in ("webui.py", "launch.py", "webui-user.bat", "webui.sh"))
    except OSError:
        return False


def find_webuis(extra_roots: list[Path] | None = None) -> list[WebUI]:
    """WebUI installs in the usual places (two levels deep; Forge's one-click package keeps the
    real folder in webui\\ inside its own)."""
    out: list[WebUI] = []
    seen: set[str] = set()
    roots = list(extra_roots or []) + finder._search_roots()
    for root in roots:
        for c in finder._children(root):
            if not (finder._is_dir(c) and WEBUI_NAMES.search(c.name)):
                continue
            for cand in (c, *[g for g in finder._children(c) if finder._is_dir(g)]):
                key = str(cand).lower()
                if key in seen or not is_webui(cand):
                    continue
                seen.add(key)
                out.append(WebUI(cand, _label(cand if cand.name.lower() != "webui" else c),
                                 _count(cand / "models" / "Stable-diffusion")))
    return out


# --------------------------------------------------------------------------- the yaml file
def yaml_file(inst) -> Path | None:
    """Which extra-paths file this ComfyUI reads."""
    if not inst:
        return None
    if inst.kind == "desktop":
        dirs = finder._desktop_config_dirs()
        for d in dirs:
            if (d / "extra_models_config.yaml").exists():
                return d / "extra_models_config.yaml"
        return dirs[0] / "extra_models_config.yaml" if dirs else None
    base = Path(inst.base) if inst.base else None
    if base and (base / "main.py").exists():
        return base / "extra_model_paths.yaml"
    if inst.cwd and (Path(inst.cwd) / "ComfyUI" / "main.py").exists():
        return Path(inst.cwd) / "ComfyUI" / "extra_model_paths.yaml"
    return None


def parse(text: str) -> list[dict]:
    """ComfyUI's extra-paths file -> [{name, base_path, folders: {kind: [paths]}}].
    Small reader for this one format (top-level names, 'key: value', and 'key: |' lists)."""
    sections: list[dict] = []
    cur: dict | None = None
    key_multi: str | None = None
    for raw in text.splitlines():
        line = raw.split(" #", 1)[0].rstrip() if not raw.lstrip().startswith("#") else ""
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0 and line.endswith(":"):
            cur = {"name": line[:-1].strip(), "base_path": "", "folders": {}}
            sections.append(cur)
            key_multi = None
            continue
        if cur is None:
            continue
        m = re.match(r"\s+([\w-]+)\s*:\s*(.*)$", line)
        if m and (key_multi is None or indent <= cur.get("_ki", 0)):
            k, v = m.group(1), m.group(2).strip().strip("'\"")
            cur["_ki"] = indent
            if v in ("|", ">"):
                key_multi = k
                cur["folders"].setdefault(k, [])
            elif k == "base_path":
                cur["base_path"], key_multi = v, None
            elif k in ("is_default",):
                key_multi = None
            else:
                key_multi = None
                cur["folders"].setdefault(k, []).append(v)
        elif key_multi:
            cur["folders"][key_multi].append(line.strip().strip("'\""))
    for s in sections:
        s.pop("_ki", None)
    return sections


def folders_of(yaml: Path | None, kind: str) -> list[Path]:
    """Every extra folder of one kind (e.g. 'checkpoints') listed in the file."""
    if not yaml:
        return []
    try:
        text = yaml.read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for s in parse(text):
        base = Path(s["base_path"]) if s["base_path"] else None
        for rel in s["folders"].get(kind, []):
            p = Path(rel)
            if not p.is_absolute() and base:
                p = base / rel
            out.append(p)
    return out


def yaml_for_models_dir(models_dir: Path | None) -> list[Path]:
    """Extra-paths files that belong to the ComfyUI whose models folder this is."""
    if not models_dir:
        return []
    out = [models_dir.parent / "extra_model_paths.yaml"]
    try:
        db = finder.desktop_base_path()
        if db and db.resolve() == models_dir.parent.resolve():
            out += [d / "extra_models_config.yaml" for d in finder._desktop_config_dirs()]
    except OSError:
        pass
    return [p for p in out if p.exists()]


def extra_dirs(models_dir: Path | None, kind: str) -> list[Path]:
    seen, out = set(), []
    for y in yaml_for_models_dir(models_dir):
        for p in folders_of(y, kind):
            k = str(p).lower()
            if k not in seen and finder._is_dir(p) and (not models_dir or p != models_dir / kind):
                seen.add(k)
                out.append(p)
    return out


def shared_already(yaml: Path | None, webui: Path) -> bool:
    if not yaml:
        return False
    try:
        text = yaml.read_text(encoding="utf-8")
    except OSError:
        return False
    w = str(webui).replace("\\", "/").rstrip("/").lower()
    return any(s["base_path"].replace("\\", "/").rstrip("/").lower() == w for s in parse(text))


def section(webui: WebUI, n: int) -> str:
    """The lines Joe adds for one WebUI folder (only folders that exist)."""
    lines = [f"{MARK} ({webui.label})", f"joe_webui_{n}:", f"    base_path: {webui.folder.as_posix()}/"]
    for kind, rels in A1111_MAP:
        have = [r for r in rels if (webui.folder / r).is_dir()]
        if not have:
            continue
        if len(have) == 1:
            lines.append(f"    {kind}: {have[0]}")
        else:
            lines.append(f"    {kind}: |")
            lines += [f"        {r}" for r in have]
    return "\n".join(lines) + "\n"


def share(inst, webuis: list[WebUI], log=print) -> Path | None:
    """Add a section for each WebUI not shared yet. Old file kept as .joe-backup."""
    yaml = yaml_file(inst)
    if not yaml:
        log("Couldn't find where this ComfyUI keeps its extra model folders list.")
        return None
    todo = [w for w in webuis if not shared_already(yaml, w.folder)]
    if not todo:
        log("Those model folders are already shared with ComfyUI.")
        return yaml
    old = ""
    if yaml.exists():
        old = yaml.read_text(encoding="utf-8")
        shutil.copy2(yaml, yaml.with_name(yaml.name + ".joe-backup"))
    else:
        yaml.parent.mkdir(parents=True, exist_ok=True)
    taken = set(re.findall(r"(?m)^joe_webui_(\d+):", old))
    n, parts = 1, []
    for w in todo:
        while str(n) in taken:
            n += 1
        taken.add(str(n))
        parts.append(section(w, n))
    text = old.rstrip("\n") + ("\n\n" if old.strip() else "") + "\n".join(parts)
    yaml.write_text(text, encoding="utf-8")
    for w in todo:
        log(f"ComfyUI can now use the models in {w.label} ({w.folder}). Restart ComfyUI so it sees them.")
    return yaml


def offer(inst) -> dict | None:
    """A System check line when a WebUI is found that ComfyUI can't see yet."""
    if not inst:
        return None
    yaml = yaml_file(inst)
    found = [w for w in find_webuis() if not shared_already(yaml, w.folder)]
    if not found or not yaml:
        return None
    names = "; ".join(f"{w.label} at {w.folder} ({w.models} picture model{'s' if w.models != 1 else ''})"
                      for w in found[:3])
    return {"id": "share-models", "text": f"Found {names}. ComfyUI can use those models where they are "
            "(no downloading them again).", "action": "share-models", "optional": True,
            "what": "share WebUI model folders with ComfyUI"}
