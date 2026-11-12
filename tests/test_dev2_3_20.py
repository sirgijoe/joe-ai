"""2.3.0.dev20: joe_shrink (no model) and joe_summarize (local model) on the MCP connector."""
import json

import pytest

from joeai import mcp, shrink
from joeai.config import Settings

from fake_ollama import FakeOllama


@pytest.fixture
def joe(tmp_path, monkeypatch):
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "settings.json"))
    fake = FakeOllama()
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    s.ollama.url = fake.url
    s.ollama.text_model = "qwen3:14b"
    s.save()
    j = mcp.Joe(s)
    j.fake = fake
    yield j
    fake.close()


def _log(n=500):
    rows = [f"2026-11-12 04:{i // 60:02d}:{i % 60:02d} INFO heartbeat ok" for i in range(n)]
    rows[250] = "2026-11-12 04:04:10 ERROR disk full on D:"
    return "\n".join(rows)


def test_log_keeps_edges_errors_context_and_folds_repeats():
    r = shrink.shrink(_log(), "run.log")
    t = r["text"]
    assert r["kind"] == "log" and r["shrunk"] < r["original"] // 5
    assert "L251| 2026-11-12 04:04:10 ERROR disk full on D:" in t
    assert t.count("heartbeat ok") == 1 and "L1| " in t and "(x 499)" in t   # timestamps stripped to dedupe
    assert "lines left out" in t


def test_log_context_and_edges_with_distinct_lines():
    rows = [f"step {i} done" for i in range(500)]
    rows[250] = "ERROR disk full on D:"
    t = shrink.shrink("\n".join(rows), "run.log")["text"]
    assert "L248|" in t and "L254|" in t and "L247|" not in t and "L255|" not in t   # 3 lines context
    assert "L20|" in t and "L21|" not in t and "L481|" in t and "L500|" in t


def test_traceback_and_warn_are_kept():
    rows = ["x"] * 100
    rows[50], rows[70] = "Traceback (most recent call last):", "WARN low memory"
    t = shrink.shrink("\n".join(rows), "a.log")["text"]
    assert "L51| Traceback" in t and "L71| WARN low memory" in t


def test_json_shape():
    data = {"items": [{"id": i, "name": "mug " * 20} for i in range(40)], "ok": True, "n": None}
    t = shrink.shrink(json.dumps(data), "d.json")["text"]
    shape = json.loads(t)
    assert shape["items"][0] == "array[40]" and len(shape["items"]) == 4
    assert shape["items"][1]["id"] == "int 0" and shape["items"][1]["name"].startswith("str ")
    assert shape["ok"] == "bool" and shape["n"] == "null"


def test_html_visible_text_only():
    html = ("<!doctype html><html><head><title>Shop</title><style>p{color:red}</style></head>"
            "<body><script>var secret=1</script><p>Blue mug</p><p>$24</p></body></html>")
    r = shrink.shrink(html, "page.html")
    assert r["kind"] == "html" and "Title: Shop" in r["text"] and "Blue mug" in r["text"]
    assert "secret" not in r["text"] and "color" not in r["text"]


def test_text_head_tail_grep_and_cap():
    rows = [f"line {i}" for i in range(1000)]
    rows[500] = "the glaze recipe is here"
    t = shrink.shrink("\n".join(rows), "notes.md", grep="glaze")["text"]
    assert "L501| the glaze recipe is here" in t and "L1| line 0" in t and "L1000| line 999" in t
    assert "L300|" not in t
    big = shrink.shrink("y" * 50_000, "big.txt", max_chars=1000)
    assert big["shrunk"] <= 1000 and "cut from the middle" in big["text"]


def test_mcp_shrink_reports_sizes_and_stays_in_folders(joe):
    (joe.sb.output / "run.log").write_text(_log(), encoding="utf-8")
    out = joe.call("joe_shrink", {"path": "run.log"})
    assert out.startswith("[Output/run.log | log | ") and " -> " in out and "%)" in out
    (joe.sb.inbox / "x.json").write_text('{"a": [1, 2, 3, 4]}', encoding="utf-8")
    assert "array[4]" in joe.call("joe_shrink", {"path": "Inbox/x.json"})
    for bad in ("../../settings.json", ".joe/state.json", "/etc/passwd"):
        with pytest.raises(Exception):
            joe.call("joe_shrink", {"path": bad})
    (joe.sb.output / "pic.png").write_bytes(b"\x89PNG")
    with pytest.raises(Exception):
        joe.call("joe_shrink", {"path": "pic.png"})
    names = [t["name"] for t in mcp.TOOLS]
    assert "joe_shrink" in names and "joe_summarize" in names


def test_mcp_summarize_uses_local_model_and_names_lines(joe):
    (joe.sb.output / "run.log").write_text(_log(), encoding="utf-8")
    out = joe.call("joe_summarize", {"path": "run.log", "question": "why did it stop?"})
    assert "ERROR disk full on D:" in out and "From: L1-L251" in out
    assert joe.fake.calls >= 1 and all("ERROR" in p or "heartbeat" in p for p in joe.fake.prompts)


def test_summarize_many_parts_are_combined_and_word_capped():
    calls = []

    def chat(system, user):
        calls.append(system)
        return "Found: " + "word " * 500 if system.startswith("You summarize") else "joined " * 500

    text = "\n".join(f"ERROR row {i} " + "z" * 200 for i in range(300))
    r = shrink.summarize(text, "a.log", chat, "", max_words=30)
    assert len(r["lines"]) > 1 and calls[-1].startswith("You combine")
    assert len(r["answer"].split()) <= 31


def test_summarize_refuses_a_remote_model_server(joe):
    joe.s.ollama.url = "http://10.0.0.5:11434"
    (joe.sb.output / "a.txt").write_text("hi", encoding="utf-8")
    calls = joe.fake.calls
    assert "nothing was sent" in joe.call("joe_summarize", {"path": "a.txt"})
    assert joe.fake.calls == calls
    assert shrink.is_local("http://127.0.0.1:11434") and not shrink.is_local("https://api.example.com")
