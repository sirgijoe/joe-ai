"""2.3 stage 2: pinned downloads (uv, whisper.cpp), FFmpeg reads local files only, a quick Talk model."""
from __future__ import annotations

import hashlib
import io
import shutil
import subprocess
import zipfile

import pytest

from joeai import addons, ffguard, whispercpp
from joeai.config import Settings


# ------------------------------------------------------------------ pinned + checked downloads
def test_uv_is_one_known_release_with_a_checksum_for_every_download():
    assert "/latest/" not in addons.UV_RELEASE and addons.UV_VERSION in addons.UV_RELEASE
    for plat, mach in (("win32", "AMD64"), ("win32", "ARM64"), ("darwin", "arm64"), ("darwin", "x86_64"),
                       ("linux", "x86_64"), ("linux", "aarch64")):
        asset = addons.uv_asset(plat, mach)
        assert len(addons.UV_SHA256[asset]) == 64 and int(addons.UV_SHA256[asset], 16) >= 0


def test_a_uv_download_that_doesnt_match_is_never_unpacked(tmp_path, monkeypatch):
    monkeypatch.setattr(addons, "addons_dir", lambda: tmp_path)
    monkeypatch.setattr(addons, "uv_exe", lambda: None)
    monkeypatch.setattr(addons, "uv_asset", lambda *a: "uv-x86_64-unknown-linux-gnu.tar.gz")
    monkeypatch.setattr(addons, "_winget", lambda *a: None)

    class R(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(addons.urllib.request, "urlopen", lambda *a, **k: R(b"not the real uv"))
    unpacked = []
    monkeypatch.setattr(addons, "_unpack_uv", lambda *a: unpacked.append(a))
    said = []
    assert addons.get_uv(said.append) is None
    assert not unpacked and any("didn't match the checksum" in s for s in said)


def test_sha256_ok():
    data = b"abc"
    good = hashlib.sha256(data).hexdigest()
    assert addons.sha256_ok(data, good) and addons.sha256_ok(data, good.upper())
    assert not addons.sha256_ok(data, "0" * 64) and not addons.sha256_ok(data, "")


def test_whispercpp_is_pinned_and_a_bad_zip_is_thrown_away(tmp_path, monkeypatch):
    assert "/latest/" not in whispercpp.RELEASE and whispercpp.VERSION in whispercpp.RELEASE
    assert len(whispercpp.WIN_ZIP_SHA256) == 64
    monkeypatch.setattr(whispercpp, "WINDOWS", True)
    monkeypatch.setattr(whispercpp, "home", lambda: tmp_path / "w")
    monkeypatch.setattr(whispercpp, "exe", lambda: None)

    def fake_download(url, dest, log, progress=None):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("Release/whisper-cli.exe", b"evil")
        dest.write_bytes(buf.getvalue())
        return True
    monkeypatch.setattr(addons, "_download", fake_download)
    said = []
    assert whispercpp.install(said.append, approved=True) is False
    assert not (tmp_path / "w" / "bin").exists() and not (tmp_path / "w" / whispercpp.WIN_ZIP).exists()
    assert any("didn't match the checksum" in s for s in said)


# ------------------------------------------------------------------ FFmpeg: local files only
def test_every_ffmpeg_input_gets_the_whitelist():
    cmd = ["C:\\tools\\ffmpeg.exe", "-y", "-i", "a.mp4", "-i", "b.wav", "out.mp4"]
    assert ffguard.guard(cmd) == ["C:\\tools\\ffmpeg.exe", "-y", "-protocol_whitelist", "file,pipe,fd", "-i", "a.mp4",
                                  "-protocol_whitelist", "file,pipe,fd", "-i", "b.wav", "out.mp4"]
    assert ffguard.guard(ffguard.guard(cmd)) == ffguard.guard(cmd)        # never twice
    assert ffguard.guard(["/usr/bin/ffmpeg", "-filters"]) == ["/usr/bin/ffmpeg", "-filters"]
    assert ffguard.guard(["qpdf", "-i", "x"]) == ["qpdf", "-i", "x"]      # other programs untouched
    assert ffguard.guard("ffmpeg -i x") == "ffmpeg -i x"


def test_the_guard_is_in_place_for_every_subprocess_call():
    import joeai  # noqa: F401
    assert getattr(subprocess.Popen, "_joe_guard", False)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg isn't installed here")
def test_a_media_file_cant_send_ffmpeg_to_the_network(tmp_path):
    import joeai  # noqa: F401
    bad = tmp_path / "evil.m3u8"
    bad.write_text("#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\nhttp://127.0.0.1:9/a.ts\n#EXT-X-ENDLIST\n",
                   encoding="utf-8")
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(bad), "-f", "null", "-"], capture_output=True,
                       text=True, timeout=60)
    assert r.returncode != 0 and "not on whitelist" in r.stderr


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg isn't installed here")
def test_ordinary_ffmpeg_work_still_runs(tmp_path):
    import joeai  # noqa: F401
    a = tmp_path / "a.png"
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=32x32", "-frames:v", "1",
                        str(a)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and a.exists()
    lst = tmp_path / "list.txt"
    lst.write_text(f"file '{a.as_posix()}'\nfile '{a.as_posix()}'\n", encoding="utf-8")
    out = tmp_path / "b.mp4"
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-pix_fmt",
                        "yuv420p", str(out)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and out.stat().st_size > 0


# ------------------------------------------------------------------ System check: a quick Talk model
def _issues(monkeypatch, models, talk=""):
    from joeai import doctor, hardware
    from joeai.services import ServiceManager
    from fake_ollama import FakeOllama
    fake = FakeOllama()
    try:
        s = Settings()
        s.ollama.url = fake.url
        s.comfy.url = "http://127.0.0.1:9"
        s.voice.talk_model = talk
        monkeypatch.setattr(hardware, "gpu", lambda: {"name": "Test GPU", "vendor": "nvidia"})
        monkeypatch.setattr(hardware, "vram_total_gb", lambda: 12.0)
        monkeypatch.setattr(doctor, "ollama_models", lambda sm: models)
        return {i["id"]: i for i in doctor.check(s, ServiceManager(s))["issues"]}
    finally:
        fake.close()


def test_blank_talk_model_with_a_small_one_installed_is_offered(monkeypatch):
    big = {"name": "gemma4:12b", "writer": True, "params": "12B", "size_gb": 8, "family": "gemma4"}
    small = {"name": "qwen3:4b", "writer": True, "params": "4.0B", "size_gb": 2.6, "family": "qwen3"}
    ids = _issues(monkeypatch, [big, small])
    assert ids["use-talk-model"]["model"] == "qwen3:4b" and ids["use-talk-model"]["set"] == "talk"
    assert "pull-talk-model" not in ids
    assert "use-talk-model" not in _issues(monkeypatch, [big, small], talk="qwen3:4b")


def test_blank_talk_model_without_a_small_one_offers_a_download_even_without_voice(monkeypatch):
    from joeai import doctor
    monkeypatch.setattr(doctor, "addons_mod_voice_ready", lambda: False)
    big = {"name": "gemma4:12b", "writer": True, "params": "12B", "size_gb": 8, "family": "gemma4"}
    ids = _issues(monkeypatch, [big])
    assert ids["pull-talk-model"]["set"] == "talk" and "use-talk-model" not in ids


def test_use_it_for_talk_only_changes_the_talk_model(tmp_path, monkeypatch):
    from joeai.server import App
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "settings.json"))
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    s.ollama.url = s.comfy.url = "http://127.0.0.1:9"
    s.ollama.text_model = "gemma4:12b"
    app = App(settings=s)
    r = app.doctor_fix({"action": "use", "model": "qwen3:4b", "set": "talk", "approved": True})
    assert r["ok"] and app.settings.voice.talk_model == "qwen3:4b" and app.settings.ollama.text_model == "gemma4:12b"
