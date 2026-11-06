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
