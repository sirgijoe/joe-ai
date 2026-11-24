"""The connector's reads are capped: joe_shrink at MAX_SHRINK characters, joe_read_file at MAX_READ."""
import pytest

from joeai import mcp
from joeai.config import Settings
from joeai.sandbox import SandboxError


@pytest.fixture
def joe(tmp_path, monkeypatch):
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "settings.json"))
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    s.mcp_folders = True                  # these read the Inbox (Setup > Other AI apps tick box)
    s.save()
    return mcp.Joe(s)


def _bank(joe):
    rows = [f"2026-11-{i % 28 + 1:02d},payee {i:06d},amount {i * 7 % 1000:>5}.00,acct 1234" for i in range(9000)]
    text = "\n".join(rows)
    while len(text) < 600_000:
        text += "\n" + rows[len(text) % 9000]
    (joe.sb.inbox / "bank.csv").write_text(text, encoding="utf-8")


def test_shrink_is_capped_even_when_asked_for_more(joe):
    _bank(joe)
    assert mcp.MAX_SHRINK == 20_000
    out = joe.call("joe_shrink", {"path": "Inbox/bank.csv", "grep": "acct", "max_chars": 50_000_000})
    assert len(out) <= 20_400


@pytest.mark.parametrize("ask", ["lots", -5, None, 0, "12.5", 3.7])
def test_shrink_odd_max_chars_still_answers(joe, ask):
    _bank(joe)
    out = joe.call("joe_shrink", {"path": "Inbox/bank.csv", "grep": "acct", "max_chars": ask})
    assert out.startswith("[Inbox/bank.csv | ") and len(out) <= 20_400


def test_shrink_text_max_chars_means_8000(joe):
    _bank(joe)
    a = joe.call("joe_shrink", {"path": "Inbox/bank.csv", "max_chars": "lots"})
    b = joe.call("joe_shrink", {"path": "Inbox/bank.csv", "max_chars": 8000})
    assert a == b


def test_shrink_still_refuses_private_folders(joe):
    priv = joe.sb.output / ".joe"
    priv.mkdir(parents=True, exist_ok=True)
    (priv / "state.json").write_text('{"a": 1}', encoding="utf-8")
    with pytest.raises(SandboxError):
        joe.call("joe_shrink", {"path": "Output/.joe/state.json"})


def test_shrink_description_names_cap_and_folders():
    desc = next(t for t in mcp.TOOLS if t["name"] == "joe_shrink")["description"]
    assert "at most 20,000 characters a call" in desc
    for folder in ("Output", "Inbox"):
        assert folder in desc


def test_read_file_reads_only_max_read(joe, monkeypatch):
    text = "".join(chr(97 + i % 26) for i in range(1_000_000))
    (joe.sb.output / "big.txt").write_text(text, encoding="utf-8")
    sizes = []
    real_open = open

    def spy(*a, **k):
        f = real_open(*a, **k)
        real_read = f.read

        def read(n=-1):
            sizes.append(n)
            return real_read(n)
        f.read = read
        return f
    monkeypatch.setattr("builtins.open", spy)
    out = joe.call("joe_read_file", {"path": "big.txt"})
    monkeypatch.undo()
    assert out == text[:mcp.MAX_READ]
    assert sizes and all(0 <= n <= mcp.MAX_READ for n in sizes)
