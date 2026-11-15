"""The Tools tab shows tools in closed categories from a table in app.js (TOOL_CATS).
A tool the table doesn't know still shows under "More tools"; this test makes sure none is forgotten."""
import json
import re
from pathlib import Path

from joeai import tools

UI = Path(__file__).resolve().parent.parent / "joeai" / "ui"


def _table() -> list[list]:
    js = (UI / "app.js").read_text(encoding="utf-8")
    block = js[js.index("const TOOL_CATS = ["):js.index("const TOOL_CAT_OF")]
    rows = re.findall(r'^\s*\[("[^"]*"), ("[^"]*"), ("[^"]*"), (\[[^\]]*\])\],?\s*$', block, re.M)
    return [[json.loads(a), json.loads(b), json.loads(c), json.loads(d)] for a, b, c, d in rows]


def test_every_tool_has_exactly_one_category():
    rows = _table()
    ids = [i for r in rows for i in r[3]]
    assert len(ids) == len(set(ids)), "a tool id is listed in two categories"
    assert set(ids) == set(tools.TOOLS), (
        f"missing from TOOL_CATS: {sorted(set(tools.TOOLS) - set(ids))}; "
        f"not a tool any more: {sorted(set(ids) - set(tools.TOOLS))}")


def test_category_names_and_nesting():
    rows = _table()
    top = [r[0] for r in rows if r[2] == ""]
    assert top == ["Write and edit", "Read and understand", "Files and spreadsheets", "Pictures", "Video", "Sound and voice"]
    assert [r[0] for r in rows if r[2] == "Pictures"] == ["Fix and prepare", "Change", "Make new", "Sort and describe"]
    assert len({r[0] for r in rows}) == len(rows)
    assert all(r[0] == r[1] for r in rows)          # every box looks the same: one plain name
    assert all(r[3] == [] for r in rows if r[0] == "Pictures")   # Pictures holds boxes, not tools
    assert {r[2] for r in rows} <= {"", "Pictures"}  # only one level of nesting


def test_no_box_is_too_big():
    """The agreed rule: a box with more than about 15 tools gets boxes inside it (as Pictures has)."""
    for name, _, _, ids in _table():
        assert len(ids) <= 15, f"{name} has {len(ids)} tools: split it into boxes"


def test_category_buttons_are_real_buttons_with_state():
    js = (UI / "app.js").read_text(encoding="utf-8")
    assert 'class="tcathead"' in js and 'aria-expanded="${open}"' in js and "aria-controls" in js
    css = (UI / "app.css").read_text(encoding="utf-8")
    assert ".tcards[hidden] { display: none; }" in css
    assert ".tsubs[hidden] { display: none; }" in css     # a box that holds boxes (Pictures)
    assert ".toolform[hidden] { display: none; }" in css   # .toolform is display:flex, which beats the hidden attribute
