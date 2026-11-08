"""Writing helpers on the Tools tab (2.1): Summarize, Rewrite, Brainstorm, Study helper and
Explain or review my code. All run on the writing model on this PC, read the person's files
without ever changing them, and save Markdown next to the task's other results.

Honesty rules shared by all five: never invent facts, numbers, names, quotes or experience;
anything unsure is marked [CHECK]; code is read, never run.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .fsutil import atomic_write_text
from .items import count_words, find_flags

if TYPE_CHECKING:
    from .engine import Engine, JobState
    from .mission import Job, Mission

WRITE_TOOLS = ("summarize", "rewrite", "brainstorm", "study", "code-review")
CODE_EXT = (".py", ".pyw", ".js", ".mjs", ".ts", ".tsx", ".jsx", ".html", ".htm", ".css", ".java",
            ".c", ".h", ".cpp", ".hpp", ".cs", ".go", ".rs", ".rb", ".php", ".sh", ".ps1", ".bat",
            ".sql", ".lua", ".swift", ".kt", ".gd", ".json", ".yaml", ".yml", ".toml", ".ini", ".txt", ".md")
CHUNK_WORDS = 2200            # words per model call when reading (summaries, study notes)
REWRITE_WORDS = 600           # rewrites come back as long as they went in
CODE_LINES = 260              # lines of code per model call

HONEST = ("Use only what the text says. Never invent facts, numbers, names, dates, quotes or "
          "experience. If something is unclear, write [CHECK] right after it.")

# --------------------------------------------------------------------------- summarize
SUM_SYSTEM = ("You summarize the person's document in plain, friendly words. " + HONEST +
              " Markdown headings and bullet points. Reply with ONLY the summary.")
SUM_HOW = {
    "short": "A short summary: one paragraph of 3-6 sentences, then 'Worth knowing:' with 1-3 bullets.",
    "points": "## Summary (2-4 sentences)\n## Key points (bullets)\n## Names, numbers and dates (bullets, "
              "exactly as written, or 'None')\n## To-dos or decisions (bullets, or 'None mentioned')",
    "chapters": "One '## <section title>' per section with 2-5 bullets each.",
}
SUM_PART = "Notes for part {n} of {total} of a longer document. Bullets only, keep every name, number and date exactly."

# --------------------------------------------------------------------------- rewrite
REWRITE_HOW = {
    "friendly": "warmer and friendlier, still clear",
    "formal": "more formal and professional",
    "shorter": "shorter: cut repeats and filler, keep every fact",
    "simpler": "simpler: short sentences and everyday words anyone can read",
    "email": "a clear, polite email (greeting, the point first, a short closing)",
    "resume": "a resume tailored to the job post the person gave: put the matching experience first and "
              "use the post's words where they truly fit",
    "custom": "the way the person asked",
}
RW_SYSTEM = ("You rewrite the person's text the way they ask. Keep the meaning and every fact. "
             "Never add facts, numbers, skills, experience, dates or promises that aren't in the text "
             "(for a resume: never invent jobs, skills or results). Keep Markdown formatting. "
             "If something needed is missing, write [CHECK: what's missing]. Reply with ONLY the rewritten text.")
RW_ASK = "Rewrite the text between <<< and >>> to be {how}.{wish}\n\n<<<\n{text}\n>>>"
RW_CHANGES = ("Compare the ORIGINAL and the REWRITE and list what changed, in 3-8 short bullets "
              "(tone, length, what moved, anything marked [CHECK]). Reply with ONLY the bullets.")

# --------------------------------------------------------------------------- brainstorm
BS_KINDS = {
    "ideas": "ideas",
    "names": "names (each with a one-line reason)",
    "gifts": "gift ideas (each with who it suits and a rough price range, marked [CHECK])",
    "angles": "marketing angles or hooks (each with a sample headline)",
    "outline": "an outline: numbered sections with 2-4 bullet points each",
    "solutions": "ways to solve the problem (each with one pro and one con)",
}
BS_SYSTEM = ("You brainstorm with the person. Give varied, specific, practical ideas, from safe to bold; "
             "no repeats and no filler. Never claim facts or prices as certain: mark them [CHECK]. "
             "Numbered list in Markdown. Reply with ONLY the list.")

# --------------------------------------------------------------------------- study helper
LEVELS = {
    "kid": "a 10-year-old: everyday words and simple examples",
    "teen": "a high-school student",
    "adult": "a grown-up who is new to the topic",
    "expert": "someone who already knows the basics and wants the detail",
}
ST_SYSTEM = ("You are a patient tutor. Explain using only the person's material. " + HONEST +
             " Markdown. Reply with ONLY what was asked.")
ST_EXPLAIN = "Explain the main ideas of this material for {level}. Use '## ' headings, short paragraphs and one example per idea."
ST_CARDS = ('Make {n} flashcards from this material. Reply with ONLY a JSON array like '
            '[{{"front": "question or word", "back": "short answer"}}].')
ST_QUIZ = ("Write a {n}-question multiple-choice practice quiz from this material for {level}. "
           "Number the questions, give options A-D, one right answer each. After all the questions, "
           "a line '## Answers' and each answer with one sentence on why.")
ST_TEACH = ("Teach-me mode: start with 3 questions to think about before reading, then the explanation, "
            "then 'Try it yourself': 2 small tasks (answers at the very end).")

# --------------------------------------------------------------------------- code review
CR_SYSTEM = ("You review code the person wrote. You can't run it and must not pretend you did. "
             "Be specific: name the line or function. Never invent library functions. If unsure, say "
             "[CHECK]. Markdown. Reply with ONLY the review.")
CR_PARTS = {
    "explain": "## What it does\nPlain words, then a short walk through the main parts.",
    "bugs": "## Likely bugs and risks\nBullets: where, what goes wrong, and a fix (small code block). "
            "Include security problems (secrets in code, unsafe input). Write 'None found' if none.",
    "tests": "## Tests to add\nA few test ideas, and one example test in the same language.",
    "tidy": "## Easy improvements\nNaming, repeats, simpler ways: bullets, most useful first.",
}


def _text(engine: "Engine", src: Path) -> str:
    from .tools import document_text, RAW_TEXT_EXT, DOC_EXT
    if src.suffix.lower() in DOC_EXT and src.suffix.lower() not in RAW_TEXT_EXT:
        return document_text(src, engine.log)
    raw = src.read_bytes()
    if b"\x00" in raw[:4096]:
        raise ValueError("that file isn't text")
    return raw.decode("utf-8-sig", "replace").replace("\r\n", "\n")


def chunks_by_words(text: str, words: int) -> list[str]:
    from .tools import proof_chunks
    return [c for c in proof_chunks(text, words) if c.strip()] or [text]


def chunks_by_lines(text: str, lines: int = CODE_LINES) -> list[tuple[int, str]]:
    """(first line number, piece) so the model can name real line numbers."""
    rows = text.split("\n")
    out = []
    for a in range(0, len(rows), lines):
        out.append((a + 1, "\n".join(f"{a + i + 1:>5}| {ln}" for i, ln in enumerate(rows[a:a + lines]))))
    return out or [(1, "")]


def clean(raw: str) -> str:
    t = re.sub(r"(?s)<think>.*?</think>", "", raw or "").strip()
    t = re.sub(r"^\s*(?:sure|okay|ok|here(?:'s| is| are))\b[^\n]{0,80}:\s*\n", "", t, count=1, flags=re.I)
    t = re.sub(r"^```(?:markdown|md)?\n|\n```$", "", t.strip())
    t = re.sub(r"^\s*<<<\s*\n?|\n?\s*>>>\s*$", "", t)
    return t.strip()


def parse_cards(raw: str) -> list[dict]:
    from .tools import parse_json_list
    got = parse_json_list(raw) or []
    return [{"front": str(c.get("front", "")).strip(), "back": str(c.get("back", "")).strip()}
            for c in got if str(c.get("front", "")).strip() and str(c.get("back", "")).strip()]


def cards_csv(cards: list[dict]) -> str:
    """Front,Back: Anki, Quizlet and spreadsheets all import this."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(["Front", "Back"])
    for c in cards:
        w.writerow([c["front"], c["back"]])
    return "﻿" + buf.getvalue()


def note(what: str, model: str) -> str:
    return (f"> {what} by Joe on this computer ({model or 'the writing model'}). AI makes mistakes: "
            "check names, numbers and anything marked [CHECK]. Your original wasn't changed.\n\n")


# --------------------------------------------------------------------------- shared run loop
def run(engine: "Engine", mission: "Mission", job: "Job", st: "JobState") -> "JobState":
    from .engine import PartFailed, Stopped
    from .tools import TOOLS, _finish, _key, _no_files, resolve_inputs, tool_dir, unique_stem

    tid = job.type
    if tid == "brainstorm":
        files, problems = resolve_inputs(engine, job)
        for pr in problems:
            engine.log(f"  INPUT: {pr}")
        if not job.format.strip() and not files:
            st.status, st.note = "failed", "say what you need ideas for (the box on the Tools tab, or FORMAT:)"
            engine.log(f"'{job.name}' failed: {st.note}")
            return st
    else:
        if (bad := _no_files(engine, job, st, "files to read")) is not None:
            return bad
        files, _ = resolve_inputs(engine, job)
    if not engine._text_ready(st):
        engine._save_state(job, st)
        return st
    folder = tool_dir(engine, job, st)
    model = getattr(engine, "text_model", "") or engine.s.ollama.text_model
    st.status = "running"
    st.started = st.started or datetime.now().isoformat(timespec="seconds")
    engine._save_state(job, st)
    engine.log(f"{'Resuming' if st.titles else 'Starting'} '{job.name}' ({TOOLS[tid].name}) -> {st.output}")
    rules = ("\n" + job.rules.strip()) if job.rules.strip() else ""
    part = [0]

    def ask(kind: str, system: str, prompt: str, min_chars: int = 20) -> str:
        """One model call, retried once when the reply is empty or far too short."""
        got = ""
        for attempt in range(2):
            if engine.stop.is_set():
                raise Stopped()
            r = engine._chat(job, part[0], kind, system + rules,
                             prompt + ("\n\nReply with ONLY what was asked." if attempt else ""), st)
            part[0] += 1
            got = clean(r.text)
            if len(got) >= min_chars:
                return got
            st.retries += 1
        return got

    def save(name: str, body: str, label: str) -> None:
        atomic_write_text(folder / name, body if body.endswith("\n") else body + "\n")
        flags = find_flags(body)
        st.flags.extend({"item": label, "flag": f} for f in flags[:30])
        st.media_files.append(name)
        st.words += count_words(body)

    failed: list[str] = []
    try:
        if tid == "brainstorm":
            total = 1
            if not st.titles:
                _brainstorm(engine, job, files, ask, save, model)
                st.titles.append("ideas")
                st.items += 1
                engine._save_state(job, st)
        else:
            total = len(files)
            for i, src in enumerate(files):
                rel = _key(engine, src)
                if rel in st.titles:
                    continue
                try:
                    text = _text(engine, src)
                except (ValueError, OSError) as e:
                    failed.append(f"{src.name}: {e}"[:200])
                    engine.log(f"  {src.name}: {e}")
                    continue
                if not text.strip():
                    failed.append(f"{src.name}: no words in it")
                    continue
                stem = unique_stem(files, i)
                engine._progress(f"{job.name}: {src.name}")
                try:
                    made = {"summarize": _summarize, "rewrite": _rewrite, "study": _study,
                            "code-review": _review}[tid](engine, job, src, stem, text, ask, save, model)
                except PartFailed as e:
                    failed.append(f"{src.name}: {e}"[:200])
                    engine.log(f"  {src.name}: {e}")
                    continue
                st.titles.append(rel)
                st.items += 1
                engine._save_state(job, st)
                engine.log(f"  {src.name} -> {', '.join(made)}")
    except PartFailed as e:
        failed.append(str(e)[:200])
        total = 1
    except Stopped:
        st.status, st.note = "stopped", f"stopped after {len(st.titles)} file(s)"
        engine._save_state(job, st)
        engine.log(f"'{job.name}' {st.note}")
        return st
    return _finish(engine, job, st, total, failed)


def _wish(job: "Job") -> str:
    return f"\nThe person also asked: {job.format.strip()}" if job.format.strip() else ""


def _summarize(engine, job, src, stem, text, ask, save, model) -> list[str]:
    from .tools import option_value, split_sections
    how = option_value(job, "length") or "points"
    wish = _wish(job)
    if how == "chapters":
        parts = [(t or f"Part {n + 1}", b) for n, (t, b) in enumerate(split_sections(text)) if b.strip()]
        out = []
        for title, body in parts:
            pieces = chunks_by_words(body, CHUNK_WORDS)
            notes = pieces[0] if len(pieces) == 1 else "\n\n".join(
                ask("summarize", SUM_SYSTEM, f"{SUM_PART.format(n=k + 1, total=len(pieces))}\n\n<<<\n{p}\n>>>")
                for k, p in enumerate(pieces))
            out.append(f"## {title}\n\n" + ask("summarize", SUM_SYSTEM,
                       f"Summarize this section in 2-5 bullets.{wish}\n\n<<<\n{notes}\n>>>"))
        body = "\n\n".join(out)
    else:
        pieces = chunks_by_words(text, CHUNK_WORDS)
        if len(pieces) > 1:            # long document: notes per part, then one summary of the notes
            notes = "\n\n".join(ask("summarize", SUM_SYSTEM, f"{SUM_PART.format(n=k + 1, total=len(pieces))}"
                                    f"\n\n<<<\n{p}\n>>>") for k, p in enumerate(pieces))
            src_text = notes
        else:
            src_text = text
        body = ask("summarize", SUM_SYSTEM, f"Summarize the text between <<< and >>>.\n{SUM_HOW[how]}{wish}"
                   f"\n\n<<<\n{src_text}\n>>>")
    name = f"{stem}-summary.md"
    save(name, note("Summary", model) + f"# Summary: {src.stem}\n\n{body}", src.stem)
    return [name]


def _rewrite(engine, job, src, stem, text, ask, save, model) -> list[str]:
    from .tools import option_value
    style = option_value(job, "style") or "friendly"
    how = REWRITE_HOW.get(style, REWRITE_HOW["friendly"])
    wish = _wish(job)
    if style in ("resume", "custom") and not job.format.strip():
        wish += ("\n(No job post was given: tailor it for the kind of job the resume already points to.)"
                 if style == "resume" else "")
    out = []
    for piece in chunks_by_words(text, REWRITE_WORDS):
        got = ask("rewrite", RW_SYSTEM, RW_ASK.format(how=how, wish=wish, text=piece.strip()),
                  min_chars=max(20, int(len(piece.strip()) * (0.15 if style == "shorter" else 0.3))))
        out.append(got)
    new = "\n\n".join(out)
    ext = src.suffix.lower() if src.suffix.lower() in (".txt", ".md", ".markdown") else ".md"
    name = f"{stem}-{style}{ext}"
    save(name, new, src.stem)
    changes = ask("rewrite", RW_SYSTEM.split(". ")[0] + ".",
                  RW_CHANGES + f"\n\nORIGINAL:\n<<<\n{text[:6000]}\n>>>\n\nREWRITE:\n<<<\n{new[:6000]}\n>>>", 10)
    cname = f"{stem}-what-changed.md"
    save(cname, note("Rewritten", model) + f"# What changed: {src.name} -> {name}\n\nAsked for: {how}.\n\n{changes}\n",
         src.stem)
    return [name, cname]


def _brainstorm(engine, job, files, ask, save, model) -> None:
    from .tools import option_value
    kind = option_value(job, "kind") or "ideas"
    n = option_value(job, "count") or "25"
    topic = job.format.strip() or "the material below"
    context = ""
    for f in files[:3]:
        try:
            context += f"\n\nMATERIAL ({f.name}):\n<<<\n{_text(engine, f)[:8000]}\n>>>"
        except (ValueError, OSError):
            continue
    body = ask("brainstorm", BS_SYSTEM, f"Give {n} {BS_KINDS[kind]} for: {topic}{context}", 40)
    title = re.sub(r"\s+", " ", topic)[:70]
    save("ideas.md", note("Brainstormed", model).replace(" Your original wasn't changed.", "")
         + f"# {kind.capitalize()}: {title}\n\n{body}\n\n_Like one? Type \"park this: ...\" in Joe's box to keep it in Ideas.md._\n",
         title)
    from .tools import chosen_options
    if "park" in chosen_options(job):
        p = engine.sb.root / "Ideas.md"
        head = "" if p.exists() else "# Ideas for later\n\nParked with \"park this: ...\" in Joe's box.\n\n"
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(head + f"- {datetime.now():%Y-%m-%d}: brainstorm '{title}' -> {job.save}/ideas.md\n")


def _study(engine, job, src, stem, text, ask, save, model) -> list[str]:
    from .tools import chosen_options, option_value
    opts = chosen_options(job)
    level = LEVELS.get(option_value(job, "level") or "adult", LEVELS["adult"])
    wish = _wish(job)
    pieces = chunks_by_words(text, CHUNK_WORDS)
    material = pieces[0] if len(pieces) == 1 else "\n\n".join(
        ask("study", ST_SYSTEM, f"{SUM_PART.format(n=k + 1, total=len(pieces))}\n\n<<<\n{p}\n>>>")
        for k, p in enumerate(pieces))
    mat = f"\n\nMATERIAL:\n<<<\n{material}\n>>>"
    made, guide = [], [note("Study guide", model) + f"# Study guide: {src.stem}\n"]
    if "explain" in opts or "teach" in opts:
        prompt = ST_EXPLAIN.format(level=level) + (" " + ST_TEACH if "teach" in opts else "")
        guide.append(ask("study", ST_SYSTEM, prompt + wish + mat))
    if "quiz" in opts:
        guide.append("# Practice quiz\n\n" + ask("study", ST_SYSTEM, ST_QUIZ.format(n=10, level=level) + mat))
    name = f"{stem}-study-guide.md"
    save(name, "\n\n".join(guide), src.stem)
    made.append(name)
    if "cards" in opts:
        raw = ask("study", ST_SYSTEM, ST_CARDS.format(n=20) + mat)
        cards = parse_cards(raw)
        if cards:
            cname = f"{stem}-flashcards.csv"
            save(cname, cards_csv(cards), src.stem)
            made.append(cname)
    return made


def _review(engine, job, src, stem, text, ask, save, model) -> list[str]:
    from .tools import chosen_options
    opts = chosen_options(job) or {"explain", "bugs"}
    wanted = "\n".join(CR_PARTS[k] for k in ("explain", "bugs", "tests", "tidy") if k in opts)
    wish = _wish(job)
    pieces = chunks_by_lines(text)
    out = []
    for first, piece in pieces:
        where = f" (lines {first}+ of {src.name})" if len(pieces) > 1 else f" ({src.name})"
        out.append(ask("code-review", CR_SYSTEM, f"Review this code{where}. Write these parts:\n{wanted}"
                       f"{wish}\n\n<<<\n{piece}\n>>>"))
    name = f"{stem}-review.md"
    save(name, note("Code review", model).replace("check names, numbers", "test every suggested fix")
         + f"# Code review: {src.name}\n\nJoe read this code; he never ran it.\n\n" + "\n\n---\n\n".join(out), src.name)
    return [name]
