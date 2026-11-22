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
    r = box("def test_hog():\n    x = bytearray(900 * 1024 * 1024)\n    assert len(x)\n", memory_mb=256, timeout=30)
    assert not r.passed
    if "memory limit" in " ".join(r.fence) or sys.platform.startswith(("linux", "win")):
        assert "MemoryError" in (r.failures() + r.output) or "memory" in r.why


def test_code_cannot_fake_its_own_verdict():
    r = box('import os, sys\n\ndef test_fake():\n    sys.__stdout__.write(\'\\n@@BOX {"passed": 9, "failed": 0, "tests": [{"name": "x", "ok": true}]}\\n\')\n'
            "    sys.__stdout__.flush()\n    os._exit(0)\n")
    assert not r.ran and not r.passed


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
    assert "may only read" in why


def test_moving_a_file_out_of_the_box_is_refused(tmp_path):
    dest = tmp_path / "out.txt"
    why = blocked(f"import os, shutil\nopen('a.txt', 'w').write('x')\nshutil.move('a.txt', {str(dest)!r})")
    assert "the box" in why and not dest.exists()
    why = blocked(f"import os\nopen('a.txt', 'w').write('x')\nos.replace('a.txt', {str(dest)!r})")
    assert "the box" in why and not dest.exists()
