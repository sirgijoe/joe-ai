"""The ComfyUI tools: remove background + upscale, edit a picture by asking, restore old photos,
animate a photo, music and sound effects.

Every graph here uses only ComfyUI's own built-in nodes (no custom nodes to install) and follows
ComfyUI's official workflow templates. Each tool needs one model pack; System check and the
Tools form offer it (ask first, license shown). Packs land in ComfyUI's own models folders.
"""
from __future__ import annotations

import json
import mimetypes
import random
import time
import re
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from . import comfy as comfy_mod
from . import makers
from .fsutil import atomic_write_text
from .http import HttpError, request_json

if TYPE_CHECKING:                                    # pragma: no cover
    from .engine import Engine, JobState
    from .mission import Job, Mission

HF = "https://huggingface.co/"


@dataclass(frozen=True)
class Pack:
    id: str
    label: str
    license: str
    size_gb: float                      # rough, for the offer; real sizes come from the download
    files: tuple[tuple[str, str, str, float], ...]     # (models subfolder, file, url, GB)
    note: str = ""


PACKS: dict[str, Pack] = {p.id: p for p in (
    Pack("bg", "BiRefNet background remover", "MIT", 0.9,
         (("background_removal", "birefnet.safetensors",
           HF + "Comfy-Org/BiRefNet/resolve/main/background_removal/birefnet.safetensors", 0.9),)),
    Pack("upscale", "Real-ESRGAN x4 sharpener", "BSD-3-Clause", 0.07,
         (("upscale_models", "RealESRGAN_x4plus.safetensors",
           HF + "Comfy-Org/Real-ESRGAN_repackaged/resolve/main/RealESRGAN_x4plus.safetensors", 0.07),)),
    Pack("edit", "Qwen-Image-Edit 2511 picture editor (+ 4-step Lightning add-on)", "Apache-2.0", 31.0,
         (("diffusion_models", "qwen_image_edit_2511_fp8mixed.safetensors",
           HF + "Comfy-Org/Qwen-Image-Edit_ComfyUI/resolve/main/split_files/diffusion_models/"
                "qwen_image_edit_2511_fp8mixed.safetensors", 20.5),
          ("text_encoders", "qwen_2.5_vl_7b_fp8_scaled.safetensors",
           HF + "Comfy-Org/HunyuanVideo_1.5_repackaged/resolve/main/split_files/text_encoders/"
                "qwen_2.5_vl_7b_fp8_scaled.safetensors", 9.4),
          ("vae", "qwen_image_vae.safetensors",
           HF + "Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/vae/qwen_image_vae.safetensors", 0.25),
          ("loras", "Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors",
           HF + "lightx2v/Qwen-Image-Edit-2511-Lightning/resolve/main/"
                "Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors", 0.85)),
         note="Big: works best with a 12 GB+ graphics card and 32 GB of memory (the rest waits "
              "in normal memory, which is slower)."),
    Pack("video", "Wan 2.2 5B video model", "Apache-2.0", 17.5,
         tuple((f, n, u, {"diffusion_models": 10.0, "text_encoders": 6.3, "vae": 1.3}[f])
               for f, n, u in comfy_mod.WAN_VIDEO["files"])),
    Pack("music", "ACE-Step 1.5 music model (Turbo, all-in-one)", "MIT", 10.0,
         (("checkpoints", "ace_step_1.5_turbo_aio.safetensors",
           HF + "Comfy-Org/ace_step_1.5_ComfyUI_files/resolve/main/checkpoints/ace_step_1.5_turbo_aio.safetensors",
           10.0),)),
    Pack("sfx", "Stable Audio Open 1.0 sound-effects model", "Stability AI Community License", 5.3,
         (("checkpoints", "stable-audio-open-1.0.safetensors",
           HF + "Comfy-Org/stable-audio-open-1.0_repackaged/resolve/main/stable-audio-open-1.0.safetensors", 4.85),
          ("text_encoders", "t5-base.safetensors",
           HF + "ComfyUI-Wiki/t5-base/resolve/main/t5-base.safetensors", 0.45)),
         note="Free for people and businesses under US$1 million a year in revenue; bigger "
              "businesses need Stability AI's paid license."),
    # ---- batch 3: new model families (dev123). URLs as in ComfyUI's official workflow templates.
    Pack("flux2", "FLUX.2 [klein] 4B picture model", "Apache-2.0", 16.0,
         (("diffusion_models", "flux-2-klein-4b.safetensors",
           HF + "Comfy-Org/flux2-klein/resolve/main/split_files/diffusion_models/flux-2-klein-4b.safetensors", 7.8),
          ("text_encoders", "qwen_3_4b.safetensors",
           HF + "Comfy-Org/flux2-klein/resolve/main/split_files/text_encoders/qwen_3_4b.safetensors", 8.0),
          ("vae", "flux2-vae.safetensors",
           HF + "Comfy-Org/flux2-dev/resolve/main/split_files/vae/flux2-vae.safetensors", 0.3)),
         note="Draws hands, faces and words in pictures far better than the older models, in about "
              "4 steps. Comfortable on 12 GB graphics cards; smaller cards work but slower."),
    Pack("sketch", "ControlNet Union SDXL ProMax (sketch to picture)", "Apache-2.0", 2.5,
         (("controlnet", "controlnet-union-sdxl-promax.safetensors",
           HF + "xinsir/controlnet-union-sdxl-1.0/resolve/main/diffusion_pytorch_model_promax.safetensors", 2.5),),
         note="Works with the SDXL picture models Joe already uses."),
    Pack("illusion", "QR Code Monster SDXL (hidden-picture illusions)", "OpenRAIL++", 5.0,
         (("controlnet", "control_v1p_sdxl_qrcode_monster.safetensors",
           HF + "monster-labs/control_v1p_sdxl_qrcode_monster/resolve/main/diffusion_pytorch_model.safetensors", 5.0),),
         note="Works with the SDXL picture models Joe already uses. Its license forbids harmful or "
              "deceptive uses."),
    Pack("video-restyle", "Wan 2.2 Fun Control 5B (restyle a video)", "Apache-2.0", 17.5,
         (("diffusion_models", "wan2.2_fun_control_5B_bf16.safetensors",
           HF + "Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/diffusion_models/"
                "wan2.2_fun_control_5B_bf16.safetensors", 10.0),
          comfy_mod.WAN_VIDEO["files"][1] + (6.3,), comfy_mod.WAN_VIDEO["files"][2] + (1.3,)),
         note="Shares its text reader and decoder with Joe's video model, so it's about 10 GB when "
              "that one is already installed."),
    Pack("3d", "Hunyuan3D 2.1 (picture to 3D model)", "Tencent Hunyuan 3D 2.1 Community License", 4.6,
         (("checkpoints", "hunyuan_3d_v2.1.safetensors",
           HF + "Comfy-Org/hunyuan3D_2.1_repackaged/resolve/main/hunyuan_3d_v2.1.safetensors", 4.6),),
         note="Makes the shape only (a plain white model, no colors). Free to use, but its license "
              "does not cover the European Union, the United Kingdom or South Korea; check the "
              "license before selling what you make."),
)}

# Which packs each tool needs (all of them), and which it can use if they're there.
TOOL_PACKS = {"remove-bg": ("bg",), "edit-picture": ("edit",), "restore-photo": ("edit",),
              "animate-photo": ("video",), "music": (), "fix-spot": ("edit",), "merge-pictures": ("edit",),
              "relight": ("edit",), "restyle": ("edit",), "redraw": ("edit",), "make-bigger": ("edit",),
              "character-scenes": ("edit",), "character-spin": ("edit",),
              "sketch-to-picture": ("sketch",), "illusion-art": ("illusion",),
              "restyle-video": ("video-restyle",), "make-3d": ("3d",)}
# the tools that run the Qwen picture editor (big: free the card first, text encoder on the CPU
# under 16 GB, a smaller retry after running out of memory)
EDITORS = ("edit-picture", "restore-photo", "fix-spot", "merge-pictures", "relight", "restyle", "redraw",
           "make-bigger", "character-scenes", "character-spin")
MASK_SUFFIX = "-mask.png"          # Tools tab > MARK THE SPOT saves <picture>-mask.png next to it
SPIN_VIEWS = (("front", "front view, facing the viewer"),
              ("three-quarter-left", "three-quarter view, turned to the left"),
              ("left", "left side profile view"),
              ("back", "back view, facing away from the viewer"),
              ("right", "right side profile view"),
              ("three-quarter-right", "three-quarter view, turned to the right"))
SAME_CHARACTER = ("the exact same character as in the picture: same face, hair, body shape, outfit, colors "
                  "and art style")
OPTIONAL_PACKS = {"remove-bg": ("upscale",), "restore-photo": ("upscale",), "make-3d": ("bg",)}
COMFY_TOOLS = tuple(TOOL_PACKS)

RESTORE_PROMPT = ("Restore this old photograph: remove scratches, dust, tears, stains and creases, "
                  "and fix faded and uneven areas. Keep every person's face, expression, hair, pose "
                  "and clothing, and the whole scene, exactly as they are in the photo. Do not redraw "
                  "faces or add detail that isn't there: a soft or blurry face stays the same face.")

COLORIZE = (" Then colorize it with natural, realistic colors that fit the time period, "
            "with true-to-life skin tones.")
KEEP_BW = (" Keep its own colors: if it is black and white or sepia, keep it that way; if it is a "
           "faded color photo, bring its colors back to how they looked when it was new.")


# --------------------------------------------------------------------------- packs
def pack_missing(models_dir: Path | None, pack_id: str) -> list[tuple[str, str, str, float]]:
    p = PACKS[pack_id]
    if not models_dir:
        return list(p.files)
    out = []
    for f in p.files:
        folder = models_dir / f[0]
        if not (folder.is_dir() and any(folder.rglob(f[1]))):
            out.append(f)
    return out


def pack_ready(models_dir: Path | None, pack_id: str) -> bool:
    return bool(models_dir) and not pack_missing(models_dir, pack_id)


def needed_packs(tool_id: str, options: set[str] | None = None) -> tuple[str, ...]:
    if tool_id == "music":
        kind = (options or set())
        return ("sfx",) if "sfx" in kind else ("music",)
    return TOOL_PACKS.get(tool_id, ())


def pack_size(pack_id: str, models_dir: Path | None = None) -> float:
    """GB still to download: the whole pack, or (models folder known) only the missing files,
    so a pack that shares files with one already installed says its real size."""
    p = PACKS[pack_id]
    if not models_dir:
        return p.size_gb
    missing = pack_missing(models_dir, pack_id)
    return p.size_gb if len(missing) == len(p.files) else round(sum(f[3] for f in missing), 2)


def _size_words(gb: float) -> str:
    return f"about {gb:.0f} GB" if gb >= 1 else f"about {max(1, round(gb * 1000))} MB"


def pack_offer(pack_id: str, models_dir: Path | None = None) -> str:
    p = PACKS[pack_id]
    return f"{p.label} ({_size_words(pack_size(pack_id, models_dir))}, {p.license})" + (f". {p.note}" if p.note else "")


def pack_short(pack_id: str, models_dir: Path | None = None) -> str:
    """'the Qwen-Image-Edit picture editor, about 31 GB' style, for one-line hints."""
    p = PACKS[pack_id]
    return f"{p.label.split(' (')[0]} ({_size_words(pack_size(pack_id, models_dir))})"


def download_pack(settings, pack_id: str, log, approved: bool = False, progress=None) -> bool:
    """Download a model pack into ComfyUI's models folders (asks first: approved must be True)."""
    if not approved:
        raise PermissionError("download needs the user's approval")
    from .doctor import _download, comfy_models_dir
    mdir = comfy_models_dir(settings)
    if not mdir:
        log("Can't find ComfyUI's models folder. Install ComfyUI first, or set its folder in Setup.")
        return False
    p = PACKS[pack_id]
    missing = pack_missing(mdir, pack_id)
    if not missing:
        log(f"{p.label} is already installed.")
        return True
    log(f"Downloading {pack_offer(pack_id, mdir)}. From Hugging Face; nothing about you is sent.")
    all_b = sum(f[3] for f in missing) * 2**30
    done = 0.0
    for folder, name, url, gb in missing:
        log(f"  {name} -> models/{folder}")
        if not _download(url, mdir / folder / name, log, progress, int(done), int(all_b)):
            return False
        done += gb * 2**30
    log(f"{p.label} is ready. Restart ComfyUI once so it sees the new files.")
    return True


# --------------------------------------------------------------------------- ComfyUI I/O
def upload_image(base: str, path: Path, timeout: float = 120) -> str:
    """Send a picture to ComfyUI's input folder; returns the name to use in LoadImage."""
    boundary = uuid.uuid4().hex
    name = f"joe_{uuid.uuid4().hex[:8]}_{path.name}"
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{name}\"\r\n"
            f"Content-Type: {ctype}\r\n\r\n").encode() + path.read_bytes() + (
        f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue"
        f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"type\"\r\n\r\ninput"
        f"\r\n--{boundary}--\r\n").encode()
    req = urllib.request.Request(base.rstrip("/") + "/upload/image", data=body, method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            info = json.loads(r.read().decode("utf-8") or "{}")
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise HttpError(f"couldn't send {path.name} to ComfyUI: {e}") from e
    sub = info.get("subfolder") or ""
    return f"{sub}/{info.get('name', name)}" if sub else info.get("name", name)


def outputs_of(entry: dict) -> list[dict]:
    """Saved files in a history entry, audio included."""
    files = comfy_mod.output_files(entry)
    for node_out in (entry.get("outputs") or {}).values():
        for f in (node_out.get("audio") or []) + (node_out.get("3d") or []):
            if isinstance(f, dict) and f.get("filename") and f.get("type", "output") == "output":
                files.append(f)
    return files


# --------------------------------------------------------------------------- graphs
def _load(image: str) -> dict:
    return {"class_type": "LoadImage", "inputs": {"image": image}}


def _upscale_nodes(g: dict, src: list, factor: int) -> list:
    """Real-ESRGAN x4, then scaled down to the asked factor (2 = cleaner, smaller files)."""
    g["u1"] = {"class_type": "UpscaleModelLoader", "inputs": {"model_name": PACKS["upscale"].files[0][1]}}
    g["u2"] = {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["u1", 0], "image": src}}
    if factor >= 4:
        return ["u2", 0]
    g["u3"] = {"class_type": "ImageScaleBy", "inputs": {"image": ["u2", 0], "upscale_method": "lanczos",
                                                        "scale_by": factor / 4}}
    return ["u3", 0]


def bg_graph(image: str, keep: str = "transparent", upscale: int = 0, prefix: str = "Joe/tool") -> dict:
    """Background removal (BiRefNet), optional upscale first. keep: transparent | white."""
    g: dict = {"1": _load(image)}
    src = ["1", 0]
    if upscale:
        src = _upscale_nodes(g, src, upscale)
    g["2"] = {"class_type": "LoadBackgroundRemovalModel", "inputs": {"bg_removal_name": PACKS["bg"].files[0][1]}}
    g["3"] = {"class_type": "RemoveBackground", "inputs": {"bg_removal_model": ["2", 0], "image": src}}
    g["4"] = {"class_type": "InvertMask", "inputs": {"mask": ["3", 0]}}
    g["5"] = {"class_type": "JoinImageWithAlpha", "inputs": {"image": src, "alpha": ["4", 0]}}
    g["9"] = {"class_type": "SaveImage", "inputs": {"images": ["5", 0], "filename_prefix": prefix}}
    return g


def upscale_graph(image: str, factor: int = 2, prefix: str = "Joe/tool") -> dict:
    g: dict = {"1": _load(image)}
    out = _upscale_nodes(g, ["1", 0], factor)
    g["9"] = {"class_type": "SaveImage", "inputs": {"images": out, "filename_prefix": prefix}}
    return g


def edit_graph(image: str, instruction: str, seed: int, fast: bool = True, upscale: int = 0,
               prefix: str = "Joe/tool", megapixels: float = 0, encoder_on_cpu: bool = False,
               denoise: float = 1.0, passes: int = 1, extra_images: list[str] | None = None) -> dict:
    """Qwen-Image-Edit 2511 (ComfyUI's template). fast = Lightning add-on: 4 steps, cfg 1.
    megapixels > 0 works on a smaller copy; encoder_on_cpu keeps the 9 GB text encoder in normal
    memory (slower to read the request, but the picture model gets the whole graphics card).
    Both are used on cards under 16 GB and for the retry after running out of memory."""
    unet, clip, vae, lora = (f[1] for f in PACKS["edit"].files)
    g: dict = {
        "41": _load(image),
        # about 1 megapixel in the photo's own shape (the template's preset sizes could squash it)
        "160": {"class_type": "ImageScaleToTotalPixels", "inputs": {
            "image": ["41", 0], "upscale_method": "lanczos", "megapixels": megapixels or 1.0,
            "resolution_steps": 16}},
        "161": {"class_type": "UNETLoader", "inputs": {"unet_name": unet, "weight_dtype": "default"}},
        "162": {"class_type": "CLIPLoader", "inputs": {"clip_name": clip, "type": "qwen_image",
                                              "device": "cpu" if encoder_on_cpu else "default"}},
        "146": {"class_type": "VAELoader", "inputs": {"vae_name": vae}},
        "145": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["161", 0], "shift": 3.1}},
        "152": {"class_type": "CFGNorm", "inputs": {"model": ["145", 0], "strength": 1.0}},
        "151": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {
            "clip": ["162", 0], "prompt": instruction, "vae": ["146", 0], "image1": ["160", 0]}},
        "149": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {
            "clip": ["162", 0], "prompt": "", "vae": ["146", 0], "image1": ["160", 0]}},
        "148": {"class_type": "FluxKontextMultiReferenceLatentMethod", "inputs": {
            "conditioning": ["151", 0], "reference_latents_method": "index_timestep_zero"}},
        "147": {"class_type": "FluxKontextMultiReferenceLatentMethod", "inputs": {
            "conditioning": ["149", 0], "reference_latents_method": "index_timestep_zero"}},
        "156": {"class_type": "VAEEncode", "inputs": {"pixels": ["160", 0], "vae": ["146", 0]}},
        "169": {"class_type": "KSampler", "inputs": {
            "seed": seed, "steps": 4 if fast else 40, "cfg": 1.0 if fast else 3.0,
            "sampler_name": "euler", "scheduler": "simple", "denoise": denoise,
            "model": ["153", 0] if fast else ["152", 0], "positive": ["148", 0],
            "negative": ["147", 0], "latent_image": ["156", 0]}},
        "158": {"class_type": "VAEDecode", "inputs": {"samples": ["169", 0], "vae": ["146", 0]}},
    }
    for n, extra in enumerate((extra_images or [])[:2], start=2):     # picture 2 and 3 (merge, style example)
        g[f"41_{n}"] = _load(extra)
        g[f"160_{n}"] = {"class_type": "ImageScaleToTotalPixels", "inputs": {
            "image": [f"41_{n}", 0], "upscale_method": "lanczos", "megapixels": megapixels or 1.0,
            "resolution_steps": 16}}
        g["151"]["inputs"][f"image{n}"] = [f"160_{n}", 0]
        g["149"]["inputs"][f"image{n}"] = [f"160_{n}", 0]
    last = "169"
    for n in range(2, max(1, passes) + 1):        # small passes, each starting from the last one
        k = f"169_{n}"
        g[k] = json.loads(json.dumps(g["169"]))
        g[k]["inputs"].update(seed=seed + n, latent_image=[last, 0])
        last = k
    g["158"]["inputs"]["samples"] = [last, 0]
    if fast:
        g["153"] = {"class_type": "LoraLoaderModelOnly", "inputs": {
            "model": ["152", 0], "lora_name": lora, "strength_model": 1.0}}
    out = ["158", 0]
    if upscale:
        out = _upscale_nodes(g, out, upscale)
    g["9"] = {"class_type": "SaveImage", "inputs": {"images": out, "filename_prefix": prefix}}
    return g


def video_size(width: int, height: int) -> tuple[int, int]:
    """Wan 2.2 5B's sizes, matched to the photo's shape."""
    if not width or not height:
        return 1280, 704
    r = width / height
    if r > 1.2:
        return 1280, 704
    if r < 0.83:
        return 704, 1280
    return 960, 960


def animate_graph(image: str, prompt: str, negative: str, seed: int, width: int, height: int,
                  frames: int = 0, steps: int = 20, cfg: float = 5.0, turbo: bool = False,
                  prefix: str = "Joe/tool") -> dict:
    g = comfy_mod.wan_video_graph(frames=frames, steps=steps, cfg=cfg, turbo=turbo)
    g["56"] = _load(image)
    g["55"]["inputs"].update(width=width, height=height, start_image=["56", 0])
    g["6"]["inputs"]["text"] = prompt
    g["7"]["inputs"]["text"] = negative
    g["3"]["inputs"]["seed"] = seed
    g["58"]["inputs"]["filename_prefix"] = prefix
    return g


def music_graph(tags: str, seconds: float, seed: int, bpm: int = 0, prefix: str = "Joe/tool") -> dict:
    """ACE-Step 1.5 Turbo (ComfyUI's template), instrumental."""
    ck = PACKS["music"].files[0][1]
    return {
        "97": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ck}},
        "94": {"class_type": "TextEncodeAceStepAudio1.5", "inputs": {
            "clip": ["97", 1], "tags": tags, "lyrics": "[Instrumental]", "seed": seed,
            "bpm": bpm or 110, "duration": float(seconds), "timesignature": "4", "language": "en",
            "keyscale": "C major", "generate_audio_codes": True, "cfg_scale": 2.0,
            "temperature": 0.85, "top_p": 0.9, "top_k": 0, "min_p": 0.0}},
        "78": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["97", 0], "shift": 3.0}},
        "47": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["94", 0]}},
        "98": {"class_type": "EmptyAceStep1.5LatentAudio", "inputs": {"seconds": float(seconds), "batch_size": 1}},
        "3": {"class_type": "KSampler", "inputs": {
            "seed": seed, "steps": 8, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple",
            "denoise": 1.0, "model": ["78", 0], "positive": ["94", 0], "negative": ["47", 0],
            "latent_image": ["98", 0]}},
        "18": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["3", 0], "vae": ["97", 2]}},
        "9": {"class_type": "SaveAudioMP3", "inputs": {"audio": ["18", 0], "filename_prefix": prefix,
                                                       "quality": "V0"}},
    }


def sfx_graph(prompt: str, seconds: float, seed: int, prefix: str = "Joe/tool") -> dict:
    """Stable Audio Open 1.0 (ComfyUI's template)."""
    ck, t5 = (f[1] for f in PACKS["sfx"].files)
    return {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ck}},
        "10": {"class_type": "CLIPLoader", "inputs": {"clip_name": t5, "type": "stable_audio", "device": "default"}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["10", 0]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "low quality, noise, distorted", "clip": ["10", 0]}},
        "11": {"class_type": "EmptyLatentAudio", "inputs": {"seconds": float(min(seconds, 47)), "batch_size": 1}},
        "3": {"class_type": "KSampler", "inputs": {
            "seed": seed, "steps": 50, "cfg": 5.0, "sampler_name": "dpmpp_3m_sde_gpu",
            "scheduler": "exponential", "denoise": 1.0, "model": ["4", 0], "positive": ["6", 0],
            "negative": ["7", 0], "latent_image": ["11", 0]}},
        "12": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveAudioMP3", "inputs": {"audio": ["12", 0], "filename_prefix": prefix,
                                                       "quality": "V0"}},
    }


# --------------------------------------------------------------------------- helpers
def picture_size(p: Path) -> tuple[int, int]:
    """Width and height of a JPG/PNG/WebP without extra packages (0, 0 if unknown)."""
    try:
        data = p.read_bytes()[:256 * 1024]
    except OSError:
        return 0, 0
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        if data[12:16] == b"VP8X":
            return 1 + int.from_bytes(data[24:27], "little"), 1 + int.from_bytes(data[27:30], "little")
        if data[12:16] == b"VP8 ":
            return int.from_bytes(data[26:28], "little") & 0x3FFF, int.from_bytes(data[28:30], "little") & 0x3FFF
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            seg = int.from_bytes(data[i + 2:i + 4], "big")
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                return int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big")
            i += 2 + seg
    return 0, 0


def pieces_from(text: str) -> list[str]:
    """One piece of music / sound per non-empty line of the description."""
    import re
    return [ln.strip(" -•*\t") for ln in re.split(r"\n|\s\|\s", text or "") if ln.strip(" -•*\t")]


def _seed(job: "Job", i: int) -> int:
    return comfy_mod.new_seed(job.seed, i) if getattr(job, "seed", "") else random.randrange(1, 2**31)


# --------------------------------------------------------------------------- runner
BIG_TOOLS = EDITORS + ("animate-photo", "restyle-video", "make-3d")
LONG_TOOLS = ("animate-photo", "restyle-video")      # at least an hour before ComfyUI is given up on
SMALL_MP = 0.6          # retry size (megapixels) for edit/restore after running out of memory
BIG_CARD_GB = 16        # below this the editor's text encoder runs on the processor from the start


def card_gb(base: str = "") -> float:
    """Graphics memory in GB: ComfyUI's own answer first (the card it really uses), then Joe's."""
    if base:
        try:
            devs = request_json("GET", f"{base}/system_stats", timeout=10).get("devices") or []
            total = max((float(d.get("vram_total") or 0) for d in devs
                         if str(d.get("type", "")).lower() != "cpu"), default=0)
            if total:
                return round(total / 1024 ** 3, 1)
        except (HttpError, TypeError, ValueError, AttributeError):
            pass
    try:
        from .hardware import vram_total_gb
        return vram_total_gb()
    except Exception:                           # noqa: BLE001 (unknown card)
        return 0.0


def small_card(base: str = "") -> bool:
    gb = card_gb(base)
    return 0 < gb < BIG_CARD_GB


def out_of_memory(err: object) -> bool:
    t = str(err).lower()
    return "allocation on device" in t or "out of memory" in t or "outofmemory" in t


OOM_HINT = ("The graphics card ran out of memory. Close games, video editors and other AI programs "
            "and run it again. If it keeps happening, this tool needs more graphics memory than "
            "this PC has free.")


def _free(engine, client) -> None:
    """Unload ComfyUI's cached models (a big tool after another needs the whole card)."""
    try:
        client.free()
        time.sleep(3)
    except Exception as e:                      # noqa: BLE001 (best effort)
        engine.log(f"  Couldn't ask ComfyUI to free memory: {e}")


# True to the photo: only what a darkroom would do. Each channel is stretched back to full range
# (undoes fading and the pink/orange cast of old prints), a little contrast and color, light grain
# smoothing, a plain resize and a mild sharpen. Nothing is redrawn, so faces stay exactly theirs.
_FIX = "normalize=independence=1:strength=1"
# Half-strength gray-world white balance: takes out pink/orange/green casts without making the
# photo cold (a full correction over-blues grass and sky).
_CAST = ("split[ca][cb];[cb]format=gbrpf32le,grayworld,format=yuv444p[cg];[ca]format=yuv444p[cc];"
         "[cc][cg]blend=all_mode=normal:all_opacity=0.5")
# A photographer's rounds: one soft blur hides the print's dots and grain, then rounds of
# edge-keeping smoothing (bilateral: smooths flat areas, leaves edges like hair and leaves) plus a
# sharpen. Picked on a real 1980 print: sharper trees and face than blur-only, dots still gone.
_FIRST = "gblur=sigma=1.0"
# Thin scratches and dust: a pixel far off from its row neighbours' median is a scratch or a speck,
# so it takes the median's value; everything else is left exactly as it was. Only used when a photo
# really has scratches (scratch_score), because on a clean photo it would only nibble fine lines.
SCRATCH_FIX = ("format=gbrp,split[sa][sb];[sb]median=radius=3:radiusV=0[sm];"
               "[sa][sm]blend=all_expr='if(gt(abs(A-B),28),B,A)'")
SCRATCHY = 0.5           # percent of the photo that looks like scratches/dust before Joe cleans them
_ROUND = "bilateral=sigmaS=1.5:sigmaR=0.06,cas=0.5"
_ROUND_OLD = "gblur=sigma=0.8,cas=0.5"       # for an FFmpeg too old to have bilateral
ROUNDS = 3
TRUE_LEVELS = {   # contrast and color, applied ONCE (rounds repeat only blur + sharpen)
    # faded prints: deep blacks back, gentle color (a strong color boost turned the grass yellow on a
    # real 1980 print; this was tuned on it, side by side with the old strong and medium)
    "strong": "eq=contrast=1.25:brightness=-0.03:gamma=0.95:saturation=1.15",
    "medium": "eq=contrast=1.12:gamma=0.97:saturation=1.15",
    "light": "eq=contrast=1.04:saturation=1.05",                                # still has its blacks
}


def measure(ffmpeg: str, src: Path) -> dict:
    """Brightness numbers of the photo (FFmpeg signalstats): YLOW = how dark its darkest tenth is
    (0-255; a faded print's blacks have turned grey, so it reads high). {} if unreadable."""
    import subprocess
    from .system import no_window_flags
    try:
        r = subprocess.run([ffmpeg, "-v", "info", "-noautorotate", "-i", str(src), "-frames:v", "1", "-vf",
                            "signalstats,metadata=print", "-f", "null", "-"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=120, creationflags=no_window_flags())
    except (OSError, subprocess.SubprocessError):
        return {}
    import re as _re
    return {k: float(v) for k, v in _re.findall(r"lavfi\.signalstats\.(\w+)=([\d.]+)", r.stderr or "")}


def auto_level(stats: dict) -> str:
    low = stats.get("YLOW")
    if low is None:
        return "medium"
    return "strong" if low >= 75 else "medium" if low >= 55 else "light"


# "Keep sepia tone": the per-channel stretch and the cast fix can turn a sepia print grey, so
# the photo is restored as black and white and the warm brown tone is put back at the end (on
# grey, red stays, green and blue drop a little). Auto-detecting sepia wasn't reliable.
SEPIA_TONE = "hue=s=0,colorchannelmixer=rr=1:rg=0:rb=0:gr=0:gg=0.89:gb=0:br=0:bg=0:bb=0.72"


def true_restore_command(ffmpeg: str, src: Path, dest: Path, turn: int = 1, factor: int = 0,
                         level: str = "strong", cast: bool = True, sepia: bool = False,
                         whites: str = "", scratches: bool = False) -> list[str]:
    from .tools import _TURN
    parts = ([_TURN[turn]] if turn in _TURN else []) + [_FIX]
    if cast and not sepia:
        parts.append(_CAST)
    if scratches:                                  # after the color fix, which reads the photo as it was
        parts.append(SCRATCH_FIX)
    parts += [TRUE_LEVELS.get(level, TRUE_LEVELS["medium"]), _FIRST] + [_ROUND if cast else _ROUND_OLD] * ROUNDS
    if whites and not sepia:
        parts.append(whites)                       # the photo's own whites made white (white_fix)
    if sepia:
        parts.append(SEPIA_TONE)
    if factor:
        parts.append(f"scale=iw*{factor}:ih*{factor}:flags=lanczos")
    parts += ["cas=0.3", "format=rgb24"]
    return [ffmpeg, "-y", "-v", "error", "-noautorotate", "-i", str(src), "-filter_complex", ",".join(parts),
            "-frames:v", "1", str(dest)]


def scratch_score(ffmpeg: str, img: Path) -> float:
    """About how much of the photo (percent) is thin scratches and dust. 0.0 when unsure."""
    import subprocess
    from .system import no_window_flags
    try:
        r = subprocess.run([ffmpeg, "-v", "info", "-noautorotate", "-i", str(img), "-filter_complex",
                            "format=gray,split[a][b];[b]median=radius=3:radiusV=0[m];"
                            "[a][m]blend=all_expr='if(gt(abs(A-B),28),255,0)',signalstats,"
                            "metadata=print:key=lavfi.signalstats.YAVG", "-frames:v", "1", "-f", "null", "-"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
                           creationflags=no_window_flags())
    except (OSError, subprocess.SubprocessError):
        return 0.0
    m = re.findall(r"YAVG=([0-9.]+)", r.stderr or "")
    return float(m[-1]) / 255 * 100 if m else 0.0


def white_fix(ffmpeg: str, img: Path) -> str:
    """Use the photo's own whites as the guide: the brightest nearly-colorless parts (sky, a white
    shirt, the print's border) should come out white, not minty or yellow. Returns a colorbalance
    filter that moves only the highlights there (grass and faces are barely touched), or '' when
    the photo has no such whites or they're already white."""
    import subprocess
    from .system import no_window_flags
    try:
        r = subprocess.run([ffmpeg, "-v", "error", "-i", str(img), "-vf", "scale=128:128:flags=area,format=rgb24",
                            "-f", "rawvideo", "-"], capture_output=True, timeout=120, creationflags=no_window_flags())
    except (OSError, subprocess.SubprocessError):
        return ""
    d = r.stdout or b""
    px = [(d[i], d[i + 1], d[i + 2]) for i in range(0, len(d) - 2, 3)]
    if len(px) < 1000:
        return ""
    px.sort(key=lambda p: p[0] * 0.3 + p[1] * 0.59 + p[2] * 0.11, reverse=True)
    top = [p for p in px[:len(px) // 10] if max(p) >= 170 and max(p) < 254 and (max(p) - min(p)) / max(p) < 0.12]
    if len(top) < len(px) // 100:                  # under 1% of the photo: no real whites to go by
        return ""
    m = [sum(p[i] for p in top) / len(top) for i in range(3)]
    t = sum(m) / 3
    if max(abs(t - c) for c in m) < 3:
        return ""
    # colorbalance's highlight sliders move bright parts by about 200 levels per 1.0 (measured)
    rh, gh, bh = (max(-0.1, min(0.1, (t - c) / 200)) for c in m)
    # green only a little: pulling green out of the highlights turns sunlit grass and leaves purple
    gh = max(-0.015, min(0.015, gh / 2))
    return f"colorbalance=rh={rh:.3f}:gh={gh:.3f}:bh={bh:.3f}"


def restore_is_true(job) -> bool:
    from .tools import chosen_options, option_value
    return (option_value(job, "method") or "true") != "ai" and "colorize" not in chosen_options(job)


def run_true_restore(engine, job, st, files, keys):
    import subprocess
    from .doctor import ffmpeg_exe
    from .engine import Stopped
    from .system import no_window_flags
    from .tools import _finish, chosen_options, jpeg_orientation, option_value, tool_dir
    from .mission import slug
    ffmpeg = ffmpeg_exe(engine.s.comfy.ffmpeg)
    if not ffmpeg:
        st.status, st.note = "failed", "needs FFmpeg (Setup > System check installs it)"
        engine.log(f"'{job.name}' failed: {st.note}")
        return st
    up = option_value(job, "upscale") or "none"
    factor = int(up[0]) if up[:1] in ("2", "4") else 0
    folder = tool_dir(engine, job, st)
    st.status = "running"
    st.started = st.started or datetime.now().isoformat(timespec="seconds")
    engine._save_state(job, st)
    engine.log(f"Starting '{job.name}': {len(files)} photo(s), true to the photo (no AI redraw) -> {st.output}")
    failed: list[str] = []
    stems = [it["stem"] for it in unique_stems([{"stem": slug(f.stem)} for f in files])]
    try:
        for i, (src, key) in enumerate(zip(files, keys)):
            if key in st.titles:
                continue
            if engine.stop.is_set():
                raise Stopped()
            engine._progress(f"{job.name}: {i + 1}/{len(files)} {src.name}")
            dest = folder / f"{stems[i]}-restored.png"
            turn = jpeg_orientation(src) if src.suffix.lower() in (".jpg", ".jpeg") else 1
            want = option_value(job, "strength") or "auto"
            stats = measure(ffmpeg, src) if want == "auto" else {}
            level = auto_level(stats) if want == "auto" else want
            if want == "auto":
                low = stats.get("YLOW")
                engine.log(f"  {src.name}: darkest parts at {low:.0f} of 255 -> {level}"
                           if low is not None else f"  {src.name}: couldn't measure it -> {level}")
            ok, err = False, ""
            sepia = "sepia" in chosen_options(job)
            scratchy = scratch_score(ffmpeg, src) >= SCRATCHY
            if scratchy:
                engine.log(f"  {src.name}: thin scratches and dust found -> cleaning them")
            for cast in (True, False):              # an older FFmpeg: skip the newer filters
                try:
                    p = subprocess.run(true_restore_command(ffmpeg, src, dest, turn, factor, level, cast,
                                                            sepia, scratches=scratchy and cast),
                                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
                                       creationflags=no_window_flags())
                    ok = p.returncode == 0 and dest.exists()
                    err = (p.stderr or "").strip()[:200]
                except (OSError, subprocess.SubprocessError) as e:
                    ok, err = False, str(e)
                if ok:
                    break
            if ok and cast and not sepia:                # second look: are the whites white?
                wf = white_fix(ffmpeg, dest)
                if wf:
                    try:
                        p2 = subprocess.run(true_restore_command(ffmpeg, src, dest, turn, factor, level, True,
                                                                 sepia, wf, scratches=scratchy),
                                            capture_output=True, text=True, encoding="utf-8", errors="replace",
                                            timeout=600, creationflags=no_window_flags())
                        if p2.returncode == 0:
                            engine.log(f"  {src.name}: whites balanced against the photo's own white parts")
                    except (OSError, subprocess.SubprocessError):
                        pass
            if not ok:
                failed.append(f"{src.name}: {err or 'FFmpeg failed'}")
                engine.log(f"  {src.name}: {err or 'FFmpeg failed'}")
                continue
            st.titles.append(key)
            st.media_files.append(dest.name)
            st.items += 1
            engine._save_state(job, st)
            engine.log(f"  {src.name} -> {dest.name}")
        atomic_write_text(folder / "about.txt",
                          f"# {job.name}\n\nRestored by Joe on {datetime.now():%Y-%m-%d %H:%M}, true to the photo:"
                          "\nfading and color cast undone, grain smoothed, rounds of edge-keeping smoothing + sharpen"
                          + (f", {factor}x bigger" if factor else "")
                          + (", warm sepia tone put back" if "sepia" in chosen_options(job) else "")
                          + ", mild sharpening. Thin scratches and dust specks are cleaned when a photo has "
                          "them.\nNothing was redrawn by AI. Wide scratches, tears and date stamps stay: for "
                          "those, run it again with 'AI repair' (it can change faces).\n")
    except Stopped:
        st.status, st.note = "stopped", f"stopped after {len(st.titles)} of {len(files)}"
        engine._save_state(job, st)
        engine.log(f"'{job.name}' {st.note}")
        return st
    return _finish(engine, job, st, len(files), failed)


def run(engine: "Engine", mission: "Mission", job: "Job", st: "JobState") -> "JobState":
    """One runner for all five tools: inputs -> ComfyUI graph per item -> files in the task folder."""
    from .doctor import comfy_models_dir
    from .engine import Stopped
    from .mission import slug
    from .tools import _finish, _key, chosen_options, option_value, resolve_inputs, tool_dir  # noqa: F401

    tid = job.type
    opts = chosen_options(job)
    kind = option_value(job, "kind") if tid == "music" else ""
    if tid == "music":
        items = pieces_from(job.format)
        if not items:
            st.status, st.note = "failed", "say what music or sound you want (one per line)"
            engine.log(f"'{job.name}' failed: {st.note}")
            return st
        keys = [f"{i + 1:02d} {t[:60]}" for i, t in enumerate(items)]
    else:
        files, problems = resolve_inputs(engine, job)
        for pr in problems:
            engine.log(f"  INPUT: {pr}")
        if not files and tid not in makers.NO_INPUT_OK:
            st.status, st.note = "failed", "no pictures to use" + (f" ({problems[0]})" if problems else "")
            engine.log(f"'{job.name}' failed: {st.note}")
            return st
        items, keys = files, [_key(engine, f) for f in files]
    if tid == "restore-photo" and restore_is_true(job):
        return run_true_restore(engine, job, st, items, keys)
    if tid in NEW_EDITORS or tid in makers.TOOLS:
        items, keys, why = (makers.plan_items if tid in makers.TOOLS else plan_items)(engine, job, tid, items)
        if tid != "restyle-video":                # its pieces are joined by name afterwards
            items = unique_stems(items)
        if not items:
            st.status, st.note = "failed", why
            engine.log(f"'{job.name}' failed: {why}")
            return st
    faces: dict = {}
    if tid == "restore-photo" and "change-faces" not in opts and "colorize" not in opts:
        faces = find_faces(engine, job, st, [f for f, k in zip(items, keys) if k not in st.titles])
    if tid == "edit-picture" and not job.format.strip():
        st.status, st.note = "failed", "say what to change (for example: swap the background for a white wall)"
        engine.log(f"'{job.name}' failed: {st.note}")
        return st
    mdir = comfy_models_dir(engine.s)
    need = needed_packs(tid, {kind} if kind else set())
    missing = [p for p in need if not pack_ready(mdir, p)]
    if missing:
        st.status = "failed"
        st.note = ("needs " + " and ".join(pack_offer(p, mdir) for p in missing) +
                   ": Setup (F10) > System check offers it")
        engine.log(f"'{job.name}' failed: {st.note}")
        return st
    upscale = 0
    if tid in ("remove-bg", "restore-photo"):
        up = option_value(job, "upscale") or "none"
        upscale = int(up[0]) if up[:1] in ("2", "4") else 0
        if upscale and not pack_ready(mdir, "upscale"):
            engine.log("  Sharpening skipped: the Real-ESRGAN model isn't installed (System check offers it, 70 MB).")
            upscale = 0
    folder = tool_dir(engine, job, st)
    st.status = "running"
    st.started = st.started or datetime.now().isoformat(timespec="seconds")
    engine._save_state(job, st)
    if not engine.services.handoff("image"):
        st.status, st.note = "failed", "ComfyUI is not running and could not be started (F10 > System check)"
        engine.log(f"'{job.name}' failed: {st.note}")
        engine._save_state(job, st)
        return st
    limit = engine.s.comfy.timeout_s if tid not in LONG_TOOLS else max(engine.s.comfy.timeout_s, 3600)
    client = comfy_mod.ComfyClient(engine.services.comfy_base, limit)
    engine.log(f"{'Resuming' if st.titles else 'Starting'} '{job.name}': {len(items)} item(s) -> {st.output}")
    failed: list[str] = []
    prefix = f"Joe/{slug(job.name) or tid}"
    if tid in BIG_TOOLS:
        _free(engine, client)
    cpu_enc = False
    if tid in EDITORS:
        gb = card_gb(client.base)
        cpu_enc = 0 < gb < BIG_CARD_GB
        if cpu_enc:
            engine.log(f"  Graphics card: {gb:g} GB, under {BIG_CARD_GB} GB, so the picture editor reads your "
                       "request on the processor (a little slower, but it fits). The graphics card "
                       "sits nearly idle for the first few minutes.")
        else:
            engine.log(f"  Graphics card: {gb:g} GB." if gb else "  Graphics card size unknown.")
    try:
        for i, (item, key) in enumerate(zip(items, keys)):
            if key in st.titles:
                continue
            if engine.stop.is_set():
                raise Stopped()
            engine._cool_down()
            label = item["label"] if isinstance(item, dict) else item.name if isinstance(item, Path) else item[:50]
            engine._progress(f"{job.name}: {i + 1}/{len(items)} {label}")
            t0 = time.monotonic()
            try:
                graph, stem, ext = _graph_for(engine, job, tid, item, i, opts, kind, upscale, prefix,
                                              client, cpu=cpu_enc)
                try:
                    entry = client.wait(client.submit(graph), stop=engine.stop)
                except comfy_mod.WorkflowError as e:
                    if not out_of_memory(e):
                        raise
                    engine.log("  The graphics card ran out of memory; freeing it and trying once more"
                               + (" on a smaller copy." if tid in EDITORS else "."))
                    _free(engine, client)
                    if tid in EDITORS:
                        graph, stem, ext = _graph_for(engine, job, tid, item, i, opts, kind, upscale,
                                                      prefix, client, megapixels=SMALL_MP, cpu=True)
                    try:
                        entry = client.wait(client.submit(graph), stop=engine.stop)
                    except comfy_mod.WorkflowError as e2:
                        if out_of_memory(e2):
                            raise comfy_mod.WorkflowError(OOM_HINT) from e2
                        raise
                outs = outputs_of(entry)
                if not outs:
                    raise comfy_mod.WorkflowError("ComfyUI finished but saved nothing")
                made = []
                for n, f in enumerate(outs):
                    data = client.download(f)
                    suffix = Path(f["filename"]).suffix.lower() or ext
                    name = f"{stem}{'' if n == 0 else f'-{n + 1}'}{suffix}"
                    (folder / name).write_bytes(data)
                    made.append(name)
                if tid == "remove-bg" and option_value(job, "background") == "white":
                    made = [_on_white(engine, folder, m) for m in made]
                made = (makers.after(engine, job, tid, item, folder, made) if tid in makers.TOOLS
                        else after_edit(engine, job, tid, item, folder, made, faces))
                try:
                    from .storage import delete_comfy_copies
                    delete_comfy_copies(engine.s, outs)
                except Exception:                       # noqa: BLE001 (tidying only)
                    pass
            except InterruptedError:
                raise Stopped()
            except (comfy_mod.WorkflowError, HttpError, TimeoutError, OSError) as e:
                failed.append(f"{label}: {e}"[:200])
                engine.log(f"  {label}: {e}")
                engine._record(job=job.job_id, part=i + 1, kind=tid, model=tid, ok=False,
                               seconds=round(time.monotonic() - t0, 1))
                if isinstance(e, comfy_mod.WorkflowError) and not st.titles and i == 0 \
                        and "rejected" in str(e):
                    engine.log("  ComfyUI didn't accept the workflow. Update ComfyUI (it needs a "
                               "recent version for this tool), then try again.")
                    break
                continue
            took = round(time.monotonic() - t0, 1)
            engine._record(job=job.job_id, part=i + 1, kind=tid, model=tid, ok=True, seconds=took)
            st.titles.append(key)
            st.media_files.extend(made)
            st.items += 1
            engine._save_state(job, st)
            engine.log(f"  {label} -> {', '.join(made)} ({took:.0f} s)")
        if tid == "character-spin":
            spin_sheet(engine, folder, st)
        if tid in makers.TOOLS:
            makers.finish(engine, job, tid, folder, st)
        atomic_write_text(folder / "about.txt", _about(tid, job, opts, kind, upscale))
    except Stopped:
        st.status, st.note = "stopped", f"stopped after {len(st.titles)} of {len(items)}"
        engine._save_state(job, st)
        engine.log(f"'{job.name}' {st.note}")
        return st
    return _finish(engine, job, st, len(items), failed)


def _on_white(engine, folder: Path, name: str) -> str:
    """See-through PNG -> JPG on white, with FFmpeg (keeps the PNG if FFmpeg is missing)."""
    import subprocess
    from .doctor import ffmpeg_exe
    from .system import no_window_flags
    ff = ffmpeg_exe(engine.s.comfy.ffmpeg)
    src = folder / name
    if not ff or src.suffix.lower() != ".png":
        engine.log("  White background needs FFmpeg (System check installs it); kept the see-through PNG.")
        return name
    dest = src.with_suffix(".jpg")
    cmd = [ff, "-y", "-v", "error", "-i", str(src), "-filter_complex",
           "color=white[c];[c][0]scale2ref[c][i];[c][i]overlay=format=auto:shortest=1",
           "-frames:v", "1", "-q:v", "2", str(dest)]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300, creationflags=no_window_flags())
    except (OSError, subprocess.SubprocessError):
        return name
    if p.returncode == 0 and dest.exists():
        src.unlink(missing_ok=True)
        return dest.name
    return name


def _graph_for(engine, job, tid, item, i, opts, kind, upscale, prefix, client, megapixels: float = 0,
               cpu: bool = False):
    """(graph, output stem, fallback extension) for one item."""
    from .mission import slug
    from .tools import option_value
    seed = _seed(job, i)
    extra = job.format.strip()
    from . import workflowprefs as wfp
    if tid == "music":
        secs = float(option_value(job, "length") or 30)
        stem = f"{i + 1:02d}-{slug(item)[:40] or 'sound'}"
        if kind == "sfx":
            return sfx_graph(wfp.with_add(item, wfp.get(engine.s, "sfx")), secs, seed, prefix), stem, ".mp3"
        return music_graph(wfp.with_add(item, wfp.get(engine.s, "music")), secs, seed, prefix=prefix), stem, ".mp3"
    epref = wfp.get(engine.s, "editor")
    from . import quality as quality_mod
    fast = quality_mod.level(engine.s, "pictures") != "high"      # High = 40 full steps, slow
    if isinstance(item, dict) and item.get("maker"):               # batch 3 (makers.py)
        return makers.graph_for(engine, job, tid, item, i, prefix, client)
    if isinstance(item, dict):                                     # the newer editor tools
        name = upload_image(client.base, item["src"])
        extras = [upload_image(client.base, p) for p in item.get("images", [])]
        return (edit_graph(name, wfp.with_add(item["prompt"], epref), seed, fast, 0, prefix, megapixels, cpu,
                           denoise=item.get("denoise", 1.0), extra_images=extras),
                item["stem"], ".png")
    src: Path = item
    name = upload_image(client.base, src)
    stem = slug(src.stem) or f"picture-{i + 1}"
    if tid == "remove-bg":
        keep = option_value(job, "background") or "transparent"
        return bg_graph(name, keep, upscale, prefix), stem + "-cutout", ".png"
    if tid == "edit-picture":
        return edit_graph(name, wfp.with_add(extra, epref), seed, fast, 0, prefix, megapixels, cpu), stem + "-edited", ".png"
    if tid == "restore-photo":
        prompt = RESTORE_PROMPT + (COLORIZE if "colorize" in opts else KEEP_BW)
        if extra:
            prompt += " " + extra
        prompt = wfp.with_add(prompt, epref)
        return (edit_graph(name, prompt, seed, fast, upscale, prefix, megapixels, cpu),
                stem + "-restored", ".png")
    if tid == "animate-photo":
        pw, ph = picture_size(src)
        from .tools import jpeg_orientation
        if src.suffix.lower() in (".jpg", ".jpeg") and jpeg_orientation(src) >= 5:
            pw, ph = ph, pw                       # phone portrait stored sideways: ComfyUI turns it upright
        w, h = video_size(pw, ph)
        motion = extra or "gentle natural motion, subtle camera push-in, lifelike movement"
        prompt = (f"{motion}. Keep the people, objects and setting from the photo exactly as they are; "
                  "smooth, natural movement.")
        from .doctor import comfy_models_dir
        turbo = comfy_mod.wan_turbo_installed(comfy_models_dir(engine.s))
        steps, cfg = (4, 1.0) if turbo else (20, 5.0)
        apref = wfp.get(engine.s, "animate")
        prompt = wfp.with_add(prompt, apref)
        return (animate_graph(name, prompt, wfp.with_avoid(comfy_mod.WAN_VIDEO["negative"], apref), seed, w, h,
                              steps=steps, cfg=cfg, turbo=turbo, prefix=prefix), stem + "-moving", ".mp4")
    raise comfy_mod.WorkflowError(f"unknown tool {tid}")


def _about(tid, job, opts, kind, upscale) -> str:
    packs = needed_packs(tid, {kind} if kind else set()) + (("upscale",) if upscale else ())
    lines = [f"# {job.name}", "", f"Made by Joe with ComfyUI on {datetime.now():%Y-%m-%d %H:%M}.", ""]
    for p in packs:
        lines.append(f"- Model: {PACKS[p].label} ({PACKS[p].license})")
    if "3d" in packs:
        lines += ["", "Tencent Hunyuan 3D 2.1 is licensed under the Tencent Hunyuan 3D 2.1 Community License "
                  "Agreement, Copyright (c) 2025 Tencent. All Rights Reserved. The license does not apply "
                  "in the European Union, the United Kingdom or South Korea.",
                  "The .glb files open in Windows 3D Viewer, Blender, Unity, Unreal and most 3D programs."]
    lines += ["", "Check each model's license before using these commercially.",
              "AI pictures and sound can contain mistakes: look and listen before you publish."]
    return "\n".join(lines) + "\n"



# --------------------------------------------------------------------------- the newer editor tools
NEW_EDITORS = ("fix-spot", "merge-pictures", "relight", "restyle", "redraw", "make-bigger",
               "character-scenes", "character-spin")
KEEP_REST = (" Keep everything else in the picture exactly as it is: the same people, faces, objects, "
             "colors, framing and detail.")
DENOISE = {"little": 0.45, "some": 0.65, "lots": 0.85}


def _ffmpeg(engine) -> str | None:
    from .doctor import ffmpeg_exe
    return ffmpeg_exe(engine.s.comfy.ffmpeg)


def _work_dir(engine) -> Path:
    d = engine.sb.meta / "work"
    d.mkdir(parents=True, exist_ok=True)
    return d


def wkey(f: Path) -> str:
    """A work-folder name for one source file: two 'photo.jpg' from different folders (or
    photo.jpg and photo.png) never share a scratch file."""
    import hashlib
    from .mission import slug
    return f"{slug(f.stem)[:40]}-{hashlib.sha1(str(f).encode('utf-8', 'replace')).hexdigest()[:6]}"


def unique_stems(items: list[dict]) -> list[dict]:
    """Output names: the second 'photo-relit' becomes 'photo-relit-2', so nothing is overwritten."""
    seen: set[str] = set()
    for it in items:
        base = s = str(it.get("stem") or "picture")
        n = 2
        while s.lower() in seen:
            s, n = f"{base}-{n}", n + 1
        it["stem"] = s
        seen.add(s.lower())
    return items


def plan_items(engine, job, tid: str, files: list[Path]) -> tuple[list[dict], list[str], str]:
    """Files -> one dict per picture to make: src, prompt, extra images, stem, label, key and
    what to do afterwards. ([], [], why) when it can't run."""
    from .mission import slug
    from .tools import TOOLS, RELIGHTS, RESTYLES, option_value
    from . import media
    extra = (job.format or "").strip()
    items: list[dict] = []
    if tid == "fix-spot":
        pics = [f for f in files if not f.name.lower().endswith(MASK_SUFFIX)]
        missing = []
        for f in pics:
            mask = f.with_name(f.stem + MASK_SUFFIX)
            if not mask.exists():
                missing.append(f.name)
                continue
            ff = _ffmpeg(engine)
            if not ff:
                return [], [], "needs FFmpeg to mark the spot (Setup > System check installs it)"
            orig, f = f, _upright(engine, ff, f)      # phone photos: the mark was painted on the upright view
            marked = media.outline_spot(ff, f, mask, _work_dir(engine) / f"{wkey(orig)}-marked.png")
            if not marked:
                return [], [], f"couldn't read {f.name} or its marked spot"
            what = extra or "remove what is there and fill it in so it matches the surroundings naturally"
            items.append({"src": f, "images": [marked], "stem": slug(orig.stem) + "-fixed", "label": orig.name,
                          "key": f"fix {orig.name}", "mask": mask,
                          "prompt": ("Picture 2 is picture 1 with one spot tinted red. In picture 1, in that "
                                     f"spot only: {what}. The result must not contain any red tint." + KEEP_REST)})
        if not items:
            return [], [], ("mark the spot first: Tools (F3) > Fix one spot > MARK THE SPOT"
                            + (f" (no mark for {', '.join(missing[:3])})" if missing else ""))
        if missing:
            engine.log(f"  No marked spot for {', '.join(missing)}; skipped (Tools > Fix one spot > MARK THE SPOT).")
    elif tid == "merge-pictures":
        if len(files) < 2:
            return [], [], "add 2 or 3 pictures to put together"
        if len(files) > 3:
            engine.log(f"  Using the first 3 of {len(files)} pictures.")
        if not extra:
            return [], [], "say how the pictures go together (picture 1, picture 2...)"
        names = " + ".join(f.name for f in files[:3])
        items.append({"src": files[0], "images": files[1:3], "stem": slug(job.name) or "together",
                      "label": names[:60], "key": f"merge {names}",
                      "prompt": f"{extra}. Make it one natural, believable picture with matching light, "
                                "shadows and perspective."})
    elif tid == "relight":
        light = RELIGHTS.get(option_value(job, "light") or "golden", RELIGHTS["golden"])[1]
        for f in files:
            items.append({"src": f, "stem": slug(f.stem) + "-relit", "label": f.name, "key": f"relight {f.name}",
                          "prompt": f"Relight this picture with {light}." + (f" {extra}." if extra else "")
                                    + " Change only the lighting, shadows and color of the light." + KEEP_REST})
    elif tid == "restyle":
        want = option_value(job, "style") or "watercolor"
        if want == "picture":
            if len(files) < 2:
                return [], [], "add your picture(s) and, last, the picture whose style to copy"
            ref, pics = files[-1], files[:-1]
            for f in pics:
                items.append({"src": f, "images": [ref], "stem": slug(f.stem) + "-restyled", "label": f.name,
                              "key": f"restyle {f.name} like {ref.name}",
                              "prompt": "Redraw picture 1 in the art style of picture 2: its medium, colors, "
                                        "brushwork, line work and texture. Keep the content, people, pose and "
                                        "layout of picture 1. Do not copy anything else from picture 2."
                                        + (f" {extra}." if extra else "")})
        else:
            look = RESTYLES.get(want, RESTYLES["watercolor"])[1]
            for f in files:
                items.append({"src": f, "stem": slug(f.stem) + f"-{want}", "label": f.name,
                              "key": f"restyle {f.name} {want}",
                              "prompt": f"Redraw this picture as {look}. Keep the same people, objects, pose "
                                        "and layout." + (f" {extra}." if extra else "")})
    elif tid == "redraw":
        if not extra:
            return [], [], "say what the picture should look like"
        amount = option_value(job, "change") or "some"
        for f in files:
            items.append({"src": f, "stem": slug(f.stem) + "-redrawn", "label": f.name, "key": f"redraw {f.name}",
                          "denoise": DENOISE.get(amount, 0.65),
                          "prompt": f"Redraw this picture: {extra}. Keep its overall layout."})
    elif tid == "make-bigger":
        ff = _ffmpeg(engine)
        if not ff:
            return [], [], "needs FFmpeg (Setup > System check installs it)"
        shape = option_value(job, "shape") or "wider"
        for f0 in files:
            f = _upright(engine, ff, f0)          # phone photos stored sideways: pad the upright view
            pad = media.pad_for_outpaint(ff, f, _work_dir(engine) / f"{wkey(f0)}-padded.png", shape)
            if not pad:
                engine.log(f"  Couldn't read {f.name}; skipped.")
                continue
            items.append({"src": pad[0], "stem": slug(f0.stem) + f"-{shape}", "label": f0.name,
                          "key": f"bigger {f0.name} {shape}", "padded": pad[0], "inner": pad[1],
                          "prompt": "The sharp middle of this picture is the real photo; the blurry parts around "
                                    "it are empty space to fill. Replace every blurry part with sharp, detailed "
                                    "scenery that continues the middle naturally, with the same light, style, "
                                    "colors and perspective, and no visible seams or frames."
                                    + (f" Around it: {extra}." if extra else "") +
                                    " Keep the sharp middle exactly as it is."})
        if not items:
            return [], [], "couldn't read the pictures"
    elif tid == "character-scenes":
        scenes = [x.strip(" -•\t") for x in re.split(r"[\n;]+", extra) if x.strip(" -•\t")]
        if not scenes:
            return [], [], "write the scenes, one per line (or separated by ;)"
        src = files[0]
        for n, scene in enumerate(scenes[:40], 1):
            items.append({"src": src, "stem": f"{n:02d}-{slug(scene)[:40] or 'scene'}", "label": scene[:50],
                          "key": f"scene {n} {scene[:60]}",
                          "prompt": f"Show {SAME_CHARACTER}, {scene}. A complete, well-composed picture."})
    elif tid == "character-spin":
        src = files[0]
        for n, (vid, view) in enumerate(SPIN_VIEWS, 1):
            items.append({"src": src, "stem": f"{n}-{vid}", "label": vid.replace("-", " "),
                          "key": f"spin {src.name} {vid}",
                          "prompt": f"Show {SAME_CHARACTER}, full body, {view}, standing in a relaxed neutral "
                                    "pose on a plain light grey background, evenly lit, nothing else in the picture."})
    if tid not in TOOLS:
        return [], [], f"unknown tool {tid}"
    return items, [it["key"] for it in items], ""


def _upright(engine, ff: str, f: Path) -> Path:
    """A phone photo stored sideways (EXIF turn) -> an upright copy in Joe's work folder."""
    from .tools import _TURN, jpeg_orientation
    turn = jpeg_orientation(f) if f.suffix.lower() in (".jpg", ".jpeg") else 1
    if turn not in _TURN:
        return f
    import subprocess
    from .system import no_window_flags
    dest = _work_dir(engine) / f"{wkey(f)}-upright.png"
    try:
        subprocess.run([ff, "-y", "-v", "error", "-noautorotate", "-i", str(f), "-vf", _TURN[turn],
                        "-frames:v", "1", str(dest)], capture_output=True, timeout=300,
                       creationflags=no_window_flags())
    except (OSError, subprocess.SubprocessError):
        return f
    return dest if dest.exists() else f


def after_edit(engine, job, tid: str, item, folder: Path, made: list[str], faces: dict) -> list[str]:
    """Put back what must not change: outside the marked spot, the original middle of a bigger
    picture, the real faces after an AI repair."""
    from . import media
    ff = _ffmpeg(engine)
    if not ff or not made:
        return made
    out = folder / made[0]
    try:
        if tid == "fix-spot" and isinstance(item, dict):
            if media.blend(ff, item["src"], out, item["mask"], out.with_suffix(".tmp.png")):
                out.with_suffix(".tmp.png").replace(out)
                engine.log("  Only the marked spot was changed.")
        elif tid == "make-bigger" and isinstance(item, dict):
            size = media.size_of(ff, item["padded"])
            keep = _work_dir(engine) / f"{out.stem}-keep.png"
            x, y, w, h = item["inner"]
            edge = max(4, min(w, h) // 40)                        # blend a little inside the edge
            if size and media.rect_mask(ff, size, (x + edge, y + edge, w - 2 * edge, h - 2 * edge), keep) and \
                    media.blend(ff, item["padded"], out, keep, out.with_suffix(".tmp.png"), feather=edge / 2):
                out.with_suffix(".tmp.png").replace(out)
                engine.log("  Your picture is untouched in the middle; the AI filled in around it.")
        elif tid == "restore-photo" and isinstance(item, Path) and faces.get(item):
            truer = _work_dir(engine) / f"{out.stem}-true.png"
            import subprocess
            from .system import no_window_flags
            from .tools import jpeg_orientation
            turn = jpeg_orientation(item) if item.suffix.lower() in (".jpg", ".jpeg") else 1
            subprocess.run(true_restore_command(ff, item, truer, turn, 0, auto_level(measure(ff, item))),
                           capture_output=True, timeout=600, creationflags=no_window_flags())
            size = media.size_of(ff, out)
            mask = _work_dir(engine) / f"{out.stem}-faces.png"
            if truer.exists() and size and media.box_mask(ff, size, faces[item], mask) and \
                    media.blend(ff, out, truer, mask, out.with_suffix(".tmp.png")):
                out.with_suffix(".tmp.png").replace(out)
                engine.log(f"  Kept the real face{'s' if len(faces[item]) > 1 else ''} "
                           f"({len(faces[item])}), restored true to the photo.")
    except (OSError, ValueError) as e:
        engine.log(f"  Couldn't finish {out.name}: {e}")
    return made


def find_faces(engine, job, st, files: list[Path]) -> dict:
    """Faces in each photo, as (x, y, w, h) fractions, found by the vision model before the
    picture editor starts. {} when there's no vision model (Joe says so and carries on)."""
    from .tools import find_vision_model, picture_b64, _look
    if not files or not engine.services.handoff("text"):
        return {}
    model = find_vision_model(engine)
    if not model:
        engine.log("  Keep the real faces needs a vision model (Setup > System check offers one); "
                   "the AI repair may change faces.")
        return {}
    ff = _ffmpeg(engine)
    out: dict = {}
    system = ("You find human faces in photos. Reply with JSON only: {\"faces\": [{\"x\": left, \"y\": top, "
              "\"w\": width, \"h\": height}]} where each number is a fraction of the picture's width or "
              "height from 0 to 1. Include every face, even small or blurry ones. No faces: {\"faces\": []}.")
    for n, f in enumerate(files):
        try:
            img = picture_b64(ff, f, _work_dir(engine) / f"face-{n}.jpg", 1024)
        except ValueError as e:
            engine.log(f"  {f.name}: {e}")
            continue
        o = _look(engine, job, st, n, "faces", system, "Find every face in this photo.", img, model) or {}
        boxes = []
        for b in o.get("faces") or []:
            try:
                x, y, w, h = (float(b[k]) for k in ("x", "y", "w", "h"))
            except (KeyError, TypeError, ValueError):
                continue
            if max(x, y, w, h) > 1.5:                 # the model answered in pixels or per mille
                x, y, w, h = (v / 1000 for v in (x, y, w, h))
            if 0 <= x < 1 and 0 <= y < 1 and 0.01 < w <= 1 and 0.01 < h <= 1:
                boxes.append((x, y, w, h))
        if boxes:
            out[f] = boxes
        engine.log(f"  {f.name}: {len(boxes)} face(s) to keep")
    return out


def spin_sheet(engine, folder: Path, st) -> None:
    """The six views side by side: one character sheet."""
    from . import media
    ff = _ffmpeg(engine)
    views = []
    for n, (vid, _) in enumerate(SPIN_VIEWS, 1):
        hit = sorted(folder.glob(f"{n}-{vid}.*"))
        if hit:
            views.append(hit[0])
    if ff and len(views) >= 2 and media.side_by_side(ff, views, folder / "character-sheet.png"):
        if "character-sheet.png" not in st.media_files:
            st.media_files.append("character-sheet.png")
        engine.log("  Character sheet: character-sheet.png")
