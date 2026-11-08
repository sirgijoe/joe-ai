"""Night shift "stop by" time (Reddit request, 2.1)."""
from __future__ import annotations

import json
import time
from datetime import datetime

from joeai import schedule
from joeai.config import Settings

from test_tools import app  # noqa: F401


def at(h, m=0, day=10):
    return datetime(2026, 11, day, h, m)


def test_stop_deadline_same_day_and_past_midnight():
    d = schedule.stop_deadline
    assert d("23:00", "", at(23)) is None                          # blank = run until done
    assert d("23:00", "23:00", at(23)) is None                     # same as start: ignored
    assert d("23:00", "06:00", at(23, 1)) == at(6, day=11)         # past midnight
    assert d("23:00", "06:00", at(2)) == at(6)                     # started late, still in the window
    assert d("23:00", "06:00", at(7)) == at(7)                     # outside: already past, run nothing
    assert d("01:00", "06:00", at(1, 5)) == at(6)                  # same day
    assert d("01:00", "06:00", at(6, 30)) == at(6, 30)
    assert d("", "07:00", at(8)) == at(7, day=11)                  # no start: the next 07:00


def test_bad_stop_time_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "s.json"))
    s = Settings()
    s.schedule.enabled, s.schedule.stop = True, "7am"
    r = schedule.apply(s)
    assert not r["ok"] and "07:00" in r["error"]


def test_tonight_outside_window_leaves_plans(tmp_path, monkeypatch):
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "settings.json"))
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    now = datetime.now()
    s.schedule.time = f"{(now.hour + 2) % 24:02d}:00"             # window starts later...
    s.schedule.stop = f"{(now.hour + 3) % 24:02d}:00"             # ...so now is outside it
    s.save()
    from joeai.sandbox import Sandbox
    sb = Sandbox(s.workspace_path).ensure()
    (sb.missions / "Tonight").mkdir(exist_ok=True)
    (sb.missions / "Tonight" / "p.txt").write_text("TASK: x  CHUNKS: 1 x 1")
    assert schedule.tonight() == 0
    assert (sb.missions / "Tonight" / "p.txt").exists()            # still waiting for the next night


def test_stop_time_leaves_unstarted_missions_for_tomorrow(app, monkeypatch):  # noqa: F811
    import threading
    from joeai.mission import parse
    calls = {"n": 0}

    def past():
        calls["n"] += 1
        return calls["n"] > 1                                      # first mission starts, then it's past
    monkeypatch.setattr(app, "_past_stop_time", past)
    app.settings.comfort.ntfy_topic = ""
    app.queue = []
    for name in ("First", "Second", "Third"):
        text = f"TASK: {name}  SAVE: {name.lower()}.md  CHUNKS: 1 x 2"
        app.queue.append((text, parse(text), {"label": name, "file": "", "unfinished": [name]}))
    app.chain, app.run_log, app.stop, app.accepting = [], [], threading.Event(), True
    app._work()                                                     # same loop the run thread uses
    left = sorted(p.name for p in (app.sb.missions / "Tonight").iterdir())
    assert left == ["second.txt", "third.txt"] and app.left_for_tomorrow == 2
    assert "TASK: Second" in (app.sb.missions / "Tonight" / "second.txt").read_text()
    rep = (app.sb.output / "_REPORT.md").read_text(encoding="utf-8")
    assert "## 2 missions left for tomorrow night" in rep and "- Third" in rep
    assert (app.sb.output / "first.md").exists() and not (app.sb.output / "second.md").exists()
    assert "2 missions left for tomorrow night" in app.finished["text"]


def test_read_stop_ignores_stale_files(tmp_path):
    from joeai.sandbox import Sandbox
    sb = Sandbox(tmp_path / "ws").ensure()
    sb.meta.mkdir(parents=True, exist_ok=True)
    (sb.meta / schedule.STOP_FILE).write_text(json.dumps({"until": "2020-01-01T06:00:00"}))
    assert schedule.read_stop(sb) is None
    soon = datetime.now().replace(microsecond=0)
    (sb.meta / schedule.STOP_FILE).write_text(json.dumps({"until": soon.isoformat()}))
    assert schedule.read_stop(sb) == soon
    schedule.clear_stop(sb)
    assert schedule.read_stop(sb) is None


# --------------------------------------------------------------------------- Other (OpenAI-compatible)
def _fake_openai(key=""):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    seen = {}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            seen["auth"] = self.headers.get("Authorization", "")
            if key and seen["auth"] != f"Bearer {key}":
                code, body = 401, b'{"error": "bad key"}'
            elif self.path == "/v1/models":
                code, body = 200, b'{"data": [{"id": "mistral-7b"}, {"id": "llama-3-8b"}]}'
            else:
                code, body = 404, b"{}"
            self.send_response(code)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}", seen


def _cfg(url, key="", model=""):
    from joeai.config import OllamaSettings
    c = OllamaSettings()
    c.engine, c.engine_url, c.engine_key, c.text_model = "openai", url, key, model
    return c


def test_test_connection_ok_key_and_model():
    from joeai import textengines
    srv, url, seen = _fake_openai(key="s3cret")
    try:
        r = textengines.test_connection(_cfg(url, "s3cret", "llama-3-8b"))
        assert r["ok"] and "using llama-3-8b" in r["say"] and seen["auth"] == "Bearer s3cret"
        r = textengines.test_connection(_cfg(url, "wrong"))
        assert not r["ok"] and "wants a key" in r["error"]
        r = textengines.test_connection(_cfg(url, "s3cret", "nope"))
        assert r["ok"] and "doesn't list the model 'nope'" in r["warning"]
        assert textengines.OpenAICompatClient(_cfg(url, "s3cret")).list_models() == ["mistral-7b", "llama-3-8b"]
    finally:
        srv.shutdown()


def test_test_connection_clear_errors():
    from joeai import textengines
    r = textengines.test_connection(_cfg("http://127.0.0.1:9"))
    assert not r["ok"] and "Nothing answered at http://127.0.0.1:9" in r["error"] and "running" in r["error"]
    r = textengines.test_connection(_cfg("https://api.openai.com"))
    assert not r["ok"] and "on the internet" in r["error"]


def test_engine_key_is_hidden_in_help_files():
    from joeai import support
    assert support.SECRET.search("engine_key")


def test_loose_times_are_fixed_then_confirmed(app):  # noqa: F811
    lt = schedule.loose_time
    assert [lt(x) for x in ("7am", "7 AM", "7:30 pm", "7.30 p.m.", "0700", "700", "19.30", "12am", "12pm",
                            "noon", "midnight", "7")] == \
        ["07:00", "07:00", "19:30", "19:30", "07:00", "07:00", "19:30", "00:00", "12:00", "12:00", "00:00", "07:00"]
    assert lt("13pm") is None and lt("banana") is None and lt("25:00") is None and lt("7:75") is None
    r = app.save_settings({"schedule": {"stop": "7am"}, "comfort": {"quiet_start": "10pm"}})
    assert not r["ok"] and app.settings.schedule.stop == ""         # nothing saved until they say yes
    assert {(f["path"], f["said"], f["fixed"]) for f in r["fixes"]} == \
        {("schedule.stop", "7am", "07:00"), ("comfort.quiet_start", "10pm", "22:00")}
    r = app.save_settings({"schedule": {"stop": "banana"}})
    assert not r["ok"] and "couldn't tell" in r["error"] and not r.get("fixes")
    assert app.save_settings({"schedule": {"stop": "07:00"}})["ok"] and app.settings.schedule.stop == "07:00"
    assert app.save_settings({"schedule": {"time": "23:00", "stop": ""}})["ok"]   # blank = until done


def test_start_problem_says_not_installed(monkeypatch):
    from joeai import textengines
    from joeai.config import OllamaSettings
    monkeypatch.setattr(textengines, "lms_cli", lambda: None)
    c = OllamaSettings()
    c.engine = "lmstudio"
    msg = textengines.start_problem(c, "http://127.0.0.1:1234")
    assert "couldn't find LM Studio" in msg and "lmstudio.ai" in msg and "back to Ollama" in msg
    c.engine = "openai"
    assert "Start it yourself" in textengines.start_problem(c, "http://127.0.0.1:8000")
    c.engine = "ollama"
    assert textengines.start_problem(c, "") == ""
