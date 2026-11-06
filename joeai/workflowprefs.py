"""Setup > Workflows: your own touches for each way Joe makes pictures, video and sound.

For every workflow (Joe's built-in ones, each picture style, and the workflow files you
imported) you can set: the model to use, words added to every prompt ("always add"), words
added to every leave-out list ("always leave out") and, for pictures, the number of steps.
They're kept in settings.json (Settings.workflows); Joe's own files are never edited, and
RESET THIS WORKFLOW (or Setup's RESET ALL) takes them away again.
"""
from __future__ import annotations

from pathlib import Path

FIELDS = ("model", "add", "avoid", "steps")

# id -> (group, label, what it covers, can pick a model, can set steps)
BUILTIN = {
    "pictures": ("Joe's built-in", "Pictures (every style)", "Joe's own text-to-picture graph, used by every picture task "
                 "that has no workflow file. A picture style's own settings below come first.", True, True),
    "video": ("Joe's built-in", "Video clips", "Wan 2.2 video tasks (and black-and-white video).", False, False),
    "editor": ("Joe's built-in", "Picture editor tools", "Edit a picture, AI photo repair, Fix one spot, Put pictures "
               "together, Change the lighting, Redraw, Make it bigger, character tools.", False, False),
    "animate": ("Joe's built-in", "Animate a photo", "Photo-to-clip (Wan 2.2).", False, False),
    "music": ("Joe's built-in", "Music", "ACE-Step music tracks.", False, False),
    "sfx": ("Joe's built-in", "Sound effects", "Stable Audio Open sound effects.", False, False),
}


def _clean(p: dict | None) -> dict:
    p = p if isinstance(p, dict) else {}
    out = {}
    for k in ("model", "add", "avoid"):
        v = " ".join(str(p.get(k) or "").split())[:600]
        if v:
            out[k] = v
    try:
        steps = int(p.get("steps") or 0)
    except (TypeError, ValueError):
        steps = 0
    if 1 <= steps <= 150:
        out["steps"] = steps
    return out


def get(settings, wid: str) -> dict:
    return _clean((getattr(settings, "workflows", None) or {}).get(wid))


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
    pics = [m.name for m in comfy.scan_models(models_dir) if m.folder == "checkpoints"]
    rows = []
    for wid, (group, label, about, can_model, can_steps) in BUILTIN.items():
        rows.append({"id": wid, "group": group, "label": label, "about": about, "model_ok": can_model,
                     "steps_ok": can_steps, "prefs": get(settings, wid)})
    for sid in styles.NAMES:
        if sid == "general":
            continue
        st = styles.STYLES[sid]
        rows.append({"id": f"style:{sid}", "group": "Picture styles", "label": st.label,
                     "about": f"Pictures with STYLE: {sid}.", "model_ok": True, "steps_ok": True,
                     "prefs": get(settings, f"style:{sid}")})
    folder = sb.workflows
    for f in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        rows.append({"id": f"file:{f.name}", "group": "Your workflow files", "label": f.name,
                     "about": "A workflow you imported (Workflows folder). The model is used if the file has "
                              "a checkpoint loader.", "model_ok": True, "steps_ok": False,
                     "prefs": get(settings, f"file:{f.name}")})
    return {"rows": rows, "models": pics}


def save(settings, wid: str, prefs: dict | None) -> dict:
    """prefs None = reset this workflow."""
    if not (wid in BUILTIN or wid.startswith("style:") or wid.startswith("file:")):
        return {"ok": False, "error": "Unknown workflow."}
    wf = dict(getattr(settings, "workflows", None) or {})
    clean = _clean(prefs) if prefs is not None else {}
    if clean:
        wf[wid] = clean
    else:
        wf.pop(wid, None)
    settings.workflows = wf
    settings.save()
    return {"ok": True, "prefs": clean}
