"""2.3 stage 5: the daily restart (Setup > General). One test per rule in dailyrestart.py."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from joeai import dailyrestart as dr, schedule
from joeai.config import Settings


class FakeApp:
    def __init__(self, time_=""):
        self.settings = Settings()
        self.settings.engine.restart_time = time_
        self.running, self.queue, self._starting, self.held_plan = False, [], None, {}
        self.bg = False
        self.logs, self.quit_now, self.last_seen, self.restart_hint = [], False, 99.0, "x"

    def background_work(self):
        return self.bg

    def log(self, m):
        self.logs.append(m)


def _restarts():
    calls = []
    return calls, (lambda log: calls.append(1) or True)


def test_blank_means_six_in_the_morning_and_counts_from_when_joe_started():
    app = FakeApp("")
    d = dr.DailyRestart(app.settings, datetime(2026, 11, 12, 5, 0))
    assert d.due == datetime(2026, 11, 12, 6, 0)
    d = dr.DailyRestart(app.settings, datetime(2026, 11, 12, 6, 0, 30))     # just restarted at 06:00
    assert d.due == datetime(2026, 11, 13, 6, 0)                            # not again today: no loop
    app.settings.engine.restart_time = "04:30"
    assert dr.DailyRestart(app.settings, datetime(2026, 11, 12, 9, 0)).due == datetime(2026, 11, 13, 4, 30)


def test_it_restarts_at_the_time_when_nothing_is_going():
    app = FakeApp("06:00")
    d = dr.DailyRestart(app.settings, datetime(2026, 11, 12, 1, 0))
    calls, fn = _restarts()
    assert d.tick(app, datetime(2026, 11, 12, 5, 59), fn) == ""
    assert d.tick(app, datetime(2026, 11, 12, 6, 0, 5), fn) == "restart"
    assert calls and app.quit_now and app.last_seen == 0.0 and "free memory" in app.logs[-1]


def test_never_in_the_middle_of_a_job_then_right_after_it_however_late():
    app = FakeApp("06:00")
    d = dr.DailyRestart(app.settings, datetime(2026, 11, 12, 1, 0))
    calls, fn = _restarts()
    for what in ("running", "queue", "_starting", "held_plan", "bg"):
        a = FakeApp("06:00")
        setattr(a, what, {"running": True, "queue": [("t", None, {})], "_starting": "x",
                          "held_plan": {"status": "waiting"}, "bg": True}[what])
        assert dr.busy(a), what
    app.running = True                          # the night shift runs past 6
    assert d.tick(app, datetime(2026, 11, 12, 6, 0, 5), fn) == "wait"
    assert d.tick(app, datetime(2026, 11, 12, 7, 0), fn) == "wait" and not calls
    assert sum("waiting" in m for m in app.logs) == 1                       # said once, not every tick
    app.running = False                         # done at 08:40: restart now, even though that's late
    assert d.tick(app, datetime(2026, 11, 12, 8, 40), fn) == "restart" and calls


def test_a_pc_that_slept_through_it_waits_for_tomorrow():
    app = FakeApp("06:00")
    d = dr.DailyRestart(app.settings, datetime(2026, 11, 12, 1, 0))
    calls, fn = _restarts()
    assert d.tick(app, datetime(2026, 11, 12, 9, 15), fn) == "skip" and not calls
    assert d.due == datetime(2026, 11, 13, 6, 0) and "asleep" in app.logs[-1]
    assert d.tick(app, datetime(2026, 11, 12, 6 + dr.LATE_MIN // 60 + 4, 0), fn) == ""


def test_it_can_be_turned_off():
    app = FakeApp("06:00")
    app.settings.engine.daily_restart = False
    d = dr.DailyRestart(app.settings, datetime(2026, 11, 12, 1, 0))
    calls, fn = _restarts()
    assert d.tick(app, datetime(2026, 11, 12, 6, 1), fn) == "off" and not calls


def test_a_failed_restart_tries_again_tomorrow_and_joe_keeps_running():
    app = FakeApp("06:00")
    d = dr.DailyRestart(app.settings, datetime(2026, 11, 12, 1, 0))
    assert d.tick(app, datetime(2026, 11, 12, 6, 1), lambda log: False) == "skip"
    assert not app.quit_now and d.due == datetime(2026, 11, 13, 6, 0)


def test_6am_typed_gets_the_yes_no_box():
    r = schedule.check_times({"engine": {"restart_time": "6am"}})
    assert r["fixes"] == [{"path": "engine.restart_time", "label": "Daily restart", "said": "6am", "fixed": "06:00"}]
    assert schedule.check_times({"engine": {"restart_time": ""}}) == {}
    assert "error" in schedule.check_times({"engine": {"restart_time": "teatime"}})


def test_setup_general_has_it_in_josephs_words():
    html = (Path(dr.__file__).parent / "ui" / "index.html").read_text(encoding="utf-8")
    assert 'data-path="engine.restart_time"' in html and 'data-path="engine.daily_restart"' in html
    assert "We recommend a restart daily. What time would you like that to happen?" in html
    assert "It could take a few minutes. Leaving this blank restarts at 6am." in html
    assert Settings().engine.daily_restart is True and Settings().engine.restart_time == ""


def test_the_app_checks_it_and_saving_setup_counts_from_now(tmp_path, monkeypatch):
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "cfg" / "settings.json"))
    (tmp_path / "cfg").mkdir()
    from joeai.server import App
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    app = App(settings=s)
    assert isinstance(app.daily, dr.DailyRestart) and app.daily_restart_tick() in ("", "off")
    old = app.daily.due
    r = app.save_settings({"engine": {"restart_time": "03:15"}})
    assert r.get("ok", True) and app.daily.due != old and (app.daily.due.hour, app.daily.due.minute) == (3, 15)
    _ = SimpleNamespace
