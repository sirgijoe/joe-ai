"""2.3 stage 3: low vision (high contrast, large text), screen-reader announcements, voice navigation."""
from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from joeai import chat, resultsnav
from joeai.config import Settings, reset_paths
from joeai.sandbox import Sandbox

UI = Path(__file__).parent.parent / "joeai" / "ui"


# ------------------------------------------------------------------ seeing the screen
def test_high_contrast_themes_and_large_text_are_in_setup():
    html = (UI / "index.html").read_text(encoding="utf-8")
    css = (UI / "app.css").read_text(encoding="utf-8")
    js = (UI / "app.js").read_text(encoding="utf-8")
    for v in ("contrast-dark", "contrast-light"):
        assert f'value="{v}"' in html and f"body.ph-{v}" in css and f'"{v}"' in js
    assert 'data-path="ui.large_text"' in html and 'data-path="ui.announce"' in html
    assert "prefers-contrast: more" in css and "forced-colors: active" in css
    assert 'id="sr-live"' in html and 'aria-live="polite"' in html and 'id="sr-alert"' in html and 'role="alert"' in html


def _lum(hexcol: str) -> float:
    r, g, b = (int(hexcol[i:i + 2], 16) / 255 for i in (1, 3, 5))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4   # noqa: E731
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


@pytest.mark.parametrize("theme", ["contrast-dark", "contrast-light"])
def test_high_contrast_meets_wcag_aaa(theme):
    css = (UI / "app.css").read_text(encoding="utf-8")
    block = re.search(r"body\.ph-" + theme + r" \{([^}]*)\}", css).group(1)
    v = dict(re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{6})", block))
    for fg, bg in (("--ph", "--bg"), ("--ph-dim", "--bg"), ("--on-accent", "--accent"), ("--accent", "--bg")):
        a, b = sorted((_lum(v[fg]), _lum(v[bg])), reverse=True)
        assert (a + 0.05) / (b + 0.05) >= 7, (theme, fg, bg)


def test_new_display_settings_reset_with_their_page():
    s = Settings()
    s.ui.large_text, s.ui.announce = "larger", "off"
    assert set(reset_paths(s, ["ui.large_text", "ui.announce"])) == {"ui.large_text", "ui.announce"}
    assert (s.ui.large_text, s.ui.announce) == ("normal", "progress")


# ------------------------------------------------------------------ voice navigation
LIST = ("Here are your ideas:\n1. Blue mugs for spring\n2. Speckled bowls [CHECK: price]\n"
        "3. A kiln opening party\n4. Gift sets [CHECK: shipping]\n5. Classes")


def _app(tmp_path, report=""):
    sb = Sandbox(tmp_path / "ws").ensure()
    if report:
        (sb.output / "_REPORT.md").write_text(report, encoding="utf-8")
    return SimpleNamespace(sb=sb)


def _talk(app, history, text):
    r = resultsnav.answer(app, history, text)
    return r["say"] if r else None


def test_commands_are_recognised_and_ordinary_talk_is_left_alone():
    yes = {"read the third one": ("item", "third"), "number 4": ("item", "4"), "read me the 12th one": ("item", "12th"),
           "what's the last one?": ("item", "last"), "next": ("next", None), "okay, next one please": ("next", None),
           "go back": ("prev", None), "repeat that": ("again", None), "skip to the CHECK items": ("check", None),
           "what needs checking": ("check", None), "how many are there?": ("count", None),
           "read the list": ("list", None)}
    for t, (kind, word) in yes.items():
        c = resultsnav.command(t)
        assert c and c["kind"] == kind and c.get("word") == word, t
    for t in ("write me a story about a third grader", "next week I want a cake", "read the report",
              "make 20 captions", "what's the weather", "x" * 100):
        assert resultsnav.command(t) is None, t


def test_moving_through_joes_last_list(tmp_path):
    app = _app(tmp_path)
    h = [{"role": "user", "content": "ideas?"}, {"role": "assistant", "content": LIST}]
    assert _talk(app, h, "read the third one") == "Number 3 of 5. A kiln opening party"
    assert _talk(app, h, "next").startswith("Number 4 of 5. Gift sets")
    assert _talk(app, h, "go back").startswith("Number 3 of 5")
    assert _talk(app, h, "again").startswith("Number 3 of 5")
    assert _talk(app, h, "the last one").startswith("Number 5 of 5. Classes")
    assert _talk(app, h, "next") == "That was the last one."
    assert _talk(app, h, "number 9") == "There are only 5 in the list."
    assert _talk(app, h, "how many are there?") == "There are 5 in the list, 2 marked CHECK."
    s = _talk(app, h, "skip to the CHECK items")
    assert s.startswith("Number 2 of 5, CHECK item 1 of 2. Speckled bowls")
    assert "Number 4 of 5, CHECK item 2 of 2" in _talk(app, h, "next")
    assert _talk(app, h, "next") == "That was the last one marked CHECK."
    assert _talk(app, h, "read the list").startswith("5 in the list. 1: Blue mugs")


def test_nothing_to_move_through_goes_to_joe(tmp_path):
    app = _app(tmp_path)
    assert _talk(app, [{"role": "assistant", "content": "Just one sentence."}], "next") is None
    assert _talk(app, [], "read the third one") is None
    h = [{"role": "assistant", "content": LIST}]
    assert _talk(app, h, "again") is None                  # nothing read yet: "again" may mean "do it again"


def test_the_morning_report(tmp_path):
    rep = ("# Joe report\n\n| Task | Status | File |\n|---|---|---|\n| Mugs | done | a.md |\n"
           "| Bowls | partial | b.md |\n\n## Flags\n- Bowls: price [CHECK]\n")
    app = _app(tmp_path, rep)
    h = [{"role": "assistant", "content": "Done."}]
    assert _talk(app, h, "how many in the report") == "There are 3 in the report, 1 marked CHECK."
    assert "Bowls — partial — b.md" in _talk(app, h, "read the second item in the report")
    assert "Bowls: price [CHECK]" in _talk(app, h, "next")         # keeps to the report
    empty = _app(tmp_path / "e")
    assert _talk(empty, h, "how many in the report") == "There's no morning report with a list in it yet."


def test_items_from_joes_own_list_files():
    text = "# Blurbs\n\n## Blue mug\nA calm blue.\nDishwasher safe.\n\n## Red bowl\nBright.\n"
    assert resultsnav.items(text) == ["Blue mug\nA calm blue.\nDishwasher safe.", "Red bowl\nBright."]


def test_talk_answers_navigation_without_a_model(tmp_path):
    app = _app(tmp_path)
    app.services = SimpleNamespace(ensure_ollama=lambda: (_ for _ in ()).throw(AssertionError("no model")))
    p = chat.prepare(app, [{"role": "assistant", "content": LIST}], "read the second one")
    assert p["final"]["say"].startswith("Number 2 of 5. Speckled bowls")
