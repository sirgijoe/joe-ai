"""2.1 voice assistant: reminders to the phone (ntfy scheduled delivery) and lists."""
from __future__ import annotations

from datetime import datetime

from joeai import reminders, route

from test_tools import app  # noqa: F401

NOW = datetime(2026, 11, 8, 13, 0)          # a Sunday


def test_parse_when():
    p = lambda t: reminders.parse_when(t, NOW)  # noqa: E731
    assert p("at 3pm to call the vet") == (datetime(2026, 11, 8, 15, 0), "call the vet")
    assert p("to call the vet at 3") == (datetime(2026, 11, 8, 15, 0), "call the vet")        # 3 = 3pm at 1pm
    assert p("in 20 minutes to take the bread out") == (datetime(2026, 11, 8, 13, 20), "take the bread out")
    assert p("in an hour to stretch")[0] == datetime(2026, 11, 8, 14, 0)
    assert p("tomorrow at 9am to feed the horses") == (datetime(2026, 11, 9, 9, 0), "feed the horses")
    assert p("on Friday at 10:30 am about the dentist") == (datetime(2026, 11, 13, 10, 30), "the dentist")
    assert p("tonight at 8 to lock the barn")[0] == datetime(2026, 11, 8, 20, 0)
    assert p("tomorrow to call mom")[0] == datetime(2026, 11, 9, 9, 0)
    assert p("at noon to eat")[0] == datetime(2026, 11, 8, 12, 0).replace(day=9)              # noon passed: tomorrow
    assert p("to call the vet")[0] is None


def test_routes():
    assert route.classify("remind me at 3pm to call the vet")["cmd"] == "remind"
    assert route.classify("Hey Joe, remind me in 10 minutes to check the oven.")["text"] == "in 10 minutes to check the oven"
    r = route.classify("add milk and eggs to my shopping list")
    assert r["cmd"] == "list-add" and r["items"] == "milk and eggs" and r["list"] == "shopping"
    assert route.classify("put call Sam on my list")["list"] == ""
    assert route.classify("what's on my grocery list?")["cmd"] == "list-show"
    assert route.classify("take milk off my shopping list")["cmd"] == "list-done"
    assert route.classify("send my shopping list to my phone")["cmd"] == "list-send"
    assert route.classify("add a dragon to my picture")["kind"] != "command"


def test_reminder_to_phone_and_waiting(app):  # noqa: F811
    sent = []

    def fake(server, topic, msg, title="Joe", at=None):
        sent.append((topic, msg, at))
        return ""
    r = reminders.add(app.sb, app.settings, "at 3pm to call the vet", NOW, send=fake)
    assert r["ok"] and "phone pings" in r["say"] and not sent                   # no ntfy topic yet
    app.settings.comfort.ntfy_topic = "joe-test-topic"
    r = reminders.add(app.sb, app.settings, "at 4pm to feed Rocky", NOW, send=fake)
    assert r["ok"] and "even if this PC is off" in r["say"]
    assert sent[-1] == ("joe-test-topic", "Reminder: feed Rocky", int(datetime(2026, 11, 8, 16, 0).timestamp()))
    r = reminders.add(app.sb, app.settings, "on Saturday at 9am to pay rent", NOW, send=fake)
    assert r["ok"] and "more than 3 days away" in r["say"] and len(sent) == 1
    assert "pay rent (waiting" in (app.sb.root / "Reminders.md").read_text(encoding="utf-8")
    assert reminders.tick(app.sb, app.settings, datetime(2026, 11, 12, 9, 0), send=fake) == 1   # rent (the vet one is long past)
    assert not reminders.add(app.sb, app.settings, "to call", NOW, send=fake)["ok"]
    assert "gone by" in reminders.add(app.sb, app.settings, "in 0 minutes to x", NOW, send=fake)["error"]


def test_lists(app):  # noqa: F811
    assert "Added milk and eggs" in reminders.list_add(app.sb, "grocery", "milk and eggs")["say"]
    assert "already on" in reminders.list_add(app.sb, "shopping", "Milk")["say"]
    assert reminders.list_show(app.sb, "shopping")["say"] == "Your shopping list: milk, eggs."
    assert reminders.list_done(app.sb, "shopping", "milk")["ok"]
    assert reminders.read_list(app.sb, "shopping") == ["eggs"]
    assert (app.sb.root / "Lists" / "Shopping list.md").read_text(encoding="utf-8").endswith("- [ ] eggs\n")
    reminders.list_add(app.sb, "", "call Sam")
    assert reminders.read_list(app.sb, "to do") == ["call Sam"]
    assert not reminders.list_send(app.sb, app.settings, "shopping")["ok"]       # no phone pings set up
