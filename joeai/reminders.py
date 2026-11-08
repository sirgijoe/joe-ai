"""Reminders and lists by voice or the Home box (2.1).

"remind me at 3pm to call the vet", "remind me in 20 minutes to take the bread out",
"add milk to my shopping list", "what's on my shopping list?", "take milk off my list",
"send my shopping list to my phone".

Reminders go to the person's phone through ntfy (the same free phone ping as "Joe is done"),
handed over ahead of time with ntfy's scheduled delivery, so they arrive even when this PC is off.
ntfy holds a message for at most 3 days, so one further out waits in Joe's folder and is handed
over once it's within 3 days (whenever Joe is open). Lists are plain files in Joe's folder.
Nothing here uses an account.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from .fsutil import atomic_write_text

NTFY_MAX = timedelta(days=3) - timedelta(minutes=10)
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "ten": 10, "fifteen": 15,
        "twenty": 20, "thirty": 30, "forty five": 45, "half an": 0.5, "a half": 0.5}


def _clock(h: int, m: int, ap: str, now: datetime, day: datetime | None) -> datetime | None:
    ap = (ap or "").replace(".", "").lower()
    if ap:
        if not 1 <= h <= 12:
            return None
        h = (0 if h == 12 else h) + (12 if ap.startswith("p") else 0)
    if h > 23 or m > 59:
        return None
    base = day or now
    t = base.replace(hour=h, minute=m, second=0, microsecond=0)
    if day is None and t <= now:
        if not ap and h < 12 and t + timedelta(hours=12) > now:    # "at 3" said at 1pm = 3pm
            t += timedelta(hours=12)
        else:
            t += timedelta(days=1)
    return t


_IN = re.compile(r"\bin\s+(\d+(?:\.\d+)?|a|an|one|two|three|four|five|ten|fifteen|twenty|thirty|half an)\s*"
                 r"(minutes?|mins?|hours?|hrs?|days?)\b", re.I)
_AT = re.compile(r"\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)(?=\W|$)|\bat\s+(\d{1,2})(?::(\d{2}))?\b|\b(noon|midnight)\b", re.I)
_DAY = re.compile(r"\b(today|tonight|tomorrow|(?:on\s+|next\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b", re.I)


def parse_when(text: str, now: datetime | None = None) -> tuple[datetime | None, str]:
    """('remind me') 'at 3pm to call the vet' -> (when, 'call the vet'). (None, ...) = no time found."""
    now = (now or datetime.now()).replace(microsecond=0)
    t = " " + (text or "").strip() + " "
    when = None
    m = _IN.search(t)
    if m:
        n = m.group(1).lower()
        val = float(_NUM.get(n, n)) if n in _NUM else float(n)
        unit = m.group(2).lower()
        delta = (timedelta(minutes=val) if unit.startswith("m") else
                 timedelta(hours=val) if unit.startswith("h") else timedelta(days=val))
        when = now + delta
        t = t[:m.start()] + " " + t[m.end():]
    else:
        day = None
        d = _DAY.search(t)
        if d:
            w = d.group(1).lower()
            if w in ("today", "tonight"):
                day = now
            elif w == "tomorrow":
                day = now + timedelta(days=1)
            else:
                target = DAYS.index(d.group(2).lower())
                ahead = (target - now.weekday()) % 7 or 7
                day = now + timedelta(days=ahead)
            t = t[:d.start()] + " " + t[d.end():]
        a = _AT.search(t)
        if a:
            if a.group(6):
                h, mi, ap = (12, 0, "pm") if a.group(6).lower() == "noon" else (12, 0, "am")
            elif a.group(1):
                h, mi, ap = int(a.group(1)), int(a.group(2) or 0), a.group(3)
            else:
                h, mi, ap = int(a.group(4)), int(a.group(5) or 0), ""
            if day is not None and d and d.group(1).lower() == "tonight" and not ap and h < 12:
                ap = "pm"
            when = _clock(h, mi, ap, now, day)
            t = t[:a.start()] + " " + t[a.end():]
        elif day is not None:
            hh = 19 if d.group(1).lower() == "tonight" else 9               # "tomorrow" alone = 9 in the morning
            when = day.replace(hour=hh, minute=0, second=0, microsecond=0)
            if when <= now:
                when = None
    what = re.sub(r"\s+", " ", t).strip(" ,.")
    what = re.sub(r"^(?:to|that|about)\s+", "", what, flags=re.I).strip()
    what = re.sub(r"\s+(?:to|that)$", "", what, flags=re.I).strip()
    return when, what


# --------------------------------------------------------------------------- reminder store
def _file(sb) -> Path:
    return sb.meta / "reminders.json"


def load(sb) -> list[dict]:
    try:
        data = json.loads(_file(sb).read_text(encoding="utf-8"))
        return [r for r in data if isinstance(r, dict)]
    except (OSError, ValueError):
        return []


def save(sb, items: list[dict]) -> None:
    sb.meta.mkdir(parents=True, exist_ok=True)
    atomic_write_text(_file(sb), json.dumps(items, indent=1))
    lines = ["# Reminders", "", "Set by voice or in Joe's box (\"remind me at 3pm to call the vet\"). They come "
             "to your phone as a phone ping.", ""]
    for r in sorted(items, key=lambda x: x["when"]):
        if r.get("done"):
            continue
        state = "on its way to your phone" if r.get("sent") else "waiting (sent when it's within 3 days)"
        lines.append(f"- {r['when'][:16].replace('T', ' ')}: {r['what']} ({state})")
    atomic_write_text(sb.root / "Reminders.md", "\n".join(lines) + "\n")


def add(sb, settings, text: str, now: datetime | None = None, send=None) -> dict:
    """'at 3pm to call the vet' -> a reminder. Returns {"ok", "say"} or {"ok": False, "error"}."""
    from . import notify
    now = now or datetime.now()
    when, what = parse_when(text, now)
    if not what:
        return {"ok": False, "error": "What should Joe remind you about? Like: remind me at 3pm to call the vet."}
    if not when:
        return {"ok": False, "error": f"When? Say a time, like: remind me at 3pm to {what}, or in 20 minutes, or tomorrow at 9."}
    if when <= now:
        return {"ok": False, "error": "That time has already gone by. Say a time later today, or tomorrow."}
    topic = (settings.comfort.ntfy_topic or "").strip()
    item = {"when": when.isoformat(timespec="minutes"), "what": what, "sent": False,
            "made": now.isoformat(timespec="seconds")}
    items = load(sb) + [item]
    nice = when.strftime("%a %b %d, %I:%M %p").replace(", 0", ", ")
    if not topic:
        save(sb, items)
        return {"ok": True, "say": f"Saved: {what}, {nice}. To get it on your phone, turn on phone pings in Setup > "
                                   "Display & sound (ntfy, free). It's in Reminders.md (Files, F7) meanwhile."}
    err = ""
    if when - now <= NTFY_MAX:
        err = (send or notify.send_ntfy)(settings.comfort.ntfy_server, topic, f"Reminder: {what}",
                                         title="Joe reminder", at=int(when.timestamp()), priority="high")
        item["sent"] = not err
    save(sb, items)
    if err:
        return {"ok": False, "error": f"Saved, but the phone ping didn't go out yet ({err}). Joe tries again later."}
    later = "" if item["sent"] else " It's more than 3 days away, so Joe sends it to your phone when it's closer (whenever he's open)."
    return {"ok": True, "say": f"OK: {what}, {nice}. It'll come to your phone, even if this PC is off.{later}"}


def tick(sb, settings, now: datetime | None = None, send=None) -> int:
    """Hand over waiting reminders that are now within ntfy's 3 days; drop old ones. Returns how many sent."""
    from . import notify
    topic = (settings.comfort.ntfy_topic or "").strip()
    items = load(sb)
    if not items:
        return 0
    now = now or datetime.now()
    sent, keep = 0, []
    for r in items:
        try:
            when = datetime.fromisoformat(r["when"])
        except (KeyError, ValueError):
            continue
        if when < now - timedelta(days=1):
            continue                                            # long past: tidy away
        if topic and not r.get("sent") and when > now and when - now <= NTFY_MAX:
            if not (send or notify.send_ntfy)(settings.comfort.ntfy_server, topic, f"Reminder: {r['what']}",
                                              title="Joe reminder", at=int(when.timestamp()), priority="high"):
                r["sent"] = True
                sent += 1
        keep.append(r)
    if keep != items or sent:
        save(sb, keep)
    return sent


# --------------------------------------------------------------------------- lists
def list_name(name: str) -> str:
    n = re.sub(r"[^a-z0-9 -]", "", (name or "").lower()).strip()
    n = {"": "to-do", "todo": "to-do", "to do": "to-do", "grocery": "shopping", "groceries": "shopping"}.get(n, n)
    return n[:30] or "to-do"


def _list_path(sb, name: str) -> Path:
    return sb.root / "Lists" / f"{list_name(name).title().replace(' ', '-')} list.md"


def read_list(sb, name: str) -> list[str]:
    try:
        return [ln[6:].strip() for ln in _list_path(sb, name).read_text(encoding="utf-8").splitlines()
                if ln.startswith("- [ ] ")]
    except OSError:
        return []


def _write_list(sb, name: str, items: list[str]) -> None:
    p = _list_path(sb, name)
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(p, f"# {list_name(name).capitalize()} list\n\n" + "".join(f"- [ ] {x}\n" for x in items))


def list_add(sb, name: str, things: str) -> dict:
    new = [x.strip(" .") for x in re.split(r",\s*|\s+and\s+", things or "") if x.strip(" .")]
    if not new:
        return {"ok": False, "error": "Add what? Like: add milk and eggs to my shopping list."}
    items = read_list(sb, name)
    added = [x for x in new if x.lower() not in {i.lower() for i in items}]
    _write_list(sb, name, items + added)
    n = len(items) + len(added)
    what = " and ".join(added) if added else "That"
    return {"ok": True, "say": (f"Added {what} to your {list_name(name)} list" if added else
                                f"{things.strip()} is already on your {list_name(name)} list") + f" ({n} thing{'s' if n != 1 else ''})."}


def list_done(sb, name: str, things: str) -> dict:
    items = read_list(sb, name)
    gone = [x.strip(" .").lower() for x in re.split(r",\s*|\s+and\s+", things or "") if x.strip(" .")]
    left = [i for i in items if i.lower() not in gone]
    if len(left) == len(items):
        return {"ok": False, "error": f"That isn't on your {list_name(name)} list."}
    _write_list(sb, name, left)
    return {"ok": True, "say": f"Done. {len(left)} thing{'s' if len(left) != 1 else ''} left on your {list_name(name)} list."}


def list_show(sb, name: str) -> dict:
    items = read_list(sb, name)
    if not items:
        return {"ok": True, "say": f"Your {list_name(name)} list is empty."}
    return {"ok": True, "say": f"Your {list_name(name)} list: " + ", ".join(items) + "."}


def list_send(sb, settings, name: str, send=None) -> dict:
    from . import notify
    items = read_list(sb, name)
    topic = (settings.comfort.ntfy_topic or "").strip()
    if not items:
        return {"ok": False, "error": f"Your {list_name(name)} list is empty."}
    if not topic:
        return {"ok": False, "error": "Turn on phone pings first (Setup > Display & sound, ntfy, free)."}
    err = (send or notify.send_ntfy)(settings.comfort.ntfy_server, topic, "\n".join(f"- {x}" for x in items),
                                     title=f"{list_name(name).capitalize()} list")
    return {"ok": not err, "say": f"Sent your {list_name(name)} list to your phone.", "error": err}


# --------------------------------------------------------------------------- directions and shopping
MAPS = {"google": "https://www.google.com/maps/dir/?api=1&destination={q}",
        "osm": "https://www.openstreetmap.org/search?query={q}",
        "apple": "https://maps.apple.com/?daddr={q}",
        "bing": "https://www.bing.com/maps?rtp=~adr.{q}"}
SHOPS = {"google": "https://www.google.com/search?tbm=shop&q={q}",
         "duckduckgo": "https://duckduckgo.com/?q={q}&ia=shopping",
         "bing": "https://www.bing.com/shop?q={q}"}


def directions(settings, place: str) -> dict:
    from urllib.parse import quote
    place = (place or "").strip(" ?.!")
    if not place:
        return {"ok": False, "error": "Directions to where? Like: directions to the nearest hardware store."}
    site = getattr(settings.comfort, "maps", "google")
    url = MAPS.get(site, MAPS["google"]).format(q=quote(place))
    return {"ok": True, "open": url, "say": f"Opening directions to {place} in your browser. Joe doesn't track "
                                            "where you go; the map site works out the route from your location."}


def shopping(settings, thing: str) -> dict:
    from urllib.parse import quote
    thing = (thing or "").strip(" ?.!")
    if not thing:
        return {"ok": False, "error": "Shop for what? Like: where can I buy a cheap air fryer?"}
    site = getattr(settings.comfort, "shop", "google")
    url = SHOPS.get(site, SHOPS["google"]).format(q=quote(thing))
    return {"ok": True, "open": url, "say": f"Opening a shopping search for {thing} in your browser. Joe doesn't pick "
                                            "for you or get paid by any store: compare the prices there."}
