"""Two more places Joe can search (2.3), after Ollama's web search started asking for payment on
2026-11-15: LangSearch (a web search with a no-cost plan and a usage limit; needs its own key) and
"your own search source" (any search address the person types in Setup). Fake servers only."""
import json
from pathlib import Path

import pytest

from joeai import backup, config, vault, websearch
from joeai.config import Settings

from fake_search import FakeWeb

ROOT = Path(__file__).resolve().parents[1]
LANG_OK = {"code": 200, "log_id": "x", "msg": None, "data": {"_type": "SearchResponse", "webPages": {"value": [
    {"name": "Kubota <b>orange</b>", "url": "https://example.org/kubota", "snippet": "short bit",
     "summary": "Kubota tractors are painted orange."},
    {"name": "No link", "url": "javascript:alert(1)", "snippet": "x", "summary": "x"},
    {"name": "Only a snippet", "url": "https://example.org/two", "snippet": "the snippet", "summary": None}]}}}


@pytest.fixture
def web(monkeypatch):
    with FakeWeb() as w:
        w.route("/v1/web-search", LANG_OK)
        monkeypatch.setattr(websearch, "LANGSEARCH", w.url("/v1/web-search"))
        yield w


def _s(providers, **kw):
    s = Settings()
    s.web.providers = providers
    for k, v in kw.items():
        setattr(s.web, k, v)
    config.clean_web(s)
    return s


# --------------------------------------------------------------------------- LangSearch
def test_langsearch_is_a_source_that_is_off_until_ticked():
    p = websearch.all_providers()["langsearch"]
    assert p.label == "LangSearch" and p.goes_to == "langsearch.com"
    assert Settings().web.providers == "wikipedia"                     # out of the box: Wikipedia only
    assert "langsearch" in [x["id"] for x in websearch.providers_for_setup(Settings())]


def test_langsearch_searches_with_its_own_key(web):
    f = websearch.find("what colour are kubota tractors", _s("langsearch", langsearch_key="lang-key", ollama_key="oll"))
    method, path, body, headers = web.hits[0]
    assert (method, path) == ("POST", "/v1/web-search") and headers.get("Authorization") == "Bearer lang-key"
    sent = json.loads(body)
    assert sent["query"] == "what colour are kubota tractors" and sent["count"] == 5 and sent["summary"] is True
    assert [(r.title, r.url, r.text, r.source) for r in f] == [
        ("Kubota orange", "https://example.org/kubota", "Kubota tractors are painted orange.", "langsearch"),
        ("Only a snippet", "https://example.org/two", "the snippet", "langsearch")]
    assert f.via() == "Found with LangSearch."


def test_langsearch_is_skipped_without_its_key(web):
    s = _s("langsearch")
    assert websearch.find("pottery", s) == [] and not web.hits
    assert websearch.try_each(s) == [{"id": "langsearch", "label": "LangSearch", "ok": False,
                                      "text": "needs the LangSearch key"}]
    row = [x for x in websearch.providers_for_setup(s) if x["id"] == "langsearch"][0]
    assert row["ready"] is False and row["needs"] == "langkey"


@pytest.mark.parametrize("status,answer,said", [
    (401, {"msg": "bad key"}, "the LangSearch key was refused - check it in Setup"),
    (429, {"msg": "slow"}, "it says too many searches, so Joe gives it a rest"),
    (402, {"msg": "pay"}, "LangSearch now asks for payment (it had a no-cost plan): langsearch.com"),
    (200, {"code": 429, "msg": "You have reached the request limit", "data": None},
     "it said: You have reached the request limit"),
    (200, {"code": 200, "data": {"webPages": None}}, None)])
def test_langsearch_trouble_is_said_plainly(web, status, answer, said):
    web.route("/v1/web-search", answer, status=status)
    each = websearch.try_each(_s("langsearch", langsearch_key="k"))
    assert each[0]["text"] == (said or "answered, but found nothing") and not each[0]["ok"]


def test_a_new_langsearch_key_gets_a_fresh_try(web):
    web.route("/v1/web-search", {"msg": "bad key"}, status=401)
    assert not websearch.find("pottery", _s("langsearch", langsearch_key="old"))
    assert "resting" in websearch.find("raku", _s("langsearch", langsearch_key="old")).via()
    web.route("/v1/web-search", LANG_OK)
    assert websearch.find("raku", _s("langsearch", langsearch_key="new")).source == "langsearch"


# --------------------------------------------------------------------------- your own search source
OWN = {"web": {"results": [{"title": "Raku <i>firing</i>", "url": "https://example.org/raku",
                            "description": "Raku is fired fast."},
                           {"title": "Bad", "url": "ftp://example.org/x", "description": "no"}]}}


def _own(web, **kw):
    kw = {"custom_url": web.url("/find?q={query}&count=5"), "custom_list": "web.results",
          "custom_text": "description", **kw}
    return _s("custom", **kw)


def test_your_own_source_searches_the_address_you_typed(web):
    web.route("/find", OWN)
    s = _own(web, custom_name="Brave at home")
    f = websearch.find("raku firing & glaze", s)
    method, path, body, headers = web.hits[0]
    assert method == "GET" and path == "/find?q=raku%20firing%20%26%20glaze&count=5" and "Authorization" not in headers
    assert [(r.title, r.url, r.text, r.source) for r in f] == [
        ("Raku firing", "https://example.org/raku", "Raku is fired fast.", "custom")]
    assert f.via() == "Found with Brave at home."
    row = [x for x in websearch.providers_for_setup(s) if x["id"] == "custom"][0]
    assert row["label"] == "Brave at home" and row["goes_to"] == f"127.0.0.1:{web.port}" and row["ready"]


def test_your_own_source_sends_its_key_the_way_you_said(web):
    web.route("/find", OWN)
    websearch.find("a", _own(web, custom_key="k1"))                                    # the usual way
    assert web.hits[-1][3].get("Authorization") == "Bearer k1"
    websearch.find("b", _own(web, custom_key="k2", custom_key_header="X-Subscription-Token"))
    assert web.hits[-1][3].get("X-Subscription-Token") == "k2" and "Authorization" not in web.hits[-1][3]
    websearch.find("c", _own(web, custom_key="k 3", custom_url=web.url("/find?q={query}&key={key}")))
    assert web.hits[-1][1] == "/find?q=c&key=k%203" and "Authorization" not in web.hits[-1][3]


def test_your_own_source_can_post_the_search_words(web):
    web.route("/find", OWN)
    websearch.find('say "hi"', _own(web, custom_url=web.url("/find"), custom_body='{"q": "{query}", "num": 5}'))
    method, path, body, headers = web.hits[-1]
    assert method == "POST" and json.loads(body) == {"q": 'say "hi"', "num": 5}


def test_your_own_source_is_off_until_it_has_an_address_with_the_search_words(web):
    assert Settings().web.custom_url == ""
    for bad in ("", "javascript:alert({query})", "file:///c:/x?{query}", "http://u:p@example.org/?q={query}",
                "http://example.org/search"):                                         # the last: nowhere for the words
        s = _s("custom", custom_url=bad)
        assert websearch.find("pottery", s) == [] and not web.hits
        assert websearch.try_each(s)[0]["text"] == "needs its address, with {query} where the search words go"
    assert _s("custom", custom_url="http://example.org/search", custom_body='{"q": "{query}"}').web.custom_url


def test_your_own_source_says_what_is_wrong_with_what_you_typed(web):
    web.route("/find", OWN)
    each = websearch.try_each(_own(web, custom_list="results"))
    assert each[0]["text"] == "its answer has no list called 'results' (Setup: Where the results are)"
    each = websearch.try_each(_own(web, custom_url=web.url("/find"), custom_body='{"q": {query}'))
    assert each[0]["text"] == "what Joe should send isn't valid JSON (Setup: Send this)"
    web.route("/find", {"error": "no"}, status=403)
    assert websearch.try_each(_own(web))[0]["text"] == "it refused Joe - check its key in Setup"


def test_what_is_saved_for_your_own_source_is_cleaned():
    s = _s("custom", custom_name="  <b>Mine</b> " + "x" * 80, custom_key_header="Bad Header:\r\nX: y",
           custom_list="a..b;drop", custom_title="", custom_link="link", custom_text="x" * 200,
           custom_url="http://example.org/?q={query}", custom_body="y" * 5000)
    w = s.web
    assert w.custom_name.startswith("Mine") and len(w.custom_name) <= 40 and "<" not in w.custom_name
    assert w.custom_key_header == "Authorization"
    assert (w.custom_list, w.custom_title, w.custom_link, w.custom_text) == ("results", "title", "link", "content")
    assert w.custom_body == ""                                                         # too long to be right


# --------------------------------------------------------------------------- the new keys are kept like the others
def test_the_new_keys_are_protected_like_the_ollama_key():
    for p in (("web", "langsearch_key"), ("web", "custom_key")):
        assert p in vault.SECRETS and p in backup.KEY_PATHS
        assert ".".join(p) in config.KEEP_ON_RESET
    text = (ROOT / "joeai" / "portable.py").read_text(encoding="utf-8")
    assert 'd["web"]["langsearch_key"] = ""' in text and 'd["web"]["custom_key"] = ""' in text


def test_setup_has_the_boxes_and_the_guide_explains_them():
    html = (ROOT / "joeai" / "ui" / "index.html").read_text(encoding="utf-8")
    for path in ("web.langsearch_key", "web.custom_name", "web.custom_url", "web.custom_key", "web.custom_key_header",
                 "web.custom_body", "web.custom_list", "web.custom_title", "web.custom_link", "web.custom_text"):
        assert f'data-path="{path}"' in html, path
    assert 'type="password" data-path="web.langsearch_key"' in html and 'type="password" data-path="web.custom_key"' in html
    guide = (ROOT / "docs" / "GUIDE.md").read_text(encoding="utf-8")
    assert "**LangSearch**" in guide and "**Your own search source**" in guide and "{query}" in guide
