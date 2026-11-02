import json
import time
from dataclasses import asdict

import pytest

from joeai.config import Settings
from joeai.mission import mission_to_dict, parse, to_text
from joeai.server import App

from fake_ollama import FakeOllama

A = """=== JOE MISSION ===
PROJECT: Test Studio
TASK: Mugs  SAVE: q/mugs.md  CHUNKS: 2 x 2
=== END ==="""
B = """TASK: Bowls  SAVE: q/bowls.md  CHUNKS: 1 x 2"""          # no === lines needed


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "settings.json"))
    fake = FakeOllama()
    real = fake.chat

    def slow(req):                      # slow enough to queue/stop while it works
        time.sleep(0.4)
        return real(req)
    fake.chat = slow
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    s.ollama.url = fake.url
    s.comfy.url = "http://127.0.0.1:9"
    s.engine.retry_backoff_s = 0
    s.engine.gpu_temp_pause_c = 0
    s.engine.keep_awake = False
    a = App(settings=s)
    yield a
    if a.thread:
        a.thread.join(30)
    fake.close()


def _wait(app):
    for _ in range(300):
        if not app.running:
            return
        time.sleep(0.1)
    raise AssertionError("run never finished")


def test_round_trip_every_field():
    src = """=== JOE MISSION ===
PROJECT: P   RULES: Plain.
TASK: List  SAVE: a/l.md  CHUNKS: 3 x 4  MIN WORDS PER ITEM: 30
FORMAT: Title, then a paragraph.
INPUT: facts.txt, prices.csv
TASK: Sheet  SAVE: s.csv  CHUNKS: 2 x 5
HEADER: name,type
TASK: Doc  SAVE: d.md  PROJECT: Other
PART: ## Intro
PART: ## Body
TASK: Art  SAVE: art  TYPE: image  CHUNKS: 2 x 2  SIZE: 832 x 1216  VARIANTS: 2  SEED: 7
NEGATIVE: blurry
TASK: Clip  SAVE: clip  TYPE: video  WORKFLOW: vid.json  FPS: 12
PART: a fox
PROMPTS: as written
=== END ==="""
    m = parse(src)
    d = mission_to_dict(m)
    m2 = parse(to_text(d["project"], d["rules"], d["tasks"]))
    assert [asdict(j) for j in m.jobs] == [asdict(j) for j in m2.jobs]
    assert (m2.project, m2.rules) == ("P", "Plain.")


def test_values_cant_inject_keys():
    t = to_text("", "", [{"name": "X", "save": "x.md", "parts": 1, "part_size": 1,
                          "format": "Write well.\nSAVE: ../../evil.md  TYPE: video"}])
    j = parse(t).jobs[0]
    assert j.save == "x.md" and j.type == "text" and "evil" in j.format


def test_queue_runs_back_to_back_and_reports_both(app):
    assert app.enqueue(A)["ok"]
    r = app.enqueue(B)                                  # added while the first runs
    assert r["ok"] and r["queued"] == 1
    _wait(app)
    assert (app.sb.output / "q" / "mugs.md").exists() and (app.sb.output / "q" / "bowls.md").exists()
    rep = (app.sb.output / "_REPORT.md").read_text()
    assert "2 missions ran back-to-back" in rep and "Mugs" in rep and "Bowls" in rep
    assert app.resume_offer()["offer"] is False         # everything finished: fresh start
    h = app.history()["missions"]
    assert len(h) == 2 and all(m["done"] == m["tasks"] for m in h)


def test_resume_offer_after_stop(app):
    app.enqueue(A)
    app.stop.set()
    _wait(app)
    off = app.resume_offer()
    assert off["offer"] and "Mugs" in off["names"]
    assert app.resume("fresh")["ok"] and app.resume_offer()["offer"] is False
    # Revisit from history still works and picks up where it stopped.
    f = app.history()["missions"][0]["file"]
    assert app.enqueue((app.sb.root / f).read_text())["ok"]
    _wait(app)
    st = json.loads(next((app.sb.meta / "state").glob("mugs-*.json")).read_text())
    assert st["status"] == "done"


def test_resume_action_runs_unfinished(app):
    app.enqueue(A)
    app.stop.set()
    _wait(app)
    assert app.resume("resume")["ok"]
    _wait(app)
    assert app.resume_offer()["offer"] is False
