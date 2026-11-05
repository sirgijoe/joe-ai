"""The five ComfyUI tools, with a fake ComfyUI: graphs use only built-in nodes, files land in
the task folder, missing models are explained, music needs no INPUT."""
import struct
import sys
from pathlib import Path

import pytest

from joeai import addons, describe, picturetools, tools
from joeai.config import Settings
from joeai.engine import Engine
from joeai.mission import MissionError, parse
from joeai.server import App

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from fake_comfy import FakeComfy  # noqa: E402
from fake_ollama import FakeOllama  # noqa: E402

BUILT_IN = {"LoadImage", "SaveImage", "UpscaleModelLoader", "ImageUpscaleWithModel", "ImageScaleBy",
            "LoadBackgroundRemovalModel", "RemoveBackground", "InvertMask", "JoinImageWithAlpha",
            "FluxKontextImageScale", "ImageScaleToTotalPixels", "UNETLoader", "CLIPLoader", "VAELoader", "ModelSamplingAuraFlow",
            "CFGNorm", "TextEncodeQwenImageEditPlus", "FluxKontextMultiReferenceLatentMethod",
            "VAEEncode", "KSampler", "VAEDecode", "LoraLoaderModelOnly", "ModelSamplingSD3",
            "CLIPTextEncode", "Wan22ImageToVideoLatent", "CreateVideo", "SaveVideo",
            "CheckpointLoaderSimple", "TextEncodeAceStepAudio1.5", "ConditioningZeroOut",
            "EmptyAceStep1.5LatentAudio", "VAEDecodeAudio", "SaveAudioMP3", "EmptyLatentAudio"}


def png(path: Path, w=1600, h=900) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", w, h) + b"\0" * 20)
    return path


@pytest.fixture
def studio(tmp_path, monkeypatch):
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "settings.json"))
    monkeypatch.setenv("JOE_ADDONS", str(tmp_path / "addons"))
    oll, comfy = FakeOllama(), FakeComfy()
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    s.ollama.url = oll.url
    s.comfy.url = comfy.url
    s.engine.retry_backoff_s = 0
    s.engine.gpu_temp_pause_c = 0
    s.engine.keep_awake = False
    models = tmp_path / "models"
    for p in picturetools.PACKS.values():                      # every pack "downloaded"
        for folder, name, _, _ in p.files:
            (models / folder).mkdir(parents=True, exist_ok=True)
            (models / folder / name).write_bytes(b"x")
    import joeai.doctor as doctor
    monkeypatch.setattr(doctor, "comfy_models_dir", lambda settings: models)
    monkeypatch.setattr(doctor, "ffmpeg_exe", lambda configured="": None)
    a = App(settings=s)
    monkeypatch.setattr(a.services, "handoff", lambda kind: True)
    yield a, comfy, models
    comfy.close()
    oll.close()


def run(app, text):
    chk = app.check(text)
    assert chk["ok"], chk
    st = Engine(app.settings, app.sb, log=lambda x: None, services=app.services).run_mission(parse(text))[0]
    return chk, st


def classes(g):
    return {n["class_type"] for n in g.values()}


def test_all_five_are_ready_and_use_only_built_in_nodes(studio):
    app, comfy, _ = studio
    for tid in picturetools.COMFY_TOOLS:
        assert tools.TOOLS[tid].ready
    png(app.sb.inbox / "mug.png")
    for text in ("TASK: Cut  TYPE: remove-bg\nINPUT: mug.png\nOPTIONS: background transparent, upscale 2x",
                 "TASK: Edit  TYPE: edit-picture\nINPUT: mug.png\nFORMAT: put it on a marble counter",
                 "TASK: Old  TYPE: restore-photo\nINPUT: mug.png\nOPTIONS: colorize, upscale 2x",
                 "TASK: Move  TYPE: animate-photo\nINPUT: mug.png\nFORMAT: steam rising",
                 "TASK: Tunes  TYPE: music\nOPTIONS: kind music, length 30\nFORMAT: calm guitar | upbeat ukulele",
                 "TASK: Bangs  TYPE: music\nOPTIONS: kind sfx, length 10\nFORMAT: a door creak"):
        chk, st = run(app, text)
        assert st.status == "done", (text, st.note)
    for g in comfy.graphs:
        assert classes(g) <= BUILT_IN, classes(g) - BUILT_IN
    assert len(comfy.uploads) == 4                              # one per picture task


def test_files_land_in_the_task_folder_with_clear_names(studio):
    app, comfy, _ = studio
    png(app.sb.inbox / "shots" / "blue mug.png")
    png(app.sb.inbox / "shots" / "red bowl.png")
    _, st = run(app, "TASK: Shop cutouts  TYPE: remove-bg\nINPUT: shots\nOPTIONS: background transparent, upscale none")
    out = app.sb.output / st.output
    assert sorted(p.name for p in out.iterdir()) == ["about.txt", "blue-mug-cutout.png", "red-bowl-cutout.png"]
    assert "BiRefNet" in (out / "about.txt").read_text(encoding="utf-8")
    _, st = run(app, "TASK: Tunes  TYPE: music\nOPTIONS: kind music, length 60\nFORMAT: calm guitar | lofi beat")
    names = sorted(p.name for p in (app.sb.output / st.output).iterdir())
    assert names == ["01-calm-guitar.mp3", "02-lofi-beat.mp3", "about.txt"]
    music = [g for g in comfy.graphs if "TextEncodeAceStepAudio1.5" in classes(g)][-1]
    assert music["94"]["inputs"]["duration"] == 60.0 and music["94"]["inputs"]["lyrics"] == "[Instrumental]"


def test_animate_matches_the_photo_shape(studio):
    app, comfy, _ = studio
    png(app.sb.inbox / "tall.png", 900, 1600)
    run(app, "TASK: Move  TYPE: animate-photo\nINPUT: tall.png")
    g = comfy.graphs[-1]
    assert (g["55"]["inputs"]["width"], g["55"]["inputs"]["height"]) == (704, 1280)
    assert g["55"]["inputs"]["start_image"] == ["56", 0]
    assert picturetools.picture_size(app.sb.inbox / "tall.png") == (900, 1600)


def test_restore_and_edit_prompts(studio):
    app, comfy, _ = studio
    png(app.sb.inbox / "nana.png")
    run(app, "TASK: Old  TYPE: restore-photo\nINPUT: nana.png\nOPTIONS: upscale none")
    p = comfy.graphs[-1]["151"]["inputs"]["prompt"]
    assert "scratches" in p and "black and white" in p
    assert comfy.graphs[-1]["169"]["inputs"]["steps"] == 4                # Lightning add-on
    app.settings.quality.pictures = "high"
    run(app, "TASK: Old2  TYPE: restore-photo\nINPUT: nana.png\nOPTIONS: colorize, upscale none")
    g = comfy.graphs[-1]
    assert "colorize" in g["151"]["inputs"]["prompt"] and g["169"]["inputs"]["steps"] == 40


def test_missing_model_is_explained_and_offered(studio, monkeypatch):
    app, _, models = studio
    (models / "background_removal" / "birefnet.safetensors").unlink()
    png(app.sb.inbox / "a.png")
    text = "TASK: Cut  TYPE: remove-bg\nINPUT: a.png"
    msg = tools.needs_problem(app.settings, parse(text).jobs[0])
    assert "BiRefNet" in msg and "MIT" in msg and "DOWNLOAD" in msg
    st = Engine(app.settings, app.sb, log=lambda x: None, services=app.services).run_mission(parse(text))[0]
    assert st.status == "failed" and "BiRefNet" in st.note


def test_mission_rules(studio):
    app, _, _ = studio
    with pytest.raises(MissionError):
        parse("TASK: Edit  TYPE: remove-bg")                      # pictures need INPUT
    with pytest.raises(MissionError):
        parse("TASK: Tunes  TYPE: music")                         # music needs a description
    m = parse(tools.mission_for("music", [], ["kind sfx"], "Bangs", "door creak\ndoorbell"))
    assert picturetools.pieces_from(m.jobs[0].format) == ["door creak", "doorbell"]
    chk = app.check(tools.mission_for("music", [], ["kind sfx", "length 10"], "Bangs", "door creak\ndoorbell"))
    assert chk["ok"] and describe.plain_summary(chk) == ["Make 2 sound effects (10 s each): Bangs"]


def test_pack_download_asks_first_and_skips_what_is_there(studio, monkeypatch, tmp_path):
    app, _, models = studio
    with pytest.raises(PermissionError):
        picturetools.download_pack(app.settings, "bg", print)
    logs = []
    assert picturetools.download_pack(app.settings, "bg", logs.append, approved=True)
    assert "already installed" in logs[-1]
    (models / "upscale_models" / "RealESRGAN_x4plus.safetensors").unlink()
    got = []
    import joeai.doctor as doctor
    monkeypatch.setattr(doctor, "_download", lambda url, dest, log, *a: got.append((url, dest)) or dest.write_bytes(b"x") or True)
    assert picturetools.download_pack(app.settings, "upscale", logs.append, approved=True)
    assert got[0][0].startswith("https://huggingface.co/Comfy-Org/") and got[0][1].parent.name == "upscale_models"


def test_out_of_memory_frees_and_retries_smaller(studio, monkeypatch):
    app, comfy, _ = studio
    from joeai import comfy as comfy_mod
    png(app.sb.inbox / "bowl.png")
    real, calls = comfy_mod.ComfyClient.wait, []

    def wait(self, pid, stop=None):
        calls.append(pid)
        if len(calls) == 1:
            raise comfy_mod.WorkflowError("ComfyUI error: Allocation on device \nThis error means you ran out of memory on your GPU.")
        return real(self, pid, stop=stop)
    monkeypatch.setattr(comfy_mod.ComfyClient, "wait", wait)
    monkeypatch.setattr(picturetools.time, "sleep", lambda s: None)
    _, st = run(app, "TASK: Edit  TYPE: edit-picture\nINPUT: bowl.png\nFORMAT: white background")
    assert st.status == "done", st.note
    assert comfy.freed >= 2                                    # before the tool and before the retry
    first, retry = comfy.graphs[-2], comfy.graphs[-1]
    assert first["160"]["class_type"] == "FluxKontextImageScale"
    assert retry["160"]["class_type"] == "ImageScaleToTotalPixels"
    assert retry["160"]["inputs"]["megapixels"] == picturetools.SMALL_MP


def test_out_of_memory_twice_says_so_plainly(studio, monkeypatch):
    app, comfy, _ = studio
    from joeai import comfy as comfy_mod
    png(app.sb.inbox / "bowl.png")

    def wait(self, pid, stop=None):
        raise comfy_mod.WorkflowError("ComfyUI error: Allocation on device")
    monkeypatch.setattr(comfy_mod.ComfyClient, "wait", wait)
    monkeypatch.setattr(picturetools.time, "sleep", lambda s: None)
    _, st = run(app, "TASK: Old  TYPE: restore-photo\nINPUT: bowl.png\nOPTIONS: upscale none")
    assert st.status == "failed"
    assert "ran out of memory" in st.note and "Allocation" not in st.note
