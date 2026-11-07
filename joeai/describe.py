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
- Video clips: TYPE: video, CHUNKS: 1 x clips (keep it to 1-4 clips), FORMAT: what happens. Add EXPORT: gif
  when they want a GIF.
- Finished copies (EXPORT: docx/pdf/epub, or xlsx for a .csv) can take TEMPLATE: book (printed
  novel) | manuscript (for an editor/agent) | kids (children's picture book) | ebook | report |
  largeprint | poetry | screenplay | letter (incl. cover letter) | resume | cookbook | recipecard |
  coloring (coloring/activity book) | school (MLA paper) | standard; for a .csv: sheet | pricelist.
  Only add it when the request names that kind of project. A screenplay's FORMAT says: scene headings
  (INT./EXT.), character names in capitals on their own line, dialogue under them.
- Social media posts (a list of posts): add EXPORT: social so Joe also makes files a post
  scheduler or spreadsheet can take (Joe never posts by himself).
- When they ask to research, look things up, or want current facts, add RESEARCH: yes to that
  writing task (Joe searches online first and lists the sources).
- Tasks can't see each other. When a spreadsheet or pictures must use the names from a list
  task above (a price list for the products just described), add FROM: <that task's name>
  and the same number of items.
{tools}

Rules:
- "a picture" / "an image" / "a drawing" (one, no number) = CHUNKS: 1 x 1 with VARIANTS: 4, so
  they get 4 versions of that one picture to pick from.
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
    if _WANTS_VIDEO.search(request) and not types & {"video", "animate-photo", "restyle-video"}:
        return ("the person asked for a video, but your mission has no TYPE: video task (it only "
                "writes text). Make it a TYPE: video task: CHUNKS: 1 x clips (1 unless they asked "
                "for more), FORMAT: what happens in the clip")
    if _WANTS_PICS.search(request) and not _WANTS_VIDEO.search(request) and not types & {
            "image", "remove-bg", "edit-picture", "restore-photo", "photo-batch", "photo-listing",
            "fix-spot", "merge-pictures", "relight", "restyle", "redraw", "make-bigger", "character-scenes",
            "character-spin", "sketch-to-picture", "illusion-art", "make-3d",
            "sort-photos", "read-scans"}:
        return ("the person asked for pictures, but your mission has no TYPE: image task (it only "
                "writes text). Make it a TYPE: image task: CHUNKS: parts x pictures, FORMAT: subject and style")
    return ""


_ONE_PIC = re.compile(r"\b(a|an|one|single)\s+(\w+\s+){0,4}?(picture|image|drawing|illustration|painting|"
                      r"photo|render|artwork|wallpaper|poster|logo)\b", re.I)


def one_picture(request: str, block: str) -> str:
    """'make me a super cool image of a raccoon' -> one picture, 4 versions to pick from (the
    planner sometimes makes 8 different pictures). Only when the person gave no number."""
    if not _ONE_PIC.search(request) or re.search(r"\d|\b(two|three|four|five|six|eight|ten|dozen|"
                                                 r"several|some|few|many|pictures|images|drawings)\b", request, re.I):
        return block
    tasks = re.split(r"(?m)^(?=TASK:)", block)
    if sum(1 for t in tasks if re.search(r"(?m)^TYPE:\s*image\b", t)) != 1:
        return block
    out = []
    for t in tasks:
        if re.search(r"(?m)^TYPE:\s*image\b", t) and not re.search(r"(?m)^PART:", t):
            t = re.sub(r"(?m)^CHUNKS:.*$", "CHUNKS: 1 x 1", t)
            if not re.search(r"(?m)^CHUNKS:", t):
                t = re.sub(r"(?m)^(TYPE:\s*image.*)$", r"\1\nCHUNKS: 1 x 1", t, count=1)
            t = re.sub(r"(?m)^VARIANTS:.*\n?", "", t)
            t = re.sub(r"(?m)^(CHUNKS: 1 x 1)$", r"\1\nVARIANTS: 4", t, count=1)
        out.append(t)
    return "".join(out)


_FAST = re.compile(r"\b(quick(ly)?|fast|asap|rough|draft|in a hurry|right away|low[ -]?quality|"
                   r"doesn'?t (need|have) to be (perfect|great))\b", re.I)
_KIND_NAMES = {"writing": "Writing", "pictures": "Pictures", "video": "Video"}


def quality_offer(settings, request: str, block: str) -> dict | None:
    """The person asked for high quality (or for speed) but Setup says otherwise: offer to
    change it, in plain words, with one button. Nothing changes unless they press it."""
    from . import quality
    kinds = []
    for t in re.split(r"(?m)^(?=TASK:)", block)[1:]:
        m = re.search(r"(?m)^TYPE:\s*([\w-]+)", t)
        typ = (m.group(1).lower() if m else "text")
        if typ in ("image", "edit-picture", "remove-bg", "restore-photo", "fix-spot", "merge-pictures",
                   "relight", "restyle", "redraw", "make-bigger", "character-scenes", "character-spin",
                   "sketch-to-picture", "illusion-art", "make-3d"):
            kinds.append("pictures")
        elif typ in ("video", "animate-photo", "restyle-video"):
            kinds.append("video")
        elif typ in ("text", "code"):
            kinds.append("writing")
    kinds = list(dict.fromkeys(kinds))
    if wants_high(request) or re.search(r"\b(best|amazing|stunning|super ?cool|highest|top[- ]notch|"
                                        r"professional|detailed)\b", request, re.I):
        want = "high"
    elif _FAST.search(request):
        want = "low"
    else:
        return None
    off = [k for k in kinds if quality.level(settings, k) != want]
    if want == "high":                          # only the kinds the request is really about
        media = [k for k in off if k != "writing"]
        off = media or off
    if not off:
        return None
    now = ", ".join(f"{_KIND_NAMES[k]} is set to {quality.level(settings, k).capitalize()}" for k in off)
    if want == "high":
        text = f"You asked for high quality, but {now}. Use High for this? It's slower but finer."
        button = "USE HIGH QUALITY"
    else:
        text = f"You asked for it quick, but {now}. Use Low for this? It's much faster but rougher."
        button = "USE LOW (FASTER)"
    return {"level": want, "kinds": off, "text": text, "button": button}


def want_gif(request: str, block: str) -> str:
    """'a gif of ...' -> the video task also makes a GIF (EXPORT: gif)."""
    if not re.search(r"\bgifs?\b", request or "", re.I) or re.search(r"(?m)^EXPORT:.*gif", block, re.I):
        return block
    return re.sub(r"(?m)^(TYPE:\s*video\b.*)$", r"\1\nEXPORT: gif", block, count=1)


SOCIAL_WORDS = re.compile(r"\b(social[ -]?media|facebook|instagram|tiktok|twitter|linkedin|bluesky|threads|mastodon|"
                          r"postiz|mixpost)\b", re.I)


def want_social(request: str, block: str) -> str:
    """'facebook posts for my shop' -> that list task also makes scheduler files (EXPORT: social)."""
    if not SOCIAL_WORDS.search(request or "") or not re.search(r"\bposts?\b|\bcaptions?\b", request or "", re.I) \
            or re.search(r"(?mi)^EXPORT:.*\bsocial\b", block):
        return block
    parts = re.split(r"(?m)^(?=TASK:)", block)
    for i, part in enumerate(parts):
        if not part.startswith("TASK:") or re.search(r"(?mi)^TYPE:\s*(?!text\b|list\b)\S", part):
            continue
        if not re.search(r"\bposts?\b|\bcaptions?\b|social", part, re.I):
            continue
        if re.search(r"(?mi)^EXPORT:", part):
            parts[i] = re.sub(r"(?mi)^(EXPORT:.*?)\s*$", r"\1, social", part, count=1)
        else:
            parts[i] = re.sub(r"(?m)^(TASK:.*)$", r"\1\nEXPORT: social", part, count=1)
        return "".join(parts)
    return block


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
    out = _plain_summary(chk)
    for i, j in enumerate(chk.get("jobs", [])):
        if j.get("source") and len(out) == len(chk.get("jobs", [])):
            out[i] += f" (same names as {j['source']})"
    return out


def _plain_summary(chk: dict) -> list[str]:
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
            elif t in ("fix-spot", "merge-pictures", "relight", "restyle", "redraw", "make-bigger",
                       "character-scenes", "character-spin"):
                o = j.get("options") or []
                pick = lambda k, d: next((x.split(" ", 1)[1] for x in o if x.startswith(k + " ")), d)  # noqa: E731
                from .picturetools import SPIN_VIEWS
                from .tools import RELIGHTS, RESTYLES
                scenes = [x for x in re.split(r"[\n;]+", j.get("format", "")) if x.strip()]
                line = {
                    "fix-spot": f"Fix the marked spot in {_n(n, 'picture', 'pictures')}",
                    "merge-pictures": f"Put {_n(n, 'picture', 'pictures')} together into one",
                    "relight": f"Relight {_n(n, 'picture', 'pictures')} ({RELIGHTS.get(pick('light', 'golden'), ('',))[0].lower()})",
                    "restyle": f"Redraw {_n(n, 'picture', 'pictures')} as "
                               + RESTYLES.get(pick('style', 'watercolor'), ('watercolor',))[0].lower(),
                    "redraw": f"Redraw {_n(n, 'picture', 'pictures')} (change {pick('change', 'some')})",
                    "make-bigger": f"Make {_n(n, 'picture', 'pictures')} {pick('shape', 'wider')}",
                    "character-scenes": f"The same character in {_n(len(scenes), 'scene', 'scenes')}",
                    "character-spin": f"{len(SPIN_VIEWS)} views of the character + a sheet",
                }[t]
                out.append(f"{line}: {name}")
            elif t in ("sketch-to-picture", "illusion-art", "make-3d", "restyle-video"):
                o = j.get("options") or []
                pick = lambda k, d: next((x.split(" ", 1)[1] for x in o if x.startswith(k + " ")), d)  # noqa: E731
                from .makers import LOOKS, PATTERNS
                from .tools import RESTYLES
                look = LOOKS.get(pick("look", "auto"), ("",))[0].lower()
                line = {
                    "sketch-to-picture": f"Finish {_n(n, 'drawing', 'drawings')} into pictures"
                                         + (f" ({look})" if pick("look", "auto") != "auto" else ""),
                    "illusion-art": f"{pick('versions', '2')} hidden-picture illusion(s): "
                                    + PATTERNS.get(pick("hidden", "spiral"), ("spiral",))[0].split(" (")[0].lower(),
                    "make-3d": f"Turn {_n(n, 'picture', 'pictures')} into 3D models (.glb)",
                    "restyle-video": f"Restyle {_n(n, 'file', 'files')} as "
                                     + (RESTYLES.get(pick("style", "anime"), ("your look",))[0].lower()
                                        if pick("style", "anime") != "own" else "your look")
                                     + f" (first {pick('length', '5')} s)",
                }[t]
                out.append(f"{line}: {name}")
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


# ---- "do that again": re-plan an earlier task exactly, no AI guessing --------------------------
# People say "rerun the black and white videos" or "run it again". The planner AI can't know
# what ran before, so it guessed (a rerun of style videos was planned as animate-photo). Joe
# looks in his own records instead: runs saved with each chat, and mission files in Queue/done.
_AGAIN = re.compile(r"\b(re-?run|re-?do|re-?make|again|one more time|same (?:\w+ )?as (?:before|last time))\b", re.I)
_AGAIN_WORDS = re.compile(r"\b(re-?run|re-?do|re-?make|again|one more time|same|as|before|last|time|run|do|make|"
                          r"please|joe|the|those|these|that|this|it|them|my|a|an|of|for|ones?|all|"
                          r"can|you|could|would|just|now|and|with|from|test|tests)\b", re.I)


def wants_again(request: str) -> bool:
    return bool(_AGAIN.search(request or ""))


def _stem(w: str) -> str:
    w = w.lower()
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


_ALIASES = {"bw": "black white", "b&w": "black white", "monochrome": "black white",
            "pics": "picture", "pictures": "picture", "images": "picture", "image": "picture",
            "clip": "video", "clips": "video", "vid": "video", "vids": "video"}


def _words(text: str) -> set[str]:
    t = (text or "").lower()
    for a, b in _ALIASES.items():
        t = re.sub(rf"(?<![\w&]){re.escape(a)}(?![\w&])", b, t)
    return {_stem(w) for w in re.findall(r"[a-z0-9]+", t) if len(w) > 1}


def split_tasks(mission: str) -> tuple[str, list[str]]:
    """Mission text -> (lines before the first TASK, [each TASK block])."""
    head, blocks = [], []
    for ln in (mission or "").splitlines():
        if ln.strip().startswith("==="):
            continue
        if re.match(r"\s*TASK\s*:", ln, re.I):
            blocks.append(ln)
        elif blocks:
            blocks[-1] += "\n" + ln
        else:
            head.append(ln)
    return "\n".join(l for l in head if l.strip()), [b.strip() for b in blocks]


def past_missions(app) -> list[tuple[str, str]]:
    """(when, mission text) newest first: runs saved with chats, then Queue/done files."""
    found: list[tuple[str, str]] = []
    try:
        for c in app.chats.list():
            d = app.chats.get(c.get("id", "")) or {}
            for m in d.get("messages", []):
                if m.get("kind") == "run" and m.get("mission"):
                    found.append((str(m.get("ts", "")), m["mission"]))
    except Exception:          # noqa: BLE001 (records are a convenience, never a failure)
        pass
    try:
        done = app.sb.missions / "Queue" / "done"
        for f in done.glob("*.txt") if done.is_dir() else []:
            if f.name.endswith(".problem.txt"):
                continue
            from datetime import datetime
            found.append((datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds"),
                          f.read_text(encoding="utf-8-sig", errors="replace")))
    except OSError:
        pass
    found.sort(key=lambda x: x[0], reverse=True)
    return found


def _again_block(block: str) -> str:
    """Same task, new name and folder, so the earlier results stay next to the new ones."""
    lines = block.splitlines()
    first = lines[0]
    m = re.search(r"\bSAVE:\s*(\S+)", first)
    if m:
        save = m.group(1)
        base, dot, ext = save.rpartition(".") if "." in save.rsplit("/", 1)[-1] else (save, "", "")
        new = f"{base}-again.{ext}" if dot else f"{save}-again"
        first = first[: m.start(1)] + new + first[m.end(1):]
    first = re.sub(r"^(\s*TASK\s*:\s*)(.+?)(\s{2,}[A-Z ]+:|$)", lambda k: k.group(1) + k.group(2).rstrip()
                   + " (again)" + k.group(3), first, count=1)
    return "\n".join([first] + lines[1:])


def rerun_plan(app, request: str) -> dict | None:
    """A "do it again" request -> the earlier task(s) as a plan, or None when it isn't one."""
    if not wants_again(request):
        return None
    want = _words(_AGAIN_WORDS.sub(" ", request))
    for when, mission in past_missions(app):
        head, blocks = split_tasks(mission)
        if not blocks:
            continue
        if want:
            picked = [b for b in blocks if want <= _words(b)]
            if not picked:
                continue
        else:                                  # "run it again": the whole last mission
            picked = blocks
        text = "\n".join(x for x in [head] + [_again_block(b) for b in picked] if x)
        names = [re.sub(r"^\s*TASK\s*:\s*", "", b.splitlines()[0]).split("  ")[0] for b in picked]
        try:
            parse(text)
            chk = app.check(text)
        except MissionError as e:
            chk = {"ok": False, "error": str(e)}
        if not chk.get("ok"):                  # found it, but it can't run as it is right now
            return {"ok": False, "error": f"I found {', '.join(names)} from before, but it can't run "
                    f"right now: {chk.get('error', 'unknown problem')}"}
        warns = [f"Same as before ({when[:16].replace('T', ' ')}): " + ", ".join(names)
                 + ". Saved next to the earlier results with '-again' on the folder name."]
        return {"ok": True, "mission": text, "summary": plain_summary(chk),
                "time": plain_time(chk["eta_min"]) + ("" if chk.get("eta_learned") else ROUGH),
                "eta_min": chk["eta_min"], "warnings": warns + list(chk.get("warnings", []))}
    what = " ".join(sorted(want)) or "the last run"
    return {"ok": False, "error": f"I couldn't find an earlier task matching \"{what}\". "
            "Say what to make in your own words, or pick it from a past chat (Talk > PAST CHATS)."}


def draft(app, request: str) -> dict:
    """Plain request -> {"ok", "mission", "summary", "time", "eta_min", "warnings"}."""
    request = (request or "").strip()
    if len(request) < 4:
        return {"ok": False, "error": "Tell Joe what you need first, in your own words."}
    request = request[:4000]
    again = rerun_plan(app, request)          # "rerun the bw videos": no AI guessing needed
    if again is not None:
        return again
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
        block = want_social(request, want_gif(request, one_picture(request, extract_block(r.text))))
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
                    chk["warnings"] = warns
                if chk["ok"]:
                    out = {"ok": True, "mission": block, "summary": plain_summary(chk),
                           "time": plain_time(chk["eta_min"]) + ("" if chk.get("eta_learned") else ROUGH),
                           "eta_min": chk["eta_min"],
                           "warnings": chk.get("warnings", [])}
                    offer = quality_offer(app.settings, request, block)
                    if offer:
                        out["quality_offer"] = offer
                    return out
                problem = chk["error"]
            except MissionError as e:
                problem = str(e)
        msgs += [{"role": "assistant", "content": r.text},
                 {"role": "user", "content": f"That didn't work: {problem}. Reply with the corrected "
                                             "mission block only."}]
    return {"ok": False, "error": "Joe couldn't turn that into a plan (" + problem + "). "
            "Try saying it another way, or use Step by step (F6)."}
