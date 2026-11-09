import threading
from pathlib import Path

import pytest

from joeai.config import Settings
from joeai.engine import Engine
from joeai.items import split_items
from joeai.mission import MissionError, parse
from joeai.sandbox import Sandbox, SandboxError

from fake_ollama import FakeOllama

MISSION = """
=== JOE MISSION ===
PROJECT: Test Studio   RULES: Plain voice.
Never mention competitors.
TASK: Mug blurbs  SAVE: test/mugs.md  CHUNKS: 3 x 4  MIN WORDS PER ITEM: 30
FORMAT: Title line, then one paragraph.
Note: keep it simple.
TASK: Kiln art  SAVE: test/kiln  CHUNKS: 1 x 2  TYPE: image
=== END ===
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "settings.json"))
    fake = FakeOllama()
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    s.ollama.url = fake.url
    s.comfy.url = "http://127.0.0.1:9"           # nothing listens here
    s.engine.retry_backoff_s = 0
    s.engine.gpu_temp_pause_c = 0
    s.engine.keep_awake = False
    sb = Sandbox(s.workspace_path).ensure()
    (sb.projects / "test-studio.md").write_text("Brand: Test Studio. Glazed stoneware.")
    yield s, sb, fake
    fake.close()


def test_sandbox_blocks_escapes(tmp_path):
    sb = Sandbox(tmp_path).ensure()
    for bad in ["../x.md", "C:/Windows/x", "/etc/passwd", "a/../../b", "CON.md", "a?b.md",
                "\\\\server\\share"]:
        with pytest.raises(SandboxError):
            sb.resolve(bad)
    assert sb.resolve("shop/a.md") == sb.output / "shop" / "a.md"
    assert sb.resolve("Inbox/facts.txt") == sb.inbox / "facts.txt"


def test_sandbox_blocks_symlink_escape(tmp_path):
    sb = Sandbox(tmp_path / "ws").ensure()
    outside = tmp_path / "outside"
    outside.mkdir()
    (sb.output / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(SandboxError):
        sb.resolve("link/x.md")


def test_parse_mission():
    m = parse(MISSION)
    assert m.project == "Test Studio"
    assert "Never mention competitors." in m.rules
    j = m.jobs[0]
    assert (j.parts, j.part_size, j.min_words, j.save) == (3, 4, 30, "test/mugs.md")
    assert "Note: keep it simple." in j.format      # prose 'Note:' is not a key
    assert m.jobs[1].type == "image"


@pytest.mark.parametrize("bad", [
    "no block here",
    "=== JOE MISSION ===\nTASK:   \n=== END ===",
    "=== JOE MISSION ===\nTASK: x  SAVE: a.md  CHUNKS: lots\n=== END ===",
    "=== JOE MISSION ===\nSAVE: a.md\n=== END ===",
])
def test_parse_errors(bad):
    with pytest.raises(MissionError):
        parse(bad)


def test_titles_drop_leaked_model_switches():
    items = split_items("## 001. Handcrafted Vase /no_thing\nA vase.\n## Bowl /no_think\nA bowl.\n## A/B test\nok")
    assert [i.title for i in items] == ["Handcrafted Vase", "Bowl", "A/B test"]


def test_split_items_strips_numbers_and_preamble():
    items = split_items("Here you go\n## 1. First\nbody one\n### Second\nbody two")
    assert [i.title for i in items] == ["First", "Second"]


def test_full_run(env):
    s, sb, fake = env
    states = Engine(s, sb, log=lambda m: None).run_mission(parse(MISSION))
    text, img = states
    assert text.status == "done", text.note
    assert text.items == 12 and text.parts_done == 3
    assert text.duplicates_dropped > 0
    assert text.short_items == 0                      # short ones were expanded
    out = sb.output / "test" / "mugs.md"
    titles = [i.title for i in split_items(out.read_text())]
    assert len(titles) == 12 and len(set(titles)) == 12
    assert "Sure! Here you go" not in out.read_text()
    assert img.status == "failed" and "ComfyUI" in img.note      # no ComfyUI in this test
    assert img.prompts_ready and len(img.prompts) == 2              # prompts were still written
    report = (sb.output / "_REPORT.md").read_text()
    assert "Mug blurbs" in report and "CHECK" in report
    # Format rules repeated in every part; only titles (never bodies) shown back.
    writes = [p for p in fake.prompts if "Write exactly" in p and "Mug blurbs" in p]
    assert all("Title line, then one paragraph." in p for p in writes)
    assert not any("word word word" in p for p in writes)


def test_rerun_never_overwrites(env):
    s, sb, _ = env
    m = parse(MISSION)
    Engine(s, sb, log=lambda m: None).run_mission(m)
    st = Engine(s, sb, log=lambda m: None).run_mission(m)[0]
    assert st.output == "test/mugs_v2.md"
    assert (sb.output / "test" / "mugs.md").exists()


def test_stop_and_resume(env):
    s, sb, _ = env
    m = parse(MISSION)
    stop = threading.Event()

    def log(msg):
        if "part 1/3" in msg and "items" in msg:
            stop.set()
    st = Engine(s, sb, log=log, stop=stop).run_mission(m)[0]
    assert st.status == "stopped" and st.parts_done == 1

    st = Engine(s, sb, log=lambda m: None).run_mission(m)[0]
    assert st.status == "done" and st.items == 12
    assert st.output == "test/mugs.md"               # same file, resumed
    titles = [i.title for i in split_items((sb.output / "test" / "mugs.md").read_text())]
    assert len(titles) == 12 and len(set(titles)) == 12


def test_retries_after_crash(env):
    s, sb, fake = env
    fake.fail_first = 2
    st = Engine(s, sb, log=lambda m: None).run_mission(parse(MISSION))[0]
    assert st.status == "done" and st.retries >= 2


def test_save_path_escape_fails_cleanly(env):
    s, sb, _ = env
    m = parse("=== JOE MISSION ===\nTASK: Bad  SAVE: ../../evil.md  CHUNKS: 1 x 1\n=== END ===")
    st = Engine(s, sb, log=lambda m: None).run_mission(m)[0]
    assert st.status == "failed"
    assert not (Path(sb.root).parent.parent / "evil.md").exists()


def test_settings_roundtrip(tmp_path):
    p = tmp_path / "s.json"
    s = Settings()
    s.ollama.text_model = "llama3.1:8b"
    s.save(p)
    p.write_text(p.read_text().replace("}", ', "junk": 1}', 1))
    assert Settings.load(p).ollama.text_model == "llama3.1:8b"


def test_near_duplicate_titles():
    from joeai.items import is_duplicate, norm_title
    seen = [norm_title("Hand-Thrown Speckled Coffee Mug")]
    assert is_duplicate("Hand Thrown Speckled Coffee Mugs", seen)
    assert not is_duplicate("Speckled Serving Bowl", seen)
    assert not is_duplicate("Mug 4", [norm_title("Mug 3")])


def test_server_needs_token_and_stays_in_sandbox(env):
    import json, threading, urllib.request, urllib.error
    from joeai.server import App, serve
    s, sb, _ = env
    app = App(s)
    httpd = serve(app)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    def get(path, token=True):
        req = urllib.request.Request(base + path, headers={"X-NR-Token": app.token} if token else {})
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read()

    status, html = get("/", token=False)
    assert status == 200 and app.token.encode() in html
    with pytest.raises(urllib.error.HTTPError) as e:
        get("/api/state", token=False)
    assert e.value.code == 401
    assert json.loads(get("/api/state")[1])["running"] is False
    with pytest.raises(urllib.error.HTTPError):
        get("/api/files?path=../..")
    assert "Output" in [x["name"] for x in json.loads(get("/api/files?path=")[1])["entries"]]
    httpd.shutdown()


GUIDED = """=== JOE MISSION ===
PROJECT: Test Studio
TASK: Design doc  SAVE: game/design.md  PROJECT: Game Proj  MIN WORDS PER ITEM: 50
FORMAT: Senior designer voice.
PART: ## Overview
Goals and player flow.
PART: ## Data. Tables with example rows.
TASK: Ammo  SAVE: game/ammo.csv  CHUNKS: 2 x 3
HEADER: type,name,caliber
TASK: Ammo guided  SAVE: game/ammo2.csv
HEADER: type,name,caliber
PART: Rifle rounds.
=== END ===
"""


def test_parse_parts_and_csv():
    m = parse(GUIDED)
    d, a, g = m.jobs
    assert d.guided and d.parts == 2 and d.part_prompts[0].startswith("## Overview")
    assert "Goals and player flow." in d.part_prompts[0]
    assert d.project == "Game Proj" and m.project == "Test Studio"
    assert a.is_csv and a.header == "type,name,caliber" and a.total_items == 6
    assert g.is_csv and g.guided
    with pytest.raises(MissionError):
        parse("=== JOE MISSION ===\nTASK: x  SAVE: a.csv  CHUNKS: 1 x 1\n=== END ===")
    with pytest.raises(MissionError):
        parse("=== JOE MISSION ===\nTASK: x  SAVE: a.md  CHUNKS: 1 x 1\nPART: y\n=== END ===")


def test_guided_and_csv_run(env):
    import csv as _csv
    s, sb, fake = env
    (sb.projects / "game-proj.md").write_text("Game: Unreal Engine 5.7, C++ only.")
    states = Engine(s, sb, log=lambda m: None).run_mission(parse(GUIDED))
    doc, ammo, ammo2 = states
    assert all(x.status == "done" for x in states), [(x.name, x.status, x.note) for x in states]
    text = (sb.output / "game" / "design.md").read_text()
    assert "Sure!" not in text and "| col | val |" in text      # kept verbatim, chatter gone
    assert doc.short_items == 0 and doc.retries >= 1            # short first try was retried
    assert any("Game: Unreal Engine 5.7" in x for x in fake.systems)      # per-task PROJECT
    assert any("Glazed stoneware" in x for x in fake.systems)            # mission PROJECT
    rows = list(_csv.reader(open(sb.output / "game" / "ammo.csv", newline="")))
    assert rows[0] == ["type", "name", "caliber"]
    assert len(rows) == 7 and all(len(r) == 3 for r in rows)    # 6 rows, all 3 columns
    assert len({r[1] for r in rows[1:]}) == 6                   # same 'type' isn't a duplicate
    assert rows[1][2].startswith("30-06, Springfield")          # comma field stays quoted
    rows2 = list(_csv.reader(open(sb.output / "game" / "ammo2.csv", newline="")))
    assert len(rows2) >= 2 and all(len(r) == 3 for r in rows2)


def test_parse_rows_json_and_csv_fallback():
    from joeai.engine import _parse_rows, _key_column
    cols = ["Type", "SKU", "Name", "Tags"]
    assert _key_column(cols) == "SKU"
    good, bad = _parse_rows('```json\n{"Type":"simple","SKU":"BL-1","Name":"Mug","Tags":["a","b"]}\n{"Type": oops}\n```', cols)
    assert good == [["simple", "BL-1", "Mug", "a, b"]] and bad == 1
    good, bad = _parse_rows('[{"type":"simple","sku":"BL-2","name":"Bowl"}]', cols)
    assert good == [["simple", "BL-2", "Bowl", ""]]
    good, bad = _parse_rows('simple,BL-3,Plate,"x, y"\nsimple,BL-4,Vase,x,y', cols)
    assert good == [["simple", "BL-3", "Plate", "x, y"]] and bad == 1


def test_mission_plain_and_friendly():
    m = parse("PROJECT: My Shop\nTASK: Instagram captions  CHUNKS: 2 x 5\nTASK: Price list  HEADER: name,price")
    assert [j.save for j in m.jobs] == ["my-shop/instagram-captions.md", "my-shop/price-list.csv"]
    v = parse("TASK: Mug process  SAVE: shop/mug.mp4").jobs[0]
    assert v.type == "video" and v.save == "shop/mug"            # a video, saved in a folder
    i = parse("TASK: Kiln  SAVE: art/kiln.png").jobs[0]
    assert i.type == "image" and i.save == "art/kiln"
    with pytest.raises(MissionError, match="TYPE: video"):
        parse("TASK: Script  SAVE: a.mp4  TYPE: text")
    with pytest.raises(MissionError, match="TASK:"):
        parse("make me some captions please")
    assert parse("=== JOE MISSION ===\nTASK: A  SAVE: a.md\n").jobs[0].save == "a.md"   # no END


def test_near_twins_are_not_duplicates():
    from joeai.items import is_duplicate, norm_title
    seen = [norm_title("Write 10 Instagram captions for my candle shop")]
    assert not is_duplicate("Write 10 Instagram captions for my soap shop", seen)
    assert is_duplicate("write 10 instagram captions for the candle shop!", seen)
    one = [norm_title("Joe is on it. Go to bed.")]
    assert not is_duplicate("Joe is on it. Go to sleep.", one)
    assert is_duplicate("Blue Mugs", [norm_title("The Blue Mug")])


def test_report_names_skipped_parts():
    from types import SimpleNamespace
    from joeai.report import _mission_lines
    st = SimpleNamespace(name="Test requests", status="partial", parts_total=2, parts_done=2,
                         skipped_parts=[2], note="", items=15, words=334, retries=3, short_items=0,
                         duplicates_dropped=15, flags=[], output="joe-dev/x.md", tokens_in=0,
                         tokens_out=0, model_seconds=0)
    from joeai.mission import parse
    m = parse("TASK: Test requests\nCHUNKS: 2 x 15\nFORMAT: one line each")
    lines = "\n".join(_mission_lines(m, [st]))
    assert "part 2 skipped" in lines and "0 part(s)" not in lines


def test_font_is_bundled_and_served_locally():
    from joeai.server import UI_DIR, local_font
    assert local_font() and (UI_DIR / "fonts" / "OFL.txt").is_file()
    html = (UI_DIR / "index.html").read_text(encoding="utf-8")
    assert "googleapis" not in html and "/fonts/fonts.css" in html
    css = (UI_DIR / "fonts" / "fonts.css").read_text(encoding="utf-8")
    for f in __import__("re").findall(r'url\("/fonts/([^"]+)"\)', css):
        assert (UI_DIR / "fonts" / f).is_file(), f
    assert (UI_DIR / "fonts" / "OFL-AtkinsonHyperlegible.txt").is_file()


def test_slow_comfyui_gets_a_plain_hint(env, monkeypatch):
    from joeai import services as services_mod
    s, _, _ = env
    sm = services_mod.ServiceManager(s, log=lambda x: None)
    import itertools, types
    ticks = itertools.count(0, 20)                      # a private clock: other threads keep the real one
    monkeypatch.setattr(services_mod, "time", types.SimpleNamespace(monotonic=lambda: next(ticks),
                                                                    sleep=lambda x: None))
    ok = sm._wait(lambda: False, 120, "ComfyUI to open", hint_after=45, hint="look at its window")
    assert not ok and sm.attention == "look at its window"


def test_part_retried_without_thinking_when_thinking_fills_the_room(env):
    from joeai.ollama import ChatResult
    s, sb, fake = env
    s.quality.writing = "high"
    eng = Engine(s, sb, log=lambda m: None)
    calls = []
    real = eng.client.chat

    def chat(msgs, model=None, think=None, **kw):
        calls.append(think)
        if think is not False and "Write exactly" in msgs[-1]["content"]:
            return ChatResult("", 100, 5600, 45.0)          # all thinking, no answer
        return real(msgs, model=model, think=think, **kw)
    eng.client.chat = chat
    st = eng.run_mission(parse("=== JOE MISSION ===\nTASK: Jokes\nCHUNKS: 1 x 3\n"
                               "FORMAT: One line.\n=== END ==="))[0]
    assert st.status == "done", st.note
    assert calls.count(False) >= 1 and len([c for c in calls if c is not False]) == 1
