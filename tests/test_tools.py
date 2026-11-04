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
                "TASK: x  TYPE: translate  INPUT: a.txt",                       # planned, not built
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


# --------------------------------------------------------------------------- read aloud
STORY = """# The Kiln

Intro words before anything else, see [the site](https://example.com) **now**.

## Chapter 1

- First line of a list
- Second line [CHECK: name]

| Mug | Price |
|-----|-------|
| Blue | 12 |

```
code_never_read()
```

## Chapter 2

The end. Visit https://example.com today.
"""


def test_speakable_drops_symbols_links_and_code():
    t = tools.speakable(STORY)
    for gone in ("#", "**", "https://", "[CHECK", "code_never_read", "|", "---"):
        assert gone not in t, gone
    assert "The Kiln." in t and "see the site now." in t
    assert "First line of a list." in t and "Blue, 12." in t


def test_speech_pieces_stay_under_the_limit():
    long = ("This is a sentence. " * 600).strip()
    pcs = tools.speech_pieces(long + "\n\nShort ending.", size=1000)
    assert all(len(p) <= 1000 for p in pcs) and pcs[-1].endswith("Short ending.")
    assert " ".join(pcs).count("This is a sentence.") == 600


def test_split_sections_needs_two_headings():
    secs = tools.split_sections(STORY)
    assert [t for t, _ in secs] == ["The Kiln", "Chapter 1", "Chapter 2"]
    assert tools.split_sections("just text\nno headings") == [("", "just text\nno headings")]
    plain = tools.split_sections("Chapter One\nWords.\n\nChapter Two\nMore.\n\nPart of it is fine.")
    assert [t for t, _ in plain] == ["Chapter One", "Chapter Two"]


def test_read_aloud_end_to_end(app):
    (app.sb.inbox / "tools" / "read-aloud").mkdir(parents=True)
    (app.sb.inbox / "tools" / "read-aloud" / "Kiln Story.md").write_text(STORY, encoding="utf-8")
    text = "TASK: Story  TYPE: read-aloud\nINPUT: tools/read-aloud/Kiln Story.md\nOPTIONS: chapters"
    chk = app.check(text)
    assert chk["ok"], chk
    assert describe.plain_summary(chk) == ["Read 1 document aloud as MP3 (one track per chapter): Story"]
    assert any("WAV" in w for w in chk["warnings"])                     # no FFmpeg in tests
    eng = Engine(app.settings, app.sb, log=lambda x: None, voice=app.voice)
    st = eng.run_mission(parse(text))[0]
    assert st.status == "done", st.note
    out = app.sb.output / st.output
    names = sorted(p.name for p in out.iterdir())
    assert names == ["kiln-story-01-the-kiln.wav", "kiln-story-02-chapter-1.wav",
                     "kiln-story-03-chapter-2.wav"], names
    import wave
    with wave.open(str(out / "kiln-story-02-chapter-1.wav")) as w:
        assert w.getframerate() == 24000 and w.getnframes() > 0
    assert not (eng.meta / "tmp" / "read-aloud" / parse(text).jobs[0].job_id / "kiln-story").exists()
    assert st.words > 10 and st.items == 1


def test_read_aloud_one_track_and_resume_after_a_failure(app):
    doc = app.sb.inbox / "talk.txt"
    doc.write_text("Hello there.\n\nVOICEFAIL in the middle.\n", encoding="utf-8")
    text = "TASK: Talk  TYPE: read-aloud\nINPUT: talk.txt"
    eng = Engine(app.settings, app.sb, log=lambda x: None, voice=app.voice)
    st = eng.run_mission(parse(text))[0]
    assert st.status == "failed" and "the voice broke" in st.note
    doc.write_text("Hello there.\n\nAll good now.\n", encoding="utf-8")
    st = Engine(app.settings, app.sb, log=lambda x: None, voice=app.voice).run_mission(parse(text))[0]
    assert st.status == "done", st.note
    assert sorted(p.name for p in (app.sb.output / st.output).iterdir()) == ["talk.wav"]


def test_read_aloud_reuses_finished_pieces(app, monkeypatch):
    doc = app.sb.inbox / "book.txt"
    doc.write_text("\n\n".join(f"Paragraph {i}. " + "words " * 200 for i in range(12)), encoding="utf-8")
    monkeypatch.setattr(tools, "SPEECH_PIECE", 1500)
    monkeypatch.setattr(tools.speech_pieces, "__defaults__", (1500,))
    text = "TASK: Book  TYPE: read-aloud\nINPUT: book.txt"
    job = parse(text).jobs[0]
    eng = Engine(app.settings, app.sb, log=lambda x: None, voice=app.voice)
    calls = []
    real = app.voice.call

    def stop_after_two(req, timeout=0):
        calls.append(req["cmd"])
        r = real(req, timeout=timeout)
        if len(calls) == 2:
            eng.stop.set()
        return r
    monkeypatch.setattr(app.voice, "call", stop_after_two)
    st = eng.run_mission(parse(text))[0]
    assert st.status == "stopped" and "carries on" in st.note
    kept = list((eng.meta / "tmp" / "read-aloud" / job.job_id).rglob("*.wav"))
    assert len(kept) == 2
    calls.clear()
    eng2 = Engine(app.settings, app.sb, log=lambda x: None, voice=app.voice)
    monkeypatch.setattr(app.voice, "call", lambda req, timeout=0: (calls.append(1), real(req, timeout=timeout))[1])
    st = eng2.run_mission(parse(text))[0]
    assert st.status == "done", st.note
    total = len(tools.speech_pieces(tools.speakable(doc.read_text())))
    assert len(calls) == total - 2                       # the two finished pieces weren't redone


# --------------------------------------------------------------------------- proofread
LETTER = "Dear Sam,\n\nI saw teh cat in Paris.\n\nPlease recieve this note.\n\nThanks,\nAlex\n"


def test_apply_changes_only_exact_matches():
    text, applied, noted, missed = tools.apply_changes(
        "One.\n\nTwo teh cat.\n", [{"find": "teh cat", "replace": "the cat", "why": "spelling"},
                                   {"find": "nope", "replace": "x", "why": ""},
                                   {"find": "One.", "replace": "One.", "why": "check"},
                                   {"find": "a" * 500, "replace": "b", "why": ""}])
    assert text == "One.\n\nTwo the cat.\n"
    assert applied[0]["par"] == 2 and noted[0]["par"] == 1
    assert [m["reason"] for m in missed] == ["couldn't find those exact words", "too much to change at once"]


def test_proof_chunks_join_back_exactly():
    text = "\n\n".join(f"Para {i} " + "word " * 150 for i in range(10)) + "\n"
    chunks = tools.proof_chunks(text, words=400)
    assert "".join(chunks) == text and len(chunks) > 2
    assert tools.parse_changes("no json here") is None
    assert tools.parse_changes('ok ```json\n[{"find": "a", "replace": "b"}, {"x": 1}]\n```') == \
        [{"find": "a", "replace": "b", "why": ""}]


def test_proofread_end_to_end(app):
    (app.sb.inbox / "letter.txt").write_text(LETTER, encoding="utf-8")
    text = "TASK: Letter  TYPE: proofread\nINPUT: letter.txt\nFORMAT: British spelling"
    chk = app.check(text)
    assert chk["ok"], chk
    assert describe.plain_summary(chk) == ["Proofread 1 document with a list of every change "
                                           "and a corrected copy: Letter"]
    st = Engine(app.settings, app.sb, log=lambda x: None).run_mission(parse(text))[0]
    assert st.status == "done", st.note
    out = app.sb.output / st.output
    assert sorted(p.name for p in out.iterdir()) == ["letter-changes.md", "letter-proofread.txt"]
    fixed = (out / "letter-proofread.txt").read_text(encoding="utf-8")
    assert fixed == LETTER.replace("teh cat", "the cat").replace("recieve", "receive")
    report = (out / "letter-changes.md").read_text(encoding="utf-8")
    assert "2 changes. Your original file was not changed." in report
    assert "Paragraph 2 (spelling): “teh cat” → “the cat”" in report
    assert "Paragraph 3 (spelling)" in report and "Worth a look" in report and "right city" in report
    assert (app.sb.inbox / "letter.txt").read_text(encoding="utf-8") == LETTER     # original untouched
    assert any("right city" in f["flag"] for f in st.flags)


def test_proofread_clarity_and_no_copy(app):
    (app.sb.inbox / "a.md").write_text("I saw teh cat.\n", encoding="utf-8")
    st = Engine(app.settings, app.sb, log=lambda x: None).run_mission(
        parse("TASK: A  TYPE: proofread\nINPUT: a.md\nOPTIONS: clarity"))[0]
    assert st.status == "done", st.note
    out = app.sb.output / st.output
    assert [p.name for p in out.iterdir()] == ["a-changes.md"]
    assert "couldn't apply" in (out / "a-changes.md").read_text(encoding="utf-8")


def test_proofread_retries_a_garbled_reply(app):
    (app.sb.inbox / "g.txt").write_text("GARBLE but teh cat.\n", encoding="utf-8")
    st = Engine(app.settings, app.sb, log=lambda x: None).run_mission(
        parse("TASK: G  TYPE: proofread\nINPUT: g.txt"))[0]
    assert st.status == "done" and st.retries >= 1, st.note
    assert "the cat" in (app.sb.output / st.output / "g-proofread.txt").read_text(encoding="utf-8")


def test_describe_routes_documents(app):
    (app.sb.inbox / "tools" / "read-aloud").mkdir(parents=True)
    (app.sb.inbox / "tools" / "read-aloud" / "story.md").write_text("Once upon a time.", encoding="utf-8")
    r = describe.draft(app, "read my story aloud please")
    assert r["ok"], r
    assert "TYPE: read-aloud" in r["mission"] and "tools/read-aloud/story.md" in r["mission"]
    r = describe.draft(app, "proofread my story")
    assert r["ok"] and "TYPE: proofread" in r["mission"], r


def test_catalog_lists_needs_and_hints():
    cat = {t["id"]: t for t in tools.catalog()}
    assert cat["read-aloud"]["ready"] and cat["proofread"]["ready"]
    assert "voice" in cat["read-aloud"]["needs"] and cat["proofread"]["extra_hint"]
    assert ".docx" in cat["proofread"]["accepts"]
