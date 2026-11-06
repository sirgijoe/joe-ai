"""dev115: ASK A BIGGER AI, Joe as an MCP connector, Keep my PC usable, keep-sepia restore,
scanning tips, and the night shift."""
import io
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from joeai import bigger, mcp, quality, schedule, system
from joeai.config import Settings
from joeai.server import App

from fake_ollama import FakeOllama

GOOD = """=== JOE MISSION ===
TASK: Mug blurbs
CHUNKS: 2 x 5
FORMAT: one friendly line per mug
=== END ==="""


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "settings.json"))
    fake = FakeOllama()
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    s.ollama.url = fake.url
    s.comfy.url = "http://127.0.0.1:9"
    s.save()
    a = App(settings=s)
    yield a
    fake.close()


# --------------------------------------------------------------------------- bigger AI
def test_bigger_message_has_format_request_report_and_hides_home(app):
    (app.sb.output / "_REPORT.md").write_text(f"# Joe report\nSaved in {Path.home()}/x\n", encoding="utf-8")
    (app.sb.output / "_log.txt").write_text("all fine\n'Mascot' failed: no usable items\n", encoding="utf-8")
    msg = bigger.message(app, "40 mug blurbs", with_report=True)
    assert "=== JOE MISSION ===" in msg and "CHUNKS:" in msg and "STYLE:" in msg
    assert "40 mug blurbs" in msg
    assert "JOE'S LAST REPORT" in msg and "failed: no usable items" in msg
    assert str(Path.home()) not in msg
    plain = bigger.message(app, "x", with_report=False)
    assert "JOE'S LAST REPORT" not in plain


def test_bigger_answer_is_read_back_and_checked(app):
    r = bigger.read_answer(app, "Sure! Here you go:\n```\n" + GOOD + "\n```\nHave fun.")
    assert r["ok"], r
    assert r["mission"].startswith("=== JOE MISSION ===") and r["summary"]
    assert not bigger.read_answer(app, "I can't help with that.")["ok"]
    bad = bigger.read_answer(app, "=== JOE MISSION ===\nTASK: x\nCHUNKS: banana\n=== END ===")
    assert not bad["ok"] and "problem" in bad["error"].lower()


# --------------------------------------------------------------------------- MCP connector
def _rpc(lines):
    out = io.StringIO()
    mcp.serve(io.StringIO("\n".join(json.dumps(m) for m in lines) + "\n"), out)
    return [json.loads(x) for x in out.getvalue().splitlines()]


def test_mcp_handshake_and_tool_list():
    r = _rpc([{"jsonrpc": "2.0", "id": 1, "method": "initialize",
               "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t"}}},
              {"jsonrpc": "2.0", "method": "notifications/initialized"},
              {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
              {"jsonrpc": "2.0", "id": 3, "method": "nope"}])
    assert len(r) == 3                                   # the notification gets no reply
    assert r[0]["result"]["serverInfo"]["name"] == "joe"
    names = {t["name"] for t in r[1]["result"]["tools"]}
    assert {"joe_status", "joe_queue_mission", "joe_report", "joe_mission_format"} <= names
    assert r[2]["error"]["code"] == -32601


def test_mcp_queue_check_and_sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "settings.json"))
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    s.save()
    joe = mcp.Joe(s)
    assert "Problem" in joe.call("joe_check_mission", {"mission": "TASK: x\nCHUNKS: nope"})
    out = joe.call("joe_queue_mission", {"mission": GOOD})
    assert "Queued as mug-blurbs_" in out
    assert len(list((joe.sb.missions / "Queue").glob("*.txt"))) == 1
    joe.call("joe_queue_mission", {"mission": GOOD, "tonight": True})
    assert len(list((joe.sb.missions / "Tonight").glob("*.txt"))) == 1
    bad = joe.call("joe_queue_mission", {"mission": GOOD.replace("FORMAT", "SAVE: ../../evil.md\nFORMAT")})
    assert "Nothing was queued" in bad
    (joe.sb.output / "notes.md").write_text("hello", encoding="utf-8")
    assert joe.call("joe_read_file", {"path": "notes.md"}) == "hello"
    assert "notes.md" in joe.call("joe_list_files", {})
    with pytest.raises(Exception):
        joe.call("joe_read_file", {"path": "../../settings.json"})
    st = joe.call("joe_status", {})
    assert "Waiting for the night shift: mug-blurbs_" in st


def test_mcp_tool_error_is_reported_not_crashed(monkeypatch):
    monkeypatch.setattr(mcp.Joe, "call", lambda self, n, a: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(mcp.Joe, "__init__", lambda self, settings=None: None)
    r = _rpc([{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "joe_report"}}])
    assert r[0]["result"]["isError"] and "boom" in r[0]["result"]["content"][0]["text"]


def test_mcp_client_config_uses_console_python():
    cfg = mcp.client_config()["mcpServers"]["joe"]
    assert cfg["args"][-1] == "mcp" and cfg["args"][0].endswith("Joe.pyw")
    assert not cfg["command"].lower().endswith("pythonw.exe")


# --------------------------------------------------------------------------- keep my PC usable
def test_gentle_video_is_smaller():
    s = Settings()
    assert quality.video(s, False).size == (1280, 704)
    s.engine.keep_pc_usable = True
    assert quality.video(s, False).size == (960, 544)
    s.quality.video = "low"
    assert quality.video(s, True).size == (960, 544)


def test_ease_lowers_priority_once(monkeypatch):
    from joeai.services import ServiceManager
    s = Settings()
    sm = ServiceManager(s, log=lambda *_: None)
    assert sm.ease("ollama") == []                       # off by default: nothing touched
    s.engine.keep_pc_usable = True
    calls = []
    monkeypatch.setattr(system, "pids_on_port", lambda port: calls.append(port) or [4321])
    monkeypatch.setattr(system, "pids_named", lambda name: [4321, 999])
    monkeypatch.setattr(system, "lower_priority", lambda pid: True)
    assert sm.ease("ollama") == [4321, 999] and calls == [11434]
    assert sm.ease("ollama") == []                       # once per program


@pytest.mark.skipif(system.WINDOWS, reason="nice levels")
def test_lower_priority_on_a_real_child():
    import os
    p = subprocess.Popen(["sleep", "5"])
    try:
        assert system.lower_priority(p.pid)
        assert os.getpriority(os.PRIO_PROCESS, p.pid) >= 10
    finally:
        p.kill()


# --------------------------------------------------------------------------- restore extras
FF = shutil.which("ffmpeg")


@pytest.mark.skipif(not FF, reason="needs FFmpeg")
def test_keep_sepia_comes_out_warm(tmp_path):
    from joeai.picturetools import true_restore_command
    src, out = tmp_path / "s.png", tmp_path / "o.png"
    subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=200x150", "-frames:v", "1",
                    "-vf", "hue=s=0,colorchannelmixer=rr=.9:gg=.7:bb=.5", str(src)], check=True)
    cmd = true_restore_command(FF, src, out, sepia=True)
    assert "grayworld" not in " ".join(cmd)
    subprocess.run(cmd, check=True)
    r, g, b = subprocess.run([FF, "-v", "error", "-i", str(out), "-vf", "scale=1:1", "-f", "rawvideo",
                              "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout[:3]
    assert r > g > b                                     # brown, not grey


def test_restore_form_has_sepia_and_scanning_tips():
    from joeai.tools import TOOLS
    t = TOOLS["restore-photo"]
    assert any(o.key == "sepia" and not o.default for o in t.options)
    assert "300 dpi" in t.help and "auto-correct" in t.help


# --------------------------------------------------------------------------- night shift
def test_parse_time():
    assert schedule.parse_time("23:00") == (23, 0)
    assert schedule.parse_time(" 7:05 ") == (7, 5)
    assert schedule.parse_time("25:00") is None and schedule.parse_time("11pm") is None


def test_cron_lines_add_replace_remove():
    cur = "0 5 * * * backup\n"
    added = schedule.cron_lines(cur, 23, 30, ["/my apps/Joe.AppImage", "tonight"])
    assert "backup" in added and "30 23 * * * '/my apps/Joe.AppImage' tonight # joe-ai night shift" in added
    again = schedule.cron_lines(added, 1, 0, ["/j", "tonight"])
    assert again.count(schedule.CRON_TAG) == 1 and "0 1 * * *" in again
    assert schedule.cron_lines(again) == "0 5 * * * backup\n"


def test_windows_command_and_plist():
    cmd = schedule.windows_commands(23, 5, [r"C:\P\pythonw.exe", r"C:\A\Joe.pyw", "tonight"])[0]
    assert cmd[cmd.index("/ST") + 1] == "23:05" and cmd[cmd.index("/TN") + 1] == schedule.TASK_NAME
    assert cmd[-1] == '"C:\\P\\pythonw.exe" "C:\\A\\Joe.pyw" tonight'
    pl = schedule.mac_plist(6, 0, ["/a&b/python3", "/Joe.pyw", "tonight"])
    assert "<integer>6</integer>" in pl and "<string>/a&amp;b/python3</string>" in pl


def test_joe_command_uses_joe_pyw_or_appimage(tmp_path, monkeypatch):
    monkeypatch.delenv("APPIMAGE", raising=False)
    cmd = system.joe_command("tonight")
    assert cmd[-1] == "tonight" and cmd[1].endswith("Joe.pyw")
    img = tmp_path / "Joe.AppImage"
    img.write_bytes(b"x")
    monkeypatch.setenv("APPIMAGE", str(img))
    assert system.joe_command("mcp") == [str(img), "mcp"]


def test_joe_pyw_runs_cli_commands(tmp_path):
    import sys
    root = Path(__file__).resolve().parent.parent
    r = subprocess.run([sys.executable, str(root / "Joe.pyw"), "mcp"], input='{"jsonrpc":"2.0","id":1,"method":"ping"}\n',
                       capture_output=True, text=True, timeout=60,
                       env={"JOE_CONFIG": str(tmp_path / "s.json"), "JOE_OFFLINE": "1", "PATH": "/usr/bin:/bin"})
    assert json.loads(r.stdout)["result"] == {}


def test_move_tonight_keeps_order(tmp_path):
    from joeai.sandbox import Sandbox
    sb = Sandbox(tmp_path / "ws").ensure()
    t = sb.missions / "Tonight"
    t.mkdir()
    import os
    for i, n in enumerate(("b.txt", "a.txt")):
        (t / n).write_text(GOOD)
        os.utime(t / n, (1000 + i, 1000 + i))
    (sb.missions / "Queue").mkdir(exist_ok=True)
    (sb.missions / "Queue" / "a.txt").write_text("old")
    assert schedule.move_tonight(sb) == ["b.txt", "a_2.txt"]
    assert not list(t.iterdir())


def test_tonight_with_nothing_saved_does_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "settings.json"))
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    s.save()
    import joeai.app
    monkeypatch.setattr(joeai.app, "main", lambda: pytest.fail("should not start Joe"))
    assert schedule.tonight() == 0


def test_settings_save_sets_and_removes_schedule(app, monkeypatch):
    seen = []
    monkeypatch.setattr(schedule, "apply", lambda s, log=None: seen.append(s.schedule.enabled) or {"ok": True})
    assert app.save_settings({"schedule": {"enabled": True, "time": "22:30"}})["ok"]
    assert app.save_settings({"ui": {"sounds": True}})["ok"]       # schedule unchanged: not touched
    assert app.save_settings({"schedule": {"enabled": False}})["ok"]
    assert seen == [True, False]
    monkeypatch.setattr(schedule, "apply", lambda s, log=None: {"ok": False, "error": "nope"})
    r = app.save_settings({"schedule": {"enabled": True}})
    assert not r["ok"] and not app.settings.schedule.enabled


def test_bigger_answer_with_lost_line_breaks(app):
    flat = ("=== JOE MISSION === RULES: cozy. TASK: Blurbs CHUNKS: 5 x 6 FORMAT: under 40 words.\n"
            "TASK: Care guide PART: ## First burn. Melt to the edges. PART: ## Safety. Away from pets.\n"
            "TASK: Prices CHUNKS: 1 x 30 HEADER: Name,Scent,Size SAVE: prices.csv\n"
            "TASK: Shelf art TYPE: image CHUNKS: 2 x 4 STYLE: watercolor FORMAT: candles, no text. === END ===")
    r = bigger.read_answer(app, flat)
    assert r["ok"], r
    assert "\nTASK: Blurbs\nCHUNKS: 5 x 6\n" in r["mission"] and "\nSAVE: prices.csv\n" in r["mission"]
    from joeai.mission import parse
    names = [j.name for j in parse(r["mission"]).jobs]
    assert names == ["Blurbs", "Care guide", "Prices", "Shelf art"]


# --------------------------------------------------------------------------- dev117: FROM + tidy
def test_from_must_name_an_earlier_list_task():
    from joeai.mission import MissionError, parse
    ok = parse("TASK: Blurbs\nCHUNKS: 2 x 3\nTASK: Prices\nFROM: blurbs\nCHUNKS: 2 x 3\n"
               "HEADER: Name,Price\nSAVE: p.csv")
    assert ok.jobs[1].source == "Blurbs"                  # case doesn't matter, real name kept
    for bad in ("TASK: Prices\nFROM: Blurbs\nCHUNKS: 1 x 3\nTASK: Blurbs\nCHUNKS: 1 x 3",
                "TASK: Guide\nPART: ## A. x\nTASK: B\nFROM: Guide\nCHUNKS: 1 x 3"):
        with pytest.raises(MissionError):
            parse(bad)


def test_from_hands_the_names_to_the_next_task(tmp_path, monkeypatch):
    from joeai.engine import Engine
    from joeai.mission import parse
    from joeai.sandbox import Sandbox
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "settings.json"))
    fake = FakeOllama(dup_every=1000, short_every=1000)
    try:
        s = Settings()
        s.workspace = str(tmp_path / "ws")
        s.ollama.url = fake.url
        s.comfy.url = "http://127.0.0.1:9"
        s.engine.retry_backoff_s = 0
        s.engine.gpu_temp_pause_c = 0
        s.engine.keep_awake = False
        sb = Sandbox(s.workspace_path).ensure()
        m = parse("TASK: Blurbs\nCHUNKS: 2 x 3\nFORMAT: name and one line\n"
                  "TASK: Prices\nFROM: Blurbs\nCHUNKS: 2 x 3\nHEADER: Name,Price\nSAVE: p.csv")
        states = Engine(s, sb, log=lambda *_: None).run_mission(m)
        assert states[0].status == "done", states[0].note
        names = states[0].titles
        assert len(names) == 6
        csv_prompts = [p for p in fake.prompts if "CSV COLUMNS" in p]
        assert csv_prompts
        assert all(n in csv_prompts[0] for n in names[:3]) and names[3] not in csv_prompts[0]
        assert any(names[3] in p for p in csv_prompts[1:])
    finally:
        fake.close()


def test_from_count_mismatch_warns(app):
    chk = app.check("TASK: Blurbs\nCHUNKS: 5 x 6\nTASK: Prices\nFROM: Blurbs\nCHUNKS: 2 x 5\n"
                    "HEADER: Name,Price\nSAVE: p.csv")
    assert chk["ok"] and any("only the first 10" in w for w in chk["warnings"])


def test_tidy_fixes_what_different_ais_do(app):
    messy = ("Here's your plan!\n```\n==== JOE MISSION ====\n**Task:** Blurbs\n- **Chunks:** 1 x 30\n"
             "* Format: cozy\nTask: Art\nType: pictures\nStyle: Black and White\nChunks: 2 x 4\n```\n"
             "Let me know if you want changes!")
    r = bigger.read_answer(app, messy)
    assert r["ok"], r
    assert "CHUNKS: 5 x 6" in r["mission"] and "TYPE: image" in r["mission"] and "STYLE: bw" in r["mission"]
    assert "Let me know" not in r["mission"]
    assert r["warnings"][0].startswith("Joe tidied the AI's answer")
    r2 = bigger.read_answer(app, "=== JOE MISSION ===\nTASK: Art\nTYPE: image\nSTYLE: zqx\n=== END ===")
    assert r2["ok"] and "STYLE" not in r2["mission"]
    keep = bigger.tidy("=== JOE MISSION ===\nTASK: Prices\nCHUNKS: 5 x 6\nHEADER: Name,Size\nSAVE: p.csv\n"
                       "FORMAT: one row each.\nSize: small or large\n=== END ===")[0]
    assert "\nSize: small or large" in keep                 # a sentence inside FORMAT stays text


def test_message_hides_non_writing_models_and_unused_inbox(app, monkeypatch):
    import joeai.doctor
    monkeypatch.setattr(joeai.doctor, "ollama_models", lambda sm: [{"name": "nomic-embed-text:latest"},
                        {"name": "qwen2.5vl:7b"}, {"name": "qwen3:14b"}])
    import joeai.tools
    monkeypatch.setattr(joeai.tools, "inbox_media", lambda sb, *a, **k: ["old-photo.jpg"])
    msg = bigger.message(app, "30 candle descriptions", with_report=False)
    assert "qwen3:14b" in msg and "nomic" not in msg and "qwen2.5vl" not in msg
    assert "- old-photo.jpg" not in msg and "1 of my files" in msg
    assert "FROM:" in msg and "watercolor" in msg and "mascot," not in msg
    assert "- old-photo.jpg" in bigger.message(app, "restore my old photos", with_report=False)


def test_matching_words_add_from(app):
    r = bigger.read_answer(app, "=== JOE MISSION ===\nTASK: candle product descriptions\nCHUNKS: 5 x 6\n"
                                "TASK: candle price list\nCHUNKS: 5 x 6\nHEADER: Name,Price\nSAVE: p.csv\n"
                                "FORMAT: one row per candle matching the product descriptions\n=== END ===")
    assert r["ok"] and "\nFROM: candle product descriptions\n" in r["mission"]
    plain = bigger.read_answer(app, "=== JOE MISSION ===\nTASK: Blurbs\nCHUNKS: 2 x 5\nTASK: Prices\n"
                                    "CHUNKS: 2 x 5\nHEADER: Name,Price\nSAVE: p.csv\nFORMAT: one row each\n=== END ===")
    assert "FROM:" not in plain["mission"]


def test_one_picture_request_gives_four_versions_of_one():
    from joeai.describe import one_picture
    from joeai.mission import parse
    b = "=== JOE MISSION ===\nTASK: Raccoon\nTYPE: image\nCHUNKS: 2 x 4\nFORMAT: raccoon eating a turtle\n=== END ==="
    j = parse(one_picture("make me a super cool high quality image of a racoon eating a turtle", b)).jobs[0]
    assert (j.parts, j.part_size, j.variants) == (1, 1, 4)
    for keep in ("8 images of raccoons", "some pictures of raccoons", "a few drawings of a raccoon"):
        assert one_picture(keep, b) == b


def test_quality_offer_only_when_settings_disagree():
    from joeai.describe import quality_offer
    s = Settings()
    pic = "=== JOE MISSION ===\nTASK: Raccoon\nTYPE: image\nCHUNKS: 1 x 1\n=== END ==="
    req = "make me a super cool high quality image of a racoon eating a turtle"
    assert quality_offer(s, req, pic) is None                     # already High: nothing to say
    s.quality.pictures = "low"
    o = quality_offer(s, req, pic)
    assert o["level"] == "high" and o["kinds"] == ["pictures"] and "Pictures is set to Low" in o["text"]
    assert quality_offer(s, "a picture of a raccoon", pic) is None   # didn't ask for quality
    s.quality.pictures = "high"
    o = quality_offer(s, "a quick rough picture of a raccoon", pic)
    assert o["level"] == "low" and o["kinds"] == ["pictures"]
    mixed = pic.replace("=== END ===", "TASK: Blurbs\nCHUNKS: 2 x 5\n=== END ===")
    s.quality.pictures, s.quality.writing = "low", "low"
    assert quality_offer(s, req, mixed)["kinds"] == ["pictures"]   # "image" request: pictures only


def test_offer_button_setting_saves(app):
    assert app.save_settings({"quality": {"pictures": "low"}})["ok"]
    assert app.settings.quality.pictures == "low"
