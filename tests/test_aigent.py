"""2.4 Joe-AiGent: the one agent. The manager does the work; the Coder writes code, the Tester proves it in
the box (test first), the Improver only keeps changes that still pass. Scripted model, real box."""
from __future__ import annotations

import json
from pathlib import Path

from joeai import agentrun, agents, codebox

from agent_env import env, make, run  # noqa: F401 (env is a fixture)

TEST = ("from slug import slugify\n\n"
        "def test_plain():\n    assert slugify('Hello World') == 'hello-world'\n\n"
        "def test_marks():\n    assert slugify('  A  b!! c ') == 'a-b-c'\n\n"
        "def test_empty():\n    assert slugify('') == ''\n")
GOOD = ("import re\n\n\ndef slugify(text):\n    \"\"\"Lower-case words joined by dashes.\"\"\"\n"
        "    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')\n")
BAD = "def slugify(text):\n    return text.lower().replace(' ', '-')\n"
CODE_STEP = {"action": "code", "name": "Slug", "instruction": "slugify(text) turns 'Hello World' into 'hello-world'"}


def aigent(**kw):
    data = {"name": "Joe-AiGent", "template": "aigent", "job": "write a slugify function in Python, with tests",
            "abilities": {"code": True}, "tools": ["text"], "improve": 0}
    data.update(kw)
    return make(data)


def test_joe_aigent_is_the_one_agent_offered_and_the_five_still_load(env):
    assert agents.ONE == "aigent" and agents.TEMPLATES["aigent"]["name"] == "Joe-AiGent"
    assert [k for k, t in agents.TEMPLATES.items() if not t.get("retired")] == ["aigent"]
    aid = aigent()
    a = agents.get(aid)
    assert a["tries"] == agents.DEFAULT_TRIES and a["improve"] == 0 and a["steps"] == 60 and a["minutes"] == 480
    assert agents.get("joe aigent")["id"] == aid and agents.get("Joe-AiGent")["id"] == aid and agents.get("joe agent")["id"] == aid
    old = make({"name": "Old researcher", "job": "what is a heat pump", "template": "researcher"})
    assert agents.get(old)["template"] == "researcher" and "tries" not in agents.get(old)


def test_his_limits_are_higher_but_never_without_a_limit(env):
    aid = aigent(steps=9999, minutes=9999, tries=99, improve=99, max_fails=9999)
    a = agents.get(aid)
    assert (a["steps"], a["minutes"], a["tries"], a["improve"], a["max_fails"]) == (300, 720, 10, 10, 100)
    old = make({"name": "R", "job": "j", "template": "researcher", "steps": 9999, "minutes": 9999})
    assert (agents.get(old)["steps"], agents.get(old)["minutes"]) == (30, 240)        # the five keep their old limits


def test_code_is_off_until_its_screen_is_read_and_said_yes_to(env):
    r = agents.save({"name": "J", "template": "aigent", "job": "j", "abilities": {"code": True}})
    assert not r["ok"] and "Write code and test it in the box" in r["error"]
    aid = make({"name": "J", "template": "aigent", "job": "write code", "abilities": {}})
    app, fake, script, calls = env
    script["pick"] = [dict(CODE_STEP), {"done": True}]
    last, folder = run(app, aid)
    assert not (folder / "Code").exists() and calls["tester"] == [] and calls["coder"] == []
    assert "which this agent may not do" in (folder / "AGENT LOG.txt").read_text("utf-8")
    assert "researcher" not in [k for k, t in agents.TEMPLATES.items() if "code" in t["actions"] and t.get("retired")]
    for k, t in agents.TEMPLATES.items():
        assert ("code" in t["actions"]) == (k == "aigent")


def test_test_first_then_code_that_passes_in_the_box_is_kept(env):
    app, fake, script, calls = env
    aid = aigent()
    script["plan"] = [{"points": ["A slugify function that passes its tests"]}]
    script["pick"] = [dict(CODE_STEP)]
    script["tester"] = ["Here is the test:\n```python\n" + TEST + "```\n"]
    script["coder"] = ["```python\n" + GOOD + "```"]
    last, folder = run(app, aid)
    assert last["status"] == "done", last
    assert (folder / "Code" / "slug.py").read_text("utf-8") == GOOD
    assert (folder / "Code" / "test_slug.py").read_text("utf-8") == TEST
    assert not (folder / "Code" / "not working").exists()
    # test first: the Tester was asked before the Coder, and never saw any code
    assert len(calls["tester"]) == 1 and "slug.py" in calls["tester"][0] and "def slugify" not in calls["tester"][0]
    assert "from slug import slugify" in calls["coder"][0]                  # the Coder gets the test to pass
    rep = (folder / "AGENT REPORT.md").read_text("utf-8")
    assert "## Code" in rep and "WORKS: Code/slug.py passes its 3 test(s) (try 1)" in rep
    assert "never on your PC itself" in rep and "its own empty folder" in rep and "ASK A BIGGER AI.md" in rep
    ask = (folder / "Code" / "ASK A BIGGER AI.md").read_text("utf-8")
    assert "def slugify" in ask and "def test_plain" in ask and "passes its 3 test(s)" in ask
    assert "code: 1 of 1 program(s) pass their tests" in last["note"]
    assert "code slug.py: WORKS" in calls["tick"][-1]                        # the plan is ticked on the box's word


def test_a_failing_try_goes_back_to_the_coder_with_what_the_box_said(env):
    app, fake, script, calls = env
    aid = aigent()
    script["pick"] = [dict(CODE_STEP)]
    script["tester"] = [TEST]
    script["coder"] = [BAD, GOOD]
    last, folder = run(app, aid)
    assert last["status"] == "done" and (folder / "Code" / "slug.py").read_text("utf-8") == GOOD
    assert len(calls["coder"]) == 2 and "What the Tester's box said" in calls["coder"][1]
    assert "test_marks" in calls["coder"][1] and "return text.lower()" in calls["coder"][1]
    assert TEST in calls["coder"][1]                                        # the test itself never changes
    log = (folder / "AGENT LOG.txt").read_text("utf-8")
    assert "try 1 of 4: 1 of 3 test(s) failed" in log and "try 2 of 4: 3 test(s) passed" in log
    assert "passes its 3 test(s) (try 2)" in (folder / "AGENT REPORT.md").read_text("utf-8")


def test_code_that_never_passes_is_set_aside_noted_and_the_manager_moves_on(env):
    app, fake, script, calls = env
    aid = aigent(tries=2)
    script["plan"] = [{"points": ["A slugify function", "A short note about it"]}]
    script["pick"] = [dict(CODE_STEP), {"action": "write", "title": "Note", "instruction": "write a short note"}]
    script["tester"] = [TEST]
    script["coder"] = [BAD, BAD]
    script["tick"] = [{"done": []}, {"done": [2]}, {"done": []}, {"done": []}, {"done": []}, {"done": []},
                      {"done": []}, {"done": []}, {"done": []}]
    last, folder = run(app, aid)
    assert last["status"] == "partial", last                                # never "done" with code that doesn't work
    nw = folder / "Code" / "not working"
    assert (nw / "slug.py").read_text("utf-8") == BAD and (nw / "test_slug.py").exists()
    assert "did not pass its test after 2 tries" in (nw / "slug - what the test said.txt").read_text("utf-8")
    assert not (folder / "Code" / "slug.py").exists()                       # never beside the working code
    assert len(calls["coder"]) == 2                                         # the tries limit held
    rep = (folder / "AGENT REPORT.md").read_text("utf-8")
    assert "[CHECK] NOT WORKING: slug.py" in rep and "0 of 1 program(s) pass" in rep
    assert [p.name for p in folder.glob("*.md") if p.name[:2].isdigit()] == ["02-text.md"]      # he went on to the next point
    assert "set aside in Code/not working, moving on" in (folder / "AGENT LOG.txt").read_text("utf-8")
    assert "NOT WORKING (set aside)" in (folder / "Code" / "ASK A BIGGER AI.md").read_text("utf-8")
    assert "does NOT work" in calls["tick"][0]


def test_the_tester_must_write_a_real_test(env):
    app, fake, script, calls = env
    aid = aigent()
    script["pick"] = [dict(CODE_STEP)]
    script["tester"] = ["print('looks fine to me')", "x = 1\n"]
    last, folder = run(app, aid)
    assert len(calls["tester"]) == 2 and calls["coder"] == []               # no test, so no code is run at all
    assert "the Tester couldn't write a test for it" in (folder / "AGENT REPORT.md").read_text("utf-8")
    assert last["status"] != "done"


def test_code_runs_only_in_the_box(env, monkeypatch, tmp_path):
    """The Coder's code tries to write outside its folder and reach the network: the box stops both, the
    owner's file is untouched, and Joe's own process never imports the code."""
    app, fake, script, calls = env
    victim = tmp_path / "keep.txt"
    victim.write_text("keep me")
    evil = ("import socket\n\n\ndef slugify(text):\n"
            f"    open({str(victim)!r}, 'w').write('gone')\n"
            "    socket.create_connection(('example.com', 80), timeout=2)\n    return 'hello-world'\n")
    seen = []
    real = codebox.run
    monkeypatch.setattr(codebox, "run", lambda *a, **k: seen.append(a[1]) or real(*a, **k))
    aid = aigent(tries=1)
    script["pick"] = [dict(CODE_STEP)]
    script["tester"] = [TEST]
    script["coder"] = [evil]
    last, folder = run(app, aid)
    assert seen == ["test_slug.py"] and victim.read_text() == "keep me"
    said = (folder / "Code" / "not working" / "slug - what the test said.txt").read_text("utf-8")
    assert "the box" in said and "may only write inside its own folder" in said
    import sys
    assert "slug" not in sys.modules


def test_the_improver_keeps_only_changes_that_still_pass(env):
    app, fake, script, calls = env
    aid = aigent(improve=3)
    better = GOOD.replace("Lower-case words joined by dashes.", "Lower-case words joined by single dashes; '' for ''.")
    script["pick"] = [dict(CODE_STEP)]
    script["tester"] = [TEST]
    script["coder"] = [GOOD]
    script["improver"] = ["```python\n" + better + "```", BAD, "NOTHING"]
    last, folder = run(app, aid)
    assert last["status"] == "done"
    assert (folder / "Code" / "slug.py").read_text("utf-8") == better        # round 1's change passed and was kept
    log = (folder / "AGENT LOG.txt").read_text("utf-8")
    assert "still passes its 3 test(s); kept" in log
    assert "broke a test" in log and "thrown away, the working version stays" in log      # round 2's change didn't
    assert "nothing worth keeping in round 2" in log and len(calls["improver"]) == 2      # ...so he stopped there
    assert "then improved 1 time(s), tests still passing" in (folder / "AGENT REPORT.md").read_text("utf-8")


def test_the_improver_is_off_at_zero_and_never_touches_code_that_failed(env):
    app, fake, script, calls = env
    aid = aigent(improve=0)
    script["pick"] = [dict(CODE_STEP)]
    script["tester"] = [TEST]
    script["coder"] = [GOOD]
    run(app, aid)
    assert calls["improver"] == []
    aid2 = aigent(name="Second", improve=2, tries=1)
    script["pick"] = [dict(CODE_STEP)]
    script["tester"] = [TEST]
    script["coder"] = [BAD]
    script["tick"] = [{"done": []}] * 9
    run(app, aid2)
    assert calls["improver"] == []


def test_two_programs_get_two_names_and_odd_names_are_made_plain(env):
    app, fake, script, calls = env
    aid = aigent()
    script["plan"] = [{"points": ["one", "two"]}]
    script["pick"] = [{"action": "code", "name": "../../Evil Name!.py", "instruction": "slugify"},
                      {"action": "code", "name": "evil_name", "instruction": "slugify again"}]
    script["tester"] = [TEST.replace("from slug import", "from evil_name import"),
                        TEST.replace("from slug import", "from evil_name_2 import")]
    script["coder"] = [GOOD, GOOD]
    script["tick"] = [{"done": [1]}, {"done": [2]}]
    last, folder = run(app, aid)
    names = sorted(p.name for p in (folder / "Code").glob("*.py"))
    assert names == ["evil_name.py", "evil_name_2.py", "test_evil_name.py", "test_evil_name_2.py"], names
    assert last["status"] == "done"


def test_a_big_job_gets_a_longer_plan(env):
    app, fake, script, calls = env
    aid = aigent()
    script["plan"] = [{"points": [f"point {i}" for i in range(1, 31)]}]
    script["pick"] = [{"action": "write", "title": "T", "instruction": "write"}]
    last, folder = run(app, aid)
    assert len(last["plan"]) == 20
    assert any("up to 20 for a big one" in r["messages"][0]["content"] for r in fake.requests)
    old = make({"name": "M", "job": "j", "template": "maker"})
    script["plan"] = [{"points": [f"point {i}" for i in range(1, 31)]}]
    script["pick"] = [{"action": "write", "title": "T", "instruction": "write"}]
    last, _ = run(app, old)
    assert len(last["plan"]) == agentrun.MAX_POINTS


def test_clean_code_takes_the_file_out_of_a_chatty_answer():
    assert agentrun.clean_code("Sure!\n```python\nx = 1\n```\nHope that helps!") == "x = 1\n"
    assert agentrun.clean_code("```\nx = 1\n```") == "x = 1\n"
    assert agentrun.clean_code("=== FILE: a.py ===\nx = 1\n") == "x = 1\n"
    assert agentrun.clean_code("x = 1") == "x = 1\n" and agentrun.clean_code("") == "" and agentrun.clean_code(None) == ""
    assert agentrun.clean_code("```python\nx = 1\n") == "x = 1\n"            # the model ran out of words before closing it


def test_talk_knows_him_by_name(env):
    from joeai import route
    want = {"kind": "command", "cmd": "agent-start", "name": "joe aigent"}
    for said in ("start Joe agent", "Hey Joe, run Joe-AiGent.", "wake up joe AI gent", "please start the joe aigent"):
        assert route.classify(said) == want, said
    for said, req in (("ask Joe agent to write a slugify function with tests", "write a slugify function with tests"),
                      ("Joe AiGent, research heat pumps for my house.", "research heat pumps for my house"),
                      ("have joe-aigent make a budget script", "make a budget script")):
        assert route.classify(said) == {**want, "request": req}, said
    for chat_line in ("Joe agent is a funny name", "what is Joe AiGent?", "is joe agent still working"):
        assert route.classify(chat_line).get("name") != "joe aigent", chat_line
    aid = aigent()
    assert agents.get("joe aigent")["id"] == aid
    agents.set_paused(aid, True)
    assert agents.get("joe aigent") is None                                   # a paused job isn't started by name


def test_a_program_is_never_named_after_a_part_of_python(env):
    app, fake, script, calls = env
    aid = aigent()
    script["pick"] = [{"action": "code", "name": "json", "instruction": "slugify"}]
    script["tester"] = [TEST.replace("from slug import", "from json_code import")]
    script["coder"] = [GOOD]
    last, folder = run(app, aid)
    assert (folder / "Code" / "json_code.py").exists() and last["status"] == "done"


def test_his_window_has_joes_face_and_still_only_reads_and_stops():
    ui = Path(agentrun.__file__).with_name("ui")
    html, js = (ui / "agent.html").read_text("utf-8"), (ui / "agent.js").read_text("utf-8")
    assert '<script src="/joe.js"></script>' in html and html.index("/joe.js") < html.index("/agent.js")
    assert 'id="aw-sprite" class="aw-sprite joeface" aria-hidden="true"' in html       # decoration: the words carry the news
    assert "JoeFace.attach(el, mode)" in js and 'JoeFace.mood(run && run.status === "done" ? "happy" : "worried")' in js
    assert '"/api/voice/status"' in js and 'el.hidden = mode === "off"' in js           # Talk's on / still / off switch
    css = (ui / "app.css").read_text("utf-8")
    assert ".aw-sprite.joeface:not([hidden]) ~ .aw-bar { width: auto; overflow: hidden; }" in css   # the bar stops at the face
    assert html.index('id="aw-sprite"') < html.index('class="asbar aw-bar"')
    code = "\n".join(ln for ln in js.splitlines() if not ln.lstrip().startswith(("/*", "*", "//")))
    for bad in ("/api/agents/", "/api/run", "/api/settings"):
        assert bad not in code


def test_the_page_offers_only_him_and_his_limits():
    ui = Path(agentrun.__file__).with_name("ui")
    html, js = (ui / "index.html").read_text("utf-8"), (ui / "app.js").read_text("utf-8")
    assert 'id="ag-tries"' in html and 'id="ag-improve"' in html and 'id="ag-code-limits" hidden' in html
    assert '<span class="aigent-name">Joe-AiGent</span>' in html and "underline" not in html.split("aigent-name")[1][:80]
    assert "tpl.max_steps || 30" in js and "tpl.max_minutes || 240" in js and "tries: +$(\"#ag-tries\").value" in js
    assert "never runs code outside the box" in html
    assert "[ START ${nm} ]" in js and "[ START NOW ]" not in js                           # each START says whose it is
    assert "const nm = esc((a.name.length > 28" in js                                      # made safe after the capitals
    for label in ('aria-label="Edit ${full}"', 'aria-label="Copy ${full}"', 'aria-label="Delete ${full}"'):
        assert label in js
