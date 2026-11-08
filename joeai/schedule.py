"""Night shift: plans saved "for tonight" start at a set time, even with Joe's window closed.

Setup > General > Night shift turns it on. Joe asks the computer's own scheduler to start him
at that time (Windows Task Scheduler, launchd on a Mac, cron on Linux); turning it off removes
that entry again. Nothing of Joe's keeps running in the meantime.

At the set time `python -m joeai tonight` moves Missions/Tonight/* into Missions/Queue. If Joe's
window is open he runs them as usual; if not, Joe starts without a window, works through the
queue (keep-awake, "when finished" and phone pings all apply) and closes when it's done.
Opening Joe during a night run shows the run in progress.

"Stop by" (optional): at that time Joe finishes the mission he's on, puts everything not yet
started back in Missions/Tonight for the next night and says so in the morning report. A stop
time earlier than the start time means the next morning (start 23:00, stop 06:00). If the
scheduler starts Joe outside that window (the PC was asleep or off), he leaves the plans for the
next night instead of running into the day.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from .system import LINUX, MAC, WINDOWS, no_window_flags

TASK_NAME = "Joe night shift"
LABEL = "io.github.sirgijoe.joe.tonight"
CRON_TAG = "# joe-ai night shift"
_TIME = re.compile(r"^\s*([01]?\d|2[0-3]):([0-5]\d)\s*$")


def parse_time(text: str) -> tuple[int, int] | None:
    m = _TIME.match(text or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


_LOOSE = re.compile(r"^\s*(\d{1,2})(?:\s*[:.h]\s*(\d{2}))?\s*(a\.?\s*m\.?|p\.?\s*m\.?|am|pm|a|p)?\s*$", re.I)


def loose_time(text: str) -> str | None:
    """A time typed any everyday way -> the 24-hour 'HH:MM' Joe needs, or None if it can't tell.
    '7am' -> 07:00, '7:30 pm' -> 19:30, '0700' -> 07:00, '19.30' -> 19:30, 'noon', 'midnight'."""
    t = (text or "").strip().lower()
    if not t:
        return None
    if t in ("noon", "midday", "12 noon"):
        return "12:00"
    if t in ("midnight", "12 midnight"):
        return "00:00"
    m = re.match(r"^(\d{3,4})$", t)                          # 0700, 700, 2330
    if m:
        t = f"{m.group(1)[:-2]}:{m.group(1)[-2:]}"
    m = _LOOSE.match(t)
    if not m:
        return None
    h, mins, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").replace(".", "").replace(" ", "")
    if mins > 59:
        return None
    if ap:
        if not 1 <= h <= 12:
            return None
        h = (0 if h == 12 else h) + (12 if ap.startswith("p") else 0)
    elif h > 23:
        return None
    return f"{h:02d}:{mins:02d}"


TIME_FIELDS = {"schedule.time": "Night shift start", "schedule.stop": "Stop by",
               "comfort.quiet_start": "Quiet hours from", "comfort.quiet_end": "Quiet hours until"}


def check_times(data: dict) -> dict:
    """Setup's time boxes before saving. Returns {} (all fine), {"fixes": [...]} (Joe can tell what
    was meant: ask the person to confirm), or {"error": ...} (he can't)."""
    fixes = []
    for path, label in TIME_FIELDS.items():
        a, _, b = path.partition(".")
        v = (data.get(a) or {}).get(b) if isinstance(data.get(a), dict) else None
        if not isinstance(v, str) or not v.strip():
            continue
        good = parse_time(v)
        fixed = f"{good[0]:02d}:{good[1]:02d}" if good else loose_time(v)
        if fixed is None:
            return {"error": f"{label}: Joe couldn't tell what time \"{v.strip()}\" means. Use the 24-hour "
                             "clock, like 07:00 or 23:30."}
        if fixed != v.strip():
            fixes.append({"path": path, "label": label, "said": v.strip(), "fixed": fixed})
    return {"fixes": fixes} if fixes else {}


STOP_FILE = "night_stop.json"


def stop_deadline(start: str, stop: str, now):
    """When tonight's run must stop taking new missions, or None (no stop time). A time at or
    before `now` means "already past": don't start anything."""
    from datetime import timedelta
    st = parse_time(stop)
    if not st:
        return None
    sa = parse_time(start)
    stop_at = now.replace(hour=st[0], minute=st[1], second=0, microsecond=0)
    if not sa:                                      # no start time: the next stop time
        return stop_at if stop_at > now else stop_at + timedelta(days=1)
    if sa == st:
        return None
    start_at = now.replace(hour=sa[0], minute=sa[1], second=0, microsecond=0)
    if sa < st:                                     # same day (01:00 -> 06:00)
        return stop_at if start_at <= now < stop_at else now
    if now >= start_at:                             # past midnight (23:00 -> 06:00), evening side
        return stop_at + timedelta(days=1)
    return stop_at if now < stop_at else now        # morning side, or outside the window


def read_stop(sb):
    """The stop time the night shift left for this run, or None (none set, or stale)."""
    import json
    from datetime import datetime, timedelta
    try:
        until = datetime.fromisoformat(json.loads((sb.meta / STOP_FILE).read_text(encoding="utf-8"))["until"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return until if datetime.now() - until < timedelta(hours=20) else None


def clear_stop(sb) -> None:
    try:
        (sb.meta / STOP_FILE).unlink()
    except OSError:
        pass


def put_back(sb, texts: list[tuple[str, str]]) -> list[str]:
    """Missions not started before the stop time -> Missions/Tonight, for the next night."""
    import re as _re
    dst = sb.missions / "Tonight"
    dst.mkdir(parents=True, exist_ok=True)
    out = []
    for label, text in texts:
        stem = _re.sub(r"[^\w-]+", "-", label.lower()).strip("-")[:40] or "plan"
        target, n = dst / f"{stem}.txt", 2
        while target.exists():
            target = dst / f"{stem}_{n}.txt"
            n += 1
        try:
            target.write_text(text, encoding="utf-8")
            out.append(target.name)
        except OSError:
            continue
    return out


def windows_commands(hh: int, mm: int, cmd: list[str]) -> list[list[str]]:
    tr = " ".join(f'"{c}"' if " " in c or "\\" in c else c for c in cmd)
    return [["schtasks", "/Create", "/F", "/TN", TASK_NAME, "/SC", "DAILY", "/ST", f"{hh:02d}:{mm:02d}",
             "/TR", tr]]


def windows_xml(hh: int, mm: int, cmd: list[str], start_date: str = "2026-01-01") -> str:
    """Task Scheduler entry that also WAKES the PC from sleep at that time (Windows only; the
    power plan's "Allow wake timers" must be on, which it is by default on most PCs)."""
    from xml.sax.saxutils import escape
    exe, args = cmd[0], " ".join(f'"{c}"' if " " in c or "\\" in c else c for c in cmd[1:])
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Joe's night shift: starts the plans saved for tonight (Setup &gt; General).</Description></RegistrationInfo>
  <Triggers><CalendarTrigger><StartBoundary>{start_date}T{hh:02d}:{mm:02d}:00</StartBoundary><Enabled>true</Enabled>
    <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay></CalendarTrigger></Triggers>
  <Principals><Principal id="Author"><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <WakeToRun>true</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author"><Exec><Command>{escape(exe)}</Command><Arguments>{escape(args)}</Arguments></Exec></Actions>
</Task>
"""


def mac_plist(hh: int, mm: int, cmd: list[str]) -> str:
    esc = lambda t: t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731
    args = "".join(f"<string>{esc(c)}</string>" for c in cmd)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{LABEL}</string>
  <key>ProgramArguments</key><array>{args}</array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>{hh}</integer><key>Minute</key><integer>{mm}</integer></dict>
</dict></plist>
"""


def mac_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def cron_lines(current: str, hh: int | None = None, mm: int | None = None,
               cmd: list[str] | None = None) -> str:
    """The crontab with Joe's line removed, then added back when a time is given."""
    import shlex
    keep = [ln for ln in current.splitlines() if CRON_TAG not in ln]
    if hh is not None:
        keep.append(f"{mm} {hh} * * * {' '.join(shlex.quote(c) for c in cmd or [])} {CRON_TAG}")
    return "\n".join(keep).strip() + "\n" if keep else ""


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
                          creationflags=no_window_flags(), **kw)


def apply(settings, log=lambda *_: None) -> dict:
    """Make the computer's scheduler match Setup: add/update the entry, or remove it."""
    sc = settings.schedule
    from . import portable
    if portable.active():                  # never touch this computer's scheduler (or its Joe's task)
        if not sc.enabled:
            return {"ok": True}
        return {"ok": False, "error": "Night shift isn't available while Joe runs from a drive: it would "
                                      "leave a task in this computer's scheduler. Press RUN before bed instead."}
    if not sc.enabled:
        return remove(log)
    t = parse_time(sc.time)
    if not t:
        return {"ok": False, "error": "Night shift time should look like 23:00 (24-hour clock)."}
    hh, mm = t
    if (sc.stop or "").strip() and not parse_time(sc.stop):
        return {"ok": False, "error": "Stop time should look like 07:00 (24-hour clock), or leave it blank."}
    from .system import joe_command
    joe = joe_command("tonight", console=False)
    try:
        if WINDOWS:
            from datetime import date
            from .config import config_path
            xml = config_path().parent / "joe-night-shift.xml"
            xml.write_text(windows_xml(hh, mm, joe, date.today().isoformat()), encoding="utf-16")
            r = _run(["schtasks", "/Create", "/F", "/TN", TASK_NAME, "/XML", str(xml)])
            if r.returncode:                            # older Windows: plain entry, no wake
                r = _run(windows_commands(hh, mm, joe)[0])
            if r.returncode:
                return {"ok": False, "error": "Windows Task Scheduler said no: "
                                              + (r.stderr or r.stdout).strip()[:300]}
        elif MAC:
            p = mac_plist_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            _run(["launchctl", "unload", str(p)])
            p.write_text(mac_plist(hh, mm, joe), encoding="utf-8")
            r = _run(["launchctl", "load", "-w", str(p)])
            if r.returncode:
                return {"ok": False, "error": "launchctl said no: " + (r.stderr or r.stdout).strip()[:300]}
        else:
            if not shutil.which("crontab"):
                return {"ok": False, "error": "This Linux has no crontab (install the cron package), so "
                                              "the night shift can't be set."}
            cur = _run(["crontab", "-l"])
            r = _run(["crontab", "-"], input=cron_lines(cur.stdout if cur.returncode == 0 else "",
                                                        hh, mm, joe))
            if r.returncode:
                return {"ok": False, "error": "crontab said no: " + (r.stderr or r.stdout).strip()[:300]}
    except (OSError, subprocess.SubprocessError) as e:
        return {"ok": False, "error": f"Couldn't set the night shift: {e}"}
    log(f"Night shift set: Joe starts the plans saved for tonight at {hh:02d}:{mm:02d}.")
    return {"ok": True, "time": f"{hh:02d}:{mm:02d}"}


def remove(log=lambda *_: None) -> dict:
    try:
        if WINDOWS:
            q = _run(["schtasks", "/Query", "/TN", TASK_NAME])
            if q.returncode == 0:
                _run(["schtasks", "/Delete", "/F", "/TN", TASK_NAME])
                log("Night shift off: removed Joe's entry from Task Scheduler.")
        elif MAC:
            p = mac_plist_path()
            if p.exists():
                _run(["launchctl", "unload", "-w", str(p)])
                p.unlink()
                log("Night shift off: removed Joe's launchd entry.")
        elif LINUX and shutil.which("crontab"):
            cur = _run(["crontab", "-l"])
            if cur.returncode == 0 and CRON_TAG in cur.stdout:
                _run(["crontab", "-"], input=cron_lines(cur.stdout))
                log("Night shift off: removed Joe's cron line.")
    except (OSError, subprocess.SubprocessError) as e:
        return {"ok": False, "error": f"Couldn't remove the night shift entry: {e}"}
    return {"ok": True}


def move_tonight(sb) -> list[str]:
    """Missions/Tonight/* -> Missions/Queue (mtime kept, so the queue order stays the same)."""
    src = sb.missions / "Tonight"
    dst = sb.missions / "Queue"
    dst.mkdir(parents=True, exist_ok=True)
    moved = []
    try:
        files = sorted((p for p in src.iterdir() if p.is_file() and p.suffix.lower() in (".txt", ".md")),
                       key=lambda p: p.stat().st_mtime)
    except OSError:
        return []
    for p in files:
        target = dst / p.name
        n = 2
        while target.exists():
            target = dst / f"{p.stem}_{n}{p.suffix}"
            n += 1
        try:
            p.replace(target)
            moved.append(target.name)
        except OSError:
            continue
    return moved


def tonight() -> int:
    """What the scheduler runs. Returns a process exit code."""
    from .app import _existing_url
    from .app import main as app_main
    from .config import Settings
    from .sandbox import Sandbox
    import json
    from datetime import datetime
    s = Settings.load()
    sb = Sandbox(s.workspace_path).ensure()
    now = datetime.now()
    until = stop_deadline(s.schedule.time, s.schedule.stop, now)
    if until is not None and until <= now:              # started too late (PC was off/asleep)
        return 0                                        # the plans wait for the next night
    clear_stop(sb)
    if until is not None:
        sb.meta.mkdir(parents=True, exist_ok=True)
        (sb.meta / STOP_FILE).write_text(json.dumps({"until": until.isoformat(timespec="seconds")}),
                                         encoding="utf-8")
    moved = move_tonight(sb)
    waiting = [p for p in (sb.missions / "Queue").glob("*.txt")]
    if not moved and not waiting:
        return 0                                        # nothing saved for tonight
    if _existing_url():                                 # Joe's window is open: he picks them up
        return 0
    os.environ["JOE_NO_WINDOW"] = "1"                   # no window at night; closes when done
    return app_main()
