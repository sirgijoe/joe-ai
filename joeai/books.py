"""Find a book to read aloud (2.1): by ISBN, title or a photo of the cover or barcode.

Joe looks the book up in Open Library (title, author, year). If it's in the public domain and
Project Gutenberg has it, Joe downloads the plain text into Inbox/books and, if asked, queues
"Read a document aloud" for it. A book still under copyright can't be downloaded: Joe says so and
points to scanning your own copy's pages (Read scans and receipts), which he can read aloud.

Online, and only when Setup > Voice & Talk > online lookups is on: only the ISBN or title is sent.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .fsutil import atomic_write_text

if TYPE_CHECKING:
    from .engine import Engine, JobState
    from .mission import Job, Mission

UA = {"User-Agent": "joe-ai (open-source local helper; https://github.com/sirgijoe/joe-ai)"}
MAX_BOOK = 25 * 1024 * 1024
LOOK_SYSTEM = ("You read book covers and barcodes. Copy only what is printed. Reply with ONLY JSON.")
LOOK_ASK = ('Reply with ONLY JSON: {"isbn": "the ISBN digits if printed (often above or below the barcode), else empty", '
            '"title": "the book title if shown", "author": "the author if shown"}')


def isbn_of(text: str) -> str:
    """An ISBN-10/13 in the text (dashes and spaces allowed), checked with its check digit; '' if none."""
    for m in re.finditer(r"(?:97[89][\s-]?)?(?:\d[\s-]?){9}[\dXx]", text or ""):
        d = re.sub(r"[\s-]", "", m.group(0)).upper()
        if len(d) == 13 and d.isdigit() and sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(d)) % 10 == 0:
            return d
        if len(d) == 10 and d[:9].isdigit() and sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(d)) % 11 == 0:
            return d
    return ""


def _get(url: str, timeout: float = 20, limit: int = 2_000_000) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise ValueError("that file is too big")
    return data


def open_library(isbn: str = "", query: str = "", get=_get) -> dict | None:
    """{"title", "author", "year"} from Open Library, or None."""
    q = f"isbn={isbn}" if isbn else "q=" + urllib.parse.quote(query)
    data = json.loads(get(f"https://openlibrary.org/search.json?{q}&fields=title,author_name,first_publish_year&limit=1"))
    docs = data.get("docs") or []
    if not docs:
        return None
    d = docs[0]
    return {"title": d.get("title", ""), "author": ", ".join((d.get("author_name") or [])[:2]),
            "year": d.get("first_publish_year") or ""}


def gutenberg(title: str, author: str = "", get=_get) -> dict | None:
    """The best Project Gutenberg match with a plain-text copy: {"id", "title", "author", "url"} or None."""
    q = urllib.parse.quote(f"{title} {author.split(',')[0] if author else ''}".strip())
    data = json.loads(get(f"https://gutendex.com/books?search={q}"))
    want = re.sub(r"\W+", " ", title.lower()).strip()
    for b in data.get("results") or []:
        if b.get("copyright"):
            continue
        name = re.sub(r"\W+", " ", str(b.get("title", "")).lower()).strip()
        if want and not (name.startswith(want) or want.startswith(name[:max(8, len(want) // 2)])):
            continue
        fmts = b.get("formats") or {}
        url = next((u for k, u in fmts.items() if k.startswith("text/plain") and not u.endswith(".zip")), "")
        if url:
            who = "; ".join(a.get("name", "") for a in (b.get("authors") or [])[:2])
            return {"id": b.get("id"), "title": b.get("title", ""), "author": who, "url": url}
    return None


def strip_gutenberg(text: str) -> str:
    """The book itself, without Project Gutenberg's license header and footer (kept in a note)."""
    a = re.search(r"\*\*\*\s*START OF (?:THE|THIS) PROJECT GUTENBERG EBOOK[^\n]*\*\*\*", text, re.I)
    b = re.search(r"\*\*\*\s*END OF (?:THE|THIS) PROJECT GUTENBERG EBOOK", text, re.I)
    body = text[a.end() if a else 0:b.start() if b else len(text)]
    return body.strip() + "\n"


def run(engine: "Engine", mission: "Mission", job: "Job", st: "JobState") -> "JobState":
    import os
    from .tools import _finish, _look, find_vision_model, option_value, picture_b64, resolve_inputs, tool_dir
    from .doctor import ffmpeg_exe
    from .mission import slug
    w = getattr(engine.s, "web", None)
    if not w or not w.enabled or os.environ.get("JOE_OFFLINE"):
        st.status, st.note = "failed", ("finding a book needs online lookups (Setup > Voice & Talk > Let Joe look "
                                        "things up online). Only the ISBN or title is sent")
        engine.log(f"'{job.name}' failed: {st.note}")
        return st
    files, _ = resolve_inputs(engine, job)
    said = job.format.strip()
    isbn, title, author = isbn_of(said), "", ""
    if not isbn and said:
        title = said
    if files and not isbn:                                   # a photo of the cover or barcode
        if engine.services.handoff("text"):
            model = find_vision_model(engine)
            if model:
                try:
                    img = picture_b64(ffmpeg_exe(engine.s.comfy.ffmpeg), files[0],
                                      engine.meta / "tmp" / f"book-{job.job_id}.jpg", 1280)
                    o = _look(engine, job, st, 0, "find-book", LOOK_SYSTEM, LOOK_ASK, img, model) or {}
                    isbn = isbn_of(str(o.get("isbn", ""))) or isbn
                    title = title or str(o.get("title", "")).strip()
                    author = str(o.get("author", "")).strip()
                except (ValueError, OSError) as e:
                    engine.log(f"  {files[0].name}: {e}")
    if not isbn and not title:
        st.status, st.note = "failed", "type the ISBN or the title in the box, or add a clear photo of the cover or barcode"
        engine.log(f"'{job.name}' failed: {st.note}")
        return st
    folder = tool_dir(engine, job, st)
    st.status = "running"
    st.started = st.started or datetime.now().isoformat(timespec="seconds")
    engine._save_state(job, st)
    get = getattr(engine, "_book_get", _get)
    try:
        info = open_library(isbn=isbn, get=get) if isbn else open_library(query=f"{title} {author}".strip(), get=get)
    except (OSError, ValueError) as e:
        info = None
        engine.log(f"  Open Library: {e}")
    if info:
        title, author = info["title"] or title, info["author"] or author
    L = [f"# {title or isbn}", ""]
    if author:
        L += [f"By {author}" + (f", first published {info['year']}" if info and info.get("year") else ""), ""]
    try:
        gb = gutenberg(title, author, get=get) if title else None
    except (OSError, ValueError) as e:
        gb = None
        engine.log(f"  Project Gutenberg: {e}")
    if not gb:
        L += ["Joe couldn't find a free copy of this book. It's probably still under copyright (most books from "
              "the last 100 years are), so its text can't be downloaded.", "",
              "To hear it anyway: photograph or scan the pages of your own copy, run **Read scans and receipts** "
              "on them, then **Read a document aloud** on the text it makes."]
        atomic_write_text(folder / "book.md", "\n".join(L) + "\n")
        st.media_files.append("book.md")
        st.flags.append({"item": title or isbn, "flag": "[CHECK] no free copy found (likely under copyright)"})
        st.titles.append("lookup")
        return _finish(engine, job, st, 1, [])
    try:
        raw = get(gb["url"], timeout=60, limit=MAX_BOOK).decode("utf-8", "replace")
    except (OSError, ValueError) as e:
        st.status, st.note = "failed", f"couldn't download it from Project Gutenberg: {e}"
        engine.log(f"'{job.name}' failed: {st.note}")
        return st
    body = strip_gutenberg(raw)
    name = (slug(gb["title"])[:60] or "book") + ".txt"
    books = engine.sb.inbox / "books"
    books.mkdir(parents=True, exist_ok=True)
    atomic_write_text(books / name, body)
    atomic_write_text(folder / name, body)
    L += [f"Found a free, public-domain copy on Project Gutenberg (ebook #{gb['id']}): **{gb['title']}**"
          + (f" by {gb['author']}" if gb["author"] else "") + ".", "",
          f"Saved as Inbox/books/{name}. Project Gutenberg's license text was left off the copy; the book is "
          "free to read and share in the US (check your own country's rules if elsewhere).", ""]
    if option_value(job, "aloud") != "no":
        q = engine.sb.missions / "Queue"
        q.mkdir(parents=True, exist_ok=True)
        atomic_write_text(q / f"read-{slug(gb['title'])[:40] or 'book'}.txt",
                          f"TASK: {gb['title'][:60]} (read aloud)  TYPE: read-aloud\nINPUT: books/{name}\nOPTIONS: chapters\n")
        L += ["Joe queued **Read a document aloud** for it (one track per chapter)."]
    atomic_write_text(folder / "book.md", "\n".join(L) + "\n")
    st.media_files += [name, "book.md"]
    st.items = 1
    st.titles.append("lookup")
    engine.log(f"  Found {gb['title']} on Project Gutenberg -> Inbox/books/{name}")
    return _finish(engine, job, st, 1, [])
