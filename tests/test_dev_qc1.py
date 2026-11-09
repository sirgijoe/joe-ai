"""Fixes from the showcase-video QC (2026-11-09)."""
from __future__ import annotations

import threading

from test_tools import app  # noqa: F401


def test_stop_keeps_waiting_missions_on_hold(app, monkeypatch):  # noqa: F811
    """Stop after this step used to throw away the missions waiting in line."""
    from joeai.mission import parse
    app.settings.comfort.ntfy_topic = ""
    app.queue = []
    for name in ("First", "Second", "Third"):
        text = f"TASK: {name}  SAVE: {name.lower()}.md  CHUNKS: 1 x 2"
        app.queue.append((text, parse(text), {"label": name, "file": "", "unfinished": [name]}))
    app.chain, app.run_log, app.stop, app.accepting = [], [e for _, _, e in app.queue], threading.Event(), True
    real = app.run_result

    def stop_after_first(*a, **k):                                 # Stop pressed during mission 1
        app.stop.set()
        return real(*a, **k)
    monkeypatch.setattr(app, "run_result", stop_after_first)
    app._work()
    held = app.held_missions()
    assert [h["label"] for h in held] == ["Second", "Third"]          # kept, in line order
    assert [e["label"] for e in app.run_log] == ["First"]             # resume offer won't run them twice
    assert any("ON HOLD" in line for line in app.logs)
    r = app.held_action("clear")
    assert r["ok"] and r["cleared"] == 2 and not app.held_missions()
    assert len(list((app.sb.missions / "Queue" / "done").glob("cleared_*"))) == 2


def test_held_missions_run_again_in_order(app, monkeypatch):  # noqa: F811
    folder = app.hold_dir()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "01_b.txt").write_text("TASK: Bee  SAVE: b.md  CHUNKS: 1 x 1")
    (folder / "02_a.txt").write_text("TASK: Ay  SAVE: a.md  CHUNKS: 1 x 1")
    seen = []
    monkeypatch.setattr(app, "enqueue", lambda text, only=None: seen.append(text.split()[1]) or {"ok": True})
    r = app.held_action("run")
    assert r["ok"] and r["started"] == 2 and seen == ["Bee", "Ay"] and not app.held_missions()


def _ff():
    import shutil
    return shutil.which("ffmpeg")


def test_blank_border_is_caught(tmp_path):
    import subprocess
    import pytest
    from joeai import media
    ff = _ff()
    if not ff:
        pytest.skip("no ffmpeg")
    src = tmp_path / "s.png"
    subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=320x200", "-frames:v", "1", str(src)],
                   check=True)
    pad, inner = media.pad_for_outpaint(ff, src, tmp_path / "p.png", "wider")
    assert media.size_of(ff, pad) == (480, 200) and inner == (80, 0, 320, 200)
    assert not media.border_is_flat(ff, pad, inner, (480, 200))          # blurred stretch: not flat
    white = tmp_path / "w.png"                                          # the editor's white frame
    subprocess.run([ff, "-y", "-v", "error", "-i", str(src), "-vf", "pad=480:200:80:0:white",
                    "-frames:v", "1", str(white)], check=True)
    assert media.border_is_flat(ff, white, inner, (480, 200))
    vase = tmp_path / "v.png"                                           # product on white: white is right
    subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", "color=white:s=480x200", "-vf",
                    "drawbox=x=200:y=60:w=80:h=80:color=blue:t=fill", "-frames:v", "1", str(vase)], check=True)
    assert not media.border_is_flat(ff, vase, inner, (480, 200))


def test_bigger_all_around_goes_wider_then_taller(tmp_path):
    import subprocess
    import pytest
    from types import SimpleNamespace
    from joeai import picturetools
    ff = _ff()
    if not ff:
        pytest.skip("no ffmpeg")
    src = tmp_path / "beach.png"
    subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=320x200", "-frames:v", "1", str(src)],
                   check=True)
    eng = SimpleNamespace(log=lambda *a: None)
    job = SimpleNamespace(format="", options={"shape": "around"}, type="make-bigger")
    import joeai.tools as tools_mod
    orig = tools_mod.option_value
    tools_mod.option_value = lambda j, k: j.options.get(k, "")
    picturetools._ffmpeg, keep_ff = (lambda e: ff), picturetools._ffmpeg
    picturetools._work_dir, keep_wd = (lambda e: tmp_path), picturetools._work_dir
    try:
        items, keys, why = picturetools.plan_items(eng, job, "make-bigger", [src])
    finally:
        tools_mod.option_value = orig
        picturetools._ffmpeg, picturetools._work_dir = keep_ff, keep_wd
    it = items[0]
    assert not why and it["then"] == "taller" and it["stem"].endswith("-around")
    assert it["inner"] == (80, 0, 320, 200)                             # step 1 only grows the sides
    assert "no borders, frames, white margins" in it["prompt"]


def test_pixel_art_finishes_with_crisp_pixels_and_no_detail_pass():
    import json
    from pathlib import Path
    from joeai import comfy, styles
    st = styles.STYLES["pixel"]
    assert not st.hires and st.pixelate == 8
    g = comfy.with_pixelate(comfy.with_lora(comfy.basic_graph("sdxl", 30), "pixel-art-xl.safetensors"), 8)
    assert g["9"]["inputs"]["images"] == ["21", 0] and g["21"]["inputs"]["image"] == ["20", 0]
    assert g["20"]["inputs"]["image"] == ["8", 0] and g["20"]["inputs"]["upscale_method"] == "area"
    assert g["21"]["inputs"]["upscale_method"] == "nearest-exact" and g["21"]["inputs"]["scale_by"] == 8.0
    assert g["3"]["inputs"]["steps"] == 30                      # normal steps, not the 8-step LCM recipe
    picks = json.loads((Path(comfy.__file__).parent / "model_picks.json").read_text(encoding="utf-8"))
    def walk(o):
        if isinstance(o, dict):
            if "lora_settings" in o:
                yield o["lora_settings"]
            for v in o.values():
                yield from walk(v)
        elif isinstance(o, list):
            for v in o:
                yield from walk(v)
    for ls in walk(picks):
        assert "steps" not in ls and "cfg" not in ls             # few-step numbers need a speed add-on


def test_part_title_is_cut_at_the_first_period():
    from joeai.engine import _fix_part_heading, split_part
    part = "## The Little Robot Who Helped. A gentle children's picture book page, about 60 words: a robot helps."
    assert split_part(part) == ("The Little Robot Who Helped",
                                "A gentle children's picture book page, about 60 words: a robot helps.")
    assert split_part("## Chapter 1: The Storm. Write it.")[0] == "Chapter 1: The Storm"
    assert split_part("## Meet Dr. Lee. Introduce her.")[0] == "Meet Dr. Lee"
    assert split_part("Just do it") == ("", "Just do it")
    copied = "## The Little Robot Who Helped. A gentle children's picture book page, about 60 words\n\nBeep."
    assert _fix_part_heading(copied, part).startswith("## The Little Robot Who Helped\n")


def test_a_part_is_held_to_its_own_length():
    from joeai.engine import asked_words, thin_reply_words
    assert asked_words("a page, about 60 words: x") == 60 and asked_words("150-200 words") == 150
    assert thin_reply_words(400, 2, asked_words("about 60 words")) == 30     # 65 words is fine now
    assert thin_reply_words(400, 2) == 80                                     # no length asked: as before


def test_proofread_leaves_names_and_web_addresses_alone():
    from joeai.tools import apply_changes
    txt = "Find Joe at Sunny Day Cafe dot com. I has a dog named Max."
    out, applied, noted, missed = apply_changes(txt, [
        {"find": "Sunny Day Cafe dot com", "replace": "SunnyDayCafeO.com", "why": "spelling"},
        {"find": "named Max", "replace": "named Maxx", "why": "spelling"},
        {"find": "I has", "replace": "I have", "why": "grammar"}])
    assert out == "Find Joe at Sunny Day Cafe dot com. I have a dog named Max."
    assert len(applied) == 1 and len(noted) == 2 and "left as written" in noted[0]["why"]


def test_groups_and_riders_get_framed_and_neon_gets_no_signs():
    from joeai import styles
    assert styles.crowded("a family of five at a picnic") and styles.crowded("friends around a campfire")
    assert styles.crowded("a father and daughter riding a horse")
    assert not styles.crowded("grandfather and grandson fishing") and not styles.crowded("a sunflower")
    cy = styles.STYLES["cyberpunk"]
    assert "signage" in cy.negative and "no signage" in cy.suffix and cy.cfg < 0
    assert "brand" in styles.STYLES["product"].negative


def test_edits_come_back_at_the_photos_own_size(tmp_path):
    import subprocess
    import pytest
    from types import SimpleNamespace
    from joeai import media, picturetools
    ff = _ff()
    if not ff:
        pytest.skip("no ffmpeg")
    src, out = tmp_path / "dock.png", tmp_path / "dock-relit.png"
    subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=1008x576", "-frames:v", "1", str(src)], check=True)
    subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=680x384", "-frames:v", "1", str(out)], check=True)
    picturetools._keep_size(SimpleNamespace(log=lambda *a: None), ff, src, out)
    assert media.size_of(ff, out) == (1008, 576)
