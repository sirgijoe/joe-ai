"""Compare two versions of a document: what was added, removed and changed (tool "compare-docs",
run by paperwork.py). No AI: plain text matching with difflib, so nothing is invented.

Paragraphs are matched first; a paragraph that was edited is paired with its new version when the
two are at least half alike, and its changed words are marked. Pure functions, easy to test."""
from __future__ import annotations

import difflib
import re

PAIR_MIN = 0.5                 # how alike (0-1) an old and a new paragraph must be to count as "changed"
PAIR_CELLS = 40_000            # a block of edits bigger than this many old x new paragraphs isn't paired
SHOW_MAX = 500                 # changes listed in the report; the rest are counted
TEXT_MAX = 1200                # characters of one paragraph shown in the report


LIST_LINE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
LINE_END = re.compile(r"[.!?:;]\s*$")


def _is_list(block: str) -> bool:
    """A block of separate lines (a to-do list, bullets, one sentence per line), not prose wrapped
    over several lines: every line is a bullet, ends a sentence, or is at most 4 words (milk, eggs, bread)."""
    lines = [ln for ln in block.split("\n") if ln.strip()]
    return len(lines) >= 2 and all(LIST_LINE.match(ln) or LINE_END.search(ln) or len(ln.split()) <= 4
                                   for ln in lines)


def paragraphs(text: str) -> list[str]:
    """Non-empty paragraphs with their spaces and line breaks tidied. Blank lines separate
    paragraphs; a file with no blank lines (a plain list of lines) is split on line breaks, and so is
    a block that is a list of lines (2.3.0.dev25: a to-do list came out as one long changed paragraph)."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n[ \t]*\n", text)
    if len([b for b in blocks if b.strip()]) <= 1:
        blocks = text.split("\n")
    else:
        blocks = [ln for b in blocks for ln in (b.split("\n") if _is_list(b) else [b])]
    out = [" ".join(b.split()) for b in blocks]
    return [p for p in out if p]


def _words(p: str) -> list[str]:
    return p.split()


def _ratio(a: str, b: str) -> float:
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return 0.0
    sm = difflib.SequenceMatcher(None, wa, wb, autojunk=False)
    if sm.real_quick_ratio() < PAIR_MIN or sm.quick_ratio() < PAIR_MIN:
        return 0.0
    return sm.ratio()


def word_diff(old: str, new: str) -> tuple[str, int, int]:
    """(markdown, words added, words removed): ~~old~~ for removed words, **new** for added ones."""
    wa, wb = _words(old), _words(new)
    sm = difflib.SequenceMatcher(None, wa, wb, autojunk=False)
    parts: list[str] = []
    added = removed = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            parts.append(" ".join(wa[i1:i2]))
            continue
        if i2 > i1:
            parts.append("~~" + " ".join(wa[i1:i2]) + "~~")
            removed += i2 - i1
        if j2 > j1:
            parts.append("**" + " ".join(wb[j1:j2]) + "**")
            added += j2 - j1
    return " ".join(parts), added, removed


def _pair_block(old: list[str], new: list[str], i1: int, i2: int, j1: int, j2: int) -> list[tuple[int | None, int | None]]:
    """Pair up the old and new paragraphs of one replaced block, in order:
    (i, j) = changed, (i, None) = removed, (None, j) = added."""
    pairs: list[tuple[int | None, int | None]] = []
    matched: list[tuple[int, int | None]] = []
    if (i2 - i1) * (j2 - j1) <= PAIR_CELLS:
        last = j1 - 1
        for i in range(i1, i2):
            best: tuple[float, int] | None = None
            for j in range(last + 1, j2):
                r = _ratio(old[i], new[j])
                if r >= PAIR_MIN and (best is None or r > best[0]):
                    best = (r, j)
            if best:
                matched.append((i, best[1]))
                last = best[1]
            else:
                matched.append((i, None))
    else:
        matched = [(i, None) for i in range(i1, i2)]
    cursor = j1
    for i, j in matched:
        if j is None:
            pairs.append((i, None))
            continue
        while cursor < j:
            pairs.append((None, cursor))
            cursor += 1
        pairs.append((i, j))
        cursor = j + 1
    while cursor < j2:
        pairs.append((None, cursor))
        cursor += 1
    return pairs


def compare(old_text: str, new_text: str) -> dict:
    """What changed from the old text to the new one.

    Returns {"changes": [{"kind": "added|removed|changed", "old": str, "new": str, "diff": str,
    "old_no": int, "new_no": int}], "added_words", "removed_words", "old_paragraphs",
    "new_paragraphs", "old_words", "new_words", "same": bool}. Paragraph numbers start at 1."""
    old, new = paragraphs(old_text), paragraphs(new_text)
    changes: list[dict] = []
    added_w = removed_w = 0
    sm = difflib.SequenceMatcher(None, old, new, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        if tag == "delete":
            pairs = [(i, None) for i in range(i1, i2)]
        elif tag == "insert":
            pairs = [(None, j) for j in range(j1, j2)]
        else:
            pairs = _pair_block(old, new, i1, i2, j1, j2)
        for i, j in pairs:
            if i is not None and j is not None:
                diff, a, r = word_diff(old[i], new[j])
                added_w += a
                removed_w += r
                changes.append({"kind": "changed", "old": old[i], "new": new[j], "diff": diff,
                                "old_no": i + 1, "new_no": j + 1})
            elif i is not None:
                removed_w += len(_words(old[i]))
                changes.append({"kind": "removed", "old": old[i], "new": "", "diff": "",
                                "old_no": i + 1, "new_no": 0})
            else:
                added_w += len(_words(new[j]))
                changes.append({"kind": "added", "old": "", "new": new[j], "diff": "",
                                "old_no": 0, "new_no": j + 1})
    return {"changes": changes, "added_words": added_w, "removed_words": removed_w,
            "old_paragraphs": len(old), "new_paragraphs": len(new),
            "old_words": sum(len(_words(p)) for p in old), "new_words": sum(len(_words(p)) for p in new),
            "same": not changes}


def _shown(p: str) -> str:
    return p if len(p) <= TEXT_MAX else p[:TEXT_MAX].rsplit(" ", 1)[0] + " ..."


def _quote(p: str) -> str:
    return "> " + _shown(p)


def report(res: dict, old_name: str, new_name: str, words: bool = True) -> str:
    """The comparison as a Markdown page. `words`: show the changed words inside an edited
    paragraph (off: show the old and the new paragraph whole)."""
    ch = res["changes"]
    n_add = sum(1 for c in ch if c["kind"] == "added")
    n_rem = sum(1 for c in ch if c["kind"] == "removed")
    n_chg = sum(1 for c in ch if c["kind"] == "changed")
    lines = ["# Document comparison", "",
             f"Older: **{old_name}** ({res['old_words']:,} words, {res['old_paragraphs']:,} paragraphs)  ",
             f"Newer: **{new_name}** ({res['new_words']:,} words, {res['new_paragraphs']:,} paragraphs)", ""]
    if res["same"]:
        lines += ["**No differences.** Every paragraph is the same (extra spaces and line breaks are ignored).", ""]
        return "\n".join(lines)
    lines += ["## Summary", "",
              f"- {n_chg} paragraph(s) changed",
              f"- {n_add} paragraph(s) added",
              f"- {n_rem} paragraph(s) removed",
              f"- About {res['added_words']:,} word(s) added and {res['removed_words']:,} word(s) removed", "",
              "Nothing was guessed: this is a plain side-by-side match of the two texts. "
              "Neither file was changed. In the lists below, ~~struck-through~~ words are only in the older "
              "version and **bold** words are only in the newer one.", ""]
    shown = ch[:SHOW_MAX]
    for title, kind in (("Changed", "changed"), ("Added", "added"), ("Removed", "removed")):
        rows = [c for c in shown if c["kind"] == kind]
        if not rows:
            continue
        lines += [f"## {title}", ""]
        for c in rows:
            if kind == "changed":
                lines.append(f"**Paragraph {c['old_no']} (older) / {c['new_no']} (newer)**")
                lines.append("")
                if words:
                    lines.append(_quote(c["diff"]))
                else:
                    lines += ["Older:", "", _quote(c["old"]), "", "Newer:", "", _quote(c["new"])]
            elif kind == "added":
                lines += [f"**New paragraph {c['new_no']}**", "", _quote(c["new"])]
            else:
                lines += [f"**Old paragraph {c['old_no']}**", "", _quote(c["old"])]
            lines.append("")
    if len(ch) > SHOW_MAX:
        lines += [f"*{len(ch) - SHOW_MAX} more change(s) are not listed here (the first {SHOW_MAX} are shown). "
                  "Compare smaller parts to see them all.*", ""]
    return "\n".join(lines)
