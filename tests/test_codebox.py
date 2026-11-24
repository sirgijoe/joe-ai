"""The Tester's box (codebox.py): each fence is tried for real, with code that does the forbidden thing."""
import os
import sys
import tempfile
from pathlib import Path

import pytest

from joeai import codebox

GOOD = "def add(a, b):\n    return a + b\n"
TEST = "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n\ndef test_negative():\n    assert add(-1, 1) == 0\n"


def box(test_body, extra=None, **kw):
    files = {"calc.py": GOOD, "test_calc.py": test_body}
    files.update(extra or {})
    return codebox.run(files, "test_calc.py", **{"timeout": 30, **kw})


def blocked(body):
    """Code that tries something forbidden inside a test: the test must fail with the box's own refusal."""
    r = box("def test_it():\n" + "\n".join("    " + line for line in body.splitlines()) + "\n")
    assert r.ran and not r.passed, (r.why, r.output)
    return r.tests[0]["why"]


def test_passing_tests_pass_and_say_which():
    r = box(TEST)
    assert r.ran and r.passed and r.counts == (2, 0), (r.why, r.output)
    assert [t["name"] for t in r.tests] == ["test_add", "test_negative"]
    assert "its own empty folder" in r.fence and "time limit" in r.fence and "passed" in r.summary()


def test_a_failing_test_fails_with_the_reason():
    r = box(TEST + "\ndef test_wrong():\n    assert add(2, 2) == 5, 'two and two'\n")
    assert r.ran and not r.passed and r.counts == (2, 1)
    assert "two and two" in r.failures() and "1 of 3 test(s) failed" in r.summary()


def test_unittest_classes_are_run_too():
    r = box("import unittest\nfrom calc import add\n\nclass T(unittest.TestCase):\n"
            "    def test_ok(self):\n        self.assertEqual(add(1, 1), 2)\n"
            "    def test_bad(self):\n        self.assertEqual(add(1, 1), 3)\n")
    assert r.ran and not r.passed and r.counts == (1, 1)
    assert any(t["name"].endswith("test_bad") and "3" in t["why"] for t in r.tests)


def test_a_test_file_with_no_test_in_it_is_refused():
    r = box("from calc import add\nprint(add(1, 2))\n")
    assert not r.ran and not r.passed and "no test in it" in r.why
    assert not codebox.has_real_test("x = 1\nassert x") and codebox.has_real_test("def test_a():\n    pass")


def test_a_syntax_error_is_a_failure_not_a_crash():
    r = box("def test_a(:\n    pass\n")
    assert not r.ran or not r.passed
    r = box("def test_a():\n    assert True\n", {"calc.py": "def add(:\n"})
    assert r.ran and r.passed            # the test doesn't import calc
    r = box("import calc\n\ndef test_a():\n    assert True\n", {"calc.py": "def add(:\n"})
    assert r.ran and not r.passed and "SyntaxError" in r.failures()


def test_only_plain_file_names_go_in():
    for bad in ("../x.py", "a/b.py", "C:\\x.py", "x.exe", ".py", "x y.py", "con.py\n"):
        r = codebox.run({bad: "x=1", "test_a.py": "def test_a():\n    pass\n"}, "test_a.py")
        assert not r.ran and "plain file name" in r.why, bad
    assert "isn't among" in codebox.run({"a.py": "x=1"}, "test_a.py").why
    assert "too many" in codebox.run({f"f{i}.py": "" for i in range(60)}, "f1.py").why
    assert "no files" in codebox.run({}, "t.py").why


# --------------------------------------------------------------------------- the fences
def test_no_network():
    why = blocked("import socket\nsocket.create_connection(('example.com', 80), timeout=3)")
    assert "the box" in why or "PermissionError" in why or "OSError" in why
    why = blocked("import urllib.request\nurllib.request.urlopen('http://example.com', timeout=3)")
    assert "the box" in why
    why = blocked("import socket\ns = socket.socket()\ns.bind(('127.0.0.1', 0))")
    assert "the box" in why


def test_no_other_programs():
    for body in ("import subprocess, sys\nsubprocess.run([sys.executable, '-c', 'print(1)'])",
                 "import os\nos.system('echo hi')",
                 "import os, sys\nos.execv(sys.executable, [sys.executable, '-c', '1'])"):
        assert "the box" in blocked(body), body
    if hasattr(os, "fork"):
        assert "the box" in blocked("import os\npid = os.fork()\nif pid == 0:\n    os._exit(0)")


def test_no_system_libraries():
    why = blocked("import ctypes\nctypes.CDLL(None)")
    assert "the box" in why


def test_cannot_read_outside_its_folder(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("the owner's file")
    why = blocked(f"print(open({str(secret)!r}).read())")
    assert "may only read its own files" in why
    home = str(Path.home())
    assert "may only read" in blocked(f"import os\nprint(os.listdir({home!r}))")
    assert "may only read" in blocked(f"from pathlib import Path\nprint(Path({str(secret)!r}).read_text())")
    assert "the owner's file" not in box(f"def test_it():\n    print(open({str(secret)!r}).read())\n").output


def test_cannot_write_or_delete_outside_its_folder(tmp_path):
    victim = tmp_path / "keep.txt"
    victim.write_text("keep me")
    new = tmp_path / "new.txt"
    for body in (f"open({str(new)!r}, 'w').write('x')",
                 f"import os\nos.remove({str(victim)!r})",
                 f"import os\nos.rename({str(victim)!r}, {str(new)!r})",
                 f"import shutil\nshutil.rmtree({str(tmp_path)!r})",
                 f"import os\nos.mkdir({str(tmp_path / 'd')!r})",
                 f"from pathlib import Path\nPath({str(victim)!r}).unlink()",
                 f"import os\nfd = os.open({str(new)!r}, os.O_WRONLY | os.O_CREAT)"):
        why = blocked(body)
        assert "the box" in why, (body, why)
    assert victim.read_text() == "keep me" and not new.exists() and not (tmp_path / "d").exists()


def test_can_read_and_write_inside_its_own_folder_and_use_pythons_library():
    r = box("import json, tempfile, os, re, math, datetime, collections, sqlite3\nfrom pathlib import Path\n\n"
            "def test_files():\n    Path('out.txt').write_text('hello')\n    assert Path('out.txt').read_text() == 'hello'\n"
            "    os.remove('out.txt')\n    assert 'data.json' in os.listdir('.')\n"
            "    assert json.loads(Path('data.json').read_text())['n'] == 3\n\n"
            "def test_temp():\n    with tempfile.TemporaryDirectory() as d:\n        Path(d, 'a').write_text('x')\n\n"
            "def test_db():\n    c = sqlite3.connect(':memory:')\n    c.execute('create table t(x)')\n",
            {"data.json": '{"n": 3}'})
    assert r.ran and r.passed, (r.failures(), r.output)


def test_the_box_folder_is_gone_afterwards_and_the_code_never_saw_joes_folder():
    r = box("import os\n\ndef test_where():\n    print('BOX=' + os.getcwd())\n    print('ENV=' + ','.join(sorted(os.environ)))\n")
    assert r.ran and r.passed
    where = r.output.split("BOX=")[1].splitlines()[0]
    assert not os.path.exists(where) and os.path.realpath(tempfile.gettempdir()) in os.path.realpath(where)
    env = r.output.split("ENV=")[1].splitlines()[0]
    for leak in ("PATH", "OLLAMA_API_KEY", "GITHUB_TOKEN", "JOE_CONFIG", "APPDATA", "USERNAME", "USER"):
        assert leak not in env.split(","), env


def test_secrets_in_joes_environment_do_not_reach_the_box(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret")
    monkeypatch.setenv("JOE_CONFIG", "/somewhere/settings.json")
    r = box("import os\n\ndef test_env():\n    print(repr(os.environ.get('GITHUB_TOKEN')), repr(os.environ.get('JOE_CONFIG')))\n")
    assert r.passed and "ghp_secret" not in r.output and "settings.json" not in r.output


def test_an_endless_loop_is_stopped():
    r = box("def test_forever():\n    while True:\n        pass\n", timeout=3)
    assert not r.ran and not r.passed and "ran longer than 3 seconds" in r.why and r.seconds < 20


def test_too_much_memory_is_stopped():
    # the sleep: where Joe watches the memory himself (a Mac) he looks ten times a second, so the code
    # holds what it took for a moment; a limit from the system (Linux, Windows) stops it before the sleep
    r = box("import time\n\ndef test_hog():\n    x = bytearray(900 * 1024 * 1024)\n    time.sleep(3)\n"
            "    assert len(x)\n", memory_mb=256, timeout=30)
    assert not r.passed
    if sys.platform == "darwin":
        assert codebox.WATCH_LABEL in r.fence and "memory" in r.why and r.seconds < 3
    if "memory limit" in " ".join(r.fence) or sys.platform.startswith(("linux", "win")):
        assert "MemoryError" in (r.failures() + r.output) or "memory" in r.why


HOG = "import time\nx = bytearray({mb} * 1024 * 1024)\nprint('took it', flush=True)\ntime.sleep(30)\n"


def _start(code):
    import subprocess
    return subprocess.Popen([sys.executable, "-I", "-S", "-c", code], stdout=subprocess.PIPE,
                            start_new_session=True)


@pytest.mark.skipif(os.name == "nt", reason="Windows has the Job Object; the watch asks 'ps'")
def test_the_memory_watch_kills_a_box_that_goes_over():
    """The watch itself, on every system with "ps" (in a real run only a Mac needs it)."""
    proc = _start(HOG.format(mb=300))
    try:
        watch = codebox.MemoryWatch(proc, 100)
        assert watch.start()
        proc.wait(timeout=10)                              # killed (often while still taking it), not after 30 s
        assert watch.hit and watch.peak > 100 and proc.returncode not in (0, None)
    finally:
        watch.stop()
        codebox._kill(proc)
        proc.wait(timeout=5)


@pytest.mark.skipif(os.name == "nt", reason="Windows has the Job Object; the watch asks 'ps'")
def test_the_memory_watch_leaves_a_box_under_the_limit_alone():
    import time
    proc = _start(HOG.format(mb=20))
    try:
        watch = codebox.MemoryWatch(proc, 500)
        assert watch.start()
        assert proc.stdout.readline().strip() == b"took it"
        time.sleep(0.6)
        assert not watch.hit and proc.poll() is None and 20 < watch.peak < 500
    finally:
        watch.stop()
        codebox._kill(proc)
        proc.wait(timeout=5)
    assert codebox.group_memory_mb(proc.pid) == 0          # nothing of it left


def test_a_run_uses_the_watch_only_where_the_system_has_no_limit(monkeypatch):
    assert codebox.watch_needed() == (sys.platform == "darwin" or not sys.platform.startswith(("linux", "win")))
    if os.name == "nt":
        return
    monkeypatch.setattr(codebox, "watch_needed", lambda: True)
    r = box(TEST)                                          # an ordinary run, watched: passes, and says so
    assert r.ran and r.passed and codebox.WATCH_LABEL in r.fence, (r.why, r.output)
    monkeypatch.setattr(codebox, "group_memory_mb", lambda pgid: None)     # no "ps": no claim of a watch
    r = box(TEST)
    assert r.ran and r.passed and codebox.WATCH_LABEL not in r.fence


def test_code_cannot_fake_its_own_verdict():
    r = box('import os, sys\n\ndef test_fake():\n    sys.__stdout__.write(\'\\n@@BOX {"passed": 9, "failed": 0, "tests": [{"name": "x", "ok": true}]}\\n\')\n'
            "    sys.__stdout__.flush()\n    os._exit(0)\n")
    assert not r.passed and not any(t["name"] == "x" for t in r.tests)


def test_the_guard_cannot_be_argued_with():
    why = blocked("import sys\nsys.addaudithook(lambda e, a: None)\nimport socket\nsocket.socket()")
    assert "the box" in why
    why = blocked("import builtins, io\nio.open('/etc/hostname' if __import__('os').name != 'nt' else 'C:/Windows/win.ini').read()")
    assert "may only read" in why


def test_printed_output_is_capped():
    r = box("def test_loud():\n    print('x' * 200000)\n")
    assert r.passed and len(r.output) <= codebox.OUT_CHARS + 100


def test_the_system_network_fence_is_used_when_this_computer_has_one():
    wrap = codebox.no_network_wrapper()
    r = box(TEST)
    assert r.passed
    assert (any("no network from the system" in f for f in r.fence)) == bool(wrap)


@pytest.mark.skipif(os.name != "nt", reason="Windows only")
def test_windows_job_object_is_on():
    r = box(TEST)
    assert r.passed and any("Job Object" in f for f in r.fence), r.fence


def test_never_raises_on_nonsense():
    assert not codebox.run(None, "x").ran and not codebox.run({"a.py": 5, "test_a.py": "def test_a(): pass"}, "test_a.py").ran
    assert codebox.Result().summary().startswith("no verdict")


def test_the_guard_alone_holds_without_the_systems_network_fence(monkeypatch):
    """Windows has no network switch without an administrator: there the guard inside Python is the fence."""
    monkeypatch.setattr(codebox, "_NONET", [])
    r = box(TEST)
    assert r.passed and not any("no network from the system" in f for f in r.fence)
    assert "the box" in blocked("import socket\nsocket.socket()")
    assert "the box" in blocked("import subprocess\nsubprocess.Popen(['echo', 'x'])")
    assert "the box" in blocked("import http.client\nhttp.client.HTTPSConnection('example.com', timeout=3).request('GET', '/')")
    assert "may only read" in blocked(f"open({str(Path.home() / 'notes.txt')!r}).read()")
    r = box("import os\n\ndef test_home():\n    print('HOME=' + os.path.expanduser('~'))\n")       # "home" is the box itself
    assert r.passed and "joe-box-" in r.output.split("HOME=")[1]


def test_a_program_may_not_take_the_name_of_a_part_of_python():
    for bad in ("json.py", "random.py", "os.py", "re.py", "site.py"):
        r = codebox.run({bad: "x = 1\n", "test_a.py": "def test_a():\n    assert True\n"}, "test_a.py")
        assert not r.ran and "same name as a part of Python" in r.why, bad
    assert codebox.shadows_python("JSON") and not codebox.shadows_python("budget")


def test_a_link_pointing_out_of_the_box_cannot_be_made_or_followed(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("the owner's file")
    if hasattr(os, "symlink"):
        why = blocked(f"import os\nos.symlink({str(secret)!r}, 'link.txt')\nprint(open('link.txt').read())")
        assert "the box" in why
    why = blocked(f"import os\nfd = os.open('.', os.O_RDONLY)\nos.open({'../' * 12 + str(secret).lstrip('/')!r}, os.O_RDONLY, dir_fd=fd)"
                  if os.name != "nt" else f"open({str(secret)!r}).read()")
    assert "may only read" in why or "folder can't be opened" in why


def test_moving_a_file_out_of_the_box_is_refused(tmp_path):
    dest = tmp_path / "out.txt"
    why = blocked(f"import os, shutil\nopen('a.txt', 'w').write('x')\nshutil.move('a.txt', {str(dest)!r})")
    assert "the box" in why and not dest.exists()
    why = blocked(f"import os\nopen('a.txt', 'w').write('x')\nos.replace('a.txt', {str(dest)!r})")
    assert "the box" in why and not dest.exists()


# --------------------------------------------------------------------------- the 2026-11-22 review
def test_a_print_loop_is_stopped_before_it_fills_joes_memory():
    """Joe reads what the box prints with a budget of his own; a print loop is stopped, not stored."""
    r = box("def test_loud():\n    i = 0\n    while True:\n        print('value', i)\n        i += 1\n", timeout=20)
    assert not r.ran and not r.passed and "printed far too much" in r.why, (r.why, r.seconds)
    assert r.seconds < 15 and len(r.output) <= codebox.OUT_CHARS + 100
    assert any("output limit" in f for f in r.fence)
    r = box("import sys\n\ndef test_big_lines():\n    s = 'x' * (1 << 20) + '\\n'\n    while True:\n        sys.stdout.write(s)\n",
            timeout=20)
    assert not r.passed and "printed far too much" in r.why and r.seconds < 15


def test_ending_the_program_while_loading_is_not_a_pass():
    for calc in ("import sys\ndef add(a, b):\n    return a + b\nsys.exit(0)\n",
                 "def add(a, b):\n    return a + b\nraise SystemExit\n",
                 "import os\ndef add(a, b):\n    return a + b\nos._exit(0)\n"):
        r = box("from calc import add\n\ndef test_add():\n    assert add(2, 2) == 5\n", {"calc.py": calc})
        assert not r.passed, calc
        assert "ended the program while it was being loaded" in (r.why + r.failures()), (calc, r.why, r.failures())
    r = box("import sys\n\ndef test_quits():\n    sys.exit(0)\n\ndef test_ok():\n    assert True\n")
    assert r.ran and not r.passed and r.counts == (1, 1)
    r = box("import unittest, sys\n\nclass T(unittest.TestCase):\n    def test_quits(self):\n        sys.exit(0)\n")
    assert r.ran and not r.passed
    # the program ended with exit code 0 and no verdict at all
    low = "nt" if os.name == "nt" else "posix"
    r = box(f"import {low}\n{low}._exit(0)\n\ndef test_a():\n    assert True\n")
    assert not r.ran and not r.passed and "ended before" in r.why, r.why


def test_tests_that_never_run_do_not_pass():
    plain = "def test_ok():\n    assert True\n\n"
    for body in ("async def test_b():\n    assert 1 == 2\n",
                 "def test_b():\n    for x in [1, 2]:\n        yield x\n        assert x == 99\n",
                 "class Later:\n    def __call__(self):\n        async def go():\n            assert False\n        return go()\n\ntest_b = Later()\n"):
        r = box(plain + body)
        assert r.ran and not r.passed and r.counts == (1, 1), (body, r.tests)
        assert "never ran" in r.failures(), r.failures()
    r = box("import unittest\n\nclass T(unittest.TestCase):\n    def test_ok(self):\n        pass\n"
            "    async def test_b(self):\n        self.assertEqual(1, 2)\n    def test_c(self):\n        yield 1\n")
    assert r.ran and not r.passed and r.counts == (1, 2), r.tests
    assert "never ran" in r.failures()
    r = box("import unittest\n\nclass T(unittest.TestCase):\n    @unittest.expectedFailure\n    def test_a(self):\n"
            "        self.assertEqual(1, 1)\n")                     # "expected to fail" but passed: unittest says failed
    assert r.ran and not r.passed and "expectedFailure" in r.failures()
    r = box("async def test_only():\n    assert 1 == 2\n")             # nothing but async tests: refused
    assert not r.ran and not r.passed and "async" in r.why


def test_sqlite_stays_inside_the_box(tmp_path):
    out = tmp_path.as_posix()                              # (forward slashes: fine for SQLite and Python on Windows)
    for body in (f"import sqlite3\nc = sqlite3.connect(':memory:')\nc.execute(\"ATTACH '{out}/att.db' AS x\")",
                 f"import sqlite3\nc = sqlite3.connect('in.db')\nc.execute('create table t(x)')\nc.execute(\"VACUUM INTO '{out}/vac.db'\")",
                 f"import sqlite3\nsqlite3.connect('file:{out}/uri.db?mode=rwc', uri=True).execute('create table t(x)')",
                 "import sqlite3\nc = sqlite3.connect(':memory:')\nc.enable_load_extension(True)",
                 f"import sqlite3\nc = sqlite3.connect(':memory:')\nc.set_authorizer(None)\nc.execute(\"ATTACH '{out}/att2.db' AS x\")",
                 "import sqlite3\nc = sqlite3.connect(':memory:')\nc.execute(\"PRAGMA temp_store_directory = '/'\")"):
        r = box("def test_it():\n" + "\n".join("    " + line for line in body.splitlines()) + "\n")
        assert r.ran and not r.passed, (body, r.why)
    assert not os.listdir(tmp_path), os.listdir(tmp_path)
    r = box("import sqlite3\n\ndef test_db():\n    c = sqlite3.connect('shop.db')\n    c.execute('create table t(x)')\n"
            "    c.execute('insert into t values (1)')\n    c.commit()\n    c.close()\n"
            "    assert sqlite3.connect('shop.db').execute('select x from t').fetchall() == [(1,)]\n"
            "    m = sqlite3.connect(':memory:')\n    m.execute('create table t(x)')\n"
            "    s = sqlite3.connect('file::memory:?cache=shared', uri=True)\n    s.execute('select 1')\n")
    assert r.ran and r.passed, (r.failures(), r.output)


def _library_folder():
    import sysconfig
    return os.path.realpath(sysconfig.get_paths()["stdlib"])


def test_changing_folder_cannot_carry_writes_out_of_the_box(tmp_path):
    lib = _library_folder()
    made = [os.path.join(lib, n) for n in ("zz_box_chdir.txt", "zz_box_dirfd.txt", "zz_box_dirfd_dir")]
    try:
        assert "the box" in blocked(f"import os\nos.chdir({str(tmp_path)!r})")
        why = blocked(f"import os\nos.chdir({lib!r})\nopen('zz_box_chdir.txt', 'w').write('x')")
        assert "may only change folder inside its own folder" in why, why
        if hasattr(os, "O_DIRECTORY") or os.name != "nt":
            why = blocked(f"import os\nfd = os.open({lib!r}, os.O_RDONLY)\n"
                          "os.open('zz_box_dirfd.txt', os.O_WRONLY | os.O_CREAT, dir_fd=fd)")
            assert "the box" in why, why
            why = blocked(f"import os\nfd = os.open({lib!r}, os.O_RDONLY)\nos.mkdir('zz_box_dirfd_dir', dir_fd=fd)")
            assert "the box" in why, why
        if os.name != "nt":                                 # any folder handle at all is refused
            assert "dir_fd" in blocked("import os\nos.mkdir('zz_box_dirfd_dir', dir_fd=0)")
        for m in made:
            assert not os.path.exists(m), m
    finally:
        for m in made:
            if os.path.isdir(m):
                os.rmdir(m)
            elif os.path.exists(m):
                os.remove(m)
    # inside the box, changing folder works, and a relative name means the real current folder
    r = box("import os\nfrom pathlib import Path\n\ndef test_sub():\n    os.mkdir('sub')\n    os.chdir('sub')\n"
            "    open('../top.txt', 'w').write('x')\n    open('here.txt', 'w').write('y')\n    os.chdir('..')\n"
            "    assert Path('top.txt').read_text() == 'x' and Path('sub', 'here.txt').read_text() == 'y'\n"
            "    import shutil\n    shutil.rmtree('sub')\n    assert not os.path.exists('sub')\n")
    assert r.ran and r.passed, (r.failures(), r.output)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="no pipes-as-files on this system")
def test_no_named_pipes_outside_the_box(tmp_path):
    why = blocked(f"import os\nos.mkfifo({str(tmp_path / 'p')!r})")
    assert "the box" in why and not (tmp_path / "p").exists()


def test_too_much_on_disk_is_stopped():
    """Many files, each under the per-file limit, together over the total: Joe sees it and stops the box."""
    r = box("import time\n\ndef test_fill():\n    chunk = b'x' * (2 << 20)\n    for i in range(100):\n"
            "        with open(f'f{i}.bin', 'wb') as f:\n            f.write(chunk)\n        time.sleep(0.03)\n",
            disk_mb=20, timeout=30)
    assert not r.ran and not r.passed and "too many or too big files" in r.why, (r.why, r.output)
    assert any("disk limit" in f for f in r.fence) and r.seconds < 15


def test_too_many_files_is_stopped(monkeypatch):
    monkeypatch.setattr(codebox, "DISK_FILES", 300)
    r = box("import time\n\ndef test_many():\n    for i in range(3000):\n        open(f'f{i}.txt', 'w').close()\n"
            "        if i % 100 == 0:\n            time.sleep(0.05)\n", timeout=30)
    assert not r.passed and "too many or too big files" in r.why, (r.why, r.output)


def test_a_normal_run_has_the_disk_and_output_limits():
    r = box(TEST)
    assert r.passed and any("disk limit" in f for f in r.fence) and any("output limit" in f for f in r.fence)


def test_reassigning_what_the_guard_uses_does_not_switch_it_off(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("the owner's file")
    for patch in ("os.path.join = lambda *a: a[0]", "builtins.isinstance = lambda *a: True",
                  "builtins.any = lambda *a: True", "os.path.realpath = lambda p, **k: os.getcwd()"):
        target, _ = patch.split(" = ", 1)
        body = (f"import os, builtins\nkeep = {target}\n{patch}\ntry:\n    data = open({str(secret)!r}).read()\n"
                f"finally:\n    {target} = keep\nprint(data)")
        r = box("def test_it():\n" + "\n".join("    " + line for line in body.splitlines()) + "\n")
        assert r.ran and not r.passed and "the owner's file" not in r.output, (patch, r.output)
        assert "may only read" in r.tests[0]["why"] or patch.startswith("builtins.isinstance"), (patch, r.tests)


@pytest.mark.skipif(os.name == "nt", reason="Windows has the Job Object; the watch asks 'ps'")
def test_the_memory_watch_stops_claiming_when_ps_stops_answering(monkeypatch):
    calls = []

    def flaky(pgid):
        calls.append(pgid)
        return 1.0 if len(calls) == 1 else None             # answers once (the start), then never again
    monkeypatch.setattr(codebox, "watch_needed", lambda: True)
    monkeypatch.setattr(codebox, "group_memory_mb", flaky)
    r = box("import time\n\ndef test_slow():\n    time.sleep(1.5)\n    assert True\n")
    assert r.ran and r.passed and codebox.WATCH_LABEL not in r.fence and len(calls) > 3
    assert codebox.ps_program() is None or os.path.isabs(codebox.ps_program())


def test_old_box_folders_are_swept_and_locked_files_do_not_stop_the_cleanup(tmp_path):
    import stat
    import time
    temp = Path(tempfile.gettempdir())
    old, new = temp / "joe-box-test-old", temp / "joe-box-test-new"
    for d in (old, new):
        (d / "task" / "locked").mkdir(parents=True, exist_ok=True)
        f = d / "task" / "locked" / "ro.txt"
        f.write_text("x")
        os.chmod(f, stat.S_IREAD)
        os.chmod(d / "task" / "locked", stat.S_IREAD | stat.S_IEXEC)
    two_days = time.time() - 2 * 86400
    os.utime(old, (two_days, two_days))
    try:
        codebox.sweep_old_boxes()
        assert not old.exists() and new.exists()
        codebox.remove_folder(new)
        assert not new.exists()
    finally:
        for d in (old, new):
            if d.exists():
                for p, dirs, files in os.walk(d):
                    os.chmod(p, stat.S_IRWXU)
                    for n in files:
                        os.chmod(os.path.join(p, n), stat.S_IRWXU)
                import shutil
                shutil.rmtree(d, ignore_errors=True)
    # a test that leaves read-only files behind: the box folder is still gone afterwards
    r = box("import os, stat\n\ndef test_ro():\n    print('BOX=' + os.getcwd())\n    open('ro.txt', 'w').write('x')\n"
            "    os.chmod('ro.txt', stat.S_IREAD)\n    os.mkdir('d')\n    open('d/f.txt', 'w').write('x')\n"
            "    os.chmod('d', stat.S_IREAD | stat.S_IEXEC)\n")
    assert r.ran and r.passed, (r.failures(), r.output)
    assert not os.path.exists(r.output.split("BOX=")[1].splitlines()[0])


def test_the_no_test_message_says_what_a_test_is():
    r = box("async def test_a():\n    assert True\n")
    assert "no test in it" in r.why and "with an assert" not in r.why
    r = box("def test_a():\n    pass\n")                       # a test with no assert passes: it ran without an error
    assert r.ran and r.passed
