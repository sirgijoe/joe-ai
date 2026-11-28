"""Dev projects (Setup > Other AI apps > Dev tools): a short list, typed by the person in Joe's own
window, of project folders and the commands a connected AI app may ask Joe to run in them.

Why: a cloud chat can reach this PC only through Joe. Without this, every test run, `hua check` or
eval means the person running it in a terminal and pasting the result back (Joseph, 2026-11-27: "I
had to run stuff in the terminal ... because you weren't allowed to control the terminal").

The rules (each one has a test in tests/test_devprojects.py):
  - Off when Joe comes. Nothing here works until the person ticks Setup > Other AI apps > Dev tools.
  - The list changes only through Joe's own window (/api/settings, which needs the window's token).
    The connector, the phone, missions and add-ons have no way to add or change a project or a
    command. An app Joe was started by reads the settings file again on every call, so a change in
    Setup counts at once and nothing an app holds in memory can widen it.
  - A connected app picks a project and a command BY NAME. The command runs exactly as the person
    typed it: the app can add no argument, path, option or environment to it (Joseph chose "nothing
    added", 2026-11-27). A different target is a different command on the list.
  - Never an open command line and never a shell: one program with its arguments. `|`, `>` and `&&`
    are not understood (put those in a script and list the script).
  - It runs in the project's folder, one command at a time on this PC, with a time limit the person
    sets (15 minutes when blank, 4 hours at most). At the limit the program and everything it
    started are ended, and the answer says so. A small minder program (devrun.py) holds the limit and
    the output cap, so they still hold if the AI app, the connector or Joe is closed mid-run.
  - Never in Joe's own folder (or a folder around it or inside it): a connected app can already get
    files written there, so it could change what a listed command does.
  - Bringing a git bundle into a project (joe_repo pull) changes what a listed command will run, so
    it needs its own tick per project in Setup, off when Joe comes, and each pull is written down.
  - A question waits 90 seconds for the run. A longer run keeps going and the answer says STILL
    RUNNING; asking again with the same names waits for it, never starts it twice, and hands the
    result over once.
  - The answer is short: how it ended, how long it took, the totals and the failing lines. The whole
    output is saved in Joe's Output folder (dev/...) where joe_shrink can read it, never sent whole.
  - Every run is written down in Output/dev/_runs.txt (when, project, command, how it ended).
  - Nothing runs unseen ("there will never be anything done on Joe that isn't viewable", the owner,
    2026-11-28): a run or a bundle pull a connected app starts only starts while Joe's window is open
    (the connector opens Joe first, the way Joe normally starts, and refuses with a plain reason if it
    can't), and the window shows it while it happens: project, command, who asked, how long, the last
    lines of output, and a STOP button. STOP (or a chat's joe_stop_command for its own run) ends the
    program and everything it started, not only the program. "Open" means Joe's page has polled him within
    75 seconds (the page's heartbeat), not that he answers; he never opens the person's own browser for it.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from . import devrun

MAX_PROJECTS = 20
MAX_COMMANDS = 20
MAX_RUN_CHARS = 500
MAX_FOLDER_CHARS = 400
DEFAULT_MINUTES = 15
MAX_MINUTES = 240
KEEP_LOGS = 40                      # newest full outputs kept in Output/dev
MAX_LOG_BYTES = 20_000_000          # a runaway program's output is cut here (the program is ended)
TAIL_LINES = 12
MAX_PROBLEM_LINES = 30
LINE_CHARS = 300
RECENT_S = 300                      # Joe's window keeps showing a run that ended this recently
STOP_WAIT_S = 8                     # STOP waits this long for the minder to wind a run up before ending it by force
VIEW_TAIL = 40                      # lines of output Joe's window shows
VIEW_RUNS = 20                      # lines of _runs.txt Joe's window shows
WINDOW_STOP = "the person in Joe's window"
KEEP_RESULT_S = 600                 # a finished run nobody asked about again is forgotten after this
WAIT_S = 90                        # how long one question waits for a run before answering STILL RUNNING
OFF = ('Dev tools are off. The person can turn them on in Joe: Setup > Other AI apps > "Dev tools", '
       "and list the project folders and commands there.")
_NAME = re.compile(r"[^a-z0-9_-]+")
# A line worth showing: a failure, an error, or a totals line (pytest, unittest, cargo, npm, go, hua).
_PROBLEM = re.compile(r"\b(FAILED|FAIL|ERROR|Error|error:|Traceback|panicked|AssertionError|assert(ion)? failed|"
                      r"fatal:|Exception|not ok)\b")
_TOTALS = re.compile(r"\b\d+\s+(passed|failed|errors?|skipped|warnings?|tests?|ok|pass|fail)\b|"
                     r"\b(passed|failed|ok)[:=]\s*\d+|^Ran \d+ tests?|test result:", re.I)


def slug(text) -> str:
    """A name a connected app can say back exactly: small letters, digits, - and _ (32 at most)."""
    return _NAME.sub("-", str(text or "").strip().lower()).strip("-")[:32]


def clean(projects) -> list[dict]:
    """The list as Joe keeps it: known keys only, names made plain, repeats and empty rows dropped."""
    out: list[dict] = []
    for p in projects if isinstance(projects, list) else []:
        if not isinstance(p, dict) or len(out) >= MAX_PROJECTS:
            continue
        name, folder = slug(p.get("name")), str(p.get("folder") or "").strip().strip('"')
        if not name or not folder or len(folder) > MAX_FOLDER_CHARS or any(o["name"] == name for o in out):
            continue                              # too long is left out, never cut short: a cut path is another place
        cmds: list[dict] = []
        for c in p.get("commands") if isinstance(p.get("commands"), list) else []:
            if not isinstance(c, dict) or len(cmds) >= MAX_COMMANDS:
                continue
            cname = slug(c.get("name"))
            run = str(c.get("run") or "").strip()     # kept exactly as typed (only the ends are trimmed)
            if not cname or not run or len(run) > MAX_RUN_CHARS or re.search(r"[\x00-\x1f]", run) or any(o["name"] == cname for o in cmds):
                continue                          # too long or more than one line: left out, never cut short
            cmds.append({"name": cname, "run": run, "minutes": _minutes(c.get("minutes"))})
        out.append({"name": name, "folder": folder, "pull": p.get("pull") is True, "commands": cmds})
    return out


def _minutes(v) -> int:
    try:
        n = DEFAULT_MINUTES if v is None or v == "" or isinstance(v, bool) else int(float(v))
    except (TypeError, ValueError, OverflowError):
        n = DEFAULT_MINUTES
    return max(1, min(n, MAX_MINUTES))


def clean_settings(s) -> None:
    s.dev_tools = getattr(s, "dev_tools", False) is True
    s.dev_projects = clean(getattr(s, "dev_projects", []))


def is_on(settings) -> bool:
    return getattr(settings, "dev_tools", False) is True


def said(text) -> str:
    """A name as a connected app said it: only spaces around it and capitals are forgiven, so "../tests" or
    "tests --all" is never read as "tests"."""
    return str(text or "").strip().lower()


def find(settings, project: str) -> dict | None:
    want = said(project)
    return next((p for p in clean(getattr(settings, "dev_projects", [])) if p["name"] == want), None)


def folder_of(p: dict) -> Path | None:
    """The project's folder if it is a real folder on this PC (a full path), else None."""
    f = Path(os.path.expanduser(p["folder"]))
    return f if f.is_absolute() and f.is_dir() else None


def overlaps(folder: Path, workspace: Path) -> bool:
    """Is the project folder Joe's own folder, around it, or inside it? A connected app can already have
    files written in Joe's folder (a queued mission saves there), so a command run there could be changed
    by the app. Commands and bundle pulls are refused for such a folder."""
    a, b = Path(os.path.realpath(folder)), Path(os.path.realpath(workspace))
    return a == b or a in b.parents or b in a.parents


def shell_words(run: str) -> str:
    """A plain warning when a command has shell signs in it, which Joe passes along as ordinary words."""
    bare = re.sub(r'"[^"]*"|\'[^\']*\'', "", run)
    found = [w for w in ("&&", "||", "|", ">", "<", ";", "`", "$(") if w in bare]
    return ("" if not found else
            f"has {' '.join(found)} in it: Joe starts one program with its arguments, not a shell, so that part "
            "is handed to the program as it is (a .bat or .cmd file on Windows is run by Windows' own command "
            "program, which does read those signs). Put it in a script and list the script.")


def listing(settings) -> str:
    """What a connected app may ask for, by name."""
    if not is_on(settings):
        return OFF
    projects = clean(getattr(settings, "dev_projects", []))
    if not projects:
        return "Dev tools are on, but no project is listed yet (Setup > Other AI apps > Dev tools)."
    lines = ["Projects and the commands Joe may run in them (pick both by name; nothing can be added to a command):"]
    for p in projects:
        ok = folder_of(p)
        lines.append(f"{p['name']}: {p['folder']}" + ("" if ok else "  (that folder isn't there)")
                     + ("  [bundles may be pulled in]" if p["pull"] else ""))
        for c in p["commands"]:
            warn = shell_words(c["run"])
            lines.append(f"  {c['name']}  =  {c['run']}  (up to {c['minutes']} min)" + (f"  NOTE: {warn}" if warn else ""))
        if not p["commands"]:
            lines.append("  (no commands listed: repo status only)")
    return "\n".join(lines)


def summary(text: str) -> str:
    """Totals and failures only: the lines that look like a failure or a total, then the last few lines."""
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    lines = [ln for ln in lines if ln.strip()]
    if not lines:
        return "(it printed nothing)"
    tail_from = max(0, len(lines) - TAIL_LINES)
    picked = [i for i, ln in enumerate(lines[:tail_from]) if _PROBLEM.search(ln) or _TOTALS.search(ln)]
    out = []
    if picked:
        shown = picked[:MAX_PROBLEM_LINES]
        out.append(f"Lines with a failure, an error or a total ({len(shown)} of {len(picked)}):")
        out += [f"  L{i + 1}| {lines[i][:LINE_CHARS]}" for i in shown]
    out.append(f"Last {len(lines) - tail_from} of {len(lines):,} lines:")
    out += [f"  L{i + 1}| {lines[i][:LINE_CHARS]}" for i in range(tail_from, len(lines))]
    return "\n".join(out)


def _tidy(dev: Path) -> None:
    logs = sorted(dev.glob("*.log"), key=lambda p: p.stat().st_mtime)
    for old in logs[:-KEEP_LOGS]:
        try:
            old.unlink()
        except OSError:
            pass


class _Job:
    def __init__(self, what: str):
        self.what, self.report, self.started, self.finished = what, "", time.monotonic(), 0.0
        self.done = threading.Event()


_jobs: dict[tuple[str, str, str, str], _Job] = {}   # (Output/dev, project, command, its line) -> the run going or just finished
_jobs_lock = threading.Lock()


def state_dir() -> Path:
    """Where the "running" note and the minder's hand-over files live: beside Joe's settings, outside his
    workspace, so a mission or a connected app can't write there."""
    from .config import config_path
    d = config_path().parent / "dev-runs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _alive(pid: int) -> bool:
    """Is the minder (or Joe, for a pull) behind the note still a running program? No number yet counts as yes."""
    if pid <= 0:
        return True
    return devrun.pid_alive(pid)


def _num(v, default=None):
    """A number from a note or a file that anyone could have edited: anything else is the default, never an error."""
    try:
        if isinstance(v, bool) or v is None or v == "":
            return default
        n = float(v)
        return n if n == n and abs(n) != float("inf") else default
    except (TypeError, ValueError, OverflowError):
        return default


def _drop_note() -> None:
    """Take the "running" note and what hangs on it away (a run that can no longer be going)."""
    st = state_dir()
    for f in ("running.json", "running.prog.json", "stop.json"):
        try:
            (st / f).unlink()
        except OSError:
            pass


BOOT_SLACK_S = 5


def _before_boot(d: dict) -> bool:
    """Was the run in this note started before the PC last started? Then nothing of it can be going, whatever a
    program number now says (numbers are handed out again after a restart). A minder that is still the very
    same program (same start time) is never called old, in case the PC's clock was set after it started."""
    started, boot = _num(d.get("started")), devrun.boot_time()
    if started is None or boot is None or started >= boot - BOOT_SLACK_S:
        return False
    pid = int(_num(d.get("pid"), 0) or 0)
    return not (pid > 0 and devrun.same_born(devrun.proc_born(pid), d.get("born")))


def running_note() -> dict | None:
    """The "running" note as a dict while a run is really going; None when nothing is. A note left behind
    (the PC was switched off or crashed mid-run) stops counting, and is removed with the files that hang on
    it, when it was written before the PC last started, when its minder is gone, or when its time limit
    has passed."""
    p = state_dir() / "running.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(d, dict) and time.time() < float(d["until"]) and _alive(int(d.get("pid") or 0)):
            if _before_boot(d):
                _drop_note()
                return None
            return d
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def _busy() -> str:
    """What is running now ('' = nothing)."""
    d = running_note()
    return str(d["what"]) if d else ""


def _take_lock(what: str, limit_s: float, info: dict | None = None) -> Path | None:
    """The "running" note, made in one step so two askers can't both get it. None = someone else has it.
    `info` is what Joe's window shows about the run (project, command, who asked, when it started...)."""
    p = state_dir() / "running.json"
    for _ in range(2):
        try:
            with open(p, "x", encoding="utf-8") as f:
                json.dump({**(info or {}), "what": what, "pid": int((info or {}).get("pid") or 0),
                           "until": time.time() + limit_s + 120}, f)
            return p
        except FileExistsError:
            if _busy():
                return None
            try:
                p.unlink()                        # a note nobody is behind any more
            except OSError:
                return None
    return None


def _update_note(lock: Path, **fields) -> None:
    try:
        d = json.loads(lock.read_text(encoding="utf-8"))
        d.update(fields)
        lock.write_text(json.dumps(d), encoding="utf-8")
    except (OSError, ValueError):
        pass


def how_it_ended(res: dict, spec: dict) -> str:
    if res.get("error"):
        return "didn't start"
    if res.get("ended") == "limit":
        return f"STOPPED at its time limit ({spec['minutes']} min); the program and what it started were ended"
    if res.get("ended") == "stopped":
        return f"STOPPED by {res.get('by') or WINDOW_STOP}; the program and what it started were ended"
    if res.get("ended") == "cap":
        return f"STOPPED: it printed more than {int(spec['cap_bytes']) // 1_000_000} MB; the program was ended"
    return "finished OK (exit code 0)" if res.get("code") == 0 else f"FAILED (exit code {res.get('code')})"


def note_run(runs: Path, when: str, what: str, how: str, secs: float = 0.0) -> None:
    """One line per run or bundle pull in Output/dev/_runs.txt, so the person can see what was done."""
    try:
        runs.parent.mkdir(parents=True, exist_ok=True)
        with open(runs, "a", encoding="utf-8") as f:
            f.write(f"{when}  {what}  {how}  {_took(secs)}\n")
    except OSError:
        pass


def _took(secs: float) -> str:
    return f"{secs:.0f} s" if secs < 120 else f"{secs / 60:.1f} min"


def app_name(raw) -> str:
    """The connected app's name as it said it at the start (MCP initialize), made plain and short."""
    t = re.sub(r"[^\w .@+-]", "", str(raw or "")).strip()[:40]
    return t or "a connected app"


def totals_line(log: Path | None) -> str:
    """The last totals line in the end of a run's output ("12 passed, 0 failed"), else its last line."""
    lines = tail_lines(log, 400, 200_000) if log else []
    pick = next((ln for ln in reversed(lines) if _TOTALS.search(ln)), "")
    return (pick or next((ln for ln in reversed(lines) if ln.strip()), ""))[:LINE_CHARS]


def tail_lines(path: Path | None, n: int = VIEW_TAIL, max_bytes: int = 65_536) -> list[str]:
    """The last `n` lines of a file, reading only its end (a 20 MB log is never loaded)."""
    if not path:
        return []
    try:
        with open(path, "rb") as f:
            size = f.seek(0, os.SEEK_END)
            start = max(0, size - max_bytes)
            f.seek(start)
            raw = f.read(max_bytes)
    except OSError:
        return []
    text = raw.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    one_piece = start > 0 and len([ln for ln in lines if ln.strip()]) == 1 and lines[0].strip() != ""
    if start > 0 and not one_piece and len(lines) > 1:
        lines = lines[1:]                          # the first line may be cut in half
    while lines and not lines[-1].strip():
        lines.pop()
    if one_piece and lines:                        # the end of one very long line: its last piece is what is shown
        return [lines[0][-LINE_CHARS:]]
    return [ln[:LINE_CHARS] for ln in lines[-n:]]


def _last_path() -> Path:
    return state_dir() / "last.json"


def write_last(path, info: dict, how: str, res: dict, log: Path | None, summary: str = "") -> None:
    """What Joe's window shows once a run is over: how it ended and the totals."""
    secs = float(res.get("secs") or 0) if isinstance(res, dict) else 0.0
    r = res or {}
    outcome = ("pull" if info.get("kind") == "pull" else "didnt" if r.get("error") else
               r.get("ended") if r.get("ended") in ("limit", "cap", "stopped") else "ok" if r.get("code") == 0 else "failed")
    data = {**info, "how": how, "outcome": outcome, "by": str(r.get("by") or ""), "ended": time.time(), "secs": secs,
            "code": r.get("code"),
            "totals": totals_line(log) if log else (summary.splitlines()[0][:LINE_CHARS] if summary else ""),
            "summary": summary[:4000]}
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def _inside_dev(sb, log) -> Path | None:
    """A log path from a note, only if it is a file in Output/dev (never anything else)."""
    try:
        p = Path(os.path.realpath(str(log)))
        dev = Path(os.path.realpath(str(sb.output / "dev")))
        return p if log and dev in p.parents else None
    except (OSError, ValueError, TypeError):
        return None


def view(sb) -> dict:
    """What Joe's window shows on Home: the run going (or the one that just ended), the end of its output,
    and the end of _runs.txt. Reads only small files and the end of the log."""
    now = time.time()
    dev = sb.output / "dev"
    out: dict = {"running": None, "last": None, "tail": [], "show": False,
                 "runs": tail_lines(dev / "_runs.txt", VIEW_RUNS)}

    def plain(d: dict) -> dict:
        log = _inside_dev(sb, d.get("log"))
        return {"what": str(d.get("what") or ""), "project": str(d.get("project") or ""), "command": str(d.get("command") or ""),
                "run": str(d.get("run") or ""), "who": str(d.get("who") or "a connected app"), "kind": str(d.get("kind") or "command"),
                "started": _num(d.get("started"), now), "log": f"Output/dev/{log.name}" if log else ""}
    note = running_note()
    if note:
        r = plain(note)
        r["secs"] = max(0.0, now - r["started"])
        r["can_stop"] = r["kind"] != "pull"
        r["minutes"] = _num(note.get("minutes"), 0)
        out.update(running=r, show=True, tail=tail_lines(_inside_dev(sb, note.get("log"))))
        return out
    try:
        d = json.loads(_last_path().read_text(encoding="utf-8"))
        if not isinstance(d, dict):
            raise ValueError
    except (OSError, ValueError):
        return out
    r = plain(d)
    r.update(how=str(d.get("how") or ""), outcome=str(d.get("outcome") or ""), by=str(d.get("by") or ""),
             code=d.get("code"), minutes=_num(d.get("minutes"), 0), totals=str(d.get("totals") or ""), secs=_num(d.get("secs"), 0.0),
             ago_s=max(0.0, now - _num(d.get("ended"), 0.0)))
    out["last"] = r
    out["show"] = r["ago_s"] < RECENT_S              # the whole panel with the end of the output...
    out["collapsed"] = not out["show"]               # ...else one line ("last run: ...") stays for as long as the note is there
    log = _inside_dev(sb, d.get("log"))
    out["tail"] = tail_lines(log) if log else str(d.get("summary") or "").splitlines()[-VIEW_TAIL:]
    return out


def _ident(note: dict) -> str:
    """Which run a note is about: the name of its log file (one per run)."""
    return Path(str(note.get("log") or "")).stem


def _read_json(path: Path) -> dict:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def stop_run(by: str = WINDOW_STOP, only: tuple[str, str] | None = None, wait_s: float = STOP_WAIT_S,
             sb=None, who: str | None = None) -> dict:
    """End the run that is going: the program and everything it started (Windows: taskkill /T and the minder's
    Job Object; elsewhere the program's process group). The minder notices the stop note within a moment, ends
    the tree, and writes "stopped by ..." in _runs.txt and the result; the note names the run, so a minder
    obeys only its own. If it doesn't within `wait_s`, this looks again at what is running: only that same run
    is then ended from here (the minder first, then the program, each only if it is still the very program Joe
    started: same number and same start time), and written down. `only` = (project, command) and `who` = the
    app's name: stop only if that run is the one going and that app started it."""
    note = running_note()
    if not note:
        return {"ok": False, "message": "Nothing is running right now."}
    if only and (str(note.get("project")), str(note.get("command"))) != (said(only[0]), said(only[1])):
        return {"ok": False, "message": f"{said(only[0])} / {said(only[1])} isn't running. What is running is "
                                        f"{note.get('what')}, so nothing was stopped."}
    if who is not None and str(note.get("who") or "") != who:
        return {"ok": False, "message": f"{note.get('what')} was started by {note.get('who') or 'another app'}, not by "
                                        f"{who or 'this app'}, so nothing was stopped. Only the app that started a run (or "
                                        "the person in Joe's window) can stop it."}
    if note.get("kind") == "pull":
        return {"ok": False, "message": "A bundle is being brought in right now. That takes a moment and can't be "
                                        "stopped half way; it will be over shortly."}
    ident = _ident(note)
    if not ident:
        return {"ok": False, "message": "That run is only just starting. Ask again in a moment."}
    st = state_dir()
    try:
        devrun._write_json(st / "stop.json", {"by": by, "at": time.time(), "run": ident})
    except OSError as e:
        return {"ok": False, "message": f"Joe couldn't ask the run to stop ({e})."}
    done = {"ok": True, "message": f"{note.get('what')} was stopped by {by}. The program and everything it started were ended."}
    end = time.monotonic() + max(0.0, wait_s)
    while time.monotonic() < end:
        if not (st / "running.json").exists():
            return done
        time.sleep(0.1)
    # The minder didn't wind it up in time. Look again: only the same run is ended from here.
    now = running_note()
    if now is None:
        return done
    if _ident(now) != ident:
        return {"ok": True, "message": f"{note.get('what')} has ended. {now.get('what')} has started since, and Joe left it alone."}
    prog = _read_json(st / "running.prog.json")
    if prog.get("run") not in (None, ident):
        prog = {}                                  # a program note from some other run is not this run's
    mpid, ppid = int(_num(now.get("pid"), 0) or 0), int(_num(prog.get("pid"), 0) or 0)
    seen = {"minder": devrun.check_same(mpid, now.get("born")), "program": devrun.check_same(ppid, prog.get("born"))}
    if "unsure" in seen.values():
        who_ = " and ".join(k for k, v in seen.items() if v == "unsure")
        return {"ok": False, "message": f"Joe asked {note.get('what')} to stop but it didn't, and he can't tell for sure that the {who_} "
                                        "still running is the one he started (its start time can't be read), so he did not end "
                                        "anything by force. The person can press STOP again, or end it in Task Manager."}
    if seen["minder"] == "same":                   # the minder first, so it writes nothing more about a program that is going
        devrun.kill_tree(mpid)
    if seen["program"] == "same":
        devrun.kill_tree(ppid)
    secs = max(0.0, time.time() - _num(note.get("started"), time.time()))
    res = {"code": None, "ended": "stopped", "secs": round(secs, 1), "error": "", "by": by}
    spec = {"minutes": _num(note.get("minutes"), 0), "cap_bytes": MAX_LOG_BYTES}
    how = how_it_ended(res, spec)
    try:
        log = _inside_dev(sb, note.get("log")) if sb is not None else None
        write_last(_last_path(), {**{k: note.get(k, "") for k in ("what", "project", "command", "run", "who", "started", "kind")},
                                  "log": str(log) if log else ""}, how, res, log)
        if sb is not None:
            note_run(sb.output / "dev" / "_runs.txt", str(note.get("when") or ""), str(note.get("what") or ""), how, secs)
        result = Path(str(note.get("result") or ""))
        if note.get("result") and result.parent == st:
            devrun._write_json(result, res)
    except Exception:                              # noqa: BLE001
        pass
    _drop_note()
    return done


def begin_pull(what: str, who: str, project: str, bundle: str) -> Path | None:
    """A bundle pull is shown like a run (short, and not stoppable). None = a run or pull is already going."""
    now = time.time()
    return _take_lock(what, 300, {"project": project, "command": "bundle pull", "run": f"bring in {bundle}"[:200], "who": app_name(who),
                                  "kind": "pull", "started": now, "pid": os.getpid(),
                                  "born": devrun.proc_born(os.getpid())})


def end_pull(lock: Path, who: str, what: str, project: str, bundle: str, started: float, out: str) -> None:
    """The pull is over: show how it went in Joe's window, then let go of the note."""
    try:
        first = (out.splitlines() or ["no answer"])[0][:200]
        write_last(_last_path(), {"what": what, "project": project, "command": "bundle pull", "run": f"bring in {bundle}"[:200],
                                  "who": app_name(who), "started": started, "kind": "pull", "log": ""},
                   first, {"secs": time.time() - started, "code": None}, None, summary=out)
    except OSError:
        pass
    try:
        lock.unlink()
    except OSError:
        pass


def _minder_command(spec: Path) -> list[str]:
    """This Python, running joeai/devrun.py from wherever this Joe lives (installed, portable or a copy)."""
    here = str(Path(__file__).resolve().parent.parent)
    return [sys.executable, "-c", f"import sys; sys.path.insert(0, {here!r}); from joeai import devrun; "
            "raise SystemExit(devrun.main())", str(spec)]


def _execute(job: _Job, p: dict, c: dict, folder: Path, dev: Path, lock: Path, now: datetime, who: str = "") -> None:
    """Start the minder (devrun.py) and wait for it. The minder, not this thread, holds the limits."""
    from . import system
    from .system import WINDOWS, no_window_flags
    stamp = f"{now:%Y%m%d-%H%M%S}"
    log = dev / f"{p['name']}-{c['name']}-{stamp}.log"
    n = 1
    while log.exists():
        n += 1
        log = dev / f"{p['name']}-{c['name']}-{stamp}-{n}.log"
    st = state_dir()
    spec_path, result = st / f"{log.stem}.spec.json", st / f"{log.stem}.result.json"
    spec = {"run": c["run"], "cwd": str(folder), "log": str(log), "limit_s": c["minutes"] * 60, "minutes": c["minutes"],
            "cap_bytes": MAX_LOG_BYTES, "result": str(result), "lock": str(lock), "runs": str(dev / "_runs.txt"),
            "what": job.what, "when": f"{now:%Y-%m-%d %H:%M:%S}",
            "prog": str(st / "running.prog.json"), "stop": str(st / "stop.json"), "last": str(_last_path())}
    try:
        for stale in (st / "stop.json", st / "running.prog.json"):      # a stop or program note from an earlier run
            try:
                stale.unlink()
            except OSError:
                pass
        try:
            started = _num(json.loads(lock.read_text(encoding="utf-8")).get("started"), time.time())
        except (OSError, ValueError, AttributeError):
            started = time.time()
        spec["info"] = {"what": job.what, "project": p["name"], "command": c["name"], "run": c["run"],
                        "who": app_name(who), "started": started, "kind": "command", "log": str(log)}
        _update_note(lock, log=str(log), runs=spec["runs"], result=str(result), when=spec["when"], minutes=c["minutes"])
        spec_path.write_text(json.dumps(spec), encoding="utf-8")
        try:
            minder = system.popen_breakaway(_minder_command(spec_path), no_window_flags(), stdin=subprocess.DEVNULL,
                                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                            **({} if WINDOWS else {"start_new_session": True}))
        except OSError as e:
            job.report = f"{job.what}: Joe couldn't start it ({e})."
            for f in (lock, spec_path):
                try:
                    f.unlink()
                except OSError:
                    pass
            return
        try:                                      # the minder's number goes in the note, so a dead minder is noticed
            d = json.loads(lock.read_text(encoding="utf-8"))
            d["pid"] = minder.pid
            d["born"] = devrun.proc_born(minder.pid)       # with its number, so only this very program is ever ended by force
            lock.write_text(json.dumps(d), encoding="utf-8")
        except (OSError, ValueError):
            pass
        minder.wait()
        try:
            res = json.loads(result.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            res = {"code": None, "ended": "", "secs": 0.0, "error": "its minder stopped before it could say how it went"}
        try:
            result.unlink()
        except OSError:
            pass
        if res.get("error"):
            job.report = (f"{job.what} didn't start: {res['error']}. The command is: {c['run']} (in {folder}). "
                          "The person can fix it in Setup > Other AI apps > Dev tools.")
            try:
                if log.exists() and not log.stat().st_size:
                    log.unlink()
            except OSError:
                pass
            return
        try:
            with open(log, "rb") as f:
                size = log.stat().st_size
                if size > 2_000_000:              # the short report needs the failures and the end, not 20 MB in memory
                    head = f.read(1_000_000)
                    f.seek(size - 1_000_000)
                    raw = head + b"\n... (the middle of a very long output is left out here; the whole of it is in the file)\n" + f.read()
                else:
                    raw = f.read()
        except OSError:
            raw = b""
        _tidy(dev)
        job.report = (f"[{job.what} | {how_it_ended(res, spec)} | {_took(float(res.get('secs') or 0))} | "
                      f"started {now:%Y-%m-%d %H:%M} | whole output: Output/dev/{log.name} (joe_shrink reads it)]\n"
                      f"ran: {c['run']}\n{summary(raw.decode('utf-8', errors='replace'))}")
    except Exception as e:                       # noqa: BLE001 (the app still gets a plain answer)
        job.report = f"{job.what}: Joe hit a problem running it ({e})."
    finally:
        job.finished = time.monotonic()
        job.done.set()


def run(settings, sandbox, project: str, command: str, wait_s: float = WAIT_S, now: datetime | None = None,
        who: str = "", ready=None) -> str:
    """Run one listed command and say, briefly, how it went. A run that takes longer than `wait_s` keeps
    going: the answer says STILL RUNNING, and asking again with the same two names waits for it (it is
    never started twice) and hands over the result once, when it has finished.
    `who` = the connected app that asked (shown in Joe's window). `ready` = called just before a NEW run
    starts, with no argument: it returns "" when Joe's window is open (opening it first if it was closed)
    or the plain reason it could not be, and then nothing is run."""
    if not is_on(settings):
        return OFF
    p = find(settings, project)
    if p is None:
        return f"No project called '{said(project)[:40]}' on the list.\n" + listing(settings)
    c = next((c for c in p["commands"] if c["name"] == said(command)), None)
    if c is None:
        return f"No command called '{said(command)[:40]}' for {p['name']}.\n" + listing(settings)
    dev = sandbox.output / "dev"
    key = (str(dev), p["name"], c["name"], c["run"])
    what = f"{p['name']} / {c['name']}"
    with _jobs_lock:
        for k, j in list(_jobs.items()):          # a result nobody came back for is not handed over as news later
            if j.done.is_set() and time.monotonic() - j.finished > KEEP_RESULT_S:
                del _jobs[k]
        job = _jobs.get(key)
    if job is None:
        folder = folder_of(p)
        if folder is None:
            return (f"The folder for {p['name']} isn't there: {p['folder']}. The person can fix it in "
                    "Setup > Other AI apps > Dev tools.")
        if overlaps(folder, sandbox.root):
            return (f"{p['name']} is Joe's own folder, or holds it, or is inside it ({p['folder']}). Commands "
                    "aren't run there: a connected app can already put files in Joe's folder, so it could "
                    "change what a command does. List a project folder that is separate from Joe's.")
        if ready is not None:                     # Joe's window must be open (and showing this) before it starts
            why = ready()
            if why:
                return why
        with _jobs_lock:
            job = _jobs.get(key)
            if job is None:
                dev.mkdir(parents=True, exist_ok=True)
                started = time.time()
                lock = _take_lock(what, c["minutes"] * 60, {"project": p["name"], "command": c["name"], "run": c["run"],
                                                            "who": app_name(who), "kind": "command", "started": started})
                if lock is None:
                    return f"Joe is already running {_busy() or 'a command'}. One command at a time: ask again when it has finished."
                job = _jobs[key] = _Job(what)
                threading.Thread(target=_execute, args=(job, p, c, folder, dev, lock, now or datetime.now(), who), daemon=True).start()
    if not job.done.wait(max(0.0, float(wait_s))):
        so_far = time.monotonic() - job.started
        return (f"[{job.what} | STILL RUNNING, {so_far:.0f} s so far (limit {c['minutes']} min)]\n"
                "Ask again with the same project and command to wait for it; it is not started twice. "
                "joe_computer shows what the PC is doing meanwhile.")
    with _jobs_lock:
        _jobs.pop(key, None)                      # handed over once; the next ask is a fresh run
    late = time.monotonic() - job.finished
    if late > 60:
        return job.report.replace("]", f" | finished {late / 60:.0f} min ago, not run again]", 1)
    return job.report
