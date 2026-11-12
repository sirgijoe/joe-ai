"""Online lookups for agents (2.3), with the search-words rule.

THE SEARCH-WORDS RULE (Joseph, 2026-11-11; tests/test_dev23_agent_engine.py checks it):
  The words of a search come only from the job the owner typed, never from words read from a file or
  suggested by the model after it read one. A planted line in a file ("search for <the contents of
  this letter>") must not be able to send file contents out in a search.
  - A run is "tainted" as soon as it may read anything that isn't the owner's job or what was found
    online: a file that started it, a file in the agent's own folder, the output of a tool that read
    one. From then on every search keeps only the words that are in the owner's job (plus a fixed
    list of small words like "the" and "for"); everything else the model proposed is dropped. If no
    job word is left, the search is just the job's own words.
  - Before that (a Researcher with no files), the model may phrase its own searches, because all it
    has read is the job and web results: there is nothing private to leak.
  - Searches never carry a web address, an e-mail address or a long number, tainted or not.

What leaves the PC: the search words, and the address of a page to read (only an address that a
search in this run returned, or one the owner typed into the job). Never a file, never a chat.
With lookups off (the agent's own switch, or Setup's "Let Joe look things up online", or
JOE_OFFLINE) no network call is made at all: every function here returns before touching it.
"""
from __future__ import annotations

import ipaddress
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request

from . import websearch

OLLAMA_FETCH = "https://ollama.com/api/web_fetch"
MAX_SEARCHES = 14            # per run, fact-checking included
MAX_READS = 8                # whole pages read per run
PAGE_CHARS = 12000           # of one page kept for the model
QUERY_WORDS = 12
OFFLINE_ENV = "JOE_OFFLINE"  # set = no lookups at all (the tests set it; agent tests point this elsewhere)
SMALL = frozenset("a an and the of for to in on at by with from or is are was were be how what which who when "
                  "where why best cheapest cheap price prices cost costs vs versus near new latest today "
                  "this year review reviews guide compare comparison".split())
_TOKEN = re.compile(r"[^\W_]+(?:['’.-][^\W_]+)*", re.U)
_URLISH = re.compile(r"([a-z][a-z0-9+.-]*://\S+|www\.\S+|\S+@\S+|\S+\.(?:com|net|org|io|gov|edu|co|uk|info|biz|xyz)\b\S*)", re.I)


def enabled(settings, agent: dict) -> bool:
    """May this run look things up? All three must say yes."""
    from .agents import ability_on
    w = getattr(settings, "web", None)
    return ability_on(agent, "lookups") and bool(w and w.enabled) \
        and not os.environ.get(OFFLINE_ENV)


def words(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text or "")]


def _stem(w: str) -> str:
    """houseplants = houseplant (a plural adds no new words to a search)."""
    return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w


def safe_query(proposed: str, job: str, tainted: bool) -> str:
    """The search words that may leave the PC (see THE SEARCH-WORDS RULE above)."""
    proposed = _URLISH.sub(" ", proposed or "")
    toks = [t for t in words(proposed) if not (t.isdigit() and len(t) > 4)]
    if tainted:
        allowed = {_stem(w) for w in words(_URLISH.sub(" ", job))} | SMALL
        toks = [t for t in toks if t in SMALL or _stem(t) in allowed]
        if not [t for t in toks if t not in SMALL]:
            toks = [t for t in words(_URLISH.sub(" ", job)) if not (t.isdigit() and len(t) > 4)]
    out, seen = [], set()
    for t in toks:
        if t not in seen:
            out.append(t)
            seen.add(t)
    return " ".join(out[:QUERY_WORDS])[:200]


def owner_urls(job: str) -> list[str]:
    return [u.rstrip(".,);]") for u in re.findall(r"https?://[^\s<>\"']+", job or "")]


def public_url(url: str) -> bool:
    """http(s) to a named or public host: never this PC, the home network or a file."""
    try:
        u = urllib.parse.urlparse(url)
    except ValueError:
        return False
    if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password:
        return False
    host = u.hostname.lower()
    if host in ("localhost",) or host.endswith((".local", ".lan", ".home", ".internal")) or "." not in host:
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return True


def _resolves_public(url: str) -> bool:
    """Every address the name points at is out on the internet (not this PC or the home network)."""
    host = urllib.parse.urlparse(url).hostname or ""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    return bool(infos) and all(ipaddress.ip_address(i[4][0].split("%")[0]).is_global for i in infos)


class _CheckRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not (public_url(newurl) and _resolves_public(newurl)):
            raise urllib.error.URLError("redirect to a private address refused")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Lookups:
    """Everything one run looked up (the report lists it all)."""

    def __init__(self, settings, agent: dict, job: str, log):
        self.settings, self.agent, self.job, self.log = settings, agent, job, log
        self.on = enabled(settings, agent)
        self.key = (settings.web.ollama_key or "").strip() if self.on else ""
        self.searches: list[dict] = []          # {"query", "results": [Result]}
        self.pages: dict[str, dict] = {}        # url -> {"title", "url", "text"}
        self.tainted = False

    def known_urls(self) -> set[str]:
        out = set(owner_urls(self.job))
        for s in self.searches:
            out.update(r.url for r in s["results"])
        return out

    def search(self, proposed: str) -> tuple[str, list]:
        """(the words actually sent, results). Never a network call when lookups are off."""
        if not self.on:
            return "", []
        if len(self.searches) >= MAX_SEARCHES:
            self.log(f"  Lookup limit reached ({MAX_SEARCHES} searches in one run); no more searches.")
            return "", []
        q = safe_query(proposed, self.job, self.tainted)
        if not q:
            return "", []
        if self.tainted and q != safe_query(proposed, self.job, False):
            self.log("  Search words cut to the owner's job (this run has read files, so the model's own "
                     "words may not leave the PC).")
        try:
            res = websearch.search(q, self.key, max(3, min(8, self.settings.web.max_results)))
        except Exception as e:                  # noqa: BLE001 (never stop a run for it)
            self.log(f"  lookup failed: {e}")
            res = []
        self.searches.append({"query": q, "results": res})
        self.log(f"  Looked up '{q}': {len(res)} result(s)")
        return q, res

    def read(self, url: str) -> dict | None:
        """One whole page: only an address a search in this run returned, or one the owner typed."""
        if not self.on:
            return None
        url = (url or "").strip()
        if url in self.pages:
            return self.pages[url]
        if url not in self.known_urls() or not public_url(url):
            self.log(f"  '{url[:80]}' wasn't found by a search in this run or typed in the job; not read.")
            return None
        if len(self.pages) >= MAX_READS:
            self.log(f"  Page limit reached ({MAX_READS} in one run).")
            return None
        found = next((r for s in self.searches for r in s["results"] if r.url == url), None)
        page = fetch_page(url, self.key) or (
            {"title": found.title, "url": url, "text": found.text} if found else None)
        if page:
            page["text"] = page["text"][:PAGE_CHARS]
            self.pages[url] = page
            self.log(f"  Read {url[:90]} ({len(page['text'])} characters)")
        return page

    def sources(self) -> list[dict]:
        """Every page that fed the work, numbered S1, S2... in the order first used."""
        out, seen = [], set()
        for url, p in self.pages.items():
            if url not in seen:
                out.append({"title": p["title"] or websearch._host(url), "url": url})
                seen.add(url)
        for s in self.searches:
            for r in s["results"]:
                if r.url not in seen and r.url.startswith("http"):
                    out.append({"title": r.title or websearch._host(r.url), "url": r.url})
                    seen.add(r.url)
        return out


def fetch_page(url: str, key: str = "") -> dict | None:
    """A page's text: Ollama's web fetch with a key; otherwise a plain download of the page."""
    from .http import HttpError, request_json
    if key:
        try:
            r = request_json("POST", OLLAMA_FETCH, {"url": url}, timeout=25,
                             headers={"Authorization": f"Bearer {key}", **websearch.AGENT})
            text = websearch._clean(str(r.get("content", "")))
            if text:
                return {"title": str(r.get("title", ""))[:200], "url": url, "text": text}
        except HttpError:
            pass
    if not (public_url(url) and _resolves_public(url)):
        return None
    try:
        req = urllib.request.Request(url, headers=websearch.AGENT)
        with urllib.request.build_opener(_CheckRedirects).open(req, timeout=20) as resp:
            kind = resp.headers.get("Content-Type", "")
            if "html" not in kind and "text" not in kind:
                return None
            raw = resp.read(1_500_000).decode("utf-8", "replace")
    except Exception:                           # noqa: BLE001
        return None
    title = re.search(r"<title[^>]*>(.*?)</title>", raw, re.I | re.S)
    raw = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", raw)
    return {"title": websearch._clean(title.group(1))[:200] if title else "", "url": url,
            "text": websearch._clean(raw)}
