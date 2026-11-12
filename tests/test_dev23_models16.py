"""2.3.0.dev16: Joe offers every recommended picture model that isn't installed (found on Joseph's PC:
he downloaded everything Joe told him to, and Joe had never offered DreamShaper, RealVisXL or Animagine)."""
from __future__ import annotations

from joeai import comfy, stylemodels as sm

GB = 2 ** 30
PC = [("cyberrealisticPony_v110.safetensors", "sdxl"), ("juggernautXL_ragnarokBy.safetensors", "sdxl"),
      ("perfectionAmateurILXL_v20.safetensors", "sdxl"), ("realismByStableYogi_v50FP16.safetensors", "sdxl"),
      ("ultraRealisticByStable_v10.safetensors", "sdxl"), ("v1-5-pruned-emaonly-fp16.safetensors", "sd15"),
      ("SDXL\\sd_xl_base_1.0_0.9vae.safetensors", "sdxl"), ("segmind-vega\\segmind-vega.safetensors", "sdxl"),
      ("SVD\\svd.safetensors", "svd")]
ADDONS = ["ColoringBookRedmond-ColoringBook-ColoringBookAF.safetensors", "pixel-art-xl.safetensors", "watercolor_sdxl.safetensors"]


def models(rows=PC):
    return [comfy.ImageModel(n, "checkpoints", 6.5, fam) for n, fam in rows]


def test_josephs_pc_is_offered_the_three_models_it_lacks():
    ids = [o["id"] for o in sm.offers(models(), None, ADDONS)]
    assert ids == ["style-product", "style-illustration", "style-anime"]          # RealVisXL, DreamShaper, Animagine
    what = " ".join(o["what"] for o in sm.offers(models(), None, ADDONS))
    assert "RealVisXL V5" in what and "DreamShaper XL" in what and "Animagine XL 4.0" in what and "Juggernaut" not in what


def test_a_model_that_only_suits_the_style_doesnt_hide_the_recommended_one():
    ids = {o["id"] for o in sm.offers(models([("SDXL\\sd_xl_base_1.0.safetensors", "sdxl")]), None, ADDONS)}
    assert ids == {"style-photo", "style-product", "style-illustration", "style-anime"}


def test_the_recommended_model_itself_is_found_by_its_name_or_its_file():
    have = models([("dreamshaperXL_v21.safetensors", "sdxl"), ("RealVisXL_V5.0_fp16.safetensors", "sdxl"),
                   ("sub\\animagine-xl-4.0.safetensors", "sdxl"), ("Juggernaut-XL_v9.safetensors", "sdxl")])
    assert sm.offers(have, None, ADDONS) == []
    assert not sm.has_model(models([("SVD\\juggernaut_video.safetensors", "svd")]), {"name": "Juggernaut XL"})


def test_your_models_never_lists_a_video_model_or_sd15_for_an_sdxl_add_on(tmp_path, monkeypatch):
    monkeypatch.setattr(comfy, "scan_models", lambda d: models())
    monkeypatch.setattr(comfy, "list_loras", lambda d: [])
    inv = sm.inventory(tmp_path, [])
    rows = {r["name"]: r["styles"] for r in next(v for v in inv.values() if isinstance(v, list) and v and "family" in v[0])}
    assert rows["SVD\\svd.safetensors"] == []
    sd15 = rows["v1-5-pruned-emaonly-fp16.safetensors"]
    assert sd15 and not {"Pixel art", "Watercolor", "Coloring page"} & set(sd15)
    assert "Pixel art" in rows["SDXL\\sd_xl_base_1.0_0.9vae.safetensors"]
