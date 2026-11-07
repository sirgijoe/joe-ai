"""Tools (tools.py): Transcribe end to end with the fake voice helper and fake Ollama."""
from __future__ import annotations

import json
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
    assert all(t["ready"] for t in cat)                         # nothing left "coming soon"
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


# --------------------------------------------------------------------------- photo batch
import shutil as _shutil
import subprocess as _sp

HAVE_FFMPEG = _shutil.which("ffmpeg")


def _jpeg_with_orientation(src: Path, dest: Path, value: int) -> Path:
    tiff = b"MM\x00\x2a" + struct.pack(">I", 8) + struct.pack(">H", 1) + \
        struct.pack(">HHIHH", 0x0112, 3, 1, value, 0) + struct.pack(">I", 0)
    app1 = b"Exif\x00\x00" + tiff
    raw = src.read_bytes()
    dest.write_bytes(raw[:2] + b"\xff\xe1" + struct.pack(">H", len(app1) + 2) + app1 + raw[2:])
    return dest


def test_photo_options_parse_and_round_trip():
    m = parse("TASK: Shop photos  TYPE: photo-batch\nINPUT: tools/photo-batch\n"
              "OPTIONS: size: 800, format=webp, rename\nWATERMARK:   My   Shop ")
    j = m.jobs[0]
    assert j.options == ["size 800", "format webp", "rename"] and j.watermark == "My Shop"
    assert tools.option_value(j, "size") == "800" and tools.option_value(j, "corner") == "bottom-right"
    assert tools.chosen_options(j) == {"rename"}
    again = parse(to_text("", "", mission_to_dict(m)["tasks"])).jobs[0]
    assert again.options == j.options and again.watermark == "My Shop"
    for bad in ("TASK: x  TYPE: photo-batch\nINPUT: a.jpg\nOPTIONS: size 999",
                "TASK: x  TYPE: photo-batch\nINPUT: a.jpg\nOPTIONS: rename yes",
                "TASK: x  TYPE: transcribe\nINPUT: a.wav\nWATERMARK: Mine"):
        with pytest.raises(MissionError):
            parse(bad)
    assert "watermark" not in str(parse("TASK: Tips  CHUNKS: 1 x 2").spec_hash(parse("TASK: Tips  CHUNKS: 1 x 2").jobs[0]))


def test_fit_size_and_spots():
    assert tools.fit_size(4000, 3000, 1600) == (1600, 1200)
    assert tools.fit_size(800, 600, 1600) == (800, 600)                     # never enlarged
    assert tools.fit_size(3000, 4000, None) == (3000, 4000)
    assert tools._spot("top-left", "tw", "th", "9") == ("9", "9")
    assert tools._spot("center", "w", "h", "9") == ("(W-w)/2", "(H-h)/2")
    assert tools._ff_path("C:\\Fonts\\a'b.ttf") == "'C\\:/Fonts/a'\\\\\\''b.ttf'"


def test_photo_summary(app, monkeypatch):
    (app.sb.inbox / "a.png").write_bytes(b"x")
    text = "TASK: Web  TYPE: photo-batch\nINPUT: a.png\nOPTIONS: format jpg\nWATERMARK: Me"
    chk = app.check(text)
    assert not chk["ok"] and "FFmpeg" in chk["error"]                    # no FFmpeg: says so first
    import joeai.doctor as doctor
    monkeypatch.setattr(doctor, "ffmpeg_exe", lambda configured="": "ffmpeg")
    chk = app.check(text)
    assert describe.plain_summary(chk) == ["Resize 1 photo (1600 px, JPG, watermark bottom right): Web"]


@pytest.mark.skipif(not HAVE_FFMPEG, reason="needs FFmpeg")
def test_photo_batch_end_to_end(app, tmp_path, monkeypatch):
    import joeai.doctor as doctor
    monkeypatch.setattr(doctor, "ffmpeg_exe", lambda configured="": HAVE_FFMPEG)
    folder = app.sb.inbox / "tools" / "photo-batch"
    folder.mkdir(parents=True)
    _sp.run([HAVE_FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=s=2000x1500:d=1",
             "-frames:v", "1", str(tmp_path / "base.jpg")], check=True)
    _jpeg_with_orientation(tmp_path / "base.jpg", folder / "Phone Pic.jpg", 6)
    _sp.run([HAVE_FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=red@0.2:s=600x400,format=rgba",
             "-frames:v", "1", str(folder / "see-through.png")], check=True)
    _sp.run([HAVE_FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=200x100,format=rgba",
             "-frames:v", "1", str(folder / "logo.png")], check=True)
    (folder / "notes.txt").write_text("not a photo")
    text = ("TASK: Shop Pics  TYPE: photo-batch\nINPUT: tools/photo-batch\n"
            "OPTIONS: size 800, format jpg, rename, corner top-left\nWATERMARK: tools/photo-batch/logo.png")
    chk = app.check(text)
    assert chk["ok"] and chk["jobs"][0]["files"] == 2, chk                  # the logo isn't a photo
    st = Engine(app.settings, app.sb, log=lambda x: None).run_mission(parse(text))[0]
    assert st.status == "done", st.note
    out = app.sb.output / st.output
    names = sorted(p.name for p in out.iterdir())
    assert names == ["shop-pics-01.jpg", "shop-pics-02.jpg"], names
    sizes = sorted(tools.image_size(HAVE_FFMPEG, out / n) for n in names)
    assert sizes == [(600, 400), (600, 800)]                    # small one untouched; phone photo stood up
    assert tools.jpeg_orientation(out / "shop-pics-02.jpg") == 1             # no hidden details kept
    # text watermark, same format, keep size
    st = Engine(app.settings, app.sb, log=lambda x: None).run_mission(parse(
        "TASK: Marked  TYPE: photo-batch\nINPUT: tools/photo-batch/see-through.png\n"
        "OPTIONS: size keep\nWATERMARK: 100% Mine: 'ok'"))[0]
    assert st.status == "done", st.note
    assert tools.image_size(HAVE_FFMPEG, app.sb.output / st.output / "see-through.png") == (600, 400)


def test_photo_batch_needs_ffmpeg(app):
    (app.sb.inbox / "a.jpg").write_bytes(b"x")
    st = Engine(app.settings, app.sb, log=lambda x: None).run_mission(
        parse("TASK: P  TYPE: photo-batch\nINPUT: a.jpg"))[0]
    assert st.status == "failed" and "FFmpeg" in st.note


# --------------------------------------------------------------------------- translate
MENU = "# Menu\n\nFresh bread daily.\n\nA real idiom here.\n\n- Soup: $5\n"


def test_clean_translation():
    assert tools.clean_translation("<think>hmm</think>Sure, here is the translation:\n```\nHola\n```") == "Hola"
    assert tools.clean_translation("<<<\nBonjour\n>>>") == "Bonjour"
    assert tools.clean_translation("Hola: amigos\nmore") == "Hola: amigos\nmore"      # not a preamble


def test_translate_needs_a_language(app):
    (app.sb.inbox / "m.md").write_text(MENU, encoding="utf-8")
    with pytest.raises(MissionError, match="which language"):
        parse("TASK: T  TYPE: translate\nINPUT: m.md")
    with pytest.raises(MissionError):
        parse("TASK: T  TYPE: translate\nINPUT: m.md\nOPTIONS: to klingon")


def test_translate_end_to_end(app):
    (app.sb.inbox / "Menu.md").write_text(MENU, encoding="utf-8")
    text = "TASK: Menus  TYPE: translate\nINPUT: Menu.md\nOPTIONS: to spanish, to french, to japanese"
    chk = app.check(text)
    assert chk["ok"], chk
    assert describe.plain_summary(chk) == ["Translate 1 document into Spanish, French and Japanese: Menus"]
    st = Engine(app.settings, app.sb, log=lambda x: None).run_mission(parse(text))[0]
    assert st.status == "done" and st.items == 3, st.note
    out = app.sb.output / st.output
    assert sorted(p.name for p in out.iterdir()) == ["menu-french.md", "menu-japanese.md", "menu-spanish.md"]
    es = (out / "menu-spanish.md").read_text(encoding="utf-8")
    assert es.startswith("> Translated into Spanish by Joe")
    assert "[SP] # Menu\n\n[SP] Fresh bread daily." in es and "$5" in es
    assert any("[CHECK]" in f["flag"] for f in st.flags)
    assert (app.sb.inbox / "Menu.md").read_text(encoding="utf-8") == MENU


def test_translate_retries_a_short_reply(app):
    (app.sb.inbox / "s.txt").write_text("SHORTFIRST " + "word " * 40, encoding="utf-8")
    st = Engine(app.settings, app.sb, log=lambda x: None).run_mission(
        parse("TASK: S  TYPE: translate\nINPUT: s.txt\nOPTIONS: to german"))[0]
    assert st.status == "done" and st.retries >= 1, st.note
    assert "[GE] SHORTFIRST" in (app.sb.output / st.output / "s-german.txt").read_text(encoding="utf-8")


def test_describe_routes_translate(app):
    (app.sb.inbox / "menu.md").write_text(MENU, encoding="utf-8")
    r = describe.draft(app, "translate my menu into spanish and french")
    assert r["ok"] and "TYPE: translate" in r["mission"], r
    assert r["summary"] == ["Translate 1 document into Spanish and French: Menu translations"]


# --------------------------------------------------------------------------- tidy a spreadsheet
SHEET = ("Name,Product,Price\r\n"
         "  Ann   Lee ,Blue Bwol,12\r\n"
         "Bo Chan,Tall mug,9\r\n"
         "ann lee,blue bwol,12\r\n"                      # a duplicate apart from capitals/spaces
         "Cy Dee,Big plate,15\r\n"
         ",,\r\n")


def _xlsx(path: Path) -> Path:
    """A tiny Excel file: shared strings, a number, a date cell, an inline string."""
    import zipfile
    files = {
        "[Content_Types].xml": '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        "xl/workbook.xml": '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                           'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                           '<sheets><sheet name="Stock" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                                      '<Relationship Id="rId1" Target="worksheets/stock.xml" Type="x"/></Relationships>',
        "xl/sharedStrings.xml": '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                                '<si><t>Item</t></si><si><t>Made</t></si><si><t>Count</t></si><si><t>Mug</t></si></sst>',
        "xl/styles.xml": '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                         '<cellXfs><xf numFmtId="0"/><xf numFmtId="14"/></cellXfs></styleSheet>',
        "xl/worksheets/stock.xml": '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
                                   '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c><c r="C1" t="s"><v>2</v></c></row>'
                                   '<row r="2"><c r="A2" t="s"><v>3</v></c><c r="B2" s="1"><v>45000</v></c><c r="C2"><v>3.0</v></c></row>'
                                   '<row r="3"><c r="A3" t="inlineStr"><is><t>Bowl</t></is></c><c r="C3"><v>2.5</v></c></row>'
                                   '</sheetData></worksheet>'}
    with zipfile.ZipFile(path, "w") as z:
        for n, d in files.items():
            z.writestr(n, d)
    return path


def test_sheets_read_csv_and_xlsx(tmp_path):
    from joeai import sheets
    p = tmp_path / "a.csv"
    p.write_bytes(SHEET.encode("utf-8"))
    h, rows, cut = sheets.read_table(p)
    assert h == ["Name", "Product", "Price"] and len(rows) == 4 and not cut   # blank row dropped
    (tmp_path / "semi.csv").write_text("a;b\n1;2\n", encoding="cp1252")
    assert sheets.read_table(tmp_path / "semi.csv")[:2] == (["a", "b"], [["1", "2"]])
    h, rows, _ = sheets.read_table(_xlsx(tmp_path / "s.xlsx"))
    assert h == ["Item", "Made", "Count"]
    assert rows == [["Mug", "2023-03-15", "3"], ["Bowl", "", "2.5"]]
    out = tmp_path / "o.csv"
    sheets.write_csv(out, ["A", "B"], [["café", "x,y"]])
    assert out.read_bytes().startswith(b"\xef\xbb\xbf") and b'"x,y"' in out.read_bytes()


def test_tidy_helpers():
    assert tools.tidy_cell("  a    b ") == "a b"
    kept, gone = tools.dedupe_rows([["A b", "1"], ["a  B", "1"], ["c", "1"]])
    assert kept == [0, 2] and gone == [1]
    assert tools.split_request("please split name into First name and Last name.", ["Name", "X"]) == \
        (0, ["First name", "Last name"])
    assert tools.split_request("split Nope into a, b", ["Name"]) is None
    assert tools.given_categories("tone: fun. Categories: mugs, bowls or vases") == ["mugs", "bowls", "vases"]
    h = ["Name", "Email", "Price", "Note"]
    rows = [["Ann Lee", "a@b.com", "12", "nice glaze"], ["Bo", "c@d.com", "9", "small chip"]]
    assert tools.text_columns(h, rows) == [3] or tools.text_columns(h, rows) == [0, 3]


def test_tidy_sheet_quick_options_need_no_model(app):
    (app.sb.inbox / "people.csv").write_bytes(SHEET.encode("utf-8"))
    text = "TASK: People  TYPE: tidy-sheet\nINPUT: people.csv"
    chk = app.check(text)
    assert chk["ok"], chk
    assert describe.plain_summary(chk) == ["Tidy 1 spreadsheet (spaces, duplicates): People"]
    app.settings.ollama.url = "http://127.0.0.1:9"                  # no model needed
    st = Engine(app.settings, app.sb, log=lambda x: None).run_mission(parse(text))[0]
    assert st.status == "done", st.note
    from joeai.sheets import read_table
    h, rows, _ = read_table(app.sb.output / st.output / "people-tidy.csv")
    assert rows == [["Ann Lee", "Blue Bwol", "12"], ["Bo Chan", "Tall mug", "9"], ["Cy Dee", "Big plate", "15"]]
    rep = (app.sb.output / st.output / "people-changes.md").read_text(encoding="utf-8")
    assert "1 duplicate row removed." in rep and "Row 4:" in rep


def test_tidy_sheet_with_the_model(app):
    (app.sb.inbox / "people.csv").write_bytes(SHEET.encode("utf-8"))
    text = ("TASK: People  TYPE: tidy-sheet\nINPUT: people.csv\n"
            "OPTIONS: spaces, dupes, spelling, categorize, split\nFORMAT: split Name into First name, Last name")
    st = Engine(app.settings, app.sb, log=lambda x: None).run_mission(parse(text))[0]
    assert st.status == "done", st.note
    from joeai.sheets import read_table
    h, rows, _ = read_table(app.sb.output / st.output / "people-tidy.csv")
    assert h == ["Name", "First name", "Last name", "Product", "Price", "Category"]
    assert rows[0] == ["Ann Lee", "Ann", "Lee", "Blue Bowl", "12", "Bowls"]
    assert rows[1][-1] == "Mugs"                        # "mugs" matched to the list's "Mugs"
    assert rows[2][-1] == ""                            # the model skipped it: flagged, not guessed
    rep = (app.sb.output / st.output / "people-changes.md").read_text(encoding="utf-8")
    assert "Row 2, Product: “Bwol” → “Bowl”" in rep
    assert "Row 5: no category given" in rep and "Mugs: 1 row" in rep
    assert (app.sb.inbox / "people.csv").read_bytes() == SHEET.encode("utf-8")


def test_tidy_sheet_given_categories_and_xlsx(app, tmp_path):
    _xlsx(app.sb.inbox / "stock.xlsx")
    st = Engine(app.settings, app.sb, log=lambda x: None).run_mission(parse(
        "TASK: Stock  TYPE: tidy-sheet\nINPUT: stock.xlsx\nOPTIONS: categorize\n"
        "FORMAT: categories: Mugs, Bowls, Plates"))[0]
    assert st.status == "done", st.note
    from joeai.sheets import read_table
    h, rows, _ = read_table(app.sb.output / st.output / "stock-tidy.csv")
    assert h[-1] == "Category" and rows[0][-1] == "Mugs" and rows[0][1] == "2023-03-15"


def test_missions_dropped_in_the_queue_folder_are_queued(app, monkeypatch):
    import os
    import time
    q = app.sb.missions / "Queue"
    q.mkdir(parents=True, exist_ok=True)
    good, bad = q / "night.txt", q / "broken.txt"
    good.write_text("TASK: Tips  CHUNKS: 1 x 2", encoding="utf-8")
    bad.write_text("TASK: x  CHUNKS: banana", encoding="utf-8")
    old = time.time() - 60
    for f in (good, bad):
        os.utime(f, (old, old))
    got = []
    monkeypatch.setattr(app, "enqueue", lambda text, only=None: got.append(text) or
                        ({"ok": True, "queued": 0} if "Tips" in text else {"ok": False, "error": "CHUNKS must look like '8 x 10'"}))
    assert sorted(app.watch_queue_folder()) == ["broken.txt", "night.txt"]
    assert not good.exists() and not bad.exists() and len(got) == 2
    assert len(list((q / "done").glob("night_*.txt"))) == 1
    note = next((q / "problems").glob("*.problem.txt")).read_text(encoding="utf-8")
    assert "CHUNKS must look like" in note
    fresh = q / "new.txt"
    fresh.write_text("TASK: Later  CHUNKS: 1 x 1", encoding="utf-8")
    assert app.watch_queue_folder() == [] and fresh.exists()                 # still being written


# --------------------------------------------------------------------------- vision tools
@pytest.fixture
def seeing(app, monkeypatch):
    monkeypatch.setattr(tools, "find_vision_model", lambda engine: "qwen2.5vl:7b")
    return app


def _pics(folder: Path, *names: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for n in names:
        (folder / n).write_bytes(b"\x89PNG fake picture " + n.encode())
    return folder


def test_photo_listing(seeing):
    app = seeing
    _pics(app.sb.inbox / "tools" / "photo-listing", "mug1.png", "mug2.jpg", "blurry.png")
    text = "TASK: Shop  TYPE: photo-listing\nINPUT: tools/photo-listing\nFORMAT: handmade stoneware"
    chk = app.check(text)
    assert chk["ok"] and describe.plain_summary(chk) == ["Listings from 3 photos: Shop"], chk
    eng = Engine(app.settings, app.sb, log=lambda x: None)
    st = eng.run_mission(parse(text))[0]
    assert st.status == "partial" and "blurry.png" in st.note
    out = app.sb.output / st.output
    from joeai.sheets import read_table
    h, rows, _ = read_table(out / "listings.csv")
    assert h == tools.LISTING_COLS and [r[0] for r in rows] == ["mug1.png", "mug2.jpg"]
    assert rows[0][3] == "mug, blue, handmade"
    assert "Size [CHECK]" in (out / "listings.md").read_text(encoding="utf-8")
    assert any("[CHECK]" in f["flag"] for f in st.flags)


def test_read_scans_three_ways(seeing):
    app = seeing
    _pics(app.sb.inbox, "sign.png", "r1.jpg", "stock.png")
    eng = lambda: Engine(app.settings, app.sb, log=lambda x: None)
    st = eng().run_mission(parse("TASK: Sign  TYPE: read-scans\nINPUT: sign.png"))[0]
    out = app.sb.output / st.output
    assert st.status == "done" and (out / "sign.md").read_text(encoding="utf-8").startswith("# sign\n\n# Notice")
    assert (out / "all-text.md").exists()
    st = eng().run_mission(parse("TASK: Receipts  TYPE: read-scans\nINPUT: r1.jpg\nOPTIONS: as receipts"))[0]
    from joeai.sheets import read_table
    out = app.sb.output / st.output
    assert read_table(out / "receipts.csv")[1] == [["r1.jpg", "2026-03-02", "Corner Shop", "$12.50", "$0.75", "$", "2"]]
    assert read_table(out / "receipt-items.csv")[1][1] == ["r1.jpg", "Br[CHECK]ad", "$9.50"]
    assert any("[CHECK]" in f["flag"] for f in st.flags)
    st = eng().run_mission(parse("TASK: Table  TYPE: read-scans\nINPUT: stock.png\nOPTIONS: as table"))[0]
    h, rows, _ = read_table(app.sb.output / st.output / "stock.csv")
    assert h == ["Name", "Qty", "Column 3"] and rows == [["Mugs", "4", ""], ["Bowls", "2", "extra"]]


def test_sort_photos(seeing):
    app = seeing
    _pics(app.sb.inbox / "trip", "dog1.png", "Dog2.png", "beach.jpg", "lunch.png")
    text = "TASK: Trip  TYPE: sort-photos\nINPUT: trip"
    chk = app.check(text)
    assert describe.plain_summary(chk) == ["Sort and tag 4 photos into folders: Trip"]
    st = Engine(app.settings, app.sb, log=lambda x: None).run_mission(parse(text))[0]
    assert st.status == "done", st.note
    out = app.sb.output / st.output
    assert sorted(p.name for p in out.iterdir() if p.is_dir()) == ["Beach days", "Food", "dogs"]
    assert sorted(p.name for p in (out / "dogs").iterdir()) == ["Dog2.png", "dog1.png"]
    assert (app.sb.inbox / "trip" / "dog1.png").exists()                       # copied, not moved
    st = Engine(app.settings, app.sb, log=lambda x: None).run_mission(parse(
        "TASK: Given  TYPE: sort-photos\nINPUT: trip\nOPTIONS: none\nFORMAT: categories: Dogs, Beach days"))[0]
    out = app.sb.output / st.output
    from joeai.sheets import read_table
    cats = {r[0]: r[1] for r in read_table(out / "photo-list.csv")[1]}
    assert cats["dog1.png"] == "Dogs" and cats["lunch.png"] == "Snacks"
    assert any("isn't on your list" in f["flag"] for f in st.flags)
    assert not [p for p in out.iterdir() if p.is_dir()]


def test_vision_tools_explain_a_missing_model(app, monkeypatch):
    monkeypatch.setattr(tools, "find_vision_model", lambda engine: None)
    _pics(app.sb.inbox, "a.png")
    st = Engine(app.settings, app.sb, log=lambda x: None).run_mission(
        parse("TASK: L  TYPE: photo-listing\nINPUT: a.png"))[0]
    assert st.status == "failed" and "vision model" in st.note


# --------------------------------------------------------------------------- ask my files
def _contracts(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    filler = "\n\n".join(f"Section {i}. The kiln schedule and glaze orders are handled weekly by the "
                           "studio team, who also clean the shelves and check the clay stock." for i in range(160))
    (folder / "terms.md").write_text(f"# Terms\n\n{filler}\n\nRefunds are given within 30 days of purchase.\n",
                                     encoding="utf-8")
    (folder / "studio.txt").write_text("Opening hours are 9 to 5.\n\nThe studio closes on holidays.\n",
                                       encoding="utf-8")
    return folder


def test_questions_and_search_helpers():
    assert tools.questions_from("What about refunds? When is it due?\n- Who signs") == \
        ["What about refunds?", "When is it due?", "Who signs"]
    chunks = tools.ask_chunks("a.md", "one two\n\nthree four\n\n" + "word " * 600, words=50)
    assert chunks[0]["text"] == "one two\n\nthree four" and all(len(c["text"].split()) <= 50 for c in chunks)
    cs = [{"text": "glaze orders weekly"}, {"text": "refunds within 30 days"}, {"text": "kiln schedule"}]
    assert tools.best_chunks("how do refunds work", cs, None, None, top=2) == [1]


def test_ask_files_words_only(app, monkeypatch):
    monkeypatch.setattr(tools, "find_embed_model", lambda engine: None)
    _contracts(app.sb.inbox / "docs")
    text = "TASK: Refunds  TYPE: ask-files\nINPUT: docs\nFORMAT: What is the refund policy?\nOPTIONS: summaries"
    chk = app.check(text)
    assert chk["ok"] and describe.plain_summary(chk) == ["Read 2 documents for 1 question and summaries: Refunds"]
    st = Engine(app.settings, app.sb, log=lambda x: None).run_mission(parse(text))[0]
    assert st.status == "done" and st.items == 3, st.note
    out = app.sb.output / st.output
    ans = (out / "answers.md").read_text(encoding="utf-8")
    assert "searched by words only" in ans and "## What is the refund policy?" in ans
    assert "Refunds are given within 30 days of purchase." in ans and "docs/terms.md, part" in ans
    summ = (out / "summaries.md").read_text(encoding="utf-8")
    assert "## docs/studio.txt" in summ and "## docs/terms.md" in summ


def test_ask_files_with_a_search_model(app, monkeypatch):
    monkeypatch.setattr(tools, "find_embed_model", lambda engine: "nomic-embed-text")
    _contracts(app.sb.inbox / "docs")
    text = "TASK: Ask  TYPE: ask-files\nINPUT: docs\nFORMAT: How do refunds work?\nWhen does the studio open?"
    eng = Engine(app.settings, app.sb, log=lambda x: None)
    st = eng.run_mission(parse(text))[0]
    assert st.status == "done" and st.items == 2, st.note
    ans = (app.sb.output / st.output / "answers.md").read_text(encoding="utf-8")
    assert "meaning and words (nomic-embed-text)" in ans and "within 30 days" in ans
    assert "don't seem to say" in ans                                       # the hours question
    cache = list((eng.meta / "search").glob("*.jsonl"))
    assert cache and cache[0].read_text(encoding="utf-8").count("\n") > 5   # cached for next time


def test_ask_files_no_question_means_summaries(app, monkeypatch):
    _contracts(app.sb.inbox / "docs")
    chk = app.check("TASK: Sum  TYPE: ask-files\nINPUT: docs")
    assert describe.plain_summary(chk) == ["Read 2 documents for summaries: Sum"]
    st = Engine(app.settings, app.sb, log=lambda x: None).run_mission(parse("TASK: Sum  TYPE: ask-files\nINPUT: docs"))[0]
    assert st.status == "done" and [p.name for p in (app.sb.output / st.output).iterdir()] == ["summaries.md"]


def test_tools_can_use_files_in_output(app):
    """A tool can work on something Joe made earlier (INPUT: Output/...)."""
    made = app.sb.output / "earlier"
    made.mkdir(parents=True)
    (made / "draft.txt").write_text("I saw teh cat.\n", encoding="utf-8")
    st = Engine(app.settings, app.sb, log=lambda x: None).run_mission(
        parse("TASK: Again  TYPE: proofread\nINPUT: Output/earlier/draft.txt"))[0]
    assert st.status == "done", st.note
    assert st.titles == ["Output/earlier/draft.txt"]


def test_hearing_model_picks_the_all_languages_twin():
    assert tools.hearing_model("base.en", "english") == "base.en"
    assert tools.hearing_model("small.en", "spanish") == "small"
    assert tools.hearing_model("tiny.en", "auto") == "tiny"
    assert tools.hearing_model("", "japanese") == "base"
    assert tools.whisper_language("japanese") == "ja" and tools.whisper_language("auto") == ""
    assert tools.code_language("es") == "Spanish" and tools.code_language("xx") == ""
    assert set(tools.WHISPER_CODES) == {v for v, _ in tools.LANGUAGES}


def test_transcribe_in_another_language(app):
    wav(app.sb.inbox / "llamada.wav")
    text = "TASK: Llamada  TYPE: transcribe\nINPUT: llamada.wav\nOPTIONS: notes, language spanish"
    chk = app.check(text)
    assert chk["ok"], chk
    assert describe.plain_summary(chk) == ["Transcribe 1 recording (Spanish) with notes: Llamada"]
    logs = []
    st = Engine(app.settings, app.sb, log=logs.append, voice=app.voice).run_mission(parse(text))[0]
    assert st.status == "done", st.note
    body = (app.sb.output / st.output / "llamada.txt").read_text(encoding="utf-8")
    assert "Language: Spanish" in body and "horno" in body
    assert any("hearing: base, Spanish" in x for x in logs)
    assert any("Hugging Face" in x for x in logs)


def test_transcribe_finds_the_language_and_english_notes(app):
    wav(app.sb.inbox / "x.wav")
    text = "TASK: X  TYPE: transcribe\nINPUT: x.wav\nOPTIONS: language auto, notes-in english, notes"
    assert app.check(text)["ok"]
    logs = []
    st = Engine(app.settings, app.sb, log=logs.append, voice=app.voice).run_mission(parse(text))[0]
    assert st.status == "done", st.note
    assert any("sounds like Spanish" in x for x in logs)
    assert "Language: Spanish" in (app.sb.output / st.output / "x.txt").read_text(encoding="utf-8")


def test_transcribe_rejects_an_unknown_language(app):
    wav(app.sb.inbox / "y.wav")
    assert not app.check("TASK: Y  TYPE: transcribe\nINPUT: y.wav\nOPTIONS: language klingon")["ok"]
