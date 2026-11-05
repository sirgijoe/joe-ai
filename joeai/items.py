"""Splitting model output into items, word counts, duplicates and flags."""
from __future__ import annotations

import re
from dataclasses import dataclass

_HEAD = re.compile(r"^\s*#{2,3}\s+(.+?)\s*#*\s*$")
FLAG_RE = re.compile(r"\[(?:CHECK|PRICE|CONFIRM|SHORT|TODO)[^\]\n]{0,60}\]")
_WORD = re.compile(r"[A-Za-z0-9']+(?:[-'][A-Za-z0-9]+)*")


@dataclass
class Item:
    title: str
    body: str

    @property
    def words(self) -> int:
        return count_words(self.body)

    def render(self) -> str:
        return f"## {self.title}\n\n{self.body.strip()}\n"


def count_words(text: str) -> int:
    return len(_WORD.findall(text))


def split_items(text: str) -> list[Item]:
    """Split on '## Title' / '### Title' lines. Text before the first heading is dropped."""
    items: list[Item] = []
    title, buf = None, []
    for line in text.splitlines():
        m = _HEAD.match(line)
        if m:
            if title is not None:
                items.append(Item(title, "\n".join(buf).strip()))
            title, buf = _strip_md(m.group(1)), []
        elif title is not None:
            buf.append(line)
    if title is not None:
        items.append(Item(title, "\n".join(buf).strip()))
    return items


_LOOSE_HEAD = re.compile(r"^\s*(?:\*\*(.+?)\*\*:?|\d+[.)]\s+(?:\*\*)?(.+?)(?:\*\*)?:?|#{1,6}\s+(.+?))\s*$")


_LIST_LINE = re.compile(r"^\s*(?:\d+[.)]|[-*\u2022])\s+\S")


def _one_liner(line: str) -> Item:
    """'1. **Bolt** - quick and strong' -> Item('Bolt', 'quick and strong')."""
    s = re.sub(r"^\s*(?:\d+[.)]|[-*\u2022])\s+", "", line).strip()
    m = re.match(r"^\*\*(.+?)\*\*\s*[:\-\u2013\u2014]?\s*(.*)$", s) or \
        re.match(r"^(.{1,60}?)\s*(?::|\s[-\u2013\u2014]\s)\s*(.+)$", s)
    if m:
        return Item(_strip_md(m.group(1)), m.group(2).strip() or _strip_md(m.group(1)))
    return Item(_strip_md(s)[:60], s)


def loose_items(text: str) -> list[Item]:
    """For replies without '## Title' lines: blocks that start with a bold line, a numbered
    line or any heading count as items (a model asked for prompts sometimes writes
    '1. **Title**' or '**Title**' instead)."""
    items: list[Item] = []
    lines = [x for x in (text or "").splitlines() if x.strip()]
    listed = [x for x in lines if _LIST_LINE.match(x)]
    if len(listed) >= 2 and len(listed) >= len(lines) - 2:
        return [_one_liner(x) for x in listed]          # a plain list: one item per line
    for block in re.split(r"\n[ \t]*\n", text or ""):
        lines = [x for x in block.strip().splitlines() if x.strip()]
        if not lines:
            continue
        m = _LOOSE_HEAD.match(lines[0])
        if m and len(lines) > 1:
            title = _strip_md(next(g for g in m.groups() if g))
            items.append(Item(title, "\n".join(lines[1:]).strip()))
        elif items and not m:
            items[-1] = Item(items[-1].title, (items[-1].body + "\n\n" + block.strip()).strip())
    return items


# Model control words that sometimes leak into a heading ("Stoneware Bowl /no_think", or
# misspelled "/no_thing"). They'd end up in file names, so they're removed.
_LEAK = re.compile(r"\s*/(?:no_?think\w*|no_?thing\w*|think\w*|nothink\w*)\b", re.I)


def _strip_md(t: str) -> str:
    t = re.sub(r"^\s*(?:item\s*)?\d+[.):-]\s*", "", t, flags=re.I)  # "3. Title" -> "Title"
    t = _LEAK.sub("", t)
    return t.strip(" *_`").strip()


def norm_title(t: str) -> str:
    t = re.sub(r"[-_/]", " ", t.lower())                  # "hand-thrown" -> "hand thrown"
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", t)).strip()


_STOP = frozenset("a an the and or of for to in on with my your our its this that is are be "
                  "it at by from as".split())


def _content(n: str) -> frozenset:
    """The words that carry meaning, plural-blind ('the blue mugs' -> {blue, mug})."""
    return frozenset(w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w
                     for w in n.split() if w not in _STOP)


def is_duplicate(title: str, seen: list[str], threshold: float = 0.9) -> bool:
    """Exact match, or the same meaningful words in any order, plural-blind ('Blue Mugs'
    vs 'The Blue Mug'). Titles with one different word ('...for my candle shop' vs
    '...for my soap shop') or a different number ('Mug 3' vs 'Mug 4') are kept: lists of
    one-liners and test requests are full of near-twins that are really different.
    (`threshold` is kept for older callers; it's no longer used.)"""
    n = norm_title(title)
    if not n:
        return True
    words = _content(n)
    for s in seen:
        s = norm_title(s)
        if n == s or (words and len(words) >= 2 and words == _content(s)):
            return True
    return False


def find_flags(text: str) -> list[str]:
    return FLAG_RE.findall(text)
