"""Dev tools runs are always viewable ("there will never be anything done on Joe that isn't viewable"):
Joe's window must be open before a run or a bundle pull starts (the connector opens him if it is closed),
the window shows the run (state, last lines, STOP), STOP ends the whole process tree, and a chat can stop
its own run. Rules are written in joeai/devprojects.py's docstring."""
from __future__ import annotations

import http.client
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from joeai import devprojects as dp, devrun, i18n, mcp, server, system
from joeai.config import Settings

from test_core import env  # noqa: F401
from test_devprojects import PY, _wait_for, joe, project  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
REAL_WINDOW_OPEN, REAL_CANT_OPEN = mcp._window_open, mcp.cant_open_window            # (the tests below swap the module's own for fakes)
TREE = ("import os, subprocess, sys, time\n"
        "child = (\"import os, subprocess, sys, time\\n\"\n"
        "         \"g = subprocess.Popen([sys.executable, '-c', 'import os, time; open(\\\"grand.pid\\\", \\\"w\\\").write(str(os.getpid())); time.sleep(120)'])\\n\"\n"
        "         \"open('child.pid', 'w').write(str(os.getpid()))\\n\"\n"
        "         \"time.sleep(120)\\n\")\n"
        "subprocess.Popen([sys.executable, '-c', child])\n"
        "open('parent.pid', 'w').write(str(os.getpid()))\n"
        "print('tree started', flush=True)\n"
        "time.sleep(120)\n")


@pytest.fixture(autouse=True)
def _window_open(monkeypatch):
    monkeypatch.setattr(mcp, "_window_open", lambda: True)
    monkeypatch.setitem(mcp.CLIENT, "name", "Claude")


def dead(pid: int) -> bool:
    if system.WINDOWS:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True).stdout
        return str(pid) not in out
    return devrun._gone(pid)


def start_slow(joe, monkeypatch, name="slow", script="import time\nprint('started', flush=True)\ntime.sleep(60)\nprint('never')\n", wait=0.3):
    (joe.proj / "slow.py").write_text(script, encoding="utf-8")
    joe.s.dev_projects = [project(joe.proj, **{name: f"{PY} slow.py"}, tests=f"{PY} ok.py")]
    monkeypatch.setattr(dp, "WAIT_S", wait)
    return joe.call("joe_run_command", {"project": "hooah", "command": name})


# ------------------------------------------------------------------ the state is written and cleared
def test_the_state_is_written_while_it_runs_and_cleared_after(joe, monkeypatch):
    out = start_slow(joe, monkeypatch, script="import time\nprint('started', flush=True)\ntime.sleep(2)\nprint('7 passed, 0 failed')\n")
    assert "STILL RUNNING" in out
    note = json.loads((dp.state_dir() / "running.json").read_text(encoding="utf-8"))
    assert (note["project"], note["command"], note["who"], note["kind"]) == ("hooah", "slow", "Claude", "command")
    assert note["run"].endswith("slow.py") and note["pid"] > 0 and note["started"] > 0
    assert Path(note["log"]).parent == joe.sb.output / "dev" and note["what"] == "hooah / slow"
    assert _wait_for(lambda: (dp.state_dir() / "running.prog.json").exists(), 10)
    v = dp.view(joe.sb)
    assert v["running"]["who"] == "Claude" and v["running"]["can_stop"] and v["show"]
    monkeypatch.setattr(dp, "WAIT_S", 30)
    done = joe.call("joe_run_command", {"project": "hooah", "command": "slow"})
    assert "finished OK" in done
    assert not (dp.state_dir() / "running.json").exists() and not (dp.state_dir() / "running.prog.json").exists()
    v = dp.view(joe.sb)
    assert v["running"] is None and v["show"] and v["last"]["outcome"] == "ok" and v["last"]["totals"] == "7 passed, 0 failed"
    assert v["last"]["who"] == "Claude" and v["last"]["log"].startswith("Output/dev/hooah-slow-") and v["tail"][-1] == "7 passed, 0 failed"
    assert v["runs"] and "hooah / slow" in v["runs"][-1]


def test_a_run_that_ended_long_ago_is_not_shown(joe):
    joe.call("joe_run_command", {"project": "hooah", "command": "tests"})
    last = dp.state_dir() / "last.json"
    d = json.loads(last.read_text(encoding="utf-8"))
    d["ended"] -= dp.RECENT_S + 5
    last.write_text(json.dumps(d), encoding="utf-8")
    v = dp.view(joe.sb)
    assert v["show"] is False and v["running"] is None and v["runs"]            # the list of runs stays for RECENT RUNS


def test_the_app_name_comes_from_initialize(monkeypatch):
    monkeypatch.setitem(mcp.CLIENT, "name", "")
    r = mcp.handle(None, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                          "params": {"protocolVersion": "2025-06-18", "clientInfo": {"name": "claude-ai", "version": "1"}}})
    assert r["result"]["serverInfo"]["name"] == "joe" and mcp.CLIENT["name"] == "claude-ai"
    assert dp.app_name("") == "a connected app" and dp.app_name("<b>x</b>\n" * 30)[:3] == "bxb"


# ------------------------------------------------------------------ the endpoint
@pytest.fixture
def live(joe):
    app = server.App(joe.s)
    httpd = server.serve(app)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield app, httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


def call(port, method, path, token, body=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    h = {"Host": "127.0.0.1", "Content-Type": "application/json"}
    if token:
        h["X-NR-Token"] = token
    c.request(method, path, json.dumps(body) if body is not None else None, h)
    r = c.getresponse()
    data = json.loads(r.read().decode() or "{}")
    c.close()
    return r.status, data


def test_the_endpoint_gives_the_run_going_its_last_lines_and_the_recent_runs(joe, live, monkeypatch):
    app, port = live
    assert call(port, "GET", "/api/devrun", None)[0] == 401
    assert call(port, "POST", "/api/devrun/stop", "wrong", {})[0] == 401
    st, d = call(port, "GET", "/api/devrun", app.token)
    assert st == 200 and d["running"] is None and d["show"] is False and d["tail"] == []
    joe.call("joe_run_command", {"project": "hooah", "command": "tests"})            # one finished run for the list
    assert call(port, "GET", "/api/devrun", app.token)[1]["last"]["outcome"] == "ok"
    start_slow(joe, monkeypatch, script="import time\nfor i in range(5):\n    print('line', i, flush=True)\ntime.sleep(60)\n")
    assert _wait_for(lambda: "line 4" in "\n".join(call(port, "GET", "/api/devrun", app.token)[1]["tail"]), 15)
    st, d = call(port, "GET", "/api/devrun", app.token)
    assert d["running"]["what"] == "hooah / slow" and d["running"]["who"] == "Claude" and d["running"]["can_stop"] is True
    assert d["tail"][-5:] == [f"line {i}" for i in range(5)] and d["show"] is True
    assert len(d["runs"]) == 1 and "hooah / tests" in d["runs"][0]
    call(port, "POST", "/api/devrun/stop", app.token, {})
    assert _wait_for(lambda: call(port, "GET", "/api/devrun", app.token)[1]["running"] is None, 15)


def test_the_tail_reads_only_the_end_of_a_big_file(tmp_path, monkeypatch):
    big = tmp_path / "big.log"
    with open(big, "wb") as f:
        for i in range(2000):
            f.write((f"filler {i} " + "x" * 10_000 + "\n").encode())
        f.write(b"first of the end\r\nlast line\n\n")
    assert big.stat().st_size > 20_000_000
    seen = {"bytes": 0}
    real = open

    class Counting:
        def __init__(self, f):
            self.f = f

        def read(self, n=-1):
            data = self.f.read(n)
            seen["bytes"] += len(data)
            return data

        def __getattr__(self, k):
            return getattr(self.f, k)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.f.close()

    monkeypatch.setattr(dp, "open", lambda *a, **k: Counting(real(*a, **k)), raising=False)
    lines = dp.tail_lines(big, 3)
    assert lines[-2:] == ["first of the end", "last line"] and len(lines) == 3
    assert 0 < seen["bytes"] <= 70_000
    assert dp.tail_lines(tmp_path / "missing.log") == [] and dp.tail_lines(None) == []


def test_a_note_pointing_outside_output_dev_is_never_read(joe):
    secret = joe.sb.root.parent / "secret.txt"
    secret.write_text("do not show\n", encoding="utf-8")
    (dp.state_dir() / "running.json").write_text(json.dumps({
        "what": "hooah / x", "pid": os.getpid(), "until": time.time() + 500, "log": str(secret), "started": time.time()}), encoding="utf-8")
    v = dp.view(joe.sb)
    assert v["running"] and v["tail"] == [] and v["running"]["log"] == ""


# ------------------------------------------------------------------ STOP
def test_stop_ends_the_program_and_everything_it_started(joe, monkeypatch):
    (joe.proj / "tree.py").write_text(TREE, encoding="utf-8")
    joe.s.dev_projects = [project(joe.proj, tree=f"{PY} tree.py")]
    monkeypatch.setattr(dp, "WAIT_S", 0.3)
    assert "STILL RUNNING" in joe.call("joe_run_command", {"project": "hooah", "command": "tree"})
    pids = ("parent.pid", "child.pid", "grand.pid")
    assert _wait_for(lambda: all((joe.proj / f).exists() and (joe.proj / f).read_text() for f in pids), 20)
    ids = [int((joe.proj / f).read_text()) for f in pids]
    assert not any(dead(i) for i in ids)
    r = dp.stop_run(dp.WINDOW_STOP)
    assert r["ok"] and "stopped by the person in Joe's window" in r["message"]
    assert _wait_for(lambda: all(dead(i) for i in ids), 15), ids                  # the grandchild too
    assert not (dp.state_dir() / "running.json").exists() and dp._busy() == ""
    runs = (joe.sb.output / "dev" / "_runs.txt").read_text(encoding="utf-8")
    assert "STOPPED by the person in Joe's window" in runs
    last = dp.view(joe.sb)["last"]
    assert last["outcome"] == "stopped" and last["by"] == dp.WINDOW_STOP
    monkeypatch.setattr(dp, "WAIT_S", 30)
    assert "STOPPED by the person in Joe's window" in joe.call("joe_run_command", {"project": "hooah", "command": "tree"}).splitlines()[0]


def test_stop_by_force_when_the_minder_does_not_answer(joe, monkeypatch):
    start_slow(joe, monkeypatch)
    assert _wait_for(lambda: (dp.state_dir() / "running.prog.json").exists(), 10)
    prog = json.loads((dp.state_dir() / "running.prog.json").read_text(encoding="utf-8"))["pid"]
    monkeypatch.setattr(devrun, "_stop_asked", lambda spec: None)                 # (only affects this process; the minder is another program)
    r = dp.stop_run("Claude", wait_s=0, sb=joe.sb)                                # no time given: ended from here
    assert r["ok"] and _wait_for(lambda: dead(prog), 15)
    assert not (dp.state_dir() / "running.json").exists()
    assert "STOPPED by Claude" in (joe.sb.output / "dev" / "_runs.txt").read_text(encoding="utf-8")


def test_nothing_to_stop_says_so(joe):
    r = dp.stop_run()
    assert r == {"ok": False, "message": "Nothing is running right now."}


def test_the_time_limit_uses_the_same_tree_kill(joe, tmp_path, monkeypatch):
    killed = []
    real = devrun.kill_tree
    monkeypatch.setattr(devrun, "kill_tree", lambda pid: (killed.append(pid), real(pid))[1])
    spec = {"run": f"{PY} slow.py", "cwd": str(joe.proj), "log": str(tmp_path / "x.log"), "limit_s": 1, "minutes": 1,
            "cap_bytes": 10_000}
    (joe.proj / "slow.py").write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    res = devrun.run_spec(spec)
    assert res["ended"] == "limit" and len(killed) == 1 and killed[0] > 0
    assert _wait_for(lambda: dead(killed[0]), 10)
    killed.clear()
    spec.update(limit_s=60, stop=str(tmp_path / "stop.json"))
    (tmp_path / "stop.json").write_text(json.dumps({"by": "Claude", "run": "x"}), encoding="utf-8")      # x = this run's log name
    res = devrun.run_spec(spec)
    assert res["ended"] == "stopped" and res["by"] == "Claude" and len(killed) == 1


def test_kill_tree_uses_taskkill_on_windows_and_never_kills_joes_own_group(monkeypatch):
    calls = []
    monkeypatch.setattr(system, "WINDOWS", True)
    monkeypatch.setattr(subprocess, "run", lambda cmd, **k: calls.append(cmd))
    devrun.kill_tree(4321)
    assert calls == [["taskkill", "/PID", "4321", "/T", "/F"]]
    devrun.kill_tree(0)
    devrun.kill_tree("junk")
    assert len(calls) == 1
    if not system.WINDOWS and sys.platform != "win32":
        monkeypatch.setattr(system, "WINDOWS", False)
        sent = []
        monkeypatch.setattr(os, "killpg", lambda *a: sent.append(a))
        devrun.kill_tree(os.getpid())                                             # Joe's own group is never group-killed
        assert sent == []


# ------------------------------------------------------------------ a chat stops its own run
def test_a_chat_can_stop_only_its_own_run(joe, monkeypatch):
    start_slow(joe, monkeypatch)
    assert _wait_for(lambda: (dp.state_dir() / "running.prog.json").exists(), 10)
    prog = json.loads((dp.state_dir() / "running.prog.json").read_text(encoding="utf-8"))["pid"]
    other = joe.call("joe_stop_command", {"project": "hooah", "command": "tests"})
    assert "tests isn't running" in other and "hooah / slow" in other and not dead(prog)
    assert joe.call("joe_stop_command", {"project": "nope", "command": "x"}).startswith("No project called 'nope'")
    assert joe.call("joe_stop_command", {"project": "hooah", "command": "nope"}).startswith("No command called 'nope'")
    ok = joe.call("joe_stop_command", {"project": " Hooah ", "command": "SLOW"})
    assert "stopped by Claude" in ok and _wait_for(lambda: dead(prog), 15)
    assert "STOPPED by Claude" in (joe.sb.output / "dev" / "_runs.txt").read_text(encoding="utf-8")
    assert joe.call("joe_stop_command", {"project": "hooah", "command": "slow"}) == "Nothing is running right now."


def test_the_stop_tool_follows_the_dev_tools_switch(joe):
    names = lambda: [t["name"] for t in mcp._handle(joe, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]]  # noqa: E731
    assert "joe_stop_command" in names() and "joe_stop_command" in mcp.DEV_TOOLS
    joe.s.dev_tools = False
    assert "joe_stop_command" not in names()
    assert joe.call("joe_stop_command", {"project": "hooah", "command": "slow"}) == dp.OFF
    desc = next(t["description"] for t in mcp.TOOLS if t["name"] == "joe_stop_command")
    assert "joe_run_command" in desc and "STOP in Joe's window" in desc
    assert "shown in Joe's window" in next(t["description"] for t in mcp.TOOLS if t["name"] == "joe_run_command") or \
        "always shown in Joe's window" in next(t["description"] for t in mcp.TOOLS if t["name"] == "joe_run_command")


# ------------------------------------------------------------------ Joe must be open first
def test_a_run_opens_joe_when_his_window_is_closed_and_goes_ahead_when_it_reports_open(joe, monkeypatch):
    opened = []
    monkeypatch.setattr(mcp, "_window_open", lambda: False)
    monkeypatch.setattr(mcp, "_open_joe", lambda *a, **k: opened.append(1) or "")
    out = joe.call("joe_run_command", {"project": "hooah", "command": "tests"})
    assert opened == [1] and "finished OK" in out


def test_a_run_and_a_pull_refuse_with_a_reason_when_joe_cannot_be_opened(joe, monkeypatch):
    monkeypatch.setattr(mcp, "_window_open", lambda: False)
    monkeypatch.setattr(mcp, "_open_joe", lambda *a, **k: "Joe's window didn't open within 45 seconds.")
    out = joe.call("joe_run_command", {"project": "hooah", "command": "tests"})
    assert out == "Joe's window could not be opened, so nothing was run: Joe's window didn't open within 45 seconds."
    assert not list((joe.sb.output / "dev").glob("*.log")) and not (dp.state_dir() / "running.json").exists()
    (joe.proj / "x.bundle").write_bytes(b"x")
    out = joe.call("joe_repo", {"project": "hooah", "bundle": "x.bundle", "pull": True})
    assert out == "Joe's window could not be opened, so nothing was pulled in: Joe's window didn't open within 45 seconds."
    assert not (joe.sb.output / "dev" / "_runs.txt").exists()


def test_joe_is_not_opened_for_a_refused_or_listing_request_or_when_already_open(joe, monkeypatch):
    opened = []
    monkeypatch.setattr(mcp, "_open_joe", lambda *a, **k: opened.append(1) or "")
    monkeypatch.setattr(mcp, "_window_open", lambda: False)
    joe.call("joe_run_command", {})                                                # the list
    joe.call("joe_run_command", {"project": "nope", "command": "x"})
    joe.call("joe_repo", {"project": "hooah"})                                     # read-only status
    joe.s.dev_tools = False
    joe.call("joe_run_command", {"project": "hooah", "command": "tests"})
    assert opened == []
    joe.s.dev_tools = True
    monkeypatch.setattr(mcp, "_window_open", lambda: True)
    joe.call("joe_run_command", {"project": "hooah", "command": "tests"})
    assert opened == []
    joe.window_check = lambda: True                                                # the connector over Joe's own HTTP server: its page reported in
    monkeypatch.setattr(mcp, "_window_open", lambda: False)
    assert "finished OK" in joe.call("joe_run_command", {"project": "hooah", "command": "tests"}) and opened == []


def test_open_joe_starts_him_like_he_normally_starts_with_the_same_settings_file(tmp_path, monkeypatch):
    started = {}

    class Proc:
        def poll(self):
            return None

    def fake_popen(cmd, cwd=None, env=None):
        started.update(cmd=cmd, env=env)
        return Proc()

    answers = iter([False, False, True])
    monkeypatch.setattr(system, "popen_detached", fake_popen)
    monkeypatch.setattr(mcp, "_window_open", lambda: next(answers))
    monkeypatch.setattr(mcp.time, "sleep", lambda s: None)
    monkeypatch.setattr(system, "app_browser", lambda: "/usr/bin/some-browser")
    monkeypatch.delenv("JOE_NO_WINDOW", raising=False)
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "test-copy" / "settings.json"))
    assert mcp._open_joe(30) == ""
    assert started["cmd"] == system.joe_command("", console=False) and "Joe.pyw" in started["cmd"][1]
    assert started["env"]["JOE_CONFIG"] == str(tmp_path / "test-copy" / "settings.json")
    assert not any("chrome" in str(c).lower() or "http" in str(c).lower() for c in started["cmd"])    # never a browser


def test_open_joe_says_why_when_he_does_not_come_up(monkeypatch):
    class Dead:
        def poll(self):
            return 3

    monkeypatch.setattr(system, "app_browser", lambda: "/usr/bin/some-browser")
    monkeypatch.delenv("JOE_NO_WINDOW", raising=False)
    monkeypatch.setattr(system, "popen_detached", lambda *a, **k: Dead())
    monkeypatch.setattr(mcp, "_window_open", lambda: False)
    assert "closed again right after starting (code 3)" in mcp._open_joe(30)

    class Alive:
        def poll(self):
            return None

    monkeypatch.setattr(system, "popen_detached", lambda *a, **k: Alive())
    assert mcp._open_joe(0) == "Joe's window didn't open within 0 seconds."

    def boom(*a, **k):
        raise OSError("no such file")
    monkeypatch.setattr(system, "popen_detached", boom)
    assert mcp._open_joe(30) == "Joe couldn't be started (no such file)"


# ------------------------------------------------------------------ a pull is shown too
def test_a_pull_is_shown_while_it_happens_and_listed_after(joe, monkeypatch):
    from joeai import repostatus
    (joe.proj / "x.bundle").write_bytes(b"x")
    seen = {}

    def fake_pull(folder, bundle, branch):
        seen["note"] = dp.view(joe.sb)["running"]
        return "Pulled the bundle into main: fast-forward.\nmore detail"
    monkeypatch.setattr(repostatus, "pull_bundle", fake_pull)
    out = joe.call("joe_repo", {"project": "hooah", "bundle": "x.bundle", "pull": True})
    assert out.startswith("Pulled the bundle")
    assert seen["note"]["kind"] == "pull" and seen["note"]["who"] == "Claude" and seen["note"]["can_stop"] is False
    v = dp.view(joe.sb)
    assert v["running"] is None and v["last"]["outcome"] == "pull" and v["last"]["how"].startswith("Pulled the bundle")
    assert v["tail"] == ["Pulled the bundle into main: fast-forward.", "more detail"]
    assert "bundle pull (x.bundle)" in (joe.sb.output / "dev" / "_runs.txt").read_text(encoding="utf-8")
    seen.clear()
    monkeypatch.setattr(repostatus, "pull_bundle", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        joe.call("joe_repo", {"project": "hooah", "bundle": "x.bundle", "pull": True})
    assert not (dp.state_dir() / "running.json").exists()                          # let go even when it failed


def test_a_pull_cannot_be_stopped_half_way_and_waits_for_a_run(joe, monkeypatch):
    note = dp.begin_pull("hooah / bundle pull", "Claude", "hooah", "x.bundle")
    assert note and "can't be stopped" in dp.stop_run()["message"]
    assert "already running hooah / bundle pull" in joe.call("joe_run_command", {"project": "hooah", "command": "tests"})
    dp.end_pull(note, "Claude", "hooah / bundle pull", "hooah", "x.bundle", time.time(), "done")


# ------------------------------------------------------------------ the window text and Spanish
def _panel():
    html = (ROOT / "joeai" / "ui" / "index.html").read_text(encoding="utf-8")
    return (html[html.index('<section id="devrun"'):html.index('<section class="panel jobs">')]
            + html[html.index('<button type="button" id="devbadge"'):html.index('<span id="toolsbadge"')])


def _js_part():
    js = (ROOT / "joeai" / "ui" / "app.js").read_text(encoding="utf-8")
    return js[js.index("/* ---------------- Home: Dev tools run panel"):]


def test_every_new_line_has_spanish():
    p = i18n._HTML()
    p.feed(_panel())
    lines = p.out + i18n._js_text(_js_part())
    assert "[ OPEN THE LOG ]" in lines and "{1} — started by {2}" in lines and len(lines) > 15
    es = i18n.load("es")
    missing = [t for t in lines if t not in es]
    assert not missing, missing
    assert all(es[t] for t in lines)


def test_the_panel_is_reachable_and_announced_politely():
    html = _panel()
    assert 'id="devrun" class="panel devrun" aria-labelledby="devrun-h" hidden' in html
    assert 'id="devrun-status" role="status" aria-live="polite"' in html
    assert 'id="devrun-stop"' in html and 'aria-controls="devrun-runs"' in html and 'id="devbadge"' in html
    js = _js_part()
    assert "/api/devrun" in js and "/api/devrun/stop" in js and "setInterval(devRunTick, 2000)" in js
    assert "confirmBox(" in js and '"/api/open"' in js and 'how: "editor"' in js
    if (ROOT / "joeai" / "ui" / "app.js").exists() and __import__("shutil").which("node"):
        r = subprocess.run(["node", "--check", str(ROOT / "joeai" / "ui" / "app.js")], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr


# ====================================================================== review fixes (2026-11-28)
# ------------------------------------------------------------------ H1: the window's heartbeat
def _post_mcp(port, key, msg, sid=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
    h = {"Host": "127.0.0.1", "Content-Type": "application/json", "Authorization": f"Bearer {key}"}
    if sid:
        h["Mcp-Session-Id"] = sid
    c.request("POST", "/mcp", json.dumps(msg), h)
    r = c.getresponse()
    body = json.loads(r.read().decode() or "{}")
    got = r.getheader("Mcp-Session-Id")
    c.close()
    return r.status, body, got


def _tool(port, key, name, args, sid=None):
    st, body, _ = _post_mcp(port, key, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                        "params": {"name": name, "arguments": args}}, sid)
    return body["result"]["content"][0]["text"]


def test_the_window_heartbeat_is_only_the_pages_poll_with_the_key(joe, live):
    app, port = live
    assert call(port, "GET", "/api/ping", app.token)[1]["window"] is False and app.ui_seen == 0
    call(port, "GET", "/api/devrun", None)                                         # no key: nobody's page
    call(port, "GET", "/api/state", app.token)                                     # another question: not the heartbeat
    call(port, "GET", "/api/ping", app.token)                                      # the connector's question
    assert call(port, "GET", "/api/ping", app.token)[1]["window"] is False
    call(port, "GET", "/api/devrun", app.token)                                    # Joe's page polls
    assert call(port, "GET", "/api/ping", app.token)[1]["window"] is True and app.window_alive()
    app.ui_seen = time.monotonic() - server.WINDOW_FRESH_S - 1                     # silent for over 75 s
    assert call(port, "GET", "/api/ping", app.token)[1]["window"] is False


def test_the_page_says_goodbye_and_only_with_the_key(joe, live):
    app, port = live
    call(port, "GET", "/api/devrun", app.token)
    assert app.window_alive()
    assert call(port, "POST", "/api/window/bye", "wrong", {})[0] == 401 and app.window_alive()
    assert call(port, "POST", "/api/window/bye", None, {})[0] == 401 and app.window_alive()
    assert call(port, "POST", "/api/window/bye", app.token, {})[1] == {"ok": True}
    assert app.ui_seen == 0 and not app.window_alive()
    js = _js_part()
    assert '"/api/window/bye"' in js and "keepalive: true" in js and '"pagehide"' in js and '"X-NR-Token": TOKEN' in js


def test_window_open_in_the_connector_needs_the_heartbeat(joe, live, monkeypatch):
    app, port = live
    from joeai import app as app_mod
    lock = joe.sb.root.parent / "app.lock.json"
    lock.write_text(json.dumps({"port": port, "token": app.token}), encoding="utf-8")
    monkeypatch.setattr(app_mod, "_lock_path", lambda: lock)
    assert REAL_WINDOW_OPEN() is False                                              # Joe answers, nobody is looking
    call(port, "GET", "/api/devrun", app.token)
    assert REAL_WINDOW_OPEN() is True
    call(port, "POST", "/api/window/bye", app.token, {})
    assert REAL_WINDOW_OPEN() is False
    lock.unlink()
    assert REAL_WINDOW_OPEN() is False


def test_connector_pings_and_unkeyed_requests_keep_nothing_alive(joe, live):
    app, port = live
    app.last_seen = 5.0
    call(port, "GET", "/api/ping", app.token)
    call(port, "GET", "/api/state", None)                                          # no key
    call(port, "GET", "/api/devrun", "wrong")
    assert app.last_seen == 5.0 and app.ui_seen == 0
    call(port, "GET", "/api/state", app.token)
    assert app.last_seen > 5.0                                                     # the window's own questions do


def test_the_http_connector_opens_the_window_and_waits_for_the_heartbeat(joe, live, monkeypatch):
    app, port = live
    from joeai import app as app_mod
    joe.s.mcp_key = "k" * 30
    opened = []
    monkeypatch.setattr(mcp, "cant_open_window", lambda: "")
    monkeypatch.setattr(app_mod, "open_window", lambda url: (opened.append(url), setattr(app, "ui_seen", time.monotonic())))
    out = _tool(port, joe.s.mcp_key, "joe_run_command", {"project": "hooah", "command": "tests"})
    assert opened == [app.url] and app.url.startswith(f"http://127.0.0.1:{port}/#t=") and "finished OK" in out
    opened.clear()
    out = _tool(port, joe.s.mcp_key, "joe_run_command", {"project": "hooah", "command": "tests"})
    assert opened == [] and "finished OK" in out                                    # the page is reporting in: nothing to open


def test_the_http_connector_refuses_when_no_window_comes(joe, live, monkeypatch):
    app, port = live
    from joeai import app as app_mod
    joe.s.mcp_key = "k" * 30
    monkeypatch.setattr(mcp, "cant_open_window", lambda: "")
    monkeypatch.setattr(mcp, "OPEN_WAIT_S", 1)
    monkeypatch.setattr(app_mod, "open_window", lambda url: None)                   # JOE_NO_WINDOW or a window that never loads
    out = _tool(port, joe.s.mcp_key, "joe_run_command", {"project": "hooah", "command": "tests"})
    assert out == "Joe's window could not be opened, so nothing was run: Joe's window didn't open within 1 seconds."
    assert not list((joe.sb.output / "dev").glob("*.log")) and not (dp.state_dir() / "running.json").exists()
    monkeypatch.setattr(mcp, "cant_open_window", REAL_CANT_OPEN)
    monkeypatch.setenv("JOE_NO_WINDOW", "1")
    assert "JOE_NO_WINDOW" in _tool(port, joe.s.mcp_key, "joe_run_command", {"project": "hooah", "command": "tests"})


def test_a_run_with_no_window_opens_it_again_at_most_once_a_minute(joe, monkeypatch):
    app = server.App(joe.s)                                                         # (no server: its own loop would tick too)
    app.url = "http://127.0.0.1:9/#t=" + app.token
    from joeai import app as app_mod
    opened = []
    monkeypatch.setattr(mcp, "cant_open_window", lambda: "")
    monkeypatch.setattr(app_mod, "open_window", lambda url: opened.append(url))
    app.dev_window_tick()
    assert opened == []                                                             # nothing is running: nothing to show
    note = dp.begin_pull("hooah / bundle pull", "Claude", "hooah", "x.bundle")
    assert app.background_work() is True                                           # Joe doesn't quit on an idle window mid-run
    app.dev_window_tick()
    app.dev_window_tick()
    assert opened == [app.url]
    app._dev_reopen_at -= server.WINDOW_REOPEN_S + 1
    app.dev_window_tick()
    assert len(opened) == 2
    app.ui_seen = time.monotonic()                                                  # a page is there: left alone
    app._dev_reopen_at = -1e9
    app.dev_window_tick()
    assert len(opened) == 2
    dp.end_pull(note, "Claude", "hooah / bundle pull", "hooah", "x.bundle", time.time(), "done")
    assert app.background_work() is False


def test_two_first_requests_start_one_joe(joe, monkeypatch):
    state, started = {"open": False}, []
    monkeypatch.setattr(mcp, "_window_open", lambda: state["open"])

    def opener():
        started.append(1)
        time.sleep(0.3)
        state["open"] = True
        return ""
    monkeypatch.setattr(mcp, "_open_joe", opener)
    out = []
    ts = [threading.Thread(target=lambda: out.append(joe._window_ready("run"))) for _ in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert out == ["", ""] and started == [1]


def test_an_already_running_joe_reopens_his_window_when_started_again(monkeypatch):
    from joeai import app as app_mod, portable, profiles
    opened = []
    monkeypatch.setattr(portable, "start", lambda *a, **k: None)
    monkeypatch.setattr(profiles, "pick_for_launch", lambda *a, **k: None)
    monkeypatch.setattr(app_mod, "_existing_url", lambda: "http://127.0.0.1:1/#t=x")
    monkeypatch.setattr(app_mod, "open_window", lambda url: opened.append(url))
    assert app_mod.main() == 0 and opened == ["http://127.0.0.1:1/#t=x"]


# ------------------------------------------------------------------ the browser rule
def test_joe_is_never_opened_in_the_persons_own_browser_for_an_app(monkeypatch):
    started = []
    monkeypatch.setattr(system, "popen_detached", lambda *a, **k: started.append(a))
    monkeypatch.delenv("JOE_NO_WINDOW", raising=False)
    monkeypatch.setattr(system, "app_browser", lambda: None)                         # his window would fall back to webbrowser.open
    why = mcp._open_joe(5)
    assert "everyday browser" in why and started == []
    monkeypatch.setattr(system, "app_browser", lambda: "/usr/bin/some-browser")
    monkeypatch.setenv("JOE_NO_WINDOW", "1")
    assert "JOE_NO_WINDOW" in mcp._open_joe(5) and started == []
    monkeypatch.delenv("JOE_NO_WINDOW")
    assert mcp.cant_open_window() == ""


def test_a_run_refuses_when_joe_could_only_open_in_a_browser(joe, monkeypatch):
    monkeypatch.setattr(mcp, "_window_open", lambda: False)
    monkeypatch.setattr(system, "app_browser", lambda: None)
    monkeypatch.delenv("JOE_NO_WINDOW", raising=False)
    started = []
    monkeypatch.setattr(system, "popen_detached", lambda *a, **k: started.append(a))
    out = joe.call("joe_run_command", {"project": "hooah", "command": "tests"})
    assert out.startswith("Joe's window could not be opened, so nothing was run:") and "everyday browser" in out and started == []


# ------------------------------------------------------------------ H2: notes left by a restart or a crash
def _note(**kw):
    d = {"what": "hooah / slow", "project": "hooah", "command": "slow", "pid": os.getpid(), "until": time.time() + 900,
         "started": time.time(), "who": "Claude"}
    d.update(kw)
    st = dp.state_dir()
    (st / "running.json").write_text(json.dumps(d), encoding="utf-8")
    (st / "running.prog.json").write_text(json.dumps({"pid": 4242}), encoding="utf-8")
    (st / "stop.json").write_text(json.dumps({"by": "x"}), encoding="utf-8")
    return d


def test_a_note_from_before_the_last_boot_is_stale_and_removed_with_its_files(joe, monkeypatch):
    monkeypatch.setattr(devrun, "boot_time", lambda: time.time() - 600)
    _note(started=time.time() - 3600)                                              # the pid is alive (it is this test!): numbers are reused after a restart
    assert dp.running_note() is None
    st = dp.state_dir()
    assert not (st / "running.json").exists() and not (st / "running.prog.json").exists() and not (st / "stop.json").exists()
    assert dp._busy() == ""


def test_a_note_after_the_boot_or_when_the_boot_is_unknown_is_kept(joe, monkeypatch):
    monkeypatch.setattr(devrun, "boot_time", lambda: time.time() - 600)
    _note(started=time.time() - 100)
    assert dp.running_note() is not None
    monkeypatch.setattr(devrun, "boot_time", lambda: None)
    _note(started=time.time() - 99999)
    assert dp.running_note() is not None


def test_a_minder_that_is_the_very_same_program_is_not_called_old_by_a_wrong_clock(joe, monkeypatch):
    monkeypatch.setattr(devrun, "boot_time", lambda: time.time() - 600)
    _note(started=time.time() - 3600, born=devrun.proc_born(os.getpid()))
    assert dp.running_note() is not None


def test_boot_time_and_start_time_can_be_read_here(monkeypatch):
    monkeypatch.setattr(devrun, "_BOOT", [])
    b = devrun.boot_time()
    assert b is None or 0 < b <= time.time()
    me = devrun.proc_born(os.getpid())
    assert me is not None and devrun.same_born(me, devrun.proc_born(os.getpid()))
    assert devrun.proc_born(0) is None and devrun.proc_born("x") is None and not devrun.same_born(None, 1.0) and not devrun.same_born(1.0, 9.0)
    assert devrun.pid_alive(os.getpid()) and not devrun.pid_alive(0) and not devrun.pid_alive("junk")
    assert dp._alive(0) is True                                                    # no number yet: the time in the note decides


def test_boot_time_on_mac_and_start_time_on_mac_are_read_from_the_system(monkeypatch):
    monkeypatch.setattr(system, "WINDOWS", False)
    monkeypatch.setattr(system, "MAC", True)
    monkeypatch.setattr(devrun, "_BOOT", [])

    class R:
        def __init__(self, out):
            self.stdout = out
    outs = {"sysctl": "{ sec = 1700000000, usec = 12 } Tue Nov 14 22:13:20 2023\n", "ps": "Sat Nov 28 10:11:12 2026\n"}
    monkeypatch.setattr(subprocess, "run", lambda cmd, **k: R(outs[cmd[0]]))
    assert devrun.boot_time() == 1700000000.0
    born = devrun.proc_born(77)
    assert born == time.mktime(time.strptime("Sat Nov 28 10:11:12 2026", "%a %b %d %H:%M:%S %Y"))
    outs["ps"] = ""
    assert devrun.proc_born(77) is None                                            # can't be read: never force-killed


class _Fn:
    def __init__(self, f):
        self.f, self.restype, self.argtypes = f, None, None

    def __call__(self, *a):
        return self.f(*a)


class _K32:
    """A pretend kernel32 (only what Joe asks of it), so the Windows paths run on any PC. Every call is logged;
    `fns` gives a call its answer (anything else answers 1)."""
    def __init__(self, **fns):
        self.log, self._fns = [], fns

    def __getattr__(self, name):
        def call(*a):
            self.log.append((name, a))
            f = self._fns.get(name)
            return f(*a) if f else 1
        fn = _Fn(call)
        object.__setattr__(self, name, fn)
        return fn


def _win(monkeypatch, k32):
    import ctypes
    monkeypatch.setattr(system, "WINDOWS", True)
    monkeypatch.setattr(devrun, "_k32", lambda: k32)
    return ctypes


def _set(ref, **kw):
    for k, v in kw.items():
        setattr(ref._obj, k, v)
    return 1


def test_windows_alive_uses_openprocess_and_the_exit_code(monkeypatch):
    ctypes = _win(monkeypatch, None)
    for code, want in ((259, True), (0, False), (1, False)):                       # 259 = STILL_ACTIVE
        k = _K32(OpenProcess=lambda access, inherit, pid: 99, GetExitCodeProcess=lambda h, ref, code=code: _set(ref, value=code))
        monkeypatch.setattr(devrun, "_k32", lambda k=k: k)
        assert devrun.pid_alive(1234) is want
        assert k.log[0] == ("OpenProcess", (0x1000, False, 1234)) and k.log[-1][0] == "CloseHandle"
    k = _K32(OpenProcess=lambda *a: 0)
    monkeypatch.setattr(devrun, "_k32", lambda: k)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 87, raising=False)       # invalid parameter: no such program
    assert devrun.pid_alive(1234) is False
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 5, raising=False)        # access denied: it is there
    assert devrun.pid_alive(1234) is True
    monkeypatch.setattr(devrun, "_k32", lambda: None)
    assert devrun.pid_alive(1234) is True                                          # can't ask: not called gone


def test_windows_start_time_and_boot_time(monkeypatch):
    _win(monkeypatch, None)
    epoch_ft = 116444736000000000 + int(1_700_000_000 * 1e7)
    k = _K32(OpenProcess=lambda *a: 55, GetTickCount64=lambda: 3_600_000,
             GetProcessTimes=lambda h, c, e, kt, u: _set(c, lo=epoch_ft & 0xFFFFFFFF, hi=epoch_ft >> 32))
    monkeypatch.setattr(devrun, "_k32", lambda: k)
    assert abs(devrun.proc_born(4321) - 1_700_000_000) < 1e-3
    monkeypatch.setattr(devrun, "_BOOT", [])
    assert abs(devrun.boot_time() - (time.time() - 3600)) < 5


def test_the_job_object_ends_everything_when_it_closes_and_is_used_by_the_minder(monkeypatch):
    _win(monkeypatch, None)
    k = _K32(CreateJobObjectW=lambda *a: 777,
             SetInformationJobObject=lambda job, kind, ref, size: (kind, ref._obj.Basic.LimitFlags, size) and 1)
    monkeypatch.setattr(devrun, "_k32", lambda: k)
    job = devrun._make_job()
    assert job == 777
    kind, ref, size = next(a for n, a in k.log if n == "SetInformationJobObject")[1:]
    assert kind == 9 and ref._obj.Basic.LimitFlags == 0x2000 and size > 100          # extended limits, kill on close

    class P:
        _handle = 1234
    assert devrun._job_add(job, P()) is True and k.log[-1][0] == "AssignProcessToJobObject"
    devrun._job_kill(job)
    devrun._job_end(job)
    names = [n for n, _ in k.log]
    assert names.count("TerminateJobObject") == 2 and names.index("TerminateJobObject") < names.index("CloseHandle")
    devrun.end_leftovers(P(), None)                                                  # no job: nothing, and no error
    k2 = _K32(CreateJobObjectW=lambda *a: 5, SetInformationJobObject=lambda *a: 0)
    monkeypatch.setattr(devrun, "_k32", lambda: k2)
    assert devrun._make_job() is None and k2.log[-1][0] == "CloseHandle"             # Windows said no: taskkill still does it
    monkeypatch.setattr(devrun, "_k32", lambda: None)
    assert devrun._make_job() is None and devrun._job_add("J", P()) is False


def test_the_minder_puts_the_program_in_the_job_and_closes_it_at_the_end(joe, tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(devrun, "_make_job", lambda: "JOB")
    monkeypatch.setattr(devrun, "_job_add", lambda job, proc: seen.append(("add", job, proc.pid)) or True)
    monkeypatch.setattr(devrun, "_job_kill", lambda job: seen.append(("kill", job)))
    monkeypatch.setattr(devrun, "_job_end", lambda job: seen.append(("end", job)))
    spec = {"run": f"{PY} ok.py", "cwd": str(joe.proj), "log": str(tmp_path / "x.log"), "limit_s": 30, "minutes": 1, "cap_bytes": 100_000}
    res = devrun.run_spec(spec)
    assert res["code"] == 0 and seen[0][:2] == ("add", "JOB") and seen[-1] == ("end", "JOB") and seen.count(("end", "JOB")) == 1


def test_a_program_that_cannot_join_the_job_still_runs(joe, tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(devrun, "_make_job", lambda: "JOB")
    monkeypatch.setattr(devrun, "_job_add", lambda job, proc: False)
    monkeypatch.setattr(devrun, "_job_end", lambda job: seen.append(job))
    spec = {"run": f"{PY} ok.py", "cwd": str(joe.proj), "log": str(tmp_path / "x.log"), "limit_s": 30, "minutes": 1, "cap_bytes": 100_000}
    assert devrun.run_spec(spec)["code"] == 0 and seen == ["JOB"]                   # closed once, then run without it


@pytest.mark.skipif(system.WINDOWS, reason="process groups are for Mac and Linux")
def test_what_a_program_leaves_running_is_ended_when_it_ends(joe, tmp_path):
    (joe.proj / "leaver.py").write_text(
        "import subprocess, sys\n"
        "p = subprocess.Popen([sys.executable, '-c', 'import os, time; open(\"left.pid\", \"w\").write(str(os.getpid())); time.sleep(120)'])\n"
        "import time\nwhile True:\n    try:\n        open('left.pid').read().strip() and int(open('left.pid').read()); break\n    except Exception:\n        time.sleep(0.05)\n"
        "print('leaving', flush=True)\n", encoding="utf-8")
    spec = {"run": f"{PY} leaver.py", "cwd": str(joe.proj), "log": str(tmp_path / "x.log"), "limit_s": 60, "minutes": 1, "cap_bytes": 100_000}
    res = devrun.run_spec(spec)
    assert res["code"] == 0 and res["ended"] == ""
    left = int((joe.proj / "left.pid").read_text())
    assert _wait_for(lambda: dead(left), 10)


def test_kill_tree_never_ends_joes_own_program_or_his_parent(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **k: calls.append(cmd))
    monkeypatch.setattr(os, "kill", lambda *a: calls.append(a))
    monkeypatch.setattr(os, "killpg", lambda *a: calls.append(a), raising=False)   # Windows has no killpg
    for windows in (False, True):
        monkeypatch.setattr(system, "WINDOWS", windows)
        devrun.kill_tree(os.getpid())
        devrun.kill_tree(os.getppid())
        devrun.kill_tree(str(os.getpid()))
    assert calls == []


def test_a_program_with_another_start_time_is_not_ended_by_force(joe, monkeypatch):
    start_slow(joe, monkeypatch)
    assert _wait_for(lambda: (dp.state_dir() / "running.prog.json").exists(), 10)
    prog = json.loads((dp.state_dir() / "running.prog.json").read_text(encoding="utf-8"))
    note = json.loads((dp.state_dir() / "running.json").read_text(encoding="utf-8"))
    assert prog["born"] and note["born"] and prog["run"] == Path(note["log"]).stem          # written down with the numbers
    real = devrun.proc_born
    monkeypatch.setattr(devrun, "proc_born", lambda pid: 12345.0)                           # the numbers now belong to other programs
    r = dp.stop_run("Claude", wait_s=0, sb=joe.sb)
    assert r["ok"] and not dead(prog["pid"]) and not dead(note["pid"])                      # neither was touched
    monkeypatch.setattr(devrun, "proc_born", real)
    devrun.kill_tree(note["pid"])
    devrun.kill_tree(prog["pid"])


def test_a_program_whose_start_time_cannot_be_read_is_not_ended_and_it_says_so(joe, monkeypatch):
    start_slow(joe, monkeypatch)
    assert _wait_for(lambda: (dp.state_dir() / "running.prog.json").exists(), 10)
    prog = json.loads((dp.state_dir() / "running.prog.json").read_text(encoding="utf-8"))
    note = json.loads((dp.state_dir() / "running.json").read_text(encoding="utf-8"))
    real = devrun.proc_born
    monkeypatch.setattr(devrun, "proc_born", lambda pid: None)
    r = dp.stop_run("Claude", wait_s=0, sb=joe.sb)
    assert r["ok"] is False and "did not end anything by force" in r["message"] and "can't tell for sure" in r["message"]
    assert not dead(prog["pid"]) and (dp.state_dir() / "running.json").exists()             # still shown: it is still going
    monkeypatch.setattr(devrun, "proc_born", real)
    assert dp.stop_run("Claude", wait_s=10, sb=joe.sb)["ok"]                                  # the minder answers a stop when it can
    assert _wait_for(lambda: dead(prog["pid"]), 15)


def test_the_minder_ends_the_program_after_the_minder_in_the_force_path(joe, monkeypatch):
    start_slow(joe, monkeypatch)
    assert _wait_for(lambda: (dp.state_dir() / "running.prog.json").exists(), 10)
    prog = json.loads((dp.state_dir() / "running.prog.json").read_text(encoding="utf-8"))
    note = json.loads((dp.state_dir() / "running.json").read_text(encoding="utf-8"))
    order = []
    real = devrun.kill_tree
    monkeypatch.setattr(devrun, "kill_tree", lambda pid: (order.append(pid), real(pid))[1])
    monkeypatch.setattr(devrun, "_stop_asked", lambda spec: None)
    assert dp.stop_run("Claude", wait_s=0, sb=joe.sb)["ok"]
    assert order == [note["pid"], prog["pid"]]
    assert _wait_for(lambda: dead(prog["pid"]), 15)
    time.sleep(0.5)
    lines = (joe.sb.output / "dev" / "_runs.txt").read_text(encoding="utf-8").splitlines()
    assert len([ln for ln in lines if "hooah / slow" in ln]) == 1                              # one line, not two


# ------------------------------------------------------------------ M1: a stop is for one run
def test_a_minder_obeys_only_a_stop_that_names_its_own_run(joe, tmp_path):
    f = tmp_path / "stop.json"
    spec = {"run": f"{PY} slow.py", "cwd": str(joe.proj), "log": str(tmp_path / "mine-123.log"), "stop": str(f)}
    assert devrun.run_id(spec) == "mine-123"
    assert devrun._stop_asked(spec) is None
    f.write_text(json.dumps({"by": "Claude"}), encoding="utf-8")                              # names no run
    assert devrun._stop_asked(spec) is None
    f.write_text(json.dumps({"by": "Claude", "run": "other-456"}), encoding="utf-8")
    assert devrun._stop_asked(spec) is None
    f.write_text(json.dumps({"by": "Claude", "run": "mine-123"}), encoding="utf-8")
    assert devrun._stop_asked(spec) == "Claude"
    f.write_text(json.dumps({"run": "mine-123"}), encoding="utf-8")
    assert devrun._stop_asked(spec) == "the person in Joe's window"
    f.write_text("not json", encoding="utf-8")
    assert devrun._stop_asked(spec) is None
    (joe.proj / "short.py").write_text("import time\ntime.sleep(1)\nprint('done')\n", encoding="utf-8")
    f.write_text(json.dumps({"by": "Claude", "run": "other-456"}), encoding="utf-8")
    spec.update(run=f"{PY} short.py", limit_s=60, cap_bytes=10_000)
    res = devrun.run_spec(spec)
    assert res["ended"] == "" and res["code"] == 0                                             # someone else's stop does not end this run


def test_the_stop_note_names_the_run_and_a_new_run_is_left_alone(joe, monkeypatch):
    start_slow(joe, monkeypatch)
    assert _wait_for(lambda: (dp.state_dir() / "running.prog.json").exists(), 10)
    first = dp.running_note()
    prog = json.loads((dp.state_dir() / "running.prog.json").read_text(encoding="utf-8"))["pid"]
    monkeypatch.setattr(devrun, "_stop_asked", lambda spec: None)
    seen = iter([first, {**first, "log": str(Path(first["log"]).with_name("another-20991231-000000.log")), "what": "hooah / tests"}])
    monkeypatch.setattr(dp, "running_note", lambda: next(seen))
    r = dp.stop_run("Claude", wait_s=0, sb=joe.sb)                                              # the run it meant ended; another started
    assert r["ok"] and "hooah / tests has started since, and Joe left it alone" in r["message"] and not dead(prog)
    stop = json.loads((dp.state_dir() / "stop.json").read_text(encoding="utf-8"))
    assert stop["run"] == Path(first["log"]).stem and stop["by"] == "Claude"
    monkeypatch.undo()
    devrun.kill_tree(first["pid"])
    devrun.kill_tree(prog)


def test_a_run_that_is_only_just_starting_cannot_be_stopped_yet(joe):
    lock = dp._take_lock("hooah / slow", 60, {"project": "hooah", "command": "slow", "who": "Claude", "started": time.time()})
    assert lock and "only just starting" in dp.stop_run("Claude")["message"]
    lock.unlink()


# ------------------------------------------------------------------ LOW: whose run is it
def test_a_different_app_cannot_stop_a_run_it_did_not_start(joe, monkeypatch):
    start_slow(joe, monkeypatch)
    assert _wait_for(lambda: (dp.state_dir() / "running.prog.json").exists(), 10)
    prog = json.loads((dp.state_dir() / "running.prog.json").read_text(encoding="utf-8"))["pid"]
    monkeypatch.setitem(mcp.CLIENT, "name", "Some Other App")
    out = joe.call("joe_stop_command", {"project": "hooah", "command": "slow"})
    assert "was started by Claude, not by Some Other App, so nothing was stopped" in out and not dead(prog)
    monkeypatch.setitem(mcp.CLIENT, "name", "Claude")
    assert "stopped by Claude" in joe.call("joe_stop_command", {"project": "hooah", "command": "slow"})
    assert _wait_for(lambda: dead(prog), 15)


def test_each_http_session_has_its_own_app_name(joe, live, monkeypatch):
    app, port = live
    joe.s.mcp_key = key = "k" * 30
    app.ui_seen = time.monotonic()
    monkeypatch.setattr(dp, "WAIT_S", 0.3)
    init = lambda n: _post_mcp(port, key, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {  # noqa: E731
        "protocolVersion": "2025-06-18", "clientInfo": {"name": n, "version": "1"}}})
    (_, _, a), (_, _, b) = init("App-A"), init("App-B")
    assert a and b and a != b and app.mcp_sessions == {a: "App-A", b: "App-B"}
    assert mcp.CLIENT["name"] == "Claude"                                          # the one stdio connection's name is not touched
    out = _tool(port, key, "joe_run_command", {"project": "hooah", "command": "slow"}, a)
    assert "STILL RUNNING" in out
    assert _wait_for(lambda: (dp.state_dir() / "running.prog.json").exists(), 10)
    assert json.loads((dp.state_dir() / "running.json").read_text(encoding="utf-8"))["who"] == "App-A"
    assert "started by App-A, not by App-B" in _tool(port, key, "joe_stop_command", {"project": "hooah", "command": "slow"}, b)
    assert "stopped by App-A" in _tool(port, key, "joe_stop_command", {"project": "hooah", "command": "slow"}, a)
    for i in range(60):
        app.mcp_sessions[f"s{i}"] = "x"
    init("App-C")
    assert len(app.mcp_sessions) <= 50


def test_the_force_path_writes_only_inside_output_dev(joe, monkeypatch, tmp_path):
    start_slow(joe, monkeypatch)
    assert _wait_for(lambda: (dp.state_dir() / "running.prog.json").exists(), 10)
    note = json.loads((dp.state_dir() / "running.json").read_text(encoding="utf-8"))
    elsewhere = tmp_path / "elsewhere.txt"
    elsewhere.write_text("x\n", encoding="utf-8")
    note.update(log=str(elsewhere), runs=str(tmp_path / "evil-runs.txt"), result=str(tmp_path / "evil-result.json"))
    (dp.state_dir() / "running.json").write_text(json.dumps(note), encoding="utf-8")
    monkeypatch.setattr(devrun, "_stop_asked", lambda spec: None)
    assert dp.stop_run("Claude", wait_s=0, sb=joe.sb)["ok"]
    assert not (tmp_path / "evil-runs.txt").exists() and not (tmp_path / "evil-result.json").exists()
    assert dp.view(joe.sb)["last"]["log"] == "" and elsewhere.read_text() == "x\n"


# ------------------------------------------------------------------ M2: the last run stays as one line
def test_the_last_run_stays_as_a_collapsed_line_after_the_five_minutes(joe):
    joe.call("joe_run_command", {"project": "hooah", "command": "tests"})
    v = dp.view(joe.sb)
    assert v["show"] is True and v["collapsed"] is False
    last = dp.state_dir() / "last.json"
    d = json.loads(last.read_text(encoding="utf-8"))
    d["ended"] -= 2 * 3600
    last.write_text(json.dumps(d), encoding="utf-8")
    v = dp.view(joe.sb)
    assert v["show"] is False and v["collapsed"] is True and v["running"] is None
    assert v["last"]["what"] == "hooah / tests" and v["last"]["outcome"] == "ok" and 7000 < v["last"]["ago_s"] < 7400
    last.unlink()
    assert dp.view(joe.sb)["last"] is None


def test_the_page_keeps_one_line_for_the_last_run_and_announces_the_end():
    html, js = _panel(), _js_part()
    assert 'id="devrun-last"' in html and "Last run:" in html and 'id="devrun-last-ago"' in html
    assert 'id="devrun-end" class="devrun-end" role="status" aria-live="polite"' in html
    assert html.count('role="group"') == 2 and 'role="group" aria-label="The last lines the program printed"' in html
    assert 'role="group" aria-label="Recent runs"' in html
    assert "d.show" in js and "`${r.what} — ended`" in js and "`${devDur(r.ago_s || 0)} ago`" in js
    assert "const r = d && (d.running || d.last)" in js                            # a last-run note keeps at least the line on Home


# ------------------------------------------------------------------ LOW: odd notes and files
def test_notes_with_odd_numbers_never_break_the_window(joe):
    st = dp.state_dir()
    _note(started="yesterday", minutes="lots", log=str(joe.sb.output / "dev" / "x.log"))
    v = dp.view(joe.sb)
    assert v["running"]["secs"] >= 0 and v["running"]["minutes"] == 0
    (st / "running.json").unlink()
    (st / "last.json").write_text(json.dumps({"what": "a / b", "started": "no", "ended": "no", "secs": "no", "minutes": [1]}), encoding="utf-8")
    v = dp.view(joe.sb)
    assert v["last"]["secs"] == 0.0 and v["collapsed"] is True
    (st / "last.json").write_text(json.dumps({"what": "a / b", "ended": float("nan"), "started": float("inf")}), encoding="utf-8")
    assert dp.view(joe.sb)["last"]["what"] == "a / b"
    _note(started="yesterday")
    assert dp.stop_run("Claude", wait_s=0)["message"] == "That run is only just starting. Ask again in a moment."   # no log named: no 500, no guess


def test_the_end_of_one_very_long_line_is_still_shown(tmp_path):
    f = tmp_path / "one.log"
    f.write_text("a" * 200_000 + "THE END", encoding="utf-8")
    lines = dp.tail_lines(f)
    assert len(lines) == 1 and lines[0].endswith("THE END") and len(lines[0]) == dp.LINE_CHARS
    f.write_text("x" * 100_000 + "\nsecond line\n", encoding="utf-8")                           # a cut first line is still dropped
    assert dp.tail_lines(f, 5, 20_000) == ["second line"]
    f.write_text("head of a short line\n", encoding="utf-8")
    assert dp.tail_lines(f) == ["head of a short line"]


# ------------------------------------------------------------------ M3: Windows breakaway from the job
def test_on_windows_a_detached_program_asks_to_leave_the_job_and_retries_without(monkeypatch):
    seen = []

    def fake(cmd, **kw):
        seen.append(kw.get("creationflags"))
        if kw.get("creationflags", 0) & system.CREATE_BREAKAWAY_FROM_JOB:
            raise PermissionError("access denied")                                              # the job doesn't allow it
        return "proc"
    monkeypatch.setattr(system, "WINDOWS", True)
    monkeypatch.setattr(subprocess, "Popen", fake)
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, raising=False)
    assert system.popen_detached(["x"]) == "proc"
    assert seen[0] == 0x08000000 | 0x200 | 0x01000000 and seen[1] == 0x08000000 | 0x200 and len(seen) == 2
    seen.clear()
    assert system.popen_breakaway(["x"], 0x08000000, stdin=None) == "proc" and seen == [0x08000000 | 0x01000000, 0x08000000]
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: seen.append(kw.get("creationflags")) or "ok")
    seen.clear()
    assert system.popen_detached(["x"]) == "ok" and seen == [0x08000000 | 0x200 | 0x01000000]    # allowed the first time: one start


def test_the_minder_is_started_with_the_breakaway_helper(joe, monkeypatch):
    seen = []
    real = system.popen_breakaway
    monkeypatch.setattr(system, "popen_breakaway", lambda cmd, flags=0, **kw: (seen.append((cmd, flags)), real(cmd, flags, **kw))[1])
    assert "finished OK" in joe.call("joe_run_command", {"project": "hooah", "command": "tests"})
    assert seen and "devrun" in " ".join(seen[0][0])


# ------------------------------------------------------------------ the server's own words have Spanish
def test_the_stop_messages_have_spanish():
    es = i18n.load("es")
    for k in ("Nothing is running right now.",
              "{1} / {2} isn't running. What is running is {3}, so nothing was stopped.",
              "A bundle is being brought in right now. That takes a moment and can't be stopped half way; it will be over shortly.",
              "{1} was stopped by {2}. The program and everything it started were ended.",
              "Joe couldn't ask the run to stop ({1}).", "That run is only just starting. Ask again in a moment.",
              "{1} has ended. {2} has started since, and Joe left it alone.", "Last run:", "{1} ago", "{1} — ended"):
        assert es.get(k), k
    assert any(k.startswith("Joe asked {1} to stop but it didn't") and v for k, v in es.items())
