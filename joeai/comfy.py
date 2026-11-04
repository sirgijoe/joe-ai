"""ComfyUI: client, model discovery and workflow templates.

Workflows are ComfyUI's "API format" JSON (in ComfyUI: Workflow menu > Export (API),
older versions: "Save (API Format)"). Drop them into <workspace>/Workflows/.

Joe fills a template in one of two ways:
1. Placeholders anywhere in a text value: {{PROMPT}} {{NEGATIVE}} {{SEED}} {{WIDTH}}
   {{HEIGHT}} {{CHECKPOINT}} {{PREFIX}}
2. No placeholders: it finds the prompt boxes by following the sampler's
   positive/negative inputs, and sets seed, size, checkpoint and save prefix.

With no WORKFLOW at all, image jobs use a built-in text-to-image graph that works
with any SD 1.5 / SDXL checkpoint, so a fresh install needs no workflow files.
"""
from __future__ import annotations

import copy
import json
import random
import re
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

from .http import HttpError, request_bytes, request_json

PLACEHOLDERS = ("{{PROMPT}}", "{{NEGATIVE}}", "{{SEED}}", "{{WIDTH}}", "{{HEIGHT}}",
                "{{CHECKPOINT}}", "{{PREFIX}}")
MODEL_EXTS = {".safetensors", ".ckpt", ".pt", ".pth", ".gguf", ".sft"}
DEFAULT_PORTS = (8000, 8188)       # desktop app, then portable/manual install


class WorkflowError(ValueError):
    pass


# --------------------------------------------------------------------------- models
@dataclass
class ImageModel:
    name: str          # as ComfyUI names it, e.g. "SDXL\\sd_xl_base_1.0.safetensors"
    folder: str        # checkpoints | diffusion_models | unet
    size_gb: float
    family: str        # sdxl | sd15 | flux | sd3 | svd | video | other
    mtime: float = 0.0

    @property
    def kind(self) -> str:
        return "video" if self.family in ("svd", "video") else "image"


# Name hints are only a fallback: family_of() first reads the model file itself.
# These are public model-family names, never anyone's particular files.
_FAMILIES = [  # (family, pattern) — first match wins; checked against the lowercased path
    ("svd", r"(^|[\\/_-])svd|stable[-_ ]?video"),
    ("video", r"wan2|wan[-_]?\d|ltx|hunyuan.*video|cogvideo|mochi|cosmos"),
    ("flux", r"flux"),
    ("sd3", r"sd3|sd_3|stable[-_]?diffusion[-_]?3"),
    ("sd15", r"v1-5|sd15|sd-?1\.5|sd_1\.5"),
    ("sdxl", r"sdxl|xl\b|xl[_.-]|pony|illustrious"),
]
# Tensor names that identify each architecture inside a .safetensors file.
_ARCH_KEYS = [
    ("svd", ("time_stack", "time_mixer")),
    ("video", ("patch_embedding", "scale_shift_table", "transformer_blocks.0.attn1.to_q")),
    ("flux", ("double_blocks.", "single_blocks.")),
    ("sd3", ("joint_blocks.",)),
    ("sdxl", ("conditioner.embedders.1",)),
    ("sd15", ("cond_stage_model.",)),
]
_arch_cache: dict[tuple, str] = {}


def arch_of_file(path: Path) -> str:
    """Read a .safetensors header (tensor names only, a few MB at most) to tell
    SDXL / SD1.5 / Flux / SD3 / video apart, whatever the file is called."""
    if path.suffix.lower() not in (".safetensors", ".sft"):
        return ""
    try:
        st = path.stat()
        key = (str(path), st.st_mtime, st.st_size)
        if key in _arch_cache:
            return _arch_cache[key]
        with open(path, "rb") as f:
            n = int.from_bytes(f.read(8), "little")
            if not 0 < n < 64_000_000:
                return ""
            names = json.loads(f.read(n)).keys()
    except (OSError, ValueError, UnicodeDecodeError):
        return ""
    found = ""
    # SD1.5/SDXL/SVD UNets use input_blocks (and their attention layers are also called
    # transformer_blocks...), so a file with input_blocks is never one of the newer video models.
    sd_unet = any("input_blocks." in k for k in names)
    for fam, needles in _ARCH_KEYS:
        if fam == "video" and sd_unet:
            continue
        if any(nd in k for k in names for nd in needles):
            found = fam
            break
    _arch_cache[key] = found
    return found
# Rough VRAM (GB) each family needs to run comfortably at default settings.
FAMILY_VRAM = {"sd15": 4, "sdxl": 8, "sd3": 10, "flux": 12, "svd": 10, "video": 12, "other": 8}
FAMILY_RANK = {"flux": 5, "sd3": 4, "sdxl": 3, "sd15": 1, "other": 0, "svd": 2, "video": 4}


def family_of(path: str, size_gb: float = 0, file: Path | None = None) -> str:
    if file is not None:
        arch = arch_of_file(file)
        if arch:
            return arch
    low = path.lower()
    for fam, pat in _FAMILIES:
        if re.search(pat, low):
            return fam
    # Unknown name: guess from file size (SD1.5 ~2-4 GB, SDXL ~6-7 GB).
    if 1.5 <= size_gb <= 4.5:
        return "sd15"
    if 5.5 <= size_gb <= 7.5:
        return "sdxl"
    return "other"


def desktop_base_path() -> Path | None:
    """ComfyUI Desktop's data folder (see finder.py)."""
    from .finder import desktop_base_path as _b
    return _b()


def desktop_exe() -> Path | None:
    """ComfyUI Desktop's program, newest name first (see finder.py)."""
    from .finder import desktop_exe as _e
    return _e()


def scan_models(models_dir: Path | None) -> list[ImageModel]:
    """Find checkpoints on disk (works even while ComfyUI is closed)."""
    out: list[ImageModel] = []
    if not models_dir or not models_dir.is_dir():
        return out
    for folder in ("checkpoints", "diffusion_models", "unet"):
        root = models_dir / folder
        if not root.is_dir():
            continue
        for f in root.rglob("*"):
            if f.suffix.lower() not in MODEL_EXTS or not f.is_file():
                continue
            try:
                st = f.stat()
            except OSError:
                continue
            rel = str(f.relative_to(root)).replace("/", "\\" if sys.platform == "win32" else "/")
            gb = round(st.st_size / 2**30, 1)
            out.append(ImageModel(rel, folder, gb, family_of(rel, gb, f), st.st_mtime))
    return out


def best_image_model(models: list[ImageModel], vram_gb: float, kind: str = "image",
                     want: str = "", family: str = "") -> ImageModel | None:
    """Pick a checkpoint: `want` (part of a file name) wins; else the best family that
    fits in VRAM, newest file first. `family` limits the choice (template compatibility)."""
    pool = [m for m in models if m.kind == kind and m.folder == "checkpoints"] or \
           [m for m in models if m.kind == kind]
    if want:
        w = want.lower()
        hits = [m for m in pool if w in m.name.lower()]
        return max(hits, key=lambda m: m.mtime) if hits else None
    if family:
        pool = [m for m in pool if m.family == family]
    if not pool:
        return None
    vram = vram_gb or 8
    fits = [m for m in pool if FAMILY_VRAM.get(m.family, 8) <= vram + 0.5] or pool
    return max(fits, key=lambda m: (FAMILY_RANK.get(m.family, 0), m.mtime))


# --------------------------------------------------------------------------- client
class ComfyClient:
    def __init__(self, base: str, timeout_s: int = 900):
        self.base = base.rstrip("/")
        self.timeout_s = timeout_s
        self.client_id = uuid.uuid4().hex

    def up(self) -> bool:
        try:
            request_json("GET", f"{self.base}/system_stats", timeout=3)
            return True
        except HttpError:
            return False

    def checkpoints(self) -> list[str]:
        """Model names exactly as ComfyUI will accept them in a graph."""
        names: list[str] = []
        for node, key in (("CheckpointLoaderSimple", "ckpt_name"), ("UNETLoader", "unet_name")):
            try:
                info = request_json("GET", f"{self.base}/object_info/{node}", timeout=10)
                opts = info[node]["input"]["required"][key][0]
                if isinstance(opts, list):
                    names += [n for n in opts if isinstance(n, str)]
            except (HttpError, KeyError, IndexError, TypeError):
                continue
        return names

    def free(self) -> None:
        request_json("POST", f"{self.base}/free", {"unload_models": True, "free_memory": True},
                     timeout=30)

    def submit(self, graph: dict) -> str:
        r = request_json("POST", f"{self.base}/prompt",
                         {"prompt": graph, "client_id": self.client_id}, timeout=60)
        if r.get("node_errors"):
            raise WorkflowError(f"ComfyUI rejected the workflow: {json.dumps(r['node_errors'])[:300]}")
        pid = r.get("prompt_id")
        if not pid:
            raise HttpError(f"ComfyUI gave no prompt_id: {str(r)[:200]}")
        return pid

    def wait(self, prompt_id: str, stop=None, poll_s: float = 1.5) -> dict:
        """Wait for a queued prompt; returns its history entry (outputs + status)."""
        end = time.monotonic() + self.timeout_s
        while time.monotonic() < end:
            h = request_json("GET", f"{self.base}/history/{prompt_id}", timeout=30)
            if prompt_id in h:
                entry = h[prompt_id]
                st = entry.get("status", {})
                if st.get("status_str") == "error":
                    msgs = [m for m in st.get("messages", []) if m and m[0] == "execution_error"]
                    detail = msgs[0][1].get("exception_message", "") if msgs else ""
                    raise WorkflowError(f"ComfyUI error: {detail[:300] or 'see ComfyUI log'}")
                if st.get("completed", True):
                    return entry
            if stop is not None and stop.wait(poll_s):
                self.interrupt()
                raise InterruptedError()
            elif stop is None:
                time.sleep(poll_s)
        self.interrupt()
        raise TimeoutError(f"ComfyUI took longer than {self.timeout_s}s")

    def interrupt(self) -> None:
        try:
            request_json("POST", f"{self.base}/interrupt", {}, timeout=10)
        except HttpError:
            pass

    def download(self, f: dict) -> bytes:
        q = urlencode({"filename": f["filename"], "subfolder": f.get("subfolder", ""),
                       "type": f.get("type", "output")})
        return request_bytes(f"{self.base}/view?{q}", timeout=300)


def output_files(entry: dict) -> list[dict]:
    """Every saved file in a history entry (images, gifs/videos from VideoHelperSuite, etc.)."""
    files = []
    for node_out in (entry.get("outputs") or {}).values():
        for key in ("images", "gifs", "videos", "animated", "video"):
            for f in node_out.get(key) or []:
                if isinstance(f, dict) and f.get("filename") and f.get("type", "output") == "output":
                    files.append(f)
    return files


# --------------------------------------------------------------------------- templates
def load_template(path: Path) -> dict:
    try:
        g = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise WorkflowError(f"can't read workflow {path.name}: {e}") from e
    if isinstance(g, dict) and "nodes" in g and "links" in g:
        raise WorkflowError(f"{path.name} is a normal (UI) workflow. In ComfyUI use Workflow > "
                            "Export (API) and drop that file in Workflows/ instead.")
    if isinstance(g, dict) and "prompt" in g and isinstance(g["prompt"], dict):
        g = g["prompt"]
    if not isinstance(g, dict) or not all(isinstance(v, dict) and "class_type" in v for v in g.values()):
        raise WorkflowError(f"{path.name} doesn't look like a ComfyUI API-format workflow.")
    return g


def basic_graph(family: str, steps: int = 0, sampler: str = "dpmpp_2m") -> dict:
    """Built-in text-to-image graph for SD1.5/SDXL-style checkpoints (steps: Setup > Images & video)."""
    sdxl = family != "sd15"
    return {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "{{CHECKPOINT}}"}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "{{PROMPT}}", "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "{{NEGATIVE}}", "clip": ["4", 1]}},
        "5": {"class_type": "EmptyLatentImage",
              "inputs": {"width": "{{WIDTH}}", "height": "{{HEIGHT}}", "batch_size": 1}},
        "3": {"class_type": "KSampler", "inputs": {
            "seed": "{{SEED}}", "steps": steps or (28 if sdxl else 25), "cfg": 6.0 if sdxl else 7.0,
            "sampler_name": sampler, "scheduler": "karras", "denoise": 1.0,
            "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "{{PREFIX}}", "images": ["8", 0]}},
    }


# Built-in video: Wan 2.2 TI2V 5B (Apache 2.0), ComfyUI's own repackaged files.
# Runs on ~8 GB+ graphics cards (ComfyUI offloads what doesn't fit).
WAN_VIDEO = {
    "label": "Wan 2.2 5B", "license": "Apache 2.0", "size_gb": 17.5,
    "files": [
        ("diffusion_models", "wan2.2_ti2v_5B_fp16.safetensors",
         "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/"
         "diffusion_models/wan2.2_ti2v_5B_fp16.safetensors"),
        ("text_encoders", "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
         "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/"
         "text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors"),
        ("vae", "wan2.2_vae.safetensors",
         "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/"
         "vae/wan2.2_vae.safetensors"),
    ],
    "size": (1280, 704), "frames": 121, "fps": 24,      # about 5 seconds
    "negative": ("static, frozen, blurry, low quality, jpeg artifacts, watermark, text, subtitles, "
                 "deformed, extra fingers, bad hands, bad face, messy background, walking backwards"),
}


# Optional "Turbo" add-on for the same model: a LoRA from the Wan2.2-TI2V-5B-Turbo finetune
# (Apache 2.0), packaged for ComfyUI by Kijai. 4 steps and no CFG instead of 20 steps x 2.
WAN_TURBO = {
    "label": "Wan 2.2 5B Turbo add-on", "license": "Apache 2.0", "size_gb": 0.6,
    "file": ("loras", "Wan22_TI2V_5B_Turbo_lora_rank_64_fp16.safetensors",
             "https://huggingface.co/Kijai/WanVideo_comfy/resolve/main/LoRAs/Wan22-Turbo/"
             "Wan22_TI2V_5B_Turbo_lora_rank_64_fp16.safetensors"),
}


def wan_turbo_installed(models_dir: Path | None) -> bool:
    if not models_dir:
        return False
    folder, name, _ = WAN_TURBO["file"]
    return any((models_dir / folder).rglob(name)) if (models_dir / folder).is_dir() else False


def wan_missing(models_dir: Path | None) -> list[tuple[str, str, str]]:
    """The Wan 2.2 5B files that aren't in ComfyUI's models folder yet."""
    if not models_dir:
        return list(WAN_VIDEO["files"])
    return [f for f in WAN_VIDEO["files"] if not any((models_dir / f[0]).rglob(f[1]))]


def wan_video_graph(frames: int = 0, fps: int = 0, steps: int = 20, cfg: float = 5.0,
                    turbo: bool = False) -> dict:
    """Built-in text-to-video graph (ComfyUI's Wan 2.2 5B template, API format).
    turbo=True adds the Turbo LoRA (use steps=4, cfg=1)."""
    w = WAN_VIDEO
    unet, clip, vae = (f[1] for f in w["files"])
    frames = frames or w["frames"]
    frames = max(5, (frames - 1) // 4 * 4 + 1)          # Wan wants 4n+1 frames
    g = {
        "37": {"class_type": "UNETLoader", "inputs": {"unet_name": unet, "weight_dtype": "default"}},
        "38": {"class_type": "CLIPLoader", "inputs": {"clip_name": clip, "type": "wan", "device": "default"}},
        "39": {"class_type": "VAELoader", "inputs": {"vae_name": vae}},
        "48": {"class_type": "ModelSamplingSD3", "inputs": {"shift": 8.0,
                                                            "model": ["60", 0] if turbo else ["37", 0]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "{{PROMPT}}", "clip": ["38", 0]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "{{NEGATIVE}}", "clip": ["38", 0]}},
        "55": {"class_type": "Wan22ImageToVideoLatent", "inputs": {
            "width": "{{WIDTH}}", "height": "{{HEIGHT}}", "length": frames, "batch_size": 1,
            "vae": ["39", 0]}},
        "3": {"class_type": "KSampler", "inputs": {
            "seed": "{{SEED}}", "steps": steps, "cfg": cfg, "sampler_name": "uni_pc", "scheduler": "simple",
            "denoise": 1.0, "model": ["48", 0], "positive": ["6", 0], "negative": ["7", 0],
            "latent_image": ["55", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["39", 0]}},
        "57": {"class_type": "CreateVideo", "inputs": {"images": ["8", 0], "fps": float(fps or w["fps"])}},
        "58": {"class_type": "SaveVideo", "inputs": {"video": ["57", 0], "filename_prefix": "{{PREFIX}}",
                                                     "format": "auto", "codec": "auto"}},
    }
    if turbo:
        g["60"] = {"class_type": "LoraLoaderModelOnly", "inputs": {
            "lora_name": WAN_TURBO["file"][1], "strength_model": 1.0, "model": ["37", 0]}}
    return g


def default_size(family: str) -> tuple[int, int]:
    if family == "wan":
        return WAN_VIDEO["size"]
    return (512, 512) if family == "sd15" else (1024, 1024)


def _has_placeholders(g: dict) -> bool:
    blob = json.dumps(g)
    return any(p in blob for p in PLACEHOLDERS)


def _is_link(v) -> bool:
    return isinstance(v, list) and len(v) == 2 and isinstance(v[0], str)


_TEXT_KEYS = ("text", "text_g", "text_l", "prompt", "positive_prompt")


def _text_node(g: dict, link, depth: int = 0) -> str | None:
    """Follow a conditioning link back to the node that holds the prompt text."""
    if not _is_link(link) or depth > 6 or link[0] not in g:
        return None
    node = g[link[0]]
    ins = node.get("inputs", {})
    if any(isinstance(ins.get(k), str) for k in _TEXT_KEYS):
        return link[0]
    for k in ("conditioning", "positive", "conditioning_to", "conditioning_1", "cond"):
        if _is_link(ins.get(k)):
            found = _text_node(g, ins[k], depth + 1)
            if found:
                return found
    return None


def analyze(g: dict) -> dict:
    """Where the prompt, negative, seed, size, checkpoint and save prefix live in a graph."""
    pos, neg = set(), set()
    for node in g.values():
        ins = node.get("inputs", {})
        if _is_link(ins.get("positive")):
            n = _text_node(g, ins["positive"])
            n and pos.add(n)
        if _is_link(ins.get("negative")):
            n = _text_node(g, ins["negative"])
            n and neg.add(n)
        if node.get("class_type") == "BasicGuider" and _is_link(ins.get("conditioning")):
            n = _text_node(g, ins["conditioning"])
            n and pos.add(n)
    neg -= pos
    if not pos:
        texts = [k for k, v in g.items()
                 if any(isinstance(v.get("inputs", {}).get(t), str) for t in _TEXT_KEYS)]
        if len(texts) == 1:
            pos = set(texts)
    seeds = [(k, s) for k, v in g.items() for s in ("seed", "noise_seed")
             if isinstance(v.get("inputs", {}).get(s), int)]
    sizes = [k for k, v in g.items() if "latent" in v.get("class_type", "").lower()
             and isinstance(v.get("inputs", {}).get("width"), int)]
    ckpts = [(k, key) for k, v in g.items() for key in ("ckpt_name", "unet_name")
             if isinstance(v.get("inputs", {}).get(key), str)]
    saves = [k for k, v in g.items() if isinstance(v.get("inputs", {}).get("filename_prefix"), str)]
    return {"positive": sorted(pos), "negative": sorted(neg), "seeds": seeds, "sizes": sizes,
            "checkpoints": ckpts, "saves": saves}


def check_template(g: dict) -> str:
    """Return '' if Joe can fill this graph, else a plain-English problem."""
    if _has_placeholders(g):
        return "" if "{{PROMPT}}" in json.dumps(g) else "template has placeholders but no {{PROMPT}}"
    a = analyze(g)
    if not a["positive"]:
        return ("can't find the prompt box. Put {{PROMPT}} in your positive prompt text "
                "before exporting, or use a workflow with a normal KSampler.")
    return ""


def template_checkpoint(g: dict) -> str:
    for v in g.values():
        for key in ("ckpt_name", "unet_name"):
            val = v.get("inputs", {}).get(key)
            if isinstance(val, str) and "{{" not in val:
                return val
    return ""


def fill(g: dict, prompt: str, negative: str, seed: int, width: int | None, height: int | None,
         checkpoint: str = "", prefix: str = "Joe") -> dict:
    g = copy.deepcopy(g)
    vals = {"{{PROMPT}}": prompt, "{{NEGATIVE}}": negative, "{{PREFIX}}": prefix,
            "{{CHECKPOINT}}": checkpoint}
    nums = {"{{SEED}}": seed, "{{WIDTH}}": width or 1024, "{{HEIGHT}}": height or 1024}
    templated = _has_placeholders(g)
    if templated:
        for node in g.values():
            ins = node.get("inputs", {})
            for k, v in list(ins.items()):
                if not isinstance(v, str):
                    continue
                if v.strip() in nums:
                    ins[k] = nums[v.strip()]
                    continue
                for ph, rep in vals.items():
                    v = v.replace(ph, rep)
                ins[k] = v
    a = analyze(g)
    if not templated:                       # automatic: write into the found prompt boxes
        for n in a["positive"]:
            ins = g[n]["inputs"]
            for t in _TEXT_KEYS:
                if isinstance(ins.get(t), str):
                    ins[t] = prompt
        for n in a["negative"]:
            ins = g[n]["inputs"]
            for t in _TEXT_KEYS:
                if isinstance(ins.get(t), str) and negative:
                    ins[t] = negative
    for n, key in a["seeds"]:
        g[n]["inputs"][key] = seed
    if width and height:
        for n in a["sizes"]:
            g[n]["inputs"]["width"], g[n]["inputs"]["height"] = width, height
    if checkpoint:
        for n, key in a["checkpoints"]:
            g[n]["inputs"][key] = checkpoint
    for n in a["saves"]:
        g[n]["inputs"]["filename_prefix"] = prefix
    return g


def new_seed(base: str, index: int) -> int:
    base = (base or "").strip().lower()
    if base.isdigit():
        return (int(base) + index) % 2**48
    return random.randrange(1, 2**48)
