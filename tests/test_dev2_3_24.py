"""2.3.0.dev24: a copy started with its own settings file (JOE_CONFIG) has its own lock file, so it never
opens, or shuts down as "an older version", the everyday Joe that uses the same settings folder."""
from joeai import app, config


def test_everyday_joe_keeps_app_json(monkeypatch):
    monkeypatch.delenv("JOE_CONFIG", raising=False)
    assert app._lock_path() == config.config_dir() / "app.json"


def test_own_settings_file_gets_its_own_lock(tmp_path, monkeypatch):
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "Joe TEST" / "settings.json"))
    a = app._lock_path()
    assert a.parent == config.config_dir() and a.name.startswith("app-") and a.name != "app.json"
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "other" / "settings.json"))
    assert app._lock_path() != a                       # two test copies don't share one either
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "Joe TEST" / "settings.json"))
    assert app._lock_path() == a                       # same settings file: same lock, so it reopens itself


def test_pointing_at_the_usual_settings_file_is_the_everyday_joe(monkeypatch):
    monkeypatch.setenv("JOE_CONFIG", str(config.config_dir() / "settings.json"))
    assert app._lock_path() == config.config_dir() / "app.json"


def test_a_test_copy_never_sees_the_everyday_joes_lock(tmp_path, monkeypatch):
    monkeypatch.delenv("JOE_CONFIG", raising=False)
    config.config_dir().mkdir(parents=True, exist_ok=True)
    everyday = app._lock_path()
    everyday.write_text('{"port": 9, "token": "x", "pid": 1}', encoding="utf-8")
    try:
        monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "settings.json"))
        assert not app._lock_path().exists() and app._existing_url() is None
    finally:
        everyday.unlink()
