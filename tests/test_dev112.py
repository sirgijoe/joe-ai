"""dev112: black-and-white videos are made in color by Wan, then turned black and white by
FFmpeg (asking Wan for monochrome gave bad hands); /api/ping says how Joe was installed."""
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from joeai import media, styles
from joeai.engine import Engine

FF = shutil.which("ffmpeg")


@pytest.mark.skipif(not FF, reason="needs FFmpeg")
def test_video_bw_has_no_color(tmp_path):
    src, out = tmp_path / "c.mp4", tmp_path / "bw.mp4"
    subprocess.run([FF, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=12",
                    "-t", "1", "-pix_fmt", "yuv420p", str(src)], check=True)
    assert media.video_bw(FF, src, out)
    # chroma planes of a colorless yuv420p frame sit at 128 (+/- encoder noise)
    raw = subprocess.run([FF, "-v", "error", "-i", str(out), "-frames:v", "1", "-f", "rawvideo",
                          "-pix_fmt", "yuv420p", "-"], capture_output=True, check=True).stdout
    chroma = raw[320 * 240:]
    assert max(abs(b - 128) for b in chroma) <= 3


@pytest.mark.skipif(not FF, reason="needs FFmpeg")
def test_bw_videos_keeps_color_copy(tmp_path):
    subprocess.run([FF, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=8",
                    "-t", "1", "-pix_fmt", "yuv420p", str(tmp_path / "001_walk.mp4")], check=True)
    (tmp_path / "001_walk.webp").write_bytes(b"x")
    eng = SimpleNamespace(log=lambda *a: None)
    out = Engine._bw_videos(eng, tmp_path, ["001_walk.webp", "001_walk.mp4"], FF)
    assert out == ["001_walk.webp", "001_walk.mp4", "001_walk_color.mp4"]
    assert (tmp_path / "001_walk_color.mp4").exists()


def test_bw_videos_without_ffmpeg_stays_color(tmp_path):
    logs = []
    eng = SimpleNamespace(log=logs.append)
    assert Engine._bw_videos(eng, tmp_path, ["a.mp4"], None) == ["a.mp4"]
    assert "stays in color" in logs[0]


def test_black_and_white_video_request_picks_bw_style():
    job = SimpleNamespace(type="video", name="Black and white video of a man walking", format="",
                          style="", prompt="")
    assert styles.pick(job).id == "bw"


def test_ping_reports_install_kind():
    from joeai import update
    assert update.install_kind() in update.KINDS + ("source",)


# ---- "rerun the black and white videos" re-plans the earlier task, no AI guess --------------
from test_core import env  # noqa: F401,E402

BIG3 = """TASK: Proofread dev111  TYPE: proofread  INPUT: stress/docs/Joe-Guide.md  OPTIONS: copy, clarity
TASK: Style Coloring page  SAVE: big-test-3/styles/coloring  TYPE: image  CHUNKS: 1 x 5  STYLE: coloring
FORMAT: an adult coloring page of an intricate mandala made of flowers and birds.
TASK: Video Black and white  SAVE: big-test-3/video/bw  TYPE: video  CHUNKS: 1 x 2  STYLE: bw
FORMAT: a busy small-town diner counter with three customers holding coffee cups, gentle natural motion, slow camera move.
TASK: Video Photo  SAVE: big-test-3/video/photo  TYPE: video  CHUNKS: 1 x 2  STYLE: photo
FORMAT: an old farmer and his granddaughter at a farm stand, gentle natural motion, slow camera move.
"""


def _app_with_done(env, text):  # noqa: F811
    from joeai.server import App
    s, sb, fake = env
    app = App(s)
    real_check = app.check
    app.check = lambda t: {**real_check(t), "ok": True, "eta_min": 5} if "TYPE: video" in t or "STYLE:" in t \
        else real_check(t)
    done = app.sb.missions / "Queue" / "done"
    done.mkdir(parents=True, exist_ok=True)
    (done / "h1-dev111-retest_20261106_091343.txt").write_text(text, encoding="utf-8")
    return app


def test_rerun_finds_the_bw_video_task(env):  # noqa: F811
    from joeai import describe
    app = _app_with_done(env, BIG3)
    r = describe.rerun_plan(app, "rerun the black and white videos")
    assert r and r["ok"], r
    assert "Video Black and white (again)" in r["mission"]
    assert "SAVE: big-test-3/video/bw-again" in r["mission"]
    assert "STYLE: bw" in r["mission"] and "diner counter" in r["mission"]
    assert "Video Photo" not in r["mission"] and "Coloring" not in r["mission"]
    assert "animate-photo" not in r["mission"]
    assert describe.rerun_plan(app, "do the b&w clips again")["mission"] == r["mission"]


def test_run_it_again_takes_the_whole_last_mission(env):  # noqa: F811
    from joeai import describe
    app = _app_with_done(env, BIG3)
    r = describe.rerun_plan(app, "run it again")
    assert r["ok"] and r["mission"].count("TASK:") == 4


def test_rerun_with_no_match_says_so_and_normal_requests_pass(env):  # noqa: F811
    from joeai import describe
    app = _app_with_done(env, BIG3)
    r = describe.rerun_plan(app, "redo the dragon pictures")
    assert r and not r["ok"] and "dragon" in r["error"]
    app.check = lambda t: {"ok": False, "error": "the video model isn't installed yet"}
    r = describe.rerun_plan(app, "rerun the black and white videos")
    assert not r["ok"] and "Video Black and white" in r["error"] and "isn't installed" in r["error"]
    assert describe.rerun_plan(app, "make 20 captions for my bakery") is None
