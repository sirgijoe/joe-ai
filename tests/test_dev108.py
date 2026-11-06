"""dev108: sub-looks from the style research."""
from types import SimpleNamespace as NS

from joeai import comfy, styles, stylemodels as sm


def job(name="", fmt="", style=""):
    return NS(name=name, format=fmt, style=style)


def test_looks_picked_from_words():
    assert styles.recipe(job("x", "a portrait photo of an old farmer")).look["id"] == "portrait"
    assert styles.recipe(job("x", "a photo of a misty lake at sunrise")).look["id"] == "landscape"
    assert styles.recipe(job("x", "film noir detective, black and white photo")).look["id"] == "noir"
    assert styles.recipe(job("x", "product shot, flat lay of soaps")).look["id"] == "flatlay"
    assert styles.recipe(job("x", "cyberpunk city skyline")).look["id"] == "city"
    r = styles.recipe(job("x", "abstract geometric art"))
    assert r.look["id"] == "geometric" and not r.anatomy
    assert styles.recipe(job("x", "a mug", "product")).look["id"] == "hero"


def test_recipe_notes_and_negatives():
    r = styles.recipe(job("x", "sci-fi mech suit in a hangar", "scifi"))
    assert r.negative.startswith("(magic, wizard") and any("LOOK:" in n for n in r.notes)
    assert styles.recipe(job("x", "manga panel", "manga")).negative.startswith("color")


def test_short_negative_for_surreal():
    n = comfy.negative_for("sdxl", "", "stock photography feel", anatomy=False)
    assert "extra arms" not in n and n.startswith("stock photography")


def test_pinned_download_file():
    link = sm.download_link("https://huggingface.co/cagliostrolab/animagine-xl-4.0", file="animagine-xl-4.0.safetensors")
    assert link.endswith("/resolve/main/animagine-xl-4.0.safetensors?download=true")
