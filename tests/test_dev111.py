"""dev111: big-test-2 fixes (proofread cap + case-only suggestions, vague doubts, mascot, video,
coloring pages that are already line art)."""
import shutil
import subprocess

import pytest

from joeai import media
from joeai.engine import Engine, VIDEO_EXTRA
from joeai.styles import STYLES
from joeai.tools import apply_changes, is_doubt

FF = shutil.which("ffmpeg")


def test_case_only_suggestions_already_correct_are_dropped():
    text = "## Running it\n\nThe status bar shows the GPU live.\n\nPhone photos are turned the right way up, and more."
    out, applied, noted, missed = apply_changes(text, [
        {"find": "running it", "replace": "Running it", "why": "capitalization"},
        {"find": "the status bar shows the GPU live.", "replace": "The status bar shows the GPU live.", "why": ""},
        {"find": "phone photos are turned the right way up", "replace": "phone photos are turned the right way up,",
         "why": "punctuation"},
    ])
    assert out == text and not applied and not missed


def test_case_insensitive_match_keeps_original_capital():
    text = "Teh cat sat."
    out, applied, _, missed = apply_changes(text, [{"find": "teh cat", "replace": "the cat", "why": "spelling"}])
    assert out == "The cat sat." and len(applied) == 1 and not missed


def test_vague_missing_word_is_not_a_doubt():
    assert not is_doubt("unsure: possibly missing word: it's made once and kept")
    assert not is_doubt("possibly missing word")
    assert is_doubt("unsure: missing word 'the' before ComfyUI?")
    assert is_doubt("might be the wrong product name")


def test_capped_kinds():
    assert {"proofread", "translate"} <= Engine.CAPPED_KINDS
    assert not Engine.CAPPED_KINDS & Engine.THINK_KINDS


def test_mascot_is_a_brand_character_not_an_icon():
    s = STYLES["character"]
    assert "Mascot" in s.label and "icon" in s.negative and "DOING" in s.note


def test_video_prompt_asks_for_one_subject_one_motion():
    assert "ONE main subject" in VIDEO_EXTRA


@pytest.mark.skipif(not FF, reason="needs ffmpeg")
def test_thin_line_drawing_is_detected_as_line_art(tmp_path):
    pic = tmp_path / "lines.png"
    # thin black grid on white: at 64x64 this used to blur into 'filled in' gray
    subprocess.run([FF, "-v", "error", "-f", "lavfi", "-i", "color=white:s=1024x1024",
                    "-vf", "drawgrid=w=40:h=40:t=2:c=black", "-frames:v", "1", str(pic)], check=True)
    assert media.is_line_drawing(FF, pic)
    red = tmp_path / "red.png"
    subprocess.run([FF, "-v", "error", "-f", "lavfi", "-i", "color=red:s=256x256", "-frames:v", "1", str(red)],
                   check=True)
    assert not media.is_line_drawing(FF, red)
