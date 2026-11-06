"""dev109: Setup > System check > Your models."""
from joeai import stylemodels as sm


def test_inventory(tmp_path):
    md = tmp_path / "models"
    (md / "checkpoints").mkdir(parents=True)
    (md / "loras").mkdir()
    (md / "vae").mkdir()
    (md / "checkpoints" / "juggernautXL_v9.safetensors").write_bytes(b"x" * 2048)
    (md / "loras" / "pixel-art-xl.safetensors").write_bytes(b"x" * 10)
    (md / "vae" / "wan2.2_vae.safetensors").write_bytes(b"x")
    inv = sm.inventory(md, [{"name": "qwen3:14b", "size_gb": 9.3, "params": "14B", "writer": True}])
    assert inv["writing"][0]["name"] == "qwen3:14b"
    assert inv["pictures"][0]["name"].endswith("juggernautXL_v9.safetensors") and "Photo" in inv["pictures"][0]["styles"]
    assert inv["addons"][0]["styles"] == ["Pixel art"]
    assert inv["other"][0]["what"].startswith("Picture decoder")
    assert sm.inventory(None, [])["pictures"] == []
