"""Shared set-up for the agent tests: a Joe with a fake Ollama whose agent answers are scripted."""
from __future__ import annotations

import json
import time

import pytest

from joeai import agentrun, agents
from joeai.config import Settings
from joeai.server import App

from fake_ollama import FakeOllama

KINDS = {"plan": agentrun.PLAN_SYS, "pick": agentrun.PICK_SYS, "tick": agentrun.TICK_SYS,
         "review": agentrun.REVIEW_SYS, "claims": agentrun.CLAIMS_SYS, "verdict": agentrun.VERDICT_SYS,
         "check": "You check finished work"}
DEFAULT = {"plan": {"points": ["Do the job"]}, "pick": {"done": True}, "tick": "all", "review": {"on_track": True},
           "claims": {"claims": []}, "verdict": {"verdict": "confirmed", "source": 1}, "check": {"ok": True}}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "cfg" / "settings.json"))
    (tmp_path / "cfg").mkdir()
    fake = FakeOllama()
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    s.ollama.url = fake.url
    s.comfy.url = "http://127.0.0.1:9"
    s.engine.retry_backoff_s = 0
    s.engine.gpu_temp_pause_c = 0
    s.engine.keep_awake = False
    app = App(settings=s)
    script = {k: [] for k in KINDS}
    calls = {k: [] for k in KINDS}
    real = fake.chat

    def chat(req):
        sysmsg = req["messages"][0]["content"]
        for kind, prefix in KINDS.items():
            if sysmsg.startswith(prefix):
                with fake.lock:
                    fake.requests.append(req)
                    calls[kind].append(req["messages"][-1]["content"])
                nxt = script[kind].pop(0) if script[kind] else DEFAULT[kind]
                if nxt == "all":                       # tick every point
                    n = sum(1 for ln in req["messages"][-1]["content"].splitlines() if ln.startswith(("[ ] ", "[x] ")))
                    nxt = {"done": list(range(1, n + 1))}
                return 200, fake._reply(json.dumps(nxt) if isinstance(nxt, dict) else str(nxt))
        return real(req)
    fake.chat = chat
    agents.live_clear()
    yield app, fake, script, calls
    if app.thread:
        app.thread.join(60)
    fake.close()
    agents.live_clear()


def wait(app, secs=60):
    for _ in range(secs * 10):
        if not app.running:
            return
        time.sleep(0.1)
    raise AssertionError("run never finished")


def run(app, aid, files=None, request=""):
    r = app.enqueue(agents.mission_text(agents.get(aid), files, request))
    assert r["ok"], r
    wait(app)
    a = agents.get(aid)
    if "folder" not in (a.get("last_run") or {}):
        log = app.sb.output / "_log.txt"
        raise AssertionError("the run left no report:\n" + (log.read_text(encoding="utf-8")[-3000:] if log.exists() else "(no log)"))
    return a["last_run"], app.sb.output / a["last_run"]["folder"]


def make(data: dict, sb=None) -> str:
    """Save an agent (the window's way), saying yes to the screens of the abilities it turns on."""
    data = dict(data)
    data.setdefault("template", "maker")
    acks = {k: agents.ABILITIES[k]["version"] for k, v in (data.get("abilities") or {}).items() if v}
    data["acks"] = {**acks, **(data.get("acks") or {})}
    r = agents.save(data, sb)
    assert r["ok"], r
    return r["id"]
