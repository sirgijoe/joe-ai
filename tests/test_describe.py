"""'Just describe it': plain words -> mission + plain summary."""
import pytest

from joeai import describe
from joeai.config import Settings
from joeai.server import App

from fake_ollama import FakeOllama


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "settings.json"))
    fake = FakeOllama()
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    s.ollama.url = fake.url
    s.comfy.url = "http://127.0.0.1:9"
    a = App(settings=s)
    a.fake = fake
    yield a
    fake.close()


def test_describe_makes_mission_and_plain_summary(app):
    r = describe.draft(app, "48 menu blurbs for my cafe, a price sheet and 16 food pictures")
    assert r["ok"], r
    assert "TASK: Menu blurbs" in r["mission"]
    assert "```" not in r["mission"]
    s = r["summary"]
    assert s[0] == "48 items: Menu blurbs"
    assert s[1] == "A spreadsheet with 10 rows: Menu sheet"
    assert s[2] == "16 pictures: Food pictures"
    assert r["time"].startswith("about")
    # no mission keys in what the person reads
    assert not any(k in " ".join(s) for k in ("CHUNKS", "TASK:", "SAVE"))


def test_describe_retries_when_the_model_forgets_the_block(app):
    r = describe.draft(app, "BADFIRST some captions")
    assert r["ok"], r
    assert sum(1 for p in app.fake.prompts if "That didn't work" in p) == 1


def test_describe_needs_words(app):
    assert not describe.draft(app, "  ")["ok"]


def test_extract_block_without_markers():
    b = describe.extract_block("Here you go:\nTASK: Tips\nCHUNKS: 1 x 3\n")
    assert b.startswith("=== JOE MISSION ===") and b.rstrip().endswith("=== END ===")
    assert describe.extract_block("no plan here") == ""


def test_plain_summary_kinds():
    chk = {"jobs": [
        {"name": "Guide", "type": "text", "guided": True, "parts": 1, "items": 1, "min_words": 0,
         "prompts": 0, "variants": 1},
        {"name": "Clips", "type": "video", "guided": False, "parts": 1, "items": 2, "min_words": 0,
         "prompts": 2, "variants": 1},
        {"name": "Mugs", "type": "image", "guided": False, "parts": 2, "items": 6, "min_words": 0,
         "prompts": 6, "variants": 2},
        {"name": "Posts", "type": "text", "guided": False, "parts": 2, "items": 20, "min_words": 80,
         "prompts": 0, "variants": 1},
    ]}
    assert describe.plain_summary(chk) == [
        "A document in 1 section: Guide",
        "2 short video clips: Clips",
        "12 pictures: Mugs (2 versions of each)",
        "20 items: Posts, at least 80 words each",
    ]
    assert describe.plain_time(1) == "about a minute"
    assert describe.plain_time(25) == "about 25 minutes"
    assert describe.plain_time(125) == "about 2 hours 5 min"
    assert describe.plain_time(60) == "about 1 hour"


def test_speeds_learn_from_runs_and_speed_test(app):
    import json
    from joeai import stats
    assert stats.speeds(app.sb)["part"] == stats.DEFAULT_SPEEDS["part"]
    r = app.speed_test()
    assert r["ok"] and "100 items takes about" in r["text"]
    sp = stats.speeds(app.sb)
    assert sp["learned"] == ["part"] and sp["part"] == round(r["seconds"] * 1.15, 1)
    with open(app.sb.meta / "runs.jsonl", "a") as f:
        for s in (10, 12, 50):
            f.write(json.dumps({"kind": "write", "ok": True, "seconds": s}) + "\n")
        for s in (4, 6):
            f.write(json.dumps({"kind": "image", "ok": True, "seconds": s}) + "\n")
        f.write(json.dumps({"kind": "image", "ok": False, "seconds": 99}) + "\n")
    sp = stats.speeds(app.sb)
    assert sp["part"] == round(12 * 1.15, 1) and sp["image"] == 5 and sp["video"] == 240
    chk = app.check("TASK: A  CHUNKS: 10 x 5\nTASK: P  TYPE: image  CHUNKS: 1 x 6")
    assert chk["eta_learned"] and chk["eta_min"] == round((10 * 13.8 + 6 * 5 + 6 * 6) / 60)


def test_talk_model_setting(app):
    from joeai import chat
    assert chat.talk_model(app) == "qwen3:14b"           # blank = the writing model
    app.settings.voice.talk_model = "qwen3:14b"
    assert chat.talk_model(app) == "qwen3:14b"
    app.settings.voice.talk_model = "not-installed:1b"
    assert chat.talk_model(app) == "qwen3:14b"


def test_video_request_planned_as_text_is_caught():
    from joeai.describe import kind_mismatch, wants_high
    req = "i want a sample video in high quality to show a hand made pottery mug being spun on a wheel"
    text_plan = "TASK: Video sample\nCHUNKS: 1 x 1\nFORMAT: describe the video"
    assert "TYPE: video" in kind_mismatch(req, text_plan)
    assert kind_mismatch(req, "TASK: Mug clip  TYPE: video\nCHUNKS: 1 x 1\nFORMAT: a mug spinning") == ""
    assert kind_mismatch("write 10 captions for my pottery videos", text_plan) == ""
    assert kind_mismatch("write a script for a video about glazing", text_plan) == ""
    assert "TYPE: image" in kind_mismatch("make 8 pictures of mugs on a shelf", "TASK: x\nCHUNKS: 1 x 8")
    assert kind_mismatch("remove the background from my pictures", "TASK: x  TYPE: remove-bg\nINPUT: a.png") == ""
    assert wants_high(req) and not wants_high("a quick video")


def test_request_is_held_while_drawing_then_planned(app, monkeypatch):
    import time
    from joeai import chat
    busy = {"on": True}
    monkeypatch.setattr(chat, "busy_drawing", lambda a: busy["on"])
    r = app.hold_plan("48 menu blurbs for my cafe, a price sheet and 16 food pictures")
    assert r["held"] and not r["ok"]
    assert app.state()["held_plan"]["status"] == "waiting"
    busy["on"] = False
    for _ in range(600):                              # slow CI machines: up to a minute
        if app.held_plan.get("status") == "ready":
            break
        time.sleep(0.1)
    h = app.state()["held_plan"]
    assert h["status"] == "ready" and h["result"]["ok"]


def test_talk_knows_the_tools(app):
    from joeai import chat
    p = chat.prepare(app, [], "fix my old photo please")
    assert "restore-photo" in p["msgs"][0]["content"]
