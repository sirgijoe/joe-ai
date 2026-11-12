"""Daily restart (2.3, Setup > General), for a Joe that is left running.

Joseph, 2026-11-11: "We recommend a restart daily. What time would you like that to happen? It could
take a few minutes. Leaving this blank restarts at 6am." Joe closes and opens again (the same thing
RESTART JOE does), which frees memory, the graphics card and the voice programs.

The rules:
  - Never in the middle of a job. If a run (the night shift, an agent, a queued mission), a plan
    being written, a download or an install is going at that time, Joe waits and restarts right
    after it finishes, however late that is. (Not at an agent's checkpoint: a checkpoint lives in
    that run's memory, so stopping there would lose the run. Finishing first is the safe choice.)
  - What waits is kept: the queue only exists while a run is going (so it has emptied by then),
    missions ON HOLD and in Missions/Queue are files, and the night shift is started by the
    computer's own scheduler, so all of them carry on after the restart.
  - A PC that was off at that time does nothing extra: starting Joe is already a fresh start. The
    next restart is always the next time after this Joe started.
  - A PC that was asleep at that time (Joe open, nothing running) doesn't restart the moment it
    wakes up more than LATE_MIN minutes late: the person is probably back at it. It waits for the
    next day's time.
  - Times typed like "6am" get the usual "you said ..., Joe changed it to 06:00" yes/no box
    (schedule.TIME_FIELDS).
"""
from __future__ import annotations

from datetime import datetime, timedelta

DEFAULT = "06:00"
LATE_MIN = 60


def at(settings) -> tuple[int, int]:
    from .schedule import parse_time
    return parse_time((getattr(settings.engine, "restart_time", "") or "").strip()) or parse_time(DEFAULT)


def next_due(settings, after: datetime) -> datetime:
    h, m = at(settings)
    due = after.replace(hour=h, minute=m, second=0, microsecond=0)
    return due if due > after else due + timedelta(days=1)


def busy(app) -> str:
    """What's going that a restart must wait for ('' = nothing)."""
    if app.running:
        return "a run is going"
    if getattr(app, "queue", None):
        return "missions are waiting in line"
    if getattr(app, "_starting", None):
        return "a run is starting"
    hp = getattr(app, "held_plan", None) or {}
    if hp.get("status") == "waiting":
        return "a plan is being written"
    try:
        if app.background_work():
            return "a download or install is going"
    except Exception:                           # noqa: BLE001
        pass
    return ""


class DailyRestart:
    def __init__(self, settings, now: datetime | None = None):
        self.reset(settings, now)

    def reset(self, settings, now: datetime | None = None) -> None:
        """At start, and after Setup is saved: the next time after now."""
        self.due = next_due(settings, now or datetime.now())
        self.waiting = ""

    def tick(self, app, now: datetime | None = None, do_restart=None) -> str:
        """Called every few seconds. Returns what happened: '', 'off', 'wait', 'skip' or 'restart'."""
        now = now or datetime.now()
        s = app.settings
        if not getattr(s.engine, "daily_restart", True):
            return "off"
        if now < self.due:
            return ""
        why = busy(app)
        if why:
            if not self.waiting:
                app.log(f"Daily restart ({self.due:%H:%M}): waiting, {why}. Joe restarts right after it's done.")
            self.waiting = why
            return "wait"
        if not self.waiting and now - self.due > timedelta(minutes=LATE_MIN):
            app.log(f"Daily restart: the PC was asleep at {self.due:%H:%M}, so Joe didn't restart now; "
                    "the next one is tomorrow.")
            self.reset(s, now)
            return "skip"
        app.log("Daily restart (Setup > General): Joe is closing and opening again to free memory, the "
                "graphics card and the voice programs. Back in a few minutes.")
        if do_restart is None:
            from .app import restart as do_restart
        if not do_restart(app.log):
            self.reset(s, now)                     # couldn't start a new Joe: try again tomorrow
            return "skip"
        app.restart_hint = ""
        app.last_seen = 0.0
        app.quit_now = True
        return "restart"
