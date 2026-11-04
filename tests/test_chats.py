"""Past chats: fresh chat each start, saved, listed, read, deleted, and pruned by age."""
import json
import os
import threading
import time
import urllib.request

from joeai.chats import Chats

from test_core import env  # noqa: F401  (shared fixture)


def test_chat_saved_listed_and_deleted(tmp_path):
    c = Chats(tmp_path / "chats")
    c.new()
    assert c.list() == [] and not (tmp_path / "chats").exists()       # empty chats leave no file
    c.add("hello joe", "Hi there.")
    c.add("make 5 blurbs", "It's in the Builder.", mission="=== JOE MISSION ===\nTASK: x\n=== END ===")
    [row] = c.list()
    assert row["title"] == "hello joe" and row["messages"] == 4 and row["current"]
    full = c.get(row["id"])
    assert full["messages"][3]["mission"].startswith("=== JOE")
    c.new()
    c.add("second chat", "ok")
    assert len(c.list()) == 2
    assert c.delete(row["id"]) and len(c.list()) == 1
    assert c.get("../../settings") is None and not c.delete("../x")    # stays in its folder
    assert c.delete_all() == 1 and c.list() == []


def test_old_chats_pruned_but_never_the_current_one(tmp_path):
    c = Chats(tmp_path / "chats")
    c.add("old one", "ok")
    old_id = c.list()[0]["id"]
    c.new()
    c.add("today", "ok")
    p = tmp_path / "chats" / f"{old_id}.json"
    month_ago = time.time() - 31 * 86400
    os.utime(p, (month_ago, month_ago))
    assert c.prune(0) == 0                       # 0 = keep everything
    assert c.prune(30) == 1 and [r["title"] for r in c.list()] == ["today"]
    cur = tmp_path / "chats" / f"{c.current['id']}.json"
    os.utime(cur, (month_ago, month_ago))
    assert c.prune(30) == 0                      # the chat in progress is never pruned


def test_server_talk_saves_chat_and_new_chat_starts_fresh(env):  # noqa: F811
    from joeai.server import App, serve
    s, sb, _ = env
    app = App(s)
    httpd = serve(app)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    def call(path, body=None):
        req = urllib.request.Request(base + path, headers={"X-NR-Token": app.token,
                                                           "Content-Type": "application/json"},
                                     data=None if body is None else json.dumps(body).encode(),
                                     method="GET" if body is None else "POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    try:
        assert call("/api/chats")["chats"] == []
        r = call("/api/talk", {"text": "what can you do?"})
        assert r["ok"]
        [c1] = call("/api/chats")["chats"]
        assert c1["title"] == "what can you do?" and c1["current"]
        call("/api/talk/clear", {})
        assert app.chat_history == []
        call("/api/talk", {"text": "second"})
        assert len(call("/api/chats")["chats"]) == 2
        assert [c["title"] for c in call("/api/chats?q=SECOND")["chats"]] == ["second"]   # search
        opened = call("/api/chats/open", {"id": c1["id"]})                   # pick an old chat back up
        assert opened["ok"] and app.chat_history[0]["content"] == "what can you do?"
        call("/api/talk", {"text": "and one more"})
        assert len(call("/api/chats")["chats"]) == 2                         # added to the old one
        assert call("/api/chats/get", {"id": c1["id"]})["chat"]["messages"][-2]["text"] == "and one more"
        assert call("/api/chats")["chats"][0]["id"] == c1["id"]              # newest activity first
        got = call("/api/chats/get", {"id": c1["id"]})
        assert got["ok"] and got["chat"]["messages"][0]["text"] == "what can you do?"
        d = call("/api/chats/delete", {"id": c1["id"]})
        assert d["deleted"] == 1 and d["was_current"] and app.chat_history == []
        assert call("/api/chats/delete", {"all": True})["deleted"] == 1
        assert call("/api/chats")["chats"] == []
        assert (sb.meta / "chats").is_dir()      # inside Joe's own folder
    finally:
        httpd.shutdown()


def test_hello_voice_is_made_once_and_kept(env, tmp_path, monkeypatch):  # noqa: F811
    from joeai import server as srv
    from joeai.server import App
    s, sb, _ = env
    monkeypatch.setattr(srv, "config_dir", lambda: tmp_path / "cfg")
    app = App(s)
    calls = []
    monkeypatch.setattr(app, "speak", lambda text: (calls.append(text) or b"RIFFwav", ""))
    monkeypatch.setattr(app, "quiet", lambda: False)
    assert app.hello_audio() == (b"RIFFwav", "")
    assert app.hello_audio() == (b"RIFFwav", "")
    assert calls == ["Joe is now reporting for duty."]          # second time from the saved copy
    s.ui.hello_text = "Morning, boss."
    app.hello_audio()
    assert calls[-1] == "Morning, boss." and len(list((tmp_path / "cfg" / "hello").glob("*.wav"))) == 1
    s.voice.voice = "bf_emma"                                          # a new voice = a new hello
    app.hello_audio()
    assert len(calls) == 3
    monkeypatch.setattr(app, "quiet", lambda: True)
    assert app.hello_audio()[0] == b""                                 # silent in quiet hours


def test_old_hello_words_are_updated(tmp_path):
    from joeai.config import Settings
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"ui": {"hello_text": "Hello! Joe here, reporting for duty."}}))
    assert Settings.load(p).ui.hello_text == "Joe is now reporting for duty."
    p.write_text(json.dumps({"ui": {"hello_text": "Morning, boss."}}))      # your own words stay
    assert Settings.load(p).ui.hello_text == "Morning, boss."


def test_intro_screen_can_be_turned_off(env):  # noqa: F811
    from joeai.server import App, serve
    s, sb, _ = env
    app = App(s)
    httpd = serve(app)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    try:
        page = lambda: urllib.request.urlopen(url, timeout=5).read().decode()  # noqa: E731
        assert '<meta name="joe-intro" content="1">' in page()
        app.settings.ui.intro = False
        assert '<meta name="joe-intro" content="0">' in page()
        with urllib.request.urlopen(url + "sounds/intro.wav", timeout=5) as r:     # Joe's 8-bit theme
            body = r.read()
            assert r.headers["Content-Type"] == "audio/wav" and body[:4] == b"RIFF" and len(body) < 400_000
    finally:
        httpd.shutdown()


def test_a_chat_holds_the_whole_session(env):  # noqa: F811
    """Plans, runs, results and the run's log go in the chat; a new chat is a fresh start,
    and a run that finishes after NEW CHAT still reports to the chat it started in."""
    from joeai.server import App
    s, sb, _ = env
    app = App(s)
    app.log("old line from before")
    assert app.new_session() == {"ok": True, "running": False}
    assert app.state()["log"] == [] and app.state()["jobs"] == []          # a clean screen
    from joeai import describe
    r = describe.draft(app, "write 5 tips about glazing")
    assert r["ok"], r
    app.note_chat({"who": "you", "text": "write 5 tips about glazing"})
    app.note_chat({"who": "joe", "kind": "plan", "text": "Here's the plan:", "summary": r["summary"],
                   "mission": r["mission"]})
    q = app.enqueue("TASK: Tips  CHUNKS: 1 x 2")
    assert q["ok"]
    first = app.chats.current["id"]
    app.new_session()                                                     # NEW CHAT while it runs
    app.thread.join(60)
    d = app.chats.get(first)
    kinds = [m.get("kind", "") for m in d["messages"]]
    assert kinds == ["", "plan", "run", "result"], kinds
    res = d["messages"][-1]
    assert res["tasks"][0]["status"] == "done" and res["tasks"][0]["output"].startswith("Output/")
    assert any("Finished" in ln for ln in res["log"]) and res["report"].startswith("# Joe report")
    assert d["title"].startswith("write 5 tips")
    app.new_session()                                                     # after it finished
    assert app.state()["log"] == [] and app.state()["jobs"] == [] and app.state()["media"] == []
    assert len(app.chats.list()) == 1                                     # empty chats leave no file


def test_session_pictures_go_in_the_chat(env, tmp_path):  # noqa: F811
    """Pictures a tool made (inside its own folder) are listed in the run's chat with full paths."""
    from types import SimpleNamespace
    from joeai.server import App
    s, sb, _ = env
    app = App(s)
    (sb.output / "shop" ).mkdir(parents=True)
    (sb.output / "shop" / "mug.webp").write_bytes(b"x")
    (sb.output / "pics").mkdir()
    (sb.output / "pics" / "001_a.png").write_bytes(b"x")
    tool = SimpleNamespace(media_files=["mug.webp", "listings.csv"], output="shop")
    media = SimpleNamespace(media_files=["pics/001_a.png"], output="pics")
    assert app.media_of([tool, media]) == ["Output/shop/mug.webp", "Output/pics/001_a.png"]
