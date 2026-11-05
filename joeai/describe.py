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

_WANTS_VIDEO = re.compile(r"\b(videos?|clips?|animations?|animated|movie|footage|mp4|gifs?)\b", re.I)
_WANTS_PICS = re.compile(r"\b(pictures?|images?|illustrations?|drawings?|artwork|renders?|mockups?|"
                         r"posters?|wallpapers?)\b", re.I)
_ABOUT_MEDIA = re.compile(r"\b(scripts?|captions?|descriptions?|titles?|ideas?|prompts?|transcri\w*|"
                          r"subtitles?|storyboards?|outlines?|hashtags?|blurbs?|posts?)\b", re.I)


def kind_mismatch(request: str, mission_text: str) -> str:
    """The person asked for a video or pictures, but the plan only writes text about them.
    Returns what to tell the planner ('' = fine). Requests for writing ABOUT videos or
    pictures (scripts, captions, ideas...) are left alone, and so are tool tasks."""
    types = set(re.findall(r"TYPE:\s*([\w-]+)", mission_text, re.I))
    types = {t.lower() for t in types}
    if _ABOUT_MEDIA.search(request):
        return ""
    if _WANTS_VIDEO.search(request) and not types & {"video", "animate-photo"}:
        return ("the person asked for a video, but your mission has no TYPE: video task (it only "
                "writes text). Make it a TYPE: video task: CHUNKS: 1 x clips (1 unless they asked "
                "for more), FORMAT: what happens in the clip")
    if _WANTS_PICS.search(request) and not _WANTS_VIDEO.search(request) and not types & {
            "image", "remove-bg", "edit-picture", "restore-photo", "photo-batch", "photo-listing",
            "sort-photos", "read-scans"}:
        return ("the person asked for pictures, but your mission has no TYPE: image task (it only "
                "writes text). Make it a TYPE: image task: CHUNKS: parts x pictures, FORMAT: subject and style")
    return ""


def wants_high(request: str) -> bool:
    return bool(re.search(r"\b(high|best|top|max(imum)?)[ -]?(quality|detail)\b|\bhigh[ -]?res", request, re.I))


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
                lang = next((o.split(" ", 1)[1] for o in (j.get("options") or [])
                             if o.startswith("language ")), "english")
                from .tools import language_name
                spoken = ("" if lang == "english" else
                          " (finding the language)" if lang == "auto" else f" ({language_name(lang)})")
                out.append(f"Transcribe {_n(n, 'recording', 'recordings')}{spoken}{tail}: {name}")
            elif t == "read-aloud":
                ch = " (one track per chapter)" if "chapters" in (j.get("options") or []) else ""
                out.append(f"Read {_n(n, 'document', 'documents')} aloud as MP3{ch}: {name}")
            elif t == "photo-batch":
                from .tools import TOOLS as _T
                vals = {o.key: o.value for o in _T[t].options if o.choices}
                for o in j.get("options") or []:
                    k, _, v = o.partition(" ")
                    if v:
                        vals[k] = v
                bits = ["same size" if vals["size"] == "keep" else f"{vals['size']} px"]
                if vals["format"] != "same":
                    bits.append(vals["format"].upper())
                if "rename" in (j.get("options") or []):
                    bits.append("renamed in order")
                if j.get("watermark"):
                    bits.append("watermark " + vals["corner"].replace("-", " "))
                out.append(f"Resize {_n(n, 'photo', 'photos')} ({', '.join(bits)}): {name}")
            elif t == "translate":
                from .tools import language_name
                langs = [o.split(" ", 1)[1] for o in (j.get("options") or []) if o.startswith("to ")]
                names = [language_name(x) for x in langs]
                into = " and ".join(names) if len(names) < 3 else ", ".join(names[:-1]) + " and " + names[-1]
                out.append(f"Translate {_n(n, 'document', 'documents')} into {into}: {name}")
            elif t == "tidy-sheet":
                from .tools import TOOLS as _T
                opts = j.get("options") or [o.key for o in _T[t].options if o.default]
                words = {"spaces": "spaces", "dupes": "duplicates", "spelling": "spelling",
                         "categorize": "categories", "split": "split a column"}
                did = [words[o] for o in words if o in opts]
                tail = (" (" + ", ".join(did) + ")") if did else ""
                out.append(f"Tidy {_n(n, 'spreadsheet', 'spreadsheets')}{tail}: {name}")
            elif t == "photo-listing":
                out.append(f"Listings from {_n(n, 'photo', 'photos')}: {name}")
            elif t == "read-scans":
                how = next((o.split(" ", 1)[1] for o in (j.get("options") or []) if o.startswith("as ")), "text")
                what = {"text": "the text", "receipts": "receipts into a spreadsheet",
                        "table": "tables into spreadsheets"}[how]
                out.append(f"Read {what} from {_n(n, 'picture', 'pictures')}: {name}")
            elif t in ("remove-bg", "edit-picture", "restore-photo", "animate-photo", "music"):
                o = j.get("options") or []
                pick = lambda k, d: next((x.split(" ", 1)[1] for x in o if x.startswith(k + " ")), d)  # noqa: E731
                if t == "remove-bg":
                    up = pick("upscale", "none")
                    bg = "on white" if pick("background", "transparent") == "white" else "see-through"
                    out.append(f"Remove the background from {_n(n, 'picture', 'pictures')} ({bg}"
                               + (f", {up} bigger" if up != "none" else "") + f"): {name}")
                elif t == "edit-picture":
                    out.append(f"Edit {_n(n, 'picture', 'pictures')} as asked: {name}")
                elif t == "restore-photo":
                    out.append(f"Restore {_n(n, 'old photo', 'old photos')}"
                               + (" and add color" if "colorize" in o else "") + f": {name}")
                elif t == "animate-photo":
                    out.append(f"Turn {_n(n, 'photo', 'photos')} into 5-second clips: {name}")
                else:
                    from .picturetools import pieces_from
                    k = len(pieces_from(j.get("format", "")))
                    what = ("sound effect", "sound effects") if pick("kind", "music") == "sfx" else ("music track", "music tracks")
                    out.append(f"Make {_n(k, *what)} ({pick('length', '30')} s each): {name}")
            elif t == "sort-photos":
                tail = " into folders" if not j.get("options") or "folders" in j["options"] else ""
                out.append(f"Sort and tag {_n(n, 'photo', 'photos')}{tail}: {name}")
            elif t == "ask-files":
                from .tools import questions_from
                q = len(questions_from(j.get("format", "")))
                bits = [_n(q, "question", "questions")] if q else []
                if not q or "summaries" in (j.get("options") or []):
                    bits.append("summaries")
                out.append(f"Read {_n(n, 'document', 'documents')} for " + " and ".join(bits) + f": {name}")
            elif t == "proofread":
                opts = j.get("options") or ["copy"]
                tail = " and a corrected copy" if "copy" in opts else ""
                tail += ", with wording suggestions" if "clarity" in opts else ""
                out.append(f"Proofread {_n(n, 'document', 'documents')} with a list of every change"
                           f"{tail}: {name}")
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
    files_note = ("\n\nFiles waiting in Joe's Inbox (use these exact names in INPUT):\n"
                  + "\n".join("- " + f for f in waiting)) if waiting else \
                 "\n\nNo files are waiting in Joe's Inbox right now."
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
                mismatch = kind_mismatch(request, block) if chk["ok"] else ""
                if mismatch and attempt == 0:
                    chk = {"ok": False, "error": mismatch}
                if chk["ok"]:
                    warns = list(chk.get("warnings", []))
                    if mismatch:
                        warns.append("Joe planned only writing, though you mentioned a video or "
                                     "pictures. If you wanted those, try 'make a video of ...' or use "
                                     "Step by step (F6).")
                    if wants_high(request) and re.search(r"TYPE:\s*(video|image)", block, re.I):
                        warns.append("For high quality, set Setup (F10) > Images & video > Quality to "
                                     "High first (slower, finer).")
                    chk["warnings"] = warns
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
            "Try saying it another way, or use Step by step (F6)."}
