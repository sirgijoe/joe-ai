"""The little minder that runs one Dev tools command (devprojects.py starts it as its own program).

Why a separate program: the time limit and the output cap must hold even when the AI app closes its
connector, Joe is closed, or Joe restarts while a command is still going (found in the 2026-11-27
security review: the command ran on with no limit and its output grew without end). The minder is
handed one small file saying what to run, and it alone starts the program, copies its output to the
log up to the cap, ends the program and everything it started at the limit, writes down how it went
and takes the "running" note away. It reads nothing from a connected app.

    python -c "... from joeai import devrun; devrun.main()" <spec.json>
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path


def program_line(run: str, cwd: Path):
    """What to hand the system. A program named with a folder in front (scripts\\check.bat, ./run.sh) is
    looked for in the project's folder, where the person meant it, not in Joe's own. Windows gets the
    line as typed (its own quoting rules, no cmd.exe added by Joe); elsewhere it is split into words
    the way a shell would, with no shell involved."""
    from .system import WINDOWS
    if WINDOWS:
        s = run.strip()
        if s.startswith('"'):
            end = s.find('"', 1)
            first, rest = (s[1:end], s[end + 1:]) if end > 0 else (s[1:], "")
        else:
            first, _, rest = s.partition(" ")
            rest = (" " + rest) if rest else ""
        if ("\\" in first or "/" in first) and not os.path.isabs(first) and (cwd / first).exists():
            return f'"{cwd / first}"{rest}'
        return s
    import shlex
    argv = shlex.split(run)
    if argv and "/" in argv[0] and not os.path.isabs(argv[0]) and (cwd / argv[0]).exists():
        argv[0] = str(cwd / argv[0])
    return argv


def end_tree(proc: subprocess.Popen) -> None:
    """End the program and everything it started (a test runner's workers, a server it launched)."""
    from .system import WINDOWS, no_window_flags
    try:
        if WINDOWS:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=20,
                           creationflags=no_window_flags())
        else:
            import signal
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError, ProcessLookupError):
        pass
    try:
        proc.kill()
    except OSError:
        pass


def run_spec(spec: dict) -> dict:
    """Run it; returns {"code", "ended", "secs", "error"} (also what is written to spec["result"])."""
    from .system import WINDOWS, no_window_flags
    cwd, log = Path(spec["cwd"]), Path(spec["log"])
    limit, cap = float(spec["limit_s"]), int(spec["cap_bytes"])
    start, state = time.monotonic(), {"ended": "", "bytes": 0}
    res = {"code": None, "ended": "", "secs": 0.0, "error": ""}
    try:
        proc = subprocess.Popen(program_line(spec["run"], cwd), cwd=str(cwd), stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                creationflags=no_window_flags(), start_new_session=not WINDOWS)
    except (OSError, ValueError) as e:
        log.write_bytes(b"")
        res["error"] = str(e)
        return res

    def copy():                                   # the output goes to the log; past the cap nothing more is kept
        with open(log, "wb") as out:
            while True:
                chunk = proc.stdout.read1(65536) if hasattr(proc.stdout, "read1") else proc.stdout.read(65536)
                if not chunk:
                    return
                room = cap - state["bytes"]
                if room > 0:
                    out.write(chunk[:room])
                    out.flush()
                state["bytes"] += len(chunk)
                if state["bytes"] > cap and not state["ended"]:
                    state["ended"] = "cap"
                    end_tree(proc)

    t = threading.Thread(target=copy, daemon=True)
    t.start()
    while proc.poll() is None:
        if time.monotonic() - start > limit and not state["ended"]:
            state["ended"] = "limit"
            end_tree(proc)
            break
        time.sleep(0.1)
    try:
        proc.wait(timeout=15)
    except (OSError, subprocess.SubprocessError):
        pass
    t.join(timeout=5)                              # a program it started may still hold the pipe: don't wait on it
    res.update(code=proc.returncode, ended=state["ended"], secs=round(time.monotonic() - start, 1))
    return res


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    spec_path = Path(argv[0])
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    try:
        res = run_spec(spec)
    except Exception as e:                         # noqa: BLE001 (the result file is how anyone finds out)
        res = {"code": None, "ended": "", "secs": 0.0, "error": f"Joe hit a problem running it ({e})"}
    try:
        from . import devprojects
        devprojects.note_run(Path(spec["runs"]), spec["when"], spec["what"], devprojects.how_it_ended(res, spec), res["secs"])
    except Exception:                              # noqa: BLE001
        pass
    tmp = Path(spec["result"] + ".tmp")
    tmp.write_text(json.dumps(res), encoding="utf-8")
    os.replace(tmp, spec["result"])
    for p in (spec.get("lock"), str(spec_path)):   # the "running" note goes last, once the result is there
        try:
            if p:
                os.unlink(p)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
