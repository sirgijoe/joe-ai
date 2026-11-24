"""2026-11-24 workflow audit fixes (workflow_audit_11_24.md, Joseph's decisions): kids mode under 13,
looks that fit, the medium word wins, the look owns lens and background, model profiles, the Pictures row
only fills in, FLUX.2 still used for the hard cases, SDXL sizes, Animate, music feel, temperatures."""
from __future__ import annotations

from types import SimpleNamespace as NS

from joeai import comfy, modelprofiles as mp, styles, workflowprefs as wfp
from joeai.config import Settings


def job(fmt="", name="x", style=""):
    return NS(name=name, format=fmt, style=style, rules="", part_prompts=[], template="")


# ------------------------------------------------------------------ kids mode (N1)
def test_kids_mode_is_for_children_under_13():
    for words in ("for my 5-year-old", "for my 5 year old", "a twelve year old's party", "for my 2nd grade class",
                  "a coloring book for my granddaughter"):
        assert styles.for_kids(job(words)), words
    for words in ("portrait of a 45 year old man", "photo of a 65-year-old couple on a beach",
                  "mug design for a 3rd grade teacher", "a twenty-two-year-old runner", "a 13 year old car"):
        assert not styles.for_kids(job(words)), words


# ------------------------------------------------------------------ looks (F4, F5)
def test_kids_coloring_page_never_gets_the_adult_look():
    r = styles.recipe(job("a detailed dinosaur with patterns for my 5 year old", "Kids coloring book"))
    assert r.style.id == "coloring" and r.look["id"] == "simple" and "intricate" not in r.words
    assert styles.recipe(job("an intricate mandala for adults", "Coloring book")).look["id"] == "adult"


def test_animal_portrait_gets_wildlife_and_a_person_keeps_portrait():
    assert styles.recipe(job("a golden retriever puppy portrait")).look["id"] == "wildlife"
    assert styles.recipe(job("portrait of a woman with her dog")).look["id"] == "portrait"
    assert styles.recipe(job("a portrait photo of an old farmer")).look["id"] == "portrait"


# ------------------------------------------------------------------ style pick (F6)
def test_the_medium_word_beats_the_subject_word():
    assert styles.pick(job("a castle on a hill at sunset, photo")).id == "photo"
    assert styles.pick(job("watercolor of a dragon")).id == "watercolor"
    assert styles.pick(job("cyberpunk street at night with neon")).id == "cyberpunk"      # no medium word
    assert styles.pick(job("a superhero")).id == "comic"
    assert styles.pick(job("fantasy art of a castle")).id == "fantasy"


# ------------------------------------------------------------------ the look owns lens / background (F7), repeats (F9)
def test_the_look_owns_lens_and_background():
    r = styles.recipe(job("portrait of a 45 year old man"))
    assert any("35mm" in n and "CAMERA" in n for n in r.notes)
    r = styles.recipe(job("studio product photo of a mug, flat lay on linen"))
    assert "seamless background" not in r.words and "warm linen surface" in r.words
    assert any(n.startswith("BACKGROUND") for n in r.notes)


def test_repeated_words_are_dropped_and_weighted_groups_kept_whole():
    assert styles.dedupe("anime style, cel shaded, Anime  style, (a, b:1.4), a, c") == "anime style, cel shaded, (a, b:1.4), c"
    r = styles.recipe(job("mascot for a pottery shop"))
    assert r.words.count("full body") == 1 and "(mascot character" in r.words


def test_words_fit_the_model_that_draws():
    w = "cyberpunk, no signage, (mascot, cartoon:1.4), masterpiece, high score"
    assert styles.words_for(w, "sdxl") == "cyberpunk, (mascot, cartoon:1.4), masterpiece, high score"
    assert styles.words_for(w, "flux2") == "cyberpunk, no signage, mascot, cartoon"


# ------------------------------------------------------------------ model profiles (F1, F2)
def test_profiles_from_the_file_name():
    kinds = {n: mp.for_checkpoint(n).kind for n in (
        "dreamshaperXL_v21TurboDPMSDE.safetensors", "juggernautXL_lightning.safetensors", "HyperRealismXL.safetensors",
        "ponyDiffusionV6XL.safetensors", "waiNSFWIllustrious_v140.safetensors", "animagine-xl-4.0.safetensors",
        "juggernautXL_ragnarokBy.safetensors")}
    assert list(kinds.values()) == ["fast", "fast", "", "pony", "illustrious", "animagine", ""]
    assert mp.for_checkpoint("x_turbo.safetensors", "flux2") is mp.NONE


def test_fast_model_gets_its_own_steps_and_strength_and_pony_gets_clip_skip():
    g = comfy.basic_graph("sdxl", 40, "dpmpp_2m_sde", -1.5)
    g = mp.apply_graph(g, mp.for_checkpoint("juggernautXL_lightning.safetensors"), "high")
    ks = g["3"]["inputs"]
    assert (ks["steps"], ks["cfg"], ks["sampler_name"], ks["scheduler"]) == (6, 2.0, "dpmpp_sde", "karras")
    g = mp.apply_graph(comfy.basic_graph("sdxl", 40, "euler_ancestral"), mp.for_checkpoint("pony_v6.safetensors"), "high")
    assert g["15"]["class_type"] == "CLIPSetLastLayer" and g["6"]["inputs"]["clip"] == ["15", 0]
    g = comfy.with_lora(g, "pixel.safetensors")
    assert g["15"]["inputs"]["clip"] == ["10", 1]                   # checkpoint -> add-on -> clip skip -> words


def test_pony_swaps_animagine_quality_tags_and_keeps_the_style_words():
    rec = styles.recipe(job("a knight, anime style"))
    assert "high score" in rec.words
    r2 = mp.adapt_recipe(rec, mp.for_checkpoint("pony_v6.safetensors"))
    assert "high score" not in r2.words and "anime style" in r2.words and r2.prefix.startswith("score_9")
    assert r2.negative.startswith("score_5") and "low score" not in r2.negative


def test_illustr_hint_no_longer_picks_illustrious_for_drawing_styles():
    ms = [comfy.ImageModel("waiNSFWIllustrious_v140.safetensors", "checkpoints", 6.5, "sdxl"),
          comfy.ImageModel("sdxl_base.safetensors", "checkpoints", 6.5, "sdxl")]
    assert [m.name for m in styles.choose_model(ms, "anime")] == ["waiNSFWIllustrious_v140.safetensors"]
    suited = styles.choose_model(ms, "illustration")                # no drawing model: any non-photo one
    assert len(suited) == 2 and comfy.best_image_model(suited, 12).name == "sdxl_base.safetensors"


def test_same_general_model_every_time():
    ms = [comfy.ImageModel("zzz_new_test.safetensors", "checkpoints", 6.5, "sdxl", 999.0),
          comfy.ImageModel("juggernautXL.safetensors", "checkpoints", 6.5, "sdxl", 1.0)]
    assert comfy.best_image_model(ms, 12).name == "juggernautXL.safetensors"


# ------------------------------------------------------------------ Pictures row only fills in (F11)
def test_pictures_row_only_fills_in(tmp_path, monkeypatch):
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "settings.json"))
    s = Settings()
    s.workflows = {"pictures": {"cfg": 7.0, "sampler": "euler", "hires": "on", "versions": 3, "add": "warm"},
                   "style:photo": {"add": "film"}}
    p = wfp.picture_prefs(s, styles.STYLES["photo"])
    assert "cfg" not in p and "sampler" not in p and p["versions"] == 3 and p["add"] == "film, warm"
    p = wfp.picture_prefs(s, styles.STYLES["pixel"])
    assert "hires" not in p                                          # pixel art keeps its detail pass off
    p = wfp.picture_prefs(s, styles.STYLES["general"])
    assert p["cfg"] == 7.0 and p["sampler"] == "euler" and p["hires"] == "on"


# ------------------------------------------------------------------ FLUX.2 still used for the hard cases (N2)
def test_a_picked_model_still_switches_for_the_hard_cases(monkeypatch, tmp_path):
    from joeai import engine as engine_mod, picturetools as pt
    import joeai.doctor as doctor
    from joeai.mission import parse
    monkeypatch.setattr(doctor, "comfy_models_dir", lambda s: tmp_path)
    monkeypatch.setattr(pt, "pack_ready", lambda m, p: p == "flux2")
    me = NS(s=Settings())
    j = parse("TASK: a  SAVE: p  TYPE: image\nFORMAT: a bakery sign that says FRESH BREAD").jobs[0]
    use, why = engine_mod.Engine._use_flux2(me, j, ["x"], {"model": "juggernautXL.safetensors"})
    assert use and "juggernautXL" in why and "Always use my chosen model" in why
    plain = parse("TASK: a  SAVE: p  TYPE: image\nFORMAT: a loaf of bread").jobs[0]
    assert not engine_mod.Engine._use_flux2(me, plain, ["x"], {"model": "juggernautXL.safetensors"})[0]
    me.s.comfy.always_my_model = True
    assert not engine_mod.Engine._use_flux2(me, j, ["x"], {"model": "juggernautXL.safetensors"})[0]


# ------------------------------------------------------------------ SDXL sizes (N5)
def test_big_sizes_are_drawn_at_the_models_own_size():
    assert comfy.native_size("sdxl", 1024, 1024) is None
    assert comfy.native_size("sdxl", 1920, 1080) == (1344, 768)
    assert comfy.native_size("sdxl", 1080, 1920) == (768, 1344)
    assert comfy.native_size("flux2", 1920, 1080) is None
    g = comfy.with_final_size(comfy.basic_graph("sdxl"), 1920, 1080)
    assert g["9"]["inputs"]["images"] == ["22", 0] and g["22"]["inputs"]["width"] == 1920


def test_pixel_finish_works_on_flux():
    g = comfy.with_pixelate(comfy.flux2_graph(), 8)
    assert g["9"]["inputs"]["images"] == ["21", 0] and g["20"]["inputs"]["image"] == ["65", 0]


# ------------------------------------------------------------------ Animate, audio (F15, F17, F18)
def test_animate_has_its_own_leave_out_list():
    assert "静态" not in comfy.ANIMATE_NEGATIVE and "静止不动的画面" not in comfy.ANIMATE_NEGATIVE
    assert "identity change" in comfy.ANIMATE_NEGATIVE and "静态" in comfy.WAN_NEGATIVE
    assert wfp.tune_defaults("animate") == {"cfg": wfp.ANIMATE_CFG}
    assert wfp.builtin_text("animate")["leave"] == comfy.ANIMATE_NEGATIVE


def test_music_tempo_and_key_follow_the_request():
    from joeai import picturetools as pt
    assert pt.music_feel("slow sad piano") == (75, "A minor", "4")
    assert pt.music_feel("fast chiptune boss fight") == (150, "C major", "4")
    assert pt.music_feel("spooky waltz") == (110, "A minor", "3")
    assert pt.music_feel("upbeat pop at 128 bpm")[0] == 128
    g = pt.music_graph("x", 30, 1, bpm=75, keyscale="A minor", timesignature="3")
    assert g["94"]["inputs"]["keyscale"] == "A minor" and g["94"]["inputs"]["timesignature"] == "3"
    assert pt.sfx_negative("radio static") == "low quality, distorted"
    assert pt.sfx_negative("door creak") == "low quality, noise, distorted"


# ------------------------------------------------------------------ writing (F19, F20)
def test_fact_jobs_get_a_low_temperature():
    from joeai.engine import Engine
    assert Engine.PRECISE_TEMPS["proofread"] <= 0.3 and "write" not in Engine.PRECISE_TEMPS
    assert "prompt" not in Engine.PRECISE_TEMPS and "brainstorm" not in Engine.PRECISE_TEMPS


def test_context_grows_only_when_the_input_needs_it(monkeypatch):
    from joeai import hardware, ollama
    monkeypatch.setattr(hardware, "vram_total_gb", lambda: 12)
    assert ollama.auto_ctx() == 6144 and ollama.auto_ctx(5000) == 6144 and ollama.auto_ctx(9000) == 12288
    msgs = [{"role": "user", "content": "x" * 35000}]
    assert ollama.need_tokens(msgs, None, True) > 6144


# ------------------------------------------------------------------ found in the live A/B run (2026-11-24)
def test_flat_lay_is_a_product_photo_not_flat_art():
    r = styles.recipe(job("studio product photo of a handmade ceramic mug, flat lay on linen", "AB product flat lay"))
    assert r.style.id == "product" and r.look["id"] == "flatlay"
    assert styles.pick(job("flat vector icons of fruit")).id == "illustration"


def test_the_writers_own_lens_gives_way_to_the_looks():
    t = "A stone castle on a hill. Wide 24mm shot from a low angle. 24mm, f/4, weathered stone, shot on 35mm lens, f/1.8."
    assert styles.strip_lens(t) == "A stone castle on a hill. Wide shot from a low angle. weathered stone"
    from joeai.engine import Engine
    rec = styles.recipe(job("a castle on a hill at sunset, photo"))
    out = Engine._styled(NS(_lora_used=False), "A castle, shot on 35mm lens, f/1.8, golden light", rec, "sdxl")
    assert rec.look["id"] == "landscape" and "35mm" not in out and "16mm" in out


# ------------------------------------------------------------------ look words start a word (baseline rerun, 2026-11-24)
def test_look_words_must_start_a_word():
    def look(name, style):
        return styles.recipe(job(name=name, style=style)).look["id"]
    assert look("Rerun 05 manga", "manga") == "quiet"            # "run" inside "Rerun" picked the action panel
    assert look("a brunch table", "manga") == "quiet"
    assert look("kids running in a park", "manga") == "action"   # a real word still matches, stems too
    assert look("a knight in armor", "bw") != "noir"             # "night" inside "knight"
    assert look("a night street", "bw") == "noir"
    assert look("a surface of water", "manga") == "quiet"        # "face" inside "surface"
    assert look("headphones levitating over a desk", "product") == "floating"
