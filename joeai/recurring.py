"""Recurring missions (2.3): "every Sunday night, make next week's meal plan".

A recurring mission is a plan the person saw and chose to repeat (REPEAT ... under a plan on Home).
It rides on the night shift: when the night shift starts on one of its days, Joe puts a copy into
Missions/Tonight and it runs with the rest. The night shift has to be on (Setup > General); the
list in Setup > General > RECURRING MISSIONS says so when it isn't, and lets each one be paused,
started again or deleted (a deleted one is kept as a .txt in Missions/Recurring/removed).

Which night: a night shift that starts before noon (01:00) counts as the night before (Sunday night).
Kept in Missions/Recurring/recurring.json: [{id, label, when, days, mission, paused, last, made}].
"""
from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timedelta
from pathlib import Path

from .fsutil import atomic_write_text

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
SHORT = {d[:3]: i for i, d in enumerate(DAYS)} | {"tues": 1, "weds": 2, "thur": 3, "thurs": 3}
MAX = 50
_DAY = r"(?:mon|tues?|wed(?:nes)?|thu(?:rs?)?|fri|sat(?:ur)?|sun)(?:day)?s?"
_DAYS = r"(?:mon|tues|wednes|thurs|fri|satur|sun)days"          # "on Sundays" repeats; "on Sunday" is one day
_WHEN = re.compile(
    r"^\s*(?:please\s+)?(?:(?:every|each)\s+(?P<every>day|night|evening|weekday|weekend|week|"
    + _DAY + r"(?:\s*(?:,|and|&)\s*" + _DAY + r")*)|on\s+(?P<on>" + _DAYS + r"(?:\s*(?:,|and|&)\s*" + _DAYS + r")*))"
    r"(?:\s+(?:night|evening|morning|overnight))?\s*[,:-]?\s+(?P<rest>.{4,})$", re.I | re.S)


def folder(sb) -> Path:
    return sb.missions / "Recurring"


def _path(sb) -> Path:
    return folder(sb) / "recurring.json"


def load(sb) -> list[dict]:
    try:
        d = json.loads(_path(sb).read_text(encoding="utf-8"))
        return [x for x in d if isinstance(x, dict) and x.get("id") and isinstance(x.get("days"), list)]
    except (OSError, ValueError, TypeError):
        return []


def _save(sb, items: list[dict]) -> None:
    folder(sb).mkdir(parents=True, exist_ok=True)
    atomic_write_text(_path(sb), json.dumps(items[:MAX], indent=1, ensure_ascii=False))


def _day_list(words: str, today: int) -> list[int]:
    w = words.lower()
    if w in ("day", "night", "evening"):
        return list(range(7))
    if w == "weekday":
        return [0, 1, 2, 3, 4]
    if w == "weekend":
        return [5, 6]
    if w == "week":
        return [today]
    out = []
    for tok in re.findall(r"[a-z]+", w):
        if tok in ("and",):
            continue
        tok = tok.rstrip("s") if tok.endswith("days") else tok
        key = tok[:5] if tok[:5] in SHORT else tok[:4] if tok[:4] in SHORT else tok[:3]
        if key in SHORT and SHORT[key] not in out:
            out.append(SHORT[key])
    return sorted(out)


def words(days: list[int]) -> str:
    d = sorted(set(days))
    if d == list(range(7)):
        return "every night"
    if d == [0, 1, 2, 3, 4]:
        return "every weekday night"
    if d == [5, 6]:
        return "every weekend night"
    names = [DAYS[i].capitalize() for i in d]
    return "every " + (names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]) + " night"


def parse(text: str, today: int | None = None) -> dict | None:
    """'every Sunday night, make next week's meal plan' -> {days: [6], when: 'every Sunday night',
    request: "make next week's meal plan"}; None when it isn't a repeating request."""
    m = _WHEN.match(text or "")
    if not m:
        return None
    today = datetime.now().weekday() if today is None else today
    days = _day_list((m.group("every") or m.group("on") or "").strip(), today)
    if not days:
        return None
    return {"days": days, "when": words(days), "request": m.group("rest").strip()}


def add(sb, mission: str, days: list[int], label: str = "") -> dict:
    from .mission import MissionError, parse as parse_mission
    try:
        m = parse_mission(mission)
    except MissionError as e:
        return {"ok": False, "error": f"That plan has a problem: {e}"}
    days = sorted({int(d) for d in days if 0 <= int(d) <= 6})
    if not days:
        return {"ok": False, "error": "Pick at least one day."}
    items = load(sb)
    if len(items) >= MAX:
        return {"ok": False, "error": f"There are already {MAX} recurring missions. Delete some first."}
    label = " ".join((label or ", ".join(j.name for j in m.jobs[:3])).split())[:80]
    item = {"id": secrets.token_hex(4), "label": label, "days": days, "when": words(days),
            "mission": mission.strip(), "paused": False, "last": "",
            "made": datetime.now().isoformat(timespec="seconds")}
    _save(sb, items + [item])
    return {"ok": True, "id": item["id"], "say": f"Saved: {label}, {item['when']}."}


def set_paused(sb, rid: str, paused: bool) -> dict:
    items = load(sb)
    for x in items:
        if x["id"] == rid:
            x["paused"] = bool(paused)
            _save(sb, items)
            return {"ok": True}
    return {"ok": False, "error": "That recurring mission is gone."}


def delete(sb, rid: str) -> dict:
    items = load(sb)
    gone = [x for x in items if x["id"] == rid]
    if not gone:
        return {"ok": False, "error": "That recurring mission is gone."}
    keep = folder(sb) / "removed"
    keep.mkdir(parents=True, exist_ok=True)
    atomic_write_text(keep / f"{rid}.txt", gone[0].get("mission", "") + "\n")
    _save(sb, [x for x in items if x["id"] != rid])
    return {"ok": True, "note": "Deleted. A copy of its plan is in Missions/Recurring/removed."}


def night_of(now: datetime, shift_time: str) -> datetime:
    """The evening a night shift belongs to: one that starts before noon is the night before."""
    try:
        hh = int((shift_time or "23:00").split(":")[0])
    except ValueError:
        hh = 23
    return now - timedelta(days=1) if hh < 12 and now.hour < 12 else now


def due(sb, settings, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now()
    night = night_of(now, settings.schedule.time)
    tag = night.strftime("%Y-%m-%d")
    return [x for x in load(sb) if not x.get("paused") and night.weekday() in x["days"] and x.get("last") != tag]


def queue_due(sb, settings, now: datetime | None = None) -> list[str]:
    """Night shift start: each recurring mission due tonight -> Missions/Tonight (marked as run tonight,
    so a second start the same night doesn't queue it twice)."""
    now = now or datetime.now()
    tag = night_of(now, settings.schedule.time).strftime("%Y-%m-%d")
    todo = due(sb, settings, now)
    if not todo:
        return []
    dst = sb.missions / "Tonight"
    dst.mkdir(parents=True, exist_ok=True)
    made = []
    items = load(sb)
    for x in todo:
        name = f"recurring-{x['id']}-{tag}.txt"
        atomic_write_text(dst / name, x["mission"].rstrip() + "\n")
        made.append(name)
        for y in items:
            if y["id"] == x["id"]:
                y["last"] = tag
    _save(sb, items)
    return made
