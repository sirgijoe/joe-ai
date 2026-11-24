"""The Tester's box (2.4, Joe-AiGent): the ONE place where code that Joe wrote is ever run.

Joseph's rule (2026-11-12): Joe may write code, but the risk is in RUNNING it, so only the Tester
runs code, and only in here: no network, only the task's own files in, only the result text out,
time and memory caps. A task is done when its test passes in the box.

What the box is. A second Python (the same one Joe runs on, nothing to install) started for one
test run and thrown away afterwards, fenced several ways at once:

  1. ITS OWN EMPTY FOLDER, outside the Joe folder, holding only the files of this one task. It is
     deleted after the run. The code never sees the Joe folder, the person's files or their settings.
  2. A GUARD INSIDE THAT PYTHON (an "audit hook", put in before any of the task's code is loaded;
     it cannot be taken out again). It refuses, with a plain error: opening or changing any file
     outside the box folder (reading Python's own library is allowed, writing to it is not),
     changing folder to anywhere outside the box, folder handles (dir_fd), SQLite reaching outside
     the box (ATTACH, VACUUM INTO, "file:" names, extensions), named pipes, every kind of network
     connection, starting any other program, loading system libraries (ctypes), the Windows
     registry, and killing other programs.
  3. LIMITS: a time limit (the run is killed, with everything it started); a memory limit (Linux:
     rlimit; Windows: a Job Object, which also forbids starting a second program and dies with Joe;
     Mac: the system has no working limit of its own, so Joe WATCHES the box's memory from outside,
     about ten times a second, and kills it when it goes over: slower than a limit from the system,
     a quick grab can get past one look); a per-file size limit (Linux and Mac only: Windows has
     none); a total disk limit, on every system (Joe adds up the box folder about four times a
     second and stops the box past DISK_MB or DISK_FILES: a fast writer gets up to a quarter
     second's writing past it); an output limit (Joe reads what it prints with a budget of his own,
     holds on to only the last part, and stops the box past PRINT_MB).
  4. NO NETWORK FROM THE SYSTEM where the system offers it without an administrator password:
     Linux "unshare" (its own empty network), Mac "sandbox-exec". On Windows there is no such
     switch without administrator rights, so there the guard (2) is what stops the network.
  5. A BARE START: Python's isolated mode (no user packages, no environment settings), an almost
     empty environment (no keys, no tokens, no PATH of the person's programs), only Python's own
     library on the path.

What it is NOT (said plainly, the design rule): the guard in (2) is a strong fence against code
that goes wrong or does something it shouldn't have, which is what a writing model produces. It is
not a vault against a determined attacker who writes code on purpose to break out of Python; that
needs a real sandbox (the WebAssembly box in NEXT_STEPS.md is the planned next step). So the box is
only ever given code Joe's own Coder wrote for the owner's job, never code from a web page or a
file, and the ability is off until the owner has read its screen and said yes (agents.ABILITIES).
Known limits against code written ON PURPOSE to get out (none of these happen by accident): it can
find the verdict word in the runner's memory and fake a verdict; it can reach the guard's insides
(or the functions Python's own realpath uses) and change them; it can call the low-level twins of
what the box takes away (posix._exit, posix.mkfifo); it can switch SQLite's fence back off on its
own connection (set_authorizer, setlimit); it can look at whether outside files exist (os.stat); on
Linux it can signal Joe's own programs through a pidfd; on Windows _winapi is not fenced.

Python only, for now. Pure functions around one subprocess call; tests/test_codebox.py tries each
fence for real.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

TIME_S = 60                 # one test run, seconds
MEMORY_MB = 768
FILE_MB = 20                # the biggest file the code may write
MAX_FILES = 40              # files of one task
MAX_FILE_CHARS = 400_000
OUT_CHARS = 30_000          # of what it printed, kept for the Coder
PRINT_MB = 6                # more printed than this and the box is stopped (Joe never holds more than this)
KEEP_BYTES = 3 << 20        # the last part of what it printed that Joe holds on to (the verdict line comes last)
DISK_MB = 200               # all the box's files together
DISK_FILES = 5000           # and how many there may be
DISK_EVERY_S = 0.25         # how often Joe adds them up
OUT_LABEL = f"output limit ({PRINT_MB} MB)"
MARK = "@@BOX "             # the line the box prints its verdict on
NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,60}\.(?:py|txt|json|csv|md)")
RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10)),
            "boot", "tmp"}       # Windows device names, and the box's own names
TEST_HAS = re.compile(r"^\s*(?:def\s+test_\w+\s*\(|class\s+\w+\s*\(\s*(?:unittest\.)?TestCase\s*\))", re.M)

# The program that runs inside the box. It is kept in a folder of its own that the guard doesn't let
# the task's code write to. Order matters: limits, then the guard, then (only then) the task's code.
BOOT = r'''
import sys, os
def _main():
    import io, json, runpy, traceback, time, unittest, sysconfig, inspect, warnings, shutil, threading
    box = os.path.realpath(sys.argv[1]); test = sys.argv[2]
    mem_mb = int(sys.argv[3]); cpu_s = int(sys.argv[4]); file_mb = int(sys.argv[5])
    fence = []
    try:
        import resource
        def lim(what, soft):
            try:
                hard = resource.getrlimit(what)[1]
                soft = soft if hard == resource.RLIM_INFINITY else min(soft, hard)
                resource.setrlimit(what, (soft, soft))
                return True
            except (ValueError, OSError):
                return False
        # a Mac takes this limit (or refuses it) and doesn't keep to it: there Joe watches from outside
        if lim(resource.RLIMIT_AS, mem_mb * 1024 * 1024) and sys.platform != "darwin":
            fence.append("memory limit")
        lim(resource.RLIMIT_CPU, cpu_s)
        if lim(resource.RLIMIT_FSIZE, file_mb * 1024 * 1024):
            fence.append("file-size limit (" + str(file_mb) + " MB a file)")
        lim(resource.RLIMIT_CORE, 0)
    except ImportError:
        pass
    # wait for Joe's "go" (on Windows he fences this program first); the word after it marks the verdict
    # line, so the task's code can't fake a verdict BY ACCIDENT (code written on purpose can find the word:
    # a known limit, see the top of codebox.py)
    mark = (sys.stdin.readline().split() + ["", ""])[1]
    # Python's own library is the only thing outside the box that may be read: the folders Python itself
    # put on its path (isolated mode: no user or site packages), not the rest of the disk
    roots = {os.path.realpath(p) for p in list(sys.path) + [sysconfig.get_paths().get("stdlib") or "",
                                                            sysconfig.get_paths().get("platstdlib") or "",
                                                            os.path.join(sys.base_prefix, "DLLs")]
             if p and "site-packages" not in p and "dist-packages" not in p}
    roots = tuple(sorted(r for r in roots if r and r != os.path.realpath(os.sep) and r != box))
    sep = os.sep
    # the guard's own copies of everything it uses, taken now: code that later replaces os.path.join,
    # isinstance, any... (a careless mock, say) doesn't switch the guard off by accident
    real, join, getcwd, isdir = os.path.realpath, os.path.join, os.getcwd, os.path.isdir
    fsdecode, fspath, PathLike = os.fsdecode, os.fspath, os.PathLike
    _isinstance, _any, _str, _int, _bytes, _list, _len, _getattr = isinstance, any, str, int, bytes, list, len, getattr
    NoWay = PermissionError
    def inside(p, base):
        return p == base or p.startswith(base.rstrip(sep) + sep)
    def where(p):
        """The real place a name points to: a relative name counts from the real current folder."""
        if _isinstance(p, _bytes):
            p = fsdecode(p)
        try:
            here = getcwd()
        except OSError:
            raise NoWay("the box: its current folder is gone") from None
        return real(join(here, fspath(p)))
    def may_read(p):
        if _isinstance(p, _int) or p is None:
            return
        q = where(p)
        if inside(q, box) or _any(inside(q, r) for r in roots):
            return
        raise NoWay("the box: this code may only read its own files (not " + _str(p)[:120] + ")")
    def may_write(p):
        if _isinstance(p, _int) or p is None:
            return
        if inside(where(p), box):
            return
        raise NoWay("the box: this code may only write inside its own folder (not " + _str(p)[:120] + ")")
    def may_go(p):
        if not _isinstance(p, _int) and inside(where(p), box):
            return
        raise NoWay("the box: this code may only change folder inside its own folder (not " + _str(p)[:120] + ")")
    def may_sql(name):
        if _isinstance(name, _bytes):
            name = fsdecode(name)
        name = fspath(name)
        if name in (":memory:", ""):
            return
        if name[:5].lower() == "file:":         # a SQLite "file:" name (uri=True): only an in-memory one
            if name[5:].split("?")[0].split("#")[0] in (":memory:", ""):
                return
            raise NoWay("the box: SQLite 'file:' names can't be used in here; use a plain file name")
        may_write(name)
    # SQLite's own fence, put on every connection as it is made: no ATTACH (VACUUM INTO attaches too),
    # no moving its temporary files. (Code that switches it off again on purpose: a known limit.)
    def sql_fence(action, a1, a2, db, trigger, _str=str):
        if action in (24, 25):                  # SQLITE_ATTACH, SQLITE_DETACH
            return 1                            # SQLITE_DENY
        if action == 19 and _str(a1).lower() in ("temp_store_directory", "data_store_directory"):   # PRAGMA
            return 1
        return 0                                # SQLITE_OK
    NEVER = ("socket.", "subprocess.", "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.fork",
             "os.forkpty", "os.startfile", "os.kill", "os.killpg", "os.add_dll_directory", "ctypes.",
             "winreg.", "webbrowser.", "urllib.Request", "http.client.", "ftplib.", "smtplib.", "poplib.",
             "imaplib.", "nntplib.", "telnetlib.", "pty.spawn", "_winapi.CreateProcess",
             "_posixsubprocess.fork_exec", "signal.pthread_kill", "syslog.", "msvcrt.locking",
             "cpython._PySys_ClearAuditHooks", "sys.setprofile", "sys.settrace", "os.chroot", "os.setuid",
             "resource.setrlimit", "resource.prlimit", "fcntl.", "mmap.__new__", "os.mkfifo", "os.mknod",
             "sqlite3.enable_load_extension", "sqlite3.load_extension")
    WRITES = ("os.remove", "os.unlink", "os.rmdir", "os.mkdir", "os.rename", "os.replace", "os.truncate",
              "os.chmod", "os.chown", "os.link", "os.symlink", "os.utime", "shutil.rmtree", "shutil.move",
              "shutil.copyfile", "shutil.copytree", "shutil.copymode", "shutil.copystat", "shutil.chown",
              "shutil.make_archive", "shutil.unpack_archive", "os.chflags", "os.setxattr", "os.removexattr",
              "tempfile.mkstemp", "tempfile.mkdtemp", "os.lchmod", "os.lchown", "pathlib.Path.rename")
    READS = ("os.listdir", "os.scandir", "os.walk", "glob.glob", "glob.glob/2",
             "os.getxattr", "os.listxattr", "os.readlink", "pathlib.Path.glob", "pathlib.Path.rglob")
    # where a folder handle (dir_fd) sits in each event's arguments (-1 or None: no handle)
    DIR_FD = {"os.mkdir": (2,), "os.rmdir": (1,), "os.remove": (1,), "os.rename": (2, 3), "os.link": (2, 3),
              "os.symlink": (2,), "os.chmod": (2,), "os.chown": (3,), "os.utime": (3,), "shutil.rmtree": (1,)}
    W = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
    def guard(event, args):
        if event == "open":
            path, mode, flags = (_list(args) + [None, None, None])[:3]
            writing = (_isinstance(mode, _str) and _any(c in mode for c in "wax+")) or \
                      (_isinstance(flags, _int) and flags & W)
            (may_write if writing else may_read)(path)
            # os.open of a folder: its handle (dir_fd) would let later calls name files the guard can't place
            if mode is None and path is not None and not _isinstance(path, _int) and isdir(where(path)):
                raise NoWay("the box: a folder can't be opened like a file in here")
            return
        for bad in NEVER:
            if event.startswith(bad):
                raise NoWay("the box: not allowed in here (" + event + "): no network, no other "
                            "programs, no system libraries")
        for i in DIR_FD.get(event, ()):
            if i < _len(args) and args[i] is not None and args[i] != -1:
                raise NoWay("the box: folder handles (dir_fd) can't be used in here")
        if event in WRITES:
            for a in args[:2]:
                if _isinstance(a, (_str, _bytes, PathLike)):
                    may_write(a)
            return
        if event == "os.chdir":
            may_go(args[0] if args else None)
            return
        if event == "sqlite3.connect":
            may_sql(args[0] if args else "")
            return
        if event == "sqlite3.connect/handle" and not _getattr(making, "ok", False):
            raise NoWay("the box: open SQLite with sqlite3.connect(...) in here")
        if event in READS:
            a = args[0] if args else None
            if _isinstance(a, (_str, _bytes, PathLike)):
                may_read(a)
            return
        if event == "import" and args and _str(args[0]).split(".")[0] in ("ctypes", "_ctypes", "winreg", "_winreg"):
            raise ImportError("the box: " + _str(args[0]) + " can't be used in here")
    os.chdir(box)
    sys.path[:] = [box] + [p for p in sys.path if p and any(inside(real(p), r) for r in roots)
                           and "site-packages" not in p and "dist-packages" not in p]
    out = {"passed": 0, "failed": 0, "tests": [], "fence": fence}
    def note(name, ok, why=""):
        out["passed" if ok else "failed"] += 1
        if len(out["tests"]) < 200:              # (the counts above stay right past 200)
            out["tests"].append({"name": str(name)[:120], "ok": bool(ok), "why": str(why)[-1500:]})
    # what the guard can't see coming, taken away before the task's code loads: named pipes and device
    # files (no audit event), and os._exit (it would end the run with no verdict: now a failed test)
    def no_pipes(*a, **k):
        raise PermissionError("the box: not allowed in here (named pipes and device files)")
    for name in ("mkfifo", "mknod"):
        if hasattr(os, name):
            setattr(os, name, no_pipes)
    _exit = os._exit
    def exit_instead(code=0):
        raise SystemExit(code)
    os._exit = exit_instead
    # SQLite: every connection is made through sqlite3.connect, which puts SQLite's fence on it (the
    # guard refuses one made any other way; a connection can't take the fence while it is being made)
    making = threading.local()
    try:
        import sqlite3
    except ImportError:
        sqlite3 = None
    if sqlite3 is not None:
        plain_connect = sqlite3.connect
        def connect(*a, **k):
            making.ok = True
            try:
                con = plain_connect(*a, **k)
            finally:
                making.ok = False
            con.set_authorizer(sql_fence)
            try:
                con.setlimit(7, 0)              # SQLITE_LIMIT_ATTACHED: no second database at all
            except Exception:
                pass                            # (an older SQLite: the fence above still refuses ATTACH)
            return con
        sqlite3.connect = sqlite3.dbapi2.connect = connect
    # shutil.rmtree works through folder handles where it can; the guard refuses those, so it works by name
    shutil._use_fd_functions = False
    # Python 3.14 picks its way once, when shutil loads (shutil._rmtree_impl), so the switch above no longer
    # reaches it there: tempfile's own clean-up and shutil.rmtree were refused inside the box on Linux and Mac
    if hasattr(shutil, "_rmtree_impl") and hasattr(shutil, "_rmtree_unsafe"):
        shutil._rmtree_impl = shutil._rmtree_unsafe
    NEVER_RAN = ("this test never ran: it is async or a generator (it has 'yield' in it), and the box runs "
                 "plain tests only. Write it as a plain 'def test_...():'")
    def never_runs(fn):
        try:
            return inspect.iscoroutinefunction(fn) or inspect.isgeneratorfunction(fn) or inspect.isasyncgenfunction(fn)
        except Exception:
            return False
    def unran(value):
        if inspect.isawaitable(value) or inspect.isgenerator(value) or inspect.isasyncgen(value):
            try:
                value.close()
            except Exception:
                pass
            return True
        return False
    sys.addaudithook(guard)                   # from here on the fence is up, for good
    t0 = time.time()
    try:
        ns = runpy.run_path(os.path.join(box, test), run_name="__box__")
    except SystemExit as e:
        ns = None
        note("(loading the test file)", False,
             "the code ended the program while it was being loaded (sys.exit or os._exit"
             + ("" if e.code in (0, None) else ", code " + repr(e.code)[:40]) + "); nothing was tested. "
             "A program's own start belongs under  if __name__ == '__main__':")
    except BaseException:
        ns = None
        note("(loading the test file)", False, traceback.format_exc(limit=8))
    if ns is not None:
        cases = [v for v in ns.values() if isinstance(v, type) and issubclass(v, unittest.TestCase)
                 and v is not unittest.TestCase and v.__module__ in ("__box__", None)]
        funcs = [(k, v) for k, v in ns.items() if k.startswith("test_") and callable(v) and not isinstance(v, type)]
        for k, fn in funcs:
            if never_runs(fn):
                note(k, False, NEVER_RAN)
                continue
            try:
                if unran(fn()):
                    note(k, False, NEVER_RAN)
                else:
                    note(k, True)
            except BaseException as e:
                if isinstance(e, KeyboardInterrupt):
                    raise
                note(k, False, traceback.format_exc(limit=6))
        for case in cases:
            suite = unittest.defaultTestLoader.loadTestsFromTestCase(case)
            ids = [t.id() for t in suite]           # (a suite forgets its tests once it has run them)
            never = {t.id() for t in suite if never_runs(getattr(t, getattr(t, "_testMethodName", ""), None))}
            res = unittest.TestResult()
            with warnings.catch_warnings():         # a test that hands back a coroutine: an error, not a pass
                warnings.filterwarnings("error", message="It is deprecated to return a value",
                                        category=DeprecationWarning)
                suite.run(res)
            bad = {}
            for t, tb in list(res.failures) + list(res.errors):
                bad[t.id() if hasattr(t, "id") else str(t)] = tb
            for t in res.unexpectedSuccesses:       # (unittest itself counts these as a failed run)
                bad[t.id()] = "it is marked expectedFailure, but it passed"
            skipped = {t.id() for t, _ in res.skipped if hasattr(t, "id")}
            for tid in ids:
                short = tid.split(".", 1)[-1] if tid.startswith("__box__.") else tid
                if tid in never:
                    bad.pop(tid, None)
                    note(short, False, NEVER_RAN)
                elif tid in bad:
                    note(short, False, bad.pop(tid))
                elif tid not in skipped:
                    note(short, True)
            for tid, tb in bad.items():             # setUpClass and the like
                note(tid, False, tb)
    out["seconds"] = round(time.time() - t0, 2)
    try:
        sys.stdout.flush(); sys.stderr.flush()
    except Exception:
        pass
    sys.__stdout__.write("\n" + "@@BOX " + mark + " " + json.dumps(out) + "\n")
    sys.__stdout__.flush()
    _exit(0 if out["failed"] == 0 and out["passed"] > 0 else 1)
_main()
'''


@dataclass
class Result:
    ran: bool = False           # the box started and gave a verdict (False: no verdict, see why)
    passed: bool = False        # every test passed, and there was at least one
    tests: list = field(default_factory=list)      # [{"name", "ok", "why"}]
    output: str = ""            # what the code printed (cut to OUT_CHARS)
    why: str = ""               # in plain words, when it didn't pass
    seconds: float = 0.0
    fence: list = field(default_factory=list)      # which fences were up for this run

    @property
    def counts(self) -> tuple[int, int]:
        ok = sum(1 for t in self.tests if t.get("ok"))
        return ok, len(self.tests) - ok

    def summary(self) -> str:
        ok, bad = self.counts
        if not self.ran:
            return f"no verdict: {self.why}"
        return (f"{ok} test(s) passed" if self.passed else f"{bad} of {ok + bad} test(s) failed") + \
            (f" in {self.seconds:.1f} s" if self.seconds else "")

    def failures(self, limit: int = 2500) -> str:
        """What went wrong, for the Coder's next try."""
        parts = [f"{t['name']}: {t.get('why', '')}".strip() for t in self.tests if not t.get("ok")]
        text = "\n\n".join(parts) or self.why or self.output[-limit:]
        return text[-limit:]


def python_exe() -> str:
    """The Python the box runs on: the one Joe runs on (python.exe beside pythonw.exe on Windows)."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and exe.with_name("python.exe").is_file():
        return str(exe.with_name("python.exe"))
    return str(exe)


def clean_files(files: dict) -> tuple[dict[str, str], str]:
    """The files that may go into the box: plain names, text, not too many or too big. -> (files, problem)."""
    out: dict[str, str] = {}
    if not isinstance(files, dict) or not files:
        return {}, "no files to test"
    if len(files) > MAX_FILES:
        return {}, f"too many files for one task ({len(files)}; {MAX_FILES} at most)"
    for name, text in files.items():
        name = str(name)
        if not NAME.fullmatch(name) or name.split(".")[0].lower() in RESERVED:
            return {}, f"'{name[:60]}' isn't a plain file name (letters, digits and _ then .py, .txt, .json, .csv or .md)"
        if name.endswith(".py") and shadows_python(name[:-3]):
            return {}, (f"{name} has the same name as a part of Python itself; a program by that name would "
                        "be loaded instead of Python's own")
        if not isinstance(text, str) or len(text) > MAX_FILE_CHARS:
            return {}, f"{name} is too big for the box"
        if name.lower() in out:
            return {}, f"two files are both called {name}"
        out[name] = text
    return out, ""


def shadows_python(stem: str) -> bool:
    """Would a file called <stem>.py be loaded in place of one of Python's own modules (json.py, random.py...)?"""
    stem = (stem or "").lower()
    names = {m.lower() for m in getattr(sys, "stdlib_module_names", ())} | {"site", "sitecustomize", "usercustomize"}
    return stem in names


def has_real_test(text: str) -> bool:
    """A test file must hold at least one test (def test_...() or a unittest.TestCase): a file with
    no test in it would "pass" without checking anything. (A test passes when it runs without an
    error, so a test with no assert in it passes too: it is the Checker's job to see it checks something.)
    async tests don't count: the box doesn't run them."""
    return bool(TEST_HAS.search(text or ""))


_NONET: list | None = None          # the system's own "no network" wrapper for this computer ([] = none)


def no_network_wrapper() -> list[str]:
    """A command to put in front of the box so the SYSTEM gives it no network (found once, by trying it)."""
    global _NONET
    if _NONET is not None:
        return list(_NONET)
    _NONET = []
    tries = []
    if sys.platform.startswith("linux") and shutil.which("unshare"):
        tries.append([shutil.which("unshare"), "--user", "--map-root-user", "--net"])
    if sys.platform == "darwin" and os.path.exists("/usr/bin/sandbox-exec"):
        tries.append(["/usr/bin/sandbox-exec", "-p", "(version 1)(allow default)(deny network*)"])
    for cmd in tries:
        try:
            r = subprocess.run(cmd + [python_exe(), "-I", "-S", "-c", "print(7)"], capture_output=True, text=True,
                               timeout=20, stdin=subprocess.DEVNULL)
            if r.returncode == 0 and r.stdout.strip() == "7":
                _NONET = cmd
                break
        except (OSError, subprocess.SubprocessError):
            continue
    return list(_NONET)


def _windows_job(proc, memory_mb: int):
    """Windows: put the box in a Job Object (memory cap, no second program, dies with Joe).
    Returns (handle or None, what it's called in the fence list or '')."""
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOperationCount", "WriteOperationCount",
                                                       "OtherOperationCount", "ReadTransferCount",
                                                       "WriteTransferCount", "OtherTransferCount")]

        class EXT(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        job = k32.CreateJobObjectW(None, None)
        if not job:
            return None, ""
        info = EXT()
        # ACTIVE_PROCESS 0x8 | PROCESS_MEMORY 0x100 | DIE_ON_UNHANDLED_EXCEPTION 0x400 | KILL_ON_JOB_CLOSE 0x2000
        info.BasicLimitInformation.LimitFlags = 0x8 | 0x100 | 0x400 | 0x2000
        info.BasicLimitInformation.ActiveProcessLimit = 1
        info.ProcessMemoryLimit = memory_mb * 1024 * 1024
        if not k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            k32.CloseHandle(job)
            return None, ""
        if not k32.AssignProcessToJobObject(job, wintypes.HANDLE(int(proc._handle))):
            k32.CloseHandle(job)
            return None, ""
        return job, "memory limit and no second program (Windows Job Object)"
    except Exception:                                   # noqa: BLE001 (no Job Object: the other fences still stand)
        return None, ""


WATCH_EVERY_S = 0.1          # how often the box's memory is looked at, where Joe has to watch it himself
WATCH_LABEL = "memory limit (watched from outside)"


def watch_needed() -> bool:
    """Does Joe have to watch the box's memory himself? Linux has a limit of its own (rlimit) and
    Windows the Job Object; a Mac (and anything else) has neither."""
    return os.name != "nt" and not sys.platform.startswith("linux")


WATCH_MISSES = 5            # "ps" not answering this many times in a row: the watch is given up, and not claimed


def ps_program() -> str | None:
    """The system's own "ps", at its usual place first (not whatever Joe's PATH finds first). None = none."""
    for p in ("/bin/ps", "/usr/bin/ps"):
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return shutil.which("ps")


def group_memory_mb(pgid: int) -> float | None:
    """The memory in use right now (MB) by every program in the box's group, asked of the system's
    own "ps". None = couldn't be read. 0 = nothing of the box is running any more."""
    ps = ps_program()
    if not ps:
        return None
    try:
        r = subprocess.run([ps, "-A", "-o", "pgid=,rss="], capture_output=True, text=True, timeout=5,
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    kb = 0
    for line in r.stdout.splitlines():
        part = line.split()
        if len(part) == 2 and part[0] == str(pgid) and part[1].isdigit():
            kb += int(part[1])
    return kb / 1024


class MemoryWatch:
    """Looks at the box's memory from outside and kills the box when it is over the limit.
    For systems with no memory limit of their own (a Mac). The box is its own process group
    (start_new_session), so everything it started is counted and killed with it."""

    def __init__(self, proc, memory_mb: int, every: float = WATCH_EVERY_S):
        self.proc, self.limit, self.every = proc, memory_mb, every
        self.hit = False            # the box went over and was killed
        self.lost = False           # "ps" stopped answering partway: the box was no longer watched
        self.peak = 0.0             # the most seen, MB
        self._stop = threading.Event()

    def start(self) -> bool:
        """False = this computer can't be asked (no "ps"): no watch, and the fence list won't claim one."""
        if group_memory_mb(self.proc.pid) is None:
            return False
        threading.Thread(target=self._loop, daemon=True, name="joe-box-memory").start()
        return True

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        misses = 0
        while not self._stop.wait(self.every):
            if self.proc.poll() is not None:
                return
            mb = group_memory_mb(self.proc.pid)
            if mb is None:
                misses += 1
                if misses >= WATCH_MISSES:      # no more answers: stop, and stop claiming the watch
                    self.lost = True
                    return
                continue
            misses = 0
            self.peak = max(self.peak, mb)
            if mb > self.limit:
                self.hit = True
                _kill(self.proc)
                return


class DiskWatch:
    """Adds up the box folder from outside, about four times a second, and kills the box when all its files
    together are over the limit (or there are too many of them). Every system, Windows too."""

    def __init__(self, folder, proc, limit_mb: int, max_files: int, every: float = DISK_EVERY_S):
        self.folder, self.proc, self.every = str(folder), proc, every
        self.limit, self.max_files = limit_mb * 1024 * 1024, max_files
        self.hit = False            # the box went over and was killed
        self._stop = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._loop, daemon=True, name="joe-box-disk").start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self.every):
            if self.proc.poll() is not None:
                return
            if self.over():
                self.hit = True
                _kill(self.proc)
                return

    def over(self) -> bool:
        """Are the box's files, all together, too big or too many? (Stops counting as soon as they are.)"""
        total, count, todo = 0, 0, [self.folder]
        while todo:
            d = todo.pop()
            try:
                it = os.scandir(d)
            except PermissionError:             # a folder the code locked: it is Joe's own, open it again
                try:
                    os.chmod(d, stat.S_IRWXU)
                    it = os.scandir(d)
                except OSError:
                    continue
            except OSError:
                continue
            with it:
                for e in it:
                    count += 1
                    try:
                        if e.is_dir(follow_symlinks=False):
                            todo.append(e.path)
                        else:
                            total += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        pass
                    if total > self.limit or count > self.max_files:
                        return True
        return False


class _Reader(threading.Thread):
    """Reads what the box prints, as it comes, keeping only the last KEEP_BYTES of it: past PRINT_MB in
    all, the box is stopped. (Not proc.communicate(): that keeps everything in Joe's memory.) A thread,
    because Windows can't wait on a pipe any other way."""

    def __init__(self, proc):
        super().__init__(daemon=True, name="joe-box-output")
        self.proc, self.kept, self.total, self.over = proc, bytearray(), 0, False

    def run(self) -> None:
        pipe = self.proc.stdout
        read = getattr(pipe, "read1", pipe.read)
        while True:
            try:
                chunk = read(65536)
            except (OSError, ValueError):
                break
            if not chunk:
                break
            self.total += len(chunk)
            self.kept += chunk
            if len(self.kept) > 2 * KEEP_BYTES:
                del self.kept[:-KEEP_BYTES]
            if self.total > PRINT_MB * 1024 * 1024:
                self.over = True
                _kill(self.proc)
                break

    def text(self) -> tuple[str, bool]:
        """What was kept, and whether the start of it was cut off."""
        kept = bytes(self.kept[-KEEP_BYTES:])
        return kept.decode("utf-8", "replace"), self.total > len(kept)


def _kill(proc) -> None:
    try:
        if os.name == "nt":
            proc.kill()
        else:
            import signal
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        try:
            proc.kill()
        except OSError:
            pass


def remove_folder(path) -> None:
    """Delete a box folder, even when the code left read-only files or locked folders in it. Never raises."""
    def unlock(func, p, _err):              # (onexc on 3.12+, onerror before: the third argument differs, unused)
        try:
            os.chmod(os.path.dirname(p), stat.S_IRWXU)
            if not os.path.islink(p):         # (never through a link: that could change a file outside)
                os.chmod(p, stat.S_IRWXU)
            if func in (os.unlink, os.remove, os.rmdir):
                func(p)
        except Exception:                   # noqa: BLE001 (the next round tries again)
            pass
    for _ in range(4):                      # each round gets one more level of locked folders open
        try:
            if not os.path.lexists(path):
                return
            if sys.version_info >= (3, 12):
                shutil.rmtree(path, onexc=unlock)
            else:
                shutil.rmtree(path, onerror=unlock)
        except Exception:                   # noqa: BLE001
            pass


def sweep_old_boxes(max_age_s: float = 86400) -> int:
    """Delete box folders left in the temp folder for more than a day (Joe was killed mid-run, say).
    Only folders called joe-box-... that belong to this user. Never raises. -> how many."""
    n = 0
    try:
        now, uid = time.time(), (os.getuid() if hasattr(os, "getuid") else None)
        with os.scandir(tempfile.gettempdir()) as it:
            for e in it:
                if not e.name.startswith("joe-box-"):
                    continue
                try:
                    st = e.stat(follow_symlinks=False)
                    if not e.is_dir(follow_symlinks=False) or (uid is not None and st.st_uid != uid) \
                            or now - st.st_mtime < max_age_s:
                        continue
                except OSError:
                    continue
                remove_folder(e.path)
                n += 1
    except Exception:                       # noqa: BLE001
        pass
    return n


_SWEPT = [float("-inf")]                    # when the temp folder was last swept (once an hour is plenty)


def run(files: dict, test: str, timeout: float = TIME_S, memory_mb: int = MEMORY_MB,
        disk_mb: int = DISK_MB) -> Result:
    """Run the test file `test` (one of `files`: {name: text}) in a fresh box. Never raises."""
    try:
        return _run(files, test, timeout, memory_mb, disk_mb)
    except Exception as e:                  # noqa: BLE001 (a box that couldn't run is a "no verdict", never a crash)
        return Result(why=f"the box couldn't run ({type(e).__name__}: {str(e)[:200]})")


def _run(files, test, timeout, memory_mb, disk_mb) -> Result:
    res = Result()
    try:
        if time.monotonic() - _SWEPT[0] > 3600:
            _SWEPT[0] = time.monotonic()
            sweep_old_boxes()
    except Exception:                       # noqa: BLE001
        pass
    files, problem = clean_files(files)
    if problem:
        res.why = problem
        return res
    if test not in files:
        res.why = f"the test file {test} isn't among the task's files"
        return res
    if not has_real_test(files[test]):
        res.why = (f"{test} has no test in it (it needs at least one plain 'def test_...():' or a "
                   "unittest.TestCase; async tests can't be run in the box)")
        return res
    timeout = max(2.0, min(float(timeout), 900.0))
    memory_mb = max(128, min(int(memory_mb), 8192))
    disk_mb = max(1, min(int(disk_mb), 100_000))
    top = Path(tempfile.mkdtemp(prefix="joe-box-"))
    job = None
    watch = None
    disk = None
    proc = None
    reader = None
    try:
        box, boot = top / "task", top / "boot"
        box.mkdir()
        boot.mkdir()
        (box / "tmp").mkdir()
        for name, text in files.items():
            (box / name).write_text(text, encoding="utf-8")
        (boot / "boot.py").write_text(BOOT, encoding="utf-8")
        env = {"PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0",
               "TMPDIR": str(box / "tmp"), "TEMP": str(box / "tmp"), "TMP": str(box / "tmp"),
               "HOME": str(box), "USERPROFILE": str(box), "LANG": "C.UTF-8"}
        for keep in ("SYSTEMROOT", "WINDIR", "SYSTEMDRIVE"):          # Windows can't start Python without these
            if os.environ.get(keep):
                env[keep] = os.environ[keep]
        wrap = no_network_wrapper()
        cmd = wrap + [python_exe(), "-I", "-S", "-B", "-X", "utf8", str(boot / "boot.py"), str(box), test,
                      str(memory_mb), str(int(timeout) + 5), str(FILE_MB)]
        kw: dict = {"creationflags": 0x08000000 | 0x00000200} if os.name == "nt" else {"start_new_session": True}
        t0 = time.monotonic()
        try:
            proc = subprocess.Popen(cmd, cwd=str(box), env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, **kw)
        except OSError as e:
            res.why = f"the box couldn't start ({e})"
            return res
        res.fence = ["its own empty folder", "file, network and program guard", "time limit", OUT_LABEL,
                     f"disk limit ({disk_mb} MB in all, watched from outside)"]
        if wrap:
            res.fence.append("no network from the system (" + Path(wrap[0]).name + ")")
        if os.name == "nt":
            job, label = _windows_job(proc, memory_mb)       # before "go": the box waits for it
            if label:
                res.fence.append(label)
        elif watch_needed():
            watch = MemoryWatch(proc, memory_mb)
            if watch.start():
                res.fence.append(WATCH_LABEL)
            else:
                watch = None
        disk = DiskWatch(box, proc, disk_mb, DISK_FILES)
        disk.start()
        reader = _Reader(proc)
        reader.start()
        import secrets
        word = secrets.token_hex(12)
        mark = f"{MARK}{word} "
        try:
            proc.stdin.write(f"go {word}\n".encode())
            proc.stdin.flush()
        except (OSError, ValueError):
            pass                                            # (it already ended: there will be no verdict)
        try:
            proc.stdin.close()
        except (OSError, ValueError):
            pass
        # the time limit: the reader ends when the box's output closes (it ended, or was stopped)
        late = False
        reader.join(timeout)
        if reader.is_alive():
            late = True
        else:
            try:
                proc.wait(timeout=max(0.5, t0 + timeout - time.monotonic()))
            except subprocess.TimeoutExpired:
                late = True
        if late:
            _kill(proc)
            reader.join(5)
        try:
            proc.wait(timeout=5)
        except (subprocess.SubprocessError, OSError):
            pass
        res.seconds = time.monotonic() - t0
        text, cut = reader.text()
        verdict = None
        for line in reversed(text.splitlines()):
            if line.startswith(mark):
                try:
                    verdict = json.loads(line[len(mark):])
                except ValueError:
                    verdict = None
                break
        res.output = _tail(text.split("\n" + mark)[0], cut)
        if reader.over:
            res.why = f"it printed far too much (more than {PRINT_MB} MB) and was stopped"
            return res
        if disk.hit:
            res.why = (f"it wrote too many or too big files and was stopped (more than {disk_mb} MB "
                       f"or {DISK_FILES} files)")
            return res
        if late:
            res.why = f"it ran longer than {int(timeout)} seconds and was stopped (an endless loop?)"
            return res
        if not isinstance(verdict, dict):
            over = (watch is not None and watch.hit) or _looks_like_memory(text, proc.returncode)
            if over:
                res.why = "it used more memory than the box allows and was stopped"
            elif proc.returncode == 0:
                res.why = ("it ended before giving a verdict (the code itself ended the program); "
                           "nothing was counted as passed")
            else:
                res.why = "it stopped without finishing its tests" + \
                    (f" (exit code {proc.returncode})" if proc.returncode else "")
            return res
        res.ran = True
        res.tests = [t for t in verdict.get("tests") or [] if isinstance(t, dict)][:200]
        for f in verdict.get("fence") or []:
            if isinstance(f, str) and f not in res.fence and not any(f in x for x in res.fence):
                res.fence.append(f)
        ok, bad = res.counts
        try:                                    # past 200 tests the list is cut, the counts are not
            ok, bad = max(ok, int(verdict.get("passed") or 0)), max(bad, int(verdict.get("failed") or 0))
        except (TypeError, ValueError):
            pass
        res.passed = bad == 0 and ok > 0
        if not res.passed:
            res.why = "no test ran" if not ok + bad else f"{bad} of {ok + bad} test(s) failed"
        return res
    finally:
        if proc is not None and proc.poll() is None:        # (never leave it running)
            _kill(proc)
        for w in (watch, disk):
            if w:
                w.stop()
        if watch is not None and watch.lost and WATCH_LABEL in res.fence:
            res.fence.remove(WATCH_LABEL)                   # "ps" stopped answering: no claim of a watch
        if proc is not None and (reader is None or not reader.is_alive()):
            try:
                proc.stdout.close()
            except (OSError, ValueError):
                pass
        if job:
            try:
                import ctypes
                ctypes.WinDLL("kernel32").CloseHandle(job)
            except Exception:                           # noqa: BLE001
                pass
        remove_folder(top)


def _tail(text: str, cut: bool = False) -> str:
    if len(text) <= OUT_CHARS and not cut:
        return text
    return "...(the start was cut)...\n" + text[-OUT_CHARS:]


def _looks_like_memory(text: str, code) -> bool:
    return "MemoryError" in text[-4000:] or code in (-9, 137, -11, 139, 0xC0000017, 0xC00000FD - (1 << 32))


def describe(fence: list) -> str:
    return "; ".join(fence) if fence else "none"
