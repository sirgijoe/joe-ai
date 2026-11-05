"""dev96: picture styles (model, prompt-writer note, suffix, leave-out words)."""
from types import SimpleNamespace as NS

import pytest

from joeai import styles
from joeai.mission import MissionError, parse


def job(name="", fmt="", style=""):
    return NS(name=name, format=fmt, style=style)


@pytest.mark.parametrize("name,fmt,want", [
    ("Website pictures", "Clean friendly flat illustration... a camera and printed photos", "illustration"),
    ("Coloring book", "farm animals, line art for kids", "coloring"),
    ("Mascot sketches", "Character sheet of an original cartoon mascot", "character"),
    ("Shop", "product shot of a stoneware mug", "product"),
    ("Portraits", "realistic portrait photo of an old farmer", "photo"),
    ("Banners", "a sunrise over hills", "general"),
])
def test_guess(name, fmt, want):
    assert styles.pick(job(name, fmt)).id == want


def test_style_line_wins_and_is_checked():
    assert styles.pick(job("x", "cartoon", "photo")).id == "photo"
    m = parse("TASK: a  SAVE: pics  TYPE: image  STYLE: coloring\nFORMAT: cats")
    assert m.jobs[0].style == "coloring"
    with pytest.raises(MissionError):
        parse("TASK: a  SAVE: pics  TYPE: image  STYLE: neon\nFORMAT: cats")


def test_choose_model():
    M = lambda n: NS(name=n)   # noqa: E731
    ms = [M("realismByStableYogi_v50.safetensors"), M("dreamshaperXL.safetensors"), M("sdxl_base.safetensors")]
    assert [m.name for m in styles.choose_model(ms, "photo")] == ["realismByStableYogi_v50.safetensors"]
    assert styles.choose_model(ms, "illustration")[0].name == "dreamshaperXL.safetensors"
    only_real = [M("realismByStableYogi_v50.safetensors"), M("sdxl_base.safetensors")]
    assert [m.name for m in styles.choose_model(only_real, "coloring")] == ["sdxl_base.safetensors"]
    assert styles.choose_model([M("juggernautXL.safetensors")], "illustration") == []
    assert styles.hints("photo", {"styles": {"photo": ["Mine"]}}) == ["mine"]


def test_suffix():
    assert styles.add("a cat.", styles.STYLES["coloring"]).startswith("a cat, black and white")
    assert styles.add("a cat", styles.STYLES["general"]) == "a cat"


@pytest.mark.parametrize("fmt,want", [
    ("a knight, anime style, cel shaded", "anime"), ("oil painting of a harbor", "painting"),
    ("concept art of a ruined castle", "concept"), ("3d render of a robot toy", "render3d"),
    ("cyberpunk street at night with neon", "scifi"), ("comic panel of a dog hero", "cartoon"),
    ("16-bit pixel art forest", "pixel"), ("surreal melting clocks", "surreal"),
])
def test_eight_common_styles(fmt, want):
    assert styles.pick(job("x", fmt)).id == want
    assert set(styles.NAMES) == set(styles.STYLES)
