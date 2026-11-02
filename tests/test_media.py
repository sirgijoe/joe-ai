import json
import threading

import pytest

from joeai import comfy, doctor, media
from joeai.config import Settings
from joeai.engine import Engine
from joeai.mission import MissionError, parse
from joeai.sandbox import Sandbox

from fake_comfy import FakeComfy
from fake_ollama import FakeOllama

IMG = """=== JOE MISSION ===
PROJECT: Test Studio
TASK: Writeup  SAVE: t/a.md  CHUNKS: 1 x 2
TASK: Mood art  SAVE: art/mood  TYPE: image  CHUNKS: 2 x 2  VARIANTS: 2  SEED: 100
FORMAT: Soft morning light, studio still life.
=== END ==="""


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "settings.json"))
    fo, fc = FakeOllama(), FakeComfy()
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    s.ollama.url, s.comfy.url = fo.url, fc.url
    s.comfy.models_dir = str(tmp_path / "none")
    s.engine.retry_backoff_s = 0
    s.engine.gpu_temp_pause_c = 0
    s.engine.keep_awake = False
    sb = Sandbox(s.workspace_path).ensure()
    yield s, sb, fo, fc
    fo.close()
    fc.close()


def test_image_job_end_to_end(env):
    s, sb, fo, fc = env
    order = []
    states = Engine(s, sb, log=order.append).run_mission(parse(IMG))
    text, img = states
    assert text.status == "done"
    assert img.status == "done", img.note
    assert len(img.prompts) == 4 and img.items == 8          # 4 prompts x 2 variants
    folder = sb.output / "art" / "mood"
    pngs = sorted(p.name for p in folder.glob("*.png"))
    assert len(pngs) == 8 and pngs[0].startswith("001_") and pngs[0].endswith("_1.png")
    man = json.loads((folder / "_media.json").read_text())
    assert man["ai_generated"] and "AI-GENERATED" in man["note"]
    seeds = sorted(v["seed"] for v in man["items"].values())
    assert seeds == list(range(100, 108))
    assert (folder / "_prompts.md").exists()
    # built-in graph got the best SDXL checkpoint, 1024 size and the prompt text
    g = fc.graphs[0]
    assert g["4"]["inputs"]["ckpt_name"] == "SDXL\\example_sdxl_model.safetensors"
    assert g["5"]["inputs"]["width"] == 1024
    assert "{{" not in json.dumps(g)
    assert fc.freed >= 0
    assert "prompt writer" in fo.systems[-1]                   # prompt-writer system prompt


def test_image_resume_after_stop(env):
    s, sb, fo, fc = env
    stop = threading.Event()

    def log(msg):
        if " 3/8:" in msg:
            stop.set()
    st = Engine(s, sb, log=log, stop=stop).run_mission(parse(IMG))[1]
    assert st.status == "stopped" and st.images_done == 3
    st = Engine(s, sb, log=lambda m: None).run_mission(parse(IMG))[1]
    assert st.status == "done" and st.items == 8
    assert len(list((sb.output / "art" / "mood").glob("*.png"))) == 8   # same folder, no dupes


def test_template_autodetect_and_swap(env):
    s, sb, fo, fc = env
    wf = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "another_sdxl_model.safetensors"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "a cat", "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "ugly", "clip": ["1", 1]}},
        "4": {"class_type": "FluxGuidance", "inputs": {"conditioning": ["2", 0], "guidance": 3.5}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
        "6": {"class_type": "KSampler", "inputs": {"seed": 1, "positive": ["4", 0], "negative": ["3", 0],
                                                   "model": ["1", 0], "latent_image": ["5", 0]}},
        "7": {"class_type": "SaveImage", "inputs": {"filename_prefix": "x", "images": ["6", 0]}},
    }
    (sb.workflows / "mine.json").write_text(json.dumps(wf))
    m = parse("""=== JOE MISSION ===
TASK: Cats  SAVE: cats  TYPE: image  WORKFLOW: mine  SIZE: 832 x 1216  NEGATIVE: blurry
PART: a sleepy cat
PART: a cat on a kiln
PROMPTS: as written
=== END ===""")
    st = Engine(s, sb, log=lambda m: None).run_mission(m)[0]
    assert st.status == "done", st.note
    g = fc.graphs[1]
    assert g["2"]["inputs"]["text"] == "a cat on a kiln"
    assert g["3"]["inputs"]["text"] == "blurry"
    assert (g["5"]["inputs"]["width"], g["5"]["inputs"]["height"]) == (832, 1216)
    assert g["1"]["inputs"]["ckpt_name"] == "SDXL\\example_sdxl_model.safetensors"   # same family swap
    assert g["7"]["inputs"]["filename_prefix"] == "Joe/cats"


def test_ui_workflow_rejected(tmp_path):
    p = tmp_path / "ui.json"
    p.write_text(json.dumps({"nodes": [], "links": []}))
    with pytest.raises(comfy.WorkflowError, match="Export \\(API\\)"):
        comfy.load_template(p)


def test_placeholders():
    g = comfy.basic_graph("sd15")
    out = comfy.fill(g, "hello", "bad", 42, 512, 768, "a.safetensors", "P")
    assert out["6"]["inputs"]["text"] == "hello" and out["3"]["inputs"]["seed"] == 42
    assert out["5"]["inputs"]["height"] == 768 and out["9"]["inputs"]["filename_prefix"] == "P"


def test_media_mission_errors():
    for bad in ["TYPE: image  SIZE: big", "TYPE: image  VARIANTS: 99", "TYPE: image  PROMPTS: as written"]:
        with pytest.raises(MissionError):
            parse(f"=== JOE MISSION ===\nTASK: x  SAVE: a  {bad}\n=== END ===")


def test_model_pickers():
    models = [comfy.ImageModel("v1-5-pruned.safetensors", "checkpoints", 2.0, "sd15", 1),
              comfy.ImageModel("example_sdxl.safetensors", "checkpoints", 6.6, "sdxl", 2),
              comfy.ImageModel("SVD\\svd.safetensors", "checkpoints", 8.9, "svd", 3),
              comfy.ImageModel("flux1-dev-fp8.safetensors", "checkpoints", 16, "flux", 4)]
    assert comfy.best_image_model(models, 12, "image").name.startswith("flux")
    assert comfy.best_image_model(models, 8, "image").name.startswith("example_sdxl")
    assert comfy.best_image_model(models, 12, "video").name.endswith("svd.safetensors")
    assert comfy.family_of("somePonyMix_v1.safetensors") == "sdxl"
    oll = [{"name": "qwen3:14b", "size_gb": 9.3, "params": "14.8B", "writer": True},
           {"name": "qwen3:32b", "size_gb": 20, "params": "32B", "writer": True},
           {"name": "nomic-embed-text", "size_gb": 0.3, "params": "137M", "writer": False}]
    assert doctor.best_ollama_model(oll, 12) == "qwen3:14b"
    assert doctor.best_ollama_model(oll, 24) == "qwen3:32b"
    assert doctor.recommended_download(12)["name"] == "qwen3:14b"


def test_reviews(tmp_path):
    media.record(tmp_path, "a.png", {"prompt": "p"})
    assert media.set_review(tmp_path, "a.png", "star") == "star"
    assert media.set_review(tmp_path, "a.png", "star") == ""          # toggles off
    media.set_review(tmp_path, "b.png", "reject")
    assert media.reviews(tmp_path) == {"b.png": "reject"}
    assert media.info(tmp_path, "a.png")["ai_generated"] is True


def test_theme_validate_and_generate(tmp_path):
    from joeai import themes
    t = themes.validate({"name": "Murky", "bg": "#101010", "fg": "#202020", "accent": "#303030",
                         "font": "Comic Sans", "crt": 9})
    assert themes.contrast(t["fg"], t["bg"]) >= 7 and t["font"] == "VT323" and t["crt"] == 3
    with pytest.raises(ValueError):
        themes.validate({"bg": "red; } body { x", "fg": "#fff", "accent": "#fff"})

    class C:
        def chat(self, msgs, model=None):
            from joeai.ollama import ChatResult
            return ChatResult('Sure: {"name": "Deep Ocean", "bg": "#021018", "fg": "#5fe0d0", '
                              '"accent": "#ff9a3c", "font": "Cascadia Mono", "crt": 1}', 1, 1, 0.1)
    t = themes.generate(C(), "m", "deep ocean at night")
    tid = themes.save(tmp_path, t)
    assert tid == "deep-ocean" and themes.list_themes(tmp_path)[0]["vars"]["--bg"] == "#021018"
    assert themes.save(tmp_path, t) == "deep-ocean-2"


def test_video_frames_to_mp4(env, tmp_path):
    import shutil
    if not shutil.which("ffmpeg"):
        pytest.skip("no ffmpeg")
    s, sb, fo, fc = env
    import fake_comfy
    fake_comfy.PNG = _png16()
    fc.frames = 8
    wf = {"1": {"class_type": "CLIPTextEncode", "inputs": {"text": "{{PROMPT}}"}},
          "2": {"class_type": "SaveImage", "inputs": {"filename_prefix": "x", "images": ["1", 0]}}}
    (sb.workflows / "vid.json").write_text(json.dumps(wf))
    m = parse("""=== JOE MISSION ===
TASK: Clip  SAVE: clips  TYPE: video  WORKFLOW: vid  FPS: 8
PART: a kiln door opening, slow push in
PROMPTS: as written
=== END ===""")
    st = Engine(s, sb, log=lambda m: None).run_mission(m)[0]
    assert st.status == "done", st.note
    mp4s = list((sb.output / "clips").glob("*.mp4"))
    assert len(mp4s) == 1 and mp4s[0].stat().st_size > 0
    assert json.loads((sb.output / "clips" / "_media.json").read_text())["items"][mp4s[0].name]["ai_generated"]


def _png16():
    import struct, zlib
    raw = b"".join(b"\x00" + b"\x40\x80\xc0" * 16 for _ in range(16))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 16, 16, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def test_server_doctor_and_review(env):
    import urllib.request
    from joeai.server import App, serve
    s, sb, fo, fc = env
    app = App(settings=s)
    httpd = serve(app)
    import threading as th
    th.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    def call(path, body=None):
        req = urllib.request.Request(base + path, headers={"X-NR-Token": app.token, "Content-Type": "application/json"},
                                     data=None if body is None else json.dumps(body).encode(),
                                     method="GET" if body is None else "POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    d = call("/api/doctor")
    assert d["ollama"]["running"] and d["comfyui"]["running"]
    assert call("/api/doctor/fix", {"action": "install", "tool": "ollama"})["ok"] is False   # no approval
    (sb.output / "pic.png").write_bytes(b"x")
    assert call("/api/review", {"path": "Output/pic.png", "mark": "keep"})["mark"] == "keep"
    ent = [e for e in call("/api/files?path=Output")["entries"] if e["name"] == "pic.png"][0]
    assert ent["review"] == "keep" and ent["kind"] == "image"
    assert "hw" in call("/api/state")
    httpd.shutdown()


def test_family_from_file_contents(tmp_path):
    def st(name, keys):
        import struct
        hdr = json.dumps({k: {"dtype": "F16", "shape": [1], "data_offsets": [0, 2]} for k in keys}).encode()
        p = tmp_path / name
        p.write_bytes(struct.pack("<Q", len(hdr)) + hdr + b"\0\0")
        return p
    # File names say nothing; the tensor names decide.
    assert comfy.family_of("a.safetensors", 0, st("a.safetensors", ["conditioner.embedders.1.model.x"])) == "sdxl"
    assert comfy.family_of("b.safetensors", 0, st("b.safetensors", ["cond_stage_model.transformer.x"])) == "sd15"
    assert comfy.family_of("c.safetensors", 0, st("c.safetensors", ["model.diffusion_model.double_blocks.0.x"])) == "flux"
    assert comfy.family_of("d.safetensors", 0, st("d.safetensors", ["model.diffusion_model.joint_blocks.0.x"])) == "sd3"
    assert comfy.family_of("e.safetensors", 0, st("e.safetensors", ["model.diffusion_model.input_blocks.0.time_stack.x"])) == "svd"
    # Unknown contents fall back to the name, then the size.
    assert comfy.family_of("my_sdxl_mix.safetensors", 0, st("my_sdxl_mix.safetensors", ["x"])) == "sdxl"
    assert comfy.family_of("mystery.safetensors", 2.0, st("mystery.safetensors", ["x"])) == "sd15"


def test_text_model_auto(tmp_path, monkeypatch):
    from joeai import hardware
    from joeai.services import ServiceManager
    fo = FakeOllama()
    s = Settings()
    s.ollama.url = fo.url
    assert s.ollama.text_model == ""                         # nothing tuned to one PC
    monkeypatch.setattr(hardware, "vram_total_gb", lambda: 12.0)
    assert doctor.resolve_text_model(s, ServiceManager(s), lambda m: None) == "qwen3:14b"   # what's installed
    fo.close()
