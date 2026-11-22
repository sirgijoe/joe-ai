"""Ollama's web search is no longer free (2.3). Found on a real account on 2026-11-15: a brand-new key was
answered with HTTP 402, "Add usage credits to use web search, or subscribe". Joe said only "it answered with
an error (402)", and Setup, the guide and Joe's own answers still called the key free. Fake servers only."""
from pathlib import Path

import pytest

from joeai import websearch
from joeai.config import Settings

from fake_search import FakeWeb
from test_lookups import _wiki

ROOT = Path(__file__).resolve().parents[1]
PAID = "Ollama now asks for paid usage credits for web search (it used to be free): ollama.com/plans"


@pytest.fixture
def web(monkeypatch):
    with FakeWeb() as w:
        w.route("/w/api.php", _wiki)
        w.route("/api/web_search", {"error": "Add usage credits to use web search, or subscribe and save up to 66%: "
                                             "https://ollama.com/plans (ref: 06cf)"}, status=402)
        monkeypatch.setattr(websearch, "WIKI_API", w.url("/w/api.php"))
        monkeypatch.setattr(websearch, "OLLAMA_SEARCH", w.url("/api/web_search"))
        yield w


def _s(key="abc", providers="ollama,wikipedia", **kw):
    s = Settings()
    s.web.ollama_key, s.web.providers = key, providers
    for k, v in kw.items():
        setattr(s.web, k, v)
    return s


def test_joe_says_plainly_that_ollama_wants_payment(web):
    each = websearch.try_each(_s())
    assert each[0] == {"id": "ollama", "label": "Ollama web search", "ok": False, "text": PAID}
    assert each[1]["ok"]                                              # Wikipedia still answers
    f = websearch.find("pottery", _s())
    assert f.source == "wikipedia"
    assert f.via() == f"Found with Wikipedia, because Ollama web search didn't answer ({PAID})."


def test_a_source_that_wants_payment_rests_like_a_refused_key(web):
    s = _s()
    websearch.find("pottery", s)
    asked = len([h for h in web.hits if h[1].startswith("/api/web_search")])
    f = websearch.find("raku", s)
    assert len([h for h in web.hits if h[1].startswith("/api/web_search")]) == asked     # not asked again
    assert "Ollama web search is resting for a while" in f.via() and "paid usage credits" in f.via()


def test_any_other_source_that_asks_for_payment_says_so(web, monkeypatch):
    web.route("/sx/search", {"error": "pay up"}, status=402)
    each = websearch.try_each(_s(key="", providers="searxng", searxng_url=web.url("/sx")))
    assert each == [{"id": "searxng", "label": "Your own SearXNG", "ok": False, "text": "it asks for payment"}]


def test_nothing_calls_the_ollama_key_free_any_more():
    about = websearch.BUILT_IN["ollama"].about
    assert "paid usage credits" in about and "free Ollama" not in about
    for name in ("joeai/websearch.py", "joeai/abilities.py", "joeai/config.py", "joeai/ui/index.html", "docs/GUIDE.md",
                 "README.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        for old in ("free Ollama account key", "With a free Ollama key", "with a free key", "Needs the free key",
                    "free key from ollama.com", "make a free account at <b>ollama.com</b>"):
            assert old not in text, (name, old)
    html = (ROOT / "joeai" / "ui" / "index.html").read_text(encoding="utf-8")
    assert "Ollama now asks for paid usage credits for web search" in html
    guide = (ROOT / "docs" / "GUIDE.md").read_text(encoding="utf-8")
    assert "paid usage credits" in guide and "HTTP 402" in guide
    assert "no free source for the whole web" in guide                # said out loud, not left for people to find
