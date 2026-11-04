"""Setup > Quality: Low / Medium / High for writing, pictures and video."""
from joeai import comfy, quality
from joeai.config import Settings


def test_levels_and_fallback():
    s = Settings()
    assert quality.level(s, "video") == "medium"
    s.quality.video = "HIGH"
    assert quality.level(s, "video") == "high"
    s.quality.video = "ultra"
    assert quality.level(s, "video") == "medium"          # anything unknown = medium


def test_video_plans_use_turbo_only_below_high():
    s = Settings()
    med = quality.video(s, turbo_installed=True)
    assert med.turbo and med.steps == 4 and med.cfg == 1.0 and med.size == (1280, 704) and med.frames == 121
    assert not quality.video(s, turbo_installed=False).turbo and quality.video(s, False).steps == 20
    s.quality.video = "high"
    hi = quality.video(s, turbo_installed=True)
    assert not hi.turbo and hi.steps == 30
    s.quality.video = "low"
    lo = quality.video(s, turbo_installed=True)
    assert lo.turbo and lo.frames == 73 and lo.size == (960, 544)
    assert all(v % 32 == 0 for v in lo.size) and (lo.frames - 1) % 4 == 0


def test_turbo_graph_adds_lora_between_model_and_sampling():
    g = comfy.wan_video_graph(frames=73, steps=4, cfg=1.0, turbo=True)
    assert g["60"]["class_type"] == "LoraLoaderModelOnly" and g["60"]["inputs"]["model"] == ["37", 0]
    assert g["48"]["inputs"]["model"] == ["60", 0]
    assert g["3"]["inputs"]["steps"] == 4 and g["3"]["inputs"]["cfg"] == 1.0
    assert g["55"]["inputs"]["length"] == 73
    plain = comfy.wan_video_graph()
    assert "60" not in plain and plain["48"]["inputs"]["model"] == ["37", 0]


def test_turbo_installed_check(tmp_path):
    assert not comfy.wan_turbo_installed(tmp_path)
    (tmp_path / "loras" / "wan").mkdir(parents=True)
    (tmp_path / "loras" / "wan" / comfy.WAN_TURBO["file"][1]).write_bytes(b"x")
    assert comfy.wan_turbo_installed(tmp_path)


def test_picture_plans():
    s = Settings()
    s.quality.pictures = "low"
    p = quality.pictures(s)
    assert p.steps("sdxl") == 14 and p.size(1024, 1024) == (768, 768) and p.size(512, 512) == (512, 512)
    s.quality.pictures = "high"
    assert quality.pictures(s).steps("sd15") == 35 and quality.pictures(s).size(1024, 1024) == (1024, 1024)
    assert comfy.basic_graph("sdxl", 40, "dpmpp_2m_sde")["3"]["inputs"]["sampler_name"] == "dpmpp_2m_sde"


def test_writing_plan_and_smaller_model():
    from joeai import doctor
    s = Settings()
    assert quality.writing(s).think is False
    s.quality.writing = "high"
    assert quality.writing(s).think is True
    s.quality.writing = "low"
    assert quality.writing(s).smaller_model

    class SM: pass
    models = [{"name": "qwen3:14b", "writer": True, "params": "14.8B", "size_gb": 9.3},
              {"name": "qwen3:8b", "writer": True, "params": "8.2B", "size_gb": 5.2},
              {"name": "qwen3:0.6b", "writer": True, "params": "0.6B", "size_gb": 0.5},
              {"name": "nomic-embed", "writer": False, "params": "137M", "size_gb": 0.3}]
    orig = doctor.ollama_models
    doctor.ollama_models = lambda sm: models
    try:
        assert doctor.smaller_text_model(SM(), "qwen3:14b") == "qwen3:8b"
        assert doctor.smaller_text_model(SM(), "qwen3:8b") is None        # nothing usable below 1B
    finally:
        doctor.ollama_models = orig


def test_think_override_reaches_ollama():
    from joeai.ollama import OllamaClient
    from fake_ollama import FakeOllama
    fake = FakeOllama()
    try:
        s = Settings()
        s.ollama.url = fake.url
        c = OllamaClient(s.ollama)
        msgs = [{"role": "system", "content": "You are Joe (real name ..."}, {"role": "user", "content": "hi"}]
        c.chat(msgs, model="m", think=True)
        assert fake.requests[-1]["think"] is True
        c.chat(msgs, model="m")
        assert fake.requests[-1]["think"] is False
    finally:
        fake.close()
