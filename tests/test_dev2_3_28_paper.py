"""2.3.0.dev28: Hide personal details can blank out the pictures inside a Word file."""
import shutil
import subprocess
import zipfile

from joeai import paperwork, tools

from paper_files import make_docx
from test_paperwork import _out, _run
from test_tools import app  # noqa: F401


def _with_pictures(app):  # noqa: F811
    src = make_docx(app.sb.inbox / "signed.docx", [["Call 269-555-0142 about the lease."]])
    with zipfile.ZipFile(src) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    parts["word/media/image1.png"] = b"SIGNATURE-PIXELS-PNG"
    parts["word/media/image2.jpeg"] = b"SCANNED-PAGE-JPEG"
    parts["word/media/image3.gif"] = b"LOGO-GIF"
    parts["word/media/image4.emf"] = b"VECTOR-LOGO-EMF"
    with zipfile.ZipFile(src, "w", zipfile.ZIP_DEFLATED) as z:
        for n, d in parts.items():
            z.writestr(n, d)
    return src


def test_blank_pictures_are_real_pictures_of_the_same_kind():
    png, jpg, gif = (paperwork.blank_picture(n) for n in ("a.PNG", "b.jpeg", "c.gif"))
    assert png.startswith(b"\x89PNG\r\n\x1a\n") and jpg.startswith(b"\xff\xd8") and jpg.endswith(b"\xff\xd9")
    assert gif.startswith(b"GIF89a") and paperwork.blank_picture("x.jpg") == jpg
    assert paperwork.blank_picture("drawing.emf") is None and paperwork.blank_picture("noext") is None
    ff = shutil.which("ffmpeg")
    if ff:                                    # FFmpeg can open each one: they are valid files, not just headers
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            for name, data in (("a.png", png), ("b.jpg", jpg), ("c.gif", gif)):
                f = Path(d) / name
                f.write_bytes(data)
                r = subprocess.run([ff, "-v", "error", "-i", str(f), "-f", "null", "-"], capture_output=True)
                assert r.returncode == 0, (name, r.stderr)


def test_pictures_option_blanks_them_in_the_copy_only(app):  # noqa: F811
    src = _with_pictures(app)
    before = src.read_bytes()
    st = _run(app, "TASK: S  TYPE: hide-details\nINPUT: signed.docx\nOPTIONS: style labels, pictures")
    assert st.status == "done", st.note
    out = _out(app, st)
    with zipfile.ZipFile(out / "signed-cleaned.docx") as z:
        assert z.read("word/media/image1.png") == paperwork.blank_picture("x.png")
        assert z.read("word/media/image2.jpeg") == paperwork.blank_picture("x.jpeg")
        assert z.read("word/media/image3.gif") == paperwork.blank_picture("x.gif")
        assert z.read("word/media/image4.emf") == b"VECTOR-LOGO-EMF"         # a kind Joe can't blank: left, and said
        assert "269-555-0142" not in z.read("word/document.xml").decode()
    assert src.read_bytes() == before                                      # the original is never changed
    report = "\n".join(p.read_text("utf-8") for p in out.glob("*.md"))
    assert "3 picture(s) inside it replaced with blank grey boxes" in report
    assert "[CHECK] 1 picture(s) of a kind Joe can't blank were left in: image4.emf" in report
    assert "Joe doesn't look inside pictures" not in report


def test_without_the_option_pictures_stay_and_the_report_says_how(app):  # noqa: F811
    _with_pictures(app)
    st = _run(app, "TASK: S  TYPE: hide-details\nINPUT: signed.docx\nOPTIONS: style labels")
    out = _out(app, st)
    with zipfile.ZipFile(out / "signed-cleaned.docx") as z:
        assert z.read("word/media/image1.png") == b"SIGNATURE-PIXELS-PNG"
    report = "\n".join(p.read_text("utf-8") for p in out.glob("*.md"))
    assert "4 picture(s) inside it" in report and "tick 'Blank out the pictures inside Word files'" in report


def test_the_option_is_off_unless_ticked():
    opt = next(o for o in tools.TOOLS["hide-details"].options if o.key == "pictures")
    assert opt.default is False
