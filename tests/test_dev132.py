"""dev132: fixes found by the while-away test run (research words, book title page, story continuity)."""
from types import SimpleNamespace

from joeai import engine, websearch
from joeai.http import HttpError
from tests.test_core import env  # noqa: F401  (fixture)


def test_research_query_drops_task_label_and_uses_parts():
    job = SimpleNamespace(name="T3 Mug care guide", format="", part_prompts=["Write a guide to caring for ceramic mugs. Keep it short."])
    q = engine.research_query(job)
    assert not q.startswith("T3")
    assert "Mug care guide" in q and "ceramic mugs" in q and "Keep it short" not in q


def test_research_query_uses_format_first_sentence():
    job = SimpleNamespace(name="Coffee history", format="Explain the history of espresso. Use headings.", part_prompts=[])
    assert engine.research_query(job) == "Coffee history history of espresso."


def test_websearch_remembers_why_ollama_failed(monkeypatch):
    def boom(method, url, *a, **k):
        if "ollama" in url:
            raise HttpError("HTTP 401 from x: unauthorized")
        return {}
    monkeypatch.setattr(websearch, "request_json", boom)
    websearch.search("mugs", key="k")
    assert "refused" in websearch.last_error
    websearch.search("mugs", key="")
    assert websearch.last_error == ""


def test_second_part_sees_what_first_part_wrote(env):
    from joeai.engine import Engine
    from joeai.mission import parse
    s, sb, fake = env
    m = parse("=== JOE MISSION ===\nTASK: Story  SAVE: story.md\nPART: Chapter one.\nPART: Chapter two.\n=== END ===")
    st = Engine(s, sb, log=lambda m: None).run_mission(m)[0]
    assert st.status == "done"
    two = [p for p in fake.prompts if "part 2 of 2" in p]
    assert two and "WHAT IS ALREADY WRITTEN" in two[-1] and "Section" in two[-1]
    one = [p for p in fake.prompts if "part 1 of 2" in p]
    assert one and "WHAT IS ALREADY WRITTEN" not in one[0]


def test_export_drops_task_name_heading(tmp_path):
    import shutil
    from joeai.addons import export_document
    pandoc = shutil.which("pandoc")
    if not pandoc:
        import pytest
        pytest.skip("no pandoc")
    md = tmp_path / "lighthouse.md"
    md.write_text("# T5 Short story as a book\n\n# Chapter One\n\nThe keeper.\n\n# Chapter Two\n\nThe storm.\n")
    out = export_document(md, ["html"], pandoc, lambda m: None, heading="T5 Short story as a book")
    html = out[0].read_text()
    assert "<title>T5 Short story as a book</title>" in html
    assert html.count("T5 Short story as a book") <= 2          # title only, no empty chapter heading
    assert "Chapter One" in html and not (tmp_path / "lighthouse.export.md").exists()
    md2 = tmp_path / "notes.md"
    md2.write_text("# My notes\n\n## A\n\ntext\n")
    html2 = export_document(md2, ["html"], pandoc, lambda m: None)[0].read_text()
    assert "<title>My notes</title>" in html2


def test_tidy_matches_case_and_skips_fake_spelling():
    from joeai.tools import match_case, real_spelling_fix
    header = ["Name", "Category"]
    rows = [["a", "mugs"], ["b", "Mugs"], ["c", "Mugs"], ["d", "bowls"], ["e", "Bowls"], ["f", "bowls"]]
    assert match_case(header, rows) == ["Category: 2 cells"]
    assert [r[1] for r in rows] == ["Mugs", "Mugs", "Mugs", "bowls", "bowls", "bowls"]
    assert [r[0] for r in rows] == list("abcdef")
    assert real_spelling_fix("recieved", "received")
    assert not real_spelling_fix("RUST", "rust")
    assert not real_spelling_fix("mug", "mugs") and not real_spelling_fix("misc", "miscellaneous")


def test_scratch_cleanup_only_on_scratched_photos(tmp_path):
    import shutil
    import subprocess
    import pytest
    from joeai import picturetools as pt
    ff = shutil.which("ffmpeg")
    if not ff:
        pytest.skip("no ffmpeg")
    clean, scratched = tmp_path / "clean.png", tmp_path / "scratched.png"
    subprocess.run([ff, "-v", "error", "-f", "lavfi", "-i", "color=c=0x8899AA:s=200x150", "-frames:v", "1",
                    str(clean)], check=True)
    lines = ",".join(f"drawbox=x={x}:y=0:w=2:h=150:color=white:t=fill" for x in range(10, 200, 20))
    subprocess.run([ff, "-v", "error", "-i", str(clean), "-vf", lines, str(scratched)], check=True)
    assert pt.scratch_score(ff, clean) < pt.SCRATCHY <= pt.scratch_score(ff, scratched)
    out = tmp_path / "out.png"
    cmd = pt.true_restore_command(ff, scratched, out, scratches=True)
    assert any("median" in c for c in cmd) and not any("median" in c for c in pt.true_restore_command(ff, clean, out))
    subprocess.run(cmd, check=True)
    assert pt.scratch_score(ff, out) < pt.SCRATCHY


def test_hand_painted_sign_is_not_a_painting_look():
    from joeai import styles
    job = SimpleNamespace(name="Bakery sign", format="A hand-painted bakery sign on a village street, photo",
                          rules="", style="", look="")
    assert styles.pick(job).id != "painting"
    job2 = SimpleNamespace(name="Harbor", format="A harbor at dusk, painted in oils", rules="", style="", look="")
    assert styles.pick(job2).id == "painting"


def test_illusion_art_without_a_picture_can_be_queued(tmp_path, monkeypatch):
    from joeai import tools as tools_mod
    monkeypatch.setattr(tools_mod, "needs_problem", lambda *a, **k: "")
    import tests.test_dev120 as t120
    gen = t120.app.__wrapped__(tmp_path, monkeypatch)
    app = next(gen)
    chk = app.check("TASK: Spiral  TYPE: illusion-art\nOPTIONS: hidden spiral\nFORMAT: a village")
    assert chk["ok"], chk


def test_character_scenes_dont_give_objects_legs():
    from joeai.picturetools import SAME_CHARACTER
    assert "object" in SAME_CHARACTER and "no face, arms or legs" in SAME_CHARACTER


def test_ask_files_lists_the_excerpt_that_backs_an_uncited_answer():
    from joeai.tools import best_line, tidy_citations
    texts = ["Kiln Warranty. The warranty lasts 2 years.", "# Apartment Lease\nSection 9. Pets are allowed.",
             "Section 31. Rent is due on the 1st of each month. A late fee of $35 is added after the 5th."]
    ans = "The rent is due on the 1st of each month, and a late fee of $35 is added after the 5th."
    _, shown = tidy_citations(ans, 3, texts)
    assert shown == [2]
    assert best_line(texts[2], "When is rent due and what is the late fee?", answer=ans).startswith(("Rent is due", "A late fee"))
    assert tidy_citations("Yes [2].", 3, texts)[1] == [1]


def test_stray_script():
    from joeai.engine import stray_script
    assert stray_script("He had been her companion for十五 years.", "A story") == "十五"
    assert stray_script("ホットサイダー と コーヒー", "Translate") == ""
    assert stray_script("Order the 寿司 set", "Menu with Japanese 寿司 names") == ""
    assert stray_script("Plain English only.", "x") == ""
