"""dev95: better default 'leave out' lists (six fingers, a four-armed background person)."""
from joeai import comfy


def test_image_default_has_anatomy():
    n = comfy.negative_for("sdxl", "", "")
    assert n.startswith("(mutated hands") and "extra arms" in n


def test_old_saved_default_upgraded_and_custom_kept():
    assert comfy.negative_for("sd15", comfy.OLD_IMAGE_NEGATIVE, "") == comfy.IMAGE_NEGATIVE
    assert comfy.negative_for("sdxl", "my own list", "") == "my own list"


def test_task_negative_adds_to_default():
    n = comfy.negative_for("wan", "", "cars")
    assert n.startswith("cars, ") and "extra arms" in n and comfy.WAN_VIDEO["negative"] == comfy.WAN_NEGATIVE
