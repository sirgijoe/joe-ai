"""Add-ons from other people: reading, safe unpacking, turning on/off, tamper check, running tools."""
from __future__ import annotations

import io
import json
import shutil
import zipfile
from pathlib import Path

import pytest

from joeai import community, packs, tools
from joeai.engine import Engine
from joeai.mission import parse

from test_tools import app  # noqa: F401

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "addons" / "simple-extras"


def _zip(folder: Path, top: str = "") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for p in folder.rglob("*"):
            if p.is_file():
                z.write(p, top + str(p.relative_to(folder)).replace("\\", "/"))
    return buf.getvalue()


@pytest.fixture
def clean():
    yield
    community._registered.clear()
    community._by_type.clear()
    for k in [k for k in tools.TOOLS if k.startswith(community.TOOL_PREFIX)]:
        tools.TOOLS.pop(k)


def test_example_addon_installs_off_then_turns_on(app, clean):  # noqa: F811
    r = community.install_zip(app.sb, _zip(EXAMPLE, "simple-extras/"))
    assert r["ok"] and r["id"] == "simple-extras", r
    [a] = community.scan(app.sb)
    assert a["state"] == "off" and "x-word-count" not in tools.TOOLS
    d = community.describe(a)
    assert d["tools"][1]["program"].endswith(("python", "python3", "python.exe")) or "python" in d["tools"][1]["program"]
    assert "{addon}/wordcount.py" in d["tools"][1]["command"]
    assert community.enable(app.sb, "simple-extras", True)["ok"]
    assert tools.TOOLS["x-word-count"].ready and "TYPE: x-word-count" in tools.planner_lines()
    assert (app.sb.missions / "Packs" / "simple-extras--yard-sale.txt").exists()
    assert any(p["name"] == "Yard sale kit" for p in packs.list_packs(app.sb))
    assert community.enable(app.sb, "simple-extras", False)["ok"]
    assert "x-word-count" not in tools.TOOLS and not (app.sb.missions / "Packs" / "simple-extras--yard-sale.txt").exists()


def test_changed_files_turn_it_off(app, clean):  # noqa: F811
    community.install_zip(app.sb, _zip(EXAMPLE))
    community.enable(app.sb, "simple-extras", True)
    assert community.scan(app.sb)[0]["state"] == "on"
    script = community.root(app.sb) / "simple-extras" / "wordcount.py"
    script.write_text(script.read_text() + "\n# sneaky change\n")
    assert community.scan(app.sb)[0]["state"] == "changed"
    community.refresh(app.sb)
    assert "x-word-count" not in tools.TOOLS


def test_tool_runs_on_a_copy(app, clean):  # noqa: F811
    community.install_zip(app.sb, _zip(EXAMPLE))
    community.enable(app.sb, "simple-extras", True)
    essay = app.sb.inbox / "essay.txt"
    essay.write_text("Hello there. This is a short essay!\n\nIt has two paragraphs.", encoding="utf-8")
    st = Engine(app.settings, app.sb, log=lambda x: None).run_mission(
        parse("TASK: Count  TYPE: x-word-count\nINPUT: essay.txt\nOPTIONS: longest"))[0]
    assert st.status == "done", st.note
    out = (app.sb.output / st.output / "essay-count.md").read_text(encoding="utf-8")
    assert "- Words: 11" in out and "- Paragraphs: 2" in out and "Longest sentences" in out
    assert essay.read_text(encoding="utf-8").startswith("Hello there")


def test_missing_program_and_failures_are_plain(app, clean, tmp_path):  # noqa: F811
    folder = tmp_path / "a"
    folder.mkdir()
    (folder / "addon.json").write_text(json.dumps({"id": "needs-magick", "name": "Needs it", "homepage": "https://example.org",
        "tools": [{"id": "shrink", "accepts": [".png"], "program": "definitely-not-installed-xyz",
                   "args": ["{input}", "{output}"]}]}))
    community.install_zip(app.sb, _zip(folder))
    community.enable(app.sb, "needs-magick", True)
    (app.sb.inbox / "a.png").write_bytes(b"x")
    st = Engine(app.settings, app.sb, log=lambda x: None).run_mission(parse("TASK: S  TYPE: x-shrink\nINPUT: a.png"))[0]
    assert st.status == "failed" and "isn't on this PC" in st.note and "example.org" in st.note


@pytest.mark.parametrize("bad,why", [
    ({"id": "X!", "tools": []}, "id must be"),
    ({"id": "ok-id"}, "doesn't add anything"),
    ({"id": "ok-id", "tools": [{"id": "t", "accepts": [".png"], "program": "p", "args": ["{input}"]}]}, "tool id"),
    ({"id": "ok-id", "tools": [{"id": "tt", "accepts": [".png"], "program": "p", "args": ["{rm -rf}"]}]}, "placeholder"),
    ({"id": "ok-id", "tools": [{"id": "tt", "accepts": [], "program": "p", "args": []}]}, "accepts"),
    ({"id": "ok-id", "tools": [{"id": "tt", "accepts": [".png"], "program": "p", "args": [], "output": "../x"}]}, "plain file"),
    ({"id": "ok-id", "packs": ["../../evil.txt"]}, "inside the add-on"),
])
def test_bad_addons_refused(tmp_path, bad, why):
    (tmp_path / "addon.json").write_text(json.dumps(bad))
    with pytest.raises(community.AddonError, match=why):
        community.read(tmp_path)


def test_unsafe_zips_refused(app):  # noqa: F811
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("addon.json", json.dumps({"id": "evil", "packs": ["p.txt"]}))
        z.writestr("../../escape.txt", "x")
    r = community.install_zip(app.sb, buf.getvalue())
    assert not r["ok"] and "outside" in r["error"]
    assert not community.install_zip(app.sb, b"not a zip")["ok"]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("readme.txt", "hi")
    assert "addon.json" in community.install_zip(app.sb, buf.getvalue())["error"]


def test_bad_workflow_blocks_turning_on(app, clean, tmp_path):  # noqa: F811
    folder = tmp_path / "w"
    (folder / "wf").mkdir(parents=True)
    (folder / "wf" / "broken.json").write_text('{"not": "a workflow"}')
    (folder / "addon.json").write_text(json.dumps({"id": "bad-wf", "workflows": ["wf/broken.json"]}))
    community.install_zip(app.sb, _zip(folder))
    r = community.enable(app.sb, "bad-wf", True)
    assert not r["ok"] and "check" in r["error"]
    assert community.remove(app.sb, "bad-wf")["ok"] and not (community.root(app.sb) / "bad-wf").exists()


def test_command_line_placeholders(tmp_path):
    tool = {"program": "prog", "args": ["-i", "{input}", "{flag:hq:--quality high}", "--size", "{option:size}", "{output}"],
            "output": "{stem}-{option:size}.{ext}"}
    cmd = community.command_line(tool, Path("prog"), tmp_path / "in" / "cat.png", tmp_path / "out", {"hq"}, {"size": "800"}, "")
    assert cmd[1:] == ["-i", str(tmp_path / "in" / "cat.png"), "--quality", "high", "--size", "800",
                       str(tmp_path / "out" / "cat-800.png")]
    cmd = community.command_line(tool, Path("prog"), tmp_path / "cat.png", tmp_path, set(), {"size": "800"}, "")
    assert "--quality" not in cmd
    shutil.rmtree(tmp_path, ignore_errors=True)
