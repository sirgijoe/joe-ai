"""Morning report: Output/_REPORT.md, sized to paste into Claude cheaply."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path

from .fsutil import atomic_write_text
from .mission import Mission
from .sandbox import Sandbox

MAX_FLAG_LINES = 40


def write_report(sb: Sandbox, mission: Mission, states: list, earlier: list | None = None) -> Path:
    """Write _REPORT.md. `earlier` = [(mission, states), ...] already run in this queue."""
    now = datetime.now()
    chain = list(earlier or []) + [(mission, states)]
    L = [f"# Joe report — {now:%Y-%m-%d %H:%M}", ""]
    if len(chain) > 1:
        L += [f"{len(chain)} missions ran back-to-back from the queue.", ""]
    for n, (m, st) in enumerate(chain, 1):
        if len(chain) > 1:
            L += [f"# Mission {n} of {len(chain)}", ""]
        L += _mission_lines(m, st)
    text = "\n".join(L)
    path = sb.output / "_REPORT.md"
    atomic_write_text(path, text)
    stamped = sb.meta / "reports" / f"REPORT_{now:%Y%m%d_%H%M%S}.md"
    atomic_write_text(stamped, text)
    return path


def add_left_note(sb: Sandbox, labels: list[str]) -> None:
    """Night shift "stop by": add the missions left for tomorrow night to the morning report."""
    n = len(labels)
    if not n:
        return
    L = ["", f"## {n} mission{'s' if n != 1 else ''} left for tomorrow night", "",
         "The night shift's stop time came first, so these weren't started (nothing of them was lost). "
         "They're back in Missions/Tonight and start at the next night shift by themselves. Want them "
         "sooner? Open Missions/Tonight in Files (F7), L loads one, then RUN.", ""]
    L += [f"- {x}" for x in labels] + [""]
    path = sb.output / "_REPORT.md"
    try:
        old = path.read_text(encoding="utf-8") if path.exists() else f"# Joe report — {datetime.now():%Y-%m-%d %H:%M}\n"
        atomic_write_text(path, old.rstrip("\n") + "\n" + "\n".join(L))
        reports = sorted((sb.meta / "reports").glob("REPORT_*.md"))
        if reports:
            atomic_write_text(reports[-1], reports[-1].read_text(encoding="utf-8").rstrip("\n") + "\n" + "\n".join(L))
    except OSError:
        pass


def _mission_lines(mission: Mission, states: list) -> list[str]:
    L = [f"Project: {mission.project or '(none)'}", ""]

    tot_items = sum(s.items for s in states)
    tot_words = sum(s.words for s in states)
    tot_in = sum(s.tokens_in for s in states)
    tot_out = sum(s.tokens_out for s in states)
    secs = sum(s.model_seconds for s in states)
    L += ["## Summary", "",
          "| Task | Status | Parts | Items | Words | Retries | Short | Dupes dropped | File |",
          "|---|---|---|---|---|---|---|---|---|"]
    for s in states:
        L.append(f"| {s.name} | {s.status} | {s.parts_done}/{s.parts_total} | {s.items} | "
                 f"{s.words} | {s.retries} | {s.short_items} | {s.duplicates_dropped} | "
                 f"{s.output or '-'} |")
    L += ["", f"Totals: {tot_items} items, {tot_words} words, {tot_in + tot_out:,} local tokens "
              f"({tot_in:,} in / {tot_out:,} out), {secs / 60:.1f} min model time.", ""]

    notes = [f"- {s.name}: {s.note}" for s in states if s.note]
    skipped = [f"- {s.name}: part{'s' if len(s.skipped_parts) > 1 else ''} {', '.join(map(str, s.skipped_parts))} skipped"
               for s in states if s.skipped_parts]
    if notes or skipped:
        L += ["## Problems", "", *notes, *skipped, ""]

    flag_lines = []
    for s in states:
        for f in s.flags:
            flag_lines.append(f"- {s.name} › {f['item']}: {f['flag']}")
    if flag_lines:
        kinds = Counter(f["flag"].split(":")[0].split()[0].strip("[]")
                        for s in states for f in s.flags)
        L += ["## Flags to review", "",
              "Counts: " + ", ".join(f"{k} {v}" for k, v in kinds.most_common()), ""]
        L += flag_lines[:MAX_FLAG_LINES]
        if len(flag_lines) > MAX_FLAG_LINES:
            L.append(f"- …and {len(flag_lines) - MAX_FLAG_LINES} more (search the files for '[').")
        L.append("")

    plain = [explain(s) for s in states if s.status in ("failed", "stopped", "partial")]
    if plain:                                   # 2.3: long jobs that failed or stopped, in plain words
        L += ["## What went wrong, in plain words", "", *plain, ""]

    left = [s for s in states if s.status not in ("done",)]
    L += ["## What's left", ""]
    if left:
        for s in left:
            skipped = sorted(set(getattr(s, "skipped_parts", []) or []))
            missing = max(0, s.parts_total - s.parts_done)
            bits = []
            if skipped:
                bits.append(f"part{'s' if len(skipped) > 1 else ''} {', '.join(map(str, skipped))} "
                            "skipped (running the plan again writes the whole task again, as a new copy)")
            if missing:
                bits.append(f"{missing} part(s) not started")
            L.append(f"- {s.name}: {s.status}" + (", " + "; ".join(bits) if bits else "")
                     + (f" ({s.note})" if s.note else ""))
    else:
        L.append("- Nothing. All tasks finished.")
    L.append("")

    return L


# (pattern in Joe's note, what happened, what to do) — first match wins
_WHY = [
    (r"Ollama is not running|Ollama isn't running|couldn't think|Connection refused.*11434",
     "the writing program (Ollama) wasn't answering", "Setup (F10) > System check starts it; then RUN the plan again."),
    (r"ComfyUI.*(not running|didn't start|couldn't start)|8188|8000.*refused",
     "the picture program (ComfyUI) wasn't answering", "Setup (F10) > System check starts it; then RUN the plan again."),
    (r"out of memory|CUDA|OOM|not enough (?:video|GPU) memory",
     "the graphics card ran out of memory", "Try a smaller SIZE, fewer VARIANTS, or Quality: Low (Setup > Images & video)."),
    (r"timed? ?out|timeout|took longer",
     "one step took longer than Joe waits for it", "Run it again (it often works the second time), or raise the time limit in Setup > Images & video."),
    (r"No space|disk full|ENOSPC|free on the drive|out of room",
     "the drive ran out of room", "Stats (F9) > CLEAN UP frees space; then RUN the plan again."),
    (r"open in another program|PermissionError|being used by another process",
     "a file was open in another program (Excel, a viewer)", "Close it and RUN the plan again."),
    (r"bad SAVE path|SandboxError|outside the workspace|not allowed",
     "the plan named a place Joe isn't allowed to write", "Change the SAVE: name in the plan (Step by step, F6)."),
    (r"Pandoc", "the Word/PDF copies need Pandoc", "Setup (F10) > System check installs it."),
    (r"stopped|run stopped|STOP", "the run was stopped (STOP, the night shift's stop time, or Joe was closed)",
     "RUN the plan again: finished parts are kept and Joe carries on where he stopped."),
    (r"I got stuck", "the agent got stuck", "Its AGENT REPORT.md says why and what would help."),
    (r"not found|no files", "a file the plan asked for wasn't there", "Put it in Inbox (or fix the INPUT: name) and RUN the plan again."),
]


def _took(s) -> str:
    try:
        a = datetime.fromisoformat(getattr(s, "started", "") or "")
        b = datetime.fromisoformat(s.finished) if getattr(s, "finished", "") else None
    except (TypeError, ValueError):
        return ""
    if not b:
        return f"started {a:%H:%M}"
    m = int((b - a).total_seconds() // 60)
    return f"ran {m // 60}h {m % 60:02d}m" if m >= 60 else f"ran {m} min"


def explain(s) -> str:
    """One plain line for a task that failed, stopped or finished with gaps: what happened, how far it
    got, what's kept and what to do. (The raw note is still under Problems for whoever helps.)"""
    import re as _re
    note = getattr(s, "note", "") or ""
    what, todo = "something went wrong", "The log on the main screen says more; RUN the plan again to retry."
    if s.status == "stopped" and not note:
        note = "stopped"
    for rx, w, t in _WHY:
        if _re.search(rx, note, _re.I):
            what, todo = w, t
            break
    if s.status == "partial" and what == "something went wrong":
        what = "some parts came out empty after every retry and were skipped"
        todo = "Running the plan again writes the whole task again, as a new copy beside this one."
    far = []
    if getattr(s, "parts_total", 0):
        far.append(f"{s.parts_done} of {s.parts_total} parts done")
    took = _took(s)
    if took:
        far.append(took)
    kept = (f" What's done is kept in {s.output}." if getattr(s, "output", "") and
            (getattr(s, "parts_done", 0) or getattr(s, "items", 0)) else "")
    return f"- **{s.name}** ({', '.join(far) or s.status}): {what}.{kept} What to do: {todo}"
