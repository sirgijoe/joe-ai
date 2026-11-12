"""Shrink a big text file before anyone reads it (2.3.0.dev20).

shrink(): pure Python, no model. Logs keep errors with context, the first and last lines, and
fold exact repeats into "(x N)". JSON becomes its shape: keys, types, first 3 items, lengths.
HTML becomes its visible text. Anything else: head + tail + grep hits.
summarize(): shrink, then summarize the pieces with the local text model, naming the lines used.
Nothing here ever leaves the PC: summarize refuses a model server that isn't on this machine.
"""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from urllib.parse import urlparse

EDGE = 20                     # first/last lines always kept
CONTEXT = 3                   # lines kept around each error/warning
MAX_FILE = 50_000_000         # characters read from one file
CHUNK = 6_000                 # characters per piece sent to the model
MAX_CHUNKS = 8

_TS = re.compile(r"^\s*(?:\[?\d{4}-\d\d-\d\d[T ]\d\d:\d\d(?::\d\d(?:[.,]\d+)?)?(?:Z|[+-]\d\d:?\d\d)?\]?"
                 r"|\[?\d\d:\d\d:\d\d(?:[.,]\d+)?\]?"
                 r"|\[?[A-Z][a-z]{2} +\d+ \d\d:\d\d:\d\d\]?)\s*[-|:]?\s*")
_ALERT = re.compile(r"\b(ERROR|ERR|WARN(?:ING)?|FATAL|CRITICAL|EXCEPTION|FAIL(?:ED|URE)?)\b|Traceback \(most recent",
                    re.I)
_LOG_EXT = {".log", ".out", ".err"}
_JSON_EXT = {".json", ".jsonl", ".ndjson"}
_HTML_EXT = {".html", ".htm", ".xhtml"}


def strip_ts(line: str) -> str:
    return _TS.sub("", line, count=1)


def detect(name: str, text: str) -> str:
    ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    if ext in _JSON_EXT:
        return "json"
    if ext in _HTML_EXT:
        return "html"
    if ext in _LOG_EXT:
        return "log"
    head = text.lstrip()[:200].lower()
    if head.startswith(("{", "[")):
        return "json"
    if head.startswith(("<!doctype html", "<html")):
        return "html"
    sample = text.splitlines()[:50]
    if sample and sum(1 for ln in sample if _TS.match(ln) and strip_ts(ln) != ln) >= len(sample) // 2:
        return "log"
    return "text"


def _numbered(lines: list[str], keep: list[int], counts: dict[str, int] | None = None) -> str:
    """Kept lines as 'L12| text', a gap note where lines were left out, repeats as '(x N)'."""
    out, last, seen = [], -1, set()
    for i in sorted(set(keep)):
        if i - last > 1:
            out.append(f"... ({i - last - 1} lines left out)")
        last = i
        ln = lines[i]
        if counts is not None:
            key = strip_ts(ln).strip()
            n = counts.get(key, 1)
            if key in seen and n > 1:
                continue                                   # shown once, with its count
            seen.add(key)
            if n > 1:
                ln += f"  (x {n})"
        out.append(f"L{i + 1}| {ln}")
    if last < len(lines) - 1:
        out.append(f"... ({len(lines) - 1 - last} lines left out)")
    return "\n".join(out)


def _log(text: str) -> str:
    lines = text.splitlines()
    counts: dict[str, int] = {}
    for ln in lines:
        k = strip_ts(ln).strip()
        counts[k] = counts.get(k, 0) + 1
    keep = list(range(min(EDGE, len(lines)))) + list(range(max(0, len(lines) - EDGE), len(lines)))
    for i, ln in enumerate(lines):
        if _ALERT.search(ln):
            keep += range(max(0, i - CONTEXT), min(len(lines), i + CONTEXT + 1))
    return _numbered(lines, keep, counts)


def _text(text: str, grep: str = "") -> str:
    lines = text.splitlines()
    keep = list(range(min(EDGE, len(lines)))) + list(range(max(0, len(lines) - EDGE), len(lines)))
    pat = _grep_pattern(grep)
    if pat:
        keep += [i for i, ln in enumerate(lines) if pat.search(ln)]
    return _numbered(lines, keep)


def _grep_pattern(grep: str):
    words = [w for w in re.findall(r"\w{3,}", grep or "") if w.lower() not in _STOP]
    if words:
        return re.compile("|".join(re.escape(w) for w in words), re.I)
    return _ALERT if not grep else None


_STOP = {"the", "and", "for", "what", "which", "who", "how", "why", "does", "did", "this", "that", "with",
         "from", "are", "was", "were", "has", "have", "about", "file", "into", "there", "any", "all"}


def _shape(v, depth: int = 0):
    if depth > 8:
        return "..."
    if isinstance(v, dict):
        return {k: _shape(x, depth + 1) for k, x in list(v.items())[:50]} | (
            {"...": f"{len(v) - 50} more keys"} if len(v) > 50 else {})
    if isinstance(v, list):
        return [f"array[{len(v)}]"] + [_shape(x, depth + 1) for x in v[:3]]
    if isinstance(v, bool) or v is None:
        return "bool" if isinstance(v, bool) else "null"
    if isinstance(v, (int, float)):
        return f"{type(v).__name__} {v}"
    s = str(v)
    return f"str {s[:40]!r}" + ("+" if len(s) > 40 else "")


def _json(text: str) -> str:
    try:
        data = json.loads(text)
    except ValueError:
        rows = [ln for ln in text.splitlines() if ln.strip()]   # JSON Lines?
        try:
            data = [json.loads(r) for r in rows]
        except ValueError:
            return _text(text)
    return json.dumps(_shape(data), indent=1, ensure_ascii=False)


class _Visible(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "template", "head"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth, self.parts, self.title, self._in_title = 0, [], "", False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        if tag in self.SKIP:
            self.depth += 1
        elif tag in ("p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "section", "article"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in self.SKIP and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self.depth:
            self.parts.append(data)


def _html(text: str) -> str:
    p = _Visible()
    p.feed(text)
    body = re.sub(r"[ \t\r\f\v]+", " ", "".join(p.parts))
    body = "\n".join(ln.strip() for ln in body.splitlines() if ln.strip())
    return (f"Title: {p.title.strip()}\n" if p.title.strip() else "") + body


def _cap(s: str, max_chars: int) -> str:
    if len(s) <= max_chars:
        return s
    half = max(1, max_chars // 2 - 40)
    return s[:half] + f"\n... ({len(s) - 2 * half:,} characters cut from the middle)\n" + s[-half:]


def shrink(text: str, name: str = "", kind: str = "auto", max_chars: int = 8000, grep: str = "") -> dict:
    """{"kind", "original", "shrunk", "text"}: text is the shrunk body (no header)."""
    kind = (kind or "auto").lower()
    if kind not in ("auto", "log", "json", "html", "text"):
        raise ValueError("kind must be auto, log, json, html or text")
    max_chars = max(500, int(max_chars or 8000))
    if kind == "auto":
        kind = detect(name, text)
    body = {"log": _log, "json": _json, "html": _html}.get(kind, lambda t: _text(t, grep))(text)
    body = _cap(body, max_chars)
    return {"kind": kind, "original": len(text), "shrunk": len(body), "text": body}


def header(r: dict, label: str) -> str:
    pct = 100 * r["shrunk"] // max(1, r["original"])
    return f"[{label} | {r['kind']} | {r['original']:,} -> {r['shrunk']:,} chars ({pct}%)]"


# -- summarize ---------------------------------------------------------------------------------

def is_local(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1") or host.startswith("127.")


def _chunks(text: str) -> list[str]:
    out, cur = [], []
    size = 0
    for ln in text.splitlines():
        if size + len(ln) > CHUNK and cur:
            out.append("\n".join(cur))
            cur, size = [], 0
        cur.append(ln[:CHUNK])
        size += len(ln) + 1
    if cur:
        out.append("\n".join(cur))
    return out


def _line_range(chunk: str, idx: int, total: int) -> str:
    nums = [int(m) for m in re.findall(r"^L(\d+)\|", chunk, re.M)]
    if nums:
        return f"L{min(nums)}-L{max(nums)}" if min(nums) != max(nums) else f"L{nums[0]}"
    return f"part {idx + 1}/{total}"


PART_SYSTEM = ("You summarize part of a shrunk file to answer a question. Use only the text given. "
               "Be short and exact; keep numbers, names and error messages as written. "
               "If nothing in this part helps, reply with just NOTHING.")
JOIN_SYSTEM = ("You combine notes about one file into one short answer to the question. "
               "Use only the notes. No preamble.")


def summarize(text: str, name: str, chat, question: str = "", max_words: int = 200,
              kind: str = "auto") -> dict:
    """chat(system, user) -> str (the local model). Returns {"answer", "lines", "shrink"}."""
    max_words = max(20, min(int(max_words or 200), 1000))
    r = shrink(text, name, kind, max_chars=CHUNK * MAX_CHUNKS, grep=question)
    q = question.strip() or "What is in this file? Give the main points and any problems."
    pieces = _chunks(r["text"])[:MAX_CHUNKS]
    notes, used = [], []
    for i, piece in enumerate(pieces):
        ans = chat(PART_SYSTEM, f"QUESTION: {q}\nAnswer in at most {max_words} words.\n\nFILE PART "
                                f"({name}):\n{piece}").strip()
        if ans and not ans.upper().startswith("NOTHING"):
            rng = _line_range(piece, i, len(pieces))
            notes.append(f"[{rng}] {ans}")
            used.append(rng)
    if not notes:
        answer = "Nothing in the file answers that."
    elif len(notes) == 1:
        answer = notes[0].split("] ", 1)[1]
    else:
        answer = chat(JOIN_SYSTEM, f"QUESTION: {q}\nAt most {max_words} words.\n\nNOTES:\n" +
                      "\n".join(notes)).strip()
    words = answer.split()
    if len(words) > max_words:
        answer = " ".join(words[:max_words]) + " ..."
    return {"answer": answer, "lines": used, "shrink": r}
