"""WHAT CAN JOE DO? (batch 5b): one source of truth, built from the code."""
from joeai import abilities, route, tools


def test_every_tool_is_explained_step_by_step():
    ready = [t.id for t in tools.TOOLS.values() if t.ready]
    missing = [t for t in ready if t not in abilities.STEPS]
    assert not missing, f"add STEPS for: {missing}"
    assert not set(abilities.STEPS) - set(tools.TOOLS)          # no leftovers for removed tools


def test_overview_lists_everything_once():
    text = abilities.overview()
    for a in abilities.all_abilities():
        assert f"- {a.name}:" in text
    assert text.rstrip().endswith(abilities.MORE)
    ids = [a.id for a in abilities.all_abilities()]
    assert len(ids) == len(set(ids))


def test_each_explanation_has_the_parts():
    for a in abilities.all_abilities():
        e = abilities.explain(a.id)
        assert e and e["title"] == a.name and len(e["text"]) > 150, a.id
        assert "What it does" in e["text"], a.id
    t = abilities.explain("tool:restore-photo")["text"]
    for part in ("How Joe does it", "What to give it", "Options:", "Needs:", "Scanning tips"):
        assert part in t
    assert abilities.explain("nope") is None


def test_questions_find_the_right_ability():
    cases = {"How does restore photo work?": "tool:restore-photo",
             "tell me about the night shift": "night-shift",
             "how do i use make shorts": "tool:make-shorts",
             "explain portable joe": "portable",
             "what does fix one spot do": "tool:fix-spot",
             "how do pictures work?": "pictures",
             "tell me more about templates": "exports",
             "how does transcribe work": "tool:transcribe"}
    for q, want in cases.items():
        a = abilities.answer(q)
        assert a and a["id"] == want, (q, a and a.get("id"))
    assert abilities.answer("what can you do?")["kind"] == "overview"
    assert abilities.answer("What all can you do") ["kind"] == "overview"
    assert abilities.answer("what is the weather today?") is None
    assert abilities.answer("restore my photo") is None


def test_route_sends_them_to_the_explainer():
    assert route.classify("what can you do?") == {"kind": "command", "cmd": "abilities"}
    assert route.classify("how does restore photo work?") == {"kind": "command", "cmd": "explain",
                                                               "id": "tool:restore-photo"}
    assert route.classify("restore my photo")["kind"] == "plan"
    assert route.classify("help") == {"kind": "command", "cmd": "help"}


def test_talk_answers_without_the_model():
    from joeai import chat

    class App:                       # prepare must not touch Ollama for these
        services = None
    p = chat.prepare(App(), [], "Can you explain how the make shorts tool works?")
    assert p["final"]["ok"] and "1080x1920" in p["final"]["say"]
