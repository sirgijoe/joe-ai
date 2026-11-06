"""dev123 (batch 3): new model families - FLUX.2 klein, sketch to picture and illusions
(ControlNet), restyle a video (Wan Fun Control 5B), picture to 3D (Hunyuan3D 2.1)."""
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from joeai import comfy, makers, picturetools as pt
from joeai.config import Settings
from joeai.mission import parse
from joeai.sandbox import Sandbox
from joeai.tools import TOOLS, needs_problem, tool_status

FF = shutil.which("ffmpeg")
needs_ff = pytest.mark.skipif(not FF, reason="needs FFmpeg")


def _links_ok(g: dict) -> None:
    """Every link points at a node that exists (what ComfyUI checks first)."""
    for nid, node in g.items():
        assert "class_type" in node, nid
        for k, v in node["inputs"].items():
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str):
                assert v[0] in g, f"{nid}.{k} -> missing node {v[0]}"


def _job(text):
    return parse("TASK: T\n" + text).jobs[0]


def _engine(tmp_path):
    s = Settings()
    s.comfy.ffmpeg = FF or ""
    sb = Sandbox(tmp_path / "ws").ensure()
    logs = []
    return SimpleNamespace(s=s, sb=sb, log=logs.append, logs=logs)


def _models(tmp_path, monkeypatch, sdxl=True):
    m = tmp_path / "models"
    (m / "checkpoints").mkdir(parents=True)
    if sdxl:
        (m / "checkpoints" / "juggernautXL_v9.safetensors").write_bytes(b"0")
        (m / "checkpoints" / "animagineXL_v3.safetensors").write_bytes(b"0")
    (m / "checkpoints" / "hunyuan_3d_v2.1.safetensors").write_bytes(b"0")
    import joeai.doctor as doctor
    monkeypatch.setattr(doctor, "comfy_models_dir", lambda s: m)
    return m


# --------------------------------------------------------------------------- packs
def test_new_packs_and_tools():
    for pid in ("flux2", "sketch", "illusion", "video-restyle", "3d"):
        p = pt.PACKS[pid]
        assert p.license and p.size_gb > 0 and all(f[2].startswith(pt.HF) for f in p.files)
    for tid in makers.TOOLS:
        assert TOOLS[tid].ready and TOOLS[tid].plan_hint and pt.TOOL_PACKS[tid]
        assert tid in pt.COMFY_TOOLS
    assert "EU" in TOOLS["make-3d"].help or "European Union" in TOOLS["make-3d"].help
    assert ".mp4" in TOOLS["restyle-video"].accepts and ".png" in TOOLS["restyle-video"].accepts


def test_shared_files_make_the_offer_smaller(tmp_path):
    m = tmp_path / "models"
    assert "about 18 GB" in pt.pack_offer("video-restyle")
    for folder, name, *_ in pt.PACKS["video"].files:            # Joe's video model is installed
        (m / folder).mkdir(parents=True, exist_ok=True)
        (m / folder / name).write_bytes(b"0")
    assert pt.pack_size("video-restyle", m) == 10.0
    assert "about 10 GB" in pt.pack_offer("video-restyle", m) and "about 10 GB" in pt.pack_short("video-restyle", m)
    assert pt.pack_size("3d", m) == pt.PACKS["3d"].size_gb


def test_3d_outputs_are_collected():
    entry = {"outputs": {"9": {"3d": [{"filename": "a_00001_.glb", "subfolder": "Joe", "type": "output"}]}}}
    assert [f["filename"] for f in pt.outputs_of(entry)] == ["a_00001_.glb"]


# --------------------------------------------------------------------------- FLUX.2 klein
def test_flux2_graph_and_fill():
    g = comfy.flux2_graph()
    _links_ok(g)
    f = comfy.fill(g, "a red barn", "ignored", 77, 1216, 832, "", prefix="Joe/x")
    assert f["73"]["inputs"]["noise_seed"] == 77 and f["66"]["inputs"]["width"] == 1216
    assert f["62"]["inputs"]["height"] == 832 and f["74"]["inputs"]["text"] == "a red barn"
    assert f["70"]["inputs"]["unet_name"] == pt.PACKS["flux2"].files[0][1]
    assert f["71"]["inputs"]["clip_name"] == pt.PACKS["flux2"].files[1][1]
    assert f["72"]["inputs"]["vae_name"] == pt.PACKS["flux2"].files[2][1]
    assert f["9"]["inputs"]["filename_prefix"] == "Joe/x"


def test_flux2_family_and_tool_models_hidden(tmp_path):
    assert comfy.family_of("flux-2-klein-4b.safetensors") == "flux2"
    assert comfy.family_of("flux1-dev.safetensors") == "flux"
    m = tmp_path / "models"
    (m / "checkpoints").mkdir(parents=True)
    (m / "diffusion_models").mkdir()
    for n in ("hunyuan_3d_v2.1.safetensors", "ace_step_1.5_turbo_aio.safetensors", "sd_xl_base_1.0.safetensors"):
        (m / "checkpoints" / n).write_bytes(b"0")
    for n in ("wan2.2_fun_control_5B_bf16.safetensors", "flux-2-klein-4b.safetensors"):
        (m / "diffusion_models" / n).write_bytes(b"0")
    names = {x.name: x.family for x in comfy.scan_models(m)}
    assert set(names) == {"sd_xl_base_1.0.safetensors", "flux-2-klein-4b.safetensors"}
    assert names["flux-2-klein-4b.safetensors"] == "flux2"


def test_words_in_picture():
    yes = ("a shop sign that says OPEN", "poster with the title Summer Fair", "bold lettering on a mug",
           "a banner with the words Happy Birthday", "a sign which reads FRESH EGGS")
    no = ("a cat on a sofa", "a forest at dawn", "a sign of the times", "my mascot waving")
    assert all(comfy.WORDS_IN_PICTURE.search(t) for t in yes)
    assert not any(comfy.WORDS_IN_PICTURE.search(t) for t in no)


def test_use_flux2_rules(monkeypatch, tmp_path):
    from joeai import engine as engine_mod
    import joeai.doctor as doctor
    ready = {"v": True}
    monkeypatch.setattr(doctor, "comfy_models_dir", lambda s: tmp_path)
    monkeypatch.setattr(pt, "pack_ready", lambda m, p: ready["v"] and p == "flux2")
    me = SimpleNamespace(s=Settings())
    use = lambda job, basic=("x",), wpref=None: engine_mod.Engine._use_flux2(me, job, list(basic), wpref or {})  # noqa: E731
    assert use(_job("TYPE: image\nFORMAT: a bakery sign that says FRESH BREAD"))[0]
    assert not use(_job("TYPE: image\nFORMAT: a loaf of bread on a table"))[0]
    assert use(_job("TYPE: image\nFORMAT: bread"), basic=())[0]                     # no SD model at all
    assert use(_job("TYPE: image\nMODEL: flux2\nFORMAT: bread"))[0]
    assert not use(_job("TYPE: image\nMODEL: juggernaut\nFORMAT: a sign that says HI"))[0]
    assert use(_job("TYPE: image\nFORMAT: bread"), wpref={"model": "flux-2-klein-4b.safetensors"})[0]
    assert not use(_job("TYPE: video\nFORMAT: a sign that says HI"))[0]
    ready["v"] = False
    assert not use(_job("TYPE: image\nFORMAT: a sign that says HI"))[0]


# --------------------------------------------------------------------------- graphs
def test_controlnet_graph():
    g = makers.controlnet_graph("x.safetensors", "s.png", "a dragon", "bad", 5, "cn.safetensors", 0.9, 0.8,
                                invert=True, union_type="hed/pidi/scribble/ted")
    _links_ok(g)
    assert g["12"]["inputs"]["image"] == ["3", 0] and g["12"]["inputs"]["control_net"] == ["11", 0]
    assert g["5"]["inputs"]["positive"] == ["12", 0] and g["5"]["inputs"]["latent_image"] == ["13", 0]
    g = makers.controlnet_graph("x", "s.png", "p", "n", 5, "qr.safetensors", 1.2, 0.9)
    _links_ok(g)
    assert "3" not in g and "11" not in g and g["12"]["inputs"]["control_net"] == ["10", 0]


def test_restyle_video_graph():
    g = makers.restyle_video_graph("v.mp4", "anime", "bad", 3, 1280, 704, 121, ref_image="look.png")
    _links_ok(g)
    assert g["60"]["inputs"]["control_video"] == ["68", 0] and g["60"]["inputs"]["ref_image"] == ["70", 0]
    assert g["37"]["inputs"]["unet_name"] == "wan2.2_fun_control_5B_bf16.safetensors"
    assert g["66"]["inputs"]["file"] == "v.mp4" and g["60"]["inputs"]["length"] == 121
    assert "70" not in makers.restyle_video_graph("v.mp4", "a", "b", 3, 960, 544, 45)


def test_model3d_graph():
    g = makers.model3d_graph("p.png", "hunyuan_3d_v2.1.safetensors", 1)
    _links_ok(g)
    assert g["9"]["class_type"] == "SaveGLB" and g["32"]["inputs"]["image"] == ["2", 0]
    g = makers.model3d_graph("p.png", "h", 1, cut_out=True)
    _links_ok(g)
    assert g["32"]["inputs"]["image"] == ["23", 0] and g["22"]["inputs"]["color"] == 0xFFFFFF


def test_wan_length_and_words():
    assert makers.wan_length(121) == 121 and makers.wan_length(200) == 121
    assert makers.wan_length(48) == 45 and makers.wan_length(3) == 0
    assert makers.word_from("a forest\nword: JOE's!") == ("a forest", "JOEs!")
    assert makers.word_from("just a scene") == ("just a scene", "")
    assert makers.word_from("a cozy village word: JOE") == ("a cozy village", "JOE")      # Tools form: one line
    assert makers.word_from("a sword fight") == ("a sword fight", "")
    assert makers.safe_word("a'b:c\\d%e") == "abcde"


# --------------------------------------------------------------------------- planning (with FFmpeg)
@needs_ff
def test_plan_sketch_and_illusion(tmp_path, monkeypatch):
    _models(tmp_path, monkeypatch)
    eng = _engine(tmp_path)
    paper = tmp_path / "sketch.png"
    subprocess.run([FF, "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=white:s=320x240", "-vf",
                    "drawbox=x=40:y=40:w=200:h=120:color=black:t=4", "-frames:v", "1", str(paper)], check=True)
    items, keys, why = makers.plan_items(eng, _job("TYPE: sketch-to-picture\nINPUT: sketch.png\n"
                                                   "OPTIONS: look anime, lines clean\nFORMAT: a house"),
                                         "sketch-to-picture", [paper])
    assert not why and len(items) == 1 and items[0]["invert"] is True
    assert items[0]["ckpt"] == "animagineXL_v3.safetensors"              # anime look -> anime model
    assert items[0]["union"].startswith("canny/lineart")
    items, keys, why = makers.plan_items(eng, _job("TYPE: illusion-art\nOPTIONS: versions 4\nFORMAT: a village"),
                                         "illusion-art", [])
    assert not why and len(items) == 4 and items[0]["src"].exists() and len(set(keys)) == 4
    items, keys, why = makers.plan_items(eng, _job("TYPE: illusion-art\nFORMAT: clouds\nword: JOE"),
                                         "illusion-art", [])
    assert not why and len(items) == 2 and "JOE" in items[0]["label"]
    assert makers.mean_gray(FF, items[0]["src"]) > 2                    # the word was drawn
    _, _, why = makers.plan_items(eng, _job("TYPE: illusion-art\nOPTIONS: hidden word\nFORMAT: clouds"),
                                  "illusion-art", [])
    assert "word:" in why


@needs_ff
def test_controlnet_tools_need_sdxl(tmp_path, monkeypatch):
    m = _models(tmp_path, monkeypatch, sdxl=False)
    eng = _engine(tmp_path)
    _, _, why = makers.plan_items(eng, _job("TYPE: sketch-to-picture\nINPUT: a.png"), "sketch-to-picture",
                                  [tmp_path / "a.png"])
    assert "SDXL" in why
    for p in pt.PACKS["sketch"].files:
        (m / p[0]).mkdir(parents=True, exist_ok=True)
        (m / p[0] / p[1]).write_bytes(b"0")
    msg = needs_problem(eng.s, _job("TYPE: sketch-to-picture\nINPUT: a.png"))
    assert "SDXL" in msg
    st = {x["id"]: x for x in tool_status({"comfy": True, "sdxl": False, "ffmpeg": True,
                                           "packs": {"sketch": {"ready": True}}})}
    assert "SDXL" in st["sketch-to-picture"]["why"] and st["make-3d"]["why"]


@needs_ff
def test_plan_restyle_video_and_finish(tmp_path, monkeypatch):
    eng = _engine(tmp_path)
    vid = tmp_path / "dance.mp4"
    subprocess.run([FF, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30:duration=7",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=7", "-shortest", "-pix_fmt", "yuv420p",
                    str(vid)], check=True)
    items, keys, why = makers.plan_items(eng, _job("TYPE: restyle-video\nINPUT: dance.mp4\n"
                                                   "OPTIONS: style watercolor, length 10"), "restyle-video", [vid])
    assert not why and [i["part"] for i in items] == [1, 2]
    assert items[0]["length"] == 121 and 41 <= items[1]["length"] <= 49 and items[0]["size"] == (960, 544) \
        or items[0]["size"] == (1280, 704)
    assert "watercolor" in items[0]["prompt"] and items[0]["ref"] is None
    one, *_ = makers.plan_items(eng, _job("TYPE: restyle-video\nINPUT: dance.mp4"), "restyle-video", [vid])
    assert len(one) == 1 and any("first 5 s" in x for x in eng.logs)
    # each piece gets its sound back, then the pieces are joined
    folder = tmp_path / "out"
    folder.mkdir()
    made = []
    for it in items:
        shutil.copy(it["src"], folder / f"{it['stem']}.mp4")
        made += makers.after(eng, None, "restyle-video", it, folder, [f"{it['stem']}.mp4"])
    probe = subprocess.run([FF, "-hide_banner", "-i", str(folder / made[0])], capture_output=True, text=True)
    assert "Audio:" in probe.stderr
    st = SimpleNamespace(media_files=list(made))
    makers.finish(eng, None, "restyle-video", folder, st)
    assert st.media_files == ["dance-restyled.mp4"] and (folder / "dance-restyled.mp4").exists()
    assert not list(folder.glob("*part*"))
    assert 6.0 < makers.duration_s(FF, folder / "dance-restyled.mp4") < 7.5


@needs_ff
def test_plan_make_3d_pads_to_square(tmp_path, monkeypatch):
    eng = _engine(tmp_path)
    pic = tmp_path / "mug.png"
    subprocess.run([FF, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=400x200", "-frames:v", "1",
                    str(pic)], check=True)
    items, keys, why = makers.plan_items(eng, _job("TYPE: make-3d\nINPUT: mug.png"), "make-3d", [pic])
    from joeai import media
    assert not why and media.size_of(FF, items[0]["src"]) == (400, 400) and items[0]["stem"] == "mug-3d"


def test_plain_summary_batch3():
    from joeai.describe import plain_summary
    jobs = [{"name": "S", "type": "sketch-to-picture", "files": 2, "options": ["look anime"], "format": "x"},
            {"name": "I", "type": "illusion-art", "files": 0, "options": ["versions 4", "hidden word"], "format": ""},
            {"name": "3", "type": "make-3d", "files": 1, "options": [], "format": ""},
            {"name": "V", "type": "restyle-video", "files": 1, "options": ["length 10"], "format": ""}]
    out = plain_summary({"jobs": jobs})
    assert "anime" in out[0] and out[1].startswith("4 hidden") and "a word" in out[1]
    assert ".glb" in out[2] and "anime" in out[3] and "10 s" in out[3]


def test_doctor_kinds_and_workflows():
    from joeai.doctor import model_kind
    from joeai import workflowprefs as wfp
    assert model_kind("pack-flux2") == "pictures" and model_kind("pack-video-restyle") == "video"
    assert model_kind("pack-3d") == "tools" and model_kind("pack-sketch") == "tools"
    assert "controlnet" in wfp.BUILTIN and "restyle-video" in wfp.BUILTIN


def test_illusion_needs_no_input_and_form_mission():
    from joeai.tools import mission_for, catalog
    text = mission_for("illusion-art", [], ["hidden word", "versions 1"], "", "a forest\nword: JOE")
    j = parse(text).jobs[0]
    assert j.type == "illusion-art" and not j.inputs and makers.word_from(j.format)[1] == "JOE"
    cat = {t["id"]: t for t in catalog()}
    assert cat["illusion-art"]["no_input"] and not cat["make-3d"]["no_input"]


# --------------------------------------------------------------------------- end to end (fake ComfyUI)
BATCH3_NODES = {"CheckpointLoaderSimple", "CLIPTextEncode", "LoadImage", "ImageScaleToTotalPixels", "ImageInvert",
                "ControlNetLoader", "SetUnionControlNetType", "ControlNetApplyAdvanced", "VAEEncode", "KSampler",
                "VAEDecode", "SaveImage", "ImageScale", "ImageOnlyCheckpointLoader", "ModelSamplingAuraFlow",
                "CLIPVisionEncode", "Hunyuan3Dv2Conditioning", "EmptyLatentHunyuan3Dv2", "VAEDecodeHunyuan3D",
                "VoxelToMesh", "SaveGLB", "LoadBackgroundRemovalModel", "RemoveBackground", "EmptyImage",
                "ImageCompositeMasked", "UNETLoader", "CLIPLoader", "VAELoader", "ConditioningZeroOut",
                "EmptyFlux2LatentImage", "Flux2Scheduler", "KSamplerSelect", "RandomNoise", "CFGGuider",
                "SamplerCustomAdvanced", "ModelSamplingSD3", "LoadVideo", "GetVideoComponents", "Canny",
                "Wan22FunControlToVideo", "CreateVideo", "SaveVideo"}


def test_restyle_graph_uses_only_known_nodes():
    for g in (makers.restyle_video_graph("v.mp4", "a", "b", 1, 960, 544, 121, ref_image="r.png"),
              makers.model3d_graph("p.png", "h", 1, cut_out=True),
              makers.controlnet_graph("c", "i", "p", "n", 1, "cn", 1, 1, invert=True, union_type="auto"),
              comfy.flux2_graph()):
        assert {n["class_type"] for n in g.values()} <= BATCH3_NODES


def test_run_sketch_3d_and_flux2_pictures(tmp_path, monkeypatch):
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from test_picturetools import png, run, studio as _studio  # noqa: F401
    gen = _studio.__wrapped__(tmp_path, monkeypatch)
    app, fake, models = next(gen)
    try:
        (models / "checkpoints" / "SDXL").mkdir(parents=True, exist_ok=True)
        (models / "checkpoints" / "SDXL" / "example_sdxl_model.safetensors").write_bytes(b"x")
        png(app.sb.inbox / "drawing.png")
        chk, st = run(app, "TASK: Sketch  TYPE: sketch-to-picture\nINPUT: drawing.png\nOPTIONS: follow close\n"
                           "FORMAT: a castle on a hill")
        assert st.status == "done", st.note
        g = fake.graphs[-1]
        assert g["4"]["inputs"]["ckpt_name"] == "SDXL\\example_sdxl_model.safetensors"
        assert g["10"]["inputs"]["control_net_name"] == pt.PACKS["sketch"].files[0][1]
        assert g["12"]["inputs"]["strength"] == makers.FOLLOW["close"][0] and "castle" in g["6"]["inputs"]["text"]
        chk, st = run(app, "TASK: Mug 3D  TYPE: make-3d\nINPUT: drawing.png")
        assert st.status == "done", st.note
        assert any(f.endswith(".glb") for f in st.media_files)
        g = fake.graphs[-1]
        assert g["9"]["class_type"] == "SaveGLB" and "21" in g             # background cut out first
        out = app.sb.output / st.output
        assert "Hunyuan" in (out / "about.txt").read_text()
        chk, st = run(app, "TASK: Sign  TYPE: image\nPROMPTS: as written\n"
                           "PART: a bakery sign that says FRESH BREAD\nFORMAT: a bakery sign that says FRESH BREAD")
        assert st.status == "done", st.note
        g = fake.graphs[-1]
        assert "Flux2Scheduler" in {n["class_type"] for n in g.values()}
        assert g["66"]["inputs"]["width"] % 16 == 0
    finally:
        try:
            next(gen)
        except StopIteration:
            pass
