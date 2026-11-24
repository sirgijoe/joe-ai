"""Settings files: true/false isn't a number, and a whole decimal counts for a whole-number setting."""
import json

from joeai.config import Settings


def _load(tmp_path, data):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return Settings.load(p)


def test_true_is_not_a_port(tmp_path):
    s = _load(tmp_path, {"phone": {"port": True}})
    assert s.phone.port == 8770 and type(s.phone.port) is int


def test_false_is_not_a_float(tmp_path):
    fresh = Settings()
    floats = [(sec.name, f.name) for sec in fresh.__dataclass_fields__.values()
              if hasattr(getattr(fresh, sec.name), "__dataclass_fields__")
              for f in getattr(fresh, sec.name).__dataclass_fields__.values()
              if type(getattr(getattr(fresh, sec.name), f.name)) is float]
    assert floats, "expected at least one decimal setting to test"
    sec, name = floats[0]
    s = _load(tmp_path, {sec: {name: False}})
    assert getattr(getattr(s, sec), name) == getattr(getattr(fresh, sec), name)
    assert type(getattr(getattr(s, sec), name)) is float


def test_whole_decimal_taken_as_whole_number(tmp_path):
    s = _load(tmp_path, {"ui": {"text_size": 22.0}})
    assert s.ui.text_size == 22 and type(s.ui.text_size) is int
    s = _load(tmp_path, {"ui": {"text_size": 26.0}})
    assert s.ui.text_size == 26 and type(s.ui.text_size) is int


def test_part_decimal_leaves_default(tmp_path):
    s = _load(tmp_path, {"ui": {"text_size": 22.5}})
    assert s.ui.text_size == 22 and type(s.ui.text_size) is int
    s = _load(tmp_path, {"ui": {"text_size": 26.5}})
    assert s.ui.text_size == 22


def test_bools_still_set_bools(tmp_path):
    fresh = Settings()
    s = _load(tmp_path, {"schedule": {"enabled": not fresh.schedule.enabled}})
    assert s.schedule.enabled is (not fresh.schedule.enabled)
