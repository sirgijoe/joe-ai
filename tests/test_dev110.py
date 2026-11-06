"""dev110: cloud cost avoided counts pictures and video, not only words."""
import json

from joeai.stats import media_made


def test_media_made(tmp_path):
    a = tmp_path / "pics"
    a.mkdir()
    (a / "_media.json").write_text(json.dumps({"items": {"001_a.png": {}, "002_b.png": {},
                                                         "001_a_example.png": {}}}))
    v = tmp_path / "vid"
    v.mkdir()
    (v / "_media.json").write_text(json.dumps({"items": {"001_x.mp4": {"seconds": 3}, "002_y.mp4": {}}}))
    assert media_made(tmp_path) == (2, 8.0)
