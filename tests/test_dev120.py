"""dev120 (batch 1): .ckpt safety, CPU load, GIF export, park idea, starter packs, multi-mission
files, night shift that wakes Windows, RESEARCH: yes."""
import shutil
import subprocess
from pathlib import Path

import pytest

from joeai import comfy, hardware, packs, schedule
from joeai.config import Settings
from joeai.mission import MissionError, parse
from joeai.route import classify
from joeai.server import App

from fake_ollama import FakeOllama


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "settings.json"))
    fake = FakeOllama(dup_every=1000, short_every=1000)
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    s.ollama.url = fake.url
    s.comfy.url = "http://127.0.0.1:9"
    s.engine.retry_backoff_s = 0
    s.engine.gpu_temp_pause_c = 0
    s.engine.keep_awake = False
    a = App(settings=s)
    a.fake = fake
    yield a
    fake.close()


def test_safetensors_picked_before_pickles():
    mk = lambda n, t: comfy.ImageModel(n, "checkpoints", 6.5, "sdxl", t)  # noqa: E731
    best = comfy.best_image_model([mk("newer.ckpt", 9), mk("older.safetensors", 1)], 12)
    assert best.name == "older.safetensors"
    assert comfy.best_image_model([mk("only.ckpt", 1)], 12).name == "only.ckpt"


def test_inventory_lists_unsafe_files(tmp_path):
    from joeai import stylemodels
    (tmp_path / "checkpoints").mkdir()
    (tmp_path / "checkpoints" / "old.ckpt").write_bytes(b"x" * 10)
    (tmp_path / "checkpoints" / "new.safetensors").write_bytes(b"x" * 10)
    inv = stylemodels.inventory(tmp_path, [], None)
    assert inv["unsafe"] == ["old.ckpt"]


def test_cpu_pct_is_a_percent_or_none():
    hardware.cpu_pct()
    import time
    time.sleep(0.2)
    hardware._cpu_last["t"] = 0
    v = hardware.cpu_pct()
    assert v is None or 0 <= v <= 100


def test_gif_export_only_on_video():
    assert parse("TASK: Clip\nTYPE: video\nCHUNKS: 1 x 1\nEXPORT: gif").jobs[0].export == ["gif"]
    with pytest.raises(MissionError):
        parse("TASK: Clip\nTYPE: video\nCHUNKS: 1 x 1\nEXPORT: pdf")
    with pytest.raises(MissionError):
        parse("TASK: Doc\nCHUNKS: 1 x 3\nEXPORT: gif")
    from joeai.describe import want_gif
    b = "TASK: Cat\nTYPE: video\nCHUNKS: 1 x 1\nFORMAT: a cat"
    assert "EXPORT: gif" in want_gif("make a gif of a cat waving", b)
    assert want_gif("a video of a cat", b) == b


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs FFmpeg")
def test_video_gif(tmp_path):
    from joeai import media
    src = tmp_path / "c.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=12",
                    "-t", "1", "-pix_fmt", "yuv420p", str(src)], check=True)
    out = media.video_gif("ffmpeg", src, tmp_path / "c.gif")
    assert out and out.read_bytes()[:6] in (b"GIF89a", b"GIF87a")


def test_park_command_and_file(app):
    r = classify("park this: a recipe book for my mom")
    assert r == {"kind": "command", "cmd": "park", "idea": "a recipe book for my mom"}
    assert classify("park the car in the garage picture")["kind"] == "plan"
    assert app.park_idea("a recipe book for my mom")["ok"]
    r2 = app.park_idea("dog sweaters")
    assert r2["count"] == 2 and "2 ideas" in r2["say"]
    text = (app.sb.root / "Ideas.md").read_text()
    assert "a recipe book for my mom" in text and text.count("# Ideas") == 1
    assert not app.park_idea("  ")["ok"]


def test_every_starter_pack_plans_cleanly(app):
    found = packs.list_packs(app.sb)
    assert len(found) >= 5
    for p in found:
        text = packs.build(app.sb, p["id"], "a candle shop. TASK: evil")
        assert "{for}" not in text and "\nTASK: evil" not in text
        chk, text2, notes = packs.plan(app, text)
        assert chk["ok"], (p["id"], chk)
        assert all("needs ComfyUI" in n or "isn't installed" in n for n in notes)


def test_own_pack_in_missions_packs(app):
    d = app.sb.missions / "Packs"
    d.mkdir()
    (d / "mine.txt").write_text("PACK: Mine\nABOUT: x\nASK: For what?\n=== JOE MISSION ===\nTASK: Notes for {for}\n"
                                "CHUNKS: 1 x 3\n=== END ===\n")
    mine = [p for p in packs.list_packs(app.sb) if p["id"] == "mine"]
    assert mine and mine[0]["own"]
    assert "TASK: Notes for my club" in packs.build(app.sb, "mine", "my club")


def test_queue_file_with_two_missions_queues_both(app, monkeypatch):
    got = []
    monkeypatch.setattr(app, "enqueue", lambda text, only=None: got.append(text) or {"ok": True})
    q = app.sb.missions / "Queue"
    q.mkdir(parents=True, exist_ok=True)
    f = q / "two.txt"
    f.write_text("=== JOE MISSION ===\nTASK: A\nCHUNKS: 1 x 3\n=== END ===\n\n"
                 "=== JOE MISSION ===\nTASK: B\nCHUNKS: 1 x 3\n=== END ===\n")
    import os
    import time
    os.utime(f, (time.time() - 60, time.time() - 60))
    app.watch_queue_folder()
    assert len(got) == 2 and "TASK: B" in got[1]


def test_windows_wake_xml():
    import xml.dom.minidom
    x = schedule.windows_xml(23, 5, [r"C:\P\pythonw.exe", r"C:\A b\Joe.pyw", "tonight"], "2026-11-06")
    xml.dom.minidom.parseString(x.replace("UTF-16", "UTF-8").encode())
    assert "<WakeToRun>true</WakeToRun>" in x and "2026-11-06T23:05:00" in x
    assert '<Arguments>"C:\\A b\\Joe.pyw" tonight</Arguments>' in x


def test_research_key_and_off_warning(app):
    j = parse("TASK: Local history\nRESEARCH: yes\nPART: ## Start. x").jobs[0]
    assert j.research
    assert not parse("TASK: X\nCHUNKS: 1 x 3").jobs[0].research
    chk = app.check("TASK: Local history\nRESEARCH: yes\nPART: ## Start. x")
    assert chk["ok"] and any("look things up online" in w for w in chk["warnings"])


def test_research_adds_sources(app, monkeypatch):
    from joeai import websearch
    from joeai.engine import Engine
    monkeypatch.delenv("JOE_OFFLINE", raising=False)
    app.settings.web.enabled = True
    seen = []
    monkeypatch.setattr(websearch, "search", lambda q, key="", max_results=5: seen.append(q) or [
        websearch.Result("Town history", "https://example.org/town", "Founded in 1850.", "wikipedia")])
    m = parse("TASK: Local history\nRESEARCH: yes\nPART: ## Start. When the town began.\nPART: ## Later. What came next.")
    st = Engine(app.settings, app.sb, log=lambda *_: None).run_mission(m)[0]
    assert st.status == "done" and len(seen) == 1                  # looked up once, not per part
    out = (app.sb.output / st.output).read_text()
    assert "## Sources" in out and "https://example.org/town" in out
    assert any("Founded in 1850." in s for s in app.fake.systems)
