"""UI reorganization steps 12-13: the agent window (/agent) and the status strip's button."""
from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "joeai" / "ui"
JS = (UI / "agent.js").read_text(encoding="utf-8")
HTML = (UI / "agent.html").read_text(encoding="utf-8")
APP = (UI / "app.js").read_text(encoding="utf-8")
INDEX = (UI / "index.html").read_text(encoding="utf-8")
CSS = (UI / "app.css").read_text(encoding="utf-8")
SERVER = (Path(__file__).resolve().parent.parent / "joeai" / "server.py").read_text(encoding="utf-8")


def test_window_key_comes_from_the_address_and_never_the_page():
    assert "#&]t=" in JS and "X-NR-Token" in JS
    assert "__TOKEN__" not in HTML and "?t=" not in JS
    assert '"/agent#t="' in APP                      # the main window passes it in the #part


def test_the_page_only_reads_and_stops_never_starts_or_turns_abilities_on():
    code = "\n".join(l for l in JS.splitlines() if not l.lstrip().startswith(("/*", "*")))
    for bad in ("/api/agents/", "abilities", "/api/run", "/api/settings"):
        assert bad not in code                        # it reads /api/agents (the last run) and nothing else
    assert '"/api/stop"' in JS and "aw-confirm" in HTML      # STOP asks first


def test_end_states_and_a_polite_live_region():
    for w in ("DONE", "STUCK", "STOPPED", "Needs your answer"):
        assert w in JS
    assert 'aria-live="polite"' in HTML and "PAUSE" not in JS and "PAUSE" not in HTML


def test_server_serves_the_page_and_script_without_a_key():
    assert 'u.path == "/agent"' in SERVER and '"/agent.js"' in SERVER


def test_strip_button_uses_a_new_action_and_old_agent_code_is_untouched():
    assert 'data-act="agent-window"' in INDEX and 'act === "agent-window"' in APP
    assert '$("#toolgrid").innerHTML = agRow() + html;' in APP        # Joe-AiGent's row is always there (2.4)
    assert 'data-act="agent-stop"' in INDEX


def test_main_text_boxes_have_accessible_names():
    import re
    for i in ("describe", "mission", "b-paste", "talk-in", "bg-msg", "bg-answer", "pk-for", "tool-find"):
        tag = re.search(r'<(?:textarea|input) id="%s"[^>]*>' % i, INDEX)
        assert tag and ("aria-label" in tag.group(0) or "aria-labelledby" in tag.group(0)), i


def test_a_second_open_takes_the_key_out_of_the_address_and_comes_to_the_front():
    assert 'addEventListener("hashchange", takeKey)' in JS and "history.replaceState" in JS
    assert "w.focus()" in APP


def test_the_small_page_can_scroll_at_any_width():
    assert ".agentwin { margin: 0; overflow: auto; }" in CSS       # body is overflow:hidden for the main window


def test_plain_words_when_joe_is_closed_and_lists_only_redrawn_on_change():
    assert "Joe isn't answering. Is Joe still open?" in JS and "draw !== lastDraw" in JS


def test_the_window_speaks_the_chosen_language():
    import json
    from joeai import i18n
    assert '"/api/lang?code="' in JS and HTML.count("data-t") >= 9
    es = json.loads((UI.parent / "lang" / "es.json").read_text(encoding="utf-8"))
    for line in ("AGENT: {1}", "Step {1} of {2}.", "[ CLOSE THIS WINDOW ]", "STUCK", "Stop the agent?"):
        assert line in es, line
    lines = i18n.extract()
    assert "Stop the agent?" in lines and "Step {1} of {2}." in lines      # other languages get these lines too
