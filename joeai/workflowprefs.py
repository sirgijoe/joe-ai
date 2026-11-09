"""Setup > Workflows: your own touches for each way Joe makes pictures, video and sound.

For every workflow (Joe's built-in ones, each picture style, and the workflow files you
imported) you can set: the model to use, words added to every prompt ("always add"), words
added to every leave-out list ("always leave out") and, for pictures, the number of steps.
They're kept in settings.json (Settings.workflows); Joe's own files are never edited, and
RESET THIS WORKFLOW (or Setup's RESET ALL) takes them away again.

Joe's own words for each workflow (a style's prompt-writer note, the words added to every
prompt, the leave-out list) are shown too, filled in, with EDIT. An edited copy replaces Joe's
for that workflow (apply() puts it in place when Joe starts and after each save); reset brings
Joe's back. The Pictures leave-out list is the same as Setup's old "negative" setting.
"""
from __future__ import annotations

from pathlib import Path

FIELDS = ("model", "add", "avoid", "steps", "note", "words", "leave",
          "cfg", "lora", "hires", "denoise", "sampler", "versions")
# Fine-tuning for the built-in picture graph (Pictures and each picture style). Shown filled in
# with Joe's own value; only a value that differs from Joe's is stored. Showcase QC 2026-11-09:
# several bad pictures were one fixed setting overpowering the words (neon signs: prompt
# strength; pixel art: the detail pass; people: the detail pass repainting faces).
TUNE = ("cfg", "lora", "hires", "denoise", "sampler", "versions", "motion")
MOTION_WORDS = {"low": "slow, subtle, gentle movement, mostly still camera",
                "high": "lively, energetic movement, dynamic camera motion"}
SAMPLERS = ("euler", "euler_ancestral", "dpmpp_2m", "dpmpp_2m_sde", "dpmpp_3m_sde", "dpmpp_sde", "uni_pc", "ddim")
TUNE_HELP = {
    "cfg": "Prompt strength (CFG): how hard the picture follows your words. Lower = more natural, "
           "fewer made-up details (try 4-5 if pictures get fake writing or look overcooked); higher = "
           "follows the words more literally.",
    "lora": "Style add-on strength (LoRA): how much the style's add-on changes the look, 0 to 1.5. "
            "Only used when the add-on is installed.",
    "hires": "Detail pass: a second, 1.5x bigger pass that adds fine detail. Auto = only on High "
             "quality. Turn it off for crisp pixel art or flat styles.",
    "denoise": "Detail pass strength: how much the detail pass may repaint (0.2-0.6). Lower keeps "
               "faces and hands as they were.",
    "sampler": "Sampler: the method that draws the picture. Joe's pick suits most pictures.",
    "versions": "Versions per prompt: make several and pick the best (people and animals go wrong "
                "more often). A task's own VARIANTS wins.",
    "motion": "Motion: how much moves in each clip. Low for calm scenes (and fewer melting details), "
              "high when a clip barely moved.",
    "vcfg": "Prompt strength (CFG) for video: higher follows your words more literally (a lighthouse stays "
            "a lighthouse); too high looks oversaturated. Not used with the Turbo add-on (it needs 1).",
}


def tune_defaults(wid: str) -> dict:
    """Joe's own fine-tuning values for a picture workflow (SDXL numbers) or Video clips, or {}."""
    if wid == "video":
        return {"cfg": 5.0, "motion": "normal"}
    if wid != "pictures" and not wid.startswith("style:"):
        return {}
    from . import styles
    st = _originals()["styles"].get(wid[6:]) if wid.startswith("style:") else None
    if wid.startswith("style:") and st is None:
        return {}
    shift = st.cfg if st else 0.0
    out = {"cfg": round(max(2.0, 6.0 + shift), 1), "hires": "auto" if (st is None or st.hires) else "off",
           "denoise": 0.4, "sampler": (st.sampler if st and st.sampler else ""), "versions": 1}
    if st is not None and st.lora:
        out["lora"] = st.lora_strength
    _ = styles
    return out
TEXT_FIELDS = ("note", "words", "leave")       # Joe's own words, shown and editable (replace his)
TEXT_LABELS = {"note": "What Joe tells the prompt writer", "words": "Words Joe adds to every prompt",
               "leave": "Joe's leave-out list (negative prompt)"}

# id -> (group, label, what it covers, can pick a model, can set steps)
BUILTIN = {
    "pictures": ("Joe's built-in", "Pictures (every style)", "Joe's own text-to-picture graph, used by every picture task "
                 "that has no workflow file. A picture style's own settings below come first. Pick the "
                 "FLUX.2 klein model to use it for every picture.", True, True),
    "video": ("Joe's built-in", "Video clips", "Wan 2.2 video tasks (and black-and-white video).", False, False),
    "editor": ("Joe's built-in", "Picture editor tools", "Edit a picture, AI photo repair, Fix one spot, Put pictures "
               "together, Change the lighting, Redraw, Make it bigger, character tools.", False, False),
    "animate": ("Joe's built-in", "Animate a photo", "Photo-to-clip (Wan 2.2).", False, False),
    "controlnet": ("Joe's built-in", "Sketch to picture and illusions", "The SDXL model and steps for Sketch to "
                   "picture and Hidden-picture illusion (ControlNet).", True, True),
    "restyle-video": ("Joe's built-in", "Restyle a video", "Wan 2.2 Fun Control: keeps a video's motion, "
                      "changes its look.", False, False),
    "music": ("Joe's built-in", "Music", "ACE-Step music tracks.", False, False),
    "sfx": ("Joe's built-in", "Sound effects", "Stable Audio Open sound effects.", False, False),
}


_ORIG: dict = {}          # Joe's own words, captured once before any edit is applied


def _originals() -> dict:
    if not _ORIG:
        from . import comfy, engine, styles
        _ORIG["styles"] = dict(styles.STYLES)
        _ORIG["wan"] = comfy.WAN_NEGATIVE
        _ORIG["video_extra"] = engine.VIDEO_EXTRA
        _ORIG["image_negative"] = comfy.IMAGE_NEGATIVE
    return _ORIG


def builtin_text(wid: str) -> dict:
    """Joe's own words for one workflow: {field: text} (only the fields it has)."""
    o = _originals()
    if wid == "pictures":
        return {"leave": o["image_negative"]}
    if wid == "video":
        return {"note": o["video_extra"], "leave": o["wan"]}
    if wid.startswith("style:"):
        st = o["styles"].get(wid[6:])
        if st:
            return {"note": st.note, "words": st.suffix, "leave": st.negative}
    return {}


def _text(v, field: str) -> str:
    v = str(v or "").replace("\r", "")
    if field == "note":
        return "\n".join(" ".join(line.split()) if not line.startswith("  ") else line.rstrip()
                         for line in v.strip().splitlines())[:4000]
    return " ".join(v.split())[:4000]


def _clean(p: dict | None, wid: str = "") -> dict:
    p = p if isinstance(p, dict) else {}
    out = {}
    for k in ("model", "add", "avoid"):
        v = " ".join(str(p.get(k) or "").split())[:600]
        if v:
            out[k] = v
    base = builtin_text(wid) if wid else {}
    for k in TEXT_FIELDS:
        if k in p and k in base:
            v = _text(p[k], k)
            if v != _text(base[k], k):        # unchanged = Joe's own (nothing stored)
                out[k] = v
    try:
        steps = int(p.get("steps") or 0)
    except (TypeError, ValueError):
        steps = 0
    if 1 <= steps <= 150:
        out["steps"] = steps
    joe = tune_defaults(wid) if wid else {}
    for k, lo, hi in (("cfg", 1.0, 20.0), ("lora", 0.0, 2.0), ("denoise", 0.1, 0.8)):
        if p.get(k) in (None, ""):
            continue
        try:
            v = round(float(p[k]), 2)
        except (TypeError, ValueError):
            continue
        if lo <= v <= hi and (k not in joe or abs(v - float(joe[k])) > 1e-6):
            out[k] = v
    h = str(p.get("hires") or "").lower()
    if h in ("on", "off", "auto") and h != joe.get("hires", "auto"):
        out["hires"] = h
    mo = str(p.get("motion") or "").lower()
    if mo in ("low", "normal", "high") and mo != joe.get("motion", "normal"):
        out["motion"] = mo
    sm = str(p.get("sampler") or "")
    if sm in SAMPLERS and sm != joe.get("sampler", ""):
        out["sampler"] = sm
    try:
        n = int(p.get("versions") or 0)
    except (TypeError, ValueError):
        n = 0
    if 2 <= n <= 6:
        out["versions"] = n
    return out


def get(settings, wid: str) -> dict:
    return _clean((getattr(settings, "workflows", None) or {}).get(wid), wid)


def text_of(settings, wid: str) -> dict:
    """The words in use now for each of Joe's own fields: your edit, else Joe's."""
    base = builtin_text(wid)
    mine = get(settings, wid)
    out = {k: mine.get(k, v) for k, v in base.items()}
    if wid == "pictures" and (settings.comfy.negative or "").strip():
        from .comfy import OLD_IMAGE_NEGATIVE
        if settings.comfy.negative.strip() != OLD_IMAGE_NEGATIVE:
            out["leave"] = settings.comfy.negative.strip()
    return out


def apply(settings) -> None:
    """Put edited words in place of Joe's (and Joe's back where there's no edit)."""
    from dataclasses import replace
    from . import comfy, engine, styles
    o = _originals()
    wf = getattr(settings, "workflows", None) or {}
    for sid, st in o["styles"].items():
        mine = _clean(wf.get(f"style:{sid}"), f"style:{sid}")
        ch = {f: mine[k] for k, f in (("note", "note"), ("words", "suffix"), ("leave", "negative")) if k in mine}
        styles.STYLES[sid] = replace(st, **ch) if ch else st
    v = _clean(wf.get("video"), "video")
    comfy.WAN_NEGATIVE = v.get("leave", o["wan"])
    comfy.WAN_VIDEO["negative"] = comfy.WAN_NEGATIVE
    engine.VIDEO_EXTRA = v.get("note", o["video_extra"])


def merged(settings, ids: list[str]) -> dict:
    """Several workflow ids, first one wins for model/steps; add/avoid words are all kept."""
    out: dict = {}
    adds, avoids = [], []
    for wid in ids:
        p = get(settings, wid)
        for k in ("model", "steps") + TUNE:
            if k in p and k not in out:
                out[k] = p[k]
        if p.get("add"):
            adds.append(p["add"])
        if p.get("avoid"):
            avoids.append(p["avoid"])
    if adds:
        out["add"] = ", ".join(adds)
    if avoids:
        out["avoid"] = ", ".join(avoids)
    return out


def with_add(text: str, prefs: dict) -> str:
    add = prefs.get("add", "")
    return f"{text.rstrip(' .,')}, {add}" if add and text.strip() else (text or add)


def with_avoid(text: str, prefs: dict) -> str:
    avoid = prefs.get("avoid", "")
    return f"{text.rstrip(' ,')}, {avoid}" if avoid and text.strip() else (text or avoid)


def entries(settings, sb, models_dir: Path | None) -> dict:
    """Everything Setup > Workflows shows."""
    from . import comfy, styles
    pics = [m.name for m in comfy.scan_models(models_dir) if m.folder == "checkpoints" or m.family == "flux2"]
    rows = []
    def texts(wid: str) -> list[dict]:
        base, now = builtin_text(wid), text_of(settings, wid)
        return [{"field": k, "label": TEXT_LABELS[k], "builtin": base[k], "value": now[k],
                 "changed": _text(now[k], k) != _text(base[k], k)} for k in TEXT_FIELDS if k in base]

    for wid, (group, label, about, can_model, can_steps) in BUILTIN.items():
        rows.append({"id": wid, "group": group, "label": label, "about": about, "model_ok": can_model,
                     "steps_ok": can_steps, "prefs": get(settings, wid), "texts": texts(wid),
                     "tune": tune_defaults(wid)})
    for sid in styles.NAMES:
        if sid == "general":
            continue
        st = styles.STYLES[sid]
        rows.append({"id": f"style:{sid}", "group": "Picture styles", "label": st.label,
                     "about": f"Pictures with STYLE: {sid}.", "model_ok": True, "steps_ok": True,
                     "prefs": get(settings, f"style:{sid}"), "texts": texts(f"style:{sid}"),
                     "tune": tune_defaults(f"style:{sid}")})
    folder = sb.workflows
    for f in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        rows.append({"id": f"file:{f.name}", "group": "Your workflow files", "label": f.name,
                     "about": "A workflow you imported (Workflows folder). The model is used if the file has "
                              "a checkpoint loader.", "model_ok": True, "steps_ok": False,
                     "prefs": get(settings, f"file:{f.name}"), "texts": []})
    return {"rows": rows, "models": pics, "samplers": list(SAMPLERS), "tune_help": TUNE_HELP}


def save(settings, wid: str, prefs: dict | None) -> dict:
    """prefs None = reset this workflow."""
    if not (wid in BUILTIN or wid.startswith("style:") or wid.startswith("file:")):
        return {"ok": False, "error": "Unknown workflow."}
    wf = dict(getattr(settings, "workflows", None) or {})
    clean = _clean(prefs, wid) if prefs is not None else {}
    if wid == "pictures":                     # its leave-out list is Setup's comfy.negative
        settings.comfy.negative = clean.pop("leave", "")
    if clean:
        wf[wid] = clean
    else:
        wf.pop(wid, None)
    settings.workflows = wf
    settings.save()
    apply(settings)
    return {"ok": True, "prefs": clean}
