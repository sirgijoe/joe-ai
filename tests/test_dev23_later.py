"""2.3 stage 7: the "worth adding later" items (one test group each)."""
from __future__ import annotations

from joeai.engine import JobState
from joeai.mission import parse
from joeai.report import _mission_lines, explain


def _st(**kw):
    base = dict(job_id="x", name="Blurbs", spec_hash="h", parts_total=60, parts_done=41, output="2026-11-10 Blurbs/blurbs.md",
                started="2026-11-10T23:00:00", finished="2026-11-11T01:13:00", items=410)
    base.update(kw)
    return JobState(**base)


# ------------------------------------------------------------------ clearer reports
def test_a_failed_long_job_says_what_happened_and_what_to_do():
    line = explain(_st(status="failed", note="RuntimeError: CUDA out of memory"))
    assert "**Blurbs** (41 of 60 parts done, ran 2h 13m)" in line
    assert "graphics card ran out of memory" in line and "kept in 2026-11-10 Blurbs/blurbs.md" in line
    assert "smaller SIZE" in line


def test_stopped_and_partial_jobs_say_nothing_is_lost():
    assert "finished parts are kept" in explain(_st(status="stopped", note="stopped after part 41"))
    p = explain(_st(status="partial", note=""))
    assert "skipped" in p and "new copy" in p
    assert "Ollama" in explain(_st(status="failed", note="Ollama is not running and could not be started", parts_done=0,
                                   items=0, finished=""))


def test_the_report_has_the_plain_words_section_only_when_needed():
    m = parse("TASK: Blurbs  CHUNKS: 60 x 10")
    ok = "\n".join(_mission_lines(m, [_st(status="done", parts_done=60)]))
    assert "What went wrong" not in ok
    bad = "\n".join(_mission_lines(m, [_st(status="failed", note="timed out waiting for ComfyUI")]))
    assert "## What went wrong, in plain words" in bad and "took longer" in bad


# ------------------------------------------------------------------ recipe scaling and substitutions
from fractions import Fraction  # noqa: E402

from joeai import recipes  # noqa: E402

PANCAKES = """Pancakes
Serves 4
- 1 1/2 cups flour
- 2 eggs
- 1¼ cups buttermilk
- 2-3 tbsp butter, melted
- ½ tsp salt
Mix and cook for 2 minutes a side."""


def test_scaling_is_done_by_joe_in_kitchen_numbers():
    out = recipes.make(PANCAKES, "double it")
    for want in ("Serves 8", "- 3 cups flour", "- 4 eggs", "- 2 1/2 cups buttermilk", "- 4-6 tbsp butter", "- 1 tsp salt",
                 "for 2 minutes a side"):                      # steps are left alone
        assert want in out, want
    assert "- 2 1/4 cups flour" in recipes.make(PANCAKES, "for 6 people")
    assert "- 3/4 cups flour" in recipes.make(PANCAKES, "half please")
    assert recipes.nice(Fraction(1, 3)) == "1/3" and recipes.nice(Fraction(7, 3)) == "2 1/3"


def test_swaps_come_from_joes_own_table():
    out = recipes.make(PANCAKES, "no eggs and I'm out of buttermilk")
    assert "ground flaxseed" in out and "lemon juice or white vinegar" in out
    assert "## Swaps" in out and "butter, melted**" not in out
    df = recipes.make(PANCAKES, "make it dairy-free")
    assert "butter, melted**" in df and "buttermilk**" in df
    odd = recipes.make("- 2 cups flour\n- 1 cup cream cheese\n- 1 tsp salt", "no cheese")
    assert "cream cheese**" in odd


def test_not_a_recipe_request():
    assert recipes.make(PANCAKES, "make it nice") is None
    assert recipes.make("", "double it") is None
    assert recipes.recipe_text("just words", "I have $80 to feed 8") == ""


def test_the_meal_planner_scales_a_pasted_recipe_without_the_model(tmp_path, monkeypatch):
    from joeai import writetools
    saved = {}
    eng = type("E", (), {"log": lambda self, m: None})()
    job = type("J", (), {"format": "double it, no eggs\n" + PANCAKES, "options": [], "type": "meal-plan"})()
    monkeypatch.setattr(writetools, "_context", lambda engine, files, n: "")

    def ask(*a, **k):
        raise AssertionError("no model needed")
    writetools._meal_plan(eng, job, [], ask, lambda name, text, what: saved.update({name: text}), "m")
    assert "- 4 eggs" in saved["recipe.md"] and "ground flaxseed" in saved["recipe.md"]
