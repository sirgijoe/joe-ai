"""Splitting model output into items, word counts, duplicates and flags."""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

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


# Model control words that sometimes leak into a heading ("Stoneware Bowl /no_think", or
# misspelled "/no_thing"). They'd end up in file names, so they're removed.
_LEAK = re.compile(r"\s*/(?:no_?think\w*|no_?thing\w*|think\w*|nothink\w*)\b", re.I)


def _strip_md(t: str) -> str:
    t = re.sub(r"^\s*(?:item\s*)?\d+[.):-]\s*", "", t, flags=re.I)  # "3. Title" -> "Title"
    t = _LEAK.sub("", t)
    return t.strip(" *_`").strip()


def norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", t.lower()).strip()


def is_duplicate(title: str, seen: list[str], threshold: float = 0.9) -> bool:
    """Exact match, or a near-copy of a longer title. Titles that differ only in a
    number ('Mug 3' vs 'Mug 4') are treated as different on purpose."""
    n = norm_title(title)
    if not n:
        return True
    nums = re.findall(r"\d+", n)
    for s in seen:
        if n == s:
            return True
        if len(n) >= 20 and re.findall(r"\d+", s) == nums \
                and SequenceMatcher(None, n, s).ratio() >= threshold:
            return True
    return False


def find_flags(text: str) -> list[str]:
    return FLAG_RE.findall(text)
