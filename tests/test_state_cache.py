"""The window asks for /api/state every second or so: the missions on hold and a custom theme are
read from disk only when their folder changed. Also: crash.log keeps the last five crashes."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from joeai import app as app_mod
from joeai import server, themes

from test_core import env  # noqa: F401

MISSION = "TASK: {job}  SAVE: {name}.md  CHUNKS: 1 x 1"


def _count_reads(monkeypatch, folder: Path) -> list[str]:
    seen: list[str] = []
    real = Path.read_text

    def counting(self, *a, **k):
        if self.parent == folder:
            seen.append(self.name)
        return real(self, *a, **k)
    monkeypatch.setattr(Path, "read_text", counting)
    return seen


def _bump(p: Path):
    st = p.stat()
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))


def test_held_missions_read_once_until_the_folder_changes(env, monkeypatch):  # noqa: F811
    s, _, _ = env
    a = server.App(s)
    hold = a.hold_dir()
    hold.mkdir(parents=True, exist_ok=True)
    (hold / "01.md").write_text(MISSION.format(name="one", job="First"), encoding="utf-8")
    (hold / "02.md").write_text(MISSION.format(name="two", job="Second"), encoding="utf-8")
    seen = _count_reads(monkeypatch, hold)
    first = a.held_missions()
    assert [h["file"] for h in first] == ["01.md", "02.md"]
    assert a.held_missions() == first
    assert sorted(seen) == ["01.md", "02.md"]                   # each file read once for two calls
    (hold / "02.md").write_text(MISSION.format(name="two", job="Changed"), encoding="utf-8")
    _bump(hold / "02.md")
    again = a.held_missions()
    assert "Changed" in again[1]["label"] and "Changed" not in first[1]["label"]
    assert seen.count("01.md") == 2                              # the folder changed: read again
    (hold / "01.md").unlink()
    assert [h["file"] for h in a.held_missions()] == ["02.md"]


def test_theme_vars_reused_until_the_theme_file_changes(env, monkeypatch):  # noqa: F811
    s, sb, _ = env
    a = server.App(s)
    sid = themes.save(sb.themes, {"name": "Clay", "bg": "#101010", "fg": "#e0c090", "accent": "#ff8040"})
    s.ui.phosphor = "custom:" + sid
    seen = _count_reads(monkeypatch, sb.themes)
    v1 = a.theme_vars()
    assert v1 and a.theme_vars() == v1
    assert seen.count(sid + ".json") == 1
    p = sb.themes / (sid + ".json")
    t = json.loads(p.read_text(encoding="utf-8"))
    t["bg"] = "#202020"
    p.write_text(json.dumps(t), encoding="utf-8")
    _bump(p)
    v2 = a.theme_vars()
    assert v2 != v1
    s.ui.phosphor = "green"
    assert a.theme_vars() is None


@pytest.fixture
def crashy(tmp_path, monkeypatch):
    monkeypatch.setattr(app_mod, "config_dir", lambda: tmp_path / "cfg")
    n = {"i": 0}

    def boom():
        n["i"] += 1
        raise RuntimeError(f"crash number {n['i']}")
    monkeypatch.setattr(app_mod, "main", boom)
    return tmp_path / "cfg" / "crash.log"


def test_crash_log_keeps_the_last_five(crashy):
    for _ in range(6):
        with pytest.raises(RuntimeError):
            app_mod.run_logged()
    txt = crashy.read_text(encoding="utf-8")
    heads = [ln for ln in txt.splitlines() if ln.startswith("=== ") and ln.endswith(" ===")]
    assert len(heads) == 5
    assert "RuntimeError: crash number 1\n" not in txt
    nums = [int(n) for n in re.findall(r"RuntimeError: crash number (\d+)", txt)]
    assert nums == [2, 3, 4, 5, 6]                                  # newest last


def test_crash_log_from_before_is_kept_as_one_entry(crashy):
    crashy.parent.mkdir(parents=True)
    crashy.write_text("Traceback (most recent call last):\nold crash\n", encoding="utf-8")
    with pytest.raises(RuntimeError):
        app_mod.run_logged()
    txt = crashy.read_text(encoding="utf-8")
    assert txt.index("old crash") < txt.index("crash number 1")
