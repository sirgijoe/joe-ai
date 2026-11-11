"""2.3 stage 5: memory (opt-in notes) and recurring missions."""
from __future__ import annotations

import json
import zipfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from joeai import backup, chat, mcp, memory, recurring, route
from joeai.config import Settings, reset_paths
from joeai.sandbox import Sandbox


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "cfg" / "settings.json"))
    (tmp_path / "cfg").mkdir()
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    return s


# ------------------------------------------------------------------ memory
def test_memory_is_off_until_turned_on(cfg):
    assert not memory.enabled(cfg)
    r = memory.handle(cfg, memory.command("remember that I like short captions"))
    assert "off" in r["say"] and memory.load() == []
    assert memory.context(cfg) == ""


def test_remember_show_edit_forget(cfg):
    cfg.memory.enabled = True
    assert memory.handle(cfg, memory.command("Remember that I like short captions with no emojis"))["ok"]
    assert memory.handle(cfg, memory.command("remember my shop is called Clay Corner"))["ok"]
    notes = memory.load()
    assert [n["text"] for n in notes] == ["I like short captions with no emojis", "My shop is called Clay Corner"]
    assert "Clay Corner" in memory.handle(cfg, memory.command("what do you remember about me?"))["say"]
    assert memory.edit(notes[1]["id"], "My shop is Clay Corner Pottery")["ok"]
    assert memory.handle(cfg, memory.command("forget that I like short captions"))["say"].startswith("Forgotten")
    assert [n["text"] for n in memory.load()] == ["My shop is Clay Corner Pottery"]
    assert "not sure" in memory.forget("something else entirely")["say"]
    assert memory.clear()["deleted"] == 1 and memory.load() == []


def test_remember_to_is_a_reminder_not_memory():
    assert memory.command("remember to buy milk") is None
    assert memory.command("please remember this about me: I'm vegetarian")["text"] == "I'm vegetarian"
    assert route.classify("remember that I'm left-handed")["cmd"] == "memory"
    assert route.classify("what do you remember about me?")["cmd"] == "memory"


def test_notes_stay_on_this_pc_not_in_the_workspace(cfg):
    cfg.memory.enabled = True
    memory.add(cfg, "I like blue")
    import os
    assert memory.path() == Path(os.environ["JOE_CONFIG"]).with_name("memory.json") and memory.path().is_file()
    assert not Path(cfg.workspace).exists() or not list(Path(cfg.workspace).rglob("memory.json"))


def test_who_sees_the_notes(cfg):
    cfg.memory.enabled = True
    memory.add(cfg, "I write for kids")
    assert "I write for kids" in memory.context(cfg, "window")
    assert memory.context(cfg, "phone") == "" and memory.context(cfg, "connector") == ""
    assert "Joe's own screen" in memory.handle(cfg, {"memory": "show"}, origin="phone")["say"]
    assert not memory.handle(cfg, {"memory": "add", "text": "x"}, origin="connector")["ok"]
    cfg.memory.phone = True
    assert "I write for kids" in memory.context(cfg, "phone")
    cfg.memory.connector = True
    assert "I write for kids" in memory.context(cfg, "connector")
    cfg.memory.enabled = False
    assert memory.context(cfg, "window") == ""


def test_the_connector_only_lists_memory_when_shared(cfg):
    cfg.memory.enabled = True
    memory.add(cfg, "I like green")
    j = mcp.Joe(cfg)
    names = [t["name"] for t in mcp.handle(j, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]]
    assert "joe_memory" not in names
    r = mcp.handle(j, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "joe_memory"}})
    assert "I like green" not in json.dumps(r)
    cfg.memory.connector = True
    names = [t["name"] for t in mcp.handle(j, {"jsonrpc": "2.0", "id": 3, "method": "tools/list"})["result"]["tools"]]
    assert "joe_memory" in names
    r = mcp.handle(j, {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "joe_memory"}})
    assert "I like green" in r["result"]["content"][0]["text"]


def test_talk_uses_notes_only_in_joes_own_window(cfg, tmp_path, monkeypatch):
    from joeai.server import App
    cfg.ollama.url = cfg.comfy.url = "http://127.0.0.1:9"
    cfg.memory.enabled = True
    memory.add(cfg, "I like haiku")
    app = App(settings=cfg)
    monkeypatch.setattr(app.services, "ensure_ollama", lambda: True)
    monkeypatch.setattr(chat, "talk_model", lambda a: "m")
    p = chat.prepare(app, [], "tell me something nice about the sea")
    assert "I like haiku" in p["msgs"][0]["content"]
    tok = memory.ORIGIN.set("phone")
    try:
        p = chat.prepare(app, [], "tell me something nice about the sea")
    finally:
        memory.ORIGIN.reset(tok)
    assert "I like haiku" not in p["msgs"][0]["content"]
    r = chat.prepare(app, [], "remember that I don't like long emails, keep them short please")
    assert r["final"]["say"].startswith("Got it")


def test_memory_left_out_of_backups_unless_ticked(cfg, tmp_path):
    cfg.memory.enabled = True
    memory.add(cfg, "I like jazz")
    sb = Sandbox(tmp_path / "ws").ensure()
    plain = backup.make(cfg, sb)
    assert "memory.json" not in zipfile.ZipFile(plain).namelist()
    withm = backup.make(cfg, sb, memory=True)
    assert "I like jazz" in zipfile.ZipFile(withm).read("memory.json").decode()
    memory.clear()
    r = backup.restore(cfg, sb, withm.read_bytes())
    assert r["memory"] == 1 and [n["text"] for n in memory.load()] == ["I like jazz"]
    assert backup.restore(cfg, sb, withm.read_bytes())["memory"] == 0        # no doubles


def test_memory_settings_reset_with_their_page():
    s = Settings()
    s.memory.enabled = s.memory.phone = True
    reset_paths(s, ["memory.enabled", "memory.phone", "memory.connector"])
    assert not (s.memory.enabled or s.memory.phone or s.memory.connector)
    html = (Path(__file__).parent.parent / "joeai" / "ui" / "index.html").read_text(encoding="utf-8")
    assert 'data-page="memory"' in html and 'data-path="memory.enabled"' in html and 'id="bk-mem"' in html


# ------------------------------------------------------------------ recurring missions
@pytest.mark.parametrize("text,days,when", [
    ("every Sunday night, make next week's meal plan", [6], "every Sunday night"),
    ("Every monday and thursday: 10 captions for my shop", [0, 3], "every Monday and Thursday night"),
    ("every weekday write a short to-do list", [0, 1, 2, 3, 4], "every weekday night"),
    ("every night make a bedtime story", list(range(7)), "every night"),
    ("on fridays, a summary of the week's sales", [4], "every Friday night"),
    ("each weekend make a family newsletter", [5, 6], "every weekend night"),
])
def test_when_words(text, days, when):
    r = recurring.parse(text, today=2)
    assert r and r["days"] == days and r["when"] == when and len(r["request"]) > 4


def test_ordinary_requests_arent_recurring():
    for t in ("make every caption short", "20 captions for every product", "everyday mugs, 10 blurbs"):
        assert recurring.parse(t) is None, t


def _sb(tmp_path):
    return Sandbox(tmp_path / "ws").ensure()


MISSION = "TASK: Meal plan  CHUNKS: 1 x 7"


def test_due_on_its_night_once(tmp_path):
    sb, s = _sb(tmp_path), Settings()
    s.schedule.time = "23:00"
    rid = recurring.add(sb, MISSION, [6])["id"]
    sunday = datetime(2026, 11, 15, 23, 0)
    monday = datetime(2026, 11, 16, 23, 0)
    assert recurring.queue_due(sb, s, monday) == []
    made = recurring.queue_due(sb, s, sunday)
    assert made == [f"recurring-{rid}-2026-11-15.txt"]
    assert (sb.missions / "Tonight" / made[0]).read_text(encoding="utf-8").strip() == MISSION
    assert recurring.queue_due(sb, s, sunday) == []                    # not twice the same night
    assert recurring.queue_due(sb, s, datetime(2026, 11, 22, 23, 0))   # next Sunday again


def test_a_shift_after_midnight_counts_as_the_night_before(tmp_path):
    sb, s = _sb(tmp_path), Settings()
    s.schedule.time = "01:30"
    recurring.add(sb, MISSION, [6])
    assert recurring.queue_due(sb, s, datetime(2026, 11, 16, 1, 30))   # Monday 01:30 = Sunday night


def test_pause_and_delete(tmp_path):
    sb, s = _sb(tmp_path), Settings()
    rid = recurring.add(sb, MISSION, [6])["id"]
    recurring.set_paused(sb, rid, True)
    assert recurring.queue_due(sb, s, datetime(2026, 11, 15, 23, 0)) == []
    recurring.set_paused(sb, rid, False)
    assert recurring.delete(sb, rid)["ok"] and recurring.load(sb) == []
    assert (recurring.folder(sb) / "removed" / f"{rid}.txt").read_text(encoding="utf-8").strip() == MISSION
    assert not recurring.add(sb, "nonsense", [1])["ok"] and not recurring.add(sb, MISSION, [])["ok"]


def test_the_night_shift_queues_them(tmp_path, monkeypatch):
    from joeai import schedule
    import joeai.app as app_mod
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "settings.json"))
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    s.schedule.time = "00:00"
    s.save()
    sb = Sandbox(s.workspace_path).ensure()
    recurring.add(sb, MISSION, list(range(7)))
    monkeypatch.setattr(app_mod, "_existing_url", lambda: "http://x")   # Joe's window is "open"
    assert schedule.tonight() == 0
    assert [p.name for p in (sb.missions / "Queue").glob("recurring-*.txt")]


def test_plan_now_offers_repeat(tmp_path, monkeypatch):
    from joeai import describe
    from joeai.server import App
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "settings.json"))
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    s.ollama.url = s.comfy.url = "http://127.0.0.1:9"
    app = App(settings=s)
    seen = []
    monkeypatch.setattr(describe, "draft", lambda a, text: seen.append(text) or
                        {"ok": True, "mission": MISSION, "summary": [], "time": "1 min"})
    r = app.plan_now("every Sunday night, make next week's meal plan")
    assert seen == ["make next week's meal plan"] and r["repeat"] == {"days": [6], "when": "every Sunday night"}
    assert "repeat" not in app.plan_now("make next week's meal plan")
