"""No test may start a real Joe (conftest._no_real_joe_starts). On 2026-11-27 a full test run crossed
06:00, the daily restart's default time, and about ten real Joe windows opened on Joseph's PC."""
from __future__ import annotations

from datetime import datetime

from joeai import app, dailyrestart as dr, system
from joeai.config import Settings


class _App:
    def __init__(self):
        self.settings = Settings()
        self.running, self.queue, self.logs = False, [], []
        self.quit_now, self.last_seen, self.restart_hint = False, 99.0, "x"

    def log(self, line):
        self.logs.append(line)

    def background_work(self):
        return False


def test_the_daily_restart_time_passing_in_a_test_starts_nothing(monkeypatch):
    started = []
    monkeypatch.setattr(system, "popen_detached", lambda *a, **k: started.append(a))
    a = _App()
    d = dr.DailyRestart(a.settings, datetime(2026, 11, 27, 5, 43))       # a test run that began at 05:43...
    assert d.tick(a, datetime(2026, 11, 27, 6, 0, 5)) == "skip"         # ...and was still going at 06:00
    assert started == [] and a.quit_now is False
    assert d.due == datetime(2026, 11, 28, 6, 0)


def test_restart_joe_starts_nothing_in_a_test(monkeypatch):
    started = []
    monkeypatch.setattr(system, "popen_detached", lambda *a, **k: started.append(a))
    assert app.restart() is False and started == []


def test_a_window_is_never_opened_in_a_test(monkeypatch):
    opened = []
    monkeypatch.setattr(system, "open_window", lambda *a, **k: opened.append(a))
    app.open_window("http://127.0.0.1:1/")
    assert opened == []
