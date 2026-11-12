"""2.3.0.dev18: picture settings moved to what each style's model asks for (docs/defaults-review.html)."""
import json
from pathlib import Path

from joeai import quality, styles, workflowprefs

PICKS = json.loads((Path(styles.__file__).parent / "model_picks.json").read_text("utf-8"))


def _looks(style):
    return next(v for v in PICKS.values() if isinstance(v, dict) and isinstance(v.get(style), dict)
                and "looks" in v[style])[style]


def test_photo_styles_follow_juggernaut():
    for sid in ("photo", "bw"):
        st = styles.STYLES[sid]
        assert (st.sampler, st.steps, st.denoise) == ("dpmpp_2m_sde", 30, 0.3)
        assert 3 <= 6 + st.cfg <= 6


def test_product_follows_realvis():
    st = styles.STYLES["product"]
    assert (st.sampler, st.steps, st.denoise) == ("dpmpp_sde", 30, 0.3)


def test_other_styles_keep_their_numbers():
    st = styles.STYLES["fantasy"]
    assert (st.sampler, st.steps, st.denoise) == ("", 0, 0.4)
    assert workflowprefs.tune_defaults("style:fantasy")["denoise"] == 0.4
    assert workflowprefs.tune_defaults("style:product")["denoise"] == 0.3


def test_animagine_score_tags():
    for sid in ("anime", "manga"):
        assert "low score, bad score, average score" in styles.STYLES[sid].negative
        for look in _looks(sid)["looks"]:
            assert look["words"].endswith("masterpiece, high score, great score, absurdres")


def test_watercolor_trigger_and_wan_high():
    assert _looks("watercolor")["trigger"] == "Watercolor, Watercolor on textured paper"
    assert "VideoPlan((1280, 704), 121, 40, 5.0, False)" in Path(quality.__file__).read_text("utf-8")
