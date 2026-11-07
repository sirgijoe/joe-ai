"""dev143: fixes from the first new-user installer test."""
import json
import threading
import time
from pathlib import Path

from joeai import describe, styles
from joeai.engine import _clean_title

PICKS = json.loads((Path(__file__).resolve().parents[1] / "joeai" / "model_picks.json").read_text(encoding="utf-8"))


def test_plan_count_reads_right():
    chk = {"jobs": [{"name": "Raccoon", "type": "image", "prompts": 1, "variants": 4, "parts": 1, "size": 1,
                     "items": 1, "guided": False}]}
    line = describe.plain_summary(chk)[0]
    assert "1 picture, 4 versions of it (4 pictures in all)" in line
    assert "of each" not in line
    chk["jobs"][0]["prompts"] = 3
    assert "3 pictures, 4 versions of each (12 pictures in all)" in describe.plain_summary(chk)[0]


def test_title_leaks_removed():
    assert _clean_title("Raccoon Feasting on Turtle (No Break)") == "Raccoon Feasting on Turtle"
    assert _clean_title("Raccoon Feasting on Turtle - no line break") == "Raccoon Feasting on Turtle"
    assert _clean_title("Title: Fox at Dawn") == "Fox at Dawn"
    assert _clean_title("Breaking Waves") == "Breaking Waves"
    assert _clean_title("Title of the Song") == "Title of the Song"


class _Job:
    name = "Generate AI Picture"
    type = "image"
    style = ""
    model = ""

    def __init__(self, fmt):
        self.format = fmt


def test_animals_get_wildlife_look_without_people_list():
    r = styles.recipe(_Job("A realistic racoon eating a realistic turtle"), PICKS)
    assert r.look.get("id") == "wildlife" and r.anatomy is False
    assert "merged animals" in r.negative and "fingers" not in r.negative
    assert styles.animals_in("a realistic racoon eating a realistic turtle") == {"raccoon", "turtle"}
    assert styles.animals_in("a computer mouse next to a bass guitar") == set()


def test_unmatched_photo_is_not_a_portrait():
    r = styles.recipe(_Job("a photo of a red sports car on a coastal road at dusk"), PICKS)
    assert r.look.get("id") != "portrait"


def test_two_quick_run_presses_start_once(monkeypatch):
    from joeai import server
    app = server.App.__new__(server.App)
    app.lock = threading.Lock()
    app.thread = None
    app.mission_text = ""
    calls = []

    def slow_enqueue(text, only=None):
        calls.append(text)
        time.sleep(0.3)
        return {"ok": True}
    app.enqueue = slow_enqueue
    out = []
    t = threading.Thread(target=lambda: out.append(app.run("PLAN")))
    t.start()
    time.sleep(0.05)
    second = app.run("PLAN")
    t.join()
    assert calls == ["PLAN"]
    assert second == {"ok": True, "already": True}
    assert app.run("OTHER") == {"ok": True}          # once it's started, a new run is allowed again
