"""LM Studio / llama.cpp / LocalAI writing engines (OpenAI-style client)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from joeai import textengines as te
from joeai.config import OllamaSettings, Settings


class _H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path == "/v1/models":
            self._send({"object": "list", "data": [{"id": "qwen3-14b"}, {"id": "text-embedding-nomic-embed-text-v1.5"}]})
        else:
            self._send({"error": "no"}, 404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _H.last = body
        if self.path == "/v1/chat/completions" and body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for piece in ["<think>hm</think>", "Hel", "lo"]:
                self.wfile.write(f"data: {json.dumps({'choices': [{'delta': {'content': piece}}]})}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
        elif self.path == "/v1/chat/completions":
            self._send({"choices": [{"message": {"content": "<think>x</think> Hi there"}}],
                        "usage": {"prompt_tokens": 5, "completion_tokens": 3}})
        elif self.path == "/v1/embeddings":
            self._send({"data": [{"index": i, "embedding": [float(i)]} for i in range(len(body["input"]))]})


def _server():
    srv = HTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}"


def test_engine_choice_and_urls():
    c = OllamaSettings()
    assert te.engine_id(c) == "ollama" and isinstance(te.make_client(c), te.OllamaClient)
    c.engine = "lmstudio"
    assert te.engine_url(c) == "http://127.0.0.1:1234"
    c.engine_url = "192.168.1.20:1234"
    assert te.engine_url(c) == "http://192.168.1.20:1234"
    c.engine_url = "https://api.example.com"           # online service: refused, usual address used
    assert te.engine_url(c) == "http://127.0.0.1:1234"
    c.engine = "nonsense"
    assert te.engine_id(c) == "ollama"


def test_params_from_name():
    assert te.params_from_name("qwen3-14b") == 14
    assert te.params_from_name("Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf") == 8
    assert te.params_from_name("smollm-360m") == 0.36
    assert te.params_from_name("mystery") == 0


def test_client_chat_stream_embed_models():
    srv, url = _server()
    try:
        c = OllamaSettings(engine="llamacpp", engine_url=url)
        cl = te.make_client(c)
        assert cl.version() == "llama.cpp (llama-server)"
        rows = cl.model_rows()
        assert rows[0]["name"] == "qwen3-14b" and rows[0]["writer"] and rows[0]["params"] == "14B"
        assert not rows[1]["writer"]
        r = cl.chat([{"role": "user", "content": "hi"}], max_tokens=10, think=False)
        assert r.text == "Hi there" and r.output_tokens == 3
        assert _H.last["max_tokens"] == 10 and _H.last["chat_template_kwargs"] == {"enable_thinking": False}
        assert "model" not in _H.last                  # blank = the loaded model
        assert "".join(cl.chat_stream([{"role": "user", "content": "x"}])) == "Hello"
        assert cl.embed(["a", "b"], "m") == [[0.0], [1.0]]
        assert cl.unload_all() == []
    finally:
        srv.shutdown()


def test_services_and_doctor_use_engine():
    from joeai import doctor
    from joeai.services import ServiceManager
    srv, url = _server()
    try:
        s = Settings()
        s.ollama.engine, s.ollama.engine_url = "lmstudio", url
        sm = ServiceManager(s, log=lambda m: None)
        assert sm.ollama_up()
        models = doctor.ollama_models(sm)
        assert [m["name"] for m in models if m["writer"]] == ["qwen3-14b"]
        assert doctor.resolve_text_model(s, sm, lambda m: None) == "qwen3-14b"
        issues = doctor._engine_issues([{"id": "pull-vision", "action": "pull"},
                                        {"id": "install-ollama", "tool": "ollama"},
                                        {"id": "install-pandoc", "action": "install-pandoc"}], s, True, models)
        assert [i["id"] for i in issues] == ["install-pandoc"]
        down = doctor._engine_issues([], s, False, [])
        assert down[0]["id"] == "start-ollama" and "LM Studio" in down[0]["text"]
    finally:
        srv.shutdown()
