"""Other writing engines: LM Studio, llama.cpp (llama-server) and LocalAI.

All three speak the same "OpenAI-style" language (/v1/models, /v1/chat/completions,
/v1/embeddings), so one small client covers them. It has the same methods as OllamaClient,
so the rest of Joe doesn't care which engine writes.

Only programs on this PC (or your own network) are used: there is no key box on purpose.
Joe never sends your work to a paid online service.
"""
from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path

from .config import OllamaSettings
from .http import HttpError, request_json
from .ollama import ChatResult, OllamaClient
from .system import WINDOWS

_THINK = re.compile(r"<think>.*?</think>", re.S)

# id -> what people see, the usual address, how to start it by hand
ENGINES: dict[str, dict] = {
    "ollama": {"label": "Ollama", "url": "http://127.0.0.1:11434",
               "how": "Joe starts Ollama by himself."},
    "lmstudio": {"label": "LM Studio", "url": "http://127.0.0.1:1234",
                 "how": "In LM Studio: Developer tab > Status: Running (or Joe runs 'lms server start' "
                        "for you). Load a model there, or let LM Studio load one when Joe asks."},
    "llamacpp": {"label": "llama.cpp (llama-server)", "url": "http://127.0.0.1:8080",
                 "how": "Start it with a model, for example: llama-server -m your-model.gguf --port 8080 "
                        "--ctx-size 8192. Put that line in Setup > Writing > Start command and Joe "
                        "starts it when he needs it."},
    "localai": {"label": "LocalAI", "url": "http://127.0.0.1:8080",
                "how": "Start LocalAI (for example: local-ai run) and install a model in its web page. "
                       "Put the start line in Setup > Writing > Start command if you want Joe to start it."},
    "openai": {"label": "Other (OpenAI-compatible)", "url": "http://127.0.0.1:8000",
               "how": "Any program on this PC or your home network that speaks the OpenAI-style "
                      "language (Jan, KoboldCpp, vLLM, Text Generation WebUI...). Put its address in "
                      "Setup > Writing > Address (for example http://127.0.0.1:1337 for Jan, :5001 for "
                      "KoboldCpp, :8000 for vLLM) and its start line in Start command if you want Joe to start it."},
}
NOT_WRITERS = re.compile(r"embed|nomic|bge|minilm|rerank|whisper|clip|vision-adapter|mmproj", re.I)


def engine_id(cfg: OllamaSettings) -> str:
    e = (getattr(cfg, "engine", "") or "ollama").strip().lower()
    return e if e in ENGINES else "ollama"


def engine_label(cfg: OllamaSettings) -> str:
    return ENGINES[engine_id(cfg)]["label"]


def engine_url(cfg: OllamaSettings) -> str:
    """Setup's engine address, else that engine's usual one."""
    e = engine_id(cfg)
    if e == "ollama":
        return cfg.url
    url = (getattr(cfg, "engine_url", "") or "").strip().rstrip("/")
    if url and not re.match(r"^https?://", url):
        url = "http://" + url
    return url if url and is_local(url) else ENGINES[e]["url"]     # never an online service


def is_local(url: str) -> bool:
    """This PC or a home-network address (no online services)."""
    host = re.sub(r"^\w+://", "", url).split("/")[0].rsplit(":", 1)[0].strip("[]").lower()
    return (host in ("localhost", "127.0.0.1", "::1", "0.0.0.0") or host.endswith(".local")
            or bool(re.match(r"^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)", host)))


def params_from_name(name: str) -> float:
    """'qwen3-14b-instruct' / 'Qwen3-14B-Q4_K_M.gguf' / 'llama-3.1-8b' -> 14 / 14 / 8 (billions)."""
    m = re.findall(r"(?<![\d.])(\d+(?:\.\d+)?)\s*([bm])(?![a-z])", name, re.I)
    best = 0.0
    for n, unit in m:
        v = float(n) / (1000 if unit.lower() == "m" else 1)
        best = max(best, v)
    return best


def lms_cli() -> str | None:
    """LM Studio's own command-line helper ('lms'), if it's on this PC."""
    hit = shutil.which("lms")
    if hit:
        return hit
    exe = "lms.exe" if WINDOWS else "lms"
    p = Path.home() / ".lmstudio" / "bin" / exe
    try:
        return str(p) if p.exists() else None
    except OSError:
        return None


def llama_server_exe() -> str | None:
    from .finder import find_tool
    return find_tool("llama-server", "", ("llama.cpp", "llama-cpp", "llamacpp"))


def localai_exe() -> str | None:
    from .finder import find_tool
    return find_tool("local-ai", "", ("LocalAI", "local-ai"))


def installed(cfg: OllamaSettings) -> str:
    """Path of something that starts the chosen engine ('' = not found)."""
    e = engine_id(cfg)
    if getattr(cfg, "engine_start", "").strip():
        return cfg.engine_start.strip()
    if e == "lmstudio":
        return lms_cli() or ""
    if e == "llamacpp":
        return llama_server_exe() or ""
    if e == "localai":
        return localai_exe() or ""
    return ""


def detect_running(timeout: float = 1.0) -> list[dict]:
    """Which OpenAI-style engines answer on their usual address right now (System check)."""
    out, seen = [], set()
    for eid, e in ENGINES.items():
        if eid == "ollama" or e["url"] in seen:
            continue
        try:
            r = request_json("GET", f"{e['url']}/v1/models", timeout=timeout)
        except (HttpError, OSError, ValueError):
            continue
        seen.add(e["url"])
        names = [m.get("id", "") for m in (r.get("data") or []) if isinstance(m, dict)]
        kind = eid
        if eid in ("llamacpp", "localai"):          # same port: tell them apart
            kind = "localai"
            try:
                request_json("GET", f"{e['url']}/props", timeout=timeout)
                kind = "llamacpp"
            except (HttpError, OSError, ValueError):
                pass
        out.append({"engine": kind, "label": ENGINES[kind]["label"], "url": e["url"], "models": names})
    return out


class OpenAICompatClient:
    """Same methods as OllamaClient, for LM Studio / llama.cpp / LocalAI."""

    def __init__(self, cfg: OllamaSettings):
        self.cfg = cfg
        self.engine = engine_id(cfg)
        self.base = engine_url(cfg)
        self.label = ENGINES[self.engine]["label"]

    # -- what's there ----------------------------------------------------
    def version(self, timeout: float = 3) -> str:
        request_json("GET", f"{self.base}/v1/models", timeout=timeout)
        return self.label

    def list_models(self) -> list[str]:
        r = request_json("GET", f"{self.base}/v1/models", timeout=10)
        return [m.get("id", "") for m in (r.get("data") or []) if isinstance(m, dict) and m.get("id")]

    def model_rows(self) -> list[dict]:
        """Rows shaped like doctor.ollama_models(). Sizes are guesses from the name (these engines
        don't say), about 0.6 GB per billion settings at the usual 4-bit size."""
        rows = []
        for name in self.list_models():
            b = params_from_name(name)
            rows.append({"name": name, "size_gb": round(b * 0.6, 1) if b else 0.0,
                         "params": f"{b:g}B" if b else "", "family": "", "digest": "",
                         "writer": not NOT_WRITERS.search(name)})
        return rows

    def loaded_models(self) -> list[dict]:
        if self.engine == "lmstudio":
            try:
                r = request_json("GET", f"{self.base}/api/v0/models", timeout=5)
                return [{"name": m.get("id", ""), "size": 1, "size_vram": 1}
                        for m in (r.get("data") or []) if m.get("state") == "loaded"]
            except (HttpError, OSError, ValueError):
                return []
        return []

    def unload(self, model: str) -> None:
        self.unload_all()

    def unload_all(self) -> list[str]:
        """Give the graphics card back for pictures. LM Studio: 'lms unload --all'. llama.cpp
        and LocalAI keep their model loaded (they have no unload call); Joe says so once."""
        if self.engine == "lmstudio":
            names = [m["name"] for m in self.loaded_models()]
            cli = lms_cli()
            if cli and names:
                import subprocess
                from .system import no_window_flags
                try:
                    subprocess.run([cli, "unload", "--all"], capture_output=True, timeout=60,
                                   creationflags=no_window_flags())
                except (OSError, subprocess.SubprocessError):
                    return []
                return names
        return []

    # -- writing ---------------------------------------------------------
    def _payload(self, messages, model, max_tokens, think, stream):
        p = {"model": model or self.cfg.text_model or "", "messages": messages,
             "temperature": self.cfg.temperature, "stream": stream}
        if max_tokens:
            p["max_tokens"] = int(max_tokens)
        want = self.cfg.think if think is None else think
        p["chat_template_kwargs"] = {"enable_thinking": bool(want)}   # llama.cpp + Qwen3; others ignore it
        if not p["model"]:
            p.pop("model")          # llama.cpp: the one loaded model
        return p

    def chat(self, messages: list[dict], model: str | None = None, max_tokens: int | None = None,
             keep_alive: str | None = None, think: bool | None = None) -> ChatResult:
        t0 = time.monotonic()
        r = request_json("POST", f"{self.base}/v1/chat/completions",
                         self._payload(messages, model, max_tokens, think, False),
                         timeout=self.cfg.request_timeout_s)
        choice = (r.get("choices") or [{}])[0]
        text = _THINK.sub("", (choice.get("message") or {}).get("content") or "").strip()
        u = r.get("usage") or {}
        return ChatResult(text=text, prompt_tokens=int(u.get("prompt_tokens", 0) or 0),
                          output_tokens=int(u.get("completion_tokens", 0) or 0),
                          seconds=time.monotonic() - t0)

    def chat_stream(self, messages: list[dict], model: str | None = None, max_tokens: int | None = None,
                    keep_alive: str | None = None, think: bool | None = None):
        import urllib.request
        payload = self._payload(messages, model, max_tokens, None, True)
        req = urllib.request.Request(f"{self.base}/v1/chat/completions", data=json.dumps(payload).encode(),
                                     method="POST", headers={"Content-Type": "application/json"})
        in_think = False
        with urllib.request.urlopen(req, timeout=self.cfg.request_timeout_s) as r:
            for raw in r:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    return
                try:
                    ev = json.loads(data)
                except ValueError:
                    continue
                if ev.get("error"):
                    raise RuntimeError(str(ev["error"]))
                piece = ((ev.get("choices") or [{}])[0].get("delta") or {}).get("content") or ""
                if "<think>" in piece:
                    in_think = True
                if in_think:
                    if "</think>" in piece:
                        in_think = False
                        piece = piece.split("</think>", 1)[1]
                    else:
                        continue
                if piece:
                    yield piece

    def embed(self, texts: list[str], model: str) -> list[list[float]]:
        r = request_json("POST", f"{self.base}/v1/embeddings", {"model": model, "input": texts},
                         timeout=self.cfg.request_timeout_s)
        rows = sorted(r.get("data") or [], key=lambda d: d.get("index", 0))
        out = [d.get("embedding") or [] for d in rows]
        if len(out) != len(texts):
            raise ValueError("the search model gave back the wrong number of results")
        return out

    def warm(self, model: str, keep_alive: str = "20m") -> None:
        try:
            self.chat([{"role": "user", "content": "hi"}], model=model, max_tokens=1, think=False)
        except (HttpError, OSError, ValueError):
            pass


def make_client(cfg: OllamaSettings):
    """The writing client for Setup's engine choice."""
    return OllamaClient(cfg) if engine_id(cfg) == "ollama" else OpenAICompatClient(cfg)
