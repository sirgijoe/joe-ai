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
    assert doctor.recommended_download(12)["name"] == "gemma4:12b"


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
    # Real SDXL / SD1.5 checkpoints also hold "transformer_blocks.0.attn1.to_q" (their UNet attention):
    # they must not be mistaken for video models.
    unet = "model.diffusion_model.input_blocks.4.1.transformer_blocks.0.attn1.to_q.weight"
    assert comfy.family_of("f.safetensors", 0, st("f.safetensors", [unet, "conditioner.embedders.1.model.x"])) == "sdxl"
    assert comfy.family_of("g.safetensors", 0, st("g.safetensors", [unet, "cond_stage_model.transformer.x"])) == "sd15"
    assert comfy.family_of("h.safetensors", 0, st("h.safetensors", [unet])) != "video"
    assert comfy.family_of("i.safetensors", 0, st("i.safetensors", ["patch_embedding.weight", "blocks.0.self_attn.q.weight"])) == "video"
    assert comfy.family_of("j.safetensors", 0, st("j.safetensors", ["scale_shift_table", "transformer_blocks.0.attn1.to_q.weight"])) == "video"
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


def test_builtin_video_wan(env, tmp_path):
    s, sb, fo, fc = env
    mdir = tmp_path / "models"
    s.comfy.models_dir = str(mdir)
    m = parse("TASK: Kiln clip  SAVE: clips/kiln.mp4  CHUNKS: 1 x 1")
    assert m.jobs[0].type == "video"
    st = Engine(s, sb, log=lambda x: None).run_mission(m)[0]
    assert st.status == "failed" and "System check" in st.note          # model not installed yet
    for folder, name, _ in comfy.WAN_VIDEO["files"]:
        (mdir / folder).mkdir(parents=True, exist_ok=True)
        (mdir / folder / name).write_bytes(b"x")
    assert comfy.wan_missing(mdir) == []
    fc.video = True
    m = parse("TASK: Kiln clip 2  SAVE: clips/kiln2.mp4  CHUNKS: 1 x 1")
    st = Engine(s, sb, log=lambda x: None).run_mission(m)[0]
    assert st.status == "done", st.note
    g = fc.graphs[-1]
    assert g["55"]["inputs"]["width"] == 1280 and g["55"]["inputs"]["length"] == 121
    assert g["57"]["inputs"]["fps"] == 24.0 and "{{" not in json.dumps(g)
    assert g["7"]["inputs"]["text"].startswith("色调艳丽")               # Wan's own negative prompt
    mp4s = list((sb.output / "clips" / "kiln2").glob("*.mp4"))
    assert len(mp4s) == 1 and mp4s[0].read_bytes()[4:8] == b"ftyp"
    # Setup > Quality: Turbo add-on installed + Low video = short, small, 4-step clip with the LoRA
    folder, name, _ = comfy.WAN_TURBO["file"]
    (mdir / folder).mkdir(parents=True, exist_ok=True)
    (mdir / folder / name).write_bytes(b"x")
    s.quality.video = "low"
    st = Engine(s, sb, log=lambda x: None).run_mission(parse("TASK: Kiln clip 3  SAVE: clips/k3.mp4  CHUNKS: 1 x 1"))[0]
    assert st.status == "done", st.note
    g = fc.graphs[-1]
    assert g["60"]["inputs"]["lora_name"] == name and g["3"]["inputs"]["steps"] == 4
    assert g["55"]["inputs"]["width"] == 960 and g["55"]["inputs"]["length"] == 73
    s.quality.video = "high"
    Engine(s, sb, log=lambda x: None).run_mission(parse("TASK: Kiln clip 4  SAVE: clips/k4.mp4  CHUNKS: 1 x 1"))
    g = fc.graphs[-1]
    assert "60" not in g and g["3"]["inputs"]["steps"] == 30 and g["55"]["inputs"]["width"] == 1280


def test_picture_quality_low_and_high(env):
    s, sb, fo, fc = env
    s.quality.pictures = "low"
    Engine(s, sb, log=lambda x: None).run_mission(parse(IMG))
    g = fc.graphs[-1]
    assert g["3"]["inputs"]["steps"] == 14 and g["5"]["inputs"]["width"] == 768
    s.quality.pictures = "high"
    Engine(s, sb, log=lambda x: None).run_mission(parse(IMG.replace("art/mood", "art/mood2")))
    g = fc.graphs[-1]
    assert g["3"]["inputs"]["steps"] == 40 and g["5"]["inputs"]["width"] == 1024


def test_doctor_offers_video_model(env, tmp_path, monkeypatch):
    s, sb, fo, fc = env
    (tmp_path / "models" / "checkpoints").mkdir(parents=True)
    s.comfy.models_dir = str(tmp_path / "models")
    from joeai import hardware
    from joeai.services import ServiceManager
    monkeypatch.setattr(hardware, "gpu", lambda: {"name": "Test GPU", "vendor": "nvidia"})
    monkeypatch.setattr(hardware, "vram_total_gb", lambda: 12.0)
    d = doctor.check(s, ServiceManager(s))
    assert any(i["action"] == "download-video-model" for i in d["issues"])
    with pytest.raises(PermissionError):
        doctor.download_video_model(s, print)


def test_check_video_needs_model_not_workflow(env, tmp_path):
    from joeai.server import App
    s, sb, fo, fc = env
    s.comfy.models_dir = str(tmp_path / "models")
    (tmp_path / "models").mkdir()
    app = App(s)
    r = app.check("TASK: Clip  SAVE: clips/a.mp4")
    assert not r["ok"] and "System check" in r["error"]
    for folder, name, _ in comfy.WAN_VIDEO["files"]:
        (tmp_path / "models" / folder).mkdir(exist_ok=True)
        (tmp_path / "models" / folder / name).write_bytes(b"x")
    assert app.check("TASK: Clip  SAVE: clips/a.mp4")["ok"]


def test_fine_tuning_reaches_the_picture_graph(env):
    """Setup > Workflows fine-tuning (showcase QC 2026-11-09): prompt strength, sampler, detail
    pass off/strength and versions per prompt."""
    from joeai import workflowprefs as wfp
    s, sb, fo, fc = env
    s.quality.pictures = "high"
    assert wfp.save(s, "pictures", {"cfg": 4.5, "sampler": "euler", "hires": "off", "versions": 3})["ok"]
    m = parse("TASK: Neon  SAVE: art/neon  TYPE: image  CHUNKS: 1 x 1")
    logs = []
    st = Engine(s, sb, log=logs.append).run_mission(m)[0]
    assert st.status == "done", st.note
    g = fc.graphs[-1]
    assert g["3"]["inputs"]["cfg"] == 4.5 and g["3"]["inputs"]["sampler_name"] == "euler"
    assert "12" not in g                                          # detail pass turned off on High
    assert st.items == 3 and any("prompt strength 4.5" in x for x in logs)
    assert wfp.save(s, "pictures", {"hires": "on", "denoise": 0.25})["ok"]
    s.quality.pictures = "medium"
    Engine(s, sb, log=lambda x: None).run_mission(parse("TASK: Neon2  SAVE: art/neon2  TYPE: image  CHUNKS: 1 x 1"))
    g = fc.graphs[-1]
    assert g["12"]["inputs"]["denoise"] == 0.25                   # detail pass forced on, gentler


def test_picture_book_gets_one_picture_per_page(env):
    import shutil
    s, sb, fo, fc = env
    if not shutil.which("pandoc"):
        pytest.skip("no pandoc")
    s.pandoc = shutil.which("pandoc")
    m = parse("TASK: Kids picture book  SAVE: robot.md  EXPORT: html  TEMPLATE: kids\n"
              "PART: ## The Robot Wakes. The robot wakes up, about 50 words.\n"
              "PART: ## The Robot Helps. It helps a friend, about 50 words.\n"
              "TASK: Robot pictures  SAVE: robot-pictures  TYPE: image  FROM: Kids picture book  CHUNKS: 1 x 2")
    logs = []
    book, pics = Engine(s, sb, log=logs.append).run_mission(m)
    assert pics.status == "done", pics.note
    html = (sb.output / "robot.html").read_text(encoding="utf-8")
    assert html.count("<img") == 2 and any("picture(s) put on its pages" in x for x in logs)


def test_video_fine_tuning(env, tmp_path):
    from joeai import workflowprefs as wfp
    s, sb, fo, fc = env
    mdir = tmp_path / "models"
    s.comfy.models_dir = str(mdir)
    for folder, name, _ in comfy.WAN_VIDEO["files"]:
        (mdir / folder).mkdir(parents=True, exist_ok=True)
        (mdir / folder / name).write_bytes(b"x")
    fc.video = True
    s.quality.video = "high"                                     # never Turbo: CFG is used
    assert wfp.save(s, "video", {"cfg": 7, "motion": "high"})["ok"]
    st = Engine(s, sb, log=lambda x: None).run_mission(parse("TASK: Waves  SAVE: clips/w.mp4  CHUNKS: 1 x 1"))[0]
    assert st.status == "done", st.note
    g = fc.graphs[-1]
    assert g["3"]["inputs"]["cfg"] == 7 and "dynamic camera motion" in g["6"]["inputs"]["text"]


def test_joe_recommends_a_better_model_that_fits(env, monkeypatch):
    """FLUX.2 klein isn't installed, a picture has words in it: a tip in the log (only when the
    card is big enough), remembered so System check puts the offer first."""
    from joeai import hardware, suggest
    s, sb, fo, fc = env
    monkeypatch.setattr(hardware, "vram_total_gb", lambda: 4.0)
    logs = []
    Engine(s, sb, log=logs.append).run_mission(parse("TASK: Sign  SAVE: art/sign  TYPE: image  CHUNKS: 1 x 1\n"
                                                     "FORMAT: a bakery sign that says OPEN"))
    assert not any("Tip:" in x and "FLUX" in x for x in logs) and not suggest.pending(sb)   # 4 GB: too small
    monkeypatch.setattr(hardware, "vram_total_gb", lambda: 12.0)
    logs = []
    Engine(s, sb, log=logs.append).run_mission(parse("TASK: Sign2  SAVE: art/sign2  TYPE: image  CHUNKS: 1 x 2\n"
                                                     "FORMAT: a bakery sign that says OPEN"))
    tips = [x for x in logs if "Tip:" in x and "FLUX" in x]
    assert len(tips) == 1 and "FLUX.2" in tips[0] and "12 GB" in tips[0]
    assert "pack:flux2" in suggest.pending(sb)
    issues = [{"id": "x", "text": "a problem"},
              {"id": "pack-bg", "pack": "bg", "optional": True, "text": "For Remove background: ..."},
              {"id": "pack-flux2", "pack": "flux2", "optional": True, "text": "For better hands: ..."},
              {"id": "pack-edit", "pack": "edit", "optional": True, "text": "For Edit a picture: ..."}]
    out = suggest.mark(issues, sb, 8.0)
    assert [i["id"] for i in out] == ["x", "pack-flux2", "pack-bg", "pack-edit"]
    assert out[1]["text"].startswith("RECOMMENDED for what you make (words in the picture")
    assert "this PC has 8 GB" in out[3]["text"]                                 # the editor wants 12 GB
