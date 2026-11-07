"""ASK A BIGGER AI: one paste-ready message for any chatbot (ChatGPT, Claude, Gemini...).

Joe builds the message (what Joe is, the exact mission format, the person's request, and, if
they want, the last report and the problems from the log). The person pastes it into the
chatbot of their choice and pastes the answer back; Joe reads the mission block straight out
of it and checks it like any other plan. Free, works with any AI, no keys, nothing is sent by
Joe himself: the person sees every word before it leaves.
"""
from __future__ import annotations

import re

from . import __version__

INTRO = """Hi! I use Joe, a free open-source app that does work overnight on my own PC with local AI
models (Ollama for writing, ComfyUI for pictures and video). Joe's own model is small, so I'm
asking you to write the plan ("mission") for him. Please reply with ONE mission block in the
exact format below, between the === JOE MISSION === and === END === lines. I'll paste your
whole answer back into Joe; he reads the block and ignores everything else.

My PC: {pc}"""

def extra_keys() -> str:
    from .styles import NAMES
    return f"""Extra keys Joe understands (use them only when needed):
- SAVE: a file name, only for spreadsheets (must end in .csv)
- TYPE: text (default) | code | image | video | or a tool name from the list above
- STYLE: one of: {", ".join(NAMES)} (bw = black and white; character = mascots and characters)
- SIZE: 1344 x 768 (pictures)   VARIANTS: 1-4 (pictures per prompt)
- PROMPTS: as written (use each PART line as the exact picture prompt)
- NEGATIVE: things to leave out of pictures, comma separated
- INPUT: file names from Joe's Inbox (for tools)   OPTIONS: tool options, comma separated
- TEMPLATE: book | manuscript | kids | ebook | report | largeprint | poetry | screenplay | letter | resume |
  cookbook | recipecard | coloring | school | standard (how the EXPORT copies look); sheet | pricelist (.xlsx)
- EXPORT: docx | pdf | epub | odt | html (a finished copy of a document); xlsx (a .csv task's Excel copy); social (posts for a scheduler:
  csv/json/Postiz lines; also works on a .csv task); gif on a video task
- FROM: the name of an earlier list or spreadsheet task. Each task is written on its own and
  can't see the others, so when one task must use the same names as another (a price list
  for the products just described, one picture per product), add FROM: <that task's name>.
  Joe then hands over the finished items in order. Use the same item count in both tasks.
- RESEARCH: yes (Joe looks the task up online first and lists sources; only when I want
  current facts or research)
- MODEL: flux2 on an image task whose pictures need readable words or lettering (Joe uses
  FLUX.2 klein when it's installed); otherwise an exact installed model name, only if I ask"""


HOW_TO_ANSWER = """How to write the answer (Joe reads it word for word):
- Put the whole block in one plain-text code block.
- Every key in CAPITALS at the start of its own line, then a colon. No bold, no bullets, no
  numbering, no extra keys that aren't listed here.
- Match my numbers exactly. Lists and spreadsheets: 4-10 items per part (30 = CHUNKS: 5 x 6).
- Facts you can't know (prices, sizes, times, measurements) are written as [CHECK].
- Example of a correct block:
=== JOE MISSION ===
RULES: Friendly tone. Unknown facts are [CHECK].
TASK: Soap descriptions
CHUNKS: 2 x 6
FORMAT: Soap name, then one short friendly description (under 40 words). Every name is different.
TASK: Soap price list
FROM: Soap descriptions
CHUNKS: 2 x 6
HEADER: Name,Scent,Price
SAVE: soap-prices.csv
FORMAT: One row per soap. Price is [CHECK].
TASK: Soap pictures
TYPE: image
FROM: Soap descriptions
CHUNKS: 3 x 4
STYLE: watercolor
FORMAT: One bar of each soap on a wooden dish, soft light, no text or logos.
=== END ==="""

_NOT_WRITING = re.compile(r"embed|nomic|bge|minilm|rerank|vl\b|vl:|vision|llava|moondream|clip|whisper", re.I)
_FILE_TALK = re.compile(r"\b(inbox|attached|my (own )?(photos?|pictures?|files?|documents?|docs?|recordings?|"
                        r"audio|receipts?|scans?|spreadsheets?|sheets?|videos?|notes?|letters?)|transcrib\w*|"
                        r"translat\w*|proofread\w*|restore|resiz\w*|remove (the )?backgrounds?|these (photos|"
                        r"pictures|files)|this (photo|picture|file|recording|document)|\.(jpe?g|png|pdf|docx?|"
                        r"csv|xlsx|mp3|wav|m4a|md|txt)\b)", re.I)


_PROBLEM = re.compile(r"(fail|error|couldn't|could not|not queued|timed out|stopped|skipped|problem)", re.I)


def _pc_line(app) -> str:
    bits = []
    try:
        from . import hardware
        g = hardware.gpu()
        if g:
            mb = g.get("vram_total_mb") or 0
            bits.append(f"{g.get('name', 'graphics card')}" + (f", {round(mb / 1024)} GB" if mb else "")
                        + (" (shares main memory)" if g.get("unified") else ""))
        else:
            bits.append("no graphics card found (CPU only)")
    except Exception:                       # noqa: BLE001 (the message works without it)
        pass
    try:
        from .doctor import ollama_models
        names = [m["name"] for m in ollama_models(app.services) if not _NOT_WRITING.search(m["name"])][:12]
        if names:
            bits.append("writing models: " + ", ".join(names))
    except Exception:                       # noqa: BLE001
        pass
    q = getattr(app.settings, "quality", None)
    if q:
        bits.append(f"quality: writing {q.writing}, pictures {q.pictures}, video {q.video}")
    return "; ".join(bits) or "unknown"


def _scrub(text: str) -> str:
    from .support import _scrub_text
    return _scrub_text(text)


def recent_problems(app, lines: int = 400, keep: int = 25) -> list[str]:
    """Lines from the end of Joe's log that look like something went wrong."""
    p = app.sb.output / "_log.txt"
    try:
        tail = p.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
    except OSError:
        return []
    return [ln for ln in tail if _PROBLEM.search(ln)][-keep:]


def format_text() -> str:
    """Joe's planner format, with the SAVE rule worded for a bigger AI."""
    from .describe import planner_text
    fmt = planner_text().split("Mission block format", 1)
    text = ("Mission block format" + fmt[1]) if len(fmt) == 2 else planner_text()
    return text.replace("- Do NOT write SAVE lines except for spreadsheets; Joe picks the file names.",
                        "- Joe picks the file names: write SAVE only for spreadsheets.").strip()


def message(app, request: str = "", with_report: bool = True, mission: str = "") -> str:
    """The whole paste-ready message. Paths and the user name are hidden."""
    from .tools import inbox_media
    fmt_text = format_text()
    parts = [INTRO.format(pc=_pc_line(app)), "--- THE MISSION FORMAT ---", fmt_text, extra_keys(), HOW_TO_ANSWER]
    try:                                    # templates the person made (Setup > Writing > Templates)
        from . import doctemplates
        mine = [r for r in doctemplates.entries(app.settings)["rows"] if r.get("custom")]
    except Exception:                       # noqa: BLE001
        mine = []
    if mine:
        parts.insert(3, "My own TEMPLATE names (use them when they fit): "
                     + "; ".join(f"{r['id']} ({r['label']}, for {'.csv' if r['for'] == 'sheet' else 'documents'})"
                                 for r in mine[:20]))
    request = (request or "").strip()
    try:
        waiting = inbox_media(app.sb)
    except Exception:                       # noqa: BLE001
        waiting = []
    if waiting and (_FILE_TALK.search(request) or _FILE_TALK.search(mission or "")):
        parts.append("Files waiting in Joe's Inbox (use these exact names in INPUT):\n"
                     + "\n".join("- " + f for f in waiting[:60]))
    elif waiting:
        parts.append(f"({len(waiting)} of my files are waiting in Joe's Inbox, but this request doesn't use them.)")
    parts.append("--- WHAT I WANT ---\n" + (request or "(I'll describe it here.)"))
    if mission.strip():
        parts.append("--- JOE'S CURRENT PLAN (fix or improve it) ---\n" + mission.strip()[:8000])
    if with_report:
        try:
            rep = (app.sb.output / "_REPORT.md").read_text(encoding="utf-8")[:6000].strip()
        except OSError:
            rep = ""
        # A clean last run (everything finished) has nothing to fix: leave it and the old log lines out,
        # so a new request isn't padded with unrelated task names or a "change the plan" nudge.
        if not mission.strip() and "- Nothing. All tasks finished." in rep:
            rep, probs = "", []
        else:
            probs = recent_problems(app)
        if rep:
            parts.append("--- JOE'S LAST REPORT ---\n" + rep)
        if probs:
            parts.append("--- PROBLEMS IN JOE'S LOG (newest last) ---\n" + "\n".join(probs))
        if rep or probs:
            parts.append("If something above failed, change the plan so it works (smaller parts, "
                         "a different style or tool), and say in one line before the block what you changed.")
    parts.append(f"(Message made by Joe {__version__}.)")
    return _scrub("\n\n".join(parts))


def unflatten(block: str) -> str:
    """Chat windows often lose line breaks when an answer is copied ('TASK: x CHUNKS: 5 x 6
    FORMAT: ...' on one line). Put each UPPERCASE key back at the start of its own line."""
    from .mission import KEYS
    keys = "|".join(re.escape(k) for k in sorted(KEYS, key=len, reverse=True))
    block = re.sub(r"(===\s*JOE\s+MISSION\s*===)[ \t]*", r"\1\n", block, flags=re.I)
    block = re.sub(r"[ \t]*(===\s*END\s*===)", r"\n\1", block, flags=re.I)
    return re.sub(rf"(?<=\S)[ \t]+(?=(?:{keys})[ \t]*:)", "\n", block)


_TYPES = {"images": "image", "picture": "image", "pictures": "image", "img": "image", "art": "image",
          "illustration": "image", "photo": "image", "videos": "video", "clip": "video", "clips": "video",
          "list": "text", "document": "text", "doc": "text", "writing": "text", "write": "text",
          "spreadsheet": "text", "csv": "text", "sheet": "text", "table": "text"}
_STYLE_SAY = {"black and white": "bw", "black & white": "bw", "b&w": "bw", "monochrome": "bw",
              "3d": "render3d", "3d render": "render3d", "sci-fi": "scifi", "photographic": "photo",
              "photorealistic": "photo", "realistic": "photo", "oil painting": "painting",
              "watercolour": "watercolor", "coloring page": "coloring", "coloring book": "coloring",
              "colouring": "coloring", "mascot": "character", "pixel art": "pixel", "comic book": "comic"}


def _split_chunks(total: int) -> tuple[int, int] | None:
    """30 -> (5, 6): parts of 4-10 items that add up exactly; None when no even split exists."""
    for size in (8, 6, 10, 5, 7, 9, 4):
        if total % size == 0:
            return total // size, size
    return None


def tidy(raw: str) -> tuple[str, list[str]]:
    """Make any chatbot's answer fit Joe's format, and say what was changed. Each AI writes the
    block a little differently (bold keys, bullets, lowercase keys, lost line breaks, a 1 x 30
    list, a style name Joe doesn't know); none of that should stop a beginner."""
    from .mission import KEYS
    from .describe import extract_block
    from . import styles as styles_mod
    notes: list[str] = []
    text = (raw or "").replace("\r\n", "\n")
    text = re.sub(r"={2,}\s*(JOE\s+MISSION|END)\s*={2,}", lambda m: f"=== {m.group(1).upper()} ===", text, flags=re.I)
    keys = "|".join(re.escape(k) for k in sorted(KEYS, key=len, reverse=True))
    # "**TASK:**", "- TASK:", "1. TASK:", "Task:" at a line start -> "TASK:"
    # Only when the AI wrote no capital TASK: at all are "Task:" lines read as keys, so a
    # sentence like "Size: small or large" inside a FORMAT stays text.
    any_case = not re.search(r"(?m)^[ \t]*(?:[-*\u2022]|\d+[.)])?[ \t]*\**[ \t]*TASK[ \t]*\**[ \t]*:", text)
    fixed = re.sub(rf"(?m{'i' if any_case else ''})^[ \t]*(?:[-*\u2022]|\d+[.)])?[ \t]*\**[ \t]*({keys})[ \t]*\**[ \t]*:[ \t]*\**[ \t]*",
                   lambda m: m.group(1).upper() + ": ", text)
    if fixed != text:
        notes.append("put the plan's keys back in Joe's plain style (capitals, no bold or bullets)")
    text = fixed
    if len(re.findall(r"===\s*JOE\s+MISSION\s*===", text, re.I)) > 1:
        notes.append("the answer had more than one plan; Joe used the first")
    block = extract_block(text)
    if not block:
        return "", notes
    if not re.search(r"===\s*END\s*===", text, re.I):
        # no END line: stop at the first blank line followed by ordinary chat ("Let me know...")
        lines, keep, blank = block.splitlines(), [], False
        for ln in lines:
            if blank and ln.strip() and not re.match(rf"\s*({keys})\s*:|\s*===", ln):
                break
            blank = not ln.strip()
            keep.append(ln)
        while keep and (not keep[-1].strip() or re.match(r"\s*===\s*END", keep[-1], re.I)):
            keep.pop()
        while keep and re.match(r"\s*(let me know|hope (this|that)|feel free|happy to|enjoy|good luck|if you('d| want| need)|"
                                r"want me to|would you like|here'?s|i can also|note:|this plan)", keep[-1], re.I):
            keep.pop()
        block = "\n".join(keep).rstrip()
        if not block.endswith("=== END ==="):
            block += "\n=== END ==="
    flat = unflatten(block)
    if any(len(re.findall(rf"(?:^|\s)(?:{keys})[ \t]*:", ln)) > 1 for ln in block.splitlines()):
        notes.append("put back line breaks that were lost when the answer was copied")
    block = flat

    def fix_line(m):
        key, val = m.group(1), m.group(2).strip()
        if key == "CHUNKS":
            nums = re.findall(r"\d+", val)
            if len(nums) == 1:
                nums = ["1", nums[0]]
            if len(nums) >= 2:
                p, n = int(nums[0]), int(nums[1])
                if n > 10 and p * n <= 500:
                    sp = _split_chunks(p * n)
                    if sp:
                        notes.append(f"split CHUNKS {p} x {n} into {sp[0]} x {sp[1]} (same total, small parts "
                                     "come out better)")
                        p, n = sp
                return f"CHUNKS: {p} x {n}"
        if key == "TYPE":
            t = val.lower().strip(" .")
            if t in _TYPES:
                notes.append(f"TYPE '{val}' read as {_TYPES[t]}")
                t = _TYPES[t]
            return f"TYPE: {t}"
        if key == "STYLE":
            t = val.lower().strip(" .")
            if t not in styles_mod.NAMES:
                guess = _STYLE_SAY.get(t) or next((sid for sid, pat in styles_mod._WORDS if re.search(pat, t)), "")
                if guess in styles_mod.NAMES:
                    notes.append(f"STYLE '{val}' read as {guess}")
                    return f"STYLE: {guess}"
                notes.append(f"left out STYLE '{val}' (Joe doesn't know it); he picks a style from the description")
                return ""
            return f"STYLE: {t}"
        if key == "SAVE":
            v = re.sub(r"^(?:\./)?(?:output/)", "", val.replace("\\", "/"), flags=re.I).strip("/ ")
            return f"SAVE: {v}"
        return m.group(0)

    block = re.sub(rf"(?m)^({keys})[ \t]*:[ \t]*(.*)$", fix_line, block)
    block = re.sub(r"\n{3,}", "\n\n", block)
    seen = []
    return block, [n for n in notes if not (n in seen or seen.append(n))]


_LINK_WORDS = re.compile(r"\b(same|matching|matches|match|each of the|for each|one (row|picture|image) per)\b", re.I)


def link_tasks(block: str, notes: list[str]) -> str:
    """An AI that writes 'one row per candle, matching the product descriptions' but no FROM:
    gets FROM: added, so the names really match (tasks can't see each other otherwise)."""
    from .mission import MissionError, parse
    try:
        jobs = parse(block).jobs
    except MissionError:
        return block
    words = lambda t: {w for w in re.findall(r"[a-z]{4,}", t.lower())} - {"task", "list", "with", "each"}  # noqa: E731
    for i, j in enumerate(jobs):
        if j.source or j.guided or j.tool or not _LINK_WORDS.search(j.format or ""):
            continue
        fmt = words(j.format)
        best = None
        for e in jobs[:i]:
            if e.media or e.guided or e.tool:
                continue
            if words(e.name) & fmt:
                best = e
        if best is None:
            continue
        new, n = re.subn(rf"(?m)^(TASK:[ \t]*{re.escape(j.name)}[ \t]*)$", rf"\1\nFROM: {best.name}", block, count=1)
        if n:
            block = new
            notes.append(f"added FROM: {best.name} to '{j.name}' so its names match")
    return block


def read_answer(app, answer: str, request: str = "") -> dict:
    """The chatbot's answer -> the same result as Joe's own planner (mission + plain summary)."""
    from . import describe as d
    block, notes = tidy(answer or "")
    if block:
        block = link_tasks(block, notes)
    if not block:
        return {"ok": False, "error": "There's no mission block in that answer. Ask the AI to reply with "
                                      "the block between === JOE MISSION === and === END ===."}
    chk = app.check(block)
    if not chk["ok"]:
        return {"ok": False, "mission": block,
                "error": f"The plan has a problem: {chk['error']} Tell the AI that, and paste its new answer."}
    warns = list(chk.get("warnings", []))
    if notes:
        warns.insert(0, "Joe tidied the AI's answer: " + "; ".join(notes) + ".")
    out = {"ok": True, "mission": block, "summary": d.plain_summary(chk),
           "time": d.plain_time(chk["eta_min"]) + ("" if chk.get("eta_learned") else d.ROUGH),
           "eta_min": chk["eta_min"], "warnings": warns}
    offer = d.quality_offer(app.settings, request, block) if request.strip() else None
    if offer:
        out["quality_offer"] = offer
    return out
