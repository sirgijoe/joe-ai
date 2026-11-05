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
    ("cyberpunk street at night with neon", "cyberpunk"), ("comic panel of a dog hero", "comic"),
    ("16-bit pixel art forest", "pixel"), ("surreal melting clocks", "surreal"),
])
def test_eight_common_styles(fmt, want):
    assert styles.pick(job("x", fmt)).id == want
    assert set(styles.NAMES) == set(styles.STYLES)


def test_kid_safe_only_when_asked():
    assert styles.for_kids(job("Coloring book", "farm animals for my toddler"))
    assert styles.for_kids(job("Kids coloring book", "mermaids"))
    assert not styles.for_kids(job("Coloring book", "art nouveau figure studies for adults"))


@pytest.mark.parametrize("fmt,want", [
    ("manga panel with screentone", "manga"), ("watercolor of a barn", "watercolor"),
    ("a dragon over a castle", "fantasy"), ("neon cyberpunk alley", "cyberpunk"),
    ("comic book superhero", "comic"), ("abstract geometric art", "abstract"),
])
def test_more_styles(fmt, want):
    assert styles.pick(job("x", fmt)).id == want


def test_lora_pick_and_graph():
    from joeai import comfy
    assert styles.pick_lora(styles.STYLES["pixel"], ["foo.safetensors", "pixel-art-xl.safetensors"]) \
        == "pixel-art-xl.safetensors"
    assert styles.pick_lora(styles.STYLES["photo"], ["pixel-art-xl.safetensors"]) == ""
    g = comfy.with_lora(comfy.basic_graph("sdxl"), "pixel-art-xl.safetensors")
    assert g["3"]["inputs"]["model"] == ["10", 0] and g["6"]["inputs"]["clip"] == ["10", 1]
    assert g["8"]["inputs"]["vae"] == ["4", 2] and g["10"]["inputs"]["model"] == ["4", 0]


def test_black_and_white_photo():
    assert styles.pick(job("x", "black and white portrait of an old farmer")).id == "bw"
    assert styles.pick(job("x", "monochrome street photo")).id == "bw"
    assert "color" in styles.STYLES["bw"].negative
