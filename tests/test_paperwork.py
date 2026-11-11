"""2.2 everyday paperwork tools (paperwork.py): PDF toolkit, Explain this letter, Hide personal details,
Meeting minutes, Bank statement to budget, Resume tailor, Mail merge, Picture descriptions, Duplicate
photo finder. Plus the add-on '/' and '@' rule from the Fable review."""
from __future__ import annotations

import json
import shutil
import subprocess
import zipfile
from decimal import Decimal
from pathlib import Path

import pytest

from joeai import abilities, community, describe, paperwork, tools
from joeai.engine import Engine
from joeai.mission import MissionError, parse

from paper_files import make_docx, make_pdf
from test_tools import _pics, app, seeing, wav  # noqa: F401  (fixtures: fake Ollama + workspace)

QPDF = shutil.which("qpdf")
need_qpdf = pytest.mark.skipif(not QPDF, reason="needs qpdf")
FF = shutil.which("ffmpeg")


def _run(app, text, voice=False):  # noqa: F811
    return Engine(app.settings, app.sb, log=lambda x: None, voice=app.voice if voice else None).run_mission(parse(text))[0]


def _out(app, st):  # noqa: F811
    return app.sb.output / st.output


# --------------------------------------------------------------------------- all nine
def test_every_paperwork_tool_is_listed_explained_and_planned():
    lines = tools.planner_lines()
    for tid in paperwork.PAPER_TOOLS:
        t = tools.TOOLS[tid]
        assert t.ready and tid in abilities.STEPS and len(abilities.STEPS[tid]) == 3
        assert f"TYPE: {tid}" in lines and t.examples and len(t.help) > 200
        text = abilities.explain("tool:" + tid)["text"]
        assert "How Joe does it, step by step" in text and "Options" in text or not t.options
    assert tools.PAPER_GUESS == paperwork.PAPER_TOOLS
    assert "qpdf" in abilities.NEED_WORDS
    with pytest.raises(MissionError):
        parse("TASK: P  TYPE: pdf-tools\nINPUT: a.pdf\nOPTIONS: do shred")


def test_plain_summaries_for_the_plan_screen(app):  # noqa: F811
    make_pdf(app.sb.inbox / "a.pdf")
    make_pdf(app.sb.inbox / "b.pdf")
    chk = app.check("TASK: Join  TYPE: pdf-tools\nINPUT: a.pdf, b.pdf\nOPTIONS: do merge")
    assert chk["ok"], chk
    assert describe.plain_summary(chk) == ["Join 2 PDFs into one: Join"]
    (app.sb.inbox / "bill.txt").write_text("Pay $5.", encoding="utf-8")
    chk = app.check("TASK: Bill  TYPE: explain-letter\nINPUT: bill.txt\nOPTIONS: reply")
    assert describe.plain_summary(chk) == ["Explain 1 letter in plain words with a draft reply: Bill"]


def test_tool_status_and_needs_problem_name_qpdf(monkeypatch):
    st = {s["id"]: s for s in tools.tool_status({"ollama": True, "ffmpeg": True, "qpdf": False})}
    assert not st["pdf-tools"]["ok"] and "qpdf" in st["pdf-tools"]["why"]
    assert st["mail-merge"]["ok"] and st["bank-budget"]["ok"]
    monkeypatch.setattr(paperwork, "qpdf_exe", lambda configured="": None)
    job = parse("TASK: P  TYPE: pdf-tools\nINPUT: a.pdf\nOPTIONS: do merge").jobs[0]
    from joeai.config import Settings
    assert "qpdf" in tools.needs_problem(Settings(), job)
    job = parse("TASK: M  TYPE: meeting-minutes\nINPUT: call.srt\nOPTIONS: none").jobs[0]
    assert tools.needs_problem(Settings(), job) == ""              # a transcript needs no voice add-on


# --------------------------------------------------------------------------- 1. PDF toolkit
def test_page_words():
    assert paperwork.parse_pages("3, 1, 2", 5) == [3, 1, 2]
    assert paperwork.parse_pages("pages 2 to 4 and last", 6) == [2, 3, 4, 6]
    assert paperwork.parse_pages("odd", 5) == [1, 3, 5]
    assert paperwork.parse_pages("5-3", 5) == [5, 4, 3]
    assert paperwork.parse_pages("first, 2 - 3", 4) == [1, 2, 3]
    for bad in ("9", "abc", "0", ""):
        with pytest.raises(ValueError):
            paperwork.parse_pages(bad, 5)
    assert paperwork.split_groups("", 3) == [[1], [2], [3]]
    assert paperwork.split_groups("every 2 pages", 5) == [[1, 2], [3, 4], [5]]
    assert paperwork.split_groups("1-2; 3-5", 5) == [[1, 2], [3, 4, 5]]
    assert paperwork._pages_arg([3, 1]) == "3,1"                  # only digits ever reach qpdf


def test_qpdf_never_gets_an_at_argument(tmp_path):
    with pytest.raises(ValueError):
        paperwork._qpdf("qpdf", ["@" + str(tmp_path / "args.txt")])
    assert not paperwork._pdf_arg(Path("x.pdf")).startswith(("-", "@"))


def test_no_qpdf_says_how_to_get_it(app, monkeypatch):  # noqa: F811
    make_pdf(app.sb.inbox / "a.pdf")
    monkeypatch.setattr(paperwork, "qpdf_exe", lambda configured="": None)
    st = _run(app, "TASK: J  TYPE: pdf-tools\nINPUT: a.pdf\nOPTIONS: do compress")
    assert st.status == "failed" and "System check" in st.note and "qpdf" in st.note


def _pages_text(p: Path) -> list[str]:
    """Each page's words, read back with qpdf (content streams are plain text in these test PDFs)."""
    out = subprocess.run([QPDF, "--qdf", "--object-streams=disable", str(p), "-"], capture_output=True).stdout
    import re
    return re.findall(rb"\((.*?)\) Tj", out)


@need_qpdf
def test_pdf_join_split_pick_turn_and_shrink(app):  # noqa: F811
    a = make_pdf(app.sb.inbox / "a.pdf", ("Alpha one", "Alpha two", "Alpha three"))
    b = make_pdf(app.sb.inbox / "b.pdf", ("Bravo one",))
    before = a.read_bytes()
    st = _run(app, "TASK: Join  TYPE: pdf-tools\nINPUT: b.pdf, a.pdf\nOPTIONS: do merge")
    assert st.status == "done", st.note
    assert _pages_text(_out(app, st) / "joined.pdf") == [b"Bravo one", b"Alpha one", b"Alpha two", b"Alpha three"]
    assert "1. b.pdf" in (_out(app, st) / "pdf-report.md").read_text(encoding="utf-8")
    st = _run(app, "TASK: One  TYPE: pdf-tools\nINPUT: a.pdf\nOPTIONS: do merge")
    assert st.status == "failed" and "two or more" in st.note

    st = _run(app, "TASK: Split  TYPE: pdf-tools\nINPUT: a.pdf\nOPTIONS: do split\nFORMAT: 1-2, 3")
    out = _out(app, st)
    assert st.status == "done" and sorted(p.name for p in (out / "a").iterdir()) == ["a-page-3.pdf", "a-pages-1-2.pdf"]
    st = _run(app, "TASK: Pick  TYPE: pdf-tools\nINPUT: a.pdf\nOPTIONS: do pages\nFORMAT: 3, 1")
    assert _pages_text(_out(app, st) / "a-pages.pdf") == [b"Alpha three", b"Alpha one"]
    st = _run(app, "TASK: Bad  TYPE: pdf-tools\nINPUT: a.pdf\nOPTIONS: do pages\nFORMAT: 7")
    assert st.status == "failed" and "page 7 doesn't exist" in st.note
    st = _run(app, "TASK: Turn  TYPE: pdf-tools\nINPUT: a.pdf\nOPTIONS: do rotate, turn left\nFORMAT: 2")
    raw = subprocess.run([QPDF, "--qdf", "--object-streams=disable", str(_out(app, st) / "a-turned.pdf"), "-"],
                         capture_output=True).stdout
    assert st.status == "done" and raw.count(b"/Rotate") == 1 and (b"/Rotate 270" in raw or b"/Rotate -90" in raw)
    st = _run(app, "TASK: Small  TYPE: pdf-tools\nINPUT: a.pdf\nOPTIONS: do compress, shrink smaller")
    assert st.status == "done", st.note
    rep = (_out(app, st) / "pdf-report.md").read_text(encoding="utf-8")
    assert "smaller" in rep
    assert a.read_bytes() == before                                       # the original is never touched


@need_qpdf
def test_pdf_locked_and_damaged_are_explained(app):  # noqa: F811
    a = make_pdf(app.sb.inbox / "a.pdf", ("Alpha",))
    subprocess.run([QPDF, "--encrypt", "user", "owner", "256", "--", str(a), str(app.sb.inbox / "locked.pdf")], check=True)
    (app.sb.inbox / "broken.pdf").write_bytes(b"this is not a pdf")
    st = _run(app, "TASK: S  TYPE: pdf-tools\nINPUT: locked.pdf, broken.pdf, a.pdf\nOPTIONS: do compress")
    assert st.status == "partial"
    assert "password" in st.note and "damaged" in st.note


@need_qpdf
def test_pdf_form_list_then_fill(app):  # noqa: F811
    make_pdf(app.sb.inbox / "form.pdf", ("Form page",), form=True)
    st = _run(app, "TASK: Form  TYPE: pdf-tools\nINPUT: form.pdf\nOPTIONS: do fill")
    assert st.status == "done", st.note
    sheet = (_out(app, st) / "form-form-fields.txt").read_text(encoding="utf-8")
    assert "Full name: " in sheet and "Agree (tick box: yes or no): " in sheet and "Color (pick one: Red, Blue): " in sheet
    filled = sheet.replace("Full name: ", "Full name: Jane O'Neil").replace("(tick box: yes or no): ", "(tick box: yes or no): yes") \
        .replace("Red, Blue): ", "Red, Blue): blue")
    answers = paperwork.parse_answers(filled)
    assert answers == {"Full name": "Jane O'Neil", "Agree": "yes", "Color": "blue"}      # hints and notes dropped
    box = " | ".join(f"{k}: {v}" for k, v in answers.items()) + " | Shoe size: 9 | color: green"
    st = _run(app, f"TASK: Fill  TYPE: pdf-tools\nINPUT: form.pdf\nOPTIONS: do fill\nFORMAT: {box}")
    assert st.status == "done", st.note
    out = _out(app, st) / "form-filled.pdf"
    j = json.loads(subprocess.run([QPDF, "--json=2", "--json-key=acroform", str(out)], capture_output=True, text=True).stdout)
    vals = {f["fullname"]: f["value"] for f in j["acroform"]["fields"]}
    assert vals == {"Full name": "u:Jane O'Neil", "Agree": "/Yes", "Color": "u:Blue"}
    rep = (_out(app, st) / "pdf-report.md").read_text(encoding="utf-8")
    assert "3 field(s) filled" in rep and "'Shoe size': no field" in rep
    assert any("Shoe size" in f["flag"] for f in st.flags)
    assert not list(app.sb.root.rglob("form-answers-*.json"))                     # the answers file is cleaned up
    st = _run(app, "TASK: Lock  TYPE: pdf-tools\nINPUT: form.pdf\nOPTIONS: do fill, lock\nFORMAT: Full name: Jane")
    raw = subprocess.run([QPDF, "--qdf", "--object-streams=disable", str(_out(app, st) / "form-filled.pdf"), "-"],
                         capture_output=True).stdout
    assert st.status == "done" and b"/AcroForm" not in raw and b"(Jane)" in raw   # flattened: printed, can't be changed
    make_pdf(app.sb.inbox / "flat.pdf", ("No form",))
    st = _run(app, "TASK: Flat  TYPE: pdf-tools\nINPUT: flat.pdf\nOPTIONS: do fill\nFORMAT: Name: x")
    assert st.status == "failed" and "no fill-in boxes" in st.note


# --------------------------------------------------------------------------- 2. Explain this letter
LETTER = ("City Water\nAccount AC-77812\n\nYour bill of $84.20 is overdue. Please pay by December 15, 2099 "
          "or call 555-0100.\n")


def test_explain_letter_checks_every_number(app):  # noqa: F811
    (app.sb.inbox / "water bill.txt").write_text(LETTER, encoding="utf-8")
    st = _run(app, "TASK: Bill  TYPE: explain-letter\nINPUT: water bill.txt\nOPTIONS: reply, calendar\n"
                   "FORMAT: I want a payment plan")
    assert st.status == "done", st.note
    out = _out(app, st)
    assert sorted(p.name for p in out.iterdir()) == ["water-bill-deadlines.ics", "water-bill-explained.md",
                                                       "water-bill-reply.txt"]
    md = (out / "water-bill-explained.md").read_text(encoding="utf-8")
    assert "not legal or money advice" in md.lower().replace("isn't", "not")
    assert "| Pay the bill | December 15, 2099 |" in md and " days |" in md          # Joe counts the days
    assert "Dec 30th [CHECK]" in md                                    # not in the letter word for word
    assert "$84.20 |" in md and "$999.00 [CHECK]" in md                # an amount the letter doesn't have
    assert "AC-77812" in md and "## What to do next" in md and "## A reply you could send" in md
    assert "scam" not in md.lower()
    assert "payment plan" in (out / "water-bill-reply.txt").read_text(encoding="utf-8")
    ics = (out / "water-bill-deadlines.ics").read_text(encoding="utf-8")
    assert "Deadline: Pay the bill" in ics and "Deadline: Shut-off [CHECK]" in ics
    assert any("[CHECK]" in f["flag"] for f in st.flags)


def test_explain_letter_warns_about_scams_and_reads_photos(seeing):  # noqa: F811
    app = seeing
    (app.sb.inbox / "prize.txt").write_text("You won! Pay the fee with a gift card today.", encoding="utf-8")
    _pics(app.sb.inbox, "letter.png")
    st = _run(app, "TASK: Prize  TYPE: explain-letter\nINPUT: prize.txt, letter.png\nOPTIONS: none")
    assert st.status == "done", st.note
    md = (_out(app, st) / "prize-explained.md").read_text(encoding="utf-8")
    assert "## Be careful: this might be a scam" in md.split("## What this letter is")[0]
    assert not (_out(app, st) / "prize-reply.txt").exists()
    assert (_out(app, st) / "letter-explained.md").exists()


def test_days_left_words():
    from datetime import date
    assert paperwork.days_left(date(2026, 1, 3), date(2026, 1, 1)) == "2 days"
    assert paperwork.days_left(date(2026, 1, 1), date(2026, 1, 1)) == "today"
    assert "ago [CHECK]" in paperwork.days_left(date(2025, 12, 31), date(2026, 1, 1))


# --------------------------------------------------------------------------- 3. Hide personal details
def test_hide_patterns_find_the_usual_and_leave_money():
    t = ("Call (555) 123-4567 or +44 20 7946 0958, email sam.smith@example.com. Card 4111 1111 1111 1111, "
         "SSN 123-45-6789, account number: 12345678, policy no. AB-99812. I live at 42 Oak Tree Lane, Apt 3. "
         "Born on 03/14/1980. Total $1,234.56 due 2026-12-01, order 10 at 9.99, year 2025. Not a card: 4111 1111 1111 1112.")
    found = {t[a:b]: k for a, b, k in paperwork.hide_spans(t, paperwork.pattern_hits(t), [])}
    assert found == {"(555) 123-4567": "phone", "+44 20 7946 0958": "phone", "sam.smith@example.com": "email",
                     "4111 1111 1111 1111": "card", "123-45-6789": "ssn", "12345678": "number", "AB-99812": "number",
                     "42 Oak Tree Lane, Apt 3": "address", "03/14/1980": "birth", "4111 1111 1111 1112": "number"}
    assert paperwork.luhn_ok("4111111111111111") and not paperwork.luhn_ok("4111111111111112")


def test_hide_details_in_text_with_labels_box_and_key(app):  # noqa: F811
    src = app.sb.inbox / "note.txt"
    src.write_text("Maria Lopez called 555-123-4567 from Acme Bakery. Email maria@example.com.\n"
                   "Maria said the card is 4111 1111 1111 1111. Ask Rivera Co.", encoding="utf-8")
    st = _run(app, "TASK: Clean  TYPE: hide-details\nINPUT: note.txt\nOPTIONS: names, style labels, key\n"
                   "FORMAT: Rivera Co | keep: 555-123-4567")
    assert st.status == "done", st.note
    out = _out(app, st)
    clean = (out / "note-cleaned.txt").read_text(encoding="utf-8")
    assert clean == ("[NAME 1] called 555-123-4567 from Acme Bakery. Email [EMAIL 1].\n"
                     "[NAME 2] said the card is [CARD NUMBER]. Ask [HIDDEN 1].")
    report = (out / "what-was-hidden.md").read_text(encoding="utf-8")
    assert "Maria" not in report and "2 names" in report and "Kept as they are" in report
    key = (out / "KEEP-PRIVATE-label-key.md").read_text(encoding="utf-8")
    assert "[NAME 1] = Maria Lopez" in key and "Invented" not in key        # AI guesses not in the text: dropped
    assert src.read_text(encoding="utf-8").startswith("Maria Lopez")


def test_hide_details_in_word_keeps_formatting_and_blanks_authors(app):  # noqa: F811
    src = make_docx(app.sb.inbox / "letter.docx", [["Dear Maria ", "Lo", "pez,"], ["Write to maria@exa", "mple.com today."]],
                    author="Maria Lopez")
    before = src.read_bytes()
    st = _run(app, "TASK: W  TYPE: hide-details\nINPUT: letter.docx\nOPTIONS: names, style blocks")
    assert st.status == "done", st.note
    out = _out(app, st) / "letter-cleaned.docx"
    assert paperwork.docx_text(out) == "Dear ██████,\nWrite to ██████ today."
    with zipfile.ZipFile(out) as z:
        core = z.read("docProps/core.xml").decode()
        doc = z.read("word/document.xml").decode()
    assert "Maria" not in core and doc.count("<w:b/>") == 5                   # bold runs kept
    assert src.read_bytes() == before


def test_hide_details_in_word_reaches_the_places_the_page_doesnt_show(app):  # noqa: F811
    """Fable review 2026-11-11: an email hidden on the page was still in the link behind it, and names were
    left in the reviewer list, picture descriptions, field codes, drawings and the file's properties."""
    src = make_docx(app.sb.inbox / "linked.docx", [["Write to maria@example.com or call 269-555-0142."]],
                    author="Maria Lopez")
    with zipfile.ZipFile(src) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    doc = parts["word/document.xml"].decode()
    extra = ('<w:p><w:r><w:drawing><wp:docPr id="9" name="Picture 9" descr="C:\\Users\\Maria Lopez\\Pictures\\sig.png"/>'
             "<a:t>maria@example.com</a:t></w:drawing></w:r>"
             '<w:r><w:instrText xml:space="preserve"> HYPERLINK "mailto:maria@example.com" </w:instrText></w:r></w:p>')
    parts["word/document.xml"] = doc.replace("</w:body>", extra + "</w:body>").encode()
    parts["word/_rels/document.xml.rels"] = (
        '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId9" Type="http://x/hyperlink" Target="mailto:maria@example.com" TargetMode="External"/>'
        '<Relationship Id="rId8" Type="http://x/hyperlink" Target="https://example.org/help" TargetMode="External"/>'
        '<Relationship Id="rId7" Type="http://x/attachedTemplate" Target="file:///C:\\Users\\mlopez\\T.dotm" TargetMode="External"/>'
        "</Relationships>").encode()
    parts["word/people.xml"] = (b'<w15:people xmlns:w15="p"><w15:person w15:author="Maria Lopez"><w15:presenceInfo '
                                b'w15:providerId="AD" w15:userId="S::maria@example.com::1"/></w15:person></w15:people>')
    parts["docProps/app.xml"] = b"<Properties><Manager>Maria Lopez</Manager><Company>Lopez LLC</Company></Properties>"
    parts["docProps/custom.xml"] = b'<Properties><property name="Owner"><vt:lpwstr xmlns:vt="v">maria@example.com</vt:lpwstr></property></Properties>'
    parts["word/media/image1.png"] = b"not really a picture"
    with zipfile.ZipFile(src, "w", zipfile.ZIP_DEFLATED) as z:
        for n, d in parts.items():
            z.writestr(n, d)
    st = _run(app, "TASK: L  TYPE: hide-details\nINPUT: linked.docx\nOPTIONS: style labels\nFORMAT: Maria Lopez")
    assert st.status == "done", st.note
    out = _out(app, st)
    with zipfile.ZipFile(out / "linked-cleaned.docx") as z:
        everything = "\n".join(z.read(n).decode("utf-8", "replace") for n in z.namelist() if n.endswith((".xml", ".rels")))
        rels = z.read("word/_rels/document.xml.rels").decode()
    for left in ("maria@example.com", "Maria Lopez", "mlopez", "555-0142", "Lopez LLC"):
        assert left.lower() not in everything.lower(), left
    assert "https://example.org/help" in rels and "example.invalid/hidden" in rels      # other links untouched
    assert "1 picture(s) inside it" in (out / "what-was-hidden.md").read_text(encoding="utf-8")


def test_hide_patterns_addresses_in_capitals_and_town_lines():
    t = ("JOHN SMITH\n1234 MAPLE STREET APT 4\nBATTLE CREEK MI 49017-1234\nPO Box 77, Springfield, IL 62701\n"
         "123 Broadway, New York, NY 10001\nTotal $1,234.56 on 2026-11-11. I paid 20 in May.\n")
    found = [t[a:b] for a, b, k in paperwork.hide_spans(t, paperwork.pattern_hits(t), []) if k == "address"]
    assert found == ["1234 MAPLE STREET APT 4", "BATTLE CREEK MI 49017-1234", "PO Box 77", "Springfield, IL 62701",
                     "New York, NY 10001"]
    hits = [t[a:b] for a, b, k in paperwork.hide_spans(t, paperwork.pattern_hits(t), [])]
    assert not any("\n" in h for h in hits)                    # a find never runs across a line break
    assert "$1,234.56" not in hits and "2026-11-11" not in hits and "20 in May" not in " ".join(hits)


def test_hide_without_ai_still_finds_patterns(app):  # noqa: F811
    (app.sb.inbox / "list.csv").write_text("Name,Phone\nSam,555-987-6543\n", encoding="utf-8")
    st = _run(app, "TASK: P  TYPE: hide-details\nINPUT: list.csv\nOPTIONS: style labels")
    assert st.status == "done", st.note
    assert (_out(app, st) / "list-cleaned.csv").read_text(encoding="utf-8") == "Name,Phone\nSam,[PHONE 1]\n"


def test_docx_edit_spans_runs():
    xml = ('<w:p><w:r><w:t>Hello {Fi</w:t></w:r><w:r><w:t xml:space="preserve">rst} &amp; </w:t></w:r></w:p>'
           '<w:p><w:r><w:t>{First}</w:t></w:r></w:p>')
    new, n = paperwork.docx_edit_xml(xml, lambda t: [(m.start(), m.end(), "Ann <B>") for m in
                                                     __import__("re").finditer(r"\{First\}", t)])
    assert n == 2
    assert new == ('<w:p><w:r><w:t xml:space="preserve">Hello Ann &lt;B&gt;</w:t></w:r><w:r><w:t xml:space="preserve"> &amp; '
                   '</w:t></w:r></w:p><w:p><w:r><w:t xml:space="preserve">Ann &lt;B&gt;</w:t></w:r></w:p>')


# --------------------------------------------------------------------------- 4. Meeting minutes
def test_minutes_from_a_recording(app):  # noqa: F811
    wav(app.sb.inbox / "standup.wav")
    st = _run(app, "TASK: Minutes  TYPE: meeting-minutes\nINPUT: standup.wav\nOPTIONS: language english, transcript, calendar",
              voice=True)
    assert st.status == "done", st.note
    out = _out(app, st)
    assert sorted(p.name for p in out.iterdir()) == ["standup-minutes.md", "standup-todos.ics", "standup-transcript.txt"]
    md = (out / "standup-minutes.md").read_text(encoding="utf-8")
    assert "## Decisions\n\n- Ship the new mugs on Friday" in md
    assert "| Update the price list | Sam | Friday |" in md                       # heard: no [CHECK]
    assert "| Call the kiln repair | Bob [CHECK] |  |" in md                       # never said: checked
    assert "Sam, Priya [CHECK]" in md and "can't tell voices apart" in md
    assert "Update the price list (Sam)" in (out / "standup-todos.ics").read_text(encoding="utf-8")


def test_minutes_from_a_transcript_needs_no_voice(app):  # noqa: F811
    (app.sb.inbox / "call.srt").write_text("1\n00:00:01,000 --> 00:00:03,000\nSam will update the price list on Friday.\n",
                                           encoding="utf-8")
    st = _run(app, "TASK: M  TYPE: meeting-minutes\nINPUT: call.srt\nOPTIONS: none")
    assert st.status == "done", st.note
    assert sorted(p.name for p in _out(app, st).iterdir()) == ["call-minutes.md"]
    assert "00:00" not in paperwork._transcript_from_text(app.sb.inbox / "call.srt", None)


# --------------------------------------------------------------------------- 5. Bank statement to budget
def test_money_and_dates_the_way_banks_write_them():
    pm = paperwork.parse_money
    assert pm("$1,234.56") == Decimal("1234.56") and pm("(12.00)") == Decimal("-12.00")
    assert pm("12.00-") == Decimal("-12.00") and pm("1.234,56 €") == Decimal("1234.56")
    assert pm("45.10 DR") == Decimal("-45.10") and pm("") is None and pm("n/a") is None
    assert paperwork.date_order(["01/02/2026", "13/02/2026"]) == "dmy"
    assert str(paperwork.parse_day("02/03/2026", "dmy")) == "2026-03-02"
    assert str(paperwork.parse_day("02/03/2026")) == "2026-02-03"
    assert str(paperwork.parse_day("2026-02-03T10:00:00")) == "2026-02-03"
    assert paperwork.merchant_key("POS DEBIT NETFLIX.COM 866-579-7172 CA #1234") == "netflix.com"


BANK = """Date,Description,Amount
01/05/2026,PAYROLL ACME,"2,000.00"
01/06/2026,NETFLIX.COM 866-579-7172,-15.49
01/09/2026,KROGER #123,-82.10
01/20/2026,PET STORE 44,-30.00
02/05/2026,PAYROLL ACME,"2,000.00"
02/06/2026,NETFLIX.COM 866-579-7172,-17.99
02/11/2026,KROGER #123,-60.00
02/12/2026,MYSTERY SHOP,-12.00
02/15/2026,TRANSFER TO SAVINGS,-500.00
03/06/2026,NETFLIX.COM 866-579-7172,-17.99
"""


def test_bank_statement_to_budget(app):  # noqa: F811
    (app.sb.inbox / "checking.csv").write_text(BANK, encoding="utf-8")
    (app.sb.inbox / "card.csv").write_text("Posted Date,Payee,Debit,Credit\n13/02/2026,GYM CLUB,25.00,\n"
                                           "06/01/2026,NETFLIX.COM 866-579-7172,15.49,\n", encoding="utf-8")
    st = _run(app, "TASK: Budget  TYPE: bank-budget\nINPUT: checking.csv, card.csv\nOPTIONS: ai")
    assert st.status == "done", st.note
    out = _out(app, st)
    md = (out / "budget.md").read_text(encoding="utf-8")
    assert "| Money in | 4,000.00 |" in md                                      # transfers left out
    assert "| Money out | 260.57 |" in md
    assert "| Subscriptions | 51.47 |" in md and "| Groceries | 142.10 |" in md and "| Pets | 30.00 |" in md
    assert "| NETFLIX.COM 866-579-7172 | monthly | 17.99 | 215.88 | yes, by 2.50 (was 15.49) |" in md
    assert "1 transaction(s) were in more than one file" in md                # the card copy of January's Netflix
    assert "card.csv: dates were read day first" in md and "Other" in md
    from joeai.sheets import read_table
    h, rows, _ = read_table(out / "budget-transactions.csv")
    assert h == ["Date", "Description", "Amount", "Category", "Regular payment"]
    cats = {r[1]: r[3] for r in rows}
    assert cats["MYSTERY SHOP"] == "Other" and cats["TRANSFER TO SAVINGS"] == "Transfers" and cats["PAYROLL ACME"] == "Income"
    h2, rows2, _ = read_table(out / "budget-by-category.csv")
    assert h2[:4] == ["Category", "2026-01", "2026-02", "2026-03"]
    # the AI only ever saw shop names, never amounts
    assert all("82.10" not in p and "2,000" not in p for p in app_prompts(app))


def app_prompts(app):  # noqa: F811
    import gc
    from fake_ollama import FakeOllama
    fakes = [o for o in gc.get_objects() if isinstance(o, FakeOllama) and o.url == app.settings.ollama.url]
    return [p for p in fakes[0].prompts if "Categories:" in p]


def test_budget_without_amount_columns_explains(app):  # noqa: F811
    (app.sb.inbox / "x.csv").write_text("Name,Color\nA,Red\n", encoding="utf-8")
    st = _run(app, "TASK: B  TYPE: bank-budget\nINPUT: x.csv\nOPTIONS: none")
    assert st.status == "failed" and "Download the statement as CSV" in st.note


def test_budget_uses_the_statements_currency(app):  # noqa: F811
    (app.sb.inbox / "uk.csv").write_text("Date,Description,Amount\n2026-01-02,TESCO,-£10.50\n2026-01-03,PAY,£100.00\n",
                                         encoding="utf-8")
    st = _run(app, "TASK: B  TYPE: bank-budget\nINPUT: uk.csv\nOPTIONS: none")
    md = (_out(app, st) / "budget.md").read_text(encoding="utf-8")
    assert st.status == "done" and "| Money out | £10.50 |" in md and "| Groceries | £10.50 |" in md


def test_positive_only_card_statement_counts_as_spending():
    rows, notes = paperwork.read_statement(["Date", "Description", "Amount"], [["2026-01-01", "Shop", "10.00"]])
    assert rows[0]["amount"] == Decimal("-10.00") and "[CHECK]" in notes[0]


# --------------------------------------------------------------------------- 6. Resume tailor
RESUME = ("Pat Doe\n\nExperience\nOffice Lead, Corner Shop (2019-2024)\n- Ran the schedule for 12 staff\n"
          "- Kept the books in Excel\n\nEducation\nCommunity College, 2018\n")
POSTING = ("We are hiring an Office Manager at Acme Co. You will handle scheduling for the team, keep spreadsheets "
           "in Excel and QuickBooks, and drive the forklift sometimes. Spanish is a plus. Full time, on site.")


def test_resume_tailor_invents_nothing(app):  # noqa: F811
    (app.sb.inbox / "my resume.txt").write_text(RESUME, encoding="utf-8")
    st = _run(app, f"TASK: Job  TYPE: resume-tailor\nINPUT: my resume.txt\nOPTIONS: letter\nFORMAT: {POSTING}")
    assert st.status == "done", st.note
    out = _out(app, st)
    assert sorted(p.name for p in out.iterdir()) == ["cover-letter.md", "match-report.md", "my-resume-tailored.md"]
    cv = (out / "my-resume-tailored.md").read_text(encoding="utf-8")
    assert "40% [CHECK: not in your resume]" in cv and "QuickBooks [CHECK: not in your resume]" in cv
    assert "12 staff" in cv and "12 [CHECK" not in cv                          # in the resume: fine
    rep = (out / "match-report.md").read_text(encoding="utf-8")
    assert 'Yes: "Ran the schedule for 12 staff"' in rep
    assert '| Must have: Excel | Yes: "Kept the books in Excel" |' in rep      # the AI's quote wasn't real: Joe found it
    assert rep.split("## Gaps")[1].split("##")[0].count("- ") == 1 and "- Forklift license" in rep
    assert "Scheduling [CHECK" not in cv                                     # "ran the schedule" backs it
    letter = (out / "cover-letter.md").read_text(encoding="utf-8")
    assert "[HIRING MANAGER]" in letter and "QuickBooks" in letter


def test_resume_needs_the_posting(app):  # noqa: F811
    (app.sb.inbox / "cv.txt").write_text(RESUME, encoding="utf-8")
    st = _run(app, "TASK: J  TYPE: resume-tailor\nINPUT: cv.txt\nOPTIONS: letter")
    assert st.status == "failed" and "job posting" in st.note
    a, b = Path("my resume.docx"), Path("job ad.txt")
    assert paperwork.pick_resume_and_posting([b, a], "") == (a, b)
    with pytest.raises(ValueError):
        paperwork.pick_resume_and_posting([Path("one.txt"), Path("two.txt")], "")


def test_backed_words_in_other_forms():
    assert paperwork.backed("Scheduling", "Ran the schedule for 12 staff")
    assert not paperwork.backed("Forklift license", "Drove a van")
    assert paperwork.resume_line_for("Excel", "Pat\n- Kept the books in Excel\n") == "Kept the books in Excel"


def test_unbacked_words_are_marked():
    text, marked = paperwork.mark_unbacked("Led 12 people, cut costs 30%. Knows SQL and Excel.",
                                           "Led 12 people. Excel daily.", ["SQL", "Excel"])
    assert text == "Led 12 people, cut costs 30% [CHECK: not in your resume]. Knows SQL [CHECK: not in your resume] and Excel."
    assert marked == ["30%", "SQL"]


# --------------------------------------------------------------------------- 7. Mail merge
PEOPLE = "First name,Last name,Company,Order\nAnn,Lee,Acme,1001\nBo,Kim,,1002\nCy,Ray,Zeta,1003\n"


def test_mail_merge_word_letter(app):  # noqa: F811
    letter = make_docx(app.sb.inbox / "thanks.docx", [["Dear {First", " name}", ","], ["Your order <<Order>> from {Company} ships {Soon}."]],
                       header=["{Company} copy"])
    (app.sb.inbox / "people.csv").write_text(PEOPLE, encoding="utf-8")
    before = letter.read_bytes()
    st = _run(app, "TASK: Mail  TYPE: mail-merge\nINPUT: thanks.docx, people.csv\nOPTIONS: one")
    assert st.status == "done", st.note
    out = _out(app, st)
    names = sorted(p.name for p in (out / "letters").iterdir())
    assert names == ["001-ann-lee.docx", "002-bo-kim.docx", "003-cy-ray.docx"]
    assert paperwork.docx_text(out / "letters" / "001-ann-lee.docx") == "Dear Ann,\nYour order 1001 from Acme ships {Soon}."
    assert "[CHECK: no Company]" in paperwork.docx_text(out / "letters" / "002-bo-kim.docx")
    with zipfile.ZipFile(out / "letters" / "003-cy-ray.docx") as z:
        assert "Zeta copy" in z.read("word/header1.xml").decode()
    allx = zipfile.ZipFile(out / "all-letters.docx").read("word/document.xml").decode()
    assert allx.count('w:type="page"') == 2 and allx.count("<w:sectPr>") == 1 and "Dear Cy" in paperwork.docx_text(out / "all-letters.docx")
    rep = (out / "mail-merge-report.md").read_text(encoding="utf-8")
    assert "{Soon}" in rep and "Company" in rep.split("nothing in:")[1]
    assert letter.read_bytes() == before


def test_mail_merge_text_and_problems(app):  # noqa: F811
    (app.sb.inbox / "note.md").write_text("Hi {{ First name }}, see you!\n", encoding="utf-8")
    (app.sb.inbox / "people.csv").write_text(PEOPLE, encoding="utf-8")
    st = _run(app, "TASK: M  TYPE: mail-merge\nINPUT: note.md, people.csv\nOPTIONS: blank")
    assert st.status == "done", st.note
    assert (_out(app, st) / "letters" / "002-bo-kim.md").read_text(encoding="utf-8") == "Hi Bo, see you!\n"
    assert not (_out(app, st) / "all-letters.md").exists()
    (app.sb.inbox / "plain.txt").write_text("Hello friend.", encoding="utf-8")
    st = _run(app, "TASK: N  TYPE: mail-merge\nINPUT: plain.txt, people.csv\nOPTIONS: none")
    assert st.status == "failed" and "curly brackets" in st.note
    st = _run(app, "TASK: N  TYPE: mail-merge\nINPUT: people.csv\nOPTIONS: none")
    assert st.status == "failed" and "one letter" in st.note


# --------------------------------------------------------------------------- 8. Alt text
def test_alt_text(seeing):  # noqa: F811
    app = seeing
    _pics(app.sb.inbox / "shop", "mug.png", "long-one.png", "blank.png")
    st = _run(app, "TASK: Alt  TYPE: alt-text\nINPUT: shop\nOPTIONS: long, sidecar\nFORMAT: my pottery shop")
    assert st.status == "partial" and "blank.png" in st.note
    out = _out(app, st)
    from joeai.sheets import read_table
    h, rows, _ = read_table(out / "alt-text.csv")
    by = {r[0]: r for r in rows}
    assert by["mug.png"][1] == "A blue mug on a table." and by["mug.png"][3].startswith("The mug is glazed")
    long = by["long-one.png"][1]
    assert len(long) <= 125 and not long.lower().startswith("image") and long.endswith(".")
    assert (out / "mug.txt").exists() and "## mug.png" in (out / "alt-text.md").read_text(encoding="utf-8")
    assert any("my pottery shop" in p for p in app_prompts_all(app))


def app_prompts_all(app):  # noqa: F811
    import gc
    from fake_ollama import FakeOllama
    return [p for o in gc.get_objects() if isinstance(o, FakeOllama) and o.url == app.settings.ollama.url for p in o.prompts]


def test_tidy_alt():
    assert paperwork.tidy_alt("image of a red barn") == "A red barn."
    assert paperwork.tidy_alt("Photograph showing two dogs!") == "Two dogs!"
    t = paperwork.tidy_alt("word " * 60)
    assert len(t) <= 125 and t.endswith("word.")


# --------------------------------------------------------------------------- 9. Duplicate photos
def test_exact_duplicates_without_ffmpeg(app):  # noqa: F811
    folder = app.sb.inbox / "phone"
    _pics(folder, "a.png", "b.png")
    shutil.copy(folder / "a.png", folder / "a copy.png")
    st = _run(app, "TASK: D  TYPE: duplicate-photos\nINPUT: phone\nOPTIONS: how close, copy")
    assert st.status == "done", st.note
    md = (_out(app, st) / "duplicates.md").read_text(encoding="utf-8")
    assert "**1 group(s)**" in md and "**Keep:** phone/a.png" in md and "could go: phone/a copy.png" in md
    assert sorted(p.name for p in (_out(app, st) / "keepers").iterdir()) == ["a.png", "b.png"]
    assert sorted(p.name for p in folder.iterdir()) == ["a copy.png", "a.png", "b.png"]   # nothing moved


def test_hash_and_best_photo():
    px = bytes(range(72))
    assert paperwork.dhash(px) == 0                                         # always getting brighter
    assert paperwork.dhash(bytes(reversed(range(72)))) == (1 << 64) - 1
    infos = [{"path": Path("a.jpg"), "size": 100, "sha": "1", "hash": 0, "ratio": 1.5},
             {"path": Path("b.jpg"), "size": 90, "sha": "2", "hash": 0b111, "ratio": 1.5},
             {"path": Path("c.jpg"), "size": 80, "sha": "3", "hash": (1 << 64) - 1, "ratio": 1.5},
             {"path": Path("d.jpg"), "size": 70, "sha": "4", "hash": 0b1, "ratio": 0.7}]
    groups = paperwork.group_photos(infos, "close")
    assert [sorted(f["path"].name for f in g) for g in groups] == [["a.jpg", "b.jpg"]]   # d: another crop
    assert len(paperwork.group_photos(infos, "loose")[0]) == 3
    assert paperwork.group_photos(infos, "exact") == []
    big = {"path": Path("IMG_1.jpg"), "size": 5, "sha": "x", "w": 4000, "h": 3000}
    small = {"path": Path("IMG_1 (1).jpg"), "size": 9, "sha": "y", "w": 800, "h": 600}
    keep, why = paperwork.best_photo([small, big])
    assert keep is big and "biggest" in why


@pytest.mark.skipif(not FF, reason="needs FFmpeg")
def test_near_duplicates_with_ffmpeg(app, monkeypatch):  # noqa: F811
    import joeai.doctor as doctor
    monkeypatch.setattr(doctor, "ffmpeg_exe", lambda configured="": FF)
    folder = app.sb.inbox / "pics"
    folder.mkdir(parents=True)
    for name, src, size in (("big.png", "testsrc2", "640x480"), ("small.jpg", "testsrc2", "320x240"),
                            ("other.png", "mandelbrot", "640x480")):
        subprocess.run([FF, "-v", "error", "-f", "lavfi", "-i", f"{src}=size={size}", "-frames:v", "1", str(folder / name)],
                       check=True)
    st = _run(app, "TASK: D  TYPE: duplicate-photos\nINPUT: pics\nOPTIONS: how close, sheets")
    assert st.status == "done", st.note
    md = (_out(app, st) / "duplicates.md").read_text(encoding="utf-8")
    assert "**Keep:** pics/big.png: the biggest picture (640x480)" in md and "could go: pics/small.jpg" in md
    assert "other.png" not in md and (_out(app, st) / "group-001.jpg").exists()


# --------------------------------------------------------------------------- add-on '/' and '@' (Fable review)
def test_addon_values_starting_with_slash_or_at_are_refused(tmp_path):
    tool = {"program": "prog", "output": "{stem}.txt", "args": ["{text}", "{input}", "{option:mode}"]}
    cmd = community.command_line(tool, Path("prog"), tmp_path / "a.png", tmp_path, set(), {"mode": "fast"}, "hello")
    assert cmd[1] == "hello" and cmd[2] == str(tmp_path / "a.png")          # Joe's own paths may start with /
    for text, values in (("/Q", {"mode": "x"}), ("@secrets.txt", {"mode": "x"}), ("ok", {"mode": "/S"}),
                         ("ok", {"mode": "@list"})):
        with pytest.raises(ValueError, match="start them with something else"):
            community.command_line(tool, Path("prog"), tmp_path / "a.png", tmp_path, set(), values, text)
    tool["args"] = ["/title:{text}", "--label=@{text}"]                       # the template's own / and @: fine
    assert community.command_line(tool, Path("prog"), tmp_path / "a.png", tmp_path, set(), {}, "@x")[1:] == ["/title:@x", "--label=@@x"]


def test_tools_form_keeps_answer_lines_apart():
    m = tools.mission_for("pdf-tools", ["form.pdf"], ["do fill"], extra="Full name: Jane\nAgree: yes")
    assert "FORMAT: Full name: Jane | Agree: yes" in m
    assert paperwork.parse_answers(parse(m).jobs[0].format) == {"Full name": "Jane", "Agree": "yes"}
    m = tools.mission_for("hide-details", ["a.txt"], ["names"], extra="Sam Rivera\nkeep: Acme")
    assert paperwork.box_words(parse(m).jobs[0].format) == (["Sam Rivera"], ["Acme"])


def test_resume_word_copies_when_pandoc_is_there(app):  # noqa: F811
    if not shutil.which("pandoc"):
        pytest.skip("needs Pandoc")
    (app.sb.inbox / "resume.txt").write_text(RESUME, encoding="utf-8")
    (app.sb.inbox / "job posting.txt").write_text(POSTING, encoding="utf-8")
    st = _run(app, "TASK: J  TYPE: resume-tailor\nINPUT: resume.txt, job posting.txt\nOPTIONS: letter, word")
    assert st.status == "done", st.note
    names = sorted(p.name for p in _out(app, st).iterdir())
    assert "resume-tailored.md" in names and any(n.endswith(".docx") for n in names)


def test_cells_from_other_peoples_files_never_run_as_formulas(app):  # noqa: F811
    assert paperwork.safe_cell("=HYPERLINK(1)") == "'=HYPERLINK(1)" and paperwork.safe_cell("Shop") == "Shop"
    (app.sb.inbox / "b.csv").write_text('Date,Description,Amount\n2026-01-02,"=cmd|x",-1.00\n', encoding="utf-8")
    st = _run(app, "TASK: B  TYPE: bank-budget\nINPUT: b.csv\nOPTIONS: none")
    assert "'=cmd|x" in (_out(app, st) / "budget-transactions.csv").read_text(encoding="utf-8-sig")


def test_folder_links_pointing_outside_the_workspace_are_skipped(app, tmp_path):  # noqa: F811
    import os
    outside = tmp_path / "secret.txt"
    outside.write_text("private", encoding="utf-8")
    folder = app.sb.inbox / "docs"
    folder.mkdir(parents=True)
    (folder / "ok.txt").write_text("Call 555-123-4567.", encoding="utf-8")
    try:
        os.symlink(outside, folder / "link.txt")
    except (OSError, NotImplementedError):
        pytest.skip("this computer doesn't allow symlinks")
    st = _run(app, "TASK: H  TYPE: hide-details\nINPUT: docs\nOPTIONS: style labels")
    assert st.status == "done" and st.items == 1
    assert not (_out(app, st) / "link-cleaned.txt").exists()
