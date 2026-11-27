"""joe_count_tokens (2.4.0.dev1): real token counts for a connected AI app, which has no tokenizer.

The pretend writing programs here count one token a word (split on spaces and line ends), so every
expected number can be checked by hand. The pretend Ollama adds a start-of-text token and cuts a
prompt at num_ctx, as the real one does."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from joeai import mcp, tokens
from joeai.config import Settings
from joeai.sandbox import SandboxError

from test_core import env  # noqa: F401

CLOSED = ('That folder is closed to connected apps. The person can open it in Joe: '
          'Setup > Other AI apps > "Apps connected to Joe may read my Inbox and other folders".')


def words(text: str) -> int:
    return len(text.split())


class Pretend:
    """kind: "ollama" (no tokenizer call), "ollama-new" (has /api/tokenize), "ollama-bad-call" (has one
    that answers nonsense), "ollama-forgetful" (leaves out text it has just read), "llamacpp",
    "localai", "vllm", "kobold", "lmstudio" (no tokenizer call at all)."""

    def __init__(self, kind: str):
        self.kind = kind
        self.calls: list[tuple[str, dict]] = []
        self.seen: set[str] = set()
        me = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, obj):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/api/version":
                    self._send(200, {"version": "0.pretend"})
                elif self.path == "/api/tags":
                    self._send(200, {"models": [{"name": "qwen3:14b"}, {"name": "llama3.1:8b"}]})
                elif self.path == "/v1/models":
                    self._send(200, {"data": [{"id": "some-model"}]})
                else:
                    self._send(404, {})

            def do_POST(self):
                req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                me.calls.append((self.path, req))
                k, path = me.kind, self.path
                if k.startswith("ollama") and path == "/api/generate":
                    assert req["raw"] is True and req["stream"] is False
                    assert req["options"]["num_predict"] in (0, 1)        # nothing (or one token) written
                    n = min(1 + words(req["prompt"]), req["options"]["num_ctx"])
                    if k == "ollama-forgetful" and req["prompt"] in me.seen:
                        n = 1
                    me.seen.add(req["prompt"])
                    self._send(200, {"done": True, "response": "", "prompt_eval_count": n})
                elif k == "ollama-new" and path == "/api/tokenize":
                    self._send(200, {"tokens": list(range(1 + words(req["text"])))})
                elif k == "ollama-drops" and path == "/api/tokenize":
                    self.connection.close()                               # no answer at all: the line just goes dead
                    return
                elif k == "ollama-bad-call" and path == "/api/tokenize":
                    self._send(200, {"count": 7})
                elif k == "llamacpp" and path == "/tokenize" and "content" in req:
                    self._send(200, {"tokens": list(range(words(req["content"])))})
                elif k == "localai" and path == "/v1/tokenize":
                    self._send(200, {"tokens": list(range(words(req["content"])))})
                elif k == "vllm" and path == "/tokenize" and "prompt" in req:
                    self._send(200, {"count": words(req["prompt"]), "max_model_len": 4096})
                elif k == "kobold" and path == "/api/extra/tokencount":
                    self._send(200, {"value": words(req["prompt"])})
                else:
                    self._send(404, {"error": "no such call"})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def paths(self) -> list[str]:
        return [p for p, _ in self.calls]


@pytest.fixture
def make(tmp_path, monkeypatch):
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "settings.json"))
    tokens.reset()
    mcp._counts.clear()
    made = []

    def _make(kind: str = "ollama", folders: bool = False, ctx: int = 0):
        fake = Pretend(kind)
        made.append(fake)
        s = Settings()
        s.workspace = str(tmp_path / "ws")
        s.mcp_folders = folders
        if kind.startswith("ollama"):
            s.ollama.url = fake.url
            s.ollama.text_model = "qwen3:14b"
            s.ollama.num_ctx = ctx
        else:
            s.ollama.engine = {"vllm": "openai", "kobold": "openai"}.get(kind, kind)
            s.ollama.engine_url = fake.url
            s.ollama.text_model = "some-model"
        s.save()
        j = mcp.Joe(s)
        j.fake = fake
        return j

    yield _make
    for f in made:
        f.close()
    tokens.reset()


def put(joe, rel: str, text: str):
    p = joe.sb.root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="")
    return p


def numbers(out: str, what: str) -> tuple[int, int]:
    """(tokens, characters) on the table line for `what`."""
    for line in out.splitlines():
        cells = line.split()
        if len(cells) >= 3 and " ".join(cells[2:]) == what:
            return int(cells[0].replace(",", "")), int(cells[1].replace(",", ""))
    raise AssertionError(f"no line for {what!r} in:\n{out}")


# ------------------------------------------------------------------ it is on the connector
def test_tool_is_listed_and_the_instructions_mention_it():
    tool = next(t for t in mcp.TOOLS if t["name"] == "joe_count_tokens")
    assert set(tool["inputSchema"]["properties"]) == {"paths", "texts", "model", "per_line", "limit", "project"}
    assert "required" not in tool["inputSchema"]
    assert "joe_count_tokens" in mcp.INSTRUCTIONS


def test_nothing_to_count(make):
    joe = make()
    assert joe.call("joe_count_tokens", {}).startswith("Nothing to count")
    assert joe.fake.calls == []


# ------------------------------------------------------------------ Ollama with no tokenizer call
def test_ollama_counts_by_reading_and_writes_nothing(make):
    joe = make()
    put(joe, "Output/a.md", "one two three four five\n")
    out = joe.call("joe_count_tokens", {"paths": ["a.md"]})
    assert numbers(out, "Output/a.md") == (5, 24)          # the start-of-text token is taken off
    head = out.splitlines()[0]
    assert "model qwen3:14b" in head and "Ollama" in head and "counted by the model reading it" in head
    assert "ESTIMATE" not in out and "exact" not in head
    assert "/api/chat" not in joe.fake.paths()


def test_two_things_get_the_difference(make):
    joe = make()
    put(joe, "Output/before.md", "word " * 100)
    put(joe, "Output/after.md", "word " * 80)
    out = joe.call("joe_count_tokens", {"paths": ["before.md", "after.md"]})
    assert numbers(out, "Output/before.md")[0] == 100 and numbers(out, "Output/after.md")[0] == 80
    assert numbers(out, "total")[0] == 180
    assert out.splitlines()[-1] == "Output/after.md vs Output/before.md: 20 tokens shorter (-20.0%)"
    worse = joe.call("joe_count_tokens", {"texts": ["a b c d", "a b c d e"]})
    assert worse.splitlines()[-1] == "text 2 vs text 1: 1 tokens LONGER (+25.0%)"
    same = joe.call("joe_count_tokens", {"texts": ["a b", "c d"]})
    assert same.splitlines()[-1] == "text 2 vs text 1: the same"


def test_long_text_is_not_cut_at_the_context_size(make):
    joe = make(ctx=64)                                     # a tiny window: 1,000 words can't go in one prompt
    text = "\n".join(" ".join(f"w{i}" for i in range(n, n + 10)) for n in range(0, 1000, 10)) + "\n"
    put(joe, "Output/long.txt", text)
    out = joe.call("joe_count_tokens", {"paths": ["long.txt"]})
    assert numbers(out, "Output/long.txt")[0] == 1000
    sent = [r["prompt"] for p, r in joe.fake.calls if p == "/api/generate"]
    assert all(r["options"]["num_ctx"] == 64 for p, r in joe.fake.calls if p == "/api/generate")
    assert len(sent) > 10                                   # it went in pieces


def test_a_piece_that_fills_the_window_is_halved(make):
    joe = make(ctx=64)
    text = " ".join("a" for _ in range(60)) + "\n"          # 120 characters, 60 words: under the piece size, over the room
    out = joe.call("joe_count_tokens", {"texts": [text + text]})
    assert numbers(out, "text 1")[0] == 120


def test_the_model_can_be_named(make):
    joe = make()
    out = joe.call("joe_count_tokens", {"texts": ["hello there"], "model": "llama3.1:8b"})
    assert "model llama3.1:8b" in out
    assert {r["model"] for p, r in joe.fake.calls if p == "/api/generate"} == {"llama3.1:8b"}


def test_what_ollama_adds_is_learned_once_per_model(make):
    joe = make()
    joe.call("joe_count_tokens", {"texts": ["one two"]})
    first = len(joe.fake.calls)
    joe.call("joe_count_tokens", {"texts": ["three four five"]})
    assert len(joe.fake.calls) - first == 1


# ------------------------------------------------------------------ Ollama with a tokenizer call
def test_ollama_tokenizer_call_is_used_when_it_agrees(make):
    joe = make("ollama-new")
    out = joe.call("joe_count_tokens", {"texts": ["one two three"]})
    assert numbers(out, "text 1") == (3, 13)
    assert "exact: Ollama's tokenizer call" in out.splitlines()[0]
    assert joe.fake.paths()[-1] == "/api/tokenize"


def test_ollama_tokenizer_call_that_disagrees_is_not_trusted(make):
    joe = make("ollama-bad-call")
    out = joe.call("joe_count_tokens", {"texts": ["one two three"]})
    assert numbers(out, "text 1")[0] == 3
    assert "counted by the model reading it" in out.splitlines()[0]
    assert joe.fake.paths()[-1] == "/api/generate"


def test_an_ollama_that_drops_the_tokenizer_call_still_counts(make):
    """Joseph's PC, 2026-11-27: Ollama answered /api/generate, then closed the connection on
    /api/tokenize, and Joe said Ollama wasn't running."""
    joe = make("ollama-drops")
    out = joe.call("joe_count_tokens", {"texts": ["one two three"]})
    assert numbers(out, "text 1")[0] == 3
    assert "counted by the model reading it" in out.splitlines()[0] and "couldn't count" not in out


def test_an_ollama_that_forgets_repeated_text_gives_an_honest_estimate(make):
    joe = make("ollama-forgetful")
    out = joe.call("joe_count_tokens", {"texts": ["x" * 35]})
    assert "ESTIMATE ONLY" in out.splitlines()[0] and "can't be trusted" in out.splitlines()[0]
    assert numbers(out, "text 1")[0] == 10


# ------------------------------------------------------------------ the other writing programs
@pytest.mark.parametrize("kind,label", [("llamacpp", "llama.cpp (llama-server)"), ("localai", "LocalAI"),
                                        ("vllm", "Other (OpenAI-compatible)"), ("kobold", "Other (OpenAI-compatible)")])
def test_programs_with_a_tokenizer_call_are_exact(make, kind, label):
    joe = make(kind)
    out = joe.call("joe_count_tokens", {"texts": ["one two three four"]})
    assert numbers(out, "text 1")[0] == 4
    assert f"exact: {label}'s tokenizer call" in out.splitlines()[0]
    assert not any("chat" in p or "completions" in p for p in joe.fake.paths())


def test_a_program_with_no_tokenizer_call_says_so_plainly(make):
    joe = make("lmstudio")
    out = joe.call("joe_count_tokens", {"texts": ["x" * 70]})
    head = out.splitlines()[0]
    assert "ESTIMATE ONLY" in head and "LM Studio has no tokenizer call" in head
    assert numbers(out, "text 1")[0] == 20                  # 70 characters at 3.5 a token
    assert joe.fake.calls == []                             # nothing was sent to it


def test_a_model_server_that_is_not_on_this_pc_gets_nothing(make):
    joe = make()
    joe.s.ollama.url = "http://example.com:11434"
    put(joe, "Output/a.md", "secret words")
    assert "nothing was sent" in joe.call("joe_count_tokens", {"paths": ["a.md"]})
    assert joe.fake.calls == []


def test_a_program_that_is_not_running_is_said_plainly(make):
    joe = make()
    joe.fake.close()
    out = joe.call("joe_count_tokens", {"texts": ["hello"], "model": "qwen3:14b"})
    assert out.startswith("Joe couldn't count: Ollama didn't answer for model qwen3:14b")


# ------------------------------------------------------------------ which files
def test_other_folders_are_closed_by_default_and_nothing_is_asked(make):
    joe = make()
    put(joe, "Projects/hooah/a.hua", "one two")
    with pytest.raises(SandboxError) as e:
        joe.call("joe_count_tokens", {"paths": ["Projects/hooah/a.hua"]})
    assert str(e.value) == CLOSED
    with pytest.raises(SandboxError):                       # one closed path stops the whole call
        joe.call("joe_count_tokens", {"paths": ["x.md", "Inbox/y.md"]})
    assert joe.fake.calls == []


def test_any_text_file_counts_when_the_folders_are_open(make):
    joe = make(folders=True)
    put(joe, "Projects/hooah/a.hua", "one two three")       # not one of joe_shrink's file types
    out = joe.call("joe_count_tokens", {"paths": ["Projects/hooah/a.hua"]})
    assert numbers(out, "Projects/hooah/a.hua") == (3, 13)


def test_a_folder_counts_every_text_file_in_it(make):
    joe = make()
    put(joe, "Output/run/a.md", "one two")
    put(joe, "Output/run/deep/b.txt", "one two three")
    put(joe, "Output/run/.joe/private.txt", "never read")
    (joe.sb.root / "Output/run/pic.png").write_bytes(b"\x89PNG\x00\x00binary")
    out = joe.call("joe_count_tokens", {"paths": ["run"]})
    assert numbers(out, "Output/run/a.md")[0] == 2 and numbers(out, "Output/run/deep/b.txt")[0] == 3
    assert numbers(out, "total")[0] == 5
    assert "skipped: Output/run/pic.png (not a text file)" in out
    assert "private" not in out
    assert not any("never" in json.dumps(r) for _, r in joe.fake.calls)


@pytest.mark.parametrize("bad", ["../settings.json", "C:/Windows/win.ini", "/etc/passwd", "Output/.joe/chats.json",
                                 "nothing-here.md"])
def test_paths_outside_or_private_or_missing_are_refused(make, bad):
    joe = make(folders=True)
    put(joe, "Output/.joe/chats.json", "{}")
    with pytest.raises(SandboxError):
        joe.call("joe_count_tokens", {"paths": [bad]})
    assert joe.fake.calls == []


def test_line_endings_are_counted_as_they_are_on_disk(make):
    joe = make()
    (joe.sb.root / "Output/win.txt").write_bytes(b"one\r\ntwo\r\n")
    assert numbers(joe.call("joe_count_tokens", {"paths": ["win.txt"]}), "Output/win.txt") == (2, 10)


def test_too_much_for_one_call_is_skipped_and_said(make, monkeypatch):
    joe = make()
    monkeypatch.setattr(mcp, "MAX_COUNT_CHARS", 20)
    put(joe, "Output/a.md", "one two three")
    put(joe, "Output/b.md", "four five six seven")
    out = joe.call("joe_count_tokens", {"paths": ["a.md", "b.md"]})
    assert numbers(out, "Output/a.md")[0] == 3
    assert "skipped: Output/b.md (over 20 characters in one call; ask again for it)" in out


# ------------------------------------------------------------------ one example a line
def test_per_line_gives_the_spread_and_the_lines_over_the_limit(make):
    joe = make("llamacpp")
    lines = [json.dumps({"text": " ".join(["w"] * n)}) for n in (3, 9, 5, 40, 7)]
    put(joe, "Output/train.jsonl", "\n".join(lines[:2]) + "\n\n" + "\n".join(lines[2:]) + "\n")
    out = joe.call("joe_count_tokens", {"paths": ["train.jsonl"], "per_line": True, "limit": 10})
    got = out.splitlines()
    assert got[0].startswith("[tokens per line | model some-model | llama.cpp (llama-server) | exact")
    assert got[1] == "Output/train.jsonl: 5 lines, 69 tokens in all"          # each line: its words + {"text":
    assert got[2] == "shortest 4 | middle 8 | 95 in 100 are at most 41 | longest 41"
    assert got[3].startswith("longest lines: L5 (41), L2 (10)")               # the blank line 3 still has a number
    assert got[4] == "over 10 tokens: 1 of 5: L5"


def test_per_line_wants_exactly_one_file(make):
    joe = make("llamacpp")
    put(joe, "Output/a.jsonl", "{}\n")
    put(joe, "Output/b.jsonl", "{}\n")
    assert "exactly one file" in joe.call("joe_count_tokens", {"paths": ["a.jsonl", "b.jsonl"], "per_line": True})
    assert "exactly one file" in joe.call("joe_count_tokens", {"texts": ["x"], "per_line": True})


def test_per_line_says_what_it_left_out(make, monkeypatch):
    joe = make("llamacpp")
    monkeypatch.setattr(mcp, "MAX_COUNT_LINES", 3)
    put(joe, "Output/big.jsonl", "a b\n" * 10)
    out = joe.call("joe_count_tokens", {"paths": ["big.jsonl"], "per_line": True})
    assert "3 lines, 6 tokens in all" in out and out.splitlines()[-1].startswith("(7 more lines not counted")


# ------------------------------------------------------------------ the small pieces
def test_pieces_cut_after_line_ends_and_lose_nothing():
    text = "".join(f"line {i} of the text\n" for i in range(200))
    parts = tokens._pieces(text, 300)
    assert "".join(parts) == text and all(len(p) <= 300 for p in parts)
    assert all(p.endswith("\n") for p in parts)
    assert tokens._pieces("x" * 1000, 300) == ["x" * 300] * 3 + ["x" * 100]     # no line ends: still cut


def test_count_in_reads_each_programs_answer():
    assert tokens._count_in({"tokens": [1, 2, 3]}) == 3
    assert tokens._count_in({"count": 4, "tokens": [1]}) == 4
    assert tokens._count_in({"value": 5}) == 5
    assert tokens._count_in({"count": True}) is None and tokens._count_in({"error": "x"}) is None
    assert tokens._count_in([1, 2]) is None


# ------------------------------------------------------------------ files in a listed dev project (outside Joe's folders)
@pytest.fixture
def hooah(make, tmp_path):
    """Dev tools on, with a project "hooah" in a folder outside Joe's workspace (Joseph's Desktop\\HUA case)."""
    joe = make("llamacpp")
    proj = tmp_path / "HUA"
    (proj / "docs" / "spec").mkdir(parents=True)
    (proj / ".git").mkdir()
    (proj / "docs" / "spec" / "fm.md").write_text("one two three four", encoding="utf-8")
    (proj / "docs" / "pilot.jsonl").write_text("a b\nc d e\n", encoding="utf-8")
    (proj / ".git" / "config").write_text("secret words here", encoding="utf-8")
    (tmp_path / "outside.txt").write_text("not yours", encoding="utf-8")
    joe.s.dev_tools = True
    joe.s.dev_projects = [{"name": "hooah", "folder": str(proj), "commands": []}]
    joe.proj = proj
    return joe


def test_a_file_in_a_listed_project_is_counted_by_project_name(hooah):
    out = hooah.call("joe_count_tokens", {"project": "hooah", "paths": ["docs/spec/fm.md"]})
    assert numbers(out, "hooah:docs/spec/fm.md") == (4, 18)
    out = hooah.call("joe_count_tokens", {"project": " Hooah ", "paths": ["docs"]})          # a folder: every text file in it
    assert numbers(out, "hooah:docs/pilot.jsonl")[0] == 5 and numbers(out, "total")[0] == 9
    per = hooah.call("joe_count_tokens", {"project": "hooah", "paths": ["docs/pilot.jsonl"], "per_line": True})
    assert "hooah:docs/pilot.jsonl: 2 lines, 5 tokens in all" in per


def test_a_project_needs_dev_tools_on_and_a_listed_name(hooah):
    assert "No project called 'elsewhere'" in hooah.call("joe_count_tokens", {"project": "elsewhere", "paths": ["x"]})
    hooah.s.dev_tools = False
    assert hooah.call("joe_count_tokens", {"project": "hooah", "paths": ["docs/spec/fm.md"]}).startswith("Dev tools are off.")
    assert hooah.fake.calls == []


@pytest.mark.parametrize("bad", ["../outside.txt", "docs/../../outside.txt", "/etc/passwd", "C:/x.txt", ".git/config",
                                 ".git", "docs/nothing.md", "docs/spec/fm.md:stream"])
def test_paths_out_of_the_project_or_into_dot_folders_are_refused(hooah, bad):
    with pytest.raises(SandboxError):
        hooah.call("joe_count_tokens", {"project": "hooah", "paths": [bad, "docs/spec/fm.md"]})
    assert hooah.fake.calls == []


def test_a_whole_project_walk_skips_dot_folders_and_links_out(hooah, tmp_path):
    try:
        (hooah.proj / "docs" / "link.txt").symlink_to(tmp_path / "outside.txt")
    except OSError:
        pass
    out = hooah.call("joe_count_tokens", {"project": "hooah", "paths": ["docs", "docs/spec"]})
    assert "config" not in out and "link.txt" not in out and "secret" not in json.dumps(hooah.fake.calls)


def test_without_a_project_joes_own_folder_rules_are_unchanged(hooah):
    with pytest.raises(SandboxError):
        hooah.call("joe_count_tokens", {"paths": [str(hooah.proj / "docs" / "spec" / "fm.md")]})


# ------------------------------------------------------------------ long counts, and a model that isn't there
def test_a_long_count_says_still_counting_and_is_never_started_twice(make, monkeypatch):
    """The Hooah chat, 2026-11-27: 359 lines took longer than the AI app waits, and the answer was lost."""
    import time as _time
    joe = make("llamacpp")
    put(joe, "Output/train.jsonl", "".join(f"a b c {i}\n" for i in range(30)))
    slow = tokens.Counter.count
    monkeypatch.setattr(tokens.Counter, "count", lambda self, text: (_time.sleep(0.05), slow(self, text))[1])
    monkeypatch.setattr(mcp, "COUNT_WAIT_S", 0.3)
    args = {"paths": ["train.jsonl"], "per_line": True}
    first = joe.call("joe_count_tokens", args)
    assert first.startswith("[tokens | STILL COUNTING, ") and " of 30 lines done]" in first and "not started twice" in first
    assert joe.call("joe_count_tokens", dict(args)).startswith("[tokens | STILL COUNTING, ")
    assert len(mcp._counts) == 1                                        # the same count, not a second one
    monkeypatch.setattr(mcp, "COUNT_WAIT_S", 30)
    done = joe.call("joe_count_tokens", dict(args))
    assert "Output/train.jsonl: 30 lines, 120 tokens in all" in done
    assert sum(1 for p, _ in joe.fake.calls if p == "/tokenize") <= 31  # each line asked once (plus the first check)
    assert mcp._counts == {}                                            # handed over once


def test_a_refused_path_is_still_refused_at_once(make, monkeypatch):
    joe = make()
    monkeypatch.setattr(mcp, "COUNT_WAIT_S", 30)
    with pytest.raises(SandboxError):
        joe.call("joe_count_tokens", {"paths": ["Inbox/x.md"]})
    assert mcp._counts == {}


def test_a_model_that_is_not_installed_is_said_at_once_with_what_is(make):
    joe = make()
    out = joe.call("joe_count_tokens", {"texts": ["hello"], "model": "qwen3.5:4b"})
    assert out.startswith("The model 'qwen3.5:4b' isn't installed in Ollama on this PC, so nothing was counted.")
    assert "Installed: qwen3:14b, llama3.1:8b." in out
    assert not any(p == "/api/generate" for p, _ in joe.fake.calls)
