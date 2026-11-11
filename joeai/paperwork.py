"""Everyday paperwork tools (2.2): the jobs people pay a monthly fee for, or struggle with alone.

- pdf-tools:        join, split, pick/reorder, turn, shrink PDFs and fill in PDF forms (qpdf, no AI)
- explain-letter:   a bill, lease or benefits letter in plain words: what to do, by when, a draft reply
- hide-details:     names, addresses, phone numbers, account numbers... hidden before sharing a document
- meeting-minutes:  a recording (or its transcript) into minutes: decisions, to-dos, who and when
- bank-budget:      a bank's CSV into a budget: categories, subscriptions, price rises (Joe's own math)
- resume-tailor:    a resume + a job posting into a matched resume and cover letter; nothing invented
- mail-merge:       one letter + a spreadsheet into a personal letter per row (no AI)
- alt-text:         short descriptions of pictures for screen readers and shop listings
- duplicate-photos: copies and near-copies grouped, with the best one to keep (nothing is deleted)

Shared rules: the person's files are read, never changed (results go into a new folder under Output);
everything runs on this computer; numbers, dates and names the AI gives are checked against the
person's own file by Joe's code, and anything that can't be found there is marked [CHECK].
"""
from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import re
import shutil
import subprocess
import zipfile
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from .fsutil import atomic_write_text
from .items import count_words, find_flags

if TYPE_CHECKING:                                    # pragma: no cover
    from .engine import Engine, JobState
    from .mission import Job, Mission

PAPER_TOOLS = ("pdf-tools", "explain-letter", "hide-details", "meeting-minutes", "bank-budget",
               "resume-tailor", "mail-merge", "alt-text", "duplicate-photos")
TEXT_DOC_EXT = (".txt", ".md", ".markdown", ".docx", ".pdf", ".html", ".htm")
LETTER_EXT = (".txt", ".md", ".markdown", ".docx", ".html", ".htm")
MERGE_SHEET_EXT = (".csv", ".tsv", ".xlsx")
TRANSCRIPT_EXT = (".txt", ".md", ".srt", ".vtt", ".docx")
DOCX_MAX = 200_000_000              # an unpacked Word part bigger than this is a "zip bomb", not a letter


# =========================================================================== shared
def _begin(engine: "Engine", job: "Job", st: "JobState", what: str, need_text: bool = False):
    """Files, the writing model (if needed) and the output folder. Returns (files, folder), or the
    finished JobState when the task can't start."""
    from .tools import TOOLS, _no_files, resolve_inputs, tool_dir
    if (bad := _no_files(engine, job, st, what)) is not None:
        return bad
    files, _ = resolve_inputs(engine, job)
    if need_text and not engine._text_ready(st):
        engine._save_state(job, st)
        return st
    folder = tool_dir(engine, job, st)
    st.status = "running"
    st.started = st.started or datetime.now().isoformat(timespec="seconds")
    engine._save_state(job, st)
    engine.log(f"{'Resuming' if st.titles else 'Starting'} '{job.name}' ({TOOLS[job.type].name}): "
               f"{len(files)} file(s) -> {st.output}")
    return files, folder


def _fail(engine: "Engine", job: "Job", st: "JobState", note: str) -> "JobState":
    st.status, st.note = "failed", note
    engine._save_state(job, st)
    engine.log(f"'{job.name}' failed: {note}")
    return st


def _stopped(engine: "Engine", job: "Job", st: "JobState", total: int, unit: str = "file(s)") -> "JobState":
    st.status, st.note = "stopped", f"stopped after {len(st.titles)} of {total} {unit}"
    engine._save_state(job, st)
    engine.log(f"'{job.name}' {st.note}")
    return st


def _save(folder: Path, st: "JobState", name: str, body: str, label: str = "") -> None:
    atomic_write_text(folder / name, body if body.endswith("\n") else body + "\n")
    st.flags.extend({"item": label or name, "flag": f} for f in find_flags(body)[:30])
    if name not in st.media_files:
        st.media_files.append(name)
    st.words += count_words(body)


def _asker(engine: "Engine", job: "Job", st: "JobState"):
    """ask(kind, system, prompt) -> the model's reply, cleaned; asked a second time when it's empty."""
    from .engine import Stopped
    from .writetools import clean
    rules = ("\n" + job.rules.strip()) if job.rules.strip() else ""
    part = [0]

    def ask(kind: str, system: str, prompt: str, min_chars: int = 2) -> str:
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
    return ask


def parse_json(raw: str):
    """The first JSON object or list in a model's reply (thinking and code fences removed)."""
    t = re.sub(r"(?s)<think>.*?</think>", "", raw or "")
    t = re.sub(r"```[\w-]*", "", t)
    for a, b in (("{", "}"), ("[", "]")):
        i, j = t.find(a), t.rfind(b)
        if 0 <= i < j:
            try:
                return json.loads(t[i:j + 1])
            except json.JSONDecodeError:
                continue
    return None


def _ask_json(ask, kind: str, system: str, prompt: str):
    got = parse_json(ask(kind, system, prompt))
    if got is None:
        got = parse_json(ask(kind, system, prompt + "\n\nReply with ONLY the JSON, nothing else."))
    return got


def _norm(s: str) -> str:
    """For 'is this really in the letter?': lower case, one space, no fancy quotes or dashes."""
    s = str(s or "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-").replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip().lower()


def found_in(needle: str, haystack: str) -> bool:
    n = _norm(needle)
    return bool(n) and n in _norm(haystack)


def safe_cell(s) -> str:
    """A spreadsheet cell that came from someone else's file or from the AI: one starting with = + - @
    would run as a formula in Excel, so it gets a ' in front (shown as plain text)."""
    s = str(s if s is not None else "")
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def _md_cell(s) -> str:
    return re.sub(r"\s+", " ", str(s if s is not None else "")).replace("|", "\\|").strip()


def _table(header: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(_md_cell(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def _read_doc(engine: "Engine", src: Path) -> str:
    from .tools import document_text
    text = document_text(src, engine.log)
    if not text.strip():
        raise ValueError("no words in it")
    return text


def _model(engine: "Engine") -> str:
    return getattr(engine, "text_model", "") or engine.s.ollama.text_model


def _ai_note(what: str, model: str, extra: str = "") -> str:
    return (f"> {what} by Joe on this computer ({model or 'the writing model'}). AI makes mistakes: "
            "check names, numbers, dates and anything marked [CHECK]. Your original wasn't changed."
            + (f" {extra}" if extra else "") + "\n\n")


# =========================================================================== Word (.docx) text
# A Word paragraph's words are split over "runs" (<w:t> pieces) wherever the formatting changes,
# so "{First name}" can be "{First" + " name}". Joe joins each paragraph's pieces, finds what to
# change in the joined text, and writes each change into the piece where it starts: the rest of
# the formatting stays exactly as it was.
_DOCX_TOKEN = re.compile(r"<w:p[\s>/]|</w:p>|(<w:(?:t|delText)(?:\s[^>]*)?>)(.*?)(</w:(?:t|delText)>)", re.S)
DOCX_TEXT_PARTS = re.compile(r"^word/(?:document|header\d*|footer\d*|footnotes|endnotes|comments)\.xml$")


def _xml_text(s: str) -> str:
    return html.unescape(s)


def _xml_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def docx_edit_xml(xml: str, edit: Callable[[str], list[tuple[int, int, str]]]) -> tuple[str, int]:
    """Apply `edit` to each paragraph's joined text. edit(text) -> [(start, end, new text)], not
    overlapping. Returns (new xml, changes made)."""
    groups: list[list[re.Match]] = [[]]
    for m in _DOCX_TOKEN.finditer(xml):
        if m.group(1) is None:                     # a paragraph starts or ends: a new group
            if groups[-1]:
                groups.append([])
            continue
        groups[-1].append(m)
    replace: dict[int, str] = {}                   # match start -> new inner text
    changes = 0
    for g in groups:
        if not g:
            continue
        texts = [_xml_text(m.group(2)) for m in g]
        full = "".join(texts)
        spans = sorted(edit(full), key=lambda s: s[0])
        if not spans:
            continue
        starts = []
        pos = 0
        for t in texts:
            starts.append(pos)
            pos += len(t)
        new = [list(t) for t in texts]
        keep = [[True] * len(t) for t in texts]
        insert: dict[tuple[int, int], str] = {}
        for a, b, rep in spans:
            if b <= a:
                continue
            changes += 1
            first = True
            for i, t in enumerate(texts):
                lo, hi = starts[i], starts[i] + len(t)
                if hi <= a or lo >= b:
                    continue
                for k in range(max(a, lo) - lo, min(b, hi) - lo):
                    keep[i][k] = False
                if first:
                    insert[(i, max(a, lo) - lo)] = rep
                    first = False
        for i, m in enumerate(g):
            chars = []
            for k, ch in enumerate(new[i]):
                if (i, k) in insert:
                    chars.append(insert[(i, k)])
                if keep[i][k]:
                    chars.append(ch)
            replace[m.start()] = "".join(chars)
    if not replace:
        return xml, 0
    out, last = [], 0
    for m in _DOCX_TOKEN.finditer(xml):
        if m.group(1) is None or m.start() not in replace:
            continue
        tag = m.group(1)
        if "xml:space" not in tag:
            tag = tag[:-1] + ' xml:space="preserve">'
        out += [xml[last:m.start()], tag, _xml_escape(replace[m.start()]), m.group(3)]
        last = m.end()
    out.append(xml[last:])
    return "".join(out), changes


def docx_rewrite(src: Path, dest: Path, edit: Callable[[str], list[tuple[int, int, str]]],
                 extra: Callable[[str, str], str] | None = None) -> int:
    """A changed copy of a Word file: text parts edited with `edit`; extra(name, xml) may change any
    other XML part (like the author's name). The original is only read."""
    changes = 0
    with zipfile.ZipFile(src) as zin:
        infos = zin.infolist()
        if sum(i.file_size for i in infos) > DOCX_MAX:
            raise ValueError("this Word file unpacks to far more than any real document")
        if "word/document.xml" not in zin.namelist():
            raise ValueError("this isn't a Word document Joe can read")
        tmp = dest.with_name(dest.name + ".part")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
            for info in infos:
                data = zin.read(info.filename)
                if info.filename.endswith(".xml") or info.filename.endswith(".rels"):
                    xml = data.decode("utf-8", "replace")
                    new = xml
                    if DOCX_TEXT_PARTS.match(info.filename):
                        new, n = docx_edit_xml(new, edit)
                        changes += n
                    if extra:
                        new = extra(info.filename, new)
                    if new != xml:
                        data = new.encode("utf-8")
                zout.writestr(info, data)
        tmp.replace(dest)
    return changes


def docx_text(src: Path) -> str:
    """The joined text of a Word file, one paragraph per line (what the edits see)."""
    with zipfile.ZipFile(src) as z:
        if z.getinfo("word/document.xml").file_size > DOCX_MAX:
            raise ValueError("this Word file's text is far too big to read")
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    lines: list[str] = [""]
    for m in _DOCX_TOKEN.finditer(xml):
        if m.group(1) is None:
            if lines[-1]:
                lines.append("")
            continue
        lines[-1] += _xml_text(m.group(2))
    return "\n".join(x for x in lines if x)


# =========================================================================== 1. PDF toolkit (qpdf)
PDF_DOS = (("merge", "Join them into one PDF"), ("split", "Split into pieces"),
           ("pages", "Pick or reorder pages"), ("rotate", "Turn pages"),
           ("compress", "Make it smaller"), ("fill", "Fill in a form"))
QPDF_TIMEOUT = 900


def qpdf_exe(configured: str = "") -> str | None:
    from .finder import qpdf_exe as _q
    return _q(configured)


def _qpdf(exe: str, args: list[str], timeout: int = QPDF_TIMEOUT) -> tuple[bool, str]:
    """Run qpdf; (worked, what it said). Exit 3 = done with warnings (still a good file)."""
    from .system import no_window_flags
    for a in args:                                 # qpdf reads "@file" as more arguments: never pass one
        if a.startswith("@"):
            raise ValueError("refused an argument starting with '@'")
    try:
        p = subprocess.run([exe, *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, creationflags=no_window_flags())
    except subprocess.TimeoutExpired:
        return False, "qpdf took too long (over 15 minutes) and was stopped"
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"couldn't run qpdf: {e}"
    return p.returncode in (0, 3), ((p.stderr or "") + "\n" + (p.stdout or "")).strip()


def _pdf_arg(p: Path) -> str:
    """A file path for qpdf: always absolute, so it can't start with '-' or '@'."""
    s = str(Path(p).resolve())
    if s.startswith(("-", "@")):
        raise ValueError("that file path can't be given to qpdf")
    return s


def pdf_problem(said: str) -> str:
    """qpdf's message in plain words."""
    s = said.lower()
    if "invalid password" in s or "password" in s and "encrypt" in s:
        return ("it's locked with a password. Open it in your PDF reader with the password, save or print "
                "a copy as PDF, and use that copy")
    if any(w in s for w in ("can't find pdf header", "unable to find trailer", "not a pdf", "file is damaged")):
        return "it looks damaged, or isn't really a PDF"
    if "no such file" in s:
        return "the file wasn't found"
    last = [ln for ln in said.splitlines() if ln.strip()]
    return (last[-1][:200] if last else "qpdf couldn't do it").replace("qpdf: ", "")


def pdf_pages(exe: str, src: Path) -> int:
    ok, out = _qpdf(exe, ["--show-npages", _pdf_arg(src)], 120)
    m = re.search(r"^\s*(\d+)\s*$", out, re.M)
    if not ok or not m:
        raise ValueError(pdf_problem(out))
    return int(m.group(1))


def pdf_locked(exe: str, src: Path) -> bool:
    """True when opening it needs a password (exit 0 from --requires-password)."""
    from .system import no_window_flags
    try:
        p = subprocess.run([exe, "--requires-password", _pdf_arg(src)], capture_output=True, timeout=60,
                           creationflags=no_window_flags())
    except (OSError, subprocess.SubprocessError):
        return False
    return p.returncode == 0


_WORDNUM = {"first": "1", "last": "z", "end": "z", "one": "1", "two": "2", "three": "3", "four": "4",
            "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10"}


def parse_pages(text: str, total: int) -> list[int]:
    """'3, 1, 2' / '1-3 and 7' / 'pages 2 to 5' / 'last' / 'odd' -> page numbers (1-based) in that
    order. Raises ValueError in plain words when a page doesn't exist or the words make no sense."""
    t = text.lower().replace("–", "-").replace("—", "-")
    t = re.sub(r"\b(?:pages?|only|just|keep|put|then|in this order|order)\b", " ", t)
    t = re.sub(r"\b(?:to|through|thru|until)\b", "-", t)
    t = re.sub(r"\b(" + "|".join(_WORDNUM) + r")\b", lambda m: _WORDNUM[m.group(1)], t)
    t = re.sub(r"\band\b|&|;", ",", t)
    t = re.sub(r"\s*-\s*", "-", t)
    out: list[int] = []
    for piece in [p.strip() for p in t.split(",")]:
        for bit in piece.split():
            if bit in ("all", "every", "everything"):
                out += list(range(1, total + 1))
                continue
            if bit in ("odd", "even"):
                out += [n for n in range(1, total + 1) if n % 2 == (1 if bit == "odd" else 0)]
                continue
            m = re.fullmatch(r"(\d+|z)(?:-(\d+|z))?", bit)
            if not m:
                raise ValueError(f"'{piece}' isn't a page number (try: 3, 1, 2 or 1-4, 7)")
            a = total if m.group(1) == "z" else int(m.group(1))
            b = a if m.group(2) is None else (total if m.group(2) == "z" else int(m.group(2)))
            for n in (a, b):
                if n < 1 or n > total:
                    raise ValueError(f"page {n} doesn't exist (this PDF has {total} page{'s' if total != 1 else ''})")
            out += list(range(a, b + 1)) if a <= b else list(range(a, b - 1, -1))
    if not out:
        raise ValueError("say which pages, like 3, 1, 2 or 1-4, 7")
    return out


def split_groups(text: str, total: int) -> list[list[int]]:
    """For Split: '' or 'every page' -> one page each; 'every 2' -> pieces of 2;
    '1-3, 4-6' -> those pieces."""
    t = text.lower().strip()
    if not t or re.fullmatch(r"(?:every|each|all)(?: single)?(?: pages?)?|one per page|single pages", t):
        return [[n] for n in range(1, total + 1)]
    m = re.fullmatch(r"(?:every|each|pieces of|chunks of|groups of|in)\s*(\d+)(?:\s*pages?)?", t)
    if m:
        k = max(1, int(m.group(1)))
        return [list(range(a, min(a + k, total + 1))) for a in range(1, total + 1, k)]
    groups = [parse_pages(piece, total) for piece in re.split(r"[;,\n]|\band\b", t) if piece.strip()]
    if not groups:
        raise ValueError("say how to split it, like every page, every 2, or 1-3, 4-6")
    return groups


def _span_name(pages: list[int]) -> str:
    if len(pages) == 1:
        return f"page-{pages[0]}"
    if pages == list(range(pages[0], pages[-1] + 1)):
        return f"pages-{pages[0]}-{pages[-1]}"
    return f"pages-{pages[0]}-and-more"


def _pages_arg(pages: list[int]) -> str:
    return ",".join(str(int(n)) for n in pages)


# ---- forms
_YES = {"yes", "y", "x", "true", "checked", "check", "on", "1", "tick", "ticked", "✓", "✔", "agree"}
_NO = {"no", "n", "false", "unchecked", "off", "0", "none", "blank", "empty", "untick", "unticked"}


def form_fields(exe: str, src: Path) -> list[dict]:
    """The form's fields from qpdf (one entry per box on the page)."""
    ok, out = _qpdf(exe, ["--json=2", "--json-key=acroform", _pdf_arg(src)], 300)
    if not ok:
        raise ValueError(pdf_problem(out))
    try:
        data = json.loads(out[out.find("{"):])
    except json.JSONDecodeError as e:
        raise ValueError("qpdf's list of the form's fields couldn't be read") from e
    return [f for f in (data.get("acroform") or {}).get("fields", []) if isinstance(f, dict)]


def _pdf_str(v) -> str:
    """qpdf JSON v2 strings start u: (text) or b: (hex); names start with /."""
    s = str(v if v is not None else "")
    if s.startswith("u:"):
        return s[2:]
    if s.startswith("b:"):
        try:
            return bytes.fromhex(s[2:]).decode("latin-1")
        except ValueError:
            return ""
    return s


def _field_kind(f: dict) -> str:
    if f.get("ischeckbox"):
        return "check"
    if f.get("isradiobutton"):
        return "radio"
    if f.get("ischoice"):
        return "choice"
    if f.get("istext"):
        return "text"
    return "other"


def _key_norm(s: str) -> str:
    return re.sub(r"[^0-9a-z]+", "", str(s).lower())


def form_listing(src_name: str, fields: list[dict], states: dict[str, list[str]]) -> str:
    """The fill-in sheet: one 'Field name: ' line per field, with what kind of answer it takes."""
    lines = [f"# Form fields in {src_name}", "#",
             "# Fill in after each colon, then paste these lines into the box on the Fill in a form tool",
             "# and run it again. A line left empty leaves that field empty. Tick boxes: yes or no.",
             "# Pick lists: one of the choices shown. Lines starting with # are skipped.", ""]
    seen: set[str] = set()
    for f in fields:
        name = " ".join(str(f.get("fullname") or "").split())        # a name from the PDF: one line only
        if not name or name in seen:
            continue
        seen.add(name)
        kind = _field_kind(f)
        hint = {"check": " (tick box: yes or no)",
                "radio": " (pick one: " + ", ".join(states.get(name, [])) + ")",
                "choice": " (pick one: " + ", ".join(str(c) for c in f.get("choices") or []) + ")"
                if f.get("choices") else "",
                "other": " (a signature or button: Joe can't fill this one)"}.get(kind, "")
        now = _pdf_str(f.get("value"))
        now = "" if kind in ("check", "radio") or now.startswith("/") else now
        alt = " ".join(str(f.get("alternativename") or "").split())
        about = f"   [{alt}]" if alt and _key_norm(alt) != _key_norm(name) and len(alt) < 120 else ""
        lines.append(f"{name}{hint}: {now}{about}")
    return "\n".join(lines) + "\n"


def parse_answers(text: str) -> dict[str, str]:
    """'Full name: Jane Smith' lines -> {name: value}. A hint in (...) after the name (it may have its own
    colon) and a [note] after the answer are dropped, so the fill-in sheet can be pasted back as it is.
    Empty answers and lines starting with # are left out."""
    out: dict[str, str] = {}
    for line in re.split(r"\n| \| ", text or ""):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([^:=(]+?)\s*\([^)]*\)\s*[:=]\s*(.*)$", line) or re.match(r"^([^:=]+?)\s*[:=]\s*(.*)$", line)
        if not m:
            continue
        name = m.group(1).strip()
        value = re.sub(r"\s+\[[^\]]*\]\s*$", "", m.group(2)).strip()
        if name and value:
            out[name] = value
    return out


def _obj_id(ref: str) -> tuple[int, int] | None:
    m = re.fullmatch(r"\s*(\d+) (\d+) R\s*", str(ref or ""))
    return (int(m.group(1)), int(m.group(2))) if m else None


def _objects(exe: str, src: Path, ids: list[tuple[int, int]]) -> tuple[dict, dict]:
    """(qpdf's header block, {"obj:N G R": {"value": {...}}}) for these objects."""
    args = ["--json=2", "--json-key=qpdf"] + [f"--json-object={a},{b}" for a, b in ids] + [_pdf_arg(src)]
    ok, out = _qpdf(exe, args, 300)
    if not ok:
        raise ValueError(pdf_problem(out))
    data = json.loads(out[out.find("{"):])
    head, objs = data["qpdf"][0], data["qpdf"][1]
    return head, objs


def fill_form(exe: str, src: Path, dest: Path, answers: dict[str, str], tmp: Path,
              lock: bool = False) -> tuple[list[str], list[str]]:
    """Fill a PDF form into a new file. Returns (filled field names, problems in plain words)."""
    fields = form_fields(exe, src)
    if not fields:
        raise ValueError("this PDF has no fill-in boxes (it may be a scan or a flat form): print it, or "
                         "type your answers with Hide personal details / your own PDF reader instead")
    by_key: dict[str, list[dict]] = {}
    for f in fields:
        for k in {_key_norm(f.get("fullname")), _key_norm(f.get("partialname")), _key_norm(f.get("alternativename"))}:
            if k:
                by_key.setdefault(k, []).append(f)
    ids: set[tuple[int, int]] = set()
    plan: list[tuple[str, str, list[dict]]] = []
    problems: list[str] = []
    for name, value in answers.items():
        hits = by_key.get(_key_norm(name), [])
        if not hits:
            problems.append(f"'{name}': no field with that name (see the form-fields list for the exact names)")
            continue
        real = hits[0].get("fullname") or name
        same = [f for f in fields if f.get("fullname") == real] or hits
        plan.append((real, value, same))
        for f in same:
            for ref in (f.get("object"), (f.get("annotation") or {}).get("object")):
                if _obj_id(ref):
                    ids.add(_obj_id(ref))
    if not plan:
        return [], problems
    head, objs = _objects(exe, src, sorted(ids))

    def val(ref) -> dict | None:
        o = objs.get(f"obj:{ref.strip()}") if ref else None
        return o.get("value") if isinstance(o, dict) and isinstance(o.get("value"), dict) else None

    changed: dict[str, dict] = {}
    filled: list[str] = []
    for real, value, same in plan:
        kind = _field_kind(same[0])
        field_ref = same[0].get("object")
        fv = val(field_ref)
        if fv is None:
            problems.append(f"'{real}': qpdf couldn't open this field")
            continue
        if kind == "text":
            if any(ord(c) > 255 for c in value):
                problems.append(f"'{real}': letters outside the basic Latin set may not show in every PDF "
                                "reader [CHECK]")
            fv["/V"] = "u:" + value
            changed[field_ref] = fv
        elif kind == "choice":
            choices = [str(c) for c in same[0].get("choices") or []]
            pick = next((c for c in choices if _norm(c) == _norm(value)), None)
            editable = int(same[0].get("fieldflags") or 0) & 262144
            if choices and pick is None and not editable:
                problems.append(f"'{real}': '{value}' isn't one of its choices ({', '.join(choices)})")
                continue
            fv["/V"] = "u:" + (pick or value)
            changed[field_ref] = fv
        elif kind in ("check", "radio"):
            v = _norm(value)
            ons: list[tuple[str, dict]] = []
            for f in same:
                aref = (f.get("annotation") or {}).get("object") or field_ref
                av = val(aref)
                if av is None:
                    continue
                normal = ((av.get("/AP") or {}).get("/N") or {}) if isinstance(av.get("/AP"), dict) else {}
                states = [k for k in normal if k != "/Off"] if isinstance(normal, dict) else []
                ons.append((aref, av, states))
            if kind == "check":
                if v in _NO:
                    want = "/Off"
                elif v in _YES:
                    want = next((s for _, _, sts in ons for s in sts), "/Yes")
                else:
                    problems.append(f"'{real}': a tick box takes yes or no, not '{value}'")
                    continue
            else:
                all_states = [s for _, _, sts in ons for s in sts]
                want = next((s for s in all_states if _key_norm(s[1:]) == _key_norm(value)), None)
                if v in _NO:
                    want = "/Off"
                if want is None:
                    problems.append(f"'{real}': '{value}' isn't one of its choices "
                                    f"({', '.join(s[1:] for s in all_states)})")
                    continue
            fv["/V"] = want
            changed[field_ref] = fv
            for aref, av, sts in ons:
                av["/AS"] = want if want in sts else "/Off"
                changed[aref] = av
        else:
            problems.append(f"'{real}': Joe can't fill signature boxes or buttons")
            continue
        filled.append(real)
    if not filled:
        return [], problems
    upd = {"version": 2, "qpdf": [head, {f"obj:{r.strip()}": {"value": v} for r, v in changed.items()}]}
    tmp.parent.mkdir(parents=True, exist_ok=True)
    try:
        tmp.write_text(json.dumps(upd), encoding="utf-8")
        args = [_pdf_arg(src), _pdf_arg(dest), "--update-from-json=" + _pdf_arg(tmp), "--generate-appearances"]
        if lock:
            args.append("--flatten-annotations=all")
        ok, out = _qpdf(exe, args)
    finally:
        try:
            tmp.unlink()                          # it holds the person's answers: never left behind
        except OSError:
            pass
    if not ok:
        raise ValueError(pdf_problem(out))
    return filled, problems


def _radio_states(exe: str, src: Path, fields: list[dict]) -> dict[str, list[str]]:
    radios = [f for f in fields if f.get("isradiobutton")]
    ids = sorted({_obj_id((f.get("annotation") or {}).get("object")) for f in radios} - {None})
    if not ids:
        return {}
    try:
        _, objs = _objects(exe, src, ids)
    except (ValueError, KeyError, json.JSONDecodeError):
        return {}
    out: dict[str, list[str]] = {}
    for f in radios:
        o = (objs.get(f"obj:{(f.get('annotation') or {}).get('object', '').strip()}") or {}).get("value") or {}
        normal = ((o.get("/AP") or {}).get("/N") or {}) if isinstance(o.get("/AP"), dict) else {}
        for k in normal if isinstance(normal, dict) else {}:
            if k != "/Off" and k[1:] not in out.setdefault(f.get("fullname", ""), []):
                out[f["fullname"]].append(k[1:])
    return out


def _mb(n: int) -> str:
    return f"{n / 1e6:.1f} MB" if n >= 100_000 else f"{max(1, round(n / 1000))} KB"


def run_pdf_tools(engine: "Engine", mission: "Mission", job: "Job", st: "JobState") -> "JobState":
    from .engine import Stopped
    from .tools import _finish, _key, option_value, chosen_options, unique_stem
    exe = qpdf_exe(getattr(engine.s, "qpdf", ""))
    if not exe:
        return _fail(engine, job, st, "the PDF toolkit needs qpdf, a free program (Apache license). "
                     "Setup (F10) > System check > \"qpdf\" installs it")
    got = _begin(engine, job, st, "PDF files")
    if not isinstance(got, tuple):
        return got
    files, folder = got
    do = option_value(job, "do") or "merge"
    words = job.format.strip()
    report = [f"# PDF toolkit: {dict(PDF_DOS).get(do, do)}", ""]
    failed: list[str] = []

    def ok_to_open(src: Path) -> bool:
        if pdf_locked(exe, src):
            failed.append(f"{src.name}: {pdf_problem('invalid password')}")
            engine.log(f"  {src.name}: locked with a password")
            return False
        return True

    try:
        if do == "merge":
            if len(files) < 2:
                return _fail(engine, job, st, "joining needs two or more PDFs (drop them in the order you want)")
            if not st.titles:
                usable = [f for f in files if ok_to_open(f)]
                if len(usable) < 2:
                    return _finish(engine, job, st, 1, failed)
                out = folder / "joined.pdf"
                ok, said = _qpdf(exe, ["--empty", "--pages", *[_pdf_arg(f) for f in usable], "--", _pdf_arg(out)])
                if not ok:
                    failed.append(f"joining: {pdf_problem(said)}")
                else:
                    n = pdf_pages(exe, out)
                    report += [f"Joined {len(usable)} PDFs into joined.pdf ({n} pages), in this order:", ""]
                    report += [f"{i}. {f.name}" for i, f in enumerate(usable, 1)]
                    st.media_files.append("joined.pdf")
                    st.titles.append("joined")
                    st.items += 1
            total = 1
        else:
            total = len(files)
            opts = chosen_options(job)
            for i, src in enumerate(files):
                key = _key(engine, src)
                if key in st.titles:
                    continue
                if engine.stop.is_set():
                    raise Stopped()
                engine._progress(f"{job.name}: {i + 1}/{len(files)} {src.name}")
                stem = unique_stem(files, i)
                if not ok_to_open(src):
                    continue
                try:
                    made = _pdf_one(engine, exe, do, src, stem, folder, words, option_value, job, opts, report, st)
                except ValueError as e:
                    failed.append(f"{src.name}: {e}"[:300])
                    engine.log(f"  {src.name}: {e}")
                    continue
                st.media_files.extend(m for m in made if m not in st.media_files)
                st.titles.append(key)
                st.items += 1
                engine._save_state(job, st)
                engine.log(f"  {src.name} -> {', '.join(made) if made else 'nothing new'}")
    except Stopped:
        return _stopped(engine, job, st, len(files))
    if failed:
        report += ["", "## Not done", ""] + [f"- {x}" for x in failed]
    atomic_write_text(folder / "pdf-report.md", "\n".join(report) + "\n")
    if "pdf-report.md" not in st.media_files:
        st.media_files.append("pdf-report.md")
    return _finish(engine, job, st, total, failed)


def _pdf_one(engine, exe, do, src, stem, folder, words, option_value, job, opts, report, st) -> list[str]:
    total = pdf_pages(exe, src)
    made: list[str] = []
    if do == "split":
        groups = split_groups(words, total)
        if len(groups) > 2000:
            raise ValueError("that would make over 2000 files: split it into bigger pieces")
        sub = folder / stem
        sub.mkdir(exist_ok=True)
        for g in groups:
            name = f"{stem}-{_span_name(g)}.pdf"
            ok, said = _qpdf(exe, ["--empty", "--pages", _pdf_arg(src), _pages_arg(g), "--", _pdf_arg(sub / name)])
            if not ok:
                raise ValueError(pdf_problem(said))
            made.append(f"{stem}/{name}")
        report += [f"- {src.name} ({total} pages): split into {len(groups)} file(s) in the {stem} folder"]
    elif do == "pages":
        if not words:
            raise ValueError("say which pages, in the order you want them (like 3, 1, 2 or 1-4, 7), in the box")
        pages = parse_pages(words, total)
        name = f"{stem}-pages.pdf"
        ok, said = _qpdf(exe, ["--empty", "--pages", _pdf_arg(src), _pages_arg(pages), "--", _pdf_arg(folder / name)])
        if not ok:
            raise ValueError(pdf_problem(said))
        made.append(name)
        shown = ", ".join(map(str, pages[:40])) + (" ..." if len(pages) > 40 else "")
        report += [f"- {src.name} ({total} pages) -> {name}: pages {shown}"]
    elif do == "rotate":
        turn = {"right": "+90", "left": "-90", "upside": "+180"}.get(option_value(job, "turn") or "right", "+90")
        pages = parse_pages(words, total) if words else list(range(1, total + 1))
        name = f"{stem}-turned.pdf"
        ok, said = _qpdf(exe, [_pdf_arg(src), _pdf_arg(folder / name), f"--rotate={turn}:{_pages_arg(sorted(set(pages)))}"])
        if not ok:
            raise ValueError(pdf_problem(said))
        made.append(name)
        report += [f"- {src.name} -> {name}: {len(set(pages))} page(s) turned"]
    elif do == "compress":
        name = f"{stem}-smaller.pdf"
        args = [_pdf_arg(src), _pdf_arg(folder / name), "--object-streams=generate", "--compress-streams=y",
                "--recompress-flate", "--compression-level=9", "--remove-unreferenced-resources=yes"]
        if (option_value(job, "shrink") or "safe") == "smaller":
            args.append("--optimize-images")
        ok, said = _qpdf(exe, args)
        if not ok:
            raise ValueError(pdf_problem(said))
        before, after = src.stat().st_size, (folder / name).stat().st_size
        if after >= before:
            (folder / name).unlink()
            report += [f"- {src.name} ({_mb(before)}): already as small as qpdf can make it"
                       + ("" if (option_value(job, "shrink") or "safe") == "smaller"
                          else ". Try How small: Smaller (re-saves photos) for scanned pages")]
        else:
            made.append(name)
            report += [f"- {src.name}: {_mb(before)} -> {_mb(after)} ({round(100 - after * 100 / before)}% smaller) = {name}"]
    elif do == "fill":
        answers = parse_answers(words)
        fields = form_fields(exe, src)
        if not fields:
            raise ValueError("this PDF has no fill-in boxes (it may be a scan or a flat form)")
        listing = f"{stem}-form-fields.txt"
        atomic_write_text(folder / listing, form_listing(src.name, fields, _radio_states(exe, src, fields)))
        made.append(listing)
        if not answers:
            report += [f"- {src.name}: {len({f.get('fullname') for f in fields})} fields. Open {listing}, fill in "
                       "after each colon, paste the lines into the box and run Fill in a form again"]
            return made
        name = f"{stem}-filled.pdf"
        filled, problems = fill_form(exe, src, folder / name, answers, engine.meta / "tmp" / f"form-answers-{job.job_id}.json",
                                     lock="lock" in opts)
        if filled:
            made.insert(0, name)
        report += [f"- {src.name} -> {name if filled else 'nothing filled'}: {len(filled)} field(s) filled"
                   + (" and locked" if filled and "lock" in opts else "")]
        report += [f"  - {p}" for p in problems]
        st.flags.extend({"item": src.name, "flag": "[CHECK] " + p} for p in problems[:20])
        if not filled:
            raise ValueError("no fields could be filled: " + "; ".join(problems[:3]))
    else:
        raise ValueError(f"unknown choice '{do}'")
    return made


# =========================================================================== 2. Explain this letter
LETTER_SYSTEM = ("You help people understand letters they got: bills, leases, insurance, benefits, tax, bank, "
                 "school, medical, court and job letters. Use only what the letter says. Never invent dates, "
                 "amounts, names, phone numbers, rules or rights. You are not a lawyer or financial adviser and "
                 "never say what the law is beyond what the letter itself says.")
LETTER_FACTS = """Today is {today}. Read the letter between <<< and >>>. Reply with ONLY JSON:
{{"from": "who sent it", "about": "one plain sentence: what it's about",
"deadlines": [{{"what": "what must happen by then", "date": "YYYY-MM-DD or empty", "as_written": "the date exactly as the letter writes it"}}],
"amounts": [{{"what": "what the money is for", "amount": "exactly as written"}}],
"contacts": [{{"how": "phone, email, website or address", "detail": "exactly as written"}}],
"references": ["account, case, policy or reference numbers exactly as written"],
"scam_signs": ["only real warning signs in the letter: gift cards, crypto, wire transfers, threats of arrest, a link to log in, pay today or else; empty list if none"]}}
<<<
{text}
>>>"""
LETTER_EXPLAIN = """Explain the letter between <<< and >>> to the person who got it, in plain, kind words anyone
can follow (short sentences, everyday words, explain any jargon in brackets).{wish}
Write exactly these Markdown sections:
## What this letter is
2-3 sentences.
## What it means for you
Short paragraphs or bullets. Keep every amount, date and number exactly as written.
## What to do next
Numbered steps, most urgent first. If the letter asks for nothing, say so.
## Questions you could ask them
2-5 bullets.
Mark anything unclear [CHECK]. Don't list every date and amount again (Joe lists those himself).
<<<
{text}
>>>"""
LETTER_REPLY = """Write a short, polite reply the person could send to whoever wrote the letter between <<< and >>>.
{wish}Put anything you don't know in square brackets for the person to fill in: [YOUR NAME], [YOUR ADDRESS],
[DATE], [YOUR PHONE]. Quote the letter's reference number exactly if it has one. Never agree to pay, admit
anything, or give up any right unless the person's note says so. Plain text, no Markdown.
<<<
{text}
>>>"""
LETTER_MAX_WORDS = 9000


def _letter_date(v) -> date | None:
    try:
        return datetime.strptime(str(v or "").strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def days_left(d: date, today: date) -> str:
    n = (d - today).days
    if n < 0:
        return f"{-n} day{'s' if n != -1 else ''} ago [CHECK]"
    if n == 0:
        return "today"
    return f"{n} day{'s' if n != 1 else ''}"


def letter_facts_md(facts: dict, letter: str, today: date) -> tuple[str, list[dict]]:
    """Joe's own part of the explanation: dates, money, contacts and numbers, each checked against
    the letter (not found word for word = [CHECK]). Also returns the deadlines for a calendar file."""
    out: list[str] = []
    events: list[dict] = []

    def checked(s) -> str:
        s = " ".join(str(s or "").split())
        return s if not s or found_in(s, letter) else f"{s} [CHECK]"

    signs = [str(x).strip() for x in facts.get("scam_signs") or [] if str(x).strip()]
    if signs:
        out += ["## Be careful: this might be a scam", "",
                "Some things in this letter are common signs of a scam:", ""] + [f"- {s}" for s in signs[:6]]
        out += ["", "Don't pay, click links or call numbers from the letter until you've checked with the company "
                "or office using a phone number or website you find yourself (on your card, a bill or their "
                "official site).", ""]
    rows = []
    for d in facts.get("deadlines") or []:
        if not isinstance(d, dict) or not (d.get("what") or d.get("as_written")):
            continue
        when = _letter_date(d.get("date"))
        written = checked(d.get("as_written") or d.get("date") or "")
        sure = when and written and "[CHECK]" not in written
        rows.append([str(d.get("what") or "").strip(), written or "[CHECK]",
                     days_left(when, today) if sure else ("[CHECK]" if when else "")])
        if when:
            events.append({"title": "Deadline: " + str(d.get("what") or "letter")[:80], "date": when.isoformat(),
                           "sure": bool(sure)})
    if rows:
        out += ["## Dates and deadlines", "", _table(["What", "When (as the letter says)", "Time left"], rows), ""]
    money = [[str(a.get("what") or "").strip(), checked(a.get("amount"))]
             for a in facts.get("amounts") or [] if isinstance(a, dict) and str(a.get("amount") or "").strip()]
    if money:
        out += ["## Money", "", _table(["What for", "Amount"], money), ""]
    contacts = [[str(c.get("how") or "").strip(), checked(c.get("detail"))]
                for c in facts.get("contacts") or [] if isinstance(c, dict) and str(c.get("detail") or "").strip()]
    if contacts:
        out += ["## Who to contact", "", _table(["How", "Details"], contacts), ""]
    refs = [checked(r) for r in facts.get("references") or [] if str(r).strip()]
    if refs:
        out += ["## Reference numbers (have these ready when you call or write)", ""] + [f"- {r}" for r in refs[:10]] + [""]
    return "\n".join(out), events


def _letter_text(engine: "Engine", job: "Job", st: "JobState", src: Path, i: int) -> str:
    """The letter's words: read from the document, or copied off a photo by the vision model."""
    from .tools import PHOTO_EXT, SCAN_ASK, SCAN_SYSTEM, _look, find_vision_model, picture_b64
    if src.suffix.lower() not in PHOTO_EXT:
        return _read_doc(engine, src)
    model = find_vision_model(engine)
    if not model:
        raise ValueError("reading a photo of a letter needs a vision model (Setup > System check offers a "
                         "free one), or type or scan it to a document")
    from .doctor import ffmpeg_exe
    img = picture_b64(ffmpeg_exe(engine.s.comfy.ffmpeg), src, engine.meta / "tmp" / f"look-{job.job_id}.jpg", 2000)
    o = _look(engine, job, st, i, "read-scans", SCAN_SYSTEM, SCAN_ASK["text"].format(name=src.name), img, model)
    text = str((o or {}).get("text") or "").strip()
    if not text:
        raise ValueError("the vision model couldn't read the words in that photo")
    return text


def run_explain_letter(engine: "Engine", mission: "Mission", job: "Job", st: "JobState") -> "JobState":
    from .engine import PartFailed, Stopped
    from .filetools import build_ics
    from .tools import _finish, _key, chosen_options, unique_stem
    got = _begin(engine, job, st, "letters to explain", need_text=True)
    if not isinstance(got, tuple):
        return got
    files, folder = got
    ask = _asker(engine, job, st)
    opts = chosen_options(job)
    model = _model(engine)
    today = date.today()
    wish = f"\nThe person says: {job.format.strip()}" if job.format.strip() else ""
    failed: list[str] = []
    try:
        for i, src in enumerate(files):
            key = _key(engine, src)
            if key in st.titles:
                continue
            engine._progress(f"{job.name}: {i + 1}/{len(files)} {src.name}")
            stem = unique_stem(files, i)
            try:
                letter = _letter_text(engine, job, st, src, i)
                cut = ""
                words = letter.split()
                if len(words) > LETTER_MAX_WORDS:
                    letter = " ".join(words[:LETTER_MAX_WORDS])
                    cut = f" Only the first {LETTER_MAX_WORDS} words were read: it's very long."
                facts = _ask_json(ask, "letter", LETTER_SYSTEM + " Reply with ONLY JSON.",
                                  LETTER_FACTS.format(today=today.isoformat(), text=letter))
                if not isinstance(facts, dict):
                    facts = {}
                explained = ask("letter", LETTER_SYSTEM + " Markdown.",
                                LETTER_EXPLAIN.format(wish=wish, text=letter), 40)
                reply = ask("letter", LETTER_SYSTEM, LETTER_REPLY.format(
                    wish=(f"The person's note on what they want to say: {job.format.strip()}\n" if job.format.strip() else ""),
                    text=letter), 40) if "reply" in opts else ""
            except (ValueError, OSError, PartFailed) as e:
                failed.append(f"{src.name}: {e}"[:200])
                engine.log(f"  {src.name}: {e}")
                continue
            own, events = letter_facts_md(facts, letter, today)
            head = [f"# {src.stem}: in plain words", ""]
            if facts.get("from") or facts.get("about"):
                head += [f"**From:** {' '.join(str(facts.get('from') or '[CHECK]').split())}  ",
                         f"**About:** {' '.join(str(facts.get('about') or '').split())}", ""]
            body = (_ai_note("Explained", model, "This isn't legal or money advice: for anything serious, call the "
                             "number on the letter or a free advice service." + cut)
                    + "\n".join(head) + "\n" + own + "\n" + explained.strip() + "\n")
            made = [f"{stem}-explained.md"]
            if reply:
                body += "\n## A reply you could send\n\nFill in the [brackets] and read it through before sending.\n\n" \
                        + "\n".join("    " + ln if ln.strip() else "" for ln in reply.strip().splitlines()) + "\n"
            _save(folder, st, f"{stem}-explained.md", body, src.name)
            if reply:
                atomic_write_text(folder / f"{stem}-reply.txt", reply.strip() + "\n")
                st.media_files.append(f"{stem}-reply.txt")
                made.append(f"{stem}-reply.txt")
            if "calendar" in opts and events:
                ics, _ = build_ics(events, [])
                atomic_write_text(folder / f"{stem}-deadlines.ics", ics)
                st.media_files.append(f"{stem}-deadlines.ics")
                made.append(f"{stem}-deadlines.ics")
            st.titles.append(key)
            st.items += 1
            engine._save_state(job, st)
            engine.log(f"  {src.name} -> {', '.join(made)}")
    except Stopped:
        return _stopped(engine, job, st, len(files), "letter(s)")
    return _finish(engine, job, st, len(files), failed)


# =========================================================================== 3. Hide personal details
HIDE_KINDS = {"email": "EMAIL", "phone": "PHONE", "card": "CARD NUMBER", "ssn": "ID NUMBER", "iban": "BANK ACCOUNT",
              "number": "NUMBER", "address": "ADDRESS", "birth": "DATE OF BIRTH", "name": "NAME",
              "detail": "DETAIL", "yours": "HIDDEN"}
_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
# (spaces and tabs between the groups, never a line break: "62701\n123 Broadway" isn't a phone number)
_PHONE = re.compile(r"(?<![\w+])(?:\+\d{1,3}[ \t .-]?)?(?:\(\d{2,5}\)[ \t .-]?)?\d{2,5}(?:[ \t .-]\d{2,5}){1,4}(?![\w])")
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
_SSN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b")
_LONGNUM = re.compile(r"(?<![\w.,$£€])\d(?:[ -]?\d){7,}(?!\w|[.,]\d)")
_KEYNUM = re.compile(r"(?i)\b(?:account|acct|a/c|policy|member|customer|client|reference|ref|routing|sort code|"
                     r"license|licence|passport|patient|case|claim|id|ssn|nin|tax|employee|badge)\b(?:\s*(?:no\.?|number|#|id))?"
                     r"\s*[:#]?\s*([A-Z0-9][A-Z0-9-]{3,}\d[A-Z0-9-]*)")
_STREET = re.compile(r"\b\d{1,6}[A-Za-z]?\s+(?:[A-Z][\w'.-]*\s+){1,4}(?:Street|St|Avenue|Ave|Road|Rd|Lane|Ln|Drive|Dr|"
                     r"Court|Ct|Boulevard|Blvd|Way|Place|Pl|Terrace|Ter|Circle|Cir|Highway|Hwy|Parkway|Pkwy|Close|"
                     r"Crescent|Cres|Square|Sq|Trail|Trl)\b\.?(?:,?\s+(?:Apt|Apartment|Unit|Suite|Ste|Flat|#)\.?\s*[\w-]+)?")
_STREET_WORDS = ("Street|St|Avenue|Ave|Road|Rd|Lane|Ln|Drive|Dr|Court|Ct|Boulevard|Blvd|Way|Place|Pl|Terrace|Ter|"
                 "Circle|Cir|Highway|Hwy|Parkway|Pkwy|Close|Crescent|Cres|Square|Sq|Trail|Trl")
# the same in CAPITALS, as bills and bank statements print them ("1234 MAPLE STREET APT 4")
_STREET_CAPS = re.compile(r"\b\d{1,6}[A-Z]?[ \t]+(?:[A-Z][A-Z'.-]*[ \t]+){1,4}(?:" + _STREET_WORDS.upper() + r")\b\.?"
                          r"(?:,?[ \t]+(?:APT|APARTMENT|UNIT|SUITE|STE|FLAT|#)\.?[ \t]*[\w-]+)?")
_POBOX = re.compile(r"(?i)\bP\.?[ \t]?O\.?[ \t]*Box[ \t]+\d+\b")
_US_STATES = ("AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|"
              "ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|PR")
# the town line of a US address: "Battle Creek, MI 49017" / "BATTLE CREEK MI 49017-1234"
_CITYZIP = re.compile(r"\b[A-Z][A-Za-z.'-]+(?:[ \t]+[A-Z][A-Za-z.'-]+){0,3},?[ \t]+(?:" + _US_STATES + r")[ \t]+\d{5}(?:-\d{4})?\b")
_UK_POST = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?[ \t]?\d[A-Z]{2}\b")
_BIRTH = re.compile(r"(?i)\b(?:d\.?o\.?b\.?|date of birth|birth ?date|born(?: on)?)\s*[:\-]?\s*"
                    r"(\d{1,4}[/.-]\d{1,2}[/.-]\d{1,4}|\w+ \d{1,2},? \d{4}|\d{1,2} \w+ \d{4})")
_DATEISH = re.compile(r"\d{4}-\d{1,2}-\d{1,2}|\d{1,2}-\d{1,2}-\d{2,4}|(?:19|20)\d{6}")
HIDE_SYSTEM = ("You find personal details in a document so they can be hidden before it's shared. List only "
               "words that are really in the text, copied exactly as written. Reply with ONLY JSON.")
HIDE_ASK = """List the personal details in the text between <<< and >>>: people's names (every form used:
full name, first name alone, Mr./Ms. + surname), home and street addresses, dates of birth, and other details
that identify a private person (ID numbers, licence plates, usernames). Not companies, government offices,
public places or famous people unless they're clearly a private person here.
Reply with ONLY JSON: {{"items": [{{"text": "exactly as written", "kind": "name|address|birth|detail"}}]}}
<<<
{text}
>>>"""
HIDE_CHUNK_WORDS = 1500
_COMMON = {"the", "and", "you", "your", "dear", "sir", "madam", "mr", "mrs", "ms", "dr", "yes", "no", "date", "name"}


def luhn_ok(digits: str) -> bool:
    d = [int(c) for c in digits if c.isdigit()]
    if not 13 <= len(d) <= 19:
        return False
    total = 0
    for i, n in enumerate(reversed(d)):
        if i % 2:
            n *= 2
            n -= 9 if n > 9 else 0
        total += n
    return total % 10 == 0


def pattern_hits(text: str) -> list[tuple[int, int, str]]:
    """Joe's own finds (no AI): (start, end, kind)."""
    hits: list[tuple[int, int, str]] = []
    hits += [(m.start(), m.end(), "email") for m in _EMAIL.finditer(text)]
    hits += [(m.start(), m.end(), "ssn") for m in _SSN.finditer(text)]
    hits += [(m.start(), m.end(), "card") for m in _CARD.finditer(text) if luhn_ok(m.group())]
    hits += [(m.start(), m.end(), "iban") for m in _IBAN.finditer(text)]
    hits += [(m.start(1), m.end(1), "birth") for m in _BIRTH.finditer(text)]
    for rx in (_STREET, _STREET_CAPS, _POBOX, _CITYZIP, _UK_POST):
        hits += [(m.start(), m.end(), "address") for m in rx.finditer(text)]
    hits += [(m.start(1), m.end(1), "number") for m in _KEYNUM.finditer(text)
             if sum(c.isdigit() for c in m.group(1)) >= 4]
    for m in _PHONE.finditer(text):
        digits = sum(c.isdigit() for c in m.group())
        g = m.group()
        if not 7 <= digits <= 15 or re.fullmatch(r"\d{4}-\d{2}-\d{2}", g) or re.fullmatch(r"(?:19|20)\d\d", g):
            continue
        if re.fullmatch(r"\d{1,3}(?:,\d{3})+|\d+\.\d{1,2}", g):          # money, not a phone
            continue
        hits.append((m.start(), m.end(), "phone"))
    hits += [(m.start(), m.end(), "number") for m in _LONGNUM.finditer(text) if not _DATEISH.fullmatch(m.group())]
    return hits


def hide_spans(text: str, finds: list[tuple[int, int, str]], keep: list[str]) -> list[tuple[int, int, str]]:
    """Overlaps sorted out (earliest, then longest wins); anything inside a 'keep' phrase stays."""
    kept: list[tuple[int, int]] = []
    low = text.lower()
    for k in keep:
        k = k.lower().strip()
        if k:
            kept += [(m.start(), m.end()) for m in re.finditer(re.escape(k), low)]
    out: list[tuple[int, int, str]] = []
    end = -1
    for a, b, kind in sorted(finds, key=lambda h: (h[0], -(h[1] - h[0]))):
        if a < end or b <= a or any(ka <= a and b <= kb for ka, kb in kept):
            continue
        out.append((a, b, kind))
        end = b
    return out


def find_words(text: str, words: list[tuple[str, str]]) -> list[tuple[int, int, str]]:
    """Every place each (word, kind) appears, as a whole word, in any letter case."""
    out = []
    for w, kind in words:
        w = w.strip()
        if len(w) < 2:
            continue
        rx = re.compile(r"(?<!\w)" + re.escape(w).replace(r"\ ", r"\s+") + r"(?!\w)", re.I)
        out += [(m.start(), m.end(), kind) for m in rx.finditer(text)]
    return out


class Labeler:
    """[NAME 1], [NAME 2]...: the same detail always gets the same label, so the shared copy still
    makes sense ('[NAME 1] called [NAME 2]'). blocks=True gives ██████ instead."""

    def __init__(self, blocks: bool = False):
        self.blocks = blocks
        self.seen: dict[tuple[str, str], str] = {}
        self.count: dict[str, int] = {}
        self.key: list[tuple[str, str]] = []

    def __call__(self, original: str, kind: str) -> str:
        if self.blocks:
            self.count[kind] = self.count.get(kind, 0) + 1
            return "██████"
        label = HIDE_KINDS.get(kind, "DETAIL")
        k = (label, _norm(original))
        if k not in self.seen:
            self.count[kind] = self.count.get(kind, 0) + 1
            n = sum(1 for (lab, _) in self.seen if lab == label) + 1
            self.seen[k] = f"[{label} {n}]" if label not in ("CARD NUMBER", "DATE OF BIRTH") else f"[{label}]"
            self.key.append((self.seen[k], original))
        return self.seen[k]


def box_words(text: str) -> tuple[list[str], list[str]]:
    """The box: 'keep: Acme Bakery' lines are never hidden; every other line (or ';' piece) is."""
    hide, keep = [], []
    for piece in re.split(r"[\n;|]", text or ""):
        p = piece.strip()
        if not p:
            continue
        m = re.match(r"(?i)^(keep|don't hide|do not hide|leave)\s*[:\-]\s*(.+)$", p)
        if m:
            keep.append(m.group(2).strip())
            continue
        p = re.sub(r"(?i)^(?:also )?(?:hide|remove|black out)\s*[:\-]?\s*", "", p).strip()
        if p:
            hide.append(p)
    return hide, keep


def _ai_details(ask, text: str) -> list[tuple[str, str]]:
    """The writing model's finds, kept only when the exact words are really in the text."""
    words = text.split()
    out: list[tuple[str, str]] = []
    for a in range(0, len(words), HIDE_CHUNK_WORDS):
        piece = " ".join(words[a:a + HIDE_CHUNK_WORDS])
        got = _ask_json(ask, "hide-details", HIDE_SYSTEM, HIDE_ASK.format(text=piece))
        items = got.get("items") if isinstance(got, dict) else got if isinstance(got, list) else []
        for it in items or []:
            if not isinstance(it, dict):
                continue
            w = " ".join(str(it.get("text") or "").split())
            kind = str(it.get("kind") or "detail").lower()
            if len(w) < 2 or w.lower() in _COMMON or not found_in(w, piece):
                continue                                 # not really there: never hidden on a guess
            out.append((w, kind if kind in HIDE_KINDS else "detail"))
    return out


def run_hide_details(engine: "Engine", mission: "Mission", job: "Job", st: "JobState") -> "JobState":
    from .engine import PartFailed, Stopped
    from .tools import _finish, _key, chosen_options, option_value, unique_stem
    opts = chosen_options(job)
    use_ai = "names" in opts
    got = _begin(engine, job, st, "documents to clean", need_text=use_ai)
    if not isinstance(got, tuple):
        return got
    files, folder = got
    ask = _asker(engine, job, st) if use_ai else None
    hide, keep = box_words(job.format)
    blocks = (option_value(job, "style") or "labels") == "blocks"
    report = ["# Hide personal details", "",
              "Joe looked for names, addresses, phone numbers, emails, card and account numbers and other "
              "personal details, and made cleaned copies. **Joe can miss things (and AI can be wrong): read "
              "each copy before you share it.** Your originals weren't changed.", ""]
    key_lines: list[str] = []
    failed: list[str] = []
    try:
        for i, src in enumerate(files):
            key = _key(engine, src)
            if key in st.titles:
                continue
            if engine.stop.is_set():
                raise Stopped()
            engine._progress(f"{job.name}: {i + 1}/{len(files)} {src.name}")
            stem = unique_stem(files, i)
            ext = src.suffix.lower()
            label = Labeler(blocks)
            try:
                if ext == ".docx":
                    text = docx_text(src)
                elif ext in (".csv", ".txt", ".md", ".markdown"):          # exactly as written
                    raw = src.read_bytes()
                    if b"\x00" in raw[:4096]:
                        raise ValueError("that file isn't plain text")
                    text = raw.decode("utf-8-sig", "replace").replace("\r\n", "\n")
                else:
                    text = _read_doc(engine, src)
                ai = _ai_details(ask, text) if ask else []
                words = [(w, "yours") for w in hide] + ai

                def edit(t: str) -> list[tuple[int, int, str]]:
                    spans = hide_spans(t, pattern_hits(t) + find_words(t, words), keep)
                    return [(a, b, label(t[a:b], kind)) for a, b, kind in spans]

                if ext == ".docx":
                    name = f"{stem}-cleaned.docx"
                    docx_rewrite(src, folder / name, edit,
                                 lambda part, xml: docx_hidden_places(part, _scrub_docx_people(part, xml), edit))
                else:
                    name = f"{stem}-cleaned{ext if ext in ('.txt', '.md', '.markdown', '.csv') else '.txt'}"
                    new, last = [], 0
                    for a, b, rep in edit(text):
                        new += [text[last:a], rep]
                        last = b
                    new.append(text[last:])
                    atomic_write_text(folder / name, "".join(new))
            except (ValueError, OSError, PartFailed, zipfile.BadZipFile, KeyError) as e:
                failed.append(f"{src.name}: {e}"[:200])
                engine.log(f"  {src.name}: {e}")
                continue
            counts = ", ".join(f"{n} {HIDE_KINDS[k].lower()}{'s' if n != 1 else ''}" for k, n in
                               sorted(label.count.items(), key=lambda kv: -kv[1])) or "nothing found"
            note = "" if ext in (".txt", ".md", ".markdown", ".csv", ".docx") else \
                (" (as plain text: blacking out a PDF by drawing boxes leaves the words underneath, so Joe "
                 "gives you a clean text copy instead)" if ext == ".pdf" else " (as plain text)")
            report.append(f"- **{src.name}** -> {name}{note}: {counts}")
            if ext == ".docx":
                report += [f"  - [CHECK] {c}" for c in docx_carries(src)]
            if label.key:
                key_lines += [f"## {src.name}", ""] + [f"- {lab} = {orig}" for lab, orig in label.key] + [""]
            st.media_files.append(name)
            st.titles.append(key)
            st.items += 1
            engine._save_state(job, st)
            engine.log(f"  {src.name} -> {name}: {counts}")
    except Stopped:
        return _stopped(engine, job, st, len(files), "document(s)")
    if keep:
        report += ["", "Kept as they are (you asked): " + ", ".join(keep)]
    if ext_pics := [f.name for f in files if f.suffix.lower() in (".jpg", ".jpeg", ".png")]:
        report += ["", "Photos: use Privacy blur for " + ", ".join(ext_pics)]
    if failed:
        report += ["", "## Not done", ""] + [f"- {x}" for x in failed]
    atomic_write_text(folder / "what-was-hidden.md", "\n".join(report) + "\n")
    st.media_files.append("what-was-hidden.md")
    if "key" in opts and key_lines:
        atomic_write_text(folder / "KEEP-PRIVATE-label-key.md",
                          "# KEEP PRIVATE: what each label stands for\n\nThis file has the details Joe hid. Never "
                          "share it with the cleaned copies.\n\n" + "\n".join(key_lines))
        st.media_files.append("KEEP-PRIVATE-label-key.md")
    return _finish(engine, job, st, len(files), failed)


def _scrub_docx_people(name: str, xml: str) -> str:
    """Word keeps the author's name (and every reviewer's) outside the text: blanked in the copy."""
    if name == "docProps/core.xml":
        xml = re.sub(r"(<dc:creator>)[^<]*(</dc:creator>)", r"\1\2", xml)
        xml = re.sub(r"(<cp:lastModifiedBy>)[^<]*(</cp:lastModifiedBy>)", r"\1\2", xml)
    if name.startswith("word/") and name.endswith(".xml"):
        xml = re.sub(r'(\sw\d*:author=")[^"]*(")', r"\1Author\2", xml)          # w:author, w15:author (people.xml)
        xml = re.sub(r'(\sw\d*:initials=")[^"]*(")', r"\1A\2", xml)
        xml = re.sub(r'(\sw\d*:userId=")[^"]*(")', r"\1\2", xml)               # the reviewer's account (often an email)
    if name == "docProps/app.xml":
        xml = re.sub(r"(<(Company|Manager|HyperlinkBase)>)[^<]*(</\2>)", r"\1\3", xml)
    return xml


# A Word file keeps words in more places than the page shows: the address a link opens (an email shown
# in the text is usually also a "mailto:" link behind it), picture descriptions and picture file names,
# field codes, words inside drawings and charts, and the file's title and custom properties. A detail
# hidden on the page but left in one of those is still in the file, so the same edit runs over them too.
_DOCX_ELEM = re.compile(r"(<(a:t|m:t|w:instrText|vt:lpwstr|dc:title|dc:subject|dc:description|cp:keywords|cp:category)"
                        r"(?:\s[^>]*)?>)([^<]*)(</\2>)")
_DOCX_PIC_TAG = re.compile(r"<(?:wp:docPr|pic:cNvPr|p:cNvPr|v:imagedata|v:shape|w:fldSimple|w:hyperlink|w:alias|w:tag|w:listItem)\b[^>]*>")
_DOCX_PIC_ATTR = re.compile(r'(\s(?:name|descr|title|alt|o:title|w:instr|w:tooltip|w:val|w:displayText|w:value)=")([^"]*)(")')
_REL = re.compile(r"<Relationship\b[^>]*>")
# a path through someone's own folder gives away their account name: C:\\Users\\<name>\\..., /home/<name>/...
_HOME_PATH = re.compile(r"(?i)((?:[\\/]|%5C|%2F)(?:Users|home|Documents and Settings)(?:[\\/]|%5C|%2F))[^\\/%\"]+")


def _attr_escape(s: str) -> str:
    return _xml_escape(s).replace('"', "&quot;")


def _apply(text: str, edit) -> str:
    out, last = [], 0
    for a, b, rep_ in sorted(edit(text), key=lambda x: x[0]):
        if b <= a or a < last:
            continue
        out += [text[last:a], rep_]
        last = b
    out.append(text[last:])
    return "".join(out)


def docx_hidden_places(name: str, xml: str, edit) -> str:
    """Run the hide edit over the words a Word file keeps off the page (see above). `edit` is the same
    function the page text gets."""
    from urllib.parse import unquote
    if name.endswith(".rels"):
        def rel(m: re.Match) -> str:
            tag = m.group(0)
            if 'TargetMode="External"' not in tag:
                return tag
            t = re.search(r'\sTarget="([^"]*)"', tag)
            if not t:
                return tag
            plain = unquote(_xml_text(t.group(1)))
            if _apply(plain, edit) == plain and not _HOME_PATH.search(plain):
                return tag
            new = "https://example.invalid/hidden" if "/hyperlink" in tag else "hidden"
            return tag[:t.start(1)] + new + tag[t.end(1):]
        return _REL.sub(rel, xml)
    if not name.endswith(".xml"):
        return xml
    xml = _DOCX_ELEM.sub(lambda m: m.group(1) + _xml_escape(_apply(_xml_text(m.group(3)), edit)) + m.group(4), xml)

    def tag(m: re.Match) -> str:
        def attr(a: re.Match) -> str:
            plain = _xml_text(a.group(2))
            new = _HOME_PATH.sub(lambda h: h.group(1) + "user", _apply(plain, edit))
            return a.group(1) + (_attr_escape(new) if new != plain else a.group(2)) + a.group(3)
        return _DOCX_PIC_ATTR.sub(attr, m.group(0))
    return _DOCX_PIC_TAG.sub(tag, xml)


def docx_carries(src: Path) -> list[str]:
    """What's inside a Word file that Joe can't read and so can't clean (said in the report)."""
    try:
        with zipfile.ZipFile(src) as z:
            names = z.namelist()
    except (OSError, zipfile.BadZipFile):
        return []
    pics = sum(1 for n in names if n.startswith("word/media/"))
    emb = sum(1 for n in names if n.startswith("word/embeddings/"))
    out = []
    if pics:
        out.append(f"{pics} picture(s) inside it (logos, signatures, scanned pages): Joe doesn't look inside pictures")
    if emb:
        out.append(f"{emb} file(s) embedded in it (like a spreadsheet): not cleaned")
    return out


# =========================================================================== 4. Meeting minutes
MIN_SYSTEM = ("You write meeting minutes from a transcript. Use only what is said. Never invent names, numbers, "
              "dates, decisions or tasks. The transcript doesn't say who is talking: name a person only when the "
              "words make it clear (they're called by name, or say who they are); otherwise write 'Someone'. "
              "Mark guesses [CHECK].")
MIN_FACTS = """Today is {today}. From this meeting transcript{piece}, reply with ONLY JSON:
{{"people": ["names of people mentioned as being there"],
"decisions": ["each decision made, one plain sentence"],
"todos": [{{"task": "what to do", "who": "name or empty", "due": "YYYY-MM-DD or empty", "due_said": "when, as said, or empty"}}],
"questions": ["questions left open"]}}
TRANSCRIPT:
{text}"""
MIN_SUMMARY = """Write the summary part of the minutes for this meeting{wish}. Markdown, exactly these sections:
## Summary
3-6 sentences.
## Who said what
Bullets 'Name: main point', only for people the transcript makes clear; 'Someone' otherwise.
## Discussion
Short bullets of the main topics in order.
{what}:
{text}"""
MIN_PIECE_WORDS = 2500


def _transcript_from_text(src: Path, engine: "Engine") -> str:
    """A saved transcript or subtitles file: the words, without the subtitle numbers and times."""
    if src.suffix.lower() in (".srt", ".vtt"):
        raw = src.read_bytes().decode("utf-8-sig", "replace").replace("\r\n", "\n")
        lines = [ln.strip() for ln in raw.splitlines()]
        keep = [ln for ln in lines if ln and ln != "WEBVTT" and not ln.isdigit() and "-->" not in ln
                and not re.match(r"^(NOTE|STYLE|Kind:|Language:)", ln)]
        return " ".join(re.sub(r"<[^>]+>", "", ln) for ln in keep)
    return _read_doc(engine, src)


def merge_minutes(parts: list[dict]) -> dict:
    """Facts from each piece of a long meeting joined, repeats dropped."""
    out = {"people": [], "decisions": [], "todos": [], "questions": []}
    seen: set[str] = set()
    for p in parts:
        if not isinstance(p, dict):
            continue
        for k in ("people", "decisions", "questions"):
            for x in p.get(k) or []:
                s = " ".join(str(x).split())
                if s and (k, _norm(s)) not in seen:
                    seen.add((k, _norm(s)))
                    out[k].append(s)
        for t in p.get("todos") or []:
            if isinstance(t, dict) and str(t.get("task") or "").strip() and ("t", _norm(t["task"])) not in seen:
                seen.add(("t", _norm(t["task"])))
                out["todos"].append(t)
    return out


def minutes_md(title: str, when: str, facts: dict, summary: str, transcript: str, model: str) -> tuple[str, list[dict]]:
    """The minutes document. To-do owners and dates are checked against the transcript."""
    todos, rows = [], []
    for t in facts.get("todos") or []:
        who = " ".join(str(t.get("who") or "").split())
        said = " ".join(str(t.get("due_said") or "").split())
        due = _letter_date(t.get("due"))
        if who and not found_in(who, transcript):
            who += " [CHECK]"
        if said and not found_in(said, transcript):
            said += " [CHECK]"
        rows.append([str(t["task"]).strip(), who or "Someone", said or (due.isoformat() + " [CHECK]" if due else "")])
        todos.append({"task": str(t["task"]).strip(), "who": who.replace(" [CHECK]", ""),
                      "due": due.isoformat() if due else ""})
    people = [p if found_in(p, transcript) else f"{p} [CHECK]" for p in facts.get("people") or []]
    out = [f"# Minutes: {title}", "", _ai_note("Written", model, "Joe can't tell voices apart: a name is only "
                                               "given when the recording makes it clear.").strip(), "",
           f"**When:** {when}  ", f"**Mentioned as there:** {', '.join(people) or 'not said'}", "",
           summary.strip(), "", "## Decisions", ""]
    out += [f"- {d}" for d in facts.get("decisions") or []] or ["- None mentioned."]
    out += ["", "## To-dos", ""]
    out += [_table(["What", "Who", "By when"], rows)] if rows else ["- None mentioned."]
    out += ["", "## Open questions", ""] + ([f"- {q}" for q in facts.get("questions") or []] or ["- None mentioned."])
    return "\n".join(out) + "\n", todos


def run_meeting_minutes(engine: "Engine", mission: "Mission", job: "Job", st: "JobState") -> "JobState":
    from .doctor import ffmpeg_exe
    from .engine import PartFailed, Stopped
    from .filetools import build_ics
    from .mission import slug
    from .tools import (WHISPER_CODES, _finish, _key, _to_wav, _wav_seconds, chosen_options, hear, hearing_model,
                        hearing_ready, how_long, option_value, transcript_text, unique_stem, whisper_language)
    got = _begin(engine, job, st, "recordings or transcripts", need_text=True)
    if not isinstance(got, tuple):
        return got
    files, folder = got
    sound = [f for f in files if f.suffix.lower() not in TRANSCRIPT_EXT]
    if sound and not hearing_ready(engine.s) and engine.voice is None:
        return _fail(engine, job, st, "turning a recording into minutes needs Joe's voice add-on or whisper.cpp "
                     "(Setup > System check). A transcript (.txt, .srt) works without it")
    ffmpeg = ffmpeg_exe(engine.s.comfy.ffmpeg)
    lang = option_value(job, "language") or "english"
    if lang not in WHISPER_CODES and lang != "auto":
        lang = "english"
    hear_model = hearing_model(engine.s.voice.stt_model, lang)
    opts = chosen_options(job)
    ask = _asker(engine, job, st)
    model = _model(engine)
    today = date.today()
    wish = f" (the person adds: {job.format.strip()})" if job.format.strip() else ""
    failed: list[str] = []
    try:
        for i, src in enumerate(files):
            key = _key(engine, src)
            if key in st.titles:
                continue
            engine._progress(f"{job.name}: {i + 1}/{len(files)} {src.name}")
            stem = unique_stem(files, i)
            made: list[str] = []
            try:
                if src.suffix.lower() in TRANSCRIPT_EXT:
                    text = _transcript_from_text(src, engine)
                else:
                    engine.log(f"  {src.name}: listening...")
                    wav = _to_wav(ffmpeg, src, engine.meta / "tmp" / (slug(src.stem) + ".wav"), engine.log)
                    if not wav:
                        raise ValueError("couldn't read the sound" + ("" if ffmpeg else " (only .wav works without FFmpeg)"))
                    secs = _wav_seconds(wav)
                    r = hear(engine, wav, hear_model, whisper_language(lang), timeout=max(900.0, secs * 4 + 600))
                    if wav != src:
                        try:
                            wav.unlink()
                        except OSError:
                            pass
                    if not r.get("ok"):
                        raise ValueError(r.get("error", "transcribing failed"))
                    segs = r.get("segments") or []
                    text = " ".join(s.get("t", "").strip() for s in segs)
                    if "transcript" in opts:
                        atomic_write_text(folder / f"{stem}-transcript.txt", transcript_text(segs, src.stem))
                        made.append(f"{stem}-transcript.txt")
                    engine.log(f"  {src.name}: {how_long(secs)} heard")
                if not text.strip():
                    raise ValueError("no words were heard in it")
                words = text.split()
                pieces = [" ".join(words[a:a + MIN_PIECE_WORDS]) for a in range(0, len(words), MIN_PIECE_WORDS)]
                facts = merge_minutes([_ask_json(ask, "minutes", MIN_SYSTEM + " Reply with ONLY JSON.", MIN_FACTS.format(
                    today=today.isoformat(), piece=f" (part {k + 1} of {len(pieces)})" if len(pieces) > 1 else "",
                    text=p)) for k, p in enumerate(pieces)])
                if len(pieces) == 1:
                    summary = ask("minutes", MIN_SYSTEM + " Markdown.",
                                  MIN_SUMMARY.format(wish=wish, what="TRANSCRIPT", text=text), 30)
                else:
                    notes = [ask("minutes", MIN_SYSTEM, f"Bullet-point notes of everything important in part {k + 1} "
                                 f"of {len(pieces)} of a meeting:\n{p}", 10) for k, p in enumerate(pieces)]
                    summary = ask("minutes", MIN_SYSTEM + " Markdown.",
                                  MIN_SUMMARY.format(wish=wish, what="NOTES FROM EACH PART, IN ORDER",
                                                     text="\n\n".join(notes)), 30)
            except (ValueError, OSError, PartFailed) as e:
                failed.append(f"{src.name}: {e}"[:200])
                engine.log(f"  {src.name}: {e}")
                continue
            when = datetime.fromtimestamp(src.stat().st_mtime).strftime("%Y-%m-%d") + " (the file's date) [CHECK]"
            body, todos = minutes_md(src.stem, when, facts, summary, text, model)
            _save(folder, st, f"{stem}-minutes.md", body, src.name)
            made.insert(0, f"{stem}-minutes.md")
            st.media_files.extend(m for m in made[1:] if m not in st.media_files)
            if "calendar" in opts and any(t["due"] for t in todos):
                ics, _ = build_ics([], todos)
                atomic_write_text(folder / f"{stem}-todos.ics", ics)
                st.media_files.append(f"{stem}-todos.ics")
                made.append(f"{stem}-todos.ics")
            st.titles.append(key)
            st.items += 1
            engine._save_state(job, st)
            engine.log(f"  {src.name} -> {', '.join(made)}")
    except Stopped:
        return _stopped(engine, job, st, len(files), "recording(s)")
    return _finish(engine, job, st, len(files), failed)


# =========================================================================== 5. Bank statement to budget
BUDGET_CATS = ("Housing", "Utilities", "Groceries", "Eating out", "Fuel and transport", "Shopping", "Subscriptions",
               "Health", "Insurance", "Kids and school", "Pets", "Fun and hobbies", "Travel", "Fees and interest",
               "Cash", "Transfers", "Income", "Gifts and giving", "Other")
# Joe's own sorting for names everyone knows; the writing model only sorts the rest.
BUDGET_RULES = (
    ("Subscriptions", r"netflix|spotify|hulu|disney\s*\+|disneyplus|youtube ?premium|apple\.com/bill|itunes|icloud|"
                      r"amazon prime|prime video|audible|patreon|paramount|peacock|max\.com|hbo|xbox|playstation|"
                      r"nintendo|adobe|microsoft 365|dropbox|google (?:one|storage)|chatgpt|openai|crunchyroll"),
    ("Fuel and transport", r"\bshell\b|exxon|mobil|chevron|\bbp\b|sunoco|marathon|speedway|valero|texaco|\bcitgo\b|"
                           r"uber(?! eats)|lyft|parking|toll|transit|metro|railway|\bdmv\b|jiffy lube"),
    ("Eating out", r"mcdonald|starbucks|burger king|wendy|taco bell|subway|chipotle|domino|pizza|doordash|"
                   r"uber ?eats|grubhub|dunkin|kfc|chick-fil-a|panera|restaurant|cafe|coffee|diner|grill"),
    ("Groceries", r"kroger|aldi|safeway|publix|meijer|wegmans|trader joe|whole foods|lidl|tesco|sainsbury|grocery|"
                  r"supermarket|food lion|h-e-b|\bheb\b|albertsons|winco|hy-vee|costco"),
    ("Utilities", r"electric|energy|power co|water|gas co|sewer|comcast|xfinity|spectrum|verizon|at&t|t-mobile|"
                  r"internet|broadband|consumers energy|duke energy"),
    ("Insurance", r"insurance|geico|state farm|progressive|allstate|usaa ins|liberty mutual|farmers ins"),
    ("Health", r"pharmacy|cvs|walgreens|rite aid|hospital|clinic|dental|dentist|medical|doctor|optical"),
    ("Fees and interest", r"\bfee\b|overdraft|interest charge|finance charge|late charge|service charge"),
    ("Cash", r"\batm\b|cash withdrawal"),
    ("Transfers", r"transfer|zelle|venmo|paypal transfer|cash app|to savings|from savings"),
    ("Housing", r"\brent\b|mortgage|hoa\b|property tax|landlord"),
    ("Pets", r"petco|petsmart|\bvet\b|veterinar|chewy"),
    ("Income", r"payroll|salary|direct dep|paycheck|pension|social security|refund"),
)
BUDGET_SYSTEM = ("You sort bank transactions into budget categories. Use only the category names given. If a "
                 "name could be several things, pick Other. Reply with ONLY JSON.")
BUDGET_ASK = """Categories: {cats}
For each merchant name below, pick one category. Reply with ONLY JSON: {{"merchant name": "Category", ...}}
{names}"""
_DATE_FORMATS_MDY = ("%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y")
_DATE_FORMATS_DMY = ("%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d-%m-%y", "%d.%m.%Y", "%d.%m.%y")
_DATE_FORMATS_ANY = ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y",
                     "%b %d %Y", "%d-%b-%Y", "%d-%b-%y", "%Y%m%d")


def parse_money(s: str) -> Decimal | None:
    """'$1,234.56' '(12.00)' '-12.00' '12.00-' '1.234,56 €' '45.10 CR' -> Decimal (negative = money out
    only when the bank wrote it so). None when it isn't a number."""
    t = str(s or "").strip()
    if not t:
        return None
    neg = t.startswith("(") and t.endswith(")") or t.startswith("-") or t.endswith("-") or \
        re.search(r"\bDR\b", t, re.I) is not None
    t = re.sub(r"(?i)\b(?:CR|DR)\b|[^\d.,]", "", t)
    if not t or not re.search(r"\d", t):
        return None
    if "," in t and "." in t:
        t = t.replace(",", "") if t.rfind(".") > t.rfind(",") else t.replace(".", "").replace(",", ".")
    elif "," in t:
        t = t.replace(",", ".") if re.search(r",\d{1,2}$", t) else t.replace(",", "")
    elif t.count(".") > 1:
        t = t.replace(".", "")
    try:
        v = Decimal(t)
    except InvalidOperation:
        return None
    return -v if neg else v


def date_order(values: list[str]) -> str:
    """'dmy' when any date can only be day-first (13/02/2026), else 'mdy' (the US way)."""
    for v in values:
        m = re.match(r"^\s*(\d{1,2})[/.-](\d{1,2})[/.-]\d{2,4}", v or "")
        if m and int(m.group(1)) > 12 >= int(m.group(2)):
            return "dmy"
    return "mdy"


def parse_day(v: str, order: str = "mdy") -> date | None:
    v = " ".join(str(v or "").split())[:40]
    v = re.sub(r"[T ]\d{1,2}:\d{2}(?::\d{2})?.*$", "", v)
    for f in _DATE_FORMATS_ANY + (_DATE_FORMATS_DMY if order == "dmy" else _DATE_FORMATS_MDY):
        try:
            return datetime.strptime(v, f).date()
        except ValueError:
            continue
    return None


def merchant_key(desc: str) -> str:
    """'POS DEBIT NETFLIX.COM 866-579-7172 CA #1234' -> 'netflix.com': the same shop each time."""
    t = str(desc or "").lower()
    t = re.sub(r"\b(?:pos|debit|credit|card|purchase|recurring|payment|ach|visa|mastercard|mc|chk|checkcard|"
               r"withdrawal|pmt|pre-?auth|authorized|on|web|online|sq \*|tst\*|sp \*|pp\*|paypal \*)\b", " ", t)
    t = re.sub(r"[#*]\s*\w*|\d{3,}|\b\d+/\d+\b", " ", t)
    t = re.sub(r"[^a-z0-9.&' +-]", " ", t)
    t = re.sub(r"(?:\s+-+)+\s*$|\s+[a-z]{2}\s*$", "", t.strip())             # a trailing state code
    words = [w for w in t.split() if len(w) > 1 or w.isalpha()]
    return " ".join(words[:2]) or str(desc or "").strip().lower()[:20]


def _find_col(header: list[str], *names: str) -> int:
    low = [h.strip().lower() for h in header]
    for n in names:
        for i, h in enumerate(low):
            if h == n:
                return i
    for n in names:
        for i, h in enumerate(low):
            if n in h:
                return i
    return -1


def read_statement(header: list[str], rows: list[list[str]]) -> tuple[list[dict], list[str]]:
    """Bank rows -> [{date, desc, amount (negative = money out), bank_cat}], plus notes on guesses."""
    notes: list[str] = []
    c_date = _find_col(header, "date", "transaction date", "posting date", "posted date", "value date", "posted")
    c_desc = _find_col(header, "description", "payee", "merchant", "name", "details", "narrative", "memo",
                       "transaction", "reference")
    c_amt = _find_col(header, "amount", "transaction amount", "value")
    # "withdraw" also finds misspellings banks really use ("Withdrawls"), "Withdrawn" and "Withdrawal amount"
    c_out = _find_col(header, "debit", "withdrawal", "money out", "paid out", "withdrawals", "debits", "spent",
                      "withdraw", "outgoing", "outflow")
    c_in = _find_col(header, "credit", "deposit", "money in", "paid in", "deposits", "credits", "received",
                     "incoming", "inflow", "lodgement")
    c_type = _find_col(header, "transaction type", "type", "cr/dr", "dr/cr", "debit/credit")
    c_cat = _find_col(header, "category")
    if c_date < 0 or c_desc < 0 or (c_amt < 0 and c_out < 0 and c_in < 0):
        raise ValueError("Joe couldn't find the date, description and amount columns (the sheet has: "
                         + ", ".join(h for h in header if h)[:200] + "). Download the statement as CSV from your "
                         "bank's website; most have a Download or Export button")
    order = date_order([r[c_date] for r in rows if c_date < len(r)])
    out: list[dict] = []
    signs = set()
    for r in rows:
        cell = lambda i: r[i] if 0 <= i < len(r) else ""  # noqa: E731
        d = parse_day(cell(c_date), order)
        if not d:
            continue
        if c_amt >= 0 and cell(c_amt).strip():
            a = parse_money(cell(c_amt))
            if a is None:
                continue
            kind = cell(c_type).lower()
            if a > 0 and re.search(r"\b(?:debit|dr|withdrawal|purchase|payment|sale)\b", kind):
                a = -a
            signs.add(a > 0)
        else:
            o, i_ = parse_money(cell(c_out)), parse_money(cell(c_in))
            if o is None and i_ is None:
                continue
            a = (abs(i_) if i_ else Decimal(0)) - (abs(o) if o else Decimal(0))
            signs.add(True)
            signs.add(False)
        out.append({"date": d, "desc": " ".join(cell(c_desc).split()), "amount": a, "bank_cat": cell(c_cat).strip()})
    if c_amt < 0 and (c_out < 0 or c_in < 0):   # only one of the two money columns was found: say so, loudly
        have, lack = (header[c_in], "money going out") if c_out < 0 else (header[c_out], "money coming in")
        notes.append(f"Joe found the '{have}' column but no column for {lack}, so that side of the budget is "
                     "empty. The sheet's columns are: " + ", ".join(h for h in header if h)[:200] + " [CHECK]")
    if signs == {True}:                         # every amount positive: a card statement lists spending as plus
        for t in out:
            t["amount"] = -t["amount"]
        notes.append("Every amount in the file was positive, so Joe counted them all as spending [CHECK]")
    if order == "dmy":
        notes.append("Dates were read day first (like 13/02/2026)")
    return out, notes


def rule_category(desc: str, bank_cat: str = "") -> str:
    low = desc.lower()
    for cat, rx in BUDGET_RULES:
        if re.search(rx, low):
            return cat
    b = bank_cat.lower()
    for cat in BUDGET_CATS:
        if b and (b == cat.lower() or b.split()[0] in cat.lower().split()):
            return cat
    return ""


VARIABLE_CATS = ("Groceries", "Fuel and transport", "Eating out", "Cash", "Transfers", "Shopping")


def _about(a: Decimal, b: Decimal) -> bool:
    """The same price, give or take 2% (some places round or add a few cents of tax)."""
    return abs(a - b) <= max(Decimal("0.05"), max(a, b) * Decimal("0.02"))


def find_subscriptions(txs: list[dict]) -> list[dict]:
    """Money out to the same place at a steady rhythm (weekly, monthly or yearly) with a similar amount:
    a subscription. Each: merchant, how often, last amount, yearly cost, rise (last vs the one before)."""
    by: dict[str, list[dict]] = {}
    for t in txs:
        if t["amount"] < 0:
            by.setdefault(t["key"], []).append(t)
    out = []
    for key, ts in by.items():
        ts = sorted(ts, key=lambda t: t["date"])
        if len(ts) < 2 or ts[-1].get("cat") in VARIABLE_CATS:
            continue                                   # groceries and fuel come often but aren't subscriptions
        gaps = [(b["date"] - a["date"]).days for a, b in zip(ts, ts[1:])]
        amts = [abs(t["amount"]) for t in ts]
        avg = sum(gaps) / len(gaps)
        how = ("weekly" if 5 <= avg <= 9 else "monthly" if 26 <= avg <= 35 else
               "yearly" if 355 <= avg <= 375 else "")
        if not how or max(gaps) > avg * 1.6:
            continue
        last = amts[-1]
        step = next((k for k in range(len(amts) - 1, 0, -1) if not _about(amts[k - 1], last)), 0)
        before, after = amts[:step], amts[step:]
        steady = all(_about(a, last) for a in after) and (not before or all(_about(a, before[-1]) for a in before))
        if not steady or (before and len(amts) < 3) or (before and not before[-1] * Decimal("0.5") <= last <= before[-1] * 2):
            continue                                   # amounts that wander (or only two that differ): not a subscription
        prev = before[-1] if before else last
        per_year = {"weekly": 52, "monthly": 12, "yearly": 1}[how]
        rise = last - prev if last - prev >= max(Decimal("0.50"), prev / 100) else Decimal(0)
        out.append({"key": key, "name": ts[-1]["desc"], "how": how, "last": last, "year": last * per_year,
                    "rise": rise, "prev": prev, "times": len(ts), "since": ts[0]["date"]})
    return sorted(out, key=lambda s: -s["year"])


def _money(v: Decimal, sym: str) -> str:
    v = Decimal(v).quantize(Decimal("0.01"))
    return ("-" if v < 0 else "") + f"{sym}{abs(v):,.2f}"


def budget_report(txs: list[dict], subs: list[dict], notes: list[str], sym: str, dropped: int) -> tuple[str, list[list[str]], list[str]]:
    """(budget.md, the by-category sheet rows, its header). All the math is Joe's own."""
    months = sorted({t["date"].strftime("%Y-%m") for t in txs})
    first, last = min(t["date"] for t in txs), max(t["date"] for t in txs)
    money_in = sum((t["amount"] for t in txs if t["amount"] > 0 and t["cat"] != "Transfers"), Decimal(0))
    money_out = -sum((t["amount"] for t in txs if t["amount"] < 0 and t["cat"] != "Transfers"), Decimal(0))
    cats: dict[str, dict[str, Decimal]] = {}
    for t in txs:
        if t["amount"] < 0:
            cats.setdefault(t["cat"], {}).setdefault(t["date"].strftime("%Y-%m"), Decimal(0))
            cats[t["cat"]][t["date"].strftime("%Y-%m")] += -t["amount"]
    totals = {c: sum(m.values(), Decimal(0)) for c, m in cats.items()}
    spend = sum((v for c, v in totals.items() if c != "Transfers"), Decimal(0)) or Decimal(1)
    n_months = max(1, len(months))
    md = ["# Your budget", "",
          f"> Worked out by Joe on this computer from {len(txs)} transactions, {first:%d %b %Y} to {last:%d %b %Y}. "
          "Joe's own code does all the math. Categories are a best guess: fix any in budget-transactions.csv. "
          "Your statement wasn't changed.", "",
          "## The big picture", "",
          _table(["", "Amount"], [["Money in", _money(money_in, sym)], ["Money out", _money(money_out, sym)],
                                  ["Left over" if money_in >= money_out else "Short by",
                                   _money(abs(money_in - money_out), sym)],
                                  ["Months covered", str(len(months))]]),
          "", "Transfers between your own accounts aren't counted as money in or out.", "",
          "## Where the money went", ""]
    rows = []
    for c in sorted(totals, key=lambda c: -totals[c]):
        if c == "Transfers":
            continue
        rows.append([c, _money(totals[c], sym), f"{totals[c] * 100 / spend:.0f}%", _money(totals[c] / n_months, sym)])
    md += [_table(["Category", "Total", "Share", "Average a month"], rows), ""]
    if subs:
        md += ["## Subscriptions and regular payments", "",
               f"These come out on a steady rhythm. Together about **{_money(sum((s['year'] for s in subs), Decimal(0)), sym)} "
               "a year**. Cancel any you don't use.", "",
               _table(["Paid to", "How often", "Last amount", "A year", "Price went up?"],
                      [[s["name"], s["how"], _money(s["last"], sym), _money(s["year"], sym),
                        f"yes, by {_money(s['rise'], sym)} (was {_money(s['prev'], sym)})" if s["rise"] else ""] for s in subs]), ""]
        rises = [s for s in subs if s["rise"]]
        if rises:
            md += ["## Price rises", ""] + [f"- **{s['name']}** went from {_money(s['prev'], sym)} to "
                                            f"{_money(s['last'], sym)} ({_money(s['rise'] * {'weekly': 52, 'monthly': 12, 'yearly': 1}[s['how']], sym)} more a year)"
                                            for s in rises] + [""]
    big = sorted((t for t in txs if t["amount"] < 0 and t["cat"] != "Transfers"), key=lambda t: t["amount"])[:10]
    if big:
        md += ["## Biggest payments", "", _table(["Date", "Paid to", "Amount", "Category"],
                                                 [[f"{t['date']:%Y-%m-%d}", t["desc"], _money(-t["amount"], sym), t["cat"]] for t in big]), ""]
    other = sum(1 for t in txs if t["cat"] == "Other" and t["amount"] < 0)
    if other:
        notes = notes + [f"{other} payment(s) couldn't be sorted and are under Other"]
    if dropped:
        notes = notes + [f"{dropped} transaction(s) were in more than one file and were counted once [CHECK]"]
    if notes:
        md += ["## Good to know", ""] + [f"- {n}" for n in notes] + [""]
    header = ["Category"] + months + ["Total", "Average a month"]
    sheet = [[c] + [f"{cats[c].get(m, Decimal(0)):.2f}" for m in months] + [f"{totals[c]:.2f}", f"{totals[c] / n_months:.2f}"]
             for c in sorted(totals, key=lambda c: -totals[c])]
    return "\n".join(md), sheet, header


def run_bank_budget(engine: "Engine", mission: "Mission", job: "Job", st: "JobState") -> "JobState":
    from .engine import PartFailed, Stopped
    from .sheets import SheetError, read_table, write_csv
    from .tools import _finish, chosen_options
    opts = chosen_options(job)
    got = _begin(engine, job, st, "bank statements (CSV from your bank)")
    if not isinstance(got, tuple):
        return got
    files, folder = got
    txs: list[dict] = []
    notes: list[str] = []
    failed: list[str] = []
    seen: dict[tuple, str] = {}
    dropped = 0
    sym = ""
    for src in files:
        try:
            header, rows, cut = read_table(src)
            got_rows, n = read_statement(header, rows)
        except (SheetError, ValueError, OSError, zipfile.BadZipFile, KeyError) as e:
            failed.append(f"{src.name}: {e}"[:300])
            engine.log(f"  {src.name}: {e}")
            continue
        n = [f"{src.name}: {x[0].lower()}{x[1:]}" for x in n]
        if cut:
            n.append(f"{src.name} is very long: only the first 20,000 rows were read")
        if not sym:
            m = re.search(r"[$£€¥₹]", " ".join(" ".join(r) for r in rows[:50]))
            sym = m.group() if m else ""
        notes += [x for x in n if x not in notes]
        for t in got_rows:
            k = (t["date"], t["desc"].lower(), t["amount"])
            if k in seen and seen[k] != src.name:
                dropped += 1
                continue
            seen.setdefault(k, src.name)
            t["key"] = merchant_key(t["desc"])
            t["cat"] = rule_category(t["desc"], t["bank_cat"]) or ("Income" if t["amount"] > 0 else "")
            txs.append(t)
        engine.log(f"  {src.name}: {len(got_rows)} transactions")
    if not txs:
        return _fail(engine, job, st, "; ".join(failed) or "no transactions were found in the file(s)")
    todo = sorted({t["key"] for t in txs if not t["cat"]})
    if todo and "ai" in opts:
        if engine._text_ready(st):
            st.status = "running"
            ask = _asker(engine, job, st)
            names = {t["key"]: t["desc"] for t in txs}
            try:
                for a in range(0, len(todo), 60):
                    if engine.stop.is_set():
                        raise Stopped()
                    batch = todo[a:a + 60]
                    engine._progress(f"{job.name}: sorting {a + len(batch)}/{len(todo)} places")
                    got = _ask_json(ask, "budget", BUDGET_SYSTEM, BUDGET_ASK.format(
                        cats=", ".join(BUDGET_CATS), names="\n".join(f"- {names[k]}" for k in batch)))
                    if isinstance(got, dict):
                        low = {_norm(k): v for k, v in got.items()}
                        for k in batch:
                            v = str(low.get(_norm(names[k])) or low.get(_norm(k)) or "")
                            cat = next((c for c in BUDGET_CATS if c.lower() == v.strip().lower()), "")
                            for t in txs:
                                if t["key"] == k and not t["cat"]:
                                    t["cat"] = cat
            except Stopped:
                return _stopped(engine, job, st, 1, "statement(s)")
            except PartFailed as e:
                notes.append(f"The writing model couldn't sort the rest ({e})")
        else:
            st.status, st.note = "running", ""
            notes.append("The writing model wasn't available, so unknown places are under Other")
    for t in txs:
        t["cat"] = t["cat"] or "Other"
    txs.sort(key=lambda t: t["date"])
    subs = find_subscriptions(txs)
    sub_keys = {s["key"] for s in subs}
    for t in txs:
        if t["key"] in sub_keys and t["amount"] < 0 and t["cat"] == "Other":
            t["cat"] = "Subscriptions"
    md, sheet, header = budget_report(txs, subs, notes, sym, dropped)
    _save(folder, st, "budget.md", md, "budget")
    write_csv(folder / "budget-transactions.csv", ["Date", "Description", "Amount", "Category", "Regular payment"],
              [[f"{t['date']:%Y-%m-%d}", safe_cell(t["desc"]), f"{t['amount']:.2f}", t["cat"],
                "yes" if t["key"] in sub_keys and t["amount"] < 0 else ""] for t in txs])
    write_csv(folder / "budget-by-category.csv", header, sheet)
    st.media_files += ["budget-transactions.csv", "budget-by-category.csv"]
    st.titles.append("budget")
    st.items = len(txs)
    engine.log(f"  {len(txs)} transactions, {len(subs)} regular payment(s) -> budget.md")
    return _finish(engine, job, st, 1, failed)


# =========================================================================== 6. Resume tailor
RESUME_SYSTEM = ("You help a person apply for a job honestly. Use only what their resume says. Never invent jobs, "
                 "employers, dates, titles, schools, degrees, certificates, skills, tools, numbers or results. If the "
                 "job asks for something the resume doesn't show, don't claim it.")
RESUME_REQS = """Read the job posting between <<< and >>>. Reply with ONLY JSON:
{{"title": "the job title", "company": "the employer, or empty",
"must": ["each must-have requirement, short"], "nice": ["each nice-to-have, short"],
"keywords": ["skills, tools and words from the posting a hiring system would look for, 1-3 words each"]}}
<<<
{text}
>>>"""
RESUME_MATCH = """For each requirement below, find where the RESUME shows it. Reply with ONLY JSON:
{{"matches": [{{"requirement": "as given", "evidence": "a line copied word for word from the resume that shows it, or empty"}}]}}
REQUIREMENTS:
{reqs}
RESUME:
<<<
{resume}
>>>"""
RESUME_REWRITE = """Rewrite the RESUME for the job below. Keep every job, employer, date, title, school and number
exactly as in the resume. Put the experience that matches the job first and use the posting's words where the
resume shows the same thing. Don't add any skill, tool, certificate, number or result the resume doesn't have;
for a requirement it doesn't show, add nothing. Start with a 2-3 sentence summary built only from the resume.
Markdown, the same sections the resume has.{wish}
JOB: {title}
REQUIREMENTS THE RESUME SHOWS: {shown}
<<<
{resume}
>>>"""
RESUME_LETTER = """Write a cover letter (under 350 words) for this job, using only these facts from the resume.
Put [YOUR NAME], [HIRING MANAGER], [DATE] and other unknowns in square brackets. Don't claim anything the
facts don't show; it's fine to say you're keen to learn something.{wish}
JOB: {title} at {company}
FACTS FROM THE RESUME (word for word):
{facts}
POSTING (for its words and what it values):
<<<
{posting}
>>>"""
_POSTING_NAME = re.compile(r"(?i)job|posting|post|advert|\bad\b|description|\bjd\b|listing|vacancy|opening|role|position")
_RESUME_NAME = re.compile(r"(?i)resume|résumé|\bcv\b|curriculum")
_NUM = re.compile(r"(?<![\w.])(?:[$£€]\s?)?\d[\d,.]*\s?(?:%|percent|k\b|m\b)?")


def pick_resume_and_posting(files: list[Path], box: str) -> tuple[Path, Path | None]:
    """Which file is the resume and which (if any) is the posting. Raises ValueError in plain words."""
    if len(files) == 1:
        if len(box.split()) < 25:
            raise ValueError("add the job posting: paste it in the box, or add it as a second file "
                             "(name it something like job-posting.txt)")
        return files[0], None
    if len(files) > 2:
        raise ValueError("give one resume and at most one job posting at a time")
    a, b = files
    for x, y in ((a, b), (b, a)):
        if _POSTING_NAME.search(y.stem) and not _POSTING_NAME.search(x.stem):
            return x, y
        if _RESUME_NAME.search(x.stem) and not _RESUME_NAME.search(y.stem):
            return x, y
    raise ValueError("Joe can't tell which file is the resume: put 'resume' in its name, or 'job' in the posting's")


_STOP = {"and", "the", "for", "with", "you", "your", "our", "are", "will", "have", "has", "can", "able", "from",
         "years", "year", "experience", "skills", "skill", "knowledge", "strong", "good", "great", "plus", "must"}


def _stem(w: str) -> str:
    w = re.sub(r"[^0-9a-z+#]", "", w.lower())
    for suf in ("ing", "ed", "es", "er", "s", "e"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[:-len(suf)]
    return w


def _stems(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[\w+#]+", text.lower())}


def backed(term: str, source: str) -> bool:
    """Is this skill or requirement in the person's own words? Word for word, or every main word in
    another form ('scheduling' is backed by 'ran the schedule')."""
    if found_in(term, source):
        return True
    words = [w for w in re.findall(r"[\w+#]+", term.lower()) if len(w) > 2 and w not in _STOP]
    have = _stems(source)
    return bool(words) and all(_stem(w) in have for w in words)


def resume_line_for(req: str, resume: str) -> str:
    """Joe's own look for a resume line that shows a requirement (when the AI's quote wasn't real)."""
    for line in resume.splitlines():
        line = line.strip(" -*•\t")
        if len(line) > 3 and backed(req, line):
            return line
    return ""


def mark_unbacked(text: str, source: str, terms: list[str]) -> tuple[str, list[str]]:
    """Joe's honesty check: numbers that aren't in the source, and posting words the source doesn't
    have, get [CHECK] right after them. Returns (marked text, what was marked)."""
    marked: list[str] = []
    src_n = _norm(source)

    def num(m: re.Match) -> str:
        s = m.group(0).strip()
        core = re.sub(r"[^\d.]", "", s).strip(".")
        if not core or len(core) < 2 or core in src_n.replace(",", "") or _norm(s) in src_n:
            return m.group(0)
        marked.append(s)
        return m.group(0) + " [CHECK: not in your resume]"
    out = _NUM.sub(num, text)
    for t in sorted({" ".join(str(x).split()) for x in terms if 2 < len(str(x).strip()) <= 40}, key=len, reverse=True):
        if backed(t, source):
            continue
        rx = re.compile(r"(?<!\w)" + re.escape(t) + r"(?!\w)(?! \[CHECK)", re.I)
        if rx.search(out):
            marked.append(t)
            out = rx.sub(lambda m: m.group(0) + " [CHECK: not in your resume]", out, count=1)
    return out, marked


def run_resume_tailor(engine: "Engine", mission: "Mission", job: "Job", st: "JobState") -> "JobState":
    from .engine import PartFailed, Stopped
    from .tools import _finish, chosen_options
    got = _begin(engine, job, st, "a resume (and the job posting)", need_text=True)
    if not isinstance(got, tuple):
        return got
    files, folder = got
    box = job.format.strip()
    try:
        cv, post = pick_resume_and_posting(files, box)
        resume = _read_doc(engine, cv)
        posting = _read_doc(engine, post) if post else box
    except (ValueError, OSError) as e:
        return _fail(engine, job, st, str(e))
    wish = f"\nThe person also asked: {box}" if post and box else ""
    ask = _asker(engine, job, st)
    model = _model(engine)
    opts = chosen_options(job)
    stem = re.sub(r"[^\w-]+", "-", cv.stem.lower()).strip("-") or "resume"
    try:
        engine._progress(f"{job.name}: reading the job posting")
        reqs = _ask_json(ask, "resume", RESUME_SYSTEM + " Reply with ONLY JSON.", RESUME_REQS.format(text=posting[:30000]))
        reqs = reqs if isinstance(reqs, dict) else {}
        must = [str(x).strip() for x in reqs.get("must") or [] if str(x).strip()][:25]
        nice = [str(x).strip() for x in reqs.get("nice") or [] if str(x).strip()][:15]
        keywords = [str(x).strip() for x in reqs.get("keywords") or [] if str(x).strip()][:40]
        title = " ".join(str(reqs.get("title") or "this job").split())
        company = " ".join(str(reqs.get("company") or "[COMPANY]").split())
        engine._progress(f"{job.name}: matching your resume")
        got = _ask_json(ask, "resume", RESUME_SYSTEM + " Reply with ONLY JSON.", RESUME_MATCH.format(
            reqs="\n".join(f"- {r}" for r in must + nice), resume=resume[:30000]))
        matches = {}
        for m in (got or {}).get("matches", []) if isinstance(got, dict) else []:
            if isinstance(m, dict) and str(m.get("requirement") or "").strip():
                ev = " ".join(str(m.get("evidence") or "").split())
                matches[_norm(m["requirement"])] = ev if ev and found_in(ev, resume) else ""   # quotes are checked
        for r in must + nice:                     # a quote that wasn't real: Joe looks for the line himself
            if not matches.get(_norm(r)):
                matches[_norm(r)] = resume_line_for(r, resume)
        shown = [r for r in must + nice if matches.get(_norm(r))]
        engine._progress(f"{job.name}: writing the tailored resume")
        tailored = ask("resume", RESUME_SYSTEM + " Markdown.", RESUME_REWRITE.format(
            wish=wish, title=title, shown="; ".join(shown) or "none clearly", resume=resume[:30000]), 100)
        letter = ""
        if "letter" in opts:
            engine._progress(f"{job.name}: writing the cover letter")
            facts = "\n".join(f"- {matches[_norm(r)]}" for r in shown) or "- (the resume, below)\n" + resume[:4000]
            letter = ask("resume", RESUME_SYSTEM, RESUME_LETTER.format(wish=wish, title=title, company=company,
                                                                         facts=facts, posting=posting[:8000]), 100)
    except Stopped:
        return _stopped(engine, job, st, 1, "resume(s)")
    except PartFailed as e:
        return _fail(engine, job, st, str(e))
    terms = must + nice + keywords
    tailored, m1 = mark_unbacked(tailored, resume, terms)
    _save(folder, st, f"{stem}-tailored.md", _ai_note("Tailored", model) + tailored.strip(), cv.name)
    made = [f"{stem}-tailored.md"]
    if letter:
        letter, m2 = mark_unbacked(letter, resume + "\n" + posting, [t for t in terms if not backed(t, posting)])
        _save(folder, st, "cover-letter.md", _ai_note("Written", model, "Fill in the [brackets].") + letter.strip(), "cover letter")
        made.append("cover-letter.md")
    rows = []
    for r in must + nice:
        ev = matches.get(_norm(r), "")
        rows.append([("Must have: " if r in must else "Nice to have: ") + r,
                     f"Yes: \"{ev[:160]}\"" if ev else "Not shown in your resume [CHECK]"])
    gaps = [r for r in must if not matches.get(_norm(r))]
    report = [f"# How your resume matches: {title}", "",
              "Joe checked each thing the job asks for against your resume. Quotes are copied from your resume and "
              "checked word for word. Nothing was invented: where your resume doesn't show something, it says so.", "",
              _table(["The job asks for", "In your resume?"], rows) if rows else "The posting's requirements couldn't be read [CHECK].", ""]
    if gaps:
        report += ["## Gaps to think about", "",
                   "If you DO have these, add them to your resume in your own words and run Joe again. If not, it's "
                   "fine: the cover letter doesn't claim them.", ""] + [f"- {g}" for g in gaps] + [""]
    if m1:
        report += ["## Joe marked these in the tailored resume", "",
                   "They aren't in your original resume, so check them (delete them if they're not true):", ""] + \
                  [f"- {x}" for x in dict.fromkeys(m1)] + [""]
    _save(folder, st, "match-report.md", "\n".join(report), "match report")
    made.append("match-report.md")
    if "word" in opts:
        from .addons import export_document, pandoc_exe
        pandoc = pandoc_exe(getattr(engine.s, "pandoc", ""))
        if pandoc:
            for md in [f"{stem}-tailored.md"] + (["cover-letter.md"] if letter else []):
                try:
                    for p in export_document(folder / md, ["docx"], pandoc, engine.log, engine.s):
                        st.media_files.append(p.name)
                        made.append(p.name)
                except Exception as e:                  # noqa: BLE001 (the .md is still there)
                    engine.log(f"  Word copy of {md} skipped: {e}")
        else:
            engine.log("  Word copies skipped: Pandoc isn't installed (Setup > System check).")
    st.titles.append("resume")
    st.items += 1
    engine.log(f"  {cv.name} -> {', '.join(made)}")
    return _finish(engine, job, st, 1, [])


# =========================================================================== 7. Mail merge
_HOLE = re.compile(r"\{\{\s*([^{}\n]{1,60}?)\s*\}\}|\{\s*([^{}\n]{1,60}?)\s*\}|<<\s*([^<>\n]{1,60}?)\s*>>|«\s*([^«»\n]{1,60}?)\s*»")


def holes(text: str) -> list[str]:
    return list(dict.fromkeys(next(g for g in m.groups() if g) for m in _HOLE.finditer(text)))


def merge_spans(text: str, row: dict[str, str], cols: dict[str, str], mark: bool,
                missing: set[str]) -> list[tuple[int, int, str]]:
    """Where each {Name} goes and what it becomes for this row."""
    out = []
    for m in _HOLE.finditer(text):
        name = next(g for g in m.groups() if g)
        col = cols.get(_key_norm(name))
        if col is None:
            continue                                     # not a column: left as it is (and listed)
        v = (row.get(col) or "").strip()
        if not v:
            missing.add(col)
            v = f"[CHECK: no {col}]" if mark else ""
        out.append((m.start(), m.end(), v))
    return out


def _file_part(s: str) -> str:
    s = re.sub(r"[^\w\s-]", "", str(s or ""), flags=re.UNICODE).strip().lower()
    return re.sub(r"[\s_-]+", "-", s)[:40].strip("-")


def _name_col(header: list[str]) -> list[str]:
    low = {_key_norm(h): h for h in header}
    for keys in (("fullname", "name"), ("firstname", "lastname"), ("company", "business", "organization"), ("email",)):
        got = [low[k] for k in keys if k in low]
        if got:
            return got
    return header[:1]


def docx_join(parts: list[Path], dest: Path) -> None:
    """One Word file with every letter, each starting on a new page (body of the first file's layout)."""
    bodies = []
    with zipfile.ZipFile(parts[0]) as z0:
        xml0 = z0.read("word/document.xml").decode("utf-8")
    for p in parts:
        with zipfile.ZipFile(p) as z:
            xml = z.read("word/document.xml").decode("utf-8")
        inner = xml[xml.index(">", xml.index("<w:body")) + 1:xml.rindex("</w:body>")]
        inner = re.sub(r"<w:sectPr\b(?:(?!<w:sectPr\b).)*?</w:sectPr>\s*$", "", inner, flags=re.S)
        bodies.append(inner)
    brk = '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'
    a = xml0.index(">", xml0.index("<w:body")) + 1
    tail = re.search(r"<w:sectPr\b(?:(?!<w:sectPr\b).)*?</w:sectPr>\s*</w:body>", xml0, re.S)
    new = xml0[:a] + brk.join(bodies) + (tail.group(0) if tail else "</w:body>") + xml0[xml0.rindex("</w:body>") + 9:]
    tmp = dest.with_name(dest.name + ".part")
    with zipfile.ZipFile(parts[0]) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            zout.writestr(info, new.encode("utf-8") if info.filename == "word/document.xml" else zin.read(info.filename))
    tmp.replace(dest)


def run_mail_merge(engine: "Engine", mission: "Mission", job: "Job", st: "JobState") -> "JobState":
    from .engine import Stopped
    from .sheets import SheetError, read_table
    from .tools import _finish, chosen_options
    got = _begin(engine, job, st, "a letter and a spreadsheet")
    if not isinstance(got, tuple):
        return got
    files, folder = got
    letters = [f for f in files if f.suffix.lower() in LETTER_EXT]
    sheets = [f for f in files if f.suffix.lower() in MERGE_SHEET_EXT]
    if len(letters) != 1 or len(sheets) != 1:
        return _fail(engine, job, st, "give one letter (.docx, .txt or .md) and one spreadsheet (.csv or .xlsx) "
                     f"(got {len(letters)} letter(s) and {len(sheets)} spreadsheet(s))")
    letter, sheet = letters[0], sheets[0]
    opts = chosen_options(job)
    try:
        header, rows, cut = read_table(sheet)
        is_docx = letter.suffix.lower() == ".docx"
        text = docx_text(letter) if is_docx else _read_doc(engine, letter)
    except (SheetError, ValueError, OSError, zipfile.BadZipFile, KeyError) as e:
        return _fail(engine, job, st, str(e))
    if is_docx:                                  # headers and footers can have {Name} too
        with zipfile.ZipFile(letter) as z:
            for n in z.namelist():
                if DOCX_TEXT_PARTS.match(n) and n != "word/document.xml" and z.getinfo(n).file_size < DOCX_MAX:
                    t = z.read(n).decode("utf-8", "replace")
                    text += "\n" + "".join(_xml_text(m.group(2)) for m in _DOCX_TOKEN.finditer(t) if m.group(1))
    cols = {_key_norm(h): h for h in header if h.strip()}
    found = holes(text)
    known = [h for h in found if _key_norm(h) in cols]
    unknown = [h for h in found if _key_norm(h) not in cols]
    if not known:
        return _fail(engine, job, st, ("the letter has no {Name}-style spots that match the spreadsheet's columns. "
                                       f"Its columns are: {', '.join(header)[:200]}. Put a column name in curly "
                                       "brackets where it should go, like Dear {" + (header[0] if header else "Name") + "},"))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if len(rows) > 5000:
        return _fail(engine, job, st, "that's over 5,000 rows: split the spreadsheet into smaller ones")
    ext = letter.suffix.lower() if letter.suffix.lower() in (".docx", ".txt", ".md") else ".txt"
    name_cols = _name_col(header)
    missing: set[str] = set()
    made: list[Path] = []
    sub = folder / "letters"
    sub.mkdir(exist_ok=True)
    width = max(3, len(str(len(rows))))
    try:
        for i, r in enumerate(rows, 1):
            if engine.stop.is_set():
                raise Stopped()
            row = {h: (r[k] if k < len(r) else "") for k, h in enumerate(header)}
            label = _file_part(" ".join(row.get(c, "") for c in name_cols)) or "row"
            dest = sub / f"{i:0{width}d}-{label}{ext}"
            edit = lambda t: merge_spans(t, row, cols, "blank" not in opts, missing)  # noqa: E731
            if ext == ".docx":
                docx_rewrite(letter, dest, edit)
            else:
                new, last = [], 0
                for a, b, rep in edit(text):
                    new += [text[last:a], rep]
                    last = b
                new.append(text[last:])
                atomic_write_text(dest, "".join(new))
            made.append(dest)
            if i % 25 == 0:
                engine._progress(f"{job.name}: {i}/{len(rows)} letters")
    except Stopped:
        return _stopped(engine, job, st, len(rows), "letter(s)")
    except (ValueError, OSError, zipfile.BadZipFile) as e:
        return _fail(engine, job, st, f"{letter.name}: {e}")
    st.media_files += [f"letters/{p.name}" for p in made[:200]]
    if "one" in opts and made:
        allname = f"all-letters{ext}"
        if ext == ".docx":
            docx_join(made, folder / allname)
        else:
            sep = "\n\n---\n\n" if ext == ".md" else "\n\n" + "=" * 60 + "\n\n"
            atomic_write_text(folder / allname, sep.join(p.read_text(encoding="utf-8") for p in made))
        st.media_files.insert(0, allname)
    report = ["# Mail merge", "", f"Made {len(made)} letter(s) from {letter.name} and {sheet.name} (one per row), "
              "in the letters folder. Read a few before sending.", "",
              "Filled in from the spreadsheet: " + ", ".join("{" + h + "}" for h in known)]
    if unknown:
        report += ["", "Left as they were (no column with that name): " + ", ".join("{" + h + "}" for h in unknown) + " [CHECK]"]
    if missing:
        report += ["", "Some rows had nothing in: " + ", ".join(sorted(missing))
                   + (" (marked [CHECK: no ...] in those letters)" if "blank" not in opts else " (left blank)")]
    if cut:
        report += ["", "The spreadsheet was cut at 20,000 rows [CHECK]"]
    atomic_write_text(folder / "mail-merge-report.md", "\n".join(report) + "\n")
    st.media_files.append("mail-merge-report.md")
    if missing and "blank" not in opts:
        st.flags.append({"item": sheet.name, "flag": "[CHECK] empty cells in: " + ", ".join(sorted(missing))})
    st.titles.append("merge")
    st.items = len(made)
    engine.log(f"  {len(made)} letters -> letters/")
    return _finish(engine, job, st, 1, [])


# =========================================================================== 8. Picture descriptions (alt text)
ALT_SYSTEM = ("You write alt text: short descriptions of pictures for people who can't see them (screen readers) "
              "and for shop listings. Describe only what you can see. Never name or guess who a person is, or their "
              "age, race, health or feelings beyond what's plain (smiling is fine). Copy important visible words "
              "exactly. Never invent brands, places, materials or sizes. Reply with ONLY a JSON object.")
ALT_ASK = """{wish}Picture file: {name}
JSON: {{"alt": "one sentence, at most 125 characters, the most important thing first; don't start with 'image of' or 'picture of'",
"long": "2-4 sentences with more detail: what's where, colors, any words shown"}}"""
ALT_MAX = 125


def tidy_alt(s: str, limit: int = ALT_MAX) -> str:
    """Alt text the way screen readers like it: no 'Image of', a full stop, at most `limit` characters
    (cut at a word, never mid-word)."""
    t = " ".join(str(s or "").split()).strip(" \"'")
    t = re.sub(r"(?i)^(?:an? )?(?:image|picture|photo(?:graph)?|graphic) (?:of|showing|that shows)\s+", "", t)
    if t:
        t = t[0].upper() + t[1:]
    if len(t) > limit:
        t = t[:limit - 1].rsplit(" ", 1)[0].rstrip(",;:-") + "."
    if t and t[-1] not in ".!?":
        t += "." if len(t) < limit else ""
    return t


def run_alt_text(engine: "Engine", mission: "Mission", job: "Job", st: "JobState") -> "JobState":
    from .engine import Stopped
    from .sheets import write_csv
    from .tools import _finish, _key, _look, _read_rows, _vision_start, chosen_options, picture_b64
    got = _vision_start(engine, job, st, "pictures")
    if not isinstance(got, tuple):
        return got
    files, model, ffmpeg, folder = got
    opts = chosen_options(job)
    wish = f"What these pictures are for: {job.format.strip()}\n" if job.format.strip() else ""
    system = ALT_SYSTEM + (("\n" + job.rules.strip()) if job.rules.strip() else "")
    sheet = folder / "alt-text.csv"
    _, rows = _read_rows(sheet)
    failed: list[str] = []
    try:
        for i, src in enumerate(files):
            key = _key(engine, src)
            if key in st.titles:
                continue
            if engine.stop.is_set():
                raise Stopped()
            engine._progress(f"{job.name}: {i + 1}/{len(files)} {src.name}")
            try:
                img = picture_b64(ffmpeg, src, engine.meta / "tmp" / f"look-{job.job_id}.jpg", 1280)
            except (ValueError, OSError) as e:
                failed.append(f"{src.name}: {e}"[:200])
                continue
            o = _look(engine, job, st, i, "alt-text", system, ALT_ASK.format(wish=wish, name=src.name), img, model)
            alt = tidy_alt((o or {}).get("alt"))
            if not alt:
                failed.append(f"{src.name}: the model's answer didn't make sense")
                continue
            long = " ".join(str((o or {}).get("long") or "").split()) if "long" in opts else ""
            rows = [r for r in rows if r and r[0] != src.name] + [[src.name, safe_cell(alt), str(len(alt)), safe_cell(long)]]
            write_csv(sheet, ["File", "Alt text", "Characters", "Longer description"], rows)
            if "sidecar" in opts:
                atomic_write_text(folder / f"{src.stem}.txt", alt + ("\n\n" + long if long else "") + "\n")
            st.titles.append(key)
            st.items += 1
            st.words += count_words(alt + " " + long)
            engine._save_state(job, st)
            engine.log(f"  {src.name}: {alt}")
    except Stopped:
        return _stopped(engine, job, st, len(files), "picture(s)")
    doc = ["# Picture descriptions (alt text)", "",
           "Written by Joe from what the vision model could see. Read each one: AI can be wrong, and it never "
           "names people. Paste the short one into the 'alt text' or 'description' box of your website, shop or "
           "social post.", ""]
    for r in rows:
        doc += [f"## {r[0]}", "", f"**Alt text ({r[2]} characters):** {r[1]}", ""] + ([r[3], ""] if len(r) > 3 and r[3] else [])
    atomic_write_text(folder / "alt-text.md", "\n".join(doc))
    st.media_files = ["alt-text.csv", "alt-text.md"] + ([f"{f.stem}.txt" for f in files] if "sidecar" in opts else [])
    st.media_files = [m for m in st.media_files if (folder / m).exists()]
    return _finish(engine, job, st, len(files), failed)


# =========================================================================== 9. Duplicate photo finder
DUP_LEVELS = {"exact": -1, "close": 5, "loose": 12}       # most bits of 64 that may differ


def file_hash(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _gray(ffmpeg: str, src: Path, w: int, h: int) -> bytes | None:
    """The picture squeezed to w x h gray pixels (one byte each), by FFmpeg."""
    from .system import no_window_flags
    try:
        p = subprocess.run([ffmpeg, "-v", "error", "-i", str(src), "-frames:v", "1",
                            "-vf", f"scale={w}:{h}:flags=area,format=gray", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                           capture_output=True, timeout=120, creationflags=no_window_flags())
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout if p.returncode == 0 and len(p.stdout) >= w * h else None


def dhash(px: bytes) -> int:
    """64-bit 'difference hash' from 9x8 gray pixels: each bit = is this pixel brighter than the next."""
    bits = 0
    for r in range(8):
        row = px[r * 9:(r + 1) * 9]
        for c in range(8):
            bits = (bits << 1) | (1 if row[c] > row[c + 1] else 0)
    return bits


def sharpness(px: bytes, w: int, h: int) -> float:
    """How sharp a gray picture is (spread of a simple edge filter): blurry shots score low."""
    vals = []
    for y in range(1, h - 1):
        o = y * w
        for x in range(1, w - 1, 2):
            i = o + x
            vals.append(4 * px[i] - px[i - 1] - px[i + 1] - px[i - w] - px[i + w])
    if not vals:
        return 0.0
    m = sum(vals) / len(vals)
    return sum((v - m) ** 2 for v in vals) / len(vals)


def group_photos(infos: list[dict], level: str) -> list[list[dict]]:
    """Groups of 2+ copies: same bytes always; with 'close'/'loose', also pictures whose hashes differ
    by only a few bits (resized, re-saved, burst shots)."""
    parent = list(range(len(infos)))

    def top(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    by_sha: dict[str, int] = {}
    for i, f in enumerate(infos):
        if f["sha"] in by_sha:
            parent[top(i)] = top(by_sha[f["sha"]])
        else:
            by_sha[f["sha"]] = i
    limit = DUP_LEVELS.get(level, 5)
    if limit >= 0:
        hashed = [i for i, f in enumerate(infos) if f.get("hash") is not None]
        for a_i, a in enumerate(hashed):
            fa = infos[a]
            for b in hashed[a_i + 1:]:
                fb = infos[b]
                if bin(fa["hash"] ^ fb["hash"]).count("1") > limit:
                    continue
                ra, rb = fa.get("ratio"), fb.get("ratio")
                if level == "close" and ra and rb and abs(ra - rb) > 0.03 * max(ra, rb):
                    continue                              # a different crop, not a copy
                parent[top(b)] = top(a)
    groups: dict[int, list[dict]] = {}
    for i, f in enumerate(infos):
        groups.setdefault(top(i), []).append(f)
    return [g for g in groups.values() if len(g) > 1]


_COPY_NAME = re.compile(r"(?i)copy|\(\d+\)|[-_ ]\d{1,2}$|edited|whatsapp|screenshot")


def best_photo(group: list[dict]) -> tuple[dict, str]:
    """The one to keep: most pixels, then sharpest, then biggest file, then the 'original' name."""
    def score(f):
        return (f.get("w", 0) * f.get("h", 0), round(f.get("sharp", 0.0), 1), f["size"],
                0 if _COPY_NAME.search(f["path"].stem) else 1, -len(f["path"].name))
    ranked = sorted(group, key=score, reverse=True)
    keep, second = ranked[0], ranked[1]
    if keep.get("w", 0) * keep.get("h", 0) > second.get("w", 0) * second.get("h", 0):
        why = f"the biggest picture ({keep['w']}x{keep['h']})"
    elif round(keep.get("sharp", 0), 1) > round(second.get("sharp", 0), 1) * 1.05:
        why = "the sharpest"
    elif keep["size"] > second["size"]:
        why = "the most detail kept (biggest file)"
    elif all(f["sha"] == keep["sha"] for f in group):
        why = "exact copies: any one will do (the plainest name)"
    else:
        why = "about the same: the plainest name"
    return keep, why


def contact_sheet(ffmpeg: str, photos: list[Path], dest: Path) -> bool:
    """The group side by side (the keeper first), 320 px squares on white."""
    from .system import no_window_flags
    photos = photos[:6]
    args = [ffmpeg, "-y", "-v", "error"]
    for p in photos:
        args += ["-i", str(p)]
    chains = [f"[{i}:v]scale=320:320:force_original_aspect_ratio=decrease,pad=320:320:(ow-iw)/2:(oh-ih)/2:color=white,"
              f"setsar=1,format=yuvj420p[p{i}]" for i in range(len(photos))]
    graph = ";".join(chains) + ";" + "".join(f"[p{i}]" for i in range(len(photos))) + f"hstack=inputs={len(photos)}[out]"
    try:
        p = subprocess.run(args + ["-filter_complex", graph, "-map", "[out]", "-frames:v", "1", "-q:v", "4", str(dest)],
                           capture_output=True, timeout=180, creationflags=no_window_flags())
    except (OSError, subprocess.SubprocessError):
        return False
    return p.returncode == 0 and dest.exists()


def run_duplicate_photos(engine: "Engine", mission: "Mission", job: "Job", st: "JobState") -> "JobState":
    from .doctor import ffmpeg_exe
    from .engine import Stopped
    from .sheets import write_csv
    from .tools import _finish, _key, chosen_options, image_size, option_value
    got = _begin(engine, job, st, "photos to check")
    if not isinstance(got, tuple):
        return got
    files, folder = got
    if len(files) > 20000:
        return _fail(engine, job, st, "that's over 20,000 photos: check one folder at a time")
    ffmpeg = ffmpeg_exe(engine.s.comfy.ffmpeg)
    level = option_value(job, "how") or "close"
    opts = chosen_options(job)
    if not ffmpeg and level != "exact":
        engine.log("  FFmpeg isn't installed, so only exact copies can be found (Setup > System check installs it).")
        level = "exact"
    infos: list[dict] = []
    failed: list[str] = []
    try:
        for i, src in enumerate(files):
            if engine.stop.is_set():
                raise Stopped()
            if i % 20 == 0:
                engine._progress(f"{job.name}: looking at {i + 1}/{len(files)}")
            try:
                f = {"path": src, "key": _key(engine, src), "size": src.stat().st_size, "sha": file_hash(src)}
            except OSError as e:
                failed.append(f"{src.name}: {e}"[:200])
                continue
            if ffmpeg:
                dims = image_size(ffmpeg, src)
                if dims:
                    f["w"], f["h"] = dims
                    f["ratio"] = dims[0] / dims[1] if dims[1] else None
                if level != "exact":
                    px = _gray(ffmpeg, src, 9, 8)
                    f["hash"] = dhash(px) if px else None
            infos.append(f)
    except Stopped:
        return _stopped(engine, job, st, len(files), "photo(s)")
    groups = group_photos(infos, level)
    if ffmpeg:
        for g in groups:
            for f in g:
                px = _gray(ffmpeg, f["path"], 256, 256)
                f["sharp"] = sharpness(px, 256, 256) if px else 0.0
    rows: list[list[str]] = []
    md = ["# Duplicate photos", "",
          f"Joe checked {len(infos)} photo(s) and found **{len(groups)} group(s)** of copies "
          f"({ {'exact': 'exact copies only', 'close': 'copies, including resized or re-saved ones', 'loose': 'similar shots too'}[level]}). "
          "**Nothing was moved or deleted.** Look at each group, then delete the extras yourself if you agree.", ""]
    spare = 0
    keepers: list[Path] = []
    in_group: set[Path] = set()
    for n, g in enumerate(sorted(groups, key=lambda g: -len(g)), 1):
        keep, why = best_photo(g)
        others = [f for f in g if f is not keep]
        spare += sum(f["size"] for f in others)
        keepers.append(keep["path"])
        in_group.update(f["path"] for f in g)
        md += [f"## Group {n} ({len(g)} photos)", "", f"**Keep:** {keep['key']}: {why}", ""]
        md += [f"- could go: {f['key']} ({_mb(f['size'])}" + (f", {f['w']}x{f['h']}" if f.get("w") else "")
               + (", exact copy" if f["sha"] == keep["sha"] else "") + ")" for f in others]
        if "sheets" in opts and ffmpeg:
            pic = f"group-{n:03d}.jpg"
            if contact_sheet(ffmpeg, [keep["path"]] + [f["path"] for f in others], folder / pic):
                md += ["", f"![Group {n}: the keeper first]({pic})"]
                st.media_files.append(pic)
        md.append("")
        for f in [keep] + others:
            rows.append([str(n), safe_cell(f["key"]), "keep" if f is keep else "could go", str(f.get("w", "")), str(f.get("h", "")),
                         str(f["size"]), why if f is keep else ("exact copy" if f["sha"] == keep["sha"] else "near copy")])
    if groups:
        md.insert(3, f"Deleting the extras would free about **{_mb(spare)}**.\n")
    else:
        md += ["No copies found. Try How alike: Similar shots to also catch burst photos."]
    if "copy" in opts:
        dest = folder / "keepers"
        dest.mkdir(exist_ok=True)
        n_copied = 0
        for f in infos:
            if f["path"] in in_group and f["path"] not in keepers:
                continue
            target = dest / f["path"].name
            k = 2
            while target.exists():
                target = dest / f"{f['path'].stem}_{k}{f['path'].suffix}"
                k += 1
            shutil.copy2(f["path"], target)
            n_copied += 1
        md += ["", f"The keepers folder has {n_copied} photo(s): the best of each group and every one-of-a-kind photo "
               "(copies; your photos stay where they are)."]
    atomic_write_text(folder / "duplicates.md", "\n".join(md) + "\n")
    write_csv(folder / "duplicates.csv", ["Group", "File", "Suggestion", "Width", "Height", "Bytes", "Why"], rows)
    st.media_files = ["duplicates.md", "duplicates.csv"] + st.media_files
    st.titles.append("photos")
    st.items = len(infos)
    engine.log(f"  {len(infos)} photos, {len(groups)} group(s) of copies, {_mb(spare)} could be freed")
    return _finish(engine, job, st, 1, failed)


# =========================================================================== dispatch + time guesses
def run(engine: "Engine", mission: "Mission", job: "Job", st: "JobState") -> "JobState":
    fn = {"pdf-tools": run_pdf_tools, "explain-letter": run_explain_letter, "hide-details": run_hide_details,
          "meeting-minutes": run_meeting_minutes, "bank-budget": run_bank_budget, "resume-tailor": run_resume_tailor,
          "mail-merge": run_mail_merge, "alt-text": run_alt_text, "duplicate-photos": run_duplicate_photos}[job.type]
    return fn(engine, mission, job, st)


def guess_seconds(job: "Job", files: list[Path], speeds: dict) -> float:
    """A rough run time for the plan screen (learned speeds replace the defaults)."""
    from .tools import _guess_words, chosen_options
    part = speeds.get("part", 25.0)
    t = job.type
    if t == "pdf-tools":
        return 2.0 + len(files) * 2.0
    if t == "explain-letter":
        return len(files) * part * (3 if "reply" in chosen_options(job) else 2)
    if t == "hide-details":
        ai = "names" in chosen_options(job)
        return sum(1 + (max(1, _guess_words(f) // HIDE_CHUNK_WORDS) * part if ai else 0) for f in files)
    if t == "meeting-minutes":
        secs = 0.0
        for f in files:
            if f.suffix.lower() in TRANSCRIPT_EXT:
                secs += max(1, _guess_words(f) // MIN_PIECE_WORDS + 1) * part
            else:
                try:
                    mb = f.stat().st_size / 1e6
                except OSError:
                    mb = 5
                minutes = mb * (0.5 if f.suffix.lower() == ".wav" else 1.0)
                secs += minutes * 60 * speeds.get("transcribe", 0.8) + max(2, minutes / 20 + 1) * part
        return secs
    if t == "bank-budget":
        return 3.0 + (2 * part if "ai" in chosen_options(job) else 0)
    if t == "resume-tailor":
        return part * (5 if "letter" in chosen_options(job) else 4)
    if t == "mail-merge":
        return 5.0
    if t == "alt-text":
        return len(files) * speeds.get("vision", 20.0)
    if t == "duplicate-photos":
        return len(files) * speeds.get("photo", 1.5) * 0.6
    return 0.0
