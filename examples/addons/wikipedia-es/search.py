"""Example Joe search add-on: the Spanish Wikipedia (docs/ADDONS.md, "Search sources").

Joe runs this program once per search. It reads one line of JSON on its input:
    {"query": "cerámica raku", "max_results": 5}
and prints one JSON object on its output:
    {"results": [{"title": "...", "url": "https://...", "text": "..."}]}
or, when the site said to slow down: {"rate_limited": true, "error": "a plain sentence"}
or, when something else went wrong:  {"error": "a plain sentence"}
Standard library only, so it runs on Joe's own Python ("program": "joe:python").
"""
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://es.wikipedia.org/w/api.php"
AGENT = "Joe-ai search add-on example (wikipedia-es)"


def fetch(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read(1_000_000).decode("utf-8"))


def search(query: str, n: int, fetch=fetch) -> list:
    q = urllib.parse.urlencode({"action": "query", "list": "search", "srsearch": query,
                                "srlimit": max(1, min(int(n), 10)), "format": "json", "utf8": 1})
    hits = (fetch(f"{API}?{q}").get("query") or {}).get("search") or []
    out = []
    for h in hits:
        title = str(h.get("title", ""))
        text = re.sub(r"<[^>]+>", "", str(h.get("snippet", "")))
        out.append({"title": title, "text": text,
                    "url": "https://es.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))})
    return out


def main() -> None:
    try:
        ask = json.loads(sys.stdin.read() or "{}")
        print(json.dumps({"results": search(str(ask.get("query", "")), int(ask.get("max_results", 5)))}))
    except urllib.error.HTTPError as e:
        if e.code == 429:
            print(json.dumps({"rate_limited": True, "error": "Wikipedia asked Joe to slow down"}))
        else:
            print(json.dumps({"error": f"Wikipedia answered with an error ({e.code})"}))
    except (OSError, ValueError) as e:
        print(json.dumps({"error": f"Wikipedia couldn't be reached ({e.__class__.__name__})"}))


if __name__ == "__main__":
    main()
