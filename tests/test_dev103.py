"""dev103: import your own ComfyUI workflows, optionally one per picture style."""
import json

import pytest

from joeai import comfy

API = {"3": {"class_type": "KSampler", "inputs": {"positive": ["6", 0], "negative": ["7", 0]}},
       "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "a cat"}},
       "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry"}}}


def test_parse_template_rejects_ui_format():
    with pytest.raises(comfy.WorkflowError, match=r"Export \(API\)"):
        comfy.parse_template(json.dumps({"nodes": [], "links": []}), "mine.json")
    assert comfy.parse_template(json.dumps(API))["3"]["class_type"] == "KSampler"


def test_import_saves_style_workflow(tmp_path):
    from joeai.server import App
    app = App.__new__(App)
    app.sb = type("SB", (), {"workflows": tmp_path / "Workflows"})()
    app.log = lambda m: None
    r = app.import_workflow(json.dumps(API), "my photo.json", "photo")
    assert r["ok"] and (tmp_path / "Workflows" / "style-photo.json").is_file()
    assert not app.import_workflow(json.dumps({"nodes": [], "links": []}), "x.json", "")["ok"]
    assert app.import_workflow(json.dumps(API), "Fancy Flux!.json", "")["file"] == "Fancy Flux.json"
