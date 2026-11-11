"""Moving through results by voice in Talk (2.3): "read the third one", "next", "go back",
"skip to the CHECK items", "how many are there?", "read the list".

What gets read: the last answer of Joe's in this chat that is a list (numbered, bullets, "## " items or
table rows), or the morning report when the person says "report". No model is asked: it's instant, and
the words come out exactly as written. Anything that isn't one of these short commands goes to Joe as
usual (this only answers when it's sure).
"""
from __future__ import annotations

import hashlib
import re

_NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
              "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
              "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20}
_ORD_WORDS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
              "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12, "thirteenth": 13, "fourteenth": 14,
              "fifteenth": 15, "sixteenth": 16, "seventeenth": 17, "eighteenth": 18, "nineteenth": 19,
              "twentieth": 20}
_WORDS = "|".join(sorted(list(_NUM_WORDS) + list(_ORD_WORDS), key=len, reverse=True))


def _n(g: str) -> str:
    return rf"(?P<{g}>\d{{1,3}}(?:st|nd|rd|th)?|{_WORDS}|last)"
_THING = r"(?:one|item|result|line|thing|entry|bit|point|answer)s?"
_LEAD = r"^(?:(?:ok(?:ay)?|now|and|so|please|joe|hey joe)[,\s]+)*"
_TAIL = r"(?:[,\s]+(?:please|again|joe|thanks))*[.!?]*$"
PATTERNS = [
    ("item", re.compile(_LEAD + r"(?:(?:can you |could you )?(?:read|say|tell me|what'?s|what is|go to|jump to|skip to|give me)\s+)?"
                        r"(?:me\s+)?(?:the\s+)?(?:" + _n("n") + r"\s+" + _THING + r"|(?:" + _THING + r"|number)\s+" + _n("m") + r")"
                        r"(?:\s+in the (?:list|report))?" + _TAIL, re.I)),
    ("item", re.compile(_LEAD + r"(?:read|go to|jump to)\s+(?:number\s+)?" + _n("n") + _TAIL, re.I)),
    ("next", re.compile(_LEAD + r"(?:next(?:\s+" + _THING + r")?|(?:read |go to )?the next(?:\s+" + _THING + r")?|"
                        r"skip(?: (?:it|this|that|ahead))?|go on|keep going|carry on|and then)" + _TAIL, re.I)),
    ("prev", re.compile(_LEAD + r"(?:previous(?:\s+" + _THING + r")?|(?:read |go to )?the previous(?:\s+" + _THING + r")?|"
                        r"go back(?: one)?|back(?: one)?|before that)" + _TAIL, re.I)),
    ("again", re.compile(_LEAD + r"(?:again|repeat(?: that| it)?|say (?:that|it) again|read (?:that|it) again|"
                         r"what was that|come again)" + _TAIL, re.I)),
    ("check", re.compile(_LEAD + r"(?:(?:read|skip to|jump to|go to|show me|what are)\s+)?(?:the\s+|only\s+)?"
                         r"(?:check(?:ed)?\s+(?:items?|ones?|lines?|bits?|flags?)|items? (?:to|i need to|that need) check|"
                         r"what needs (?:a )?check(?:ing)?|what should i check|flags?)" + _TAIL, re.I)),
    ("count", re.compile(_LEAD + r"how many(?: (?:are there|items|results|ones|things|in the (?:list|report)|"
                         r"check items|are left))?\??" + _TAIL, re.I)),
    ("list", re.compile(_LEAD + r"(?:read (?:me )?(?:the|all the|all of the)?\s*(?:titles|headings|list|names)|"
                        r"what(?:'s| is| are) (?:on|in) the list|list them|read them all)" + _TAIL, re.I)),
    ("all", re.compile(_LEAD + r"(?:all|everything|the whole (?:thing|list)|read (?:it|them) all out)" + _TAIL, re.I)),
]
_REPORT_WORD = re.compile(r"\breport\b", re.I)
_ITEM_LINE = re.compile(r"^\s*(?:\d{1,3}[.)]\s+|[-*•]\s+|#{2,3}\s+)(.*\S)")
MAX_SAY = 2500


def _num(word: str, total: int) -> int:
    w = word.lower()
    if w == "last":
        return total
    if w in _NUM_WORDS:
        return _NUM_WORDS[w]
    if w in _ORD_WORDS:
        return _ORD_WORDS[w]
    return int(re.match(r"\d+", w).group())


def command(text: str) -> dict | None:
    t = " ".join((text or "").strip().split())
    if not t or len(t) > 80:
        return None
    t = t.replace("’", "'")
    for kind, rx in PATTERNS:
        m = rx.match(t)
        if m:
            out = {"kind": kind, "report": bool(_REPORT_WORD.search(t))}
            if kind == "item":
                out["word"] = m.groupdict().get("n") or m.groupdict().get("m")
            return out
    return None


def items(text: str) -> list[str]:
    """A reply or report cut into its items. Each item keeps the lines under it ('## Title' + body)."""
    lines = (text or "").replace("\r", "").split("\n")
    out: list[str] = []
    cur: list[str] | None = None
    cur_heading = False
    for ln in lines:
        if ln.strip().startswith("|") and ln.strip().endswith("|"):          # a table row
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):        # the |---| line
                if out:
                    out.pop()                                                 # the line above it was the header
                cur = None
                continue
            if cur is not None:
                out.append("\n".join(cur).strip())
            cur = None
            out.append(" — ".join(c for c in cells if c))
            continue
        m = _ITEM_LINE.match(ln)
        if m:
            heading = ln.lstrip().startswith("#")
            # a "## Flags" heading with nothing under it, then a list: it names the list, it isn't an item
            if cur is not None and not (cur_heading and len(cur) == 1 and not heading):
                out.append("\n".join(cur).strip())
            cur, cur_heading = [m.group(1)], heading
        elif cur is not None and ln.strip():
            cur.append(ln.strip())
        elif cur is not None and not ln.strip() and len(cur) > 1:
            cur.append("")
    if cur is not None:
        out.append("\n".join(cur).strip())
    return [x for x in (o.strip() for o in out) if x]


def is_check(item: str) -> bool:
    return bool(re.search(r"\[CHECK|\bCHECK:|\bCHECK\b", item))


def _source(app, history: list[dict], want_report: bool) -> tuple[str, list[str]]:
    if not want_report:
        for h in reversed(history or []):
            if h.get("role") == "assistant" and isinstance(h.get("content"), str):
                got = items(h["content"])
                if len(got) >= 2:
                    return "reply", got
                break                                 # only Joe's latest answer counts
    try:
        rep = (app.sb.output / "_REPORT.md").read_text(encoding="utf-8")
    except OSError:
        return "", []
    if not want_report and (getattr(app, "nav", None) or {}).get("src") != "report":
        return "", []                                 # "next" after a report question keeps to the report
    return "report", items(rep)


def answer(app, history: list[dict], text: str) -> dict | None:
    """A reply for Talk, or None when this isn't a results command (or there are no results)."""
    cmd = command(text)
    if not cmd:
        return None
    src, its = _source(app, history, cmd["report"])
    if len(its) < 2:
        if cmd["report"]:
            return {"ok": True, "say": "There's no morning report with a list in it yet.", "mission": ""}
        return None                                   # nothing to move through: let Joe answer
    key = hashlib.sha1(("\n".join(its)).encode()).hexdigest()[:10]
    nav = getattr(app, "nav", None) or {}
    if nav.get("key") != key:
        nav = {"key": key, "pos": -1, "check": False}
    nav["src"] = src
    if cmd["kind"] == "again" and nav["pos"] < 0:
        return None                                   # "again" before reading anything: let Joe answer (redo...)
    pool = list(range(len(its)))
    kind = cmd["kind"]
    if kind == "check":
        nav["check"] = True
    if kind in ("item", "list", "all"):
        nav["check"] = False
    if nav["check"]:
        pool = [i for i in pool if is_check(its[i])]
        if not pool:
            nav["check"] = False
            app.nav = nav
            return _say("Nothing in it is marked CHECK.")
    where = "the report" if src == "report" else "the list"
    if kind == "count":
        app.nav = nav
        n_check = sum(1 for x in its if is_check(x))
        return _say(f"There are {len(its)} in {where}" + (f", {n_check} marked CHECK." if n_check else "."))
    if kind == "list":
        app.nav = nav
        heads = [f"{i + 1}: {its[i].splitlines()[0][:90]}" for i in range(len(its))]
        return _say(f"{len(its)} in {where}. " + ". ".join(heads[:30]) + ("." if len(heads) <= 30 else ", and more."))
    if kind == "all":
        app.nav = nav
        return _say("\n\n".join(f"{i + 1}. {x}" for i, x in enumerate(its)))
    if kind == "check":
        i = pool[0]
    elif kind == "item":
        n = _num(cmd["word"], len(its))
        if not 1 <= n <= len(its):
            app.nav = nav
            return _say(f"There are only {len(its)} in {where}.")
        i = n - 1
        nav["check"] = False
    elif kind == "next":
        after = [p for p in pool if p > nav["pos"]]
        if not after:
            app.nav = nav
            return _say("That was the last one" + (" marked CHECK." if nav["check"] else "."))
        i = after[0]
    elif kind == "prev":
        before = [p for p in pool if p < nav["pos"]]
        if not before:
            app.nav = nav
            return _say("That was the first one.")
        i = before[-1]
    else:                                             # again
        i = nav["pos"] if nav["pos"] >= 0 else pool[0]
    nav["pos"] = i
    app.nav = nav
    label = f"Number {i + 1} of {len(its)}"
    if nav["check"]:
        label += f", CHECK item {pool.index(i) + 1} of {len(pool)}" if i in pool else ""
    return _say(f"{label}. {its[i]}")


def _say(text: str) -> dict:
    from .chat import speakable
    return {"ok": True, "say": speakable(text)[:MAX_SAY], "mission": "", "raw": text[:MAX_SAY], "nav": True}
