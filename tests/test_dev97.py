"""dev97: recommended picture models per style; moving downloaded models into ComfyUI."""
from types import SimpleNamespace as NS

from joeai import stylemodels as sm


def M(n):
    return NS(name=n)


def test_offers_only_missing_styles():
    have = [M("juggernautXL_ragnarokBy.safetensors")]
    ids = [o["id"] for o in sm.offers(have)]
    assert "style-anime" in ids and "style-photo" not in ids
    o = next(o for o in sm.offers(have) if o["id"] == "style-anime")
    assert o["action"] == "import-models" and o["page"].startswith(sm.PAGE_HOSTS)


def test_bad_rows_ignored():
    picks = {"style_models": [{"style": "anime", "name": "X", "page": "http://evil.example/x"}]}
    assert sm.recommendations(picks) == []


def test_import_moves_big_model_files(tmp_path, monkeypatch):
    monkeypatch.setattr(sm, "MIN_BYTES", 10)
    monkeypatch.setattr(sm, "LORA_BYTES", 5)
    dl, mdir = tmp_path / "Downloads", tmp_path / "models"
    dl.mkdir()
    (dl / "animagine-xl-4.0.safetensors").write_bytes(b"x" * 20)
    (dl / "tiny_lora.safetensors").write_bytes(b"x")
    (dl / "notes.txt").write_text("hi")
    logs = []
    assert [p.name for p in sm.found(mdir, dl)] == ["animagine-xl-4.0.safetensors"]
    assert sm.import_downloads(mdir, logs.append, dl) == 1
    assert (mdir / "checkpoints" / "animagine-xl-4.0.safetensors").exists()
    assert "Anime" in logs[0] and sm.found(mdir, dl) == []


def test_style_of():
    assert sm.style_of("juggernautXL_v9.safetensors") == "photo"
    assert sm.style_of("animagineXL.safetensors") == "anime"
    assert sm.style_of("mystery.safetensors") == "general"


def test_lora_offer_and_move(tmp_path, monkeypatch):
    have = [M("dreamshaperXL.safetensors"), M("juggernautXL.safetensors"), M("animagine.safetensors"),
            M("realvisxl.safetensors")]
    ids = {o["id"] for o in sm.offers(have, None, [])}
    assert {"style-pixel", "style-coloring", "style-watercolor"} <= ids
    assert "style-pixel" not in {o["id"] for o in sm.offers(have, None, ["pixel-art-xl.safetensors"])}
    monkeypatch.setattr(sm, "LORA_BYTES", 5)
    monkeypatch.setattr(sm, "MIN_BYTES", 50)
    dl, mdir = tmp_path / "dl", tmp_path / "models"
    dl.mkdir()
    (dl / "pixel-art-xl.safetensors").write_bytes(b"x" * 10)
    (dl / "random_embedding.safetensors").write_bytes(b"x" * 10)
    assert sm.import_downloads(mdir, lambda m: None, dl) == 1
    assert (mdir / "loras" / "pixel-art-xl.safetensors").exists()



def test_hf_direct_link_pick():
    assert sm.hf_repo("https://huggingface.co/nerijs/pixel-art-xl") == "nerijs/pixel-art-xl"
    assert sm.hf_repo("https://civitai.com/models/1/x") == ""
    sib = [{"rfilename": "unet/diffusion_pytorch_model.safetensors", "size": 9e9},
           {"rfilename": "README.md", "size": 10},
           {"rfilename": "pixel-art-xl.safetensors", "size": 1.7e8},
           {"rfilename": "small.safetensors", "size": 1e6}]
    assert sm.hf_pick_file(sib) == "pixel-art-xl.safetensors"
    assert sm.hf_pick_file([]) == ""
    assert sm.download_link("https://civitai.com/models/1/x") == "https://civitai.com/models/1/x"
