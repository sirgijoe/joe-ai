"""2.3.0.dev15: what the review of the Agents build changed. The fail-safes (Joseph, 2026-11-11: "some
sort of fail safe if something goes wrong, rather than just letting it cycle in an endless loop of
fails and errors") and the security fixes, one test each."""
from __future__ import annotations

import http.server
import threading
import time

from joeai import agents, agentrun, agentweb, websearch

from agent_env import env, make, run  # noqa: F401 (env is a fixture)
from test_dev23_agent_engine import FakeWeb, _on


def _report(folder):
    return (folder / "AGENT REPORT.md").read_text(encoding="utf-8")


# ------------------------------------------------------------------ fail-safes inside one run
def test_a_weak_model_that_never_says_done_ends_after_the_two_steps(env):
    """Joseph's PC test (gemma4:12b): the job was finished at step 2, the model never said done and
    repeated itself to the step limit. The script here never says done and would repeat step 2 for ever."""
    app, fake, script, calls = env
    aid = make({"name": "Guide", "job": "write a one page guide to watering houseplants, then summarize into five "
                "bullet points", "tools": ["text", "summarize"], "steps": 12})
    script["plan"] = [{"points": ["A one-page guide to watering houseplants", "Five bullet points summarizing it"]}]
    script["tick"] = [{"done": [1]}, {"done": [2]}]
    two = {"action": "write", "title": "Five points", "instruction": "summarize the guide into five bullet points"}
    script["pick"] = [{"action": "write", "title": "Watering houseplants", "instruction": "the guide"}] + [dict(two)] * 10
    last, folder = run(app, aid)
    assert last["status"] == "done" and last["done"] == 2 and len(last["plan"]) == 2
    assert len(calls["pick"]) == 2                                   # nobody asked the model for a third step
    assert "I got stuck" not in _report(folder)


def test_a_repeated_step_is_sent_back_once_then_the_run_stops(env):
    """The same model with a tick-off that doesn't help: one "you already did that", then stuck."""
    app, fake, script, calls = env
    aid = make({"name": "Loop", "job": "write it, then sum it up", "tools": ["text"], "steps": 12})
    script["plan"] = [{"points": ["Write it", "Sum it up"]}]
    script["tick"] = [{"done": [1]}] + [{"done": []}] * 10
    step = {"action": "write", "instruction": "write it"}
    script["pick"] = [dict(step)] * 10
    last, folder = run(app, aid)
    rep = _report(folder)
    assert "same step again" in rep and last["status"] == "partial"
    assert len([p for p in folder.glob("0*.md")]) == 1               # the step ran once, not twice
    assert "you already did that exact step" in calls["pick"][2]
    assert len(calls["pick"]) == 3


def test_going_back_and_forth_between_two_steps_is_caught_too(env):
    app, fake, script, calls = env
    aid = make({"name": "Ping", "job": "write two things", "tools": ["text"], "steps": 12})
    script["plan"] = [{"points": ["Thing one", "Thing two", "Thing three"]}]
    script["tick"] = [{"done": []}] * 10
    a, b = {"action": "write", "instruction": "thing one"}, {"action": "write", "instruction": "thing two"}
    script["pick"] = [a, b, dict(a), dict(b), dict(a), dict(b)]
    last, folder = run(app, aid)
    assert "same step again" in _report(folder)
    assert len([p for p in folder.glob("0*.md")]) == 2


def test_the_failure_limit_stops_the_run_pauses_the_agent_and_pings_the_phone(env, monkeypatch):
    """Joseph: "pause run and ping phone (if ping is set up) after X failures, errors, or retries",
    1-100, 10 unless changed. Here a step with no file, again and again (it used to go on to the step limit)."""
    app, fake, script, calls = env
    from joeai import notify
    pings = []
    monkeypatch.setattr(notify, "send_ntfy", lambda server, topic, msg, **k: pings.append((topic, msg)) or "")
    app.settings.comfort.ntfy_topic = "joe-test-topic"
    aid = make({"name": "Nofile", "job": "summarize my notes", "tools": ["text", "summarize"], "steps": 30})
    assert agents.get(aid)["max_fails"] == 10
    script["pick"] = [{"action": "tool", "tool": "summarize", "input": [], "instruction": f"try {i}"} for i in range(30)]
    last, folder = run(app, aid)
    rep = _report(folder)
    assert "10 failures, errors or retries in this run (this agent's limit is 10)" in rep and "What would help" in rep
    assert rep.count(": failed") == 10 and last["status"] == "failed"
    a = agents.get(aid)
    assert a["paused"] and "reached its limit" in a["paused_why"] and "This agent is now paused" in rep
    assert ("joe-test-topic", "Joe paused the Nofile agent: it kept failing. Its report says why (Tools > AGENTS).") in pings
    assert sum("paused" in m for _, m in pings) == 1                 # one ping about it, not one per failure


def test_the_failure_limit_is_the_owners_number_and_never_no_limit(env):
    app, fake, script, calls = env
    for typed, kept in ((3, 3), (0, 10), (-5, 1), (1000, 100), ("", 10)):
        aid = make({"name": f"L{kept}{typed}", "job": "j", "tools": ["text"], "max_fails": typed})
        assert agents.get(aid)["max_fails"] == kept
    aid = make({"name": "Three", "job": "summarize", "tools": ["text", "summarize"], "steps": 30, "max_fails": 3})
    script["pick"] = [{"action": "tool", "tool": "summarize", "input": [], "instruction": f"try {i}"} for i in range(30)]
    last, folder = run(app, aid)                                     # no phone ping set up: it just stops and pauses
    assert _report(folder).count(": failed") == 3 and agents.get(aid)["paused"]


def test_steps_that_get_no_point_done_stop_the_run(env):
    app, fake, script, calls = env
    aid = make({"name": "Busy", "job": "keep writing", "tools": ["text"], "steps": 20})
    script["tick"] = [{"done": []}] * 20
    script["pick"] = [{"action": "write", "instruction": f"part {i}"} for i in range(20)]
    last, folder = run(app, aid)
    assert "without getting any point of the plan done" in _report(folder)
    assert len([p for p in folder.glob("0*.md")]) == agentrun.NO_PROGRESS_STEPS


def test_looking_things_up_alone_never_finishes_a_job(env, monkeypatch):
    """A model that ticks every point after one search: the last point stays open until something is made."""
    app, fake, script, calls = env
    FakeWeb(monkeypatch)
    _on(app)
    aid = make({"name": "R", "template": "researcher", "job": "Is a heat pump worth it?", "abilities": {"lookups": True}})
    script["plan"] = [{"points": ["Find out", "Write the answer"]}]
    script["tick"] = ["all", "all"]
    script["pick"] = [{"action": "search", "query": "heat pump worth it"}, {"action": "write", "instruction": "the answer"}]
    last, folder = run(app, aid)
    assert last["status"] == "done" and [p for p in folder.glob("0*.md")]
    assert "only looked things up" in (folder / "AGENT LOG.txt").read_text(encoding="utf-8")


# ------------------------------------------------------------------ the fail-safe across runs
def test_three_bad_runs_in_a_row_pause_the_agent_and_say_why(env):
    app, fake, script, calls = env
    aid = make({"name": "Nightly", "job": "do it", "tools": ["text", "summarize"]})
    for i in range(agents.PAUSE_AFTER_FAILS):
        assert not agents.get(aid).get("paused")
        script["pick"] = ["no json here", {"action": "nope"}]
        last, folder = run(app, aid)
    a = agents.get(aid)
    assert a["paused"] and "paused it instead of starting it again and again" in a["paused_why"]
    assert "This agent is now paused" in _report(folder)
    assert agents.start_remote(app, "Nightly")["ok"] is False
    agents.set_paused(aid, False)                                    # START AGAIN on Joe's screen
    a = agents.get(aid)
    assert not a["paused"] and "paused_why" not in a and a["fails"] == 0


def test_a_good_run_starts_the_count_again(env):
    app, fake, script, calls = env
    aid = make({"name": "Mixed", "job": "do it", "tools": ["text"]})
    for good in (False, False, True, False, False):
        script["pick"] = [{"action": "write", "instruction": "it"}] if good else ["no json here", {"action": "nope"}]
        run(app, aid)
    assert not agents.get(aid).get("paused") and agents.get(aid)["fails"] == 2


# ------------------------------------------------------------------ no doubles
def test_another_agent_is_started_once_and_gets_only_the_owners_words(env):
    app, fake, script, calls = env
    other = make({"name": "Heat research", "template": "researcher", "job": "heat pumps"})
    aid = make({"name": "Jarvis", "template": "assistant", "job": "Keep it short."})
    script["tick"] = [{"done": []}] * 4
    script["pick"] = [{"action": "start", "agent": "Heat research", "request": "costs in Michigan AND passport number K1234567"},
                      {"action": "start", "agent": "Heat research", "request": "again"}]
    run(app, aid, request="start the heat research on costs in Michigan")
    q = list((app.sb.missions / "Queue").glob(f"agent-{other}-*.txt"))
    assert len(q) == 1
    text = q[0].read_text(encoding="utf-8")
    assert "FORMAT: costs in Michigan" in text and "passport" not in text and "K1234567" not in text


def test_the_same_reminder_isnt_made_twice(env, monkeypatch):
    app, fake, script, calls = env
    from joeai import reminders
    made = []
    monkeypatch.setattr(reminders, "add", lambda sb, s, text: made.append(text) or {"ok": True, "say": "OK"})
    app.settings.comfort.ntfy_topic = "joe-test-topic"
    aid = make({"name": "Jarvis", "template": "assistant", "job": "help", "abilities": {"phone": True}})
    script["tick"] = [{"done": []}] * 6
    script["pick"] = [{"action": "remind", "text": "at 5pm to call the vet"}, {"action": "list", "list": "x", "things": "a"},
                      {"action": "remind", "text": "at 5pm to call the vet"}]
    run(app, aid, request="remind me at 5pm to call the vet")
    assert made == ["at 5pm to call the vet"]


# ------------------------------------------------------------------ pages: the connection itself is checked
class _Page(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"<html><title>Router</title><body>admin password: hunter2</body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def test_a_name_that_turns_to_this_pc_after_the_check_is_refused(monkeypatch):
    """DNS rebinding: the name looked public when Joe checked it, then pointed at this PC."""
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Page)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/"
        monkeypatch.setattr(agentweb, "public_url", lambda u: True)          # the checks before were fooled
        monkeypatch.setattr(agentweb, "_resolves_public", lambda u: True)
        assert agentweb.fetch_page(url) is None                              # the connection's own address isn't
        monkeypatch.setattr(agentweb, "_global_ip", lambda a: True)          # (the same download does work
        page = agentweb.fetch_page(url)                                      #  when the address is a public one)
        assert page and "hunter2" in page["text"]
    finally:
        srv.shutdown()
        srv.server_close()


def test_addresses_of_this_pc_written_the_long_way_are_private():
    for a in ("::ffff:127.0.0.1", "::ffff:192.168.1.1", "64:ff9b::7f00:1", "2002:7f00:1::", "::1", "fe80::1%eth0", "169.254.169.254"):
        assert not agentweb._global_ip(a), a
    assert agentweb._global_ip("8.8.8.8") and agentweb._global_ip("2606:4700:4700::1111")
    assert not agentweb.public_url("http://[::ffff:127.0.0.1]/") and not agentweb.public_url("http://user:pw@example.com/")


# ------------------------------------------------------------------ the clerk's folder
def test_apply_doesnt_start_the_agent_again(env, monkeypatch):
    """APPLY renames files and writes an undo list in the watched folder: neither is new work."""
    app, fake, script, calls = env
    aid = make({"name": "Clerk", "template": "clerk", "job": "name my bills", "tools": ["text"],
                "abilities": {"files": True}, "watch": True}, app.sb)
    folder = agents.agent_folder(app.sb, agents.get(aid))
    (folder / "scan1.txt").write_text("Electric bill", encoding="utf-8")
    queued = []
    monkeypatch.setattr(app, "enqueue", lambda text: queued.append(text) or {"ok": True})
    assert agents.watch_tick(app, now=time.time() + 60) == ["Clerk"]
    agents.set_pending(aid, "x", [{"from": "scan1.txt", "to": "Electric bill.txt"}])
    assert agents.apply_pending(app.sb, aid)["done"] == 1
    assert list(folder.glob("_UNDO *.json")) and (folder / "Electric bill.txt").is_file()
    assert agents.watch_tick(app, now=time.time() + 60) == [] and len(queued) == 1
    r = agentrun.Run.__new__(agentrun.Run)                           # and a run never offers the undo list as a file
    r.job, r.sb, r.agent = type("J", (), {"inputs": []})(), app.sb, agents.get(aid)
    assert r._outside_files() == ["Inbox/Agents/Clerk/Electric bill.txt"]


# ------------------------------------------------------------------ honest about what was checked
def test_with_no_web_key_the_report_says_only_wikipedia_was_searched(env, monkeypatch):
    app, fake, script, calls = env
    FakeWeb(monkeypatch)
    monkeypatch.setattr(websearch, "search", lambda q, key="", n=5: [])       # Wikipedia had nothing
    _on(app)
    assert not app.settings.web.ollama_key
    aid = make({"name": "R", "template": "researcher", "job": "What does propane cost?", "abilities": {"lookups": True}})
    script["pick"] = [{"action": "write", "instruction": "the answer"}]
    script["claims"] = [{"claims": [{"claim": "detail detail", "search": "propane price"}]}]
    last, folder = run(app, aid)
    rep = _report(folder)
    assert "only Wikipedia was searched" in rep and "not found (couldn't confirm it): detail detail" in rep
    assert "None of these could be confirmed. Treat them as unchecked." in rep


def test_a_made_up_yes_to_a_screen_doesnt_turn_an_ability_on(env):
    app, *_ = env
    for acks in ({"lookups": "yes"}, {"lookups": [1]}, "1", {"lookups": 99}):
        r = agents.save({"name": "X", "template": "researcher", "job": "j", "abilities": {"lookups": True}, "acks": acks})
        assert not r["ok"] and "say yes" in r["error"]
    assert not agents.ability_on({"abilities": {"lookups": "on"}, "acks": {"lookups": 1}}, "lookups")
