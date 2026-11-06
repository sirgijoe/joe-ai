"""Share A1111 / Forge model folders with ComfyUI (extra_model_paths.yaml)."""
from pathlib import Path

from joeai import comfy, sharedmodels as sh
from joeai.finder import ComfyInstall


def _webui(root: Path, name="stable-diffusion-webui-forge") -> Path:
    w = root / name
    (w / "models" / "Stable-diffusion" / "sdxl").mkdir(parents=True)
    (w / "models" / "Lora").mkdir(parents=True)
    (w / "models" / "LyCORIS").mkdir(parents=True)
    (w / "models" / "VAE").mkdir(parents=True)
    (w / "webui.py").write_text("")
    (w / "models" / "Stable-diffusion" / "sdxl" / "juggernautXL_v9.safetensors").write_bytes(b"x" * 10)
    (w / "models" / "Lora" / "pixel-art.safetensors").write_bytes(b"x")
    return w


def _comfy(root: Path) -> ComfyInstall:
    base = root / "ComfyUI_windows_portable" / "ComfyUI"
    (base / "models" / "checkpoints").mkdir(parents=True)
    (base / "main.py").write_text("")
    return ComfyInstall("portable", "run.bat", str(base.parent), str(base), 8188)


def test_parse_reads_comfy_format():
    text = """
comfyui_desktop:
    base_path: C:/Users/x/Documents/ComfyUI
    is_default: true
a111:
    base_path: D:/sd/webui/
    checkpoints: models/Stable-diffusion   # pictures
    loras: |
         models/Lora
         models/LyCORIS
    vae: models/VAE
"""
    secs = sh.parse(text)
    assert [s["name"] for s in secs] == ["comfyui_desktop", "a111"]
    a = secs[1]
    assert a["base_path"] == "D:/sd/webui/"
    assert a["folders"]["loras"] == ["models/Lora", "models/LyCORIS"]
    assert a["folders"]["vae"] == ["models/VAE"] and a["folders"]["checkpoints"] == ["models/Stable-diffusion"]


def test_find_share_and_scan(tmp_path, monkeypatch):
    monkeypatch.setattr(sh.finder, "_search_roots", lambda: [tmp_path])
    w = _webui(tmp_path)
    inst = _comfy(tmp_path)
    found = sh.find_webuis()
    assert len(found) == 1 and found[0].models == 1 and "Forge" in found[0].label
    offer = sh.offer(inst)
    assert offer and offer["action"] == "share-models"
    yaml = inst.models_dir.parent / "extra_model_paths.yaml"
    yaml.write_text("other:\n    base_path: E:/x\n", encoding="utf-8")
    assert sh.share(inst, found, log=lambda m: None) == yaml
    text = yaml.read_text(encoding="utf-8")
    assert "other:" in text and sh.MARK in text and "joe_webui_1:" in text
    assert "models/Lora\n        models/LyCORIS" in text
    assert (yaml.parent / "extra_model_paths.yaml.joe-backup").exists()
    assert sh.offer(inst) is None                                  # shared now
    sh.share(inst, found, log=lambda m: None)                      # no duplicate section
    assert yaml.read_text(encoding="utf-8").count("joe_webui_") == 1
    names = [m.name for m in comfy.scan_models(inst.models_dir)]
    assert any("juggernautXL_v9" in n for n in names)
    assert "pixel-art.safetensors" in comfy.list_loras(inst.models_dir)
    assert w.exists()
