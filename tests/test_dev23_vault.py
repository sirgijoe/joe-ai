"""2.3 stage 4: the key vault (vault.py). The tests use a fake vault; they never touch a real keychain."""
from __future__ import annotations

import json
import os
import sys

import pytest

from joeai import backup, vault
from joeai.config import Settings
from joeai.sandbox import Sandbox


class FakeVault(vault.Backend):
    name = "keychain"

    def __init__(self, broken_readback=False, refuse=False):
        self.store, self.broken, self.refuse, self.locked = {}, broken_readback, refuse, False
        self.deleted = []

    def put(self, acct, value):
        if self.refuse:
            return False
        self.store[acct] = value
        return True

    def get(self, acct):
        if self.locked:
            return None
        v = self.store.get(acct)
        return (v + "x") if (v is not None and self.broken) else v

    def delete(self, acct):
        self.deleted.append(acct)
        self.store.pop(acct, None)


@pytest.fixture
def fake(monkeypatch):
    fv = FakeVault()
    monkeypatch.setattr(vault, "backend", lambda path: fv)
    return fv


def _file(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _old_settings_file(path, **keys):
    s = Settings()
    s.web.ollama_key = keys.get("web", "web-secret-123")
    s.mcp_key = keys.get("mcp", "mcp-secret-456")
    s.comfort.ntfy_topic = keys.get("ntfy", "joe-topic-789")
    from dataclasses import asdict
    path.write_text(json.dumps(asdict(s)), encoding="utf-8")      # a 2.2 file: keys in plain text


def test_first_start_moves_every_key_into_the_vault(tmp_path, fake):
    p = tmp_path / "settings.json"
    _old_settings_file(p)
    s = Settings.load(p)
    assert (s.web.ollama_key, s.mcp_key, s.comfort.ntfy_topic) == ("web-secret-123", "mcp-secret-456", "joe-topic-789")
    d = _file(p)
    text = p.read_text(encoding="utf-8")
    assert "secret" not in text and "joe-topic-789" not in text
    assert d["vault"]["where"] == "keychain" and set(d["vault"]["keys"]) == {"web.ollama_key", "mcp_key", "comfort.ntfy_topic"}
    again = Settings.load(p)                                      # next start: read back from the vault
    assert (again.web.ollama_key, again.mcp_key) == ("web-secret-123", "mcp-secret-456")


def test_a_key_that_doesnt_read_back_the_same_stays_in_the_file(tmp_path, monkeypatch):
    fv = FakeVault(broken_readback=True)
    monkeypatch.setattr(vault, "backend", lambda path: fv)
    p = tmp_path / "settings.json"
    _old_settings_file(p)
    s = Settings.load(p)
    assert s.web.ollama_key == "web-secret-123" and _file(p)["web"]["ollama_key"] == "web-secret-123"
    assert "web.ollama_key" in vault.status(s, p)["kept_in_file"]


def test_a_vault_that_refuses_keeps_keys_in_the_file(tmp_path, monkeypatch):
    fv = FakeVault(refuse=True)
    monkeypatch.setattr(vault, "backend", lambda path: fv)
    p = tmp_path / "settings.json"
    _old_settings_file(p)
    Settings.load(p)
    assert _file(p)["mcp_key"] == "mcp-secret-456"
    if os.name != "nt":
        assert (p.stat().st_mode & 0o777) == 0o600


def test_a_locked_vault_never_loses_a_key(tmp_path, fake):
    p = tmp_path / "settings.json"
    _old_settings_file(p)
    Settings.load(p)
    fake.locked = True                                            # e.g. the keychain is locked today
    s = Settings.load(p)
    assert s.web.ollama_key == "" and "web.ollama_key" in vault.status(s, p)["unread"]
    s.ui.text_size = 30
    s.save(p)                                                     # saving now must not delete it
    assert not fake.deleted and "web.ollama_key" in _file(p)["vault"]["keys"]
    fake.locked = False
    assert Settings.load(p).web.ollama_key == "web-secret-123"


def test_clearing_a_key_on_purpose_removes_it_from_the_vault(tmp_path, fake):
    p = tmp_path / "settings.json"
    _old_settings_file(p)
    s = Settings.load(p)
    s.web.ollama_key = ""
    s.save(p)
    assert any(a.startswith("web.ollama_key@") for a in fake.deleted)
    assert Settings.load(p).web.ollama_key == "" and "web.ollama_key" not in _file(p)["vault"]["keys"]


def test_two_joes_on_one_computer_keep_separate_keys(tmp_path, fake):
    a, b = tmp_path / "a" / "settings.json", tmp_path / "b" / "settings.json"
    a.parent.mkdir()
    b.parent.mkdir()
    _old_settings_file(a, web="for-a")
    _old_settings_file(b, web="for-b")
    assert Settings.load(a).web.ollama_key == "for-a" and Settings.load(b).web.ollama_key == "for-b"


def test_backup_include_keys_still_works(tmp_path, fake):
    p = tmp_path / "settings.json"
    _old_settings_file(p)
    s = Settings.load(p)
    sb = Sandbox(tmp_path / "ws").ensure()
    import zipfile
    with_keys = backup.make(s, sb, keys=True)
    without = backup.make(s, sb, keys=False)
    assert "web-secret-123" in zipfile.ZipFile(with_keys).read("settings.json").decode()
    assert "web-secret-123" not in zipfile.ZipFile(without).read("settings.json").decode()
    fresh = Settings()                                            # restore on a "new computer"
    backup.restore(fresh, sb, with_keys.read_bytes())
    p2 = tmp_path / "new" / "settings.json"
    fresh.save(p2)
    assert "web-secret-123" not in p2.read_text(encoding="utf-8")
    assert Settings.load(p2).web.ollama_key == "web-secret-123"


def test_portable_joe_keeps_keys_on_its_drive(tmp_path, monkeypatch):
    monkeypatch.delenv("JOE_VAULT", raising=False)
    monkeypatch.setenv("JOE_PORTABLE", str(tmp_path / "drive"))
    from joeai import portable
    portable.forget()
    assert vault.backend(tmp_path / "settings.json").name == "file"
    p = tmp_path / "settings.json"
    s = Settings()
    s.web.ollama_key = "k"
    s.save(p)
    assert _file(p)["web"]["ollama_key"] == "k"
    assert "drive" in vault.status(s, p)["text"]
    monkeypatch.setenv("JOE_PORTABLE", "0")
    portable.forget()


def test_the_right_store_is_picked_for_each_computer(tmp_path, monkeypatch):
    monkeypatch.delenv("JOE_VAULT", raising=False)
    monkeypatch.setenv("JOE_PORTABLE", "0")
    monkeypatch.setattr(sys, "platform", "win32")
    assert vault.backend(tmp_path / "s.json").name == "dpapi"
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(vault.shutil, "which", lambda n: "/usr/bin/security" if n == "security" else None)
    assert vault.backend(tmp_path / "s.json").name == "keychain"
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(vault.shutil, "which", lambda n: "/usr/bin/secret-tool" if n == "secret-tool" else None)
    assert vault.backend(tmp_path / "s.json").name == "secret-tool"
    monkeypatch.setattr(vault.shutil, "which", lambda n: None)
    assert vault.backend(tmp_path / "s.json").name == "file"
    monkeypatch.setenv("JOE_VAULT", "file")
    monkeypatch.setattr(sys, "platform", "win32")
    assert vault.backend(tmp_path / "s.json").name == "file"


def test_the_key_never_appears_on_a_command_line(monkeypatch):
    calls = []

    class R:
        returncode, stdout = 0, 'pa"ss\\word\n'
    monkeypatch.setattr(vault, "_run", lambda cmd, stdin=None, timeout=20: calls.append((cmd, stdin)) or R())
    k = vault._Keychain("/usr/bin/security")
    assert k.put("web.ollama_key@x", 'pa"ss\\word')
    assert calls[0][0] == ["/usr/bin/security", "-i"] and 'pa\\"ss\\\\word' in calls[0][1]
    assert k.get("web.ollama_key@x") == 'pa"ss\\word'
    st = vault._SecretTool("/usr/bin/secret-tool")
    calls.clear()
    st.put("mcp_key@x", "s3cret")
    assert calls[0][1] == "s3cret" and all("s3cret" not in a for a in calls[0][0])
    assert not k.put("a@x", "two\nlines")


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows only")
def test_dpapi_round_trip_on_windows(tmp_path):
    d = vault._DPAPI(tmp_path / "settings.json")
    assert d.put("web.ollama_key@t", "héllo-key")
    raw = (tmp_path / "keys.dpapi.json").read_text(encoding="utf-8")
    assert "héllo" not in raw and d.get("web.ollama_key@t") == "héllo-key"
    d.delete("web.ollama_key@t")
    assert d.get("web.ollama_key@t") is None


def test_setup_privacy_says_where_keys_are(tmp_path, fake):
    s = Settings()
    assert "Mac Keychain" in vault.status(s, tmp_path / "s.json")["text"]
    html = (__import__("pathlib").Path(__file__).parent.parent / "joeai" / "ui" / "index.html").read_text(encoding="utf-8")
    assert 'id="vault-text"' in html


def test_going_back_to_an_older_joe_and_forward_again_keeps_the_keys(tmp_path, fake):
    """Fable review: 2.2 saves the settings file without the "vault" part and with blank keys; 2.3
    must find the keys still in the vault instead of leaving them stranded."""
    p = tmp_path / "settings.json"
    _old_settings_file(p)
    Settings.load(p)                                              # 2.3: keys move into the vault
    d = _file(p)
    d.pop("vault")                                                # 2.2 opened and saved this file
    d["mcp_key"] = "made-by-2.2"                                  # ...and made itself a new connector key
    p.write_text(json.dumps(d), encoding="utf-8")
    s = Settings.load(p)                                          # 2.3 again
    assert s.web.ollama_key == "web-secret-123" and s.comfort.ntfy_topic == "joe-topic-789"
    assert s.mcp_key == "made-by-2.2"                             # what the file has wins
    d = _file(p)
    assert set(d["vault"]["keys"]) == {"web.ollama_key", "mcp_key", "comfort.ntfy_topic"}
    assert "secret" not in p.read_text(encoding="utf-8") and "made-by-2.2" not in p.read_text(encoding="utf-8")
    assert not vault.status(s, p)["unread"] and not fake.deleted


def test_a_key_cleared_on_purpose_stays_cleared(tmp_path, fake):
    p = tmp_path / "settings.json"
    _old_settings_file(p)
    s = Settings.load(p)
    s.web.ollama_key = ""
    s.save(p)
    assert Settings.load(p).web.ollama_key == ""                  # the file has its "vault" part: no look-around


def test_a_backup_without_keys_leaves_out_the_ai_server_key(tmp_path):
    import zipfile
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    s.ollama.engine_key = "engine-secret-321"
    sb = Sandbox(s.workspace_path).ensure()
    with zipfile.ZipFile(backup.make(s, sb, keys=False)) as z:
        assert "engine-secret-321" not in z.read("settings.json").decode("utf-8")
    with zipfile.ZipFile(backup.make(s, sb, keys=True)) as z:
        assert "engine-secret-321" in z.read("settings.json").decode("utf-8")


# ------------------------------------------------------------------ Linux night shift (cron has no session)
def test_session_env_points_secret_tool_at_the_signed_in_users_bus(tmp_path):
    root = tmp_path / "run"
    (root / "1000").mkdir(parents=True)
    (root / "1000" / "bus").write_text("")
    env = vault.session_env({"PATH": "/usr/bin"}, uid=1000, runtime_root=str(root))
    assert env["DBUS_SESSION_BUS_ADDRESS"] == f"unix:path={root / '1000' / 'bus'}"
    assert env["XDG_RUNTIME_DIR"] == str(root / "1000") and env["PATH"] == "/usr/bin"
    # a session is already there (the desktop): nothing to change
    assert vault.session_env({"DBUS_SESSION_BUS_ADDRESS": "unix:path=/x"}, uid=1000, runtime_root=str(root)) is None
    # nobody is signed in (no bus): nothing to point at
    assert vault.session_env({}, uid=1001, runtime_root=str(root)) is None


def test_secret_tool_runs_with_that_session_when_cron_has_none(monkeypatch):
    seen = []

    def fake_run(cmd, stdin=None, timeout=20, env=None):
        seen.append(env)
        return None
    monkeypatch.setattr(vault, "_run", fake_run)
    monkeypatch.setattr(vault, "session_env", lambda *a, **k: {"DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus"})
    tool = vault._SecretTool("/usr/bin/secret-tool")
    assert tool.get("web.ollama_key@abc") is None and tool.put("web.ollama_key@abc", "k") is False
    tool.delete("web.ollama_key@abc")
    assert len(seen) == 3 and all(e == {"DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus"} for e in seen)
