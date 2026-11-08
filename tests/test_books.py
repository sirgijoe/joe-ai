"""2.1 Find a book to read aloud (lookups faked: no internet in tests)."""
from __future__ import annotations

import json

from joeai import books
from joeai.engine import Engine
from joeai.mission import parse

from test_tools import app  # noqa: F401

PG = ("The Project Gutenberg eBook of Pride and Prejudice\n*** START OF THE PROJECT GUTENBERG EBOOK PRIDE AND PREJUDICE ***\n"
      "Chapter 1\n\nIt is a truth universally acknowledged...\n*** END OF THE PROJECT GUTENBERG EBOOK PRIDE AND PREJUDICE ***\nlicense")


def fake_get(url, timeout=20, limit=0):
    if "openlibrary.org" in url:
        if "isbn=9780141439518" in url or "Pride" in url:
            return json.dumps({"docs": [{"title": "Pride and Prejudice", "author_name": ["Jane Austen"],
                                         "first_publish_year": 1813}]}).encode()
        return json.dumps({"docs": [{"title": "A New Novel", "author_name": ["Someone Alive"]}]}).encode()
    if "gutendex.com" in url:
        if "Pride" in url:
            return json.dumps({"results": [{"id": 1342, "title": "Pride and Prejudice", "copyright": False,
                                            "authors": [{"name": "Austen, Jane"}],
                                            "formats": {"text/plain; charset=us-ascii": "https://www.gutenberg.org/x.txt"}}]}).encode()
        return json.dumps({"results": []}).encode()
    if url.endswith(".txt"):
        return PG.encode()
    raise OSError("unexpected " + url)


def _run(app, text):
    return Engine(app.settings, app.sb, log=lambda x: None).run_mission(parse(text))[0]


def test_isbn_check_digits():
    assert books.isbn_of("ISBN 978-0-14-143951-8") == "9780141439518"
    assert books.isbn_of("0-14-143951-3") == "0141439513"
    assert books.isbn_of("978-0-14-143951-9") == "" and books.isbn_of("call 555-1234") == ""
    assert books.strip_gutenberg(PG) == "Chapter 1\n\nIt is a truth universally acknowledged...\n"


def test_find_book_needs_lookups_on(app, monkeypatch):  # noqa: F811
    monkeypatch.delenv("JOE_OFFLINE", raising=False)
    st = _run(app, "TASK: B  TYPE: find-book\nFORMAT: Pride and Prejudice")
    assert st.status == "failed" and "online lookups" in st.note


def test_find_book_public_domain_and_copyright(app, monkeypatch):  # noqa: F811
    monkeypatch.delenv("JOE_OFFLINE", raising=False)
    monkeypatch.setattr(books, "_get", fake_get)
    app.settings.web.enabled = True
    st = _run(app, "TASK: B  TYPE: find-book\nFORMAT: 978-0-14-143951-8")
    assert st.status == "done", st.note
    got = (app.sb.inbox / "books" / "pride-and-prejudice.txt").read_text(encoding="utf-8")
    assert got.startswith("Chapter 1") and "license" not in got
    q = list((app.sb.missions / "Queue").glob("read-*.txt"))
    assert q and "TYPE: read-aloud" in q[0].read_text() and "INPUT: books/pride-and-prejudice.txt" in q[0].read_text()
    st = _run(app, "TASK: B2  TYPE: find-book\nFORMAT: A New Novel\nOPTIONS: aloud no")
    assert st.status == "done"
    note = (app.sb.output / st.output / "book.md").read_text(encoding="utf-8")
    assert "under copyright" in note and "Read scans and receipts" in note
