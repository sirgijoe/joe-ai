"""Tools (tools.py): Transcribe end to end with the fake voice helper and fake Ollama."""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

from joeai import addons, describe, tools
from joeai.config import Settings
from joeai.engine import Engine
from joeai.mission import MissionError, mission_to_dict, parse, to_text
from joeai.server import App

from fake_ollama import FakeOllama

HERE = Path(__file__).parent


def wav(path: Path, seconds: float = 1.0) -> Path:
    """A tiny silent 16 kHz mono WAV."""
    n = int(16000 * seconds)
    data = b"\x00\x00" * n
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt " +
                     struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16) +
                     b"data" + struct.pack("<I", len(data)) + data)
    return path


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "settings.json"))
    monkeypatch.setenv("JOE_ADDONS", str(tmp_path / "addons"))
    fake = FakeOllama()
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    s.ollama.url = fake.url
    s.comfy.url = "http://127.0.0.1:9"
    s.comfy.ffmpeg = str(tmp_path / "no-ffmpeg")         # force the plain-WAV path
    s.engine.retry_backoff_s = 0
    s.engine.gpu_temp_pause_c = 0
    s.engine.keep_awake = False
    a = App(settings=s)
    a.voice = addons.VoiceWorker(python=sys.executable, script=HERE / "fake_voice_worker.py")
    monkeypatch.setattr(tools, "needs_problem", lambda settings, job: "")      # voice "installed"
    import joeai.doctor as doctor
    monkeypatch.setattr(doctor, "ffmpeg_exe", lambda configured="": None)
    yield a
    a.voice.close()
    fake.close()


def test_catalog_has_ready_and_planned_tools():
    cat = tools.catalog()
    ready = [t["id"] for t in cat if t["ready"]]
    assert "transcribe" in ready
    assert any(not t["ready"] for t in cat)                     # planned tools show as "coming soon"
    assert {t["group"] for t in cat} <= set(tools.GROUPS)


def test_tool_missions_parse_and_round_trip():
    m = parse("TASK: Meeting  TYPE: transcribe\nINPUT: tools/transcribe/a.mp3\nOPTIONS: notes")
    j = m.jobs[0]
    assert j.tool and not j.media and j.options == ["notes"] and j.save == "meeting"
    again = parse(to_text("", "", mission_to_dict(m)["tasks"])).jobs[0]
    assert again.options == ["notes"] and again.type == "transcribe"
    for bad in ("TASK: x  TYPE: transcribe",                                  # no INPUT
                "TASK: x  TYPE: transcribe  INPUT: a.mp3  OPTIONS: karaoke",
                "TASK: x  TYPE: transcribe  INPUT: a.mp3  CHUNKS: 2 x 2",
                "TASK: x  TYPE: proofread  INPUT: a.txt",                       # planned, not built
                "TASK: x  CHUNKS: 1 x 2  OPTIONS: notes"):                      # OPTIONS on a text task
        with pytest.raises(MissionError):
            parse(bad)


def test_options_keep_old_task_hashes():
    m = parse("TASK: Tips  SAVE: t.md  CHUNKS: 1 x 2")
    assert "options" not in str(m.spec_hash(m.jobs[0]))          # stable for resumes
    from dataclasses import asdict
    j = asdict(m.jobs[0])
    assert j["options"] == []


def test_transcript_and_subtitle_formats():
    segs = [{"s": 0.0, "e": 2.0, "t": "Hello there."}, {"s": 2.1, "e": 3.0, "t": "Same paragraph."},
            {"s": 65.0, "e": 3700.5, "t": "After a pause."}]
    txt = tools.transcript_text(segs, "Talk")
    assert txt.startswith("# Talk") and "[00:00] Hello there. Same paragraph." in txt
    assert "[01:05] After a pause." in txt
    srt = tools.srt_text(segs)
    assert srt.startswith("1\n00:00:00,000 --> 00:00:02,000\nHello there.")
    assert "3\n00:01:05,000 --> 01:01:40,500\nAfter a pause." in srt


def test_transcribe_end_to_end_with_resume(app):
    rec = app.sb.inbox / "tools" / "transcribe"
    wav(rec / "Team Meeting.wav")
    wav(rec / "second.wav")
    (rec / "notes.txt").write_text("not a recording")                     # ignored in a folder
    text = "TASK: Meeting  TYPE: transcribe\nINPUT: tools/transcribe\nOPTIONS: subtitles, notes"
    chk = app.check(text)
    assert chk["ok"], chk
    assert chk["jobs"][0]["files"] == 2
    assert describe.plain_summary(chk) == ["Transcribe 2 recordings with subtitles and notes: Meeting"]
    m = parse(text)
    eng = Engine(app.settings, app.sb, log=lambda x: None, voice=app.voice)
    st = eng.run_mission(m)[0]
    assert st.status == "done", st.note
    out = app.sb.output / st.output
    names = sorted(p.name for p in out.iterdir())
    assert names == ["second-notes.md", "second.srt", "second.txt",
                     "team-meeting-notes.md", "team-meeting.srt", "team-meeting.txt"]
    body = (out / "team-meeting.txt").read_text(encoding="utf-8")
    assert "[00:00] Welcome to the planning meeting. We will ship the new mugs on Friday." in body
    assert "[00:07] Sam will update the price list." in body                  # new paragraph after the pause
    assert "Sam: update the price list" in (out / "team-meeting-notes.md").read_text(encoding="utf-8")
    assert st.items == 2 and st.words > 10 and any(f["flag"] == "[CHECK]" for f in st.flags)
    # a second run of the same mission starts fresh in a new folder, never mixing with the first
    st2 = Engine(app.settings, app.sb, log=lambda x: None, voice=app.voice).run_mission(m)[0]
    assert st2.status == "done" and st2.output != st.output


def test_transcribe_without_notes_or_subtitles(app):
    wav(app.sb.inbox / "a.wav")
    m = parse("TASK: Plain  TYPE: transcribe\nINPUT: a.wav\nOPTIONS: none")
    st = Engine(app.settings, app.sb, log=lambda x: None, voice=app.voice).run_mission(m)[0]
    assert st.status == "done", st.note
    assert sorted(p.name for p in (app.sb.output / st.output).iterdir()) == ["a.txt"]


def test_transcribe_needs_files_and_explains(app):
    r = app.check("TASK: Missing  TYPE: transcribe\nINPUT: nope.mp3")
    assert not r["ok"] and "Tools tab" in r["error"]


def test_describe_box_routes_to_transcribe(app):
    wav(app.sb.inbox / "tools" / "transcribe" / "call.wav")
    r = describe.draft(app, "please transcribe my call and make notes")
    assert r["ok"], r
    assert "TYPE: transcribe" in r["mission"] and "tools/transcribe/call.wav" in r["mission"]
    assert r["summary"] == ["Transcribe 1 recording with subtitles and notes: Meeting notes"]


def test_upload_target_never_overwrites(app):
    a = tools.upload_target(app.sb, "transcribe", "my:file?.mp3")
    a.write_bytes(b"x")
    b = tools.upload_target(app.sb, "transcribe", "my:file?.mp3")
    assert a.name == "my_file_.mp3" and b.name == "my_file__2.mp3"
    assert a.parent == app.sb.inbox / "tools" / "transcribe"


def test_mission_for_builds_a_runnable_mission(app):
    wav(app.sb.inbox / "tools" / "transcribe" / "x.wav")
    text = tools.mission_for("transcribe", ["tools/transcribe/x.wav"], ["notes"], "Tuesday call",
                             "focus on dates")
    j = parse(text).jobs[0]
    assert j.name == "Tuesday call" and j.options == ["notes"] and j.format == "focus on dates"
    assert app.check(text)["ok"]
