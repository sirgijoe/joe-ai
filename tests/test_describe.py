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
