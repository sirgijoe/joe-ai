"""Token counts from a model's own tokenizer, on this PC, with nothing written by the model.

Why: an AI app connected to Joe (joe_count_tokens in mcp.py) has no tokenizer of its own, so it could
only guess how long a prompt or a training example is for the person's local model, or whether a
trim made a text shorter or longer for it. Joe asks the writing program instead.

How each writing program is asked (best first; the header of every answer says which was used):
  exact     the program's tokenizer call: llama.cpp POST /tokenize, LocalAI POST /v1/tokenize,
            vLLM POST /tokenize, KoboldCpp POST /api/extra/tokencount, and Ollama's
            POST /api/tokenize where that Ollama has it (asked for since 2024, not in every version;
            Joe trusts it only after it agrees with the count below on two test strings).
  counted   Ollama without that call: POST /api/generate with raw text and num_predict 0, and the
            prompt_eval_count it answers with. The model reads the text and writes nothing. Ollama
            cuts a prompt at the context size, so long text goes in pieces (split at line ends) that
            are added up; the start-of-text token Ollama adds is measured once and taken off.
  estimate  no tokenizer call at all (LM Studio's plain server, and others): about 3.5 characters a
            token, and the answer says ESTIMATE in capitals. Never passed off as a count.
"""
from __future__ import annotations

from .config import OllamaSettings
from .http import HttpError, request_json
from .textengines import ENGINES, auth_headers, engine_id, engine_url

CHARS_PER_TOKEN = 3.5           # the same rough figure as ollama.need_tokens
TIMEOUT = 600                   # the first call may have to load the model
_A, _B = "a", "a b c d e f g h"                 # two short test strings for checking a tokenizer call
_ollama_way: dict[tuple[str, str], dict] = {}   # (address, model) -> what was learned about that Ollama


def estimate(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN + 0.5) if text else 0


def reset() -> None:
    """Forget what was learned about each Ollama (tests)."""
    _ollama_way.clear()


# --------------------------------------------------------------------------- reading an answer
def _count_in(r) -> int | None:
    """The token count in a tokenizer call's answer, whatever that program calls it."""
    if not isinstance(r, dict):
        return None
    for key in ("count", "value", "token_count", "input_tokens", "length"):
        v = r.get(key)
        if isinstance(v, int) and not isinstance(v, bool) and v >= 0:
            return v
    for key in ("tokens", "token_ids", "ids"):
        v = r.get(key)
        if isinstance(v, list):
            return len(v)
    return None


def _post(url: str, payload: dict, headers: dict | None = None) -> int | None:
    """One tokenizer call. None = this program doesn't have it (or didn't understand the question)."""
    try:
        return _count_in(request_json("POST", url, payload, timeout=TIMEOUT, headers=headers))
    except HttpError as e:
        if e.kind:                       # couldn't reach the program at all: that's worth saying
            raise
        return None


# --------------------------------------------------------------------------- Ollama
def _generate_count(base: str, model: str, text: str, ctx: int) -> int:
    """prompt_eval_count for raw text with nothing written. Some Ollama versions leave the count
    out when num_predict is 0, so one token is allowed on a second try."""
    for predict in (0, 1):
        r = request_json("POST", f"{base}/api/generate",
                         {"model": model, "prompt": text, "raw": True, "stream": False,
                          "options": {"num_predict": predict, "num_ctx": ctx, "temperature": 0}},
                         timeout=TIMEOUT)
        n = r.get("prompt_eval_count") if isinstance(r, dict) else None
        if isinstance(n, int) and not isinstance(n, bool):
            return n
    raise HttpError(f"Ollama gave no prompt_eval_count for {model}")


def _ollama_tokenize(base: str, model: str, text: str) -> int | None:
    # The call isn't in a released Ollama Joe could be tested against, so the text goes under the
    # field names its proposals used and the answer is only trusted after _learn_ollama's check.
    # An Ollama without the call can also just drop the connection (seen on Windows, 2026-11-27:
    # "forcibly closed by the remote host" after /api/generate had answered fine), so any trouble
    # here means "no tokenizer call", never "Ollama is down": the reading count has already worked.
    try:
        return _post(f"{base}/api/tokenize", {"model": model, "text": text, "content": text, "prompt": text})
    except HttpError:
        return None


def _learn_ollama(base: str, model: str, ctx: int) -> dict:
    """Once per model: the tokens Ollama adds to every prompt, whether it under-reports text it has
    just seen (old versions left cached tokens out), and whether its tokenizer call can be trusted."""
    key = (base, model)
    if key in _ollama_way:
        return _ollama_way[key]
    a, b = _generate_count(base, model, _A, ctx), _generate_count(base, model, _B, ctx)
    again = _generate_count(base, model, _B, ctx)
    way = {"extra": max(0, a - 1), "steady": again == b, "tokenize": False}   # "a" is one token everywhere
    ta = _ollama_tokenize(base, model, _A)
    if ta is not None:
        tb = _ollama_tokenize(base, model, _B)
        way["tokenize"] = tb is not None and tb - ta == b - a
        way["tok_extra"] = max(0, ta - 1)
    _ollama_way[key] = way
    return way


def _pieces(text: str, size: int) -> list[str]:
    """Text in pieces of at most `size` characters, cut after a line end where there is one."""
    out, i = [], 0
    while i < len(text):
        j = min(len(text), i + size)
        if j < len(text):
            cut = text.rfind("\n", i + size // 2, j)
            if cut != -1:
                j = cut + 1
        out.append(text[i:j])
        i = j
    return out


def _ollama_counted(base: str, model: str, text: str, ctx: int, extra: int) -> tuple[int, int]:
    """(tokens, pieces) by reading. A piece that fills the window was cut by Ollama, so it is halved."""
    todo, total, pieces = _pieces(text, ctx * 2), 0, 0
    while todo:
        piece = todo.pop(0)
        try:
            n = _generate_count(base, model, piece, ctx)
        except HttpError as e:           # an Ollama that refuses a too-long prompt instead of cutting it
            if e.kind or len(piece) <= 400:
                raise
            n = ctx
        if n >= ctx - 8 and len(piece) > 1:
            half = len(piece) // 2
            cut = piece.rfind("\n", half // 2, half + half // 2)
            cut = cut + 1 if cut != -1 else half
            todo[:0] = [piece[:cut], piece[cut:]]
            continue
        total += max(0, n - extra)
        pieces += 1
    return total, pieces


# --------------------------------------------------------------------------- the other programs
def _llamacpp(base: str, model: str, text: str, headers: dict) -> int | None:
    return _post(f"{base}/tokenize", {"content": text, "add_special": False}, headers)


def _localai(base: str, model: str, text: str, headers: dict) -> int | None:
    return _post(f"{base}/v1/tokenize", {"model": model, "content": text}, headers)


def _vllm(base: str, model: str, text: str, headers: dict) -> int | None:
    return _post(f"{base}/tokenize", {"model": model, "prompt": text, "add_special_tokens": False}, headers)


def _kobold(base: str, model: str, text: str, headers: dict) -> int | None:
    return _post(f"{base}/api/extra/tokencount", {"prompt": text}, headers)


_WAYS = {"llamacpp": (_llamacpp,), "localai": (_localai, _llamacpp),
         "openai": (_llamacpp, _vllm, _localai, _kobold), "lmstudio": ()}


# --------------------------------------------------------------------------- one counter per call
class Counter:
    """Counts texts for one model on Setup's writing program. `how` is "exact", "counted" or
    "estimate"; `note` is the plain sentence for the answer's first line."""

    def __init__(self, cfg: OllamaSettings, model: str = "", ctx: int = 0):
        self.engine = engine_id(cfg)
        self.label = ENGINES[self.engine]["label"]
        self.base = (cfg.url if self.engine == "ollama" else engine_url(cfg)).rstrip("/")
        self.headers = auth_headers(cfg)
        self.model = model or cfg.text_model
        self.ctx = ctx
        self.how = ""
        self.note = ""
        self.pieces = 0                 # the most pieces any one text needed (Ollama, counted)
        self._fn = None

    def _set_up(self, text: str) -> None:
        if self.engine == "ollama":
            if not self.ctx:
                from .ollama import auto_ctx
                self.ctx = auto_ctx()
            way = _learn_ollama(self.base, self.model, self.ctx)
            if way["tokenize"]:
                extra = way["tok_extra"]
                self.how, self.note = "exact", "exact: Ollama's tokenizer call"
                self._fn = lambda t: self._exact_or_counted(t, extra)
            elif way["steady"]:
                self.how = "counted"
                self.note = ("counted by the model reading it, nothing written (this Ollama has no tokenizer "
                             "call; long text goes in pieces and can be off by a token or two per piece)")
                self._fn = self._counted
            else:
                self.how = "estimate"
                self.note = ("ESTIMATE ONLY, about 3.5 characters a token: this Ollama has no tokenizer call "
                             "and under-reports text it has just read, so its counts can't be trusted. "
                             "A newer Ollama fixes that")
                self._fn = estimate
            return
        for fn in _WAYS.get(self.engine, ()):
            if fn(self.base, self.model, text or _A, self.headers) is not None:
                self.how, self.note = "exact", f"exact: {self.label}'s tokenizer call"
                self._fn = lambda t, fn=fn: fn(self.base, self.model, t, self.headers) or 0
                return
        self.how = "estimate"
        self.note = (f"ESTIMATE ONLY, about 3.5 characters a token: {self.label} has no tokenizer call Joe "
                     "can use. For real counts, switch Setup > Writing program to Ollama or llama.cpp")
        self._fn = estimate

    def _exact_or_counted(self, text: str, extra: int) -> int:
        n = _ollama_tokenize(self.base, self.model, text)
        return self._counted(text) if n is None else max(0, n - extra)     # the call failed this once: read it instead

    def _counted(self, text: str) -> int:
        n, pieces = _ollama_counted(self.base, self.model, text, self.ctx, _ollama_way[(self.base, self.model)]["extra"])
        self.pieces = max(self.pieces, pieces)
        return n

    def count(self, text: str) -> int:
        if not text:
            return 0
        if self._fn is None:
            self._set_up(text)
        return self._fn(text)


# --------------------------------------------------------------------------- the answer, as a small table
def _n(v: int) -> str:
    return f"{v:,}"


def table(counter: Counter, rows: list[tuple[str, int, int]], skipped: list[str] | None = None) -> str:
    """rows = (what, tokens, characters). Two rows also get the difference (did a trim help?)."""
    head = f"[tokens | model {counter.model or '(the one loaded)'} | {counter.label} | {counter.note}]"
    w = max(6, *(len(_n(r[1])) for r in rows), len(_n(sum(r[1] for r in rows))))
    c = max(5, *(len(_n(r[2])) for r in rows), len(_n(sum(r[2] for r in rows))))
    lines = [head, f"{'tokens':>{w}}  {'chars':>{c}}  what"]
    lines += [f"{_n(t):>{w}}  {_n(ch):>{c}}  {what}" for what, t, ch in rows]
    if len(rows) > 1:
        lines.append(f"{_n(sum(r[1] for r in rows)):>{w}}  {_n(sum(r[2] for r in rows)):>{c}}  total")
    if len(rows) == 2:
        (a, ta, _), (b, tb, _) = rows
        d = tb - ta
        pct = f" ({d / ta * 100:+.1f}%)" if ta else ""
        word = "the same" if not d else f"{_n(abs(d))} tokens {'shorter' if d < 0 else 'LONGER'}{pct}"
        lines.append(f"{b} vs {a}: {word}")
    for s in skipped or []:
        lines.append(f"skipped: {s}")
    return "\n".join(lines)


def lines_table(counter: Counter, what: str, counts: list[tuple[int, int]], limit: int = 0, left_out: int = 0) -> str:
    """counts = (line number, tokens) for each non-empty line of one file (one example a line)."""
    head = f"[tokens per line | model {counter.model or '(the one loaded)'} | {counter.label} | {counter.note}]"
    if not counts:
        return f"{head}\n{what}: no lines with text."
    toks = sorted(t for _, t in counts)
    mid = toks[len(toks) // 2] if len(toks) % 2 else (toks[len(toks) // 2 - 1] + toks[len(toks) // 2]) // 2
    p95 = toks[min(len(toks) - 1, int(len(toks) * 0.95))]
    out = [head, f"{what}: {_n(len(counts))} lines, {_n(sum(toks))} tokens in all",
           f"shortest {_n(toks[0])} | middle {_n(mid)} | 95 in 100 are at most {_n(p95)} | longest {_n(toks[-1])}"]
    top = sorted(counts, key=lambda c: -c[1])[:5]
    out.append("longest lines: " + ", ".join(f"L{ln} ({_n(t)})" for ln, t in top))
    if limit:
        over = [(ln, t) for ln, t in counts if t > limit]
        out.append(f"over {_n(limit)} tokens: {_n(len(over))} of {_n(len(counts))}" +
                   (": " + ", ".join(f"L{ln}" for ln, _ in over[:40]) + (" ..." if len(over) > 40 else "") if over else ""))
    if left_out:
        out.append(f"({_n(left_out)} more lines not counted: the most in one call is {_n(len(counts))})")
    return "\n".join(out)
