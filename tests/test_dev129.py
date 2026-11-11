"""dev129 (batch 5c): model file check, disk space guard, settings backup, release signing."""
import json
import struct

import pytest

from joeai import backup, modelcheck, system
from joeai.config import Settings
from joeai.sandbox import Sandbox


def safetensors(p, data_len=1000, cut=0):
    head = json.dumps({"w": {"dtype": "F16", "shape": [500], "data_offsets": [0, data_len]},
                       "__metadata__": {"x": "y"}}).encode()
    blob = struct.pack("<Q", len(head)) + head + b"\0" * data_len
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(blob[:len(blob) - cut])


def test_model_check_finds_cut_short_files(tmp_path):
    m = tmp_path / "models"
    safetensors(m / "checkpoints" / "good.safetensors")
    safetensors(m / "loras" / "short.safetensors", cut=300)
    (m / "vae" / "junk.safetensors").parent.mkdir(parents=True)
    (m / "vae" / "junk.safetensors").write_bytes(b"abc")                 # not even a header
    r = modelcheck.scan(m)
    assert r["checked"] == 3
    names = sorted(s["name"] for s in r["short"])
    assert names == ["junk.safetensors", "short.safetensors"]
    assert "2 of 3" in modelcheck.plain(r)
    assert "whole" in modelcheck.plain(modelcheck.scan(m / "checkpoints"))
    assert "No model files" in modelcheck.plain(modelcheck.scan(tmp_path / "nothing"))


def test_room_problem(tmp_path, monkeypatch):
    monkeypatch.setattr(system, "free_bytes", lambda p: 3_000_000_000)
    assert system.room_problem(tmp_path, 1_000_000_000) == ""
    msg = system.room_problem(tmp_path, 5_000_000_000)
    assert "Not enough room" in msg and "3.0 GB" in msg
    assert system.room_problem(tmp_path, 0) == ""


def test_download_refuses_when_drive_is_full(tmp_path, monkeypatch):
    import io
    import urllib.request
    from joeai import doctor

    class R(io.BytesIO):
        headers = {"Content-Length": str(50_000_000_000)}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: R(b"x"))
    monkeypatch.setattr(system, "free_bytes", lambda p: 2_000_000_000)
    logs = []
    assert not doctor._download("https://example.invalid/big", tmp_path / "big.bin", logs.append)
    assert "Not enough room" in logs[-1] and not (tmp_path / "big.bin").exists()


def test_backup_and_restore(tmp_path, monkeypatch):
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "settings.json"))
    sb = Sandbox(tmp_path / "ws").ensure()
    s = Settings()
    s.workspace = str(sb.root)
    s.web.ollama_key = "secret-key"
    s.comfy.start_command = "C:/ComfyUI/run.bat"
    s.ui.text_size = 30
    s.templates = {"custom": {"my-bulletin": {"label": "Bulletin", "base": "report"}}}
    (sb.root / "Themes" / "mine.json").write_text('{"name": "mine"}', encoding="utf-8")
    (sb.root / "Missions" / "Packs").mkdir(parents=True)
    (sb.root / "Missions" / "Packs" / "p.txt").write_text("PACK: x", encoding="utf-8")
    z = backup.make(s, sb)
    assert z.parent == sb.output / "Backups"
    import zipfile
    with zipfile.ZipFile(z) as f:
        data = json.loads(f.read("settings.json"))
        assert data["web"]["ollama_key"] == "" and "start_command" not in data["comfy"]
        assert "Themes/mine.json" in f.namelist() and "Missions/Packs/p.txt" in f.namelist()
    # a new computer: other settings, a different theme file with the same name
    sb2 = Sandbox(tmp_path / "ws2").ensure()
    s2 = Settings()
    s2.workspace = str(sb2.root)
    s2.web.ollama_key = "my-own-key"
    s2.comfy.start_command = "D:/Comfy/start.bat"
    (sb2.root / "Themes" / "mine.json").write_text('{"name": "other"}', encoding="utf-8")
    r = backup.restore(s2, sb2, z.read_bytes())
    assert r["ok"] and r["files"] == 2 and r["renamed"] == 1
    assert s2.ui.text_size == 30 and "my-bulletin" in s2.templates["custom"]
    assert s2.web.ollama_key == "my-own-key"                       # backup had no keys: kept
    assert s2.comfy.start_command == "D:/Comfy/start.bat"          # this computer's paths kept
    assert s2.workspace == str(sb2.root)
    assert (sb2.root / "Themes" / "mine (restored).json").exists()
    assert json.loads((sb2.root / "Themes" / "mine.json").read_text())["name"] == "other"


def test_restore_refuses_strangers(tmp_path):
    import io
    import zipfile
    sb = Sandbox(tmp_path / "ws").ensure()
    with pytest.raises(ValueError):
        backup.restore(Settings(), sb, b"not a zip")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("manifest.json", json.dumps({"kind": backup.MARK}))
        z.writestr("settings.json", "{}")
        z.writestr("Inbox/evil.exe", "x")
    with pytest.raises(ValueError):
        backup.restore(Settings(), sb, buf.getvalue())
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("manifest.json", json.dumps({"kind": backup.MARK}))
        z.writestr("settings.json", "{}")
        z.writestr("Themes/../../evil.txt", "x")
    with pytest.raises(ValueError):
        backup.restore(Settings(), sb, buf.getvalue())


def test_signing_rfc_vector_and_files(tmp_path):
    from joeai import sign
    sk = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
    assert sign.public_key(sk).hex() == "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
    sig = sign.sign(sk, b"")
    assert sig.hex().startswith("e5564300c360ac72") and sign.verify(sign.public_key(sk), b"", sig)
    seed = sign.b64(b"\x07" * 32)
    pub = sign.b64(sign.public_key(b"\x07" * 32))
    text = sign.sign_file_text(seed, b"abc  Joe.exe\n")
    assert sign.check(b"abc  Joe.exe\n", text, pub)
    assert not sign.check(b"abd  Joe.exe\n", text, pub)               # list changed
    assert not sign.check(b"abc  Joe.exe\n", "", pub)                 # no signature
    assert not sign.check(b"abc  Joe.exe\n", "garbage", pub)


def test_update_refuses_unsigned_when_key_is_set(tmp_path, monkeypatch):
    import contextlib
    import hashlib
    import io
    import joeai
    from joeai import sign, update
    payload = b"installer bytes"
    sums = f"{hashlib.sha256(payload).hexdigest()}  Joe-Setup-9.9.9-windows-x64.exe\n# joe-ai version 9.9.9\n".encode()
    seed = b"\x09" * 32
    good_sig = sign.sign_file_text(sign.b64(seed), sums)
    files = {"inst": payload, "sums": sums, "sig": good_sig.encode()}

    class R(io.BytesIO):
        headers = {}

    def opener(url, timeout=0):
        return contextlib.closing(R(files[url])) if url in files else (_ for _ in ()).throw(OSError("404"))
    monkeypatch.setattr(update, "updates_dir", lambda: tmp_path)
    info = {"asset": {"name": "Joe-Setup-9.9.9-windows-x64.exe", "url": "inst"}, "sums": "sums", "sig": "sig",
            "latest": "9.9.9"}
    monkeypatch.setattr(joeai, "SIGN_PUBLIC_KEY", sign.b64(sign.public_key(seed)))
    logs = []
    assert update.download(info, logs.append, opener=opener)
    monkeypatch.setattr(joeai, "SIGN_PUBLIC_KEY", sign.b64(sign.public_key(b"\x01" * 32)))   # someone else's
    assert update.download(info, logs.append, opener=opener) is None and "signature" in logs[-1]
    monkeypatch.setattr(joeai, "SIGN_PUBLIC_KEY", "")                  # not signing yet: checksums only
    assert update.download({**info, "sig": ""}, logs.append, opener=opener)
