"""Joe's screens in other languages: the line collector, language files, and Joe translating himself."""
from __future__ import annotations

import json

from joeai import i18n, tools
from joeai.engine import Engine
from joeai.mission import parse
from joeai.ollama import ChatResult

from test_tools import app  # noqa: F401


def test_extract_finds_screen_text_not_code():
    lines = i18n.extract()
    assert len(lines) > 800
    for want in ("Joe Phone on", "[ PAIR A PHONE ]", "Setup", "Stopping after the current step."):
        assert want in lines, want
    assert any("{1}" in t for t in lines)                               # `Queued: ${x}` style lines
    for bad in ("/api/settings", "X-NR-Token", "application/json", "document.querySelector"):
        assert not any(t == bad or t.startswith(bad) for t in lines), bad


def test_builtin_spanish_and_own_file_on_top(app):  # noqa: F811
    es = i18n.load("es")
    assert es["Joe Phone on"] == "Joe Phone activado" and "_about" not in es
    assert i18n.load("en") == {} and i18n.load("xx") == {}
    own = app.sb.root / "Languages"
    own.mkdir()
    (own / "es.json").write_text(json.dumps({"Joe Phone on": "Joe Phone encendido", "Port": ""}), encoding="utf-8")
    es2 = i18n.load("es", app.sb)
    assert es2["Joe Phone on"] == "Joe Phone encendido" and es2["Port"] == "Puerto"   # blank lines don't wipe
    cov = i18n.coverage("es", app.sb)
    assert 10 < cov["pct"] <= 100 and cov["total"] == len(i18n.extract())
    names = {c["code"]: c for c in i18n.choices(app.sb)}
    assert names["en"]["pct"] == 100 and names["es"]["pct"] > 10 and names["fr"]["pct"] == 0


def test_joe_translates_his_screens(app, monkeypatch):  # noqa: F811
    lines = i18n.extract()
    monkeypatch.setattr(i18n, "extract", lambda: lines[:70])
    calls = []

    def fake_chat(self, job, part, kind, system, user, st, images=None, model=""):
        calls.append(kind)
        out = []
        for ln in user.splitlines():
            if "| " in ln and ln.split("|")[0].isdigit():
                n, text = ln.split("| ", 1)
                out.append(f"{n}| FR:{text}" if not (int(n) == 2) else f"{n}| broken")   # line 2 loses its {1}
        return ChatResult(text="\n".join(out), prompt_tokens=1, output_tokens=1, seconds=0.1)
    monkeypatch.setattr(Engine, "_chat", fake_chat)
    monkeypatch.setattr(Engine, "_text_ready", lambda self, st: True)
    st = Engine(app.settings, app.sb, log=lambda x: None).run_mission(
        parse("TASK: Joe in French\nTYPE: joe-language\nOPTIONS: to french"))[0]
    assert st.status == "done", st.note
    fr = json.loads((app.sb.root / "Languages" / "fr.json").read_text(encoding="utf-8"))
    assert fr["Joe"] == "FR:Joe" if "Joe" in lines[:70] else True
    assert len([k for k in fr if not k.startswith("_")]) >= 60 and set(calls) == {"translate"}
    assert all(v.startswith("FR:") or "{" not in k for k, v in fr.items() if not k.startswith("_"))
    assert i18n.coverage("fr", app.sb)["pct"] > 0


def test_language_tool_is_ready_and_planned():
    t = tools.TOOLS["joe-language"]
    assert t.ready and not t.accepts and "TYPE: joe-language" in tools.planner_lines()
    assert ("spanish", "Español (Spanish)") in t.options[0].choices


def test_extract_leaves_code_out_and_keeps_screen_lines():
    lines = set(i18n.extract())
    for code in ("joeToken", "({ name:", "return m.mission ?", "dot D L L", "[title]"):
        assert code not in lines, code
    for code_only in ("ok do it", "go ahead", "um, hey Joe ...", "C:\\JOE>", "Delete", "noopener noreferrer"):
        assert code_only not in lines, code_only           # answers the script listens for, a path, a key name
    for real in ("Home", "Tools", "Talk", "[ PAIR A PHONE ]", "[ STOP ]", "Needs your answer: {1}"):
        assert real in lines, real


def test_wordy_keeps_odd_looking_screen_lines():
    for ok in ("[ SAVE ]", "{1} of {2}", "Keep {1} in Favorites", "Joe v{1} · GPL-3.0-or-later", "Esc"):
        assert i18n._wordy(ok), ok
    for bad in ("joeToken", "({ name:", "return m.mission ?", "dot D L L", "[title]", "[translate=\"no\"], textarea, pre",
                "if (!t) { f.innerHTML = '", "18px {1}", "?force=1", "title=\"{1}\""):
        assert not i18n._wordy(bad), bad


def test_spanish_covers_nearly_every_screen_line():
    assert i18n.coverage("es")["pct"] >= 98


def test_extract_reads_text_hidden_behind_a_regex_or_comment_or_nested_string():
    src = (
        'x.replace(/[|#*`-]{2,}/g, " "); // a comment with a ` backtick and a "quote\n'
        'const a = `<p title="Hover text">${ok ? "Shown in a ternary" : "Other text"}</p>` + "Plain line";\n'
        'const b = `<div class="${hot ? "hot blink" : ""}">Real words ${n}</div>`;\n'
    )
    got = i18n._js_text(src)
    for want in ("Hover text", "Shown in a ternary", "Other text", "Plain line", "Real words {1}"):
        assert want in got, want
    for bad in ("hot blink", "a comment with a", "quote"):
        assert not any(bad in t for t in got), bad


def test_spanish_file_is_valid_and_keeps_placeholders():
    import re
    es = i18n.load("es")
    for k, v in es.items():
        assert set(re.findall(r"\{\d+\}", k)) == set(re.findall(r"\{\d+\}", v)), k
        if k.startswith("[ ") and k.endswith(" ]"):
            assert v.startswith("[ ") and v.endswith(" ]"), k
    assert es["Hey Joe"] == "Hey Joe" if "Hey Joe" in es else True


def test_placeholders_count_from_one_in_order():
    assert i18n.seq("Move {2} item{3} ({4}) to the Recycle Bin?") == "Move {1} item{2} ({3}) to the Recycle Bin?"
    assert i18n.seq("{3}/{4} done, {3}") == "{1}/{2} done, {1}"
    got = i18n._js_text("x = `<b>Hello ${q}</b> and ${r} more`; y = `<button aria-label=\"Edit ${a}\" title=\"Go ${b}\">`")
    assert "Hello {1}" in got and "and {1} more" in got              # each line counts from 1 by itself
    assert "Edit {1}" in got and "Go {1}" in got
    for k in i18n.extract():
        assert k == i18n.seq(k), k                    # the window matches by position: {1}, {2}, ... in order
    for k, v in i18n.load("es").items():
        if "{" in k:
            assert k == i18n.seq(k), k
            assert set(__import__("re").findall(r"\{(\d+)\}", v)) <= set(__import__("re").findall(r"\{(\d+)\}", k)), k


def test_nested_template_and_a_tag_split_over_two_strings():
    src = ("a = `<div>Installing${s ? \": \" + e(s) + (p ? ` ${p}%` : \"\") : \"…\"} (${q} more after this)</div>`;\n"
           "b = `<button aria-label=\"Keep ${n} in Favorites\"` +\n `>x</button>`;")
    got = i18n._js_text(src)
    assert "Installing{1} ({2} more after this)" in got
    assert "Keep {1} in Favorites" in got
