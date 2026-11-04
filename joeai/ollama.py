"""Ollama client: talks to the local Ollama server directly (no agent harness)."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .config import OllamaSettings
from .http import request_json

_THINK = re.compile(r"<think>.*?</think>", re.S)


@dataclass
class ChatResult:
    text: str
    prompt_tokens: int
    output_tokens: int
    seconds: float


def auto_ctx() -> int:
    """Context size that leaves room on this PC's GPU (bigger cards get more)."""
    from .hardware import vram_total_gb
    v = vram_total_gb()
    return 8192 if v >= 16 else 6144 if v >= 10 else 4096


class OllamaClient:
    def __init__(self, cfg: OllamaSettings):
        self.cfg = cfg
        self.base = cfg.url.rstrip("/")

    def version(self, timeout: float = 3) -> str:
        return request_json("GET", f"{self.base}/api/version", timeout=timeout).get("version", "?")

    def list_models(self) -> list[str]:
        return [m["name"] for m in request_json("GET", f"{self.base}/api/tags").get("models", [])]

    def loaded_models(self) -> list[dict]:
        """Models currently in memory, with size and size_vram (from /api/ps)."""
        return request_json("GET", f"{self.base}/api/ps").get("models", [])

    def unload(self, model: str) -> None:
        request_json("POST", f"{self.base}/api/generate",
                     {"model": model, "keep_alive": 0}, timeout=60)

    def unload_all(self) -> list[str]:
        names = [m["name"] for m in self.loaded_models()]
        for n in names:
            self.unload(n)
        return names

    def chat(self, messages: list[dict], model: str | None = None, max_tokens: int | None = None,
             keep_alive: str | None = None, think: bool | None = None) -> ChatResult:
        payload = {
            "model": model or self.cfg.text_model,
            "messages": messages,
            "stream": False,
            "think": self.cfg.think if think is None else think,
            "options": {"num_ctx": self.cfg.num_ctx or auto_ctx(), "temperature": self.cfg.temperature},
        }
        if max_tokens:
            payload["options"]["num_predict"] = max_tokens
        if keep_alive:
            payload["keep_alive"] = keep_alive
        r = request_json("POST", f"{self.base}/api/chat", payload,
                         timeout=self.cfg.request_timeout_s)
        text = _THINK.sub("", r.get("message", {}).get("content", "")).strip()
        return ChatResult(
            text=text,
            prompt_tokens=int(r.get("prompt_eval_count", 0)),
            output_tokens=int(r.get("eval_count", 0)),
            seconds=r.get("total_duration", 0) / 1e9,
        )

    def chat_stream(self, messages: list[dict], model: str | None = None, max_tokens: int | None = None,
                    keep_alive: str | None = None):
        """Yield the reply a few words at a time (for talking: Joe starts speaking sooner)."""
        import json as _json
        import urllib.request
        payload = {"model": model or self.cfg.text_model, "messages": messages, "stream": True,
                   "think": self.cfg.think,
                   "options": {"num_ctx": self.cfg.num_ctx or auto_ctx(), "temperature": self.cfg.temperature}}
        if max_tokens:
            payload["options"]["num_predict"] = max_tokens
        if keep_alive:
            payload["keep_alive"] = keep_alive
        req = urllib.request.Request(f"{self.base}/api/chat", data=_json.dumps(payload).encode(),
                                     method="POST", headers={"Content-Type": "application/json"})
        in_think = False
        with urllib.request.urlopen(req, timeout=self.cfg.request_timeout_s) as r:
            for raw in r:
                try:
                    ev = _json.loads(raw)
                except ValueError:
                    continue
                if ev.get("error"):
                    raise RuntimeError(ev["error"])
                piece = (ev.get("message") or {}).get("content", "")
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
                if ev.get("done"):
                    return

    def embed(self, texts: list[str], model: str) -> list[list[float]]:
        """Search vectors for each text (Ollama's /api/embed), in order."""
        r = request_json("POST", f"{self.base}/api/embed", {"model": model, "input": texts, "keep_alive": "10m"},
                         timeout=self.cfg.request_timeout_s)
        out = r.get("embeddings") or []
        if len(out) != len(texts):
            raise ValueError("the search model gave back the wrong number of results")
        return out

    def warm(self, model: str, keep_alive: str = "20m") -> None:
        """Load a model into memory now, so the first real question doesn't wait for it."""
        request_json("POST", f"{self.base}/api/generate", {"model": model, "keep_alive": keep_alive},
                     timeout=120)
