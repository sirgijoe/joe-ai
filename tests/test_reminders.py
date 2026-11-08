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

    def fake(server, topic, msg, title="Joe", at=None, priority=""):
        assert priority == "high"
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


def test_directions_and_shopping(app):  # noqa: F811
    r = route.classify("directions to the hardware store in Springfield")
    assert r["cmd"] == "directions" and r["text"] == "the hardware store in Springfield"
    assert route.classify("how do I get to the airport?")["text"] == "the airport"
    assert route.classify("where can I buy a cheap air fryer?") == {"kind": "command", "cmd": "shop", "text": "a cheap air fryer"}
    d = reminders.directions(app.settings, "the airport")
    assert d["open"] == "https://www.google.com/maps/dir/?api=1&destination=the%20airport"
    app.settings.comfort.maps, app.settings.comfort.shop = "osm", "duckduckgo"
    assert reminders.directions(app.settings, "x")["open"].startswith("https://www.openstreetmap.org/")
    assert "duckduckgo.com/?q=air%20fryer" in reminders.shopping(app.settings, "air fryer")["open"]
    assert not reminders.shopping(app.settings, " ")["ok"]


def test_ntfy_falls_back_to_system_curl_on_old_certificates(monkeypatch):
    import ssl
    import urllib.error
    from joeai import notify
    def bad(req, timeout=0):
        raise urllib.error.URLError(ssl.SSLCertVerificationError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate has expired"))
    monkeypatch.setattr(notify.urllib.request, "urlopen", bad)
    seen = {}
    monkeypatch.setattr(notify, "_curl_post", lambda url, body, headers, timeout: seen.update(url=url, h=headers) or "")
    assert notify.send_ntfy("https://ntfy.sh", "joe-test-123", "hi", at=1800000000) == ""
    assert seen["url"] == "https://ntfy.sh/joe-test-123" and seen["h"]["At"] == "1800000000"
    monkeypatch.setattr(notify, "_curl_post", lambda *a: "curl failed")
    assert "couldn't reach" in notify.send_ntfy("https://ntfy.sh", "joe-test-123", "hi")


def test_other_ways_to_ask_for_a_reminder():
    for t in ("set a reminder for 3pm to call the vet", "Set me a reminder at 3pm to call the vet",
              "don't let me forget to call the vet at 3pm", "reminder: call the vet at 3pm",
              "hey Joe, can you remind us at 3pm to call the vet"):
        r = route.classify(t)
        assert r["cmd"] == "remind", t
        assert reminders.parse_when(r["text"], NOW) == (datetime(2026, 11, 8, 15, 0), "call the vet"), t


def test_ping_my_phone_is_a_reminder():
    r = route.classify("ping my phone in one minute for a test")
    assert r["cmd"] == "remind" and reminders.parse_when(r["text"], NOW) == (datetime(2026, 11, 8, 13, 1), "a test")
    assert route.classify("text me at 5pm to start dinner")["cmd"] == "remind"
    assert route.classify("send me a notification tomorrow at 8 to feed the horses")["cmd"] == "remind"
    assert route.classify("ping me when the run is done").get("cmd") != "remind"        # no time: not a reminder
