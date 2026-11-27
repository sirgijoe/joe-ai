"""Dev tools (2.4.0.dev1): the person's own list of project folders and commands that a connected AI
app may ask Joe to run, by name, with nothing added. One test per rule in joeai/devprojects.py."""
from __future__ import annotations

import http.client
import json
import sys
import threading
import time
from datetime import datetime

import pytest

from joeai import devprojects as dp, mcp, server
from joeai.config import KEEP_ON_RESET, Settings, reset_paths

from test_core import env  # noqa: F401

PY = f'"{sys.executable}"'


def project(folder, **commands):
    return {"name": "hooah", "folder": str(folder), "pull": True,
            "commands": [{"name": n, "run": r, "minutes": 1} for n, r in commands.items()]}


@pytest.fixture
def joe(tmp_path, monkeypatch):
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "settings.json"))
    dp._jobs.clear()
    monkeypatch.setattr(dp, "WAIT_S", 60)
    proj = tmp_path / "my project"
    proj.mkdir()
    (proj / "ok.py").write_text("import os\nprint('cwd', os.path.basename(os.getcwd()))\nprint('12 passed, 0 failed')\n", encoding="utf-8")
    (proj / "bad.py").write_text("import sys\nprint('test_a ... ok')\nprint('FAILED test_b - AssertionError: 1 != 2')\n"
                                 + "".join(f"print('filler line {i}')\n" for i in range(40))
                                 + "print('1 failed, 1 passed')\nsys.exit(3)\n", encoding="utf-8")
    (proj / "args.py").write_text("import sys\nprint('ARGS', sys.argv[1:])\n", encoding="utf-8")
    (proj / "slow.py").write_text("import time\nprint('started', flush=True)\ntime.sleep(60)\nprint('never')\n", encoding="utf-8")
    (proj / "kids.py").write_text(
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, '-c', \"import time, pathlib; time.sleep(4); pathlib.Path('child-lived.txt').write_text('x')\"])\n"
        "print('parent waiting', flush=True)\ntime.sleep(60)\n", encoding="utf-8")
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    s.dev_tools = True
    s.dev_projects = [project(proj, tests=f"{PY} ok.py", failing=f"{PY} bad.py", args=f"{PY} args.py one \"two words\"",
                              slow=f"{PY} slow.py", kids=f"{PY} kids.py", missing="no-such-program-xyz --version")]
    s.save()
    j = mcp.Joe(s)
    j.proj = proj
    yield j
    dp._jobs.clear()


# ------------------------------------------------------------------ off when Joe comes
def test_off_by_default_and_nothing_runs(joe):
    assert Settings().dev_tools is False and Settings().dev_projects == []
    joe.s.dev_tools = False
    assert joe.call("joe_run_command", {"project": "hooah", "command": "tests"}) == dp.OFF
    assert joe.call("joe_run_command", {}) == dp.OFF
    assert not (joe.sb.output / "dev").exists()


def test_the_dev_tools_are_listed_only_when_on(joe):
    def names():
        r = mcp.handle(joe, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        return {t["name"] for t in r["result"]["tools"]}
    assert set(mcp.DEV_TOOLS) <= names()
    joe.s.dev_tools = False
    assert not (set(mcp.DEV_TOOLS) & names()) and "joe_count_tokens" in names()


# ------------------------------------------------------------------ what a connected app sees and can ask
def test_no_arguments_lists_projects_and_commands(joe):
    out = joe.call("joe_run_command", {})
    assert f"hooah: {joe.proj}" in out and "tests  =  " in out and "(up to 1 min)" in out
    assert "nothing can be added to a command" in out


def test_a_listed_command_runs_in_the_project_folder_and_reports_briefly(joe):
    out = joe.call("joe_run_command", {"project": "hooah", "command": "tests"})
    head = out.splitlines()[0]
    assert head.startswith("[hooah / tests | finished OK (exit code 0) | ") and "whole output: Output/dev/hooah-tests-" in head
    assert "cwd my project" in out and "12 passed, 0 failed" in out
    logs = list((joe.sb.output / "dev").glob("hooah-tests-*.log"))
    assert len(logs) == 1 and "12 passed" in logs[0].read_text(encoding="utf-8")
    assert "hooah / tests  finished OK" in (joe.sb.output / "dev" / "_runs.txt").read_text(encoding="utf-8")
    assert "12 passed" in joe.call("joe_shrink", {"path": f"Output/dev/{logs[0].name}"})      # the whole output is readable


def test_a_failing_run_shows_the_failure_and_the_totals_not_the_filler(joe):
    out = joe.call("joe_run_command", {"project": "hooah", "command": "failing"})
    assert "| FAILED (exit code 3) |" in out.splitlines()[0]
    assert "FAILED test_b - AssertionError: 1 != 2" in out and "1 failed, 1 passed" in out
    assert "filler line 5\n" not in out and "filler line 12" not in out and len(out.splitlines()) < 25


def test_names_are_matched_plainly(joe):
    assert "finished OK" in joe.call("joe_run_command", {"project": " Hooah ", "command": "TESTS"})


@pytest.mark.parametrize("args", [{"project": "nope", "command": "tests"}, {"project": "hooah", "command": "nope"},
                                  {"project": "hooah"}, {"command": "tests"}])
def test_an_unknown_name_runs_nothing_and_shows_the_list(joe, args):
    out = joe.call("joe_run_command", args)
    assert "hooah:" in out and "finished" not in out
    assert not list((joe.sb.output / "dev").glob("*.log")) if (joe.sb.output / "dev").exists() else True


# ------------------------------------------------------------------ nothing can be added
@pytest.mark.parametrize("sneaky", ["tests --evil", "tests; whoami", "tests && whoami", "tests | more", "../tests", "tests\nwhoami"])
def test_extra_words_in_the_command_name_never_reach_the_program(joe, sneaky):
    out = joe.call("joe_run_command", {"project": "hooah", "command": sneaky})
    assert "No command called" in out and "finished" not in out


def test_extra_arguments_from_the_app_are_ignored(joe):
    out = joe.call("joe_run_command", {"project": "hooah", "command": "args", "args": ["--evil"], "run": "whoami",
                                       "cwd": "/", "env": {"X": "1"}, "minutes": 999, "folder": "/"})
    assert "ARGS ['one', 'two words']" in out and "evil" not in out and "whoami" not in out.split("ran:")[0]


def test_no_shell_so_shell_signs_are_plain_words(joe, tmp_path):
    marker = tmp_path / "made-by-shell.txt"
    joe.s.dev_projects = [project(joe.proj, sneaky=f"{PY} args.py hello && echo x > \"{marker}\"")]
    out = joe.call("joe_run_command", {"project": "hooah", "command": "sneaky"})
    assert "'&&'" in out and not marker.exists()                       # handed to the program as words
    assert "NOTE: has && > in it" in joe.call("joe_run_command", {})   # and the list warns about it


def test_a_program_that_is_not_there_is_said_plainly(joe):
    out = joe.call("joe_run_command", {"project": "hooah", "command": "missing"})
    assert out.startswith("hooah / missing didn't start:") and "Setup > Other AI apps > Dev tools" in out
    assert dp._busy() == ""                                            # and Joe isn't left "busy"


def test_a_folder_that_is_gone_or_not_a_full_path_runs_nothing(joe, tmp_path):
    for folder in (tmp_path / "gone", "relative/folder", ""):
        joe.s.dev_projects = [{"name": "hooah", "folder": str(folder), "commands": [{"name": "tests", "run": f"{PY} ok.py"}]}]
        out = joe.call("joe_run_command", {"project": "hooah", "command": "tests"})
        assert "finished" not in out and ("isn't there" in out or "No project called" in out)


# ------------------------------------------------------------------ time limits, long runs, one at a time
def _wait_for(check, seconds=20):
    end = time.time() + seconds
    while time.time() < end:
        if check():
            return True
        time.sleep(0.1)
    return False


def _end_the_run_now():
    """Tests only: end whatever the minder is running, by making its time limit already passed."""
    for spec in dp.state_dir().glob("*.spec.json"):
        pass                                                           # (the minder read it at start; nothing to change here)


def test_a_long_run_answers_still_running_and_is_never_started_twice(joe, monkeypatch):
    joe.s.dev_projects = [project(joe.proj, slow=f"{PY} slow.py 3", tests=f"{PY} ok.py")]
    (joe.proj / "slow.py").write_text("import time\nprint('started', flush=True)\ntime.sleep(3)\nprint('3 passed')\n", encoding="utf-8")
    monkeypatch.setattr(dp, "WAIT_S", 0.3)
    first = joe.call("joe_run_command", {"project": "hooah", "command": "slow"})
    assert first.startswith("[hooah / slow | STILL RUNNING,") and "not started twice" in first
    assert joe.call("joe_run_command", {"project": "hooah", "command": "slow"}).startswith("[hooah / slow | STILL RUNNING,")
    other = joe.call("joe_run_command", {"project": "hooah", "command": "tests"})
    assert other == "Joe is already running hooah / slow. One command at a time: ask again when it has finished."
    monkeypatch.setattr(dp, "WAIT_S", 30)
    done = joe.call("joe_run_command", {"project": "hooah", "command": "slow"})
    assert "finished OK" in done.splitlines()[0] and "3 passed" in done
    assert len(list((joe.sb.output / "dev").glob("hooah-slow-*.log"))) == 1
    assert len((joe.sb.output / "dev" / "_runs.txt").read_text(encoding="utf-8").splitlines()) == 1
    assert "finished OK" in joe.call("joe_run_command", {"project": "hooah", "command": "tests"})      # free again


def test_the_time_limit_ends_the_program_and_what_it_started(joe, monkeypatch):
    joe.s.dev_projects = [project(joe.proj, kids=f"{PY} kids.py")]
    monkeypatch.setattr(dp, "_minutes", lambda v: 0.05)                # a 3-second limit instead of a minute
    out = joe.call("joe_run_command", {"project": "hooah", "command": "kids"})
    assert "| STOPPED at its time limit (0.05 min); the program and what it started were ended |" in out.splitlines()[0]
    assert "parent waiting" in out
    time.sleep(5)
    assert not (joe.proj / "child-lived.txt").exists()                # the program it started was ended too
    assert dp._busy() == ""


def test_output_past_the_cap_ends_the_program_and_is_not_kept(joe, monkeypatch):
    (joe.proj / "loud.py").write_text("import sys\nwhile True:\n    sys.stdout.write('x' * 65536 + '\\n')\n", encoding="utf-8")
    joe.s.dev_projects = [project(joe.proj, loud=f"{PY} loud.py")]
    monkeypatch.setattr(dp, "MAX_LOG_BYTES", 300_000)
    out = joe.call("joe_run_command", {"project": "hooah", "command": "loud"})
    assert "| STOPPED: it printed more than 0 MB; the program was ended |" in out.splitlines()[0]
    log = next((joe.sb.output / "dev").glob("hooah-loud-*.log"))
    assert log.stat().st_size <= 300_000                               # never more than the cap on disk


def test_the_limit_holds_when_the_connector_is_gone(joe, tmp_path):
    """The 2026-11-27 review: the AI app closed its connector and the command ran on with no limit. The
    minder is its own program, so it ends the command and clears the "running" note by itself."""
    import subprocess as sp
    spec = tmp_path / "x.spec.json"
    log, result, lock = tmp_path / "x.log", tmp_path / "x.result.json", tmp_path / "running.json"
    lock.write_text("{}", encoding="utf-8")
    spec.write_text(json.dumps({"run": f"{PY} slow.py", "cwd": str(joe.proj), "log": str(log), "limit_s": 2, "minutes": 1,
                                "cap_bytes": 1000, "result": str(result), "lock": str(lock), "runs": str(tmp_path / "_runs.txt"),
                                "what": "hooah / slow", "when": "2026-11-27 07:00:00"}), encoding="utf-8")
    minder = sp.Popen(dp._minder_command(spec))                        # nobody waits on it, as if the connector had gone
    assert _wait_for(result.exists, 20)
    minder.wait(10)
    assert json.loads(result.read_text(encoding="utf-8"))["ended"] == "limit"
    assert not lock.exists() and not spec.exists()
    assert "STOPPED at its time limit" in (tmp_path / "_runs.txt").read_text(encoding="utf-8")


def test_a_result_is_handed_over_once_then_the_next_ask_is_a_fresh_run(joe):
    joe.call("joe_run_command", {"project": "hooah", "command": "tests"})
    joe.call("joe_run_command", {"project": "hooah", "command": "tests"})
    assert len((joe.sb.output / "dev" / "_runs.txt").read_text(encoding="utf-8").splitlines()) == 2


def test_a_note_left_behind_stops_counting_when_its_minder_is_gone_or_its_time_is_up(joe):
    import os
    note = dp.state_dir() / "running.json"
    note.write_text(json.dumps({"what": "hooah / old", "pid": os.getpid(), "until": time.time() + 500}), encoding="utf-8")
    assert "already running hooah / old" in joe.call("joe_run_command", {"project": "hooah", "command": "tests"})
    note.write_text(json.dumps({"what": "hooah / old", "pid": os.getpid(), "until": time.time() - 5}), encoding="utf-8")
    assert "finished OK" in joe.call("joe_run_command", {"project": "hooah", "command": "tests"})
    note.write_text("not json at all", encoding="utf-8")
    assert "finished OK" in joe.call("joe_run_command", {"project": "hooah", "command": "tests"})
    assert not str(dp.state_dir()).startswith(str(joe.sb.root))        # outside Joe's workspace: a mission can't write it


def test_a_result_nobody_came_back_for_is_not_handed_over_as_news(joe, monkeypatch):
    joe.s.dev_projects = [project(joe.proj, slow=f"{PY} slow.py")]
    (joe.proj / "slow.py").write_text("import time\ntime.sleep(1)\nprint('OLD RESULT')\n", encoding="utf-8")
    monkeypatch.setattr(dp, "WAIT_S", 0.1)
    assert "STILL RUNNING" in joe.call("joe_run_command", {"project": "hooah", "command": "slow"})
    job = next(iter(dp._jobs.values()))
    assert job.done.wait(20)
    monkeypatch.setattr(dp, "WAIT_S", 30)
    job.finished -= 120                                                # two minutes later: handed over, and it says so
    late = joe.call("joe_run_command", {"project": "hooah", "command": "slow"})
    assert "OLD RESULT" in late and "finished 2 min ago, not run again]" in late.splitlines()[0]
    monkeypatch.setattr(dp, "WAIT_S", 0.1)
    joe.call("joe_run_command", {"project": "hooah", "command": "slow"})
    job = next(iter(dp._jobs.values()))
    assert job.done.wait(20)
    job.finished -= dp.KEEP_RESULT_S + 5                               # much later: forgotten, the ask is a fresh run
    (joe.proj / "slow.py").write_text("print('NEW RESULT')\n", encoding="utf-8")
    monkeypatch.setattr(dp, "WAIT_S", 30)
    assert "NEW RESULT" in joe.call("joe_run_command", {"project": "hooah", "command": "slow"})


def test_a_changed_command_line_is_never_answered_with_the_old_ones_result(joe, monkeypatch):
    joe.s.dev_projects = [project(joe.proj, x=f"{PY} slow.py")]
    (joe.proj / "slow.py").write_text("import time\ntime.sleep(1)\nprint('OLD LINE')\n", encoding="utf-8")
    monkeypatch.setattr(dp, "WAIT_S", 0.1)
    assert "STILL RUNNING" in joe.call("joe_run_command", {"project": "hooah", "command": "x"})
    assert next(iter(dp._jobs.values())).done.wait(20)
    joe.s.dev_projects = [project(joe.proj, x=f"{PY} ok.py")]
    monkeypatch.setattr(dp, "WAIT_S", 30)
    out = joe.call("joe_run_command", {"project": "hooah", "command": "x"})
    assert "12 passed" in out and "OLD LINE" not in out


def test_a_project_in_or_around_joes_own_folder_runs_nothing(joe):
    for folder in (joe.sb.root, joe.sb.root.parent, joe.sb.output, joe.sb.inbox):
        (folder / "ok.py").write_text("print('ran')\n", encoding="utf-8")
        joe.s.dev_projects = [project(folder, tests=f"{PY} ok.py")]
        out = joe.call("joe_run_command", {"project": "hooah", "command": "tests"})
        assert "Joe's own folder" in out and "finished" not in out


def test_a_program_named_with_a_folder_is_found_in_the_project(joe):
    (joe.proj / "scripts").mkdir()
    import stat
    sh = joe.proj / "scripts" / "check.py"
    sh.write_text("#!" + sys.executable + "\nprint('found in the project')\n", encoding="utf-8")
    sh.chmod(sh.stat().st_mode | stat.S_IEXEC)
    from joeai import devrun
    line = devrun.program_line("scripts/check.py --fast", joe.proj)
    first = line[0] if isinstance(line, list) else line.split('"')[1]
    assert first == str(joe.proj / "scripts" / "check.py")
    assert devrun.program_line("python -m pytest", joe.proj) in (["python", "-m", "pytest"], "python -m pytest")


def test_old_outputs_are_cleared_out(joe, monkeypatch):
    monkeypatch.setattr(dp, "KEEP_LOGS", 2)
    for i in range(4):
        assert "finished OK" in dp.run(joe.s, joe.sb, "hooah", "tests", now=datetime(2026, 11, 27, 7, 0, i))
    assert len(list((joe.sb.output / "dev").glob("*.log"))) == 2


# ------------------------------------------------------------------ the list itself
def test_the_list_is_kept_in_a_plain_form():
    got = dp.clean([{"name": " My Project! ", "folder": ' "C:\\Dev\\HUA" ', "extra": 1,
                     "commands": [{"name": "Full Tests", "run": "  echo  'a   b'  ", "minutes": "30", "x": 1},
                                  {"name": "full tests", "run": "again"}, {"name": "", "run": "x"}, {"name": "y", "run": ""},
                                  {"name": "toolong", "run": "x" * 501}, {"name": "twolines", "run": "a\nb"},
                                  {"name": "big", "run": "x" * 500, "minutes": 99999}, "junk"]},
                    {"name": "my-project", "folder": "/dup"}, {"name": "nofolder"}, {"name": "farfolder", "folder": "/" + "x" * 400},
                    {"name": "puller", "folder": "/p", "pull": True}, {"name": "notpuller", "folder": "/n", "pull": "yes"}, "junk", None])
    assert got == [{"name": "my-project", "folder": "C:\\Dev\\HUA", "pull": False, "commands": [
        {"name": "full-tests", "run": "echo  'a   b'", "minutes": 30},       # exactly as typed: only the ends trimmed
        {"name": "big", "run": "x" * 500, "minutes": 240}]},                 # too long or two lines: left out, never cut
        {"name": "puller", "folder": "/p", "pull": True, "commands": []},
        {"name": "notpuller", "folder": "/n", "pull": False, "commands": []}]
    assert dp.clean("junk") == [] and dp.clean(None) == []
    assert len(dp.clean([{"name": f"p{i}", "folder": "/x"} for i in range(50)])) == dp.MAX_PROJECTS


def test_the_list_survives_save_and_load_and_reset_only_turns_it_off(joe):
    s = Settings.load()
    assert s.dev_tools is True and s.dev_projects[0]["name"] == "hooah" and len(s.dev_projects[0]["commands"]) == 6
    assert "dev_projects" in KEEP_ON_RESET and "dev_tools" not in KEEP_ON_RESET
    reset_paths(s)
    assert s.dev_tools is False and s.dev_projects[0]["name"] == "hooah"
    bad = Settings()
    bad.dev_tools = "yes"                                               # only a real true turns it on
    bad.dev_projects = [{"name": "x"}]
    dp.clean_settings(bad)
    assert bad.dev_tools is False and bad.dev_projects == []


# ------------------------------------------------------------------ only Joe's own window can change the list
def _post(port, path, body, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("POST", path, json.dumps(body), {"Host": "127.0.0.1", "Content-Type": "application/json", **(headers or {})})
    r = c.getresponse()
    raw = r.read().decode()
    c.close()
    try:
        return r.status, json.loads(raw)
    except ValueError:
        return r.status, raw


def test_only_the_window_can_turn_it_on_or_change_the_list(env, tmp_path):  # noqa: F811
    s, _sb, _ = env
    s.mcp_key = "right-key"
    s.save()
    app = server.App(s)
    httpd = server.serve(app)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    change = {"dev_tools": True, "dev_projects": [{"name": "x", "folder": str(tmp_path), "commands": [{"name": "c", "run": "whoami"}]}]}
    try:
        for headers in ({}, {"X-NR-Token": "wrong"}, {"Authorization": "Bearer right-key"}):
            st, _ = _post(port, "/api/settings", change, headers)
            assert st == 401
            assert app.settings.dev_tools is False and Settings.load().dev_projects == []
        st, r = _post(port, "/api/settings", change, {"X-NR-Token": app.token})
        assert st == 200 and r.get("ok")
        assert Settings.load().dev_tools is True and Settings.load().dev_projects[0]["commands"][0] == {"name": "c", "run": "whoami", "minutes": 15}
        assert Settings.load().dev_projects[0]["pull"] is False
        st, r = _post(port, "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "joe_run_command", "arguments": {"dev_projects": [], "dev_tools": False}}}, {"Authorization": "Bearer right-key"})
        assert st == 200 and Settings.load().dev_tools is True and len(Settings.load().dev_projects) == 1
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_the_connector_has_no_tool_that_changes_the_list(joe):
    before = json.dumps(Settings.load().dev_projects)
    for name in ("joe_settings", "joe_set", "joe_add_project", "joe_add_command", "dev_projects"):
        with pytest.raises(KeyError):
            joe.call(name, {"dev_tools": True, "dev_projects": []})
    joe.call("joe_run_command", {"project": "new", "command": "c", "dev_projects": [{"name": "new", "folder": "/", "commands": [{"name": "c", "run": "whoami"}]}]})
    assert json.dumps(Settings.load().dev_projects) == before


def test_a_connector_an_app_started_sees_setup_changes_at_once(joe, monkeypatch):
    j = mcp.Joe()                                                       # as an AI app starts it: settings read from the file
    assert "hooah" in j.call("joe_run_command", {})
    s = Settings.load()
    s.dev_tools = False
    s.save()
    assert j.call("joe_run_command", {"project": "hooah", "command": "tests"}) == dp.OFF


# ------------------------------------------------------------------ the short report
def test_summary_keeps_failures_totals_and_the_end():
    text = "\n".join([f"test_{i} ... ok" for i in range(200)] + ["Traceback (most recent call last):", "x" * 900] +
                     [f"more {i}" for i in range(30)] + ["==== 1 failed, 200 passed in 3.2s ===="])
    out = dp.summary(text)
    assert "L201| Traceback (most recent call last):" in out and "1 failed, 200 passed" in out
    assert "test_5 ... ok" not in out and max(len(ln) for ln in out.splitlines()) < 320
    assert dp.summary("") == "(it printed nothing)" and dp.summary("\r\n\r\n") == "(it printed nothing)"
    many = dp.summary("\n".join(f"ERROR {i}" for i in range(500)))
    assert f"({dp.MAX_PROBLEM_LINES} of {500 - dp.TAIL_LINES})" in many


# ------------------------------------------------------------------ this computer's status is a dev tool too
def test_the_computer_report_needs_dev_tools_on(joe, monkeypatch):
    from joeai import pcstatus
    monkeypatch.setattr(pcstatus, "report", lambda settings, processes=25: f"REPORT rows={processes}")
    assert joe.call("joe_computer", {}) == "REPORT rows=25"
    assert joe.call("joe_computer", {"processes": 5}) == "REPORT rows=5"
    joe.s.dev_tools = False
    assert joe.call("joe_computer", {}) == dp.OFF


# ------------------------------------------------------------------ repo status and bundle pull (joe_repo)
import shutil  # noqa: E402
import subprocess  # noqa: E402

from joeai.sandbox import SandboxError  # noqa: E402

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git isn't installed")


def git(folder, *args):
    r = subprocess.run(["git", "-C", str(folder), "-c", "user.name=T", "-c", "user.email=t@example.com", *args],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.fixture
def repo(joe, tmp_path):
    """The project is a git repo; ahead.bundle (inside it) and Inbox/ahead.bundle hold one more commit."""
    git(joe.proj, "init", "-q", "-b", "main")
    (joe.proj / ".gitignore").write_text("*.bundle\nsync/\n", encoding="utf-8")
    git(joe.proj, "add", "-A")
    git(joe.proj, "commit", "-q", "-m", "first")
    first = git(joe.proj, "rev-parse", "HEAD")
    (joe.proj / "new.txt").write_text("more\n", encoding="utf-8")
    git(joe.proj, "add", "-A")
    git(joe.proj, "commit", "-q", "-m", "second")
    (joe.proj / "sync").mkdir()
    git(joe.proj, "bundle", "create", "-q", "sync/ahead.bundle", "main")
    shutil.copy(joe.proj / "sync" / "ahead.bundle", joe.sb.inbox / "ahead.bundle")
    shutil.copy(joe.proj / "sync" / "ahead.bundle", tmp_path / "outside.bundle")
    git(joe.proj, "reset", "-q", "--hard", first)
    joe.first = first
    return joe


@needs_git
def test_repo_status_of_a_listed_project(repo):
    out = repo.call("joe_repo", {"project": "hooah"})
    assert "Branch: main" in out and "first" in out and "Uncommitted changes" in out
    assert git(repo.proj, "rev-parse", "HEAD") == repo.first


@needs_git
@pytest.mark.parametrize("bundle", ["sync/ahead.bundle", "Inbox/ahead.bundle"])
def test_a_bundle_is_compared_but_never_pulled_unless_pull_is_really_true(repo, bundle):
    for pull in (None, False, "true", "yes", 1):
        out = repo.call("joe_repo", {"project": "hooah", "bundle": bundle, "pull": pull})
        assert "does NOT match the bundle" in out and git(repo.proj, "rev-parse", "HEAD") == repo.first
    repo.s.dev_projects[0]["pull"] = False                            # not ticked for this project: a real true still doesn't pull
    out = repo.call("joe_repo", {"project": "hooah", "bundle": bundle, "pull": True})
    assert out.startswith("Bringing a bundle into hooah isn't allowed.") and git(repo.proj, "rev-parse", "HEAD") == repo.first
    repo.s.dev_projects[0]["pull"] = True
    out = repo.call("joe_repo", {"project": "hooah", "bundle": bundle, "pull": True})
    assert out.startswith("Pulled the bundle into main:") and (repo.proj / "new.txt").exists()
    assert "matches the bundle" in repo.call("joe_repo", {"project": "hooah", "bundle": bundle})
    runs = (repo.sb.output / "dev" / "_runs.txt").read_text(encoding="utf-8")
    assert f"hooah / bundle pull ({bundle})  Pulled the bundle into main:" in runs      # every pull is written down


@needs_git
def test_pull_without_a_bundle_and_with_uncommitted_changes_changes_nothing(repo):
    assert repo.call("joe_repo", {"project": "hooah", "pull": True}).startswith("To pull, name the bundle file")
    (repo.proj / ".gitignore").write_text("changed\n", encoding="utf-8")
    out = repo.call("joe_repo", {"project": "hooah", "bundle": "sync/ahead.bundle", "pull": True})
    assert not out.startswith("Pulled") and git(repo.proj, "rev-parse", "HEAD") == repo.first


@needs_git
@pytest.mark.parametrize("bad", ["../outside.bundle", "sync/../../outside.bundle", "/etc/passwd", "C:/x.bundle",
                                 "Inbox/../../outside.bundle", "sync/nothing.bundle", "Output/.joe/x.bundle", ".git/config",
                                 ".gitignore", "sync/ahead.bundle:stream", "//server/share/x.bundle"])
def test_a_bundle_outside_the_project_and_the_inbox_is_refused(repo, bad, tmp_path):
    with pytest.raises(SandboxError):
        repo.call("joe_repo", {"project": "hooah", "bundle": bad, "pull": True})
    assert git(repo.proj, "rev-parse", "HEAD") == repo.first


@needs_git
def test_a_link_out_of_the_project_is_not_followed(repo, tmp_path):
    try:
        (repo.proj / "sync" / "link.bundle").symlink_to(tmp_path / "outside.bundle")
    except OSError:
        pytest.skip("this system doesn't allow making links")
    with pytest.raises(SandboxError):
        repo.call("joe_repo", {"project": "hooah", "bundle": "sync/link.bundle"})


def test_repo_needs_dev_tools_on_and_a_listed_project(joe):
    assert "No project called 'elsewhere'" in joe.call("joe_repo", {"project": "elsewhere"})
    assert "isn't" in joe.call("joe_repo", {"project": "hooah"}) or "not a git" in joe.call("joe_repo", {"project": "hooah"}).lower()
    joe.s.dev_tools = False
    assert joe.call("joe_repo", {"project": "hooah", "bundle": "x", "pull": True}) == dp.OFF


# ------------------------------------------------------------------ backups and the portable drive never carry it
def test_a_backup_never_brings_dev_tools_or_a_project_list_in(joe, tmp_path):
    """The 2026-11-27 review: a backup from someone else switched Dev tools on with its own commands."""
    from joeai import backup, portable
    made = backup.make(joe.s, joe.sb)
    import zipfile
    inside = json.loads(zipfile.ZipFile(made).read("settings.json"))
    assert "dev_tools" not in inside and "dev_projects" not in inside     # this PC's folders and commands stay here
    for p in (("dev_tools",), ("dev_projects",), ("mcp_folders",)):
        assert p in backup.NEVER_RESTORED
    carried = portable.portable_settings(joe.s)
    assert carried["dev_tools"] is False and carried["dev_projects"] == []


def test_restoring_a_backup_that_claims_dev_tools_changes_nothing_here(joe, tmp_path):
    import io
    import zipfile
    from joeai import backup
    fresh = Settings()
    fresh.workspace = joe.s.workspace
    evil = {"dev_tools": True, "mcp_folders": True,
            "dev_projects": [{"name": "x", "folder": str(tmp_path), "pull": True, "commands": [{"name": "c", "run": "whoami"}]}]}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("manifest.json", json.dumps({"kind": backup.MARK, "joe": "2.3.1"}))
        z.writestr("settings.json", json.dumps(evil))
    backup.restore(fresh, joe.sb, buf.getvalue())
    assert fresh.dev_tools is False and fresh.dev_projects == [] and fresh.mcp_folders is False
