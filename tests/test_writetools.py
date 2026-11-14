"""2.1 writing tools: Summarize, Rewrite, Brainstorm, Study helper, Explain or review my code."""
from __future__ import annotations

import pytest

from joeai import abilities, describe, tools, writetools
from joeai.engine import Engine
from joeai.mission import MissionError, parse

from test_tools import app  # noqa: F401  (fixture: fake Ollama + workspace)


def _run(app, text):
    return Engine(app.settings, app.sb, log=lambda x: None).run_mission(parse(text))[0]


def test_new_tools_are_listed_explained_and_planned():
    for tid in writetools.WRITE_TOOLS:
        assert tools.TOOLS[tid].ready and tid in abilities.STEPS
        assert f"TYPE: {tid}" in tools.planner_lines()
    assert "brainstorm" in tools.NO_INPUT_OK


def test_summarize_short_and_long(app):  # noqa: F811
    (app.sb.inbox / "lease.md").write_text("The lease runs a year. Rent is 900 dollars.", encoding="utf-8")
    (app.sb.inbox / "book.txt").write_text(("word " * 2000 + "\n\n") * 3, encoding="utf-8")
    st = _run(app, "TASK: Sum  TYPE: summarize\nINPUT: lease.md, book.txt")
    assert st.status == "done" and st.items == 2, st.note
    out = app.sb.output / st.output
    s = (out / "lease-summary.md").read_text(encoding="utf-8")
    assert s.startswith("> Summary by Joe") and "# Summary: lease" in s and "[CHECK]" in s
    assert any("[CHECK]" in f["flag"] for f in st.flags)
    assert (app.sb.inbox / "lease.md").read_text(encoding="utf-8").startswith("The lease")
    with pytest.raises(MissionError):
        parse("TASK: S  TYPE: summarize\nINPUT: lease.md\nOPTIONS: length huge")


def test_summarize_chapters(app):  # noqa: F811
    (app.sb.inbox / "b.md").write_text("# One\n\nFirst part.\n\n# Two\n\nSecond part.\n", encoding="utf-8")
    st = _run(app, "TASK: C  TYPE: summarize\nINPUT: b.md\nOPTIONS: length chapters")
    body = (app.sb.output / st.output / "b-summary.md").read_text(encoding="utf-8")
    assert st.status == "done" and "## One" in body and "## Two" in body


def test_rewrite_makes_copy_and_change_list(app):  # noqa: F811
    (app.sb.inbox / "note.txt").write_text("hey send the files\n\nTOOSHORT thanks a lot friend", encoding="utf-8")
    st = _run(app, "TASK: Mail  TYPE: rewrite\nINPUT: note.txt\nOPTIONS: style email")
    assert st.status == "done", st.note
    out = app.sb.output / st.output
    assert sorted(p.name for p in out.iterdir()) == ["note-email.txt", "note-what-changed.md"]
    assert "[RW] hey send the files" in (out / "note-email.txt").read_text(encoding="utf-8")
    assert "Friendlier tone" in (out / "note-what-changed.md").read_text(encoding="utf-8")


def test_brainstorm_needs_no_file_but_a_topic(app):  # noqa: F811
    st = _run(app, "TASK: Names  TYPE: brainstorm\nFORMAT: names for a bakery\nOPTIONS: kind names, count 10, park")
    assert st.status == "done", st.note
    ideas = (app.sb.output / st.output / "ideas.md").read_text(encoding="utf-8")
    assert "# Names: names for a bakery" in ideas and "10. Idea 10" in ideas
    assert "brainstorm 'names for a bakery'" in (app.sb.root / "Ideas.md").read_text(encoding="utf-8")
    st2 = _run(app, "TASK: Empty  TYPE: brainstorm")
    assert st2.status == "failed" and "ideas for" in st2.note


def test_study_guide_cards_quiz(app):  # noqa: F811
    (app.sb.inbox / "bio.md").write_text("Cells are the basic unit of life.", encoding="utf-8")
    st = _run(app, "TASK: Bio  TYPE: study\nINPUT: bio.md\nOPTIONS: level kid, explain, cards, quiz, teach")
    assert st.status == "done", st.note
    out = app.sb.output / st.output
    g = (out / "bio-study-guide.md").read_text(encoding="utf-8")
    assert "TEACHMODE" in g and "# Practice quiz" in g and "## Answers" in g
    cards = (out / "bio-flashcards.csv").read_text(encoding="utf-8-sig")
    assert cards.splitlines() == ["Front,Back", "What is a cell?,The basic unit of life"]   # empty card dropped


def test_code_review_reads_never_runs(app):  # noqa: F811
    (app.sb.inbox / "add.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    st = _run(app, "TASK: Rev  TYPE: code-review\nINPUT: add.py\nOPTIONS: explain, bugs, tests")
    assert st.status == "done", st.note
    r = (app.sb.output / st.output / "add-review.md").read_text(encoding="utf-8")
    assert "never ran it" in r and "## What it does" in r
    assert writetools.chunks_by_lines("a\nb")[0] == (1, "    1| a\n    2| b")


def test_plain_summary_for_new_tools(app):  # noqa: F811
    (app.sb.inbox / "x.md").write_text("hello", encoding="utf-8")
    chk = app.check("TASK: S  TYPE: summarize\nINPUT: x.md")
    assert chk["ok"], chk
    assert describe.plain_summary(chk)


def test_other_openai_compatible_engine():
    from joeai.config import OllamaSettings
    from joeai import textengines
    cfg = OllamaSettings()
    cfg.engine, cfg.engine_url = "openai", "127.0.0.1:1337"
    assert textengines.engine_id(cfg) == "openai"
    assert textengines.engine_url(cfg) == "http://127.0.0.1:1337"
    assert "Jan" in textengines.engine_label(cfg) or "OpenAI" in textengines.engine_label(cfg)
    cfg.engine_url = "https://api.example.com"                      # never an online service
    assert textengines.engine_url(cfg) == "http://127.0.0.1:8000"


def test_ai_search_builds_schema_from_facts_only(app):  # noqa: F811
    import json
    st = _run(app, "TASK: AEO  TYPE: ai-search\nFORMAT: Corner Bakery, fresh bread, 12 Main St Springfield, Tue-Sat 7-3")
    assert st.status == "done", st.note
    out = app.sb.output / st.output
    assert sorted(p.name for p in out.iterdir()) == ["README.md", "description.md", "faq.md", "llms.txt", "schema.html"]
    schema = (out / "schema.html").read_text(encoding="utf-8")
    d = json.loads(schema.split("\n", 1)[1].rsplit("</script>", 1)[0])
    assert d["@type"] == "Bakery" and d["address"]["streetAddress"] == "12 Main St" and "telephone" not in d
    assert "Missing" in (out / "README.md").read_text(encoding="utf-8") and "phone" in (out / "README.md").read_text(encoding="utf-8")
    assert "- Are you open Monday?" in (out / "llms.txt").read_text(encoding="utf-8")


def test_meal_plan_adds_up_and_flags_budget(app):  # noqa: F811
    assert writetools.budget_from("I only have $80 this week") == 80.0
    assert writetools.people_from("to feed a family of 8") == 8 and writetools.people_from("for 2 for 5 days") == 2
    st = _run(app, "TASK: Food  TYPE: meal-plan\nFORMAT: I only have $80 this week to feed a family of 8\nOPTIONS: days 7")
    assert st.status == "done", st.note
    out = app.sb.output / st.output
    plan = (out / "meal-plan.md").read_text(encoding="utf-8")
    # over the $80 cap at first ($95.75): asked once more, the cheaper list ($75.75) is kept
    assert "Shopping total: $75.75" in plan and "$4.25 under budget" in plan and "211" not in plan
    assert "[CHECK]" in plan and "3 of 3 prices are Joe's estimates" in plan
    assert "Total,,75.75" in (out / "shopping-list.csv").read_text(encoding="utf-8-sig")
    (app.sb.inbox / "prices.csv").write_text("Item,Price\nRice 10 lb,9.50\n", encoding="utf-8")
    st = _run(app, "TASK: Food2  TYPE: meal-plan\nINPUT: prices.csv\nFORMAT: $200 for 4 people")
    plan = (app.sb.output / st.output / "meal-plan.md").read_text(encoding="utf-8")
    assert "under budget" in plan and "2 of 3 prices" in plan and "211" not in plan


# --------------------------------------------------------------------------- write like my own documents
MINE_SAMPLE = ("Hey folks, I'm so glad you stopped by! We've been busy at the studio this month, and I can't wait "
               "to show you what's new on the shelves.\n\n"
               "Honestly, I think the new glaze is my favorite yet. It's warm, it's a little bit wild, and it "
               "doesn't behave the way I expect, which is half the fun. We'll have a full batch by Friday!\n\n"
               "If you're nearby, come say hi. I'd love to hear what you think, and we've always got coffee on.")


def test_voice_facts_count_how_someone_writes():
    from joeai import mystyle
    facts = mystyle.voice_facts(MINE_SAMPLE)
    assert "uses contractions (don't, it's)" in facts and "writes in the first person (I, we, my)" in facts
    assert "uses exclamation marks" in facts
    formal = ("The committee does not consider the proposal to be adequate. It is the view of the board that "
              "the following requirements must be satisfied before any further action is taken by the department. "
              "Payment shall be made in accordance with the schedule attached to this agreement as an appendix.")
    f2 = mystyle.voice_facts(formal + " " + formal)
    assert "rarely uses contractions (writes 'do not', 'it is')" in f2 and "no exclamation marks" in f2
    assert mystyle.voice_facts("Too short to learn from.") == []


def _spy_system_prompts(monkeypatch):
    seen = []
    orig = Engine._chat

    def chat(self, job, part, kind, system, prompt, st, *a, **k):
        seen.append(system)
        return orig(self, job, part, kind, system, prompt, st, *a, **k)
    monkeypatch.setattr(Engine, "_chat", chat)
    return seen


def test_rewrite_in_my_own_voice(app, monkeypatch):  # noqa: F811
    seen = _spy_system_prompts(monkeypatch)
    mine = app.sb.inbox / "My writing"
    mine.mkdir()
    (mine / "newsletter.md").write_text("# March news\n\n" + MINE_SAMPLE, encoding="utf-8")
    (app.sb.inbox / "note.txt").write_text("Please send the files.\n\nThank you.", encoding="utf-8")
    st = _run(app, "TASK: Mine  TYPE: rewrite\nINPUT: note.txt\nOPTIONS: style friendly, mine")
    assert st.status == "done", st.note
    guide = [s for s in seen if "VOICE GUIDE" in s]
    assert guide and "come say hi" in guide[0] and "uses contractions" in guide[0]
    assert "Never copy their sentences" in guide[0]
    assert "March news" not in guide[0]                      # headings aren't passages
    assert (mine / "newsletter.md").read_text(encoding="utf-8").startswith("# March news")   # samples untouched


def test_mine_is_off_by_default_and_the_file_being_rewritten_is_never_a_sample(app, monkeypatch):  # noqa: F811
    seen = _spy_system_prompts(monkeypatch)
    mine = app.sb.inbox / "My writing"
    mine.mkdir()
    (mine / "draft.md").write_text(MINE_SAMPLE, encoding="utf-8")
    st = _run(app, "TASK: Plain  TYPE: rewrite\nINPUT: My writing/draft.md\nOPTIONS: style friendly")
    assert st.status == "done" and not any("VOICE GUIDE" in s for s in seen)
    st = _run(app, "TASK: Self  TYPE: rewrite\nINPUT: My writing/draft.md\nOPTIONS: style formal, mine")
    assert st.status == "failed" and "Inbox/My writing" in st.note        # its only sample IS the input


def test_mine_without_samples_explains_what_to_do(app):  # noqa: F811
    (app.sb.inbox / "a.md").write_text("Some words to summarize here, enough of them.", encoding="utf-8")
    st = _run(app, "TASK: S  TYPE: summarize\nINPUT: a.md\nOPTIONS: mine")
    assert st.status == "failed" and "put some of your own documents" in st.note


def test_brainstorm_can_use_my_voice_too(app, monkeypatch):  # noqa: F811
    seen = _spy_system_prompts(monkeypatch)
    mine = app.sb.inbox / "My writing"
    mine.mkdir()
    (mine / "post.txt").write_text(MINE_SAMPLE, encoding="utf-8")
    st = _run(app, "TASK: Names  TYPE: brainstorm\nFORMAT: names for a mug line\nOPTIONS: kind names, count 10, mine")
    assert st.status == "done", st.note
    assert any("VOICE GUIDE" in s for s in seen)
