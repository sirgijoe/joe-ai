"""Write like my own documents (OPTIONS: mine on Rewrite, Summarize and Brainstorm).

The person keeps some of their own writing in Inbox/My writing. When the box is ticked, Joe reads a
few of those files, works out plain facts about how they write (sentence length, contractions,
exclamation marks, "I" and "we", lists) and picks a few short passages. The writing model gets
both as a voice guide: copy the voice, never the sentences or the facts. Nothing leaves this PC and
the samples are never changed. The counting is plain Python, no AI."""
from __future__ import annotations

import re
from pathlib import Path

FOLDER = "My writing"
SAMPLE_EXT = (".txt", ".md", ".markdown", ".docx", ".html", ".htm")
MAX_FILES = 8
FILE_WORDS = 300           # words taken from each sample file
TOTAL_WORDS = 1400         # words of samples handed to the model in all
MIN_PARAGRAPH_WORDS = 12   # a "passage" is a real paragraph, not a heading or a one-liner
MIN_SAMPLE_WORDS = 60      # less writing than this isn't enough to learn a voice from

CONTRACTION = re.compile(r"\b\w+'(?:s|t|re|ve|ll|d|m)\b", re.I)
FIRST_PERSON = re.compile(r"\b(?:i|me|my|we|our|us)\b", re.I)
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9])")


def folder(engine) -> Path:
    return engine.sb.inbox / FOLDER


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9'’-]*", text)


def voice_facts(text: str) -> list[str]:
    """Plain facts about how someone writes, as short lines. Only what can be counted."""
    plain = re.sub(r"(?m)^\s*(?:#+\s+|[-*+]\s+|\d+[.)]\s+)", "", text)
    words = _words(plain)
    if len(words) < MIN_SAMPLE_WORDS:
        return []
    sentences = [s for s in SENTENCE_END.split(" ".join(plain.split())) if s.strip()]
    per = len(words) / max(1, len(sentences))
    out = []
    if per < 11:
        out.append(f"short sentences (about {per:.0f} words each)")
    elif per < 19:
        out.append(f"medium-length sentences (about {per:.0f} words each)")
    else:
        out.append(f"long sentences (about {per:.0f} words each)")
    n = len(words)
    contractions = len(CONTRACTION.findall(plain.replace("’", "'")))
    out.append("uses contractions (don't, it's)" if contractions / n > 0.012 else
               "rarely uses contractions (writes 'do not', 'it is')")
    me = len(FIRST_PERSON.findall(plain)) / n
    if me > 0.03:
        out.append("writes in the first person (I, we, my)")
    elif me < 0.008:
        out.append("seldom says I or we")
    bangs = plain.count("!")
    if bangs >= max(2, len(sentences) // 15):
        out.append("uses exclamation marks")
    elif bangs == 0:
        out.append("no exclamation marks")
    lists = len(re.findall(r"(?m)^\s*(?:[-*+]|\d+[.)])\s+", text))
    if lists >= 4:
        out.append("often uses bullet or numbered lists")
    if len(re.findall(r"\?", plain)) / max(1, len(sentences)) > 0.08:
        out.append("asks the reader questions")
    return out


def _passage(text: str, limit: int) -> str:
    """The first real paragraphs of a document, up to `limit` words."""
    got, used = [], 0
    for block in re.split(r"\n[ \t]*\n", text.replace("\r\n", "\n")):
        block = " ".join(block.split())
        n = len(block.split())
        if n < MIN_PARAGRAPH_WORDS or block.startswith("#"):
            continue
        if used + n > limit:
            block = " ".join(block.split()[:max(0, limit - used)])
            if len(block.split()) >= MIN_PARAGRAPH_WORDS:
                got.append(block + " ...")
            break
        got.append(block)
        used += n
        if used >= limit:
            break
    return "\n\n".join(got)


def samples(engine, exclude: list[Path], log) -> list[tuple[str, str]]:
    """[(file name, text)] of the newest sample files in Inbox/My writing, never the files being worked on."""
    from .tools import document_text
    root = folder(engine)
    if not root.is_dir():
        return []
    skip = set()
    for p in exclude:
        try:
            skip.add(p.resolve())
        except OSError:
            pass
    found = []
    for f in root.iterdir():
        try:
            if (f.is_file() and f.suffix.lower() in SAMPLE_EXT and not f.name.startswith(".")
                    and f.resolve() not in skip):
                found.append((f.stat().st_mtime, f))
        except OSError:
            continue
    out = []
    for _, f in sorted(found, key=lambda t: t[0], reverse=True)[:MAX_FILES]:
        try:
            out.append((f.name, document_text(f, log)))
        except (ValueError, OSError, KeyError) as e:
            log(f"  My writing/{f.name}: skipped ({e})")
    return out


def guide(engine, exclude: list[Path], log) -> str:
    """The voice guide for the writing model, or '' when there isn't enough of the person's writing."""
    got = samples(engine, exclude, log)
    everything = "\n\n".join(t for _, t in got)
    facts = voice_facts(everything)
    if not facts:
        return ""
    per = max(80, min(FILE_WORDS, TOTAL_WORDS // max(1, len(got))))
    passages, used = [], 0
    for name, text in got:
        p = _passage(text, min(per, TOTAL_WORDS - used))
        if p:
            passages.append(p)
            used += len(p.split())
        if used >= TOTAL_WORDS:
            break
    if not passages:
        return ""
    log(f"  Writing like the {len(got)} document(s) in Inbox/{FOLDER}")
    return ("\n\nVOICE GUIDE. The person wants this to sound like their own writing. How they write: "
            + "; ".join(facts) + ". A few passages they wrote (copy the VOICE only: word choice, rhythm, "
            "warmth, how they open and close). Never copy their sentences, and never take facts, names or "
            "details from these passages into your answer):\n<<<\n" + "\n---\n".join(passages) + "\n>>>")
