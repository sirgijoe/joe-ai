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
    from .system import WINDOWS
    if WINDOWS or pid <= 0:
        return True                               # not checked on Windows: the time in the note decides
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return True


def _busy() -> str:
    """What is running now ('' = nothing). A note left behind (the PC was switched off mid-run) stops
    counting when its minder is gone or its time limit has passed."""
    p = state_dir() / "running.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        if time.time() < float(d["until"]) and _alive(int(d.get("pid") or 0)):
            return str(d["what"])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return ""


def _take_lock(what: str, limit_s: float) -> Path | None:
    """The "running" note, made in one step so two askers can't both get it. None = someone else has it."""
    p = state_dir() / "running.json"
    for _ in range(2):
        try:
            with open(p, "x", encoding="utf-8") as f:
                json.dump({"what": what, "pid": 0, "until": time.time() + limit_s + 120}, f)
            return p
        except FileExistsError:
            if _busy():
                return None
            try:
                p.unlink()                        # a note nobody is behind any more
            except OSError:
                return None
    return None


def how_it_ended(res: dict, spec: dict) -> str:
    if res.get("error"):
        return "didn't start"
    if res.get("ended") == "limit":
        return f"STOPPED at its time limit ({spec['minutes']} min); the program and what it started were ended"
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


def _minder_command(spec: Path) -> list[str]:
    """This Python, running joeai/devrun.py from wherever this Joe lives (installed, portable or a copy)."""
    here = str(Path(__file__).resolve().parent.parent)
    return [sys.executable, "-c", f"import sys; sys.path.insert(0, {here!r}); from joeai import devrun; "
            "raise SystemExit(devrun.main())", str(spec)]


def _execute(job: _Job, p: dict, c: dict, folder: Path, dev: Path, lock: Path, now: datetime) -> None:
    """Start the minder (devrun.py) and wait for it. The minder, not this thread, holds the limits."""
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
            "what": job.what, "when": f"{now:%Y-%m-%d %H:%M:%S}"}
    try:
        spec_path.write_text(json.dumps(spec), encoding="utf-8")
        try:
            minder = subprocess.Popen(_minder_command(spec_path), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL, creationflags=no_window_flags(),
                                      start_new_session=not WINDOWS)
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


def run(settings, sandbox, project: str, command: str, wait_s: float = WAIT_S, now: datetime | None = None) -> str:
    """Run one listed command and say, briefly, how it went. A run that takes longer than `wait_s` keeps
    going: the answer says STILL RUNNING, and asking again with the same two names waits for it (it is
    never started twice) and hands over the result once, when it has finished."""
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
            dev.mkdir(parents=True, exist_ok=True)
            what = f"{p['name']} / {c['name']}"
            lock = _take_lock(what, c["minutes"] * 60)
            if lock is None:
                return f"Joe is already running {_busy() or 'a command'}. One command at a time: ask again when it has finished."
            job = _jobs[key] = _Job(what)
            threading.Thread(target=_execute, args=(job, p, c, folder, dev, lock, now or datetime.now()), daemon=True).start()
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
