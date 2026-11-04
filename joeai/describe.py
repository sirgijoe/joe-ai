"""'Just describe it': plain words in, a mission out, plus a plain-English summary.

The person never has to see TASK:/CHUNKS: unless they open the details. Joe (the local
model) writes the mission; it is parsed and checked like any other, and if it doesn't
parse he gets one more try with the problem pointed out.
"""
from __future__ import annotations

import re

from .mission import MissionError, parse

PLANNER = """You turn a plain request into a work order ("mission") for Joe, an app that does
grunt work overnight on this PC with local AI models. Reply with ONLY the mission block,
nothing before or after it.

What Joe can make: lists of items (product blurbs, captions, emails, FAQs, recipes...),
documents written section by section, spreadsheets (CSV), code drafts, AI pictures, and
short AI video clips. He also has tools that work on the person's own files (listed below,
with the files waiting in Joe's Inbox). He cannot browse the web or send anything.

Mission block format (keys are UPPERCASE):
=== JOE MISSION ===
RULES: optional rules for every task (tone, things to avoid)
TASK: short name                         (one TASK line per kind of thing to make)
CHUNKS: parts x items                    (a list: items are split into small parts)
FORMAT: what each item looks like
MIN WORDS PER ITEM: optional number
=== END ===

Kinds of task:
- List of items: CHUNKS: parts x items. Keep each part 4-10 items. 48 items = CHUNKS: 6 x 8.
- Document: no CHUNKS. One PART line per section, in order:
  PART: ## Section title. What goes in it.
- Spreadsheet: CHUNKS: parts x rows, and HEADER: Column A,Column B,Column C
  plus SAVE: name.csv (the .csv is required for spreadsheets).
- Code: TYPE: code, then PART lines for each file or piece.
- Pictures: TYPE: image, CHUNKS: parts x pictures (e.g. 16 pictures = CHUNKS: 4 x 4),
  FORMAT: subject and style. Pictures are AI art or mockups, never fake photos of real
  products, places or people.
- Video clips: TYPE: video, CHUNKS: 1 x clips (keep it to 1-4 clips), FORMAT: what happens.
{tools}

Rules:
- Match the numbers the person asked for exactly. If they gave none, pick a sensible small
  amount (10-20 items, 4-8 pictures).
- Do NOT write SAVE lines except for spreadsheets; Joe picks the file names.
- Put writing first and pictures/video last.
- Use FORMAT and RULES to pass on every detail they gave (tone, audience, length, style).
- Never invent prices, reviews, quotes or facts; tell Joe to mark unknowns [CHECK]."""

def planner_text() -> str:
    from . import tools as tools_mod
    lines = tools_mod.planner_lines()
    return PLANNER.replace("{tools}", ("- Tools on the person's own files:\n" + lines) if lines else "")


_BLOCK = re.compile(r"===\s*JOE\s+MISSION\s*===.*?===\s*END\s*===", re.S | re.I)
_TASK_START = re.compile(r"(?m)^\s*(PROJECT|RULES|TASK)\s*:")


def extract_block(raw: str) -> str:
    """The mission block from a model reply (with or without the === lines)."""
    raw = re.sub(r"```[\w-]*", "", raw or "")
    m = _BLOCK.search(raw)
    if m:
        return m.group(0).strip()
    t = _TASK_START.search(raw)
    if not t:
        return ""
    return "=== JOE MISSION ===\n" + raw[t.start():].strip() + "\n=== END ==="


def _n(x: int, one: str, many: str) -> str:
    return f"{x} {one if x == 1 else many}"


def plain_summary(chk: dict) -> list[str]:
    """One plain line per task, from App.check()'s result."""
    out = []
    for j in chk.get("jobs", []):
        name = j["name"]
        t = j["type"]
        from .tools import TOOLS
        if t in TOOLS:
            n = j.get("files", 0)
            if t == "transcribe":
                extras = [x for x in ("subtitles", "notes") if not j.get("options") or x in j["options"]]
                tail = (" with " + " and ".join(extras)) if extras else ""
                out.append(f"Transcribe {_n(n, 'recording', 'recordings')}{tail}: {name}")
            else:
                out.append(f"{TOOLS[t].name}: {_n(n, 'file', 'files')} ({name})")
        elif t in ("image", "video"):
            n = j["prompts"] * j["variants"]
            what = _n(n, "picture", "pictures") if t == "image" else _n(n, "short video clip", "short video clips")
            extra = f" ({j['variants']} versions of each)" if j["variants"] > 1 else ""
            out.append(f"{what}: {name}{extra}")
        elif t == "csv":
            out.append(f"A spreadsheet with {_n(j['items'], 'row', 'rows')}: {name}")
        elif j["guided"]:
            noun = "piece" if t == "code" else "section"
            lead = "Code" if t == "code" else "A document"
            out.append(f"{lead} in {_n(j['parts'], noun, noun + 's')}: {name}")
        else:
            words = f", at least {j['min_words']} words each" if j.get("min_words") else ""
            out.append(f"{_n(j['items'], 'item', 'items')}: {name}{words}")
    return out


ROUGH = " (a rough guess until Joe has timed this PC)"


def plain_time(minutes: int) -> str:
    if minutes <= 1:
        return "about a minute"
    if minutes < 60:
        return f"about {minutes} minutes"
    h, m = divmod(minutes, 60)
    hrs = _n(h, "hour", "hours")
    return f"about {hrs}" + (f" {m} min" if m >= 5 else "")


def draft(app, request: str) -> dict:
    """Plain request -> {"ok", "mission", "summary", "time", "eta_min", "warnings"}."""
    request = (request or "").strip()
    if len(request) < 4:
        return {"ok": False, "error": "Tell Joe what you need first, in your own words."}
    request = request[:4000]
    from .chat import busy_drawing
    if busy_drawing(app):
        return {"ok": False, "error": "Joe is busy drawing right now. Try again when the pictures finish."}
    if not app.services.ensure_ollama():
        return {"ok": False, "error": "Ollama isn't running. Setup (F10) > System check can start it."}
    from .doctor import resolve_text_model
    model = resolve_text_model(app.settings, app.services, app.log)
    from . import tools as tools_mod
    waiting = tools_mod.inbox_media(app.sb)
    files_note = ("\n\nRecordings waiting in Joe's Inbox (use these exact names in INPUT):\n"
                  + "\n".join("- " + f for f in waiting)) if waiting else \
                 "\n\nNo recordings are waiting in Joe's Inbox right now."
    msgs = [{"role": "system", "content": planner_text()},
            {"role": "user", "content": "The request, in the person's words:\n" + request + files_note}]
    problem = ""
    for attempt in range(2):
        try:
            r = app.services.ollama.chat(msgs, model=model, max_tokens=1500, keep_alive="20m")
        except Exception as e:
            return {"ok": False, "error": f"Joe couldn't think: {e}"}
        block = extract_block(r.text)
        if not block:
            problem = "there was no mission block in your reply"
        else:
            try:
                parse(block)
                chk = app.check(block)
                if chk["ok"]:
                    return {"ok": True, "mission": block, "summary": plain_summary(chk),
                            "time": plain_time(chk["eta_min"]) + ("" if chk.get("eta_learned") else ROUGH),
                            "eta_min": chk["eta_min"],
                            "warnings": chk.get("warnings", [])}
                problem = chk["error"]
            except MissionError as e:
                problem = str(e)
        msgs += [{"role": "assistant", "content": r.text},
                 {"role": "user", "content": f"That didn't work: {problem}. Reply with the corrected "
                                             "mission block only."}]
    return {"ok": False, "error": "Joe couldn't turn that into a plan (" + problem + "). "
            "Try saying it another way, or use the Builder (F4)."}
