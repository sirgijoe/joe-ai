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
    assert 10 < cov["pct"] < 100 and cov["total"] == len(i18n.extract())
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
