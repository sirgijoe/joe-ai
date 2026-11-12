"""2.3.0.dev19: anime and manga (Animagine XL 4.0) skip the weighted anatomy leave-out list.
Anime test 2026-11-12 (seed 424242, mug prompt): with the list the colours burned neon and the
subject broke; without it the picture came out clean. CFG, scheduler and detail pass were not the cause."""
from types import SimpleNamespace

from joeai import comfy, styles


def _job(style):
    return SimpleNamespace(name="t", format="a handmade ceramic coffee mug", style=style, type="image")


def test_anime_and_manga_skip_anatomy_list():
    for sid in ("anime", "manga"):
        r = styles.recipe(_job(sid))
        assert r.style.id == sid and r.anatomy is False
        neg = comfy.negative_for("sdxl", "", r.negative, r.anatomy)
        assert "mutated hands" not in neg and comfy.SHORT_NEGATIVE in neg


def test_photo_keeps_anatomy_list():
    assert styles.recipe(_job("photo")).anatomy is True
