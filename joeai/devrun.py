"""The little minder that runs one Dev tools command (devprojects.py starts it as its own program).

Why a separate program: the time limit and the output cap must hold even when the AI app closes its
connector, Joe is closed, or Joe restarts while a command is still going (found in the 2026-11-27
security review: the command ran on with no limit and its output grew without end). The minder is
handed one small file saying what to run, and it alone starts the program, copies its output to the
log up to the cap, ends the program and everything it started at the limit (or when the person presses
STOP in Joe's window, or a chat asks to stop its own run: a small stop file says so), writes down how it
went (the "last run" note Joe's window shows, and a line in _runs.txt) and takes the "running" note away.
It reads nothing from a connected app. Whatever the program started is ended with it: when the program
ends normally (its process group; on Windows a Job Object that also ends everything if the minder itself
dies), and a stop note is obeyed only when it names this run.

    python -c "... from joeai import devrun; devrun.main()" <spec.json>
"""
from __future__ import annotations

import json
import os
import re
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


# ------------------------------------------------------------------ is that process there, and is it the same one?
_BOOT: list = []


def _k32():
    """kernel32 for the Windows calls below (None anywhere else, or when it can't be loaded)."""
    from .system import WINDOWS
    if not WINDOWS:
        return None
    try:
        import ctypes
        return ctypes.WinDLL("kernel32", use_last_error=True)      # type: ignore[attr-defined]
    except (OSError, AttributeError, ImportError):
        return None


def boot_time() -> float | None:
    """When this PC last started (seconds since 1970), or None when it can't be told. Windows: the tick
    count; Linux: /proc/uptime; Mac: sysctl kern.boottime. Worked out once per program."""
    if _BOOT:
        return _BOOT[0]
    from .system import MAC, WINDOWS
    t = None
    try:
        if WINDOWS:
            k = _k32()
            if k is not None:
                import ctypes
                k.GetTickCount64.restype = ctypes.c_ulonglong
                t = time.time() - int(k.GetTickCount64()) / 1000.0
        elif MAC:
            out = subprocess.run(["sysctl", "-n", "kern.boottime"], capture_output=True, text=True, timeout=5).stdout
            m = re.search(r"sec\s*=\s*(\d+)", out)
            t = float(m.group(1)) if m else None
        else:
            with open("/proc/uptime", "rb") as f:
                t = time.time() - float(f.read().split()[0])
    except (OSError, ValueError, IndexError, subprocess.SubprocessError, AttributeError):
        t = None
    _BOOT.append(t)
    return t


def pid_alive(pid: int) -> bool:
    """Is a program with this number still running? Windows: OpenProcess + GetExitCodeProcess (259 =
    still active). Elsewhere: signal 0, and a defunct one that only waits to be collected counts as gone."""
    from .system import WINDOWS
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if WINDOWS:
        import ctypes
        k = _k32()
        if k is None:
            return True                           # can't ask: not called gone
        k.OpenProcess.restype = ctypes.c_void_p
        h = k.OpenProcess(0x1000, False, pid)     # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ctypes.get_last_error() == 5   # access denied: it is there, just not ours to ask
        try:
            code = ctypes.c_ulong(0)
            if not k.GetExitCodeProcess(ctypes.c_void_p(h), ctypes.byref(code)):
                return True
            return code.value == 259              # STILL_ACTIVE
        finally:
            k.CloseHandle(ctypes.c_void_p(h))
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    try:                                          # Linux: a zombie answers kill 0 but is already dead
        with open(f"/proc/{pid}/stat", "rb") as f:
            return f.read().rsplit(b")", 1)[1].split()[0] != b"Z"
    except (OSError, IndexError):
        return True


def _gone(pid: int) -> bool:
    """Is that process finished?"""
    return not pid_alive(pid)


def proc_born(pid: int) -> float | None:
    """When that program started, as a number only comparable with another one from this function (a
    program number can be given to another program later; the start time tells them apart). Windows:
    GetProcessTimes (seconds since 1970). Linux: /proc/<pid>/stat start time (seconds since the PC started;
    a restart is caught separately by boot_time). Mac: `ps -o lstart=`. None = can't be read."""
    from .system import MAC, WINDOWS
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    try:
        if WINDOWS:
            import ctypes
            k = _k32()
            if k is None:
                return None

            class FT(ctypes.Structure):
                _fields_ = [("lo", ctypes.c_ulong), ("hi", ctypes.c_ulong)]
            k.OpenProcess.restype = ctypes.c_void_p
            h = k.OpenProcess(0x1000, False, pid)
            if not h:
                return None
            try:
                c, e, kt, ut = FT(), FT(), FT(), FT()
                if not k.GetProcessTimes(ctypes.c_void_p(h), ctypes.byref(c), ctypes.byref(e), ctypes.byref(kt), ctypes.byref(ut)):
                    return None
                return ((c.hi << 32 | c.lo) - 116444736000000000) / 1e7
            finally:
                k.CloseHandle(ctypes.c_void_p(h))
        if MAC:
            out = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True, timeout=5,
                                 env={**os.environ, "LC_ALL": "C"}).stdout.strip()
            return float(time.mktime(time.strptime(out, "%a %b %d %H:%M:%S %Y"))) if out else None
        with open(f"/proc/{pid}/stat", "rb") as f:
            ticks = int(f.read().rsplit(b")", 1)[1].split()[19])
        return ticks / float(os.sysconf("SC_CLK_TCK"))
    except (OSError, ValueError, IndexError, subprocess.SubprocessError, AttributeError, OverflowError):
        return None


def same_born(a, b) -> bool:
    """Two start times from proc_born are the same program's (a second of slack for the Mac's whole seconds)."""
    try:
        return a is not None and b is not None and abs(float(a) - float(b)) <= 2.0
    except (TypeError, ValueError):
        return False


def kill_tree(pid: int) -> None:
    """End a program and everything it started, so nothing is left running behind it.
    Windows: `taskkill /PID <pid> /T /F` ends the program and every program it started (the tree is
    followed by parent numbers). Mac and Linux: the program was started in its own process group
    (start_new_session), so the whole group is ended; a number that is not the leader of its own group
    is never group-killed, only that one program. Joe's own number and his parent's are never ended."""
    from .system import WINDOWS, no_window_flags
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return
    if pid <= 0 or pid in (os.getpid(), os.getppid()):
        return
    try:
        if WINDOWS:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=20,
                           creationflags=no_window_flags())
            return
        import signal
        try:
            leader = os.getpgid(pid) == pid and pid != os.getpgrp()
        except OSError:
            return                                # already gone
        if leader:
            os.killpg(pid, signal.SIGKILL)
        else:
            os.kill(pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass


def check_same(pid, born) -> str:
    """Is that number still the very program Joe started (same number AND same start time)?
    'same' | 'gone' (nothing there) | 'different' (the number now belongs to another program) |
    'unsure' (it is there but its start time, or the one written down, can't be had)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return "gone"
    if pid <= 0 or not pid_alive(pid):
        return "gone"
    now = proc_born(pid)
    if now is None or born is None:
        return "unsure"
    return "same" if same_born(now, born) else "different"


def kill_verified(pid, born) -> str:
    """End that program and what it started, but only if check_same says it is the very program Joe started.
    Returns what check_same said, or 'killed'. A program that is 'different' or 'unsure' is left alone."""
    what = check_same(pid, born)
    if what != "same":
        return what
    kill_tree(pid)
    return "killed"


# ------------------------------------------------------------------ a Windows Job Object: when the minder ends, so does everything under it
def _make_job():
    """A job that ends every program in it when its last handle closes (the minder dying closes it). None
    anywhere but Windows, or if Windows says no (taskkill still does the ending then)."""
    k = _k32()
    if k is None:
        return None
    try:
        import ctypes

        class BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", ctypes.c_ulong), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", ctypes.c_ulong),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", ctypes.c_ulong), ("SchedulingClass", ctypes.c_ulong)]

        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOps", "WriteOps", "OtherOps", "ReadBytes", "WriteBytes", "OtherBytes")]

        class EXT(ctypes.Structure):
            _fields_ = [("Basic", BASIC), ("Io", IO), ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]
        k.CreateJobObjectW.restype = ctypes.c_void_p
        job = k.CreateJobObjectW(None, None)
        if not job:
            return None
        info = EXT()
        info.Basic.LimitFlags = 0x2000                      # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k.SetInformationJobObject(ctypes.c_void_p(job), 9, ctypes.byref(info), ctypes.sizeof(info)):   # 9 = extended limits
            k.CloseHandle(ctypes.c_void_p(job))
            return None
        return job
    except Exception:                                       # noqa: BLE001 (the job is a safety net, never a reason not to run)
        return None


def _job_add(job, proc) -> bool:
    k = _k32()
    if job is None or k is None:
        return False
    try:
        import ctypes
        return bool(k.AssignProcessToJobObject(ctypes.c_void_p(job), ctypes.c_void_p(int(proc._handle))))   # type: ignore[attr-defined]
    except Exception:                                       # noqa: BLE001
        return False


def _job_kill(job) -> None:
    """End whatever is in the job now (the job itself stays until _job_end)."""
    k = _k32()
    if job is None or k is None:
        return
    try:
        import ctypes
        k.TerminateJobObject(ctypes.c_void_p(job), 1)
    except Exception:                                       # noqa: BLE001
        pass


def _job_end(job) -> None:
    """End whatever is left in the job and let go of it (once, at the very end of the run)."""
    _job_kill(job)
    k = _k32()
    if job is None or k is None:
        return
    try:
        import ctypes
        k.CloseHandle(ctypes.c_void_p(job))
    except Exception:                                       # noqa: BLE001
        pass


def end_leftovers(proc: subprocess.Popen, job=None) -> None:
    """The program is over: end anything it started that is still going (a server it launched, test workers).
    Windows: the job. Elsewhere: the program's process group."""
    from .system import WINDOWS
    if job is not None:
        _job_end(job)                              # Windows: ends what is left in the job
    if WINDOWS:
        return
    import signal
    pgid = proc.pid
    if pgid <= 1 or pgid in (os.getpid(), os.getppid()):
        return
    try:
        if pgid != os.getpgrp():
            os.killpg(pgid, signal.SIGKILL)
    except OSError:
        pass


def end_tree(proc: subprocess.Popen, job=None) -> None:
    """End the program and everything it started (a test runner's workers, a server it launched)."""
    kill_tree(proc.pid)
    _job_kill(job)
    try:
        proc.kill()
    except OSError:
        pass


def _write_json(path, data) -> None:
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def run_id(spec: dict) -> str:
    """Which run this is: the name of its log file (one per run)."""
    return Path(str(spec.get("log") or "")).stem


def _stop_asked(spec: dict) -> str | None:
    """Has the person (in Joe's window) or a chat asked for THIS run to stop? Who asked, or None. A stop
    note for another run (or one with no run named) is not this run's to obey."""
    f = spec.get("stop")
    if not f or not os.path.exists(f):
        return None
    try:
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        if not isinstance(d, dict) or not run_id(spec) or str(d.get("run") or "") != run_id(spec):
            return None
        by = str(d.get("by") or "")
    except (OSError, ValueError, AttributeError):
        return None
    return by or "the person in Joe's window"


def run_spec(spec: dict) -> dict:
    """Run it; returns {"code", "ended", "secs", "error"} (also what is written to spec["result"])."""
    from .system import WINDOWS, no_window_flags
    cwd, log = Path(spec["cwd"]), Path(spec["log"])
    limit, cap = float(spec["limit_s"]), int(spec["cap_bytes"])
    start, state = time.monotonic(), {"ended": "", "bytes": 0}
    res = {"code": None, "ended": "", "secs": 0.0, "error": "", "by": ""}
    job = _make_job()                              # Windows: everything the program starts ends with this minder
    try:
        proc = subprocess.Popen(program_line(spec["run"], cwd), cwd=str(cwd), stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                creationflags=no_window_flags(), start_new_session=not WINDOWS)
    except (OSError, ValueError) as e:
        _job_end(job)
        log.write_bytes(b"")
        res["error"] = str(e)
        return res
    if job is not None and not _job_add(job, proc):
        _job_end(job)                              # couldn't be used: taskkill still does the ending
        job = None

    if spec.get("prog"):                           # the program's number and start time, so STOP ends only this very program
        try:
            _write_json(spec["prog"], {"pid": proc.pid, "born": proc_born(proc.pid), "run": run_id(spec)})
        except OSError:
            pass

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
                    end_tree(proc, job)

    t = threading.Thread(target=copy, daemon=True)
    t.start()
    while proc.poll() is None:
        if time.monotonic() - start > limit and not state["ended"]:
            state["ended"] = "limit"
            end_tree(proc, job)
            break
        by = _stop_asked(spec)
        if by and not state["ended"]:
            state["ended"], res["by"] = "stopped", by
            end_tree(proc, job)
            break
        time.sleep(0.1)
    try:
        proc.wait(timeout=15)
    except (OSError, subprocess.SubprocessError):
        pass
    end_leftovers(proc, job)                       # whatever the program left running is ended with it
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
        res = {"code": None, "ended": "", "secs": 0.0, "error": f"Joe hit a problem running it ({e})", "by": ""}
    try:
        from . import devprojects
        how = devprojects.how_it_ended(res, spec)
        if spec.get("last"):                       # what Joe's window shows once the run is over
            devprojects.write_last(spec["last"], spec.get("info") or {}, how, res, Path(spec["log"]))
        devprojects.note_run(Path(spec["runs"]), spec["when"], spec["what"], how, res["secs"])
    except Exception:                              # noqa: BLE001
        pass
    tmp = Path(spec["result"] + ".tmp")
    tmp.write_text(json.dumps(res), encoding="utf-8")
    os.replace(tmp, spec["result"])
    for p in (spec.get("prog"), spec.get("stop"), spec.get("lock"), str(spec_path)):   # the "running" note goes last, once the result is there
        try:
            if p:
                os.unlink(p)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
