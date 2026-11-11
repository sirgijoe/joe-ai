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
