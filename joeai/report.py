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
