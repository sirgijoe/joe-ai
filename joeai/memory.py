"""Memory (2.3): short notes the person asks Joe to remember ("remember that I like short captions").

Opt-in: nothing is remembered until Setup > Memory > "Joe may remember things I tell him" is on.
The person sees, edits and deletes every note in Setup > Memory (and can say "forget that ...").
Kept on this PC only: memory.json in Joe's settings folder, never in the workspace, never sent
anywhere. Left out of a settings backup unless "include memory" is ticked.

Who sees the notes:
  - Joe's own window: Talk uses them, and the planner on Home may turn them into RULES of a plan
    (so they show up, in plain sight, in the plan before anything runs).
  - Joe Phone: only when Setup > Memory > "Joe Phone may use them" is on.
  - the connector (another AI app): only when "Apps connected to Joe may read them" is on.
Overnight work only follows the plan as written; it never reads the notes by itself.

ORIGIN says who is asking (a context variable: each phone / connector request sets it).
"""
from __future__ import annotations

import contextvars
import json
import re
import secrets
from datetime import datetime
from pathlib import Path

from .fsutil import atomic_write_text

ORIGIN: contextvars.ContextVar[str] = contextvars.ContextVar("joe_origin", default="window")
MAX_NOTES = 200
MAX_CHARS = 500
FILE = "memory.json"

_LEAD = r"^\s*(?:(?:hey|ok|okay)\s+)?(?:joe[,!]?\s+)?(?:please\s+)?(?:can you\s+|could you\s+)?"
_REMEMBER = re.compile(_LEAD + r"remember\s+(?:this\s+about\s+me|that|this|the\s+fact\s+that)?\s*[:,-]?\s*(.{3,})$",
                       re.I | re.S)
_REMEMBER_I = re.compile(_LEAD + r"remember\s+((?:i|i'm|i am|i've|i have|my|we|we're|our)\b.{2,})$", re.I | re.S)
_SHOW = re.compile(_LEAD + r"(?:what\s+do\s+you\s+(?:remember|know)\s+about\s+me|what\s+have\s+you\s+remembered|"
                   r"show\s+(?:me\s+)?(?:my\s+)?(?:memory|memories|notes\s+about\s+me))\s*[?.!]*$", re.I)
_FORGET = re.compile(_LEAD + r"forget\s+(?:that|about|what\s+i\s+said\s+about|the\s+(?:note|bit)\s+about)\s+(.{2,})$",
                     re.I | re.S)


def path() -> Path:
    from .config import config_path
    return config_path().with_name(FILE)


def load() -> list[dict]:
    try:
        d = json.loads(path().read_text(encoding="utf-8"))
        notes = d.get("notes", []) if isinstance(d, dict) else []
        return [n for n in notes if isinstance(n, dict) and isinstance(n.get("text"), str) and n.get("id")]
    except (OSError, ValueError):
        return []


def _save(notes: list[dict]) -> None:
    atomic_write_text(path(), json.dumps({"notes": notes[:MAX_NOTES]}, indent=1, ensure_ascii=False))


def _clean(text: str) -> str:
    t = " ".join(str(text or "").split())[:MAX_CHARS].strip()
    return t[:1].upper() + t[1:] if t else ""


def enabled(settings) -> bool:
    return bool(getattr(getattr(settings, "memory", None), "enabled", False))


def allowed(settings, origin: str | None = None) -> bool:
    """May this caller see the notes?"""
    if not enabled(settings):
        return False
    who = origin or ORIGIN.get()
    m = settings.memory
    return who == "window" or (who == "phone" and m.phone) or (who == "connector" and m.connector)


def add(settings, text: str) -> dict:
    if not enabled(settings):
        return {"ok": False, "error": "Memory is off. Turn it on in Setup > Memory first, then ask again."}
    t = _clean(text)
    if not t:
        return {"ok": False, "error": "What should Joe remember?"}
    notes = load()
    if any(n["text"].lower() == t.lower() for n in notes):
        return {"ok": True, "say": "I already have that one.", "id": next(n["id"] for n in notes if n["text"].lower() == t.lower())}
    if len(notes) >= MAX_NOTES:
        return {"ok": False, "error": f"Joe's memory is full ({MAX_NOTES} notes). Delete some in Setup > Memory."}
    now = datetime.now().isoformat(timespec="seconds")
    n = {"id": secrets.token_hex(4), "text": t, "made": now, "changed": now}
    _save(notes + [n])
    return {"ok": True, "id": n["id"], "say": f"Got it. I'll remember: {t} (Setup > Memory shows it.)"}


def edit(note_id: str, text: str) -> dict:
    t = _clean(text)
    notes = load()
    for n in notes:
        if n["id"] == note_id:
            if not t:
                return delete(note_id)
            n["text"], n["changed"] = t, datetime.now().isoformat(timespec="seconds")
            _save(notes)
            return {"ok": True}
    return {"ok": False, "error": "That note is gone."}


def delete(note_id: str) -> dict:
    notes = load()
    keep = [n for n in notes if n["id"] != note_id]
    if len(keep) == len(notes):
        return {"ok": False, "error": "That note is gone."}
    _save(keep)
    return {"ok": True}


def clear() -> dict:
    n = len(load())
    _save([])
    return {"ok": True, "deleted": n}


def _words(t: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9']+", t.lower()) if len(w) > 2 and w not in
            {"the", "and", "that", "this", "with", "for", "about", "said", "what", "you", "are", "was"}}


def forget(text: str) -> dict:
    """"forget that I like emojis": the note that matches best goes (only a clear match)."""
    want = _words(text)
    notes = load()
    if not want or not notes:
        return {"ok": True, "say": "I don't have a note like that."}
    best, score = None, 0.0
    for n in notes:
        have = _words(n["text"])
        s = len(want & have) / max(1, len(want))
        if s > score:
            best, score = n, s
    if not best or score < 0.6:
        return {"ok": True, "say": "I'm not sure which note you mean. Setup > Memory lists them all."}
    delete(best["id"])
    return {"ok": True, "say": f"Forgotten: {best['text']}"}


def command(text: str) -> dict | None:
    """'remember that ...', 'what do you remember about me?', 'forget that ...' -> a command, else None.
    ("remember to buy milk" is a reminder, not memory: it's left alone.)"""
    raw = (text or "").strip()
    if not raw or len(raw) > 700:
        return None
    if _SHOW.match(raw):
        return {"memory": "show"}
    m = _FORGET.match(raw)
    if m:
        return {"memory": "forget", "text": m.group(1).strip(" .!")}
    if re.match(_LEAD + r"remember\s+to\b", raw, re.I):
        return None
    m = _REMEMBER_I.match(raw) or _REMEMBER.match(raw)
    if m:
        return {"memory": "add", "text": m.group(1).strip()}
    return None


def handle(settings, cmd: dict, origin: str | None = None) -> dict:
    """Do a memory command for Talk, Home or the phone. Returns {"ok", "say"} or {"ok": False, "error"}."""
    who = origin or ORIGIN.get()
    if who == "connector":
        return {"ok": False, "error": "Memory can only be changed from Joe's own window."}
    if who == "phone" and not (enabled(settings) and settings.memory.phone):
        return {"ok": True, "say": "Memory works on Joe's own screen. (Setup > Memory can let Joe Phone use it.)"}
    if not enabled(settings):
        return {"ok": True, "say": "My memory is off, so I won't keep that. You can turn it on in Setup > Memory."}
    kind = cmd.get("memory")
    if kind == "add":
        return add(settings, cmd.get("text", ""))
    if kind == "forget":
        return forget(cmd.get("text", ""))
    notes = load()
    if not notes:
        return {"ok": True, "say": "I haven't been asked to remember anything yet."}
    return {"ok": True, "say": "You asked me to remember: " + " ".join(f"{i}. {n['text']}" for i, n in
                                                                      enumerate(notes[:30], 1))}


def context(settings, origin: str | None = None) -> str:
    """The notes as a few lines for Talk or the planner, or '' when this caller may not see them."""
    if not allowed(settings, origin):
        return ""
    notes = load()
    if not notes:
        return ""
    return ("Things the person asked Joe to remember about them (their own notes; follow them unless they "
            "say otherwise now; never repeat them back unasked):\n" + "\n".join(f"- {n['text']}" for n in notes[:60]))


# ------------------------------------------------------------------------- backup
def for_backup() -> dict:
    return {"notes": load()}


def restore(data: dict) -> int:
    """Notes from a backup are added (the ones already here stay; duplicates aren't doubled)."""
    have = load()
    texts = {n["text"].lower() for n in have}
    added = 0
    for n in (data or {}).get("notes", []):
        t = _clean(n.get("text", "")) if isinstance(n, dict) else ""
        if t and t.lower() not in texts and len(have) < MAX_NOTES:
            now = datetime.now().isoformat(timespec="seconds")
            have.append({"id": secrets.token_hex(4), "text": t, "made": str(n.get("made") or now)[:19], "changed": now})
            texts.add(t.lower())
            added += 1
    if added:
        _save(have)
    return added
