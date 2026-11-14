"""Household profiles (profiles.py): one Joe per person on a shared PC, each with their own settings, keys,
workspace and night shift. A PC with no profiles behaves exactly as before."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from joeai import cli, profiles, schedule, system


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    monkeypatch.delenv("JOE_CONFIG", raising=False)
    monkeypatch.delenv(profiles.ENV, raising=False)
    (tmp_path / "Documents").mkdir()
    monkeypatch.setattr(system, "documents_dir", lambda: tmp_path / "Documents")
    from joeai import portable
    portable.forget()
    monkeypatch.setattr(portable, "active", lambda: False)
    return tmp_path


def test_names_become_safe_ids():
    assert profiles.slug("Sam R.") == "sam-r" and profiles.slug("  Sam  ") == "sam"
    assert profiles.slug("../../etc") == "etc" and profiles.slug("a/b\\c") == "a-b-c"
    assert profiles.slug("") == "" and len(profiles.slug("x" * 100)) <= 40


def test_no_profiles_means_nothing_changes(home):
    assert profiles.people() == [] and profiles.current() == ""
    assert system.config_dir() == system.base_config_dir()
    assert system.default_workspace() == home / "Documents" / "Joe-ai"
    assert profiles.command_args() == []
    assert profiles.pick_for_launch(lambda o, last: pytest.fail("asked with nobody to choose")) == ""
    assert not profiles.chosen()


def test_add_and_remove_profiles(home):
    r = profiles.add("Sam R.")
    assert r["ok"] and r["id"] == "sam-r" and Path(r["folder"]).is_dir()
    assert r["workspace"] == str(home / "Documents" / "Joe-ai - Sam R.")
    assert profiles.people() == [{"id": "sam-r", "name": "Sam R."}]
    assert not profiles.add("sam r")["ok"] and not profiles.add("Main")["ok"] and not profiles.add("  ")["ok"]
    for i in range(profiles.MAX_PROFILES):
        profiles.add(f"Person {i}")
    assert "most Joe keeps" in profiles.add("One more")["error"]
    kept = profiles.profile_dir("sam-r")
    (kept / "settings.json").write_text("{}", encoding="utf-8")
    r = profiles.remove("Sam R.")
    assert r["ok"] and all(p["id"] != "sam-r" for p in profiles.people())
    assert (kept / "settings.json").exists()                  # taking someone off the list deletes nothing
    assert not profiles.remove("nobody")["ok"]
    assert profiles.add("Sam R.")["ok"]                       # the same name brings their folder back


def test_a_profile_gets_its_own_settings_workspace_and_lock(home, monkeypatch):
    profiles.add("Alex")
    profiles.add("Sam")
    base = system.config_dir()
    monkeypatch.setenv(profiles.ENV, "alex")
    assert system.config_dir() == base / "profiles" / "alex" and system.config_dir() != base
    assert system.default_workspace() == home / "Documents" / "Joe-ai - Alex"
    from joeai import app, config
    assert app._lock_path() == base / "profiles" / "alex" / "app.json"     # no more shared lock file or port
    assert config.config_path() == base / "profiles" / "alex" / "settings.json"
    monkeypatch.setenv(profiles.ENV, "sam")
    assert config.config_path().parent.name == "sam" and app._lock_path() != base / "profiles" / "alex" / "app.json"
    monkeypatch.setenv(profiles.ENV, "main")
    assert system.config_dir() == base and system.default_workspace() == home / "Documents" / "Joe-ai"
    monkeypatch.setenv("JOE_CONFIG", str(home / "x.json"))
    assert config.config_path() == home / "x.json"            # the tests' override still wins


def test_profile_argument_is_taken_off_the_command_line(home):
    assert profiles.take_arg(["--profile", "Sam", "tonight"]) == ["tonight"] and profiles.current() == "sam"
    assert profiles.take_arg(["--profile=main", "status"]) == ["status"] and profiles.current() == "" and profiles.chosen()
    assert profiles.take_arg(["mcp"]) == ["mcp"]
    assert profiles.take_arg(["status", "--profile"]) == ["status", "--profile"]       # no name: left alone


def test_who_is_using_joe_asks_once_and_remembers(home):
    profiles.add("Alex")
    seen = []

    def chooser(options, last):
        seen.append(([o["id"] for o in options], last))
        return "alex"
    assert profiles.pick_for_launch(chooser) == "alex"
    assert seen == [(["main", "alex"], "main")] and os.environ[profiles.ENV] == "alex"
    assert profiles.last() == "alex"
    assert profiles.pick_for_launch(lambda o, l: pytest.fail("asked twice")) == "alex"     # already chosen
    del os.environ[profiles.ENV]
    seen.clear()
    assert profiles.pick_for_launch(lambda o, last: (seen.append(last), "main")[1]) == "" and seen == ["alex"]
    del os.environ[profiles.ENV]

    def broken(options, last):
        raise RuntimeError("no window system")
    assert profiles.pick_for_launch(broken) == "" and profiles.last() == "main"       # carries on with who was last
    del os.environ[profiles.ENV]


def test_the_night_shift_and_restart_start_the_same_persons_joe(home, monkeypatch):
    profiles.add("Alex")
    monkeypatch.delenv("APPIMAGE", raising=False)
    cmd = system.joe_command("tonight", console=False)
    assert cmd[-3:] == ["--profile", "main", "tonight"]            # Main is named on purpose: the night shift never asks
    monkeypatch.setenv(profiles.ENV, "alex")
    cmd = system.joe_command("restart", console=False)
    assert cmd[cmd.index("--profile") + 1] == "alex" and cmd[-1] == "restart"


def test_each_profile_has_its_own_night_shift_entry(home, monkeypatch):
    assert schedule.task_name() == "Joe night shift" and schedule.label().endswith(".tonight")
    monkeypatch.setenv(profiles.ENV, "alex")
    assert schedule.task_name() == "Joe night shift (alex)" and schedule.label().endswith(".tonight.alex")
    alex = schedule.cron_lines("", 23, 0, ["joe", "tonight"])
    monkeypatch.setenv(profiles.ENV, "main")
    both = schedule.cron_lines(alex, 22, 30, ["joe", "tonight"])
    assert both.count("tonight") == 2 and "30 22" in both and "0 23" in both       # main added beside alex's
    left = schedule.cron_lines(both)                          # main's line removed, alex's stays
    assert "night shift (alex)" in left and "30 22" not in left
    monkeypatch.setenv(profiles.ENV, "alex")
    assert "(alex)" not in schedule.cron_lines(both) and "30 22" in schedule.cron_lines(both)


def test_profile_command_line(home, capsys):
    assert cli.main(["profile", "add", "Sam"]) == 0
    assert "Made the profile Sam" in capsys.readouterr().out
    assert cli.main(["profile", "add", "Sam"]) == 2
    assert cli.main(["profile", "list"]) == 0 and "Sam" in capsys.readouterr().out
    assert cli.main(["profile", "remove", "Sam"]) == 0 and "were not deleted" in capsys.readouterr().out
    assert cli.main(["profile", "list"]) == 0 and "No household profiles" in capsys.readouterr().out


def test_profiles_are_off_in_portable_joe(home, monkeypatch):
    from joeai import portable
    monkeypatch.setattr(portable, "active", lambda: True)
    assert not profiles.add("Sam")["ok"] and profiles.current() == "" and profiles.command_args() == []
    monkeypatch.setenv(profiles.ENV, "sam")
    assert profiles.current() == ""


def test_setup_summary_and_opening_another_persons_joe(home, monkeypatch):
    profiles.add("Alex")
    s = profiles.summary()
    assert s["enabled"] and s["me"] == "main" and [p["id"] for p in s["people"]] == ["main", "alex"]
    assert s["people"][0]["me"] and not s["people"][1]["me"]
    launched = []
    monkeypatch.setattr(system, "popen_detached", lambda cmd, *a, **k: launched.append(cmd))
    assert profiles.open_window_for("alex")["ok"]
    assert launched[0][-2:] == ["--profile", "alex"] and launched[0][-1] != ""        # no empty "sub" argument
    assert not profiles.open_window_for("nobody")["ok"] and not profiles.open_window_for("main")["ok"]
    monkeypatch.setenv(profiles.ENV, "alex")
    assert profiles.summary()["name"] == "Alex" and profiles.open_window_for("main")["ok"]
    assert launched[-1][-2:] == ["--profile", "main"]
