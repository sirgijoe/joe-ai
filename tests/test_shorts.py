"""Make shorts (shorts.py) and social post files (social.py)."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from joeai import shorts, social, tools
from joeai.config import Settings
from joeai.engine import Engine
from joeai.mission import parse
from joeai.ollama import ChatResult

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

WORDS = []
t = 0.0
for sent in ["Here is the secret nobody tells you.", "You have to start before you feel ready.",
             "That is the whole trick.", "Now let me tell you about my dog.", "He eats socks.",
             "Every single day he finds one.", "Okay back to work everybody.", "Thanks for watching."]:
    for w in sent.split():
        WORDS.append({"s": round(t, 2), "e": round(t + 0.45, 2), "t": w})
        t += 0.5
    t += 0.7


def test_windows_and_snap_and_choose():
    segs = [{"s": 0, "e": 3, "t": "one two three"}, {"s": 3, "e": 6, "t": "four five"}]
    assert shorts.windows(segs, words_per=100) == ["[0.0-3.0] one two three\n[3.0-6.0] four five"]
    assert shorts.snap(0.2, 4.0, WORDS, 3, 30) == (0.0, 3.7)               # ends on "you."
    a, b = shorts.snap(0.2, 5.0, WORDS, 3, 30)
    assert a == 0.0 and WORDS[14]["e"] + 0.25 == pytest.approx(b)          # ran on to "ready."
    picks = [{"start": "0:00", "end": "0:06", "score": 9, "title": "The secret"},
             {"start": 1, "end": 5, "score": 8, "title": "overlap"},             # overlaps the first: dropped
             {"start": 11.5, "end": 16, "score": 7, "title": "Dog"},
             {"start": 30, "end": 20, "score": 10}]                              # backwards: dropped
    out = shorts.choose(picks, WORDS, 5, 3, 30)
    assert [p["title"] for p in out] == ["The secret", "Dog"]


def test_captions_and_crop():
    ass = shorts.captions(WORDS, 0, 6, "The {secret}")
    assert "Style: Cap,Atkinson Hyperlegible" in ass and "Title,,0,0,0,,The secret" in ass
    assert "HERE IS THE" in ass and "{" not in ass.split("[Events]")[1].replace("{secret}", "")
    assert shorts.crop_filter(1920, 1080, 0.5) == "crop=606:1080:656:0,scale=1080:1920"
    assert shorts.crop_filter(1920, 1080, 0.0).startswith("crop=606:1080:0:0")
    assert shorts.crop_filter(1920, 1080, 1.0).startswith("crop=606:1080:1314:0")
    assert shorts.crop_filter(1080, 1920) == "scale=1080:-2,crop=1080:1920"
    assert "gblur" in shorts.crop_filter(1920, 1080, mode="fit")
    assert shorts.face_center([(0.1, 0.1, 0.1, 0.1), (0.6, 0.2, 0.2, 0.3)]) == pytest.approx(0.7)


def test_social_files(tmp_path):
    md = tmp_path / "posts.md"
    md.write_text("## Post 1\n**Big news!** Our mugs are back. #pottery\n\n## Post 2\n" + "word " * 70 + "\n",
                  encoding="utf-8")
    made = social.export(md, log=lambda m: None)
    assert [p.name for p in made] == ["posts-social.csv", "posts-social.json", "posts-postiz.txt"]
    csv_text = made[0].read_text(encoding="utf-8-sig")
    assert "Big news! Our mugs are back. #pottery" in csv_text and "X, Bluesky" in csv_text
    data = json.loads(made[1].read_text(encoding="utf-8"))
    assert len(data["posts"]) == 2 and "**" not in data["posts"][0]["text"]
    assert 'postiz posts:create -c "Big news!' in made[2].read_text(encoding="utf-8")
    c = tmp_path / "p.csv"
    c.write_text("Name,Caption\nMug,Fresh mugs today\n", encoding="utf-8")
    assert social.posts_from_csv(c.read_text())[0]["text"] == "Fresh mugs today"


def test_export_social_in_missions():
    m = parse("TASK: Posts\nEXPORT: social\nCHUNKS: 1 x 5\nSAVE: posts.csv\nHEADER: Name,Post\n")
    assert m.jobs[0].export == ["social"]
    from joeai.mission import MissionError
    with pytest.raises(MissionError):
        parse("TASK: Posts\nEXPORT: pdf\nCHUNKS: 1 x 5\nSAVE: posts.csv\nHEADER: Name,Post\n")
    from joeai.describe import want_social
    block = "TASK: Shop posts\nFORMAT: instagram posts\nCHUNKS: 1 x 5\nSAVE: p.md\nEND"
    assert "EXPORT: social" in want_social("10 instagram posts for my shop", block)
    assert want_social("10 blog ideas", block) == block


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs FFmpeg")
def test_make_shorts_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "settings.json"))
    from joeai.sandbox import Sandbox
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    s.engine.retry_backoff_s = 0
    s.engine.gpu_temp_pause_c = 0
    s.engine.keep_awake = False
    s.comfy.ffmpeg = shutil.which("ffmpeg")
    sb = Sandbox(Path(s.workspace))
    vid = sb.inbox / "talk.mp4"
    vid.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=24:duration=30",
                    "-f", "lavfi", "-i", "sine=frequency=300:duration=30", "-shortest",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(vid)],
                   capture_output=True, check=True)
    monkeypatch.setattr(tools, "hearing_ready", lambda settings, voice_ok=None: True)
    monkeypatch.setattr(tools, "hear", lambda engine, wav, model, lang, words=False, timeout=0: {
        "ok": True, "words": WORDS, "segments": [{"s": w["s"], "e": w["e"], "t": w["t"]} for w in WORDS]})
    monkeypatch.setattr(tools, "needs_problem", lambda settings, job: "")
    reply = json.dumps([{"start": 0, "end": 6, "score": 9, "title": "The secret", "post": "Start now. #tips",
                         "why": "strong hook"},
                        {"start": 11.5, "end": 26, "score": 7, "title": "My dog", "post": "Sock thief. #dogs",
                         "why": "funny"}])
    monkeypatch.setattr(Engine, "_text_ready", lambda self, st: True)
    monkeypatch.setattr(Engine, "_chat", lambda self, job, part, kind, system, user, st, images=None, model="":
                        ChatResult(reply, 1, 1, 0.1))
    m = parse("TASK: Shorts  TYPE: make-shorts\nINPUT: talk.mp4\nOPTIONS: count 3, length 30, crop center, "
              "captions, title, posts")
    st = Engine(s, sb, log=lambda x: None).run_mission(m)[0]
    assert st.status == "done", st.note
    out = sb.output / st.output
    names = sorted(p.name for p in out.iterdir())
    assert names == ["shorts-postiz.txt", "shorts-social.csv", "shorts-social.json", "shorts.md",
                     "talk-short-01.mp4", "talk-short-02.mp4"]
    from joeai.media import size_of
    assert size_of(shutil.which("ffmpeg"), out / "talk-short-01.mp4") == (1080, 1920)
    assert "Why: strong hook" in (out / "shorts.md").read_text(encoding="utf-8")
    assert "talk-short-02.mp4" in (out / "shorts-social.csv").read_text(encoding="utf-8-sig")
