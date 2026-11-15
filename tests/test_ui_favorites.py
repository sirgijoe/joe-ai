"""UI reorganization step 6: starred tools are saved as ui.favorite_tools (a short list of tool ids)."""
from pathlib import Path

from joeai.config import Settings, clean_favorites, reset_paths


def test_default_is_empty_and_nothing_else_changed():
    s = Settings()
    assert s.ui.favorite_tools == []
    assert s.ui.check_updates is True and s.ui.language == "en" and s.ui.intro is True     # defaults untouched


def test_favorites_survive_a_save_and_load(tmp_path):
    p = tmp_path / "s.json"
    s = Settings()
    s.ui.favorite_tools = ["translate", "proofread"]
    s.save(p)
    assert Settings.load(p).ui.favorite_tools == ["translate", "proofread"]


def test_junk_is_dropped_repeats_and_a_runaway_list():
    s = Settings()
    s.ui.favorite_tools = ["a", "a", 7, None, "", "b" * 65, {"x": 1}, "c"] + [f"t{i}" for i in range(300)]
    clean_favorites(s)
    assert s.ui.favorite_tools[:3] == ["a", "c", "t0"] and len(s.ui.favorite_tools) == 100
    assert all(isinstance(x, str) for x in s.ui.favorite_tools)


def test_an_old_settings_file_without_the_key_loads(tmp_path):
    p = tmp_path / "s.json"
    p.write_text('{"ui": {"crt": 1}}', encoding="utf-8")
    s = Settings.load(p)
    assert s.ui.crt == 1 and s.ui.favorite_tools == []


def test_the_page_has_stars_and_the_rows():
    js = (Path(__file__).parent.parent / "joeai" / "ui" / "app.js").read_text(encoding="utf-8")
    assert "toolFavToggle" in js and "favorite_tools" in js and "Click the star on a tool to keep it here." in js


def test_start_over_keeps_the_starred_tools():
    s = Settings()
    s.ui.favorite_tools = ["translate"]
    s.ui.crt = 3
    reset_paths(s, None)                              # START OVER: RESET ALL SETTINGS
    assert s.ui.favorite_tools == ["translate"] and s.ui.crt == Settings().ui.crt


def test_starring_a_tool_leaves_a_waiting_daily_restart_alone(tmp_path, monkeypatch):
    from joeai.server import App
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "settings.json"))
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    s.ollama.url = s.comfy.url = "http://127.0.0.1:9"
    s.save()
    app = App(settings=s)
    app.daily.waiting, due = "a run is going", app.daily.due
    assert app.save_settings({"ui": {"favorite_tools": ["translate", "translate", 5]}})["ok"]
    assert app.settings.ui.favorite_tools == ["translate"]
    assert app.daily.waiting == "a run is going" and app.daily.due == due
    assert app.save_settings({"engine": {"restart_time": "04:30"}})["ok"]       # a new time does count from now
    assert app.daily.waiting == ""
