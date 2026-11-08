"""2.1 file tools: calendar file, sort and rename, ask my spreadsheet."""
from __future__ import annotations

from datetime import datetime

from joeai import filetools, tools
from joeai.engine import Engine
from joeai.mission import parse

from test_tools import app  # noqa: F401


def _run(app, text):
    return Engine(app.settings, app.sb, log=lambda x: None).run_mission(parse(text))[0]


def test_ics_builder():
    text, problems = filetools.build_ics(
        [{"title": "Lunch, with Ann; ok", "date": "2026-12-01", "start": "12:30", "end": "12:00"},
         {"title": "Fair", "date": "2026-12-02"}, {"title": "x", "date": "tomorrow"}],
        [{"task": "Pay rent", "due": "2026-12-01"}], stamp=datetime(2026, 11, 8))
    assert text.startswith("BEGIN:VCALENDAR\r\n") and text.endswith("END:VCALENDAR\r\n")
    assert "SUMMARY:Lunch\\, with Ann\; ok" in text
    assert "DTSTART:20261201T123000" in text and "DTEND:20261201T133000" in text      # end before start: +1 h
    assert "DTSTART;VALUE=DATE:20261202" in text and "DTEND;VALUE=DATE:20261203" in text
    assert "BEGIN:VTODO" in text and "DUE;VALUE=DATE:20261201" in text
    assert problems == ["x: no clear date"]
    assert all(len(ln.encode()) <= 75 for ln in text.split("\r\n"))


def test_calendar_file_end_to_end(app):  # noqa: F811
    (app.sb.inbox / "notes.md").write_text("Dentist for Sam on Dec 1 at 3pm. Party Dec 5? Ann sends forms by the 20th.",
                                           encoding="utf-8")
    st = _run(app, "TASK: Cal  TYPE: calendar-file\nINPUT: notes.md")
    assert st.status == "done", st.note
    out = app.sb.output / st.output
    ics = (out / "calendar.ics").read_text(encoding="utf-8")
    assert ics.count("BEGIN:VEVENT") == 2 and "Party [CHECK]" in ics and "LOCATION:Main St\; Suite 2" in ics
    md = (out / "dates-and-todos.md").read_text(encoding="utf-8")
    assert "Send the forms (due 2026-11-20) - Ann" in md and "Someday: no clear date" in md


def test_sort_files_copies_and_names(app):  # noqa: F811
    (app.sb.inbox / "scan1-bill.txt").write_text("Electric company. Bill date 2026-03-02. Amount due $80.", encoding="utf-8")
    (app.sb.inbox / "letter.md").write_text("Dear parents, school starts...", encoding="utf-8")
    st = _run(app, "TASK: Sort  TYPE: sort-files\nINPUT: scan1-bill.txt, letter.md\nFORMAT: Bills, School")
    assert st.status == "done", st.note
    out = app.sb.output / st.output
    assert (out / "Bills" / "2026-03-02 Electric bill March.txt").exists()
    assert (out / "Letters" / "School letter.md").exists()
    assert (app.sb.inbox / "scan1-bill.txt").exists()                       # original left where it was
    assert any("not one of your categories" in f["flag"] for f in st.flags)
    assert "| scan1-bill.txt | Bills/2026-03-02 Electric bill March.txt |" in (out / "_sorted.md").read_text(encoding="utf-8")
    assert filetools.safe_name('a/b:c*"d') == "a b c d"


def test_query_math_is_joes():
    h = ["Month", "Product", "Price"]
    rows = [["2026-01", "Blue mug", "$12.50"], ["2026-01", "Bowl", "20"], ["2026-02", "Tall mug", "1,000"],
            ["2026-02", "Plate", ""]]
    r = filetools.run_query(h, rows, {"op": "sum", "column": "Price", "group_by": "Month", "sort": "desc"})
    assert r["rows"] == [("2026-02", 1000.0), ("2026-01", 32.5)] and r["skipped"] == 1
    assert r["how"] == "added up Price for each Month"
    r = filetools.run_query(h, rows, {"op": "count", "filters": [{"column": "Product", "is": "contains", "value": "MUG"}]})
    assert r["rows"] == [("All", 2.0)]
    r = filetools.run_query(h, rows, {"op": "max", "column": "Price", "filters": [{"column": "Price", "is": ">", "value": "15"}]})
    assert r["rows"] == [("All", 1000.0)]
    assert "no column" in filetools.run_query(h, rows, {"op": "sum", "column": "Cost"})["error"]
    d = [["2026-03-04", "5"], ["3/15/2026", "7"], ["2025-03-01", "9"]]
    r = filetools.run_query(["Date", "Amount"], d, {"op": "sum", "column": "Amount",
                                                    "filters": [{"column": "Date", "is": "month", "value": "2026-03"}]})
    assert r["rows"] == [("All", 12.0)]
    assert "<svg" in filetools.bar_svg([("A", 3.0), ("B", 1.5)], "Test")


def test_ask_sheet_end_to_end(app):  # noqa: F811
    (app.sb.inbox / "sales.csv").write_text("Month,Product,Price\n2026-01,Blue mug,12.50\n2026-01,Bowl,20\n"
                                            "2026-02,Tall mug,30\n", encoding="utf-8")
    st = _run(app, "TASK: Q  TYPE: ask-sheet\nINPUT: sales.csv\nFORMAT: Sales per month?\nHow much from mugs?\n"
                   "What was the weather?\nAverage nope?")
    assert st.status == "done", st.note
    out = app.sb.output / st.output
    a = (out / "sales-answers.md").read_text(encoding="utf-8")
    assert "| 2026-02 | 30 |" in a and "| 2026-01 | 32.50 |" in a and "sales-chart-1.svg" in a
    assert "**42.50**" in a and "the sheet has no weather" in a and "no column called 'Nope'" in a
    assert (out / "sales-chart-1.svg").exists()
    st = _run(app, "TASK: Q2  TYPE: ask-sheet\nINPUT: sales.csv")
    assert st.status == "failed" and "question" in st.note


def test_file_tools_listed():
    for tid in filetools.FILE_TOOLS:
        assert tools.TOOLS[tid].ready and f"TYPE: {tid}" in tools.planner_lines()
