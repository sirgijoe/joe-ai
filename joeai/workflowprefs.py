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

FIELDS = ("model", "add", "avoid", "steps", "note", "words", "leave")
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
        for k in ("model", "steps"):
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
                     "steps_ok": can_steps, "prefs": get(settings, wid), "texts": texts(wid)})
    for sid in styles.NAMES:
        if sid == "general":
            continue
        st = styles.STYLES[sid]
        rows.append({"id": f"style:{sid}", "group": "Picture styles", "label": st.label,
                     "about": f"Pictures with STYLE: {sid}.", "model_ok": True, "steps_ok": True,
                     "prefs": get(settings, f"style:{sid}"), "texts": texts(f"style:{sid}")})
    folder = sb.workflows
    for f in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        rows.append({"id": f"file:{f.name}", "group": "Your workflow files", "label": f.name,
                     "about": "A workflow you imported (Workflows folder). The model is used if the file has "
                              "a checkpoint loader.", "model_ok": True, "steps_ok": False,
                     "prefs": get(settings, f"file:{f.name}"), "texts": []})
    return {"rows": rows, "models": pics}


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
