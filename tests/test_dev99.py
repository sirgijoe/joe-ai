"""dev99: coloring pages always come out black and white."""
import shutil
import subprocess
from pathlib import Path

import pytest

from joeai import media

FF = shutil.which("ffmpeg")


@pytest.mark.skipif(not FF, reason="needs FFmpeg")
@pytest.mark.parametrize("src", ["testsrc2=size=256x256", "color=c=white:s=256x256,drawbox=x=40:y=40:w=120:h=120:c=red@1:t=6"])
def test_line_art_is_black_and_white(tmp_path, src):
    pic, page = tmp_path / "pic.png", tmp_path / "page.png"
    subprocess.run([FF, "-y", "-v", "error", "-f", "lavfi", "-i", src, "-frames:v", "1", str(pic)], check=True)
    assert media.line_art(FF, pic, page)
    raw = subprocess.run([FF, "-v", "error", "-i", str(page), "-vf", "format=gray", "-f", "rawvideo", "-"],
                         capture_output=True, check=True).stdout
    assert set(raw) <= {0, 255} and 0 in set(raw)


def test_white_share_handles_missing_ffmpeg(tmp_path):
    assert media.white_share(str(tmp_path / "nope"), tmp_path / "x.png") == 0.0
