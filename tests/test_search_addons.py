"""Search add-ons (community.py, docs/ADDONS.md "Search sources"): a separate program gets the search
words and prints results in Joe's fixed shape. Time limit, bare environment, own Python environment,
a plain risk screen, off until the person ticks it. No real internet: the programs here are local."""
import importlib.util
import json
import os
import sys
import textwrap
from pathlib import Path

import pytest

from joeai import community, websearch
from joeai.config import Settings
from joeai.sandbox import Sandbox

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "addons" / "wikipedia-es"

ECHO = textwrap.dedent('''
    import json, os, sys
    ask = json.loads(sys.stdin.read())
    seen = sorted(k for k in os.environ if "KEY" in k or k.startswith("JOE") or "TOKEN" in k)
    print(json.dumps({"results": [
        {"title": "You asked: " + ask["query"], "url": "https://example.org/a", "text": "n=" + str(ask["max_results"]) + " env=" + ",".join(seen) + " cwd=" + os.getcwd()},
        {"title": "bad", "url": "file:///etc/passwd", "text": "x"},
        {"title": "bad2", "url": "javascript:alert(1)", "text": "x"},
        "not a dict"]}))
''')


def _make(base: Path, aid="my-search", script=ECHO, **search):
    d = base / "Add-ons" / aid
    d.mkdir(parents=True, exist_ok=True)
    (d / "search.py").write_text(script, encoding="utf-8")
    s = {"name": "My search", "about": "Test source.", "goes_to": "example.org", "program": "joe:python",
         "args": ["{addon}/search.py"], "timeout": 10, "pace": 0}
    s.update(search)
    (d / "addon.json").write_text(json.dumps({"id": aid, "name": "My search add-on", "author": "Tester",
                                              "search": s}), encoding="utf-8")
    return d


@pytest.fixture
def ws(tmp_path):
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    sb = Sandbox(s.workspace_path).ensure()
    return s, sb


def test_reading_the_search_part(ws, tmp_path):
    s, sb = ws
    a = community.read(_make(sb.root))
    assert a["search"]["program"] == "joe:python" and a["search"]["timeout"] == 10
    d = community.describe({**a, "state": "off"})
    assert d["search"]["id"] == "addon:my-search" and "sees your search words" in d["search"]["risk"]
    assert "Joe's makers don't control it" in d["search"]["risk"]
    bad = [({"program": "magick"}, "joe:python or env:python"),
           ({"program": "bin/x.exe"}, "joe:python or env:python"),
           ({"args": ["{addon}/search.py", "{input}"]}, "isn't allowed"),
           ({"args": "search.py"}, "args list"),
           ({"args": ["{addon}/../../evil.py"]}, "outside the add-on"),
           ({"args": ["-c", "print(1)"]}, "first arg must be the add-on's own script"),
           ({"args": ["{addon}/missing.py"]}, "isn't a file in the add-on"),
           ({"program": "env:python", "requirements": []}, "needs its requirements"),
           ({"program": "env:python", "requirements": ["ddgs"]}, "exact package versions"),
           ({"program": "env:python", "requirements": ["ddgs>=9"]}, "exact package versions"),
           ({"program": "env:python", "requirements": ["ddgs==9.1; os.system('x')"]}, "exact package versions"),
           ({"program": "env:python", "requirements": ["--index-url=http://evil==1"]}, "exact package versions"),
           ({"requirements": ["ddgs==9.16.0"]}, "need program env:python"),
           ({"program": "env:python", "requirements": ["ddgs==9.16.0"], "python": "2.7"}, "3.10 to 3.14")]
    for i, (change, why) in enumerate(bad):
        with pytest.raises(community.AddonError, match=why):
            community.read(_make(tmp_path / f"b{i}", **change))
    a = community.read(_make(tmp_path / "t", timeout=999, pace=-5))
    assert a["search"]["timeout"] == 60 and a["search"]["pace"] == 0


def test_off_until_turned_on_and_ticked(ws):
    s, sb = ws
    _make(sb.root)
    assert "addon:my-search" not in websearch.all_providers(s)               # added, still off
    assert community.enable(sb, "my-search", True, log=lambda *_: None)["ok"]
    assert "addon:my-search" in websearch.all_providers(s)                  # on: listed in Setup...
    rows = {r["id"]: r for r in websearch.providers_for_setup(s)}
    assert not rows["addon:my-search"]["on"]                                 # ...but not ticked
    assert websearch.order(s) == ["ollama", "wikipedia"]


def test_the_program_gets_only_the_words_and_a_bare_room(ws, monkeypatch):
    s, sb = ws
    _make(sb.root)
    community.enable(sb, "my-search", True, log=lambda *_: None)
    monkeypatch.setenv("OLLAMA_API_KEY", "secret-1")
    monkeypatch.setenv("JOE_CONFIG", str(sb.root / "settings.json"))
    monkeypatch.setenv("GITHUB_TOKEN", "secret-2")
    s.web.providers = "addon:my-search,wikipedia"
    s.web.ollama_key = "secret-3"
    f = websearch.find("cone 6 glaze", s, 4)
    assert f.source == "addon:my-search" and f.label == "My search" and f.via() == "Found with My search."
    assert [r.url for r in f] == ["https://example.org/a"]                     # file: and javascript: dropped
    assert f[0].title == "You asked: cone 6 glaze" and "n=4 env= " in f[0].text
    assert "secret" not in f[0].text and str(sb.root) not in f[0].text.split("cwd=")[1]


def test_slow_broken_or_blocked_programs_fall_back(ws):
    s, sb = ws
    s.web.providers = "addon:my-search"
    cases = [("import time; time.sleep(30)", "longer than 5 seconds"),
             ("print('not json')", "exit code 0"),
             ("import sys; sys.stderr.write('boom happened\\n'); sys.exit(3)", "boom happened"),
             ("import json; print(json.dumps({'error': 'no internet'}))", "no internet"),
             ("import json; print(json.dumps({'rate_limited': True, 'error': 'DuckDuckGo said slow down'}))", "slow down"),
             ("print('x' * 300000)", "far too much")]
    for script, why in cases:
        websearch.reset_cooldowns()
        _make(sb.root, script=script, timeout=5)
        community.enable(sb, "my-search", True, log=lambda *_: None)          # files changed: turn on again
        f = websearch.find("q", s)
        assert not f and why in f.via(), (script, f.via())
    # resting after "slow down": not run again for a while
    websearch.reset_cooldowns()
    _make(sb.root, script="import json; print(json.dumps({'blocked': True}))")
    community.enable(sb, "my-search", True, log=lambda *_: None)
    assert "blocked" in websearch.find("q", s).via()
    assert "resting" in websearch.find("q2", s).via()


def test_a_changed_add_on_stops_and_joe_says_so(ws):
    s, sb = ws
    d = _make(sb.root)
    community.enable(sb, "my-search", True, log=lambda *_: None)
    s.web.providers = "addon:my-search,wikipedia"
    (d / "search.py").write_text(ECHO + "\n# changed\n", encoding="utf-8")
    assert "addon:my-search" not in websearch.all_providers(s)
    calls = []
    w = websearch.BUILT_IN["wikipedia"]
    websearch.BUILT_IN["wikipedia"] = websearch.Provider("wikipedia", "Wikipedia", "", "", lambda *a: calls.append(1) or [])
    try:
        f = websearch.find("q", s)
    finally:
        websearch.BUILT_IN["wikipedia"] = w
    assert calls and "the search add-on my-search is off or changed" in f.via()


def test_own_environment_is_built_only_when_turned_on(ws, monkeypatch):
    from joeai import addons
    s, sb = ws
    _make(sb.root, program="env:python", requirements=["ddgs==9.16.0", "primp==0.15.0"], python="3.12")
    cmds = []
    monkeypatch.setattr(addons, "get_uv", lambda log: "uv")

    def run(cmd, log, timeout=3600, cwd=None):
        cmds.append(cmd)
        if cmd[1] == "venv":
            py = community.env_python(Path(cmd[-1]))
            py.parent.mkdir(parents=True, exist_ok=True)
            py.write_text("")
        return True
    monkeypatch.setattr(addons, "_run", run)
    assert not cmds                                                          # nothing installed by adding it
    assert community.enable(sb, "my-search", True, log=lambda *_: None)["ok"]
    assert cmds[0][:4] == ["uv", "venv", "--python", "3.12"]
    assert cmds[1][:2] == ["uv", "pip"] and "--no-build" in cmds[1] and cmds[1][-2:] == ["ddgs==9.16.0", "primp==0.15.0"]
    assert str(sb.root / "Add-ons" / "_envs" / "my-search") in cmds[0][-1]
    a = {x["id"]: x for x in community.scan(sb)}["my-search"]
    assert community.env_ready(sb, a)
    cmds.clear()
    community.enable(sb, "my-search", False, log=lambda *_: None)
    community.enable(sb, "my-search", True, log=lambda *_: None)
    assert cmds == []                                                        # already set up: not again
    community.remove(sb, "my-search", log=lambda *_: None)
    assert not (sb.root / "Add-ons" / "_envs" / "my-search").exists()        # removing it removes its Python too


def test_a_failed_environment_keeps_it_off(ws, monkeypatch):
    from joeai import addons
    s, sb = ws
    _make(sb.root, program="env:python", requirements=["ddgs==9.16.0"])
    monkeypatch.setattr(addons, "get_uv", lambda log: "uv")
    monkeypatch.setattr(addons, "_run", lambda *a, **k: False)
    r = community.enable(sb, "my-search", True, log=lambda *_: None)
    assert not r["ok"] and "stays off" in r["error"]
    assert "addon:my-search" not in websearch.all_providers(s)


def test_the_worked_example_from_the_guide(ws):
    a = community.read(EXAMPLE)
    assert a["search"]["program"] == "joe:python" and not a["search"]["requirements"]
    spec = importlib.util.spec_from_file_location("wikipedia_es_example", EXAMPLE / "search.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    asked = []

    def fake(url):
        asked.append(url)
        return {"query": {"search": [{"title": "Cerámica raku", "snippet": "La <span>cerámica</span> raku es..."}]}}
    out = mod.search("raku", 3, fetch=fake)
    assert out == [{"title": "Cerámica raku", "text": "La cerámica raku es...",
                    "url": "https://es.wikipedia.org/wiki/Cer%C3%A1mica_raku"}]
    assert asked[0].startswith("https://es.wikipedia.org/w/api.php?") and "srsearch=raku" in asked[0]
    doc = (Path(__file__).resolve().parent.parent / "docs" / "ADDONS.md").read_text(encoding="utf-8")
    assert "## Search sources" in doc and "wikipedia-es" in doc and "env:python" in doc
    js = (Path(community.__file__).parent / "ui" / "app.js").read_text(encoding="utf-8")
    assert "SEARCH SOURCE" in js and "s.risk" in js


def test_far_too_much_output_is_stopped_at_once(ws):
    import time
    s, sb = ws
    _make(sb.root, script="import sys\nwhile True: sys.stdout.write('x' * 65536)", timeout=30)
    community.enable(sb, "my-search", True, log=lambda *_: None)
    s.web.providers = "addon:my-search"
    t = time.monotonic()
    f = websearch.find("q", s)
    assert "far too much" in f.via() and time.monotonic() - t < 10          # not left running to the limit


@pytest.mark.skipif(os.name == "nt", reason="checks the process group on Linux and Mac")
def test_anything_it_started_is_stopped_too(ws, tmp_path):
    import signal
    import time
    s, sb = ws
    pidfile = tmp_path / "child.pid"
    _make(sb.root, timeout=5, script=textwrap.dedent(f'''
        import subprocess, sys, time
        c = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        open({str(pidfile)!r}, "w").write(str(c.pid))
        time.sleep(60)
    '''))
    community.enable(sb, "my-search", True, log=lambda *_: None)
    s.web.providers = "addon:my-search"
    assert "longer than 5 seconds" in websearch.find("q", s).via()
    pid = int(pidfile.read_text())
    time.sleep(0.5)
    try:
        os.kill(pid, 0)
        alive = True
        try:
            os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            pass
        with open(f"/proc/{pid}/stat") as fh:
            alive = fh.read().split()[2] != "Z"
    except (ProcessLookupError, FileNotFoundError):
        alive = False
    if alive:
        os.kill(pid, signal.SIGKILL)
    assert not alive


# --------------------------------------------------------------------------- Fable review, 2026-11-15
def test_turning_off_or_removing_it_unticks_its_search_source(ws, monkeypatch):
    """Otherwise Joe kept saying "the search add-on ... is off or changed" on every lookup, and an
    add-on added later under the same id would have been ticked before the person ticked it."""
    from types import SimpleNamespace
    from joeai import server
    s, sb = ws
    saved = []
    monkeypatch.setattr(type(s), "save", lambda self, path=None: saved.append(self.web.providers))
    app = SimpleNamespace(settings=s, log=lambda *_: None)
    s.web.providers = "addon:my-search,wikipedia"
    server.App.forget_search_addon(app, "My-Search")
    assert s.web.providers == "wikipedia" and saved == ["wikipedia"]
    server.App.forget_search_addon(app, "my-search")                         # not there: nothing saved again
    assert saved == ["wikipedia"]
    _make(sb.root)                                                           # added again under the same id
    community.enable(sb, "my-search", True, log=lambda *_: None)
    assert "addon:my-search" in websearch.all_providers(s) and websearch.order(s) == ["wikipedia"]
    code = (Path(server.__file__)).read_text(encoding="utf-8")
    assert code.count("app.forget_search_addon(") == 2                      # the turn-off and the remove routes
