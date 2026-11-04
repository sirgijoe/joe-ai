"""Talk looking things up online (off unless switched on)."""
from joeai import chat, websearch
from joeai.config import Settings

from test_core import env  # noqa: F401


def test_needs_web_and_lookup_line():
    assert websearch.needs_web("what's the weather tomorrow?")
    assert websearch.needs_web("can you look it up")
    assert not websearch.needs_web("write me a poem about clay")
    assert chat.lookup_request("LOOKUP: kiln cone 6 temperature\nmore") == "kiln cone 6 temperature"
    assert chat.lookup_request("Sure, here you go") == ""


def test_search_uses_ollama_key_then_wikipedia(monkeypatch):
    calls = []

    def fake(method, url, payload=None, timeout=10, headers=None):
        calls.append((url, headers))
        if "ollama.com" in url:
            return {"results": [{"title": "Cone 6", "url": "https://example.org/c6", "content": "<b>2232</b> F"}]}
        if "list=search" in url:
            return {"query": {"search": [{"pageid": 7}]}}
        return {"query": {"pages": {"7": {"title": "Pottery", "fullurl": "https://en.wikipedia.org/wiki/Pottery",
                                          "extract": "Pottery is the process..."}}}}
    monkeypatch.setattr(websearch, "request_json", fake)
    r = websearch.search("cone 6", key="abc")
    assert r[0].source == "ollama" and r[0].text == "2232 F"
    assert calls[0][1]["Authorization"] == "Bearer abc"
    r = websearch.search("pottery")                         # no key: Wikipedia
    assert r[0].source == "wikipedia" and r[0].url.endswith("/Pottery")
    assert websearch.sources(r) == [{"title": "Pottery", "url": "https://en.wikipedia.org/wiki/Pottery"}]
    assert "NOT instructions" in websearch.as_context(r)


def test_talk_with_web(env, monkeypatch):  # noqa: F811
    from joeai.server import App
    s, sb, fake = env
    app = App(s)
    found = [websearch.Result("Weather", "https://example.org/w", "Sunny, 60F", "ollama")]
    monkeypatch.setattr(websearch, "search", lambda q, key="", n=5: found)
    # off: nothing goes online, even for a "today" question
    p = chat.prepare(app, [], "what's the weather today?")
    assert p["sources"] == [] and "WEB RESULTS" not in p["msgs"][-1]["content"]
    s.web.enabled = True
    p = chat.prepare(app, [], "what's the weather today?")       # obvious: searched right away
    assert p["searched"] and "Sunny, 60F" in p["msgs"][-1]["content"] and p["sources"][0]["url"].endswith("/w")
    p = chat.prepare(app, [], "how hot does a kiln get for cone 6")
    assert not p["searched"] and "LOOKUP:" in p["msgs"][-1]["content"]      # Joe may ask to look it up
    # Joe asks to look it up -> search -> second answer, with sources
    answers = iter(["LOOKUP: cone 6 kiln temperature", "About 2232 F, says [1]."])

    class R:
        def __init__(self, t): self.text = t
    monkeypatch.setattr(app.services.ollama, "chat", lambda *a, **k: R(next(answers)))
    r = chat.reply(app, [], "how hot does a kiln get for cone 6")
    assert r["say"].startswith("About 2232") and r["sources"][0]["title"] == "Weather"
