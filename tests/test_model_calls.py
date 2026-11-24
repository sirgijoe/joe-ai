"""Model calls: a low temperature for answers that are a choice, a JSON schema where the reply is read as
JSON (asked again without it when the server refuses), and a warning when the model's window was full."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace

import pytest
from agent_env import env, make, run  # noqa: F401 (env is a fixture)
from fake_ollama import FakeOllama

from joeai import agentrun, chat, ollama
from joeai import textengines as te
from joeai.config import OllamaSettings, Settings
from joeai.engine import Engine
from joeai.mission import parse
from joeai.sandbox import Sandbox

SCHEMA = {"type": "object", "properties": {"category": {"type": "string"}}, "required": ["category"]}
HI = [{"role": "system", "content": "You sort things."}, {"role": "user", "content": "Write exactly 1 item."}]


@pytest.fixture
def fake():
    f = FakeOllama()
    yield f
    f.close()


def _client(url, **kw):
    return ollama.OllamaClient(OllamaSettings(url=url, num_ctx=4096, temperature=0.55, **kw))


# ------------------------------------------------------------------ C1: temperature and schema (Ollama)
def test_decide_temperature_is_low():
    assert ollama.DECIDE_TEMP == 0.1


def test_temperature_goes_to_ollama_and_the_setting_stays_the_default(fake):
    c = _client(fake.url)
    c.chat(HI)
    assert fake.requests[-1]["options"]["temperature"] == 0.55 and "format" not in fake.requests[-1]
    c.chat(HI, temperature=ollama.DECIDE_TEMP)
    assert fake.requests[-1]["options"]["temperature"] == 0.1
    list(c.chat_stream(HI, temperature=0.2))
    assert fake.requests[-1]["options"]["temperature"] == 0.2
    list(c.chat_stream(HI))
    assert fake.requests[-1]["options"]["temperature"] == 0.55


def test_schema_reaches_ollama_as_format(fake):
    r = _client(fake.url).chat(HI, schema=SCHEMA)
    assert fake.requests[-1]["format"] == SCHEMA and r.text


def test_a_server_that_refuses_format_still_answers():
    f = FakeOllama(refuse_format=True)
    try:
        r = _client(f.url).chat(HI, schema=SCHEMA, temperature=0.1)
        assert r.text.startswith("Sure!")
        assert len(f.requests) == 2 and "format" in f.requests[0] and "format" not in f.requests[1]
        assert f.requests[1]["options"]["temperature"] == 0.1
    finally:
        f.close()


# ------------------------------------------------------------------ C1: the OpenAI-style client
class _OpenAI(BaseHTTPRequestHandler):
    refuse = False
    bodies: list = []  # noqa: RUF012 (reset by the fixture)

    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _OpenAI.bodies.append(body)
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(f"data: {json.dumps({'choices': [{'delta': {'content': 'Hi'}}]})}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
        elif _OpenAI.refuse and "response_format" in body:
            self._send({"error": {"message": "response_format is not supported"}}, 400)
        else:
            self._send({"choices": [{"message": {"content": '{"category": "Mugs"}'}}],
                        "usage": {"prompt_tokens": 4090, "completion_tokens": 3}})


@pytest.fixture
def openai_url():
    _OpenAI.refuse, _OpenAI.bodies = False, []
    srv = HTTPServer(("127.0.0.1", 0), _OpenAI)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_openai_style_temperature_and_schema(openai_url):
    cl = te.make_client(OllamaSettings(engine="llamacpp", engine_url=openai_url, temperature=0.55, num_ctx=4096))
    r = cl.chat(HI)
    assert _OpenAI.bodies[-1]["temperature"] == 0.55 and "response_format" not in _OpenAI.bodies[-1]
    assert r.ctx == 0 and not r.full                # the window is set in that program: Joe can't know it
    cl.chat(HI, temperature=0.1, schema=SCHEMA)
    assert _OpenAI.bodies[-1]["temperature"] == 0.1
    assert _OpenAI.bodies[-1]["response_format"] == {"type": "json_schema",
                                                     "json_schema": {"name": "reply", "schema": SCHEMA}}
    "".join(cl.chat_stream(HI, temperature=0.2))
    assert _OpenAI.bodies[-1]["temperature"] == 0.2


def test_openai_style_server_that_refuses_the_schema_still_answers(openai_url):
    _OpenAI.refuse = True
    cl = te.make_client(OllamaSettings(engine="llamacpp", engine_url=openai_url))
    r = cl.chat(HI, schema=SCHEMA)
    assert r.text == '{"category": "Mugs"}'
    assert len(_OpenAI.bodies) == 2 and "response_format" not in _OpenAI.bodies[1]


# ------------------------------------------------------------------ C2: a full window
def test_full_window_is_seen():
    f = FakeOllama(prompt_eval=4096)
    try:
        r = _client(f.url).chat(HI)
        assert r.ctx == 4096 and r.full
    finally:
        f.close()


def test_room_left_is_not_full(fake):
    r = _client(fake.url).chat(HI)
    assert r.ctx == 4096 and not r.full
    assert not ollama.ChatResult("x", 9000, 1, 0.1).full          # window unknown: never "full"


def _engine_env(tmp_path, monkeypatch, f):
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "settings.json"))
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    s.ollama.url = f.url
    s.ollama.num_ctx = 4096
    s.ollama.temperature = 0.55
    s.comfy.url = "http://127.0.0.1:9"
    s.engine.retry_backoff_s = 0
    s.engine.gpu_temp_pause_c = 0
    s.engine.keep_awake = False
    return s, Sandbox(s.workspace_path).ensure()


def test_engine_flags_a_full_window_once_per_task(tmp_path, monkeypatch):
    f = FakeOllama(prompt_eval=4096)
    try:
        s, sb = _engine_env(tmp_path, monkeypatch, f)
        logs = []
        st = Engine(s, sb, log=logs.append).run_mission(parse(
            "=== JOE MISSION ===\nTASK: Jokes\nCHUNKS: 2 x 3\nFORMAT: One line.\n=== END ==="))[0]
        full = [x for x in st.flags if "window was full" in x["flag"]]
        assert len(full) == 1 and "part 1" in full[0]["flag"] and "Setup > Writing" in full[0]["flag"]
        assert len([m for m in logs if "window was full" in m]) == 1
    finally:
        f.close()


def test_engine_says_nothing_when_there_was_room(tmp_path, monkeypatch, fake):
    s, sb = _engine_env(tmp_path, monkeypatch, fake)
    logs = []
    st = Engine(s, sb, log=logs.append).run_mission(parse(
        "=== JOE MISSION ===\nTASK: Jokes\nCHUNKS: 2 x 3\nFORMAT: One line.\n=== END ==="))[0]
    assert not [x for x in st.flags if "window was full" in x["flag"]]
    assert not [m for m in logs if "window was full" in m]


# ------------------------------------------------------------------ C3: which calls decide
def test_categorizing_rows_decides_and_writing_keeps_the_setting(tmp_path, monkeypatch, fake):
    s, sb = _engine_env(tmp_path, monkeypatch, fake)
    (sb.inbox / "stock.csv").write_text("Name,Product\nAnn,Blue mug\nBo,Big bowl\nCy,Flat plate\n", encoding="utf-8")
    st = Engine(s, sb, log=lambda m: None).run_mission(parse(
        "TASK: Stock  TYPE: tidy-sheet\nINPUT: stock.csv\nOPTIONS: categorize\n"
        "FORMAT: categories: Mugs, Bowls, Plates"))[0]
    assert st.status == "done", st.note
    sort = [r for r in fake.requests if r["messages"][0]["content"].startswith("You sort spreadsheet rows")]
    assert sort and all(r["options"]["temperature"] == 0.1 for r in sort)
    assert all(r["format"]["type"] == "array" for r in sort)
    fake.requests.clear()
    Engine(s, sb, log=lambda m: None).run_mission(parse(
        "=== JOE MISSION ===\nTASK: Jokes\nCHUNKS: 1 x 3\nFORMAT: One line.\n=== END ==="))
    assert fake.requests and all(r["options"]["temperature"] == 0.55 and "format" not in r for r in fake.requests)


def test_categorizing_still_works_when_the_server_refuses_format(tmp_path, monkeypatch):
    f = FakeOllama(refuse_format=True)
    try:
        s, sb = _engine_env(tmp_path, monkeypatch, f)
        (sb.inbox / "stock.csv").write_text("Name,Product\nAnn,Blue mug\nBo,Big bowl\nCy,Flat plate\n",
                                            encoding="utf-8")
        st = Engine(s, sb, log=lambda m: None).run_mission(parse(
            "TASK: Stock  TYPE: tidy-sheet\nINPUT: stock.csv\nOPTIONS: categorize\n"
            "FORMAT: categories: Mugs, Bowls, Plates"))[0]
        assert st.status == "done", st.note
        from joeai.sheets import read_table
        _, rows, _ = read_table(sb.output / st.output / "stock-tidy.csv")
        assert rows[0][-1] == "Mugs" and rows[1][-1] == "Bowls"
    finally:
        f.close()


def test_search_words_are_a_decision():
    seen = []

    def ask(msgs, **kw):
        seen.append(kw)
        return ollama.ChatResult("kiln cone 6", 1, 1, 0.1)
    app = SimpleNamespace(services=SimpleNamespace(ollama=SimpleNamespace(chat=ask)), leaky_models=set())
    assert chat._search_words(app, [], "how hot is cone 6 in a kiln?", "m", False, "", "") == "kiln cone 6"
    assert seen[0]["temperature"] == ollama.DECIDE_TEMP


def test_agent_picks_its_step_with_a_low_temperature(env):  # noqa: F811
    app, fake, script, _calls = env
    app.settings.ollama.temperature = 0.55
    aid = make({"name": "Guide", "job": "write a short guide to watering houseplants", "tools": ["text"], "steps": 3})
    script["plan"] = [{"points": ["A short guide to watering houseplants"]}]
    script["pick"] = [{"action": "write", "title": "Watering", "instruction": "the guide"}]
    script["tick"] = [{"done": [1]}]
    run(app, aid)

    def temps(prefix):
        return [r["options"]["temperature"] for r in fake.requests if r["messages"][0]["content"].startswith(prefix)]
    assert temps(agentrun.PICK_SYS) and set(temps(agentrun.PICK_SYS)) == {0.1}
    assert temps(agentrun.PLAN_SYS) and set(temps(agentrun.PLAN_SYS)) == {0.55}
