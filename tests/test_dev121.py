"""dev121 (batch 2): picture tools on the Qwen editor."""
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from joeai import comfy, media, picturetools as pt
from joeai.config import Settings
from joeai.mission import parse
from joeai.sandbox import Sandbox
from joeai.tools import TOOLS

FF = shutil.which("ffmpeg")
needs_ff = pytest.mark.skipif(not FF, reason="needs FFmpeg")


def _pic(p: Path, src: str = "testsrc2=size=320x240", color: str = "") -> Path:
    subprocess.run([FF, "-y", "-v", "error", "-f", "lavfi", "-i", color or src, "-frames:v", "1", str(p)], check=True)
    return p


def _engine(tmp_path):
    s = Settings()
    s.comfy.ffmpeg = FF or ""
    sb = Sandbox(tmp_path / "ws").ensure()
    logs = []
    return SimpleNamespace(s=s, sb=sb, log=logs.append, logs=logs)


def _job(text):
    return parse("TASK: T\n" + text).jobs[0]


def test_new_tools_are_ready_and_planable():
    for tid in pt.NEW_EDITORS:
        assert TOOLS[tid].ready and pt.TOOL_PACKS[tid] == ("edit",) and tid in pt.EDITORS
        assert TOOLS[tid].plan_hint
    j = _job("TYPE: relight\nINPUT: a.jpg\nOPTIONS: light night")
    assert j.options == ["light night"]


def test_edit_graph_takes_extra_pictures():
    g = pt.edit_graph("a.png", "merge", 1, extra_images=["b.png", "c.png", "d.png"])
    assert g["151"]["inputs"]["image2"] == ["160_2", 0] and g["151"]["inputs"]["image3"] == ["160_3", 0]
    assert "image4" not in g["151"]["inputs"] and g["41_3"]["inputs"]["image"] == "c.png"


def test_hires_second_pass():
    g = comfy.with_hires(comfy.basic_graph("sdxl", 40))
    assert g["8"]["inputs"]["samples"] == ["12", 0]
    assert g["12"]["inputs"]["latent_image"] == ["11", 0] and g["12"]["inputs"]["denoise"] < 0.5
    assert g["12"]["inputs"]["model"] == g["3"]["inputs"]["model"]


@needs_ff
def test_plan_items_each_tool(tmp_path):
    eng = _engine(tmp_path)
    a, b, c = (_pic(tmp_path / f"{n}.png") for n in "abc")
    items, keys, why = pt.plan_items(eng, _job("TYPE: fix-spot\nINPUT: a.png"), "fix-spot", [a])
    assert not items and "MARK THE SPOT" in why
    media.box_mask(FF, (320, 240), [(0.4, 0.4, 0.2, 0.2)], a.with_name("a-mask.png"))
    items, keys, why = pt.plan_items(eng, _job("TYPE: fix-spot\nINPUT: a.png"), "fix-spot",
                                     [a, a.with_name("a-mask.png")])
    assert len(items) == 1 and items[0]["images"][0].exists() and "remove" in items[0]["prompt"]
    items, *_ = pt.plan_items(eng, _job("TYPE: merge-pictures\nINPUT: a.png, b.png\nFORMAT: mug on table"),
                              "merge-pictures", [a, b, c])
    assert len(items) == 1 and items[0]["images"] == [b, c]
    assert not pt.plan_items(eng, _job("TYPE: merge-pictures\nINPUT: a.png"), "merge-pictures", [a])[0]
    items, *_ = pt.plan_items(eng, _job("TYPE: restyle\nINPUT: a.png\nOPTIONS: style picture"), "restyle", [a, b, c])
    assert [i["src"] for i in items] == [a, b] and items[0]["images"] == [c]
    items, *_ = pt.plan_items(eng, _job("TYPE: redraw\nINPUT: a.png\nOPTIONS: change little\nFORMAT: clean"),
                              "redraw", [a])
    assert items[0]["denoise"] == pt.DENOISE["little"]
    items, *_ = pt.plan_items(eng, _job("TYPE: make-bigger\nINPUT: a.png\nOPTIONS: shape taller"), "make-bigger", [a])
    assert media.size_of(FF, items[0]["padded"]) == (320, 360) and items[0]["inner"] == (0, 60, 320, 240)
    items, *_ = pt.plan_items(eng, _job("TYPE: character-scenes\nINPUT: a.png\nFORMAT: at the beach; in space\nreading"),
                              "character-scenes", [a])
    assert len(items) == 3 and "at the beach" in items[0]["prompt"]
    items, *_ = pt.plan_items(eng, _job("TYPE: character-spin\nINPUT: a.png"), "character-spin", [a])
    assert len(items) == len(pt.SPIN_VIEWS) and len(set(i["key"] for i in items)) == 6


def _avg(p: Path, crop: str) -> tuple:
    out = subprocess.run([FF, "-v", "error", "-i", str(p), "-vf", f"crop={crop},scale=1:1", "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    return tuple(out[:3])


@needs_ff
def test_fix_spot_changes_only_the_spot(tmp_path):
    eng = _engine(tmp_path)
    src = _pic(tmp_path / "p.png", color="color=red:s=320x240")
    mask = media.box_mask(FF, (320, 240), [(0.375, 0.375, 0.25, 0.25)], tmp_path / "p-mask.png", grow=0)
    folder = tmp_path / "out"
    folder.mkdir()
    _pic(folder / "p-fixed.png", color="color=blue:s=320x240")
    item = {"src": src, "mask": mask}
    pt.after_edit(eng, None, "fix-spot", item, folder, ["p-fixed.png"], {})
    r, g, b = _avg(folder / "p-fixed.png", "20:20:150:110")       # the middle: new (blue)
    assert b > 200 and r < 60
    r, g, b = _avg(folder / "p-fixed.png", "20:20:5:5")           # a corner: untouched (red)
    assert r > 200 and b < 60


@needs_ff
def test_make_bigger_keeps_the_middle(tmp_path):
    eng = _engine(tmp_path)
    src = _pic(tmp_path / "p.png", color="color=red:s=320x240")
    padded, inner = media.pad_for_outpaint(FF, src, tmp_path / "pad.png", "wider")
    folder = tmp_path / "out"
    folder.mkdir()
    _pic(folder / "p-wider.png", color="color=green:s=480x240")
    pt.after_edit(eng, None, "make-bigger", {"padded": padded, "inner": inner}, folder, ["p-wider.png"], {})
    r, g, b = _avg(folder / "p-wider.png", "40:40:220:100")       # middle = the real picture
    assert r > 200 and g < 60
    r, g, b = _avg(folder / "p-wider.png", "20:20:5:110")         # left edge = AI part
    assert g > 100 and r < 60


@needs_ff
def test_keep_real_faces_after_ai_repair(tmp_path):
    eng = _engine(tmp_path)
    orig = _pic(tmp_path / "o.png", color="color=gray:s=320x240")
    folder = tmp_path / "out"
    folder.mkdir()
    _pic(folder / "o-restored.png", color="color=purple:s=640x480")
    pt.after_edit(eng, None, "restore-photo", orig, folder, ["o-restored.png"], {orig: [(0.4, 0.4, 0.2, 0.2)]})
    r, g, b = _avg(folder / "o-restored.png", "40:40:300:220")    # the face box: real (grey-ish)
    assert abs(r - g) < 40
    r, g, b = _avg(folder / "o-restored.png", "20:20:5:5")        # elsewhere: the repair (purple)
    assert r > g + 40


@needs_ff
def test_spin_sheet(tmp_path):
    eng = _engine(tmp_path)
    for n, (vid, _) in enumerate(pt.SPIN_VIEWS, 1):
        _pic(tmp_path / f"{n}-{vid}.png")
    st = SimpleNamespace(media_files=[])
    pt.spin_sheet(eng, tmp_path, st)
    assert (tmp_path / "character-sheet.png").exists() and st.media_files == ["character-sheet.png"]


def test_mask_endpoint_saves_next_to_picture(tmp_path, monkeypatch):
    import base64
    from joeai.server import App
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "settings.json"))
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    s.comfy.url = "http://127.0.0.1:9"
    s.ollama.url = "http://127.0.0.1:9"
    app = App(settings=s)
    pic = app.sb.inbox / "tools" / "fix-spot" / "x.jpg"
    pic.parent.mkdir(parents=True)
    pic.write_bytes(b"jpg")
    import json
    import threading
    import urllib.error
    import urllib.request
    from joeai.server import serve
    httpd = serve(app, 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        def post(body):
            req = urllib.request.Request(f"http://127.0.0.1:{httpd.server_address[1]}/api/tools/mask",
                                         data=json.dumps(body).encode(), method="POST",
                                         headers={"X-NR-Token": app.token, "Content-Type": "application/json"})
            try:
                return json.loads(urllib.request.urlopen(req, timeout=10).read())
            except urllib.error.HTTPError as e:
                return {"ok": False, "code": e.code}
        png = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()
        assert post({"input": "tools/fix-spot/x.jpg", "png": png})["ok"]
        assert (pic.parent / "x-mask.png").read_bytes().startswith(b"\x89PNG")
        assert not post({"input": "tools/fix-spot/x.jpg", "png": "aGVsbG8="})["ok"]
        assert not post({"input": "../../evil.jpg", "png": png}).get("ok")
    finally:
        httpd.shutdown()


def test_plain_summary_new_tools(tmp_path, monkeypatch):
    from joeai.describe import plain_summary
    jobs = [{"name": "Spin", "type": "character-spin", "files": 1, "options": [], "format": ""},
            {"name": "Light", "type": "relight", "files": 2, "options": ["light night"], "format": ""},
            {"name": "Scenes", "type": "character-scenes", "files": 1, "options": [], "format": "a; b; c"}]
    out = plain_summary({"jobs": jobs})
    assert out[0].startswith("6 views") and "night" in out[1] and "3 scenes" in out[2]
