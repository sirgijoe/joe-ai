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


def test_picture_book_pages_get_their_pictures_and_a_real_title(tmp_path):
    from joeai.addons import GENERIC_TITLE, add_pictures
    from joeai.mission import parse
    assert GENERIC_TITLE.match("Kids picture book") and not GENERIC_TITLE.match("The Little Robot Who Helped")
    text = "## The Robot Wakes\n\nBeep.\n\n## The Robot Helps\n\nBoop.\n"
    out = add_pictures(text, ["pics/001_a.png", "pics/002_b.png"])
    assert out.index("## The Robot Wakes") < out.index("![](pics/001_a.png)") < out.index("Beep.")
    assert out.index("## The Robot Helps") < out.index("![](pics/002_b.png)")
    m = parse("TASK: The Little Robot  SAVE: robot.md  EXPORT: pdf  TEMPLATE: kids\n"
              "PART: ## Wakes. The robot wakes, about 50 words.\nPART: ## Helps. It helps, about 50 words.\n"
              "TASK: Robot pictures  SAVE: robot-pictures  TYPE: image  FROM: The Little Robot  CHUNKS: 1 x 2")
    assert m.jobs[1].source == "The Little Robot"                          # pictures FROM a document: allowed


def test_kids_template_leaves_room_for_words():
    from joeai import doctemplates as dt
    t = dt.get(None, "kids")
    assert t["picture_share"] == 0.45 and t["size"] == 18
    css = dt.css(t)
    assert "max-height: 3.3in" in css                                   # 8.5 in page, 0.6 margins: 45%


def test_main_subject_only_drops_the_brush(tmp_path):
    import subprocess
    import pytest
    from types import SimpleNamespace
    from joeai import picturetools
    ff = _ff()
    if not ff:
        pytest.skip("no ffmpeg")
    m = bytes([255 if (2 <= x <= 5 and 2 <= y <= 5) or (x == 8 and y == 8) else 0 for y in range(10) for x in range(10)])
    keep = picturetools.largest_blob(m, 10, 10)
    assert keep[3 * 10 + 3] == 255 and keep[8 * 10 + 8] == 0
    # a cut-out with a big vase and a small brush: the brush becomes see-through
    cut = tmp_path / "vase-cutout.png"
    subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", "color=blue:s=200x100", "-f", "lavfi", "-i",
                    "color=black:s=200x100", "-filter_complex",
                    "[1]drawbox=x=20:y=10:w=80:h=80:color=white:t=fill,drawbox=x=150:y=40:w=20:h=10:color=white:t=fill,"
                    "format=gray[m];[0][m]alphamerge", "-frames:v", "1", str(cut)], check=True)
    eng = SimpleNamespace(s=SimpleNamespace(comfy=SimpleNamespace(ffmpeg=ff)), log=lambda *a: None)
    keep_wd = picturetools._work_dir
    picturetools._work_dir = lambda e: tmp_path
    try:
        picturetools._main_subject(eng, tmp_path, cut.name)
    finally:
        picturetools._work_dir = keep_wd
    def alpha(x, y):
        r = subprocess.run([ff, "-v", "error", "-i", str(cut), "-vf", f"crop=1:1:{x}:{y},alphaextract,format=gray",
                            "-f", "rawvideo", "-"], capture_output=True)
        return r.stdout[0]
    assert alpha(60, 50) > 200 and alpha(160, 45) < 30


def test_quick_turnaround_makes_three_views(tmp_path):
    from types import SimpleNamespace
    from joeai import picturetools
    import joeai.tools as tools_mod
    src = tmp_path / "robot.png"
    src.write_bytes(b"x")
    eng = SimpleNamespace(log=lambda *a: None)
    orig = tools_mod.option_value
    tools_mod.option_value = lambda j, k: j.options.get(k, "")
    try:
        quick = picturetools.plan_items(eng, SimpleNamespace(format="", options={"views": "quick"}), "character-spin", [src])[0]
        full = picturetools.plan_items(eng, SimpleNamespace(format="", options={}), "character-spin", [src])[0]
    finally:
        tools_mod.option_value = orig
    assert [i["stem"] for i in quick] == ["1-front", "3-left", "4-back"] and len(full) == 6


def test_neon_prompts_lose_their_signs():
    from joeai.styles import no_signs
    out = no_signs("rainy street, glowing neon signs and holographic billboards, kanji, wet asphalt")
    assert "sign" not in out and "billboard" not in out and "kanji" not in out and "neon light strips" in out
