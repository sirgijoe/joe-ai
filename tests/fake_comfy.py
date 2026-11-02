"""A fake ComfyUI server for tests: accepts /prompt, 'renders' a tiny PNG."""
from __future__ import annotations

import base64
import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg==")


class FakeComfy:
    def __init__(self, checkpoints=("SDXL\\example_sdxl_model.safetensors", "v1-5-pruned-emaonly.safetensors"),
                 frames: int = 1, fail_prompt: bool = False):
        self.checkpoints = list(checkpoints)
        self.frames = frames
        self.fail_prompt = fail_prompt
        self.graphs: list[dict] = []
        self.history: dict = {}
        self.freed = 0
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, code, obj):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                u = urlparse(self.path)
                if u.path == "/system_stats":
                    return self._json(200, {"system": {"os": "fake"}})
                if u.path == "/object_info/CheckpointLoaderSimple":
                    return self._json(200, {"CheckpointLoaderSimple": {"input": {"required": {
                        "ckpt_name": [fake.checkpoints]}}}})
                if u.path.startswith("/object_info/"):
                    return self._json(200, {})
                if u.path.startswith("/history/"):
                    pid = u.path.rsplit("/", 1)[1]
                    return self._json(200, {pid: fake.history[pid]} if pid in fake.history else {})
                if u.path == "/view":
                    q = parse_qs(u.query)
                    assert q["filename"][0].endswith(".png")
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(PNG)))
                    self.end_headers()
                    self.wfile.write(PNG)
                    return
                self._json(404, {})

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                req = json.loads(self.rfile.read(n) or b"{}")
                if self.path == "/free":
                    fake.freed += 1
                    return self._json(200, {})
                if self.path == "/interrupt":
                    return self._json(200, {})
                if self.path == "/prompt":
                    g = req["prompt"]
                    if fake.fail_prompt:
                        return self._json(400, {"error": "bad", "node_errors": {"4": "missing model"}})
                    fake.graphs.append(g)
                    pid = uuid.uuid4().hex
                    imgs = [{"filename": f"NR_{len(fake.graphs):05d}_{i}.png", "subfolder": "Joe",
                             "type": "output"} for i in range(fake.frames)]
                    fake.history[pid] = {"outputs": {"9": {"images": imgs}},
                                         "status": {"status_str": "success", "completed": True}}
                    return self._json(200, {"prompt_id": pid, "number": 1, "node_errors": {}})
                self._json(404, {})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
