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
     outside the box folder (reading Python's own library is allowed), every kind of network
     connection, starting any other program, loading system libraries (ctypes), the Windows
     registry, and killing other programs.
  3. LIMITS from the computer itself: a time limit (the run is killed, with everything it started),
     a memory limit (Linux: rlimit; Windows: a Job Object, which also forbids starting a second
     program and dies with Joe; Mac: where the system allows), a file-size limit, a cap on how much
     it may print.
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

Python only, for now. Pure functions around one subprocess call; tests/test_codebox.py tries each
fence for real.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

TIME_S = 60                 # one test run, seconds
MEMORY_MB = 768
FILE_MB = 20                # the biggest file the code may write
MAX_FILES = 40              # files of one task
MAX_FILE_CHARS = 400_000
OUT_CHARS = 30_000          # of what it printed, kept
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
    import io, json, runpy, traceback, time, unittest, sysconfig
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
        if lim(resource.RLIMIT_AS, mem_mb * 1024 * 1024):
            fence.append("memory limit")
        lim(resource.RLIMIT_CPU, cpu_s)
        lim(resource.RLIMIT_FSIZE, file_mb * 1024 * 1024)
        lim(resource.RLIMIT_CORE, 0)
    except ImportError:
        pass
    # wait for Joe's "go" (on Windows he fences this program first); the word after it marks the verdict
    # line, so the task's code can't print a made-up verdict of its own (it never sees the word)
    mark = (sys.stdin.readline().split() + ["", ""])[1]
    # Python's own library is the only thing outside the box that may be read: the folders Python itself
    # put on its path (isolated mode: no user or site packages), not the rest of the disk
    roots = {os.path.realpath(p) for p in list(sys.path) + [sysconfig.get_paths().get("stdlib") or "",
                                                            sysconfig.get_paths().get("platstdlib") or "",
                                                            os.path.join(sys.base_prefix, "DLLs")]
             if p and "site-packages" not in p and "dist-packages" not in p}
    roots = tuple(sorted(r for r in roots if r and r != os.path.realpath(os.sep) and r != box))
    sep = os.sep
    real, isint = os.path.realpath, lambda p: isinstance(p, int)
    def inside(p, base):
        return p == base or p.startswith(base.rstrip(sep) + sep)
    def where(p):
        if isinstance(p, bytes):
            p = os.fsdecode(p)
        return real(os.path.join(box, os.fspath(p)))
    def may_read(p):
        if isint(p) or p is None:
            return
        q = where(p)
        if inside(q, box) or any(inside(q, r) for r in roots):
            return
        raise PermissionError("the box: this code may only read its own files (not " + str(p)[:120] + ")")
    def may_write(p):
        if isint(p) or p is None:
            return
        q = where(p)
        if inside(q, box):
            return
        raise PermissionError("the box: this code may only write inside its own folder (not " + str(p)[:120] + ")")
    NEVER = ("socket.", "subprocess.", "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.fork",
             "os.forkpty", "os.startfile", "os.kill", "os.killpg", "os.add_dll_directory", "ctypes.",
             "winreg.", "webbrowser.", "urllib.Request", "http.client.", "ftplib.", "smtplib.", "poplib.",
             "imaplib.", "nntplib.", "telnetlib.", "pty.spawn", "_winapi.CreateProcess",
             "_posixsubprocess.fork_exec", "signal.pthread_kill", "syslog.", "msvcrt.locking",
             "cpython._PySys_ClearAuditHooks", "sys.setprofile", "sys.settrace", "os.chroot", "os.setuid",
             "resource.setrlimit", "resource.prlimit", "fcntl.", "mmap.__new__", "os.mkfifo", "os.mknod")
    WRITES = ("os.remove", "os.unlink", "os.rmdir", "os.mkdir", "os.rename", "os.replace", "os.truncate",
              "os.chmod", "os.chown", "os.link", "os.symlink", "os.utime", "shutil.rmtree", "shutil.move",
              "shutil.copyfile", "shutil.copytree", "shutil.copymode", "shutil.copystat", "shutil.chown",
              "shutil.make_archive", "shutil.unpack_archive", "os.chflags", "os.setxattr", "os.removexattr",
              "tempfile.mkstemp", "tempfile.mkdtemp", "os.lchmod", "os.lchown", "pathlib.Path.rename")
    READS = ("os.listdir", "os.scandir", "os.walk", "glob.glob", "glob.glob/2", "os.chdir", "sqlite3.connect",
             "os.getxattr", "os.listxattr", "os.readlink", "pathlib.Path.glob", "pathlib.Path.rglob")
    W = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
    def guard(event, args):
        if event == "open":
            path, mode, flags = (list(args) + [None, None, None])[:3]
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or \
                      (isinstance(flags, int) and flags & W)
            (may_write if writing else may_read)(path)
            return
        for bad in NEVER:
            if event.startswith(bad):
                raise PermissionError("the box: not allowed in here (" + event + "): no network, no other "
                                      "programs, no system libraries")
        if event in WRITES:
            for a in args[:2]:
                if isinstance(a, (str, bytes, os.PathLike)):
                    may_write(a)
            return
        if event in READS:
            a = args[0] if args else None
            if isinstance(a, (str, bytes, os.PathLike)) and str(a) != ":memory:":
                (may_write if event == "sqlite3.connect" else may_read)(a)
            return
        if event == "import" and args and str(args[0]).split(".")[0] in ("ctypes", "_ctypes", "winreg", "_winreg"):
            raise ImportError("the box: " + str(args[0]) + " can't be used in here")
    os.chdir(box)
    sys.path[:] = [box] + [p for p in sys.path if p and any(inside(real(p), r) for r in roots)
                           and "site-packages" not in p and "dist-packages" not in p]
    out = {"passed": 0, "failed": 0, "tests": [], "fence": fence}
    def note(name, ok, why=""):
        out["tests"].append({"name": str(name)[:120], "ok": bool(ok), "why": str(why)[-1500:]})
        out["passed" if ok else "failed"] += 1
    sys.addaudithook(guard)                   # from here on the fence is up, for good
    t0 = time.time()
    try:
        ns = runpy.run_path(os.path.join(box, test), run_name="__box__")
    except SystemExit as e:
        ns = None
        note("(the test file)", e.code in (0, None), "" if e.code in (0, None) else "it exited with " + repr(e.code))
    except BaseException:
        ns = None
        note("(loading the test file)", False, traceback.format_exc(limit=8))
    if ns is not None:
        cases = [v for v in ns.values() if isinstance(v, type) and issubclass(v, unittest.TestCase)
                 and v is not unittest.TestCase and v.__module__ in ("__box__", None)]
        funcs = [(k, v) for k, v in ns.items() if k.startswith("test_") and callable(v) and not isinstance(v, type)]
        for k, fn in funcs:
            try:
                fn()
                note(k, True)
            except BaseException as e:
                if isinstance(e, KeyboardInterrupt):
                    raise
                note(k, False, traceback.format_exc(limit=6))
        for case in cases:
            suite = unittest.defaultTestLoader.loadTestsFromTestCase(case)
            ids = [t.id() for t in suite]           # (a suite forgets its tests once it has run them)
            res = unittest.TestResult()
            suite.run(res)
            bad = {}
            for t, tb in list(res.failures) + list(res.errors):
                bad[t.id() if hasattr(t, "id") else str(t)] = tb
            skipped = {t.id() for t, _ in res.skipped if hasattr(t, "id")}
            for tid in ids:
                short = tid.split(".", 1)[-1] if tid.startswith("__box__.") else tid
                if tid in bad:
                    note(short, False, bad.pop(tid))
                elif tid not in skipped:
                    note(short, True)
            for tid, tb in bad.items():             # setUpClass and the like
                note(tid, False, tb)
    out["seconds"] = round(time.time() - t0, 2)
    sys.stdout.flush(); sys.stderr.flush()
    sys.__stdout__.write("\n" + "@@BOX " + mark + " " + json.dumps(out) + "\n")
    sys.__stdout__.flush()
    os._exit(0 if out["failed"] == 0 and out["passed"] > 0 else 1)
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
    no test in it would "pass" without checking anything."""
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


def run(files: dict, test: str, timeout: float = TIME_S, memory_mb: int = MEMORY_MB) -> Result:
    """Run the test file `test` (one of `files`: {name: text}) in a fresh box. Never raises."""
    res = Result()
    files, problem = clean_files(files)
    if problem:
        res.why = problem
        return res
    if test not in files:
        res.why = f"the test file {test} isn't among the task's files"
        return res
    if not has_real_test(files[test]):
        res.why = (f"{test} has no test in it (it needs at least one 'def test_...():' with an assert, or a "
                   "unittest.TestCase)")
        return res
    timeout = max(2.0, min(float(timeout), 900.0))
    memory_mb = max(128, min(int(memory_mb), 8192))
    top = Path(tempfile.mkdtemp(prefix="joe-box-"))
    job = None
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
        res.fence = ["its own empty folder", "file, network and program guard"]
        if wrap:
            res.fence.append("no network from the system (" + Path(wrap[0]).name + ")")
        if os.name == "nt":
            job, label = _windows_job(proc, memory_mb)
            if label:
                res.fence.append(label)
        import secrets
        word = secrets.token_hex(12)
        mark = f"{MARK}{word} "
        try:
            raw, _ = proc.communicate(f"go {word}\n".encode(), timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill(proc)
            try:
                raw, _ = proc.communicate(timeout=5)
            except (subprocess.SubprocessError, OSError):
                raw = b""
            res.why = f"it ran longer than {int(timeout)} seconds and was stopped (an endless loop?)"
            res.output = _tail(raw)
            res.seconds = time.monotonic() - t0
            res.fence.append("time limit")
            return res
        res.seconds = time.monotonic() - t0
        res.fence.append("time limit")
        text = raw.decode("utf-8", "replace")
        verdict = None
        for line in reversed(text.splitlines()):
            if line.startswith(mark):
                try:
                    verdict = json.loads(line[len(mark):])
                except ValueError:
                    verdict = None
                break
        res.output = _tail(text.split("\n" + mark)[0].encode("utf-8", "replace"))
        if not isinstance(verdict, dict):
            res.why = ("it used more memory than the box allows and was stopped" if _looks_like_memory(text, proc.returncode)
                       else "it stopped without finishing its tests" + (f" (exit code {proc.returncode})" if proc.returncode else ""))
            return res
        res.ran = True
        res.tests = [t for t in verdict.get("tests") or [] if isinstance(t, dict)][:200]
        for f in verdict.get("fence") or []:
            if isinstance(f, str) and f not in res.fence and not any(f in x for x in res.fence):
                res.fence.append(f)
        ok, bad = res.counts
        res.passed = bad == 0 and ok > 0
        if not res.passed:
            res.why = "no test ran" if not res.tests else f"{bad} of {ok + bad} test(s) failed"
        return res
    finally:
        if job:
            try:
                import ctypes
                ctypes.WinDLL("kernel32").CloseHandle(job)
            except Exception:                           # noqa: BLE001
                pass
        shutil.rmtree(top, ignore_errors=True)


def _tail(raw: bytes) -> str:
    text = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
    return text if len(text) <= OUT_CHARS else "...(the start was cut)...\n" + text[-OUT_CHARS:]


def _looks_like_memory(text: str, code) -> bool:
    return "MemoryError" in text[-4000:] or code in (-9, 137, -11, 139, 0xC0000017, 0xC00000FD - (1 << 32))


def describe(fence: list) -> str:
    return "; ".join(fence) if fence else "none"
