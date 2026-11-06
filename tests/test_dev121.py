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


# --------------------------------------------------------------------------- batch 2.5 (dev122)
def test_reset_paths_keeps_protected_and_stats(tmp_path, monkeypatch):
    from joeai.config import reset_paths
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "s.json"))
    s = Settings()
    s.workspace = "/my/folder"
    s.web.ollama_key = "k"
    s.ui.welcomed = True
    s.engine.keep_awake = False
    s.ui.text_size = 30
    s.workflows = {"pictures": {"add": "x"}}
    assert reset_paths(s, ["engine.keep_awake"]) == ["engine.keep_awake"] and s.ui.text_size == 30
    changed = reset_paths(s, None)
    assert "ui.text_size" in changed and s.ui.text_size == 22
    assert s.workspace == "/my/folder" and s.web.ollama_key == "k" and s.ui.welcomed


def test_app_reset_all_clears_workflows_not_stats(tmp_path, monkeypatch):
    from joeai.server import App
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "settings.json"))
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    s.comfy.url = s.ollama.url = "http://127.0.0.1:9"
    app = App(settings=s)
    (app.sb.meta).mkdir(parents=True, exist_ok=True)
    (app.sb.meta / "runs.jsonl").write_text('{"ok": true, "ts": "2026-11-06T10:00:00", "tokens_in": 5}\n')
    app.settings.workflows = {"video": {"add": "slow"}}
    app.settings.quality.pictures = "low"
    r = app.reset_settings(None)
    assert r["ok"] and app.settings.quality.pictures == "high" and app.settings.workflows == {}
    assert (app.sb.meta / "runs.jsonl").read_text()                 # stats untouched
    assert not app.reset_settings(["quality.writing"]).get("changed")


def test_stats_periods(tmp_path):
    from datetime import date, timedelta
    from joeai import stats
    sb = Sandbox(tmp_path / "ws").ensure()
    sb.meta.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    old = (date.today() - timedelta(days=400)).isoformat()
    (sb.meta / "runs.jsonl").write_text(
        f'{{"ok": true, "ts": "{today}T10:00:00", "tokens_in": 10, "seconds": 1}}\n'
        f'{{"ok": true, "ts": "{old}T10:00:00", "tokens_in": 100, "seconds": 1}}\n')
    s = Settings()
    assert stats.collect(s, sb, "day")["tokens_in"] == 10
    assert stats.collect(s, sb, "all")["tokens_in"] == 110
    assert stats.collect(s, sb, "nonsense")["period"] == "all"


def test_workflow_prefs_merge_and_save(tmp_path, monkeypatch):
    from joeai import workflowprefs as w
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "s.json"))
    s = Settings()
    assert w.save(s, "pictures", {"add": "soft light", "steps": 30, "model": "", "avoid": ""})["ok"]
    assert w.save(s, "style:watercolor", {"add": "paper texture", "model": "dream.safetensors"})["ok"]
    m = w.merged(s, ["style:watercolor", "pictures"])
    assert m == {"model": "dream.safetensors", "steps": 30, "add": "paper texture, soft light"}
    assert w.with_add("a cat.", m) == "a cat, paper texture, soft light"
    assert w.save(s, "pictures", None)["ok"] and "pictures" not in s.workflows
    assert not w.save(s, "bogus", {"add": "x"})["ok"]
    assert Settings.load().workflows == {"style:watercolor": {"model": "dream.safetensors", "add": "paper texture"}}
    rows = w.entries(s, Sandbox(tmp_path / "ws").ensure(), None)["rows"]
    assert any(r["id"] == "editor" for r in rows) and any(r["id"].startswith("style:") for r in rows)


def test_model_kinds():
    from joeai.doctor import model_kind
    assert model_kind("pull-model") == "writing" and model_kind("pack-edit") == "tools"
    assert model_kind("pack-music") == "sound" and model_kind("style-anime") == "pictures"
    assert model_kind("install-ollama") == ""


def test_connect_writes_only_joes_entry(tmp_path, monkeypatch):
    import json
    from joeai import connect
    monkeypatch.setenv("JOE_HOME_OVERRIDE", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    gem = tmp_path / ".gemini" / "settings.json"
    gem.parent.mkdir()
    gem.write_text(json.dumps({"theme": "dark", "mcpServers": {"other": {"command": "x"}}}))
    assert not connect.connect("cursor", {"command": "py"})["ok"]          # not installed
    assert connect.connect("gemini", {"command": "py", "args": ["Joe.pyw", "mcp"]})["ok"]
    d = json.loads(gem.read_text())
    assert d["theme"] == "dark" and "other" in d["mcpServers"] and d["mcpServers"]["joe"]["command"] == "py"
    assert gem.with_name("settings.json.before-joe").exists()
    assert next(a for a in connect.status() if a["id"] == "gemini")["connected"]
    assert connect.disconnect("gemini")["ok"] and "joe" not in json.loads(gem.read_text())["mcpServers"]
    gem.write_text("{not json")
    assert not connect.connect("gemini", {"command": "py"})["ok"] and gem.read_text() == "{not json"


def test_mcp_new_tools_and_prompt(tmp_path, monkeypatch):
    from joeai import mcp
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "s.json"))
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    s.ollama.url = s.comfy.url = "http://127.0.0.1:9"
    j = mcp.Joe(s)
    out = j.call("joe_make_pictures", {"description": "a raccoon eating a turtle", "count": 12, "style": "watercolor"})
    assert "12 prompt(s)" in out or "12 prompt" in out
    q = next((j.sb.missions / "Queue").glob("*.txt")).read_text()
    assert "CHUNKS: 2 x 6" in q and "STYLE: watercolor" in q
    assert "fix-spot" in j.call("joe_list_tools", {})
    assert "Nothing was queued" in j.call("joe_run_tool", {"tool": "transcribe", "files": []}) or \
        "INPUT" in j.call("joe_run_tool", {"tool": "transcribe", "files": []})
    assert "no tool called" in j.call("joe_run_tool", {"tool": "nope"})
    pic = j.sb.output / "p.png"
    pic.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    img = j.call("joe_show_picture", {"path": "p.png"})
    assert img["type"] == "image" and img["data"]
    r = mcp.handle(j, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert "polish" in r["result"]["instructions"]
    r = mcp.handle(j, {"jsonrpc": "2.0", "id": 2, "method": "prompts/get",
                       "params": {"name": "work-with-joe", "arguments": {"job": "40 candle blurbs"}}})
    assert "40 candle blurbs" in r["result"]["messages"][0]["content"]["text"]
    r = mcp.handle(j, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                       "params": {"name": "joe_show_picture", "arguments": {"path": "p.png"}}})
    assert r["result"]["content"][0]["type"] == "image"


def test_mcp_over_http_needs_the_key(tmp_path, monkeypatch):
    import json
    import threading
    import urllib.error
    import urllib.request
    from joeai.server import App, serve
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "settings.json"))
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    s.comfy.url = s.ollama.url = "http://127.0.0.1:9"
    s.mcp_key = "secret-key"
    app = App(settings=s)
    httpd = serve(app, 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/mcp"

    def post(body, key):
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, (json.loads(r.read() or b"null"))
        except urllib.error.HTTPError as e:
            return e.code, None
    try:
        assert post({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, "wrong")[0] == 401
        code, body = post({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, "secret-key")
        assert code == 200 and any(t["name"] == "joe_capabilities" for t in body["result"]["tools"])
        assert post({"jsonrpc": "2.0", "method": "notifications/initialized"}, "secret-key")[0] == 202
    finally:
        httpd.shutdown()


def test_connect_chatgpt_codex_toml(tmp_path, monkeypatch):
    import tomllib
    from joeai import connect
    monkeypatch.setenv("JOE_HOME_OVERRIDE", str(tmp_path))
    cfg = tmp_path / ".codex" / "config.toml"
    cfg.parent.mkdir()
    cfg.write_text('model = "gpt-5"\n\n[mcp_servers.other]\ncommand = "x"\n')
    entry = {"command": r"C:\Joe\python\python.exe", "args": [r"C:\Joe\Joe.pyw", "mcp"], "env": {"PYTHONIOENCODING": "utf-8"}}
    assert connect.connect("chatgpt", entry)["ok"]
    assert connect.connect("chatgpt", entry)["ok"]                     # twice: still one entry
    d = tomllib.loads(cfg.read_text())
    assert d["model"] == "gpt-5" and d["mcp_servers"]["other"]["command"] == "x"
    assert d["mcp_servers"]["joe"]["args"] == [r"C:\Joe\Joe.pyw", "mcp"]
    assert d["mcp_servers"]["joe"]["env"]["PYTHONIOENCODING"] == "utf-8"
    assert next(a for a in connect.status() if a["id"] == "chatgpt")["connected"]
    assert connect.disconnect("chatgpt")["ok"]
    d = tomllib.loads(cfg.read_text())
    assert "joe" not in d["mcp_servers"] and d["mcp_servers"]["other"]["command"] == "x"
