"""2.1 sound/picture tools: clean a recording, social graphics, privacy blur, cut ums."""
from __future__ import annotations

import shutil
import subprocess

import pytest

from joeai import avtools, describe, tools
from joeai.engine import Engine
from joeai.mission import parse

from test_tools import app  # noqa: F401

FF = shutil.which("ffmpeg")
need_ff = pytest.mark.skipif(not FF, reason="needs FFmpeg")


@pytest.fixture
def ffapp(app, monkeypatch):  # noqa: F811
    import joeai.doctor as doctor
    monkeypatch.setattr(doctor, "ffmpeg_exe", lambda configured="": FF)
    return app


def _run(app, text):
    return Engine(app.settings, app.sb, log=lambda x: None).run_mission(parse(text))[0]


def _tone(path, seconds=3):
    subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=f=440:d={seconds}", "-f", "lavfi", "-i",
                    f"anoisesrc=d={seconds}:a=0.05", "-filter_complex", "amix=2", str(path)], check=True)


def test_filters_and_plans():
    f = avtools.clean_filter("strong", hum=True, level=True)
    assert "afftdn=nf=-35" in f and "bandreject=f=60" in f and "bandreject=f=150" in f and f.endswith("LRA=11")
    assert "loudnorm" not in avtools.clean_filter(level=False)
    words = [{"t": "So", "s": 0.0, "e": 0.3}, {"t": "um,", "s": 0.4, "e": 0.8}, {"t": "today", "s": 0.9, "e": 1.2},
             {"t": "we", "s": 4.2, "e": 4.4}, {"t": "Uh", "s": 4.5, "e": 4.7}]
    cuts = avtools.cut_plan(words, fillers=True, pause=1.0)
    assert [c[2] for c in cuts] == ['"um"', "pause 3.0 s", '"uh"']
    assert cuts[1][0] == pytest.approx(1.375) and cuts[1][1] == pytest.approx(4.025)
    assert avtools.keep_spans(cuts, 6.0)[0] == (0.0, 0.4)
    assert avtools.cut_plan(words, fillers=False, pause=0) == []
    head, rest, big, small = avtools.layout("Grand opening Saturday!\n10% off everything", 1080, 1080)
    assert " ".join(head) == "Grand opening Saturday!" and rest and big > small
    assert avtools.parse_boxes('{"boxes": [{"kind": "faces", "x": 0.1, "y": 0.2, "w": 0.2, "h": 0.2}, '
                               '{"kind": "faces", "x": 120, "y": 5, "w": 9, "h": 9}]}', {"faces"}) == \
        [{"kind": "faces", "x": 0.1, "y": 0.2, "w": 0.2, "h": 0.2}]


@need_ff
def test_clean_audio_end_to_end(ffapp):
    _tone(ffapp.sb.inbox / "talk.wav")
    st = _run(ffapp, "TASK: Clean  TYPE: clean-audio\nINPUT: talk.wav\nOPTIONS: strength normal, hum, level")
    assert st.status == "done", st.note
    out = ffapp.sb.output / st.output / "talk-clean.wav"
    assert out.exists() and out.stat().st_size > 1000
    assert (ffapp.sb.inbox / "talk.wav").exists()


@need_ff
def test_social_graphic_sizes_and_exact_words(ffapp):
    st = _run(ffapp, "TASK: Post  TYPE: social-graphic\nFORMAT: Grand opening Saturday!\nOPTIONS: size ig-post, size story")
    assert st.status == "done", st.note
    out = ffapp.sb.output / st.output
    assert sorted(p.name for p in out.iterdir()) == ["graphic-ig-post.png", "graphic-story.png"]
    assert avtools.picture_size(FF, out / "graphic-story.png") == (1080, 1920)
    subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=800x600", "-frames:v", "1",
                    str(ffapp.sb.inbox / "shop.jpg")], check=True)
    st = _run(ffapp, "TASK: Post2  TYPE: social-graphic\nINPUT: shop.jpg\nFORMAT: O'Brien's sale: 50% off\nOPTIONS: size fb-post")
    assert st.status == "done", st.note
    assert avtools.picture_size(FF, ffapp.sb.output / st.output / "shop-fb-post.jpg") == (1200, 630)
    st = _run(ffapp, "TASK: Post3  TYPE: social-graphic")
    assert st.status == "failed" and "words" in st.note


@need_ff
def test_privacy_blur_blurs_found_spots(ffapp, monkeypatch):
    subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x480", "-frames:v", "1",
                    str(ffapp.sb.inbox / "party.jpg")], check=True)
    monkeypatch.setattr(tools, "find_vision_model", lambda engine: "llava:7b")
    monkeypatch.setattr(tools, "_look", lambda *a, **k: {"boxes": [{"kind": "faces", "x": 0.1, "y": 0.1, "w": 0.3, "h": 0.3}]})
    st = _run(ffapp, "TASK: Blur  TYPE: privacy-blur\nINPUT: party.jpg\nOPTIONS: blur faces")
    assert st.status == "done", st.note
    out = ffapp.sb.output / st.output / "party-blurred.jpg"
    assert out.exists() and avtools.picture_size(FF, out) == (640, 480)
    assert any("1 faces" in f["flag"] and "[CHECK]" in f["flag"] for f in st.flags)
    monkeypatch.setattr(tools, "_look", lambda *a, **k: None)
    st = _run(ffapp, "TASK: Blur2  TYPE: privacy-blur\nINPUT: party.jpg")
    assert st.status == "failed" and "nothing was blurred" in st.note


@need_ff
def test_tidy_speech_cuts_and_lists(ffapp, monkeypatch):
    _tone(ffapp.sb.inbox / "pod.mp3", 6)
    words = [{"t": "Hi", "s": 0.0, "e": 0.4}, {"t": "um", "s": 0.5, "e": 0.9}, {"t": "folks", "s": 1.0, "e": 1.4},
             {"t": "today", "s": 4.0, "e": 4.5}]
    monkeypatch.setattr(tools, "hear", lambda engine, wav, model, lang, words=False, timeout=0: {"ok": True, "words": words_})
    words_ = words
    monkeypatch.setattr(tools, "hearing_ready", lambda settings, voice_ok=None: True)
    st = _run(ffapp, "TASK: Tidy  TYPE: tidy-speech\nINPUT: pod.mp3\nOPTIONS: fillers, pauses, pause 1.0")
    assert st.status == "done", st.note
    out = ffapp.sb.output / st.output
    assert (out / "pod-tidy.mp3").exists()
    cuts = (out / "pod-cuts.md").read_text(encoding="utf-8")
    assert '"um"' in cuts and "pause 2.6 s" in cuts
    assert avtools.media_seconds(FF, out / "pod-tidy.mp3") < avtools.media_seconds(FF, ffapp.sb.inbox / "pod.mp3") - 2


def test_new_tools_planned_and_summarized(app):  # noqa: F811
    for tid in avtools.AV_TOOLS:
        assert tools.TOOLS[tid].ready and f"TYPE: {tid}" in tools.planner_lines()
    (app.sb.inbox / "a.wav").write_bytes(b"RIFF")
    chk = app.check("TASK: C  TYPE: clean-audio\nINPUT: a.wav")
    assert chk["ok"], chk
    assert describe.plain_summary(chk)


def test_dub_helpers():
    assert avtools.srt_time(3725.5) == "01:02:05,500"
    srt = avtools.make_srt([{"s": 0, "e": 1.5, "t": "Hola"}])
    assert srt.startswith("1\n00:00:00,000 --> 00:00:01,500\nHola\n")
    assert avtools.parse_numbered("1| Hola\n[2] Adiós\n3) tres\nnoise", 2) == {1: "Hola", 2: "Adiós"}


@need_ff
def test_dub_video_subtitles_and_voice(ffapp, monkeypatch):
    subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x240:d=8", "-f", "lavfi", "-i",
                    "sine=f=300:d=8", "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
                    str(ffapp.sb.inbox / "talk.mp4")], check=True)
    monkeypatch.setattr(tools, "hearing_ready", lambda settings, voice_ok=None: True)
    monkeypatch.setattr("joeai.addons.voice_python", lambda: __import__("sys").executable)
    st = Engine(ffapp.settings, ffapp.sb, log=lambda x: None, voice=ffapp.voice).run_mission(
        parse("TASK: Dub  TYPE: dub-video\nINPUT: talk.mp4\nOPTIONS: to spanish, voice, voice-of woman"))[0]
    assert st.status == "done", st.note
    out = ffapp.sb.output / st.output
    srt = (out / "talk-spanish.srt").read_text(encoding="utf-8")
    assert "[ES] Welcome to the planning meeting." in srt and "We will ship the new mugs on Friday. [CHECK]" in srt
    assert (out / "talk-spanish.mp4").exists() and avtools.media_seconds(FF, out / "talk-spanish.mp4") > 7
    probe = subprocess.run([FF, "-hide_banner", "-i", str(out / "talk-spanish.mp4")], capture_output=True, text=True).stderr
    assert "Subtitle: mov_text" in probe
    assert any("machine-translated Spanish voice-over" in f["flag"] for f in st.flags)
    st = Engine(ffapp.settings, ffapp.sb, log=lambda x: None, voice=ffapp.voice).run_mission(
        parse("TASK: Dub2  TYPE: dub-video\nINPUT: talk.mp4\nOPTIONS: to german, voice"))[0]
    assert st.status == "done" and sorted(p.name for p in (ffapp.sb.output / st.output).iterdir()) == ["talk-german.srt"]


@need_ff
def test_memory_voice_sample_and_reading(ffapp, monkeypatch):
    import wave
    from joeai import addons
    _tone(ffapp.sb.inbox / "voicemail.mp3", 12)
    out = ffapp.sb.inbox / "sample.wav"
    assert avtools.prepare_voice_sample(FF, ffapp.sb.inbox / "voicemail.mp3", out) == ""
    with wave.open(str(out)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (24000, 1, 2)
    data = out.read_bytes()
    assert "promises" in addons.save_memory_voice("Grandpa", data, {"family", "private"})
    assert addons.save_memory_voice("Grandpa", data, {"family", "private", "honest"}) == ""
    assert [v["name"] for v in addons.memory_voices()] == ["Grandpa"] and addons.memory_ref("grandpa")

    class FakeClone:
        def __init__(self, *a, **k):
            pass

        def call(self, req, timeout=0):
            assert req["ref"].endswith("reference.wav")
            with wave.open(req["out"], "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(24000)
                w.writeframes(b"\x00\x00" * 24000)
            return {"ok": True}
    monkeypatch.setattr(addons, "VoiceWorker", FakeClone)
    monkeypatch.setattr(addons, "clone_ready", lambda: True)
    (ffapp.sb.inbox / "letter.md").write_text("Dear kids, I'm proud of you.", encoding="utf-8")
    st = _run(ffapp, "TASK: Letter  TYPE: memory-voice\nINPUT: letter.md\nFORMAT: Grandpa")
    assert st.status == "done", st.note
    got = sorted(p.name for p in (ffapp.sb.output / st.output).iterdir())
    assert got == ["About this recording.txt", "letter-grandpa-voice.mp3"]
    assert "made by AI" in (ffapp.sb.output / st.output / "About this recording.txt").read_text(encoding="utf-8")
    st = _run(ffapp, "TASK: L2  TYPE: memory-voice\nINPUT: letter.md\nFORMAT: Nobody")
    assert st.status == "failed" and "made so far: Grandpa" in st.note
    addons.delete_memory_voice("grandpa")
    assert addons.memory_voices() == []
