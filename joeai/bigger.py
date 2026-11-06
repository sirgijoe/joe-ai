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

EXTRA_KEYS = """Extra keys Joe understands (use them only when needed):
- SAVE: folder/or-file-name (inside Joe's Output folder; .csv required for spreadsheets)
- TYPE: write (default) | code | image | video | or a tool name from the list above
- STYLE: a picture style (photo, anime, watercolor, coloring, mascot, black and white...)
- SIZE: 1344 x 768 (pictures)   VARIANTS: 2 (pictures per prompt)
- PROMPTS: as written (use each PART line as the exact picture prompt)
- NEGATIVE: things to leave out of pictures, comma separated
- INPUT: file names from Joe's Inbox (for tools)   OPTIONS: tool options, comma separated
- EXPORT: docx | pdf | epub | odt | html (a copy of a document)
- MODEL: an exact installed model name (only if I ask for one)
Put each key at the start of a line, or two spaces after another key on the same line."""

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
        names = [m["name"] for m in ollama_models(app.services)][:12]
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


def message(app, request: str = "", with_report: bool = True, mission: str = "") -> str:
    """The whole paste-ready message. Paths and the user name are hidden."""
    from .describe import planner_text
    from .tools import inbox_media
    fmt = planner_text().split("Mission block format", 1)
    fmt_text = ("Mission block format" + fmt[1]) if len(fmt) == 2 else planner_text()
    parts = [INTRO.format(pc=_pc_line(app)), "--- THE MISSION FORMAT ---", fmt_text.strip(), EXTRA_KEYS]
    try:
        waiting = inbox_media(app.sb)
    except Exception:                       # noqa: BLE001
        waiting = []
    if waiting:
        parts.append("Files waiting in Joe's Inbox (use these exact names in INPUT):\n"
                     + "\n".join("- " + f for f in waiting[:60]))
    request = (request or "").strip()
    parts.append("--- WHAT I WANT ---\n" + (request or "(I'll describe it here.)"))
    if mission.strip():
        parts.append("--- JOE'S CURRENT PLAN (fix or improve it) ---\n" + mission.strip()[:8000])
    if with_report:
        try:
            rep = (app.sb.output / "_REPORT.md").read_text(encoding="utf-8")[:6000].strip()
        except OSError:
            rep = ""
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


def read_answer(app, answer: str) -> dict:
    """The chatbot's answer -> the same result as Joe's own planner (mission + plain summary)."""
    from . import describe as d
    block = d.extract_block(answer or "")
    if not block:
        return {"ok": False, "error": "There's no mission block in that answer. Ask the AI to reply with "
                                      "the block between === JOE MISSION === and === END ===."}
    chk = app.check(block)
    if not chk["ok"]:
        return {"ok": False, "mission": block,
                "error": f"The plan has a problem: {chk['error']} Tell the AI that, and paste its new answer."}
    return {"ok": True, "mission": block, "summary": d.plain_summary(chk),
            "time": d.plain_time(chk["eta_min"]) + ("" if chk.get("eta_learned") else d.ROUGH),
            "eta_min": chk["eta_min"], "warnings": chk.get("warnings", [])}
