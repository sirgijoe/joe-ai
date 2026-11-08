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
