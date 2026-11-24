"""Model profiles: settings that belong to the picture model that actually draws, not to the style.

Joe's picture styles (styles.py) say how a picture should look. Some checkpoints need their own
numbers whatever the style, and other people's PCs have models Joe's own picks don't cover
(audit 2026-11-24, agreed with Joseph):

  fast         Turbo / Lightning / Hyper / LCM / DMD files. They are made for a few steps at a low
               prompt strength; at Joe's normal 40 steps and strength 6 they come out burnt.
  pony         Pony Diffusion and models built on it: score_9... quality tags, clip skip 2.
  illustrious  Illustrious / NoobAI models: "masterpiece, best quality" tags, clip skip 2.
  animagine    Animagine: the anime style's own recipe already fits it (nothing changes).
  ""           Everything else: Joe's normal settings.

Picked from words in the file name only. Setup > Workflows (steps, prompt strength, sampler) still
wins over a profile, and Joseph's style words are never changed: a profile only swaps the model's
own quality tags.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace

# "hyper" etc. only as a word of their own: HyperRealism is an ordinary model.
FAST_RE = re.compile(r"turbo|lightning|(?<![a-z])(?:hyper|lcm|dmd2?|schnell)(?![a-z])", re.I)
PONY_RE = re.compile(r"pony|pdxl", re.I)
ILLUSTRIOUS_RE = re.compile(r"illustrious|noob|ilxl|[_\-]il[_\-]?xl|illu[_\-]", re.I)
ANIMAGINE_RE = re.compile(r"animagine", re.I)

# Animagine 4.0's own quality words, which mean nothing to other anime models.
ANIMAGINE_TAGS = ("high score", "great score", "low score", "bad score", "average score")


@dataclass(frozen=True)
class Profile:
    kind: str = ""                 # fast | pony | illustrious | animagine | ""
    label: str = ""
    steps: int = 0                 # fast models: the whole run (0 = Joe's quality setting)
    low_steps: int = 0             # fast models on Low
    cfg: float = 0.0               # base prompt strength (0 = Joe's normal 6, plus the style's nudge)
    fixed_cfg: bool = False        # fast models: the style's nudge isn't added
    sampler: str = ""              # "" = the style's / quality setting's
    force_sampler: bool = False    # fast models need their own sampler whatever the style says
    scheduler: str = ""
    hires_steps: int = 0           # detail pass steps (0 = Joe's 14)
    clip_skip: int = 0             # 2 = CLIPSetLastLayer -2
    prefix: str = ""               # quality tags put first in the prompt
    negative: str = ""             # quality tags put first in the leave-out list
    drop_animagine_tags: bool = False

    def describe(self) -> str:
        bits = []
        if self.steps:
            bits.append(f"{self.steps} steps")
        if self.cfg:
            bits.append(f"prompt strength {self.cfg:g}")
        if self.sampler:
            bits.append(self.sampler)
        if self.clip_skip:
            bits.append(f"clip skip {self.clip_skip}")
        return f"{self.label}" + (f" ({', '.join(bits)})" if bits else "")


NONE = Profile()


def for_checkpoint(name: str, family: str = "sdxl") -> Profile:
    """The profile for a checkpoint file name (NONE for FLUX/video or an ordinary model)."""
    n = (name or "").replace("\\", "/").split("/")[-1]
    if family not in ("sdxl", "sd15", "other") or not n:
        return NONE
    if FAST_RE.search(n):
        lcm = re.search(r"lcm", n, re.I)
        # DreamShaper/Juggernaut/RealVis Lightning, Turbo and Hyper pages: DPM++ SDE Karras, about 4-8
        # steps at prompt strength 1.5-2. LCM files: the LCM sampler, about 8 steps at 1.5.
        return Profile("fast", "fast model (Turbo/Lightning/Hyper)", steps=8 if lcm else 6, low_steps=4,
                       cfg=1.5 if lcm else 2.0, fixed_cfg=True, sampler="lcm" if lcm else "dpmpp_sde",
                       force_sampler=True, scheduler="sgm_uniform" if lcm else "karras", hires_steps=4)
    if family == "sd15":
        return NONE
    if PONY_RE.search(n):
        # Pony Diffusion V6 XL: score_9... tags first, clip skip 2 (blobs without it), CFG about 7, Euler a.
        return Profile("pony", "Pony-based model", cfg=7.0, sampler="euler_ancestral", clip_skip=2,
                       prefix="score_9, score_8_up, score_7_up, score_6_up",
                       negative="score_5, score_4, score_3", drop_animagine_tags=True)
    if ILLUSTRIOUS_RE.search(n):
        # Illustrious XL guides: masterpiece / best quality tags, CFG about 5-6, Euler a, clip skip 2.
        return Profile("illustrious", "Illustrious-based model", cfg=5.5, sampler="euler_ancestral", clip_skip=2,
                       prefix="masterpiece, best quality, amazing quality",
                       negative="worst quality, bad quality, low quality, lowres", drop_animagine_tags=True)
    if ANIMAGINE_RE.search(n):
        return Profile("animagine", "Animagine")
    return NONE


def strip_tags(text: str, tags=ANIMAGINE_TAGS) -> str:
    from .styles import split_parts
    drop = {t.lower() for t in tags}
    return ", ".join(p for p in split_parts(text) if " ".join(p.lower().split()) not in drop)


def adapt_recipe(rec, prof: Profile):
    """The style recipe with this model's own quality words (Joseph's style words stay as they are)."""
    if not prof.kind or prof.kind in ("animagine", "fast"):
        return rec
    words = strip_tags(rec.words) if prof.drop_animagine_tags else rec.words
    neg = strip_tags(rec.negative) if prof.drop_animagine_tags else rec.negative
    if prof.negative:
        neg = f"{prof.negative}, {neg}" if neg else prof.negative
    return replace(rec, words=words, negative=neg, prefix=prof.prefix)


def apply_graph(g: dict, prof: Profile, level: str, style_sampler: str = "", style_cfg: float = 0.0) -> dict:
    """Put a profile's numbers into the built-in SD graph (node "3" = the KSampler)."""
    if not prof.kind or prof.kind == "animagine":
        return g
    from .comfy import with_clip_skip
    ks = g["3"]["inputs"]
    if prof.kind == "fast":
        ks["steps"] = prof.low_steps if level == "low" and prof.low_steps else prof.steps
        ks["cfg"] = prof.cfg
        ks["sampler_name"] = prof.sampler
        ks["scheduler"] = prof.scheduler
    else:
        if prof.cfg:
            ks["cfg"] = round(max(2.0, prof.cfg + style_cfg), 2)
        if prof.sampler and not style_sampler:
            ks["sampler_name"] = prof.sampler
    if prof.clip_skip:
        g = with_clip_skip(g, -abs(prof.clip_skip))
    return g
