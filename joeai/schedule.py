"""Night shift: plans saved "for tonight" start at a set time, even with Joe's window closed.

Setup > General > Night shift turns it on. Joe asks the computer's own scheduler to start him
at that time (Windows Task Scheduler, launchd on a Mac, cron on Linux); turning it off removes
that entry again. Nothing of Joe's keeps running in the meantime.

At the set time `python -m joeai tonight` moves Missions/Tonight/* into Missions/Queue. If Joe's
window is open he runs them as usual; if not, Joe starts without a window, works through the
queue (keep-awake, "when finished" and phone pings all apply) and closes when it's done.
Opening Joe during a night run shows the run in progress.
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
    s = Settings.load()
    sb = Sandbox(s.workspace_path).ensure()
    moved = move_tonight(sb)
    waiting = [p for p in (sb.missions / "Queue").glob("*.txt")]
    if not moved and not waiting:
        return 0                                        # nothing saved for tonight
    if _existing_url():                                 # Joe's window is open: he picks them up
        return 0
    os.environ["JOE_NO_WINDOW"] = "1"                   # no window at night; closes when done
    return app_main()
