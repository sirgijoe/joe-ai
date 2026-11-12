"""2.3.0.dev22: manga looks ask for monochrome, greyscale; anime/manga prompts that name no person get "no humans"."""
from types import SimpleNamespace

from joeai import styles
from joeai.engine import Engine


def _rec(style):
    return styles.recipe(SimpleNamespace(name="Baseline", format=f"STYLE: {style}"))


def test_manga_looks_are_greyscale():
    for name in ("two fighters clash", "close-up of her eyes", "a quiet street"):
        rec = styles.recipe(SimpleNamespace(name=name, format="STYLE: manga"))
        assert "monochrome, greyscale" in rec.words


def test_no_humans_per_prompt():
    eng = SimpleNamespace(_lora_used=False)
    styled = lambda p, s: Engine._styled(eng, p, _rec(s))
    assert styled("a ceramic mug on a wooden table", "anime").endswith("no humans")
    assert styled("a cat on a rooftop", "manga").endswith("no humans")
    assert "no humans" not in styled("a woman sitting in an armchair reading a book", "anime")
    assert "no humans" not in styled("1boy, close-up", "manga")
    assert "no humans" not in styled("a ceramic mug on a wooden table", "watercolor")
