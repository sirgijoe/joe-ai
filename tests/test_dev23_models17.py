"""2.3.0.dev17: each style uses the model recommended for it, and getting a model is plain for anyone
(Joseph asks "from the average user's shoes": nobody should have to know to press GET IT twice)."""
from __future__ import annotations

import json
import time
from pathlib import Path

from joeai import comfy, stylemodels as sm, styles

PC = ["animagine-xl-4.0.safetensors", "cyberrealisticPony_v110.safetensors",
      "DreamShaperXL1.0Alpha2_fixedVae_half_00001_.safetensors", "juggernautXL_ragnarokBy.safetensors",
      "perfectionAmateurILXL_v20.safetensors", "realismByStableYogi_v50FP16.safetensors",
      "RealVisXL_V5.0_fp32.safetensors", "SDXL\\sd_xl_base_1.0_0.9vae.safetensors", "ultraRealisticByStable_v10.safetensors"]
WANT = {"photo": "juggernaut", "bw": "juggernaut", "product": "realvis", "anime": "animagine", "manga": "animagine",
        "illustration": "dreamshaper", "character": "dreamshaper", "coloring": "dreamshaper", "painting": "dreamshaper",
        "watercolor": "dreamshaper", "concept": "dreamshaper", "fantasy": "dreamshaper", "render3d": "dreamshaper",
        "scifi": "dreamshaper", "cyberpunk": "dreamshaper", "cartoon": "dreamshaper", "comic": "dreamshaper",
        "pixel": "dreamshaper", "surreal": "dreamshaper", "abstract": "dreamshaper"}


def _pick(style, picks):
    ms = [comfy.ImageModel(n, "checkpoints", 6.5, "sdxl", 1.0) for n in PC]
    suited = styles.choose_model(ms, style, picks)
    return comfy.best_image_model(suited, 12, "image").name.lower() if suited else ""


def test_every_style_uses_the_model_recommended_for_it():
    bundled = json.loads((Path(sm.__file__).parent / "model_picks.json").read_text(encoding="utf-8"))
    for picks in (None, bundled):                       # Joe's built-in words, and the list on GitHub
        for style, model in WANT.items():
            assert model in _pick(style, picks), (style, _pick(style, picks), "bundled" if picks else "built-in")
    assert bundled["updated"] >= "2026-11-12"           # newer than GitHub's copy, so this Joe's list wins


def test_the_half_size_file_is_taken_when_a_repo_has_one():
    both = [{"rfilename": "RealVisXL_V5.0_fp32.safetensors", "size": 13_800_000_000},
            {"rfilename": "RealVisXL_V5.0_fp16.safetensors", "size": 6_900_000_000},
            {"rfilename": "unet/diffusion_pytorch_model.fp16.safetensors", "size": 5_000_000_000}]
    assert sm.hf_pick_file(both) == "RealVisXL_V5.0_fp16.safetensors"
    assert sm.hf_pick_file(both[:1]) == "RealVisXL_V5.0_fp32.safetensors"          # only the big one: that one


def test_an_offer_says_which_file_and_why_you_download_it_yourself():
    o = next(x for x in sm.offers([comfy.ImageModel("sd_xl_base_1.0.safetensors", "checkpoints", 6.5, "sdxl")])
             if x["id"] == "style-illustration")
    assert "alpha2, not Turbo or Lightning" in o["text"] and "Joe can't download it for you" in o["text"]
    assert "Joe asks to move it into ComfyUI" in o["text"]


def test_joe_notices_a_finished_download_and_offers_to_move_it(tmp_path, monkeypatch):
    from joeai import doctor
    from joeai.server import App
    from joeai.config import Settings
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "cfg" / "settings.json"))
    (tmp_path / "cfg").mkdir()
    dl, mdir = tmp_path / "Downloads", tmp_path / "models"
    dl.mkdir()
    (mdir / "checkpoints").mkdir(parents=True)
    monkeypatch.setenv("JOE_DOWNLOADS", str(dl))
    monkeypatch.setattr(sm, "MIN_BYTES", 10)
    monkeypatch.setattr(sm, "LORA_BYTES", 5)
    monkeypatch.setattr(doctor, "comfy_models_dir", lambda s: mdir)
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    app = App(settings=s)
    (dl / "animagine-xl-4.0.safetensors").write_bytes(b"x" * 20)
    assert app.models_waiting_tick() == [] and app.state()["models_waiting"] == []       # nobody pressed GET IT
    app.models_pending_until = time.time() + 60                                           # GET IT opened the page
    (dl / "half.safetensors.crdownload").write_bytes(b"x" * 20)                           # still downloading: not yet
    assert app.models_waiting_tick() == ["animagine-xl-4.0.safetensors"]
    assert app.state()["models_waiting"] == ["animagine-xl-4.0.safetensors"]
    assert (dl / "animagine-xl-4.0.safetensors").exists()                                 # noticing moves nothing
    app.models_pending_until = time.time() - 1                                            # six hours on: stops looking
    assert app.models_waiting_tick() == []
    html = (Path(sm.__file__).parent / "ui" / "index.html").read_text(encoding="utf-8")
    assert 'id="modelsbar"' in html and html.index('id="modelsbar"') < html.index('id="workarea"')   # on every tab
