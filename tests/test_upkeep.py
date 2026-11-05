import json

import pytest

from joeai import system, upkeep
from joeai.http import HttpError


@pytest.fixture(autouse=True)
def tmp_config(tmp_path, monkeypatch):
    monkeypatch.setattr(upkeep, "_cache_dir", lambda: tmp_path)
    upkeep._UPD.clear()
    yield


def test_builtin_picks_are_valid():
    assert upkeep.valid_picks(upkeep._builtin())


@pytest.mark.parametrize("bad", [
    {"writing": []},
    {"writing": [{"min_vram": 4, "name": "rm -rf /", "size_gb": 2}]},
    {"writing": [{"min_vram": 4, "name": "ok:4b", "size_gb": 9999}]},
    {"writing": [{"min_vram": 4, "name": "ok:4b"}]},
    "nope",
])
def test_bad_picks_rejected(bad):
    assert not upkeep.valid_picks(bad)


def test_picks_offline_uses_builtin():
    assert upkeep.picks(net=False) == upkeep._builtin()


def test_picks_from_github_then_cached():
    new = {"version": 1, "writing": [{"min_vram": 0, "name": "newmodel:9b", "size_gb": 6}],
           "talk": {"name": "tiny:1b", "size_gb": 1}}
    calls = []

    def fetch(*a, **k):
        calls.append(a)
        return new
    assert upkeep.picks(fetch, net=True)["writing"][0]["name"] == "newmodel:9b"
    assert upkeep.picks(fetch, net=True)["talk"]["name"] == "tiny:1b"
    assert len(calls) == 1                         # second time came from the weekly cache


def test_bad_github_picks_fall_back():
    assert upkeep.picks(lambda *a, **k: {"writing": "junk"}, net=True) == upkeep._builtin()


def test_update_check_finds_newer_things():
    def fetch(method, url, **k):
        if url.endswith("/api/version"):
            return {"version": "0.9.0"}
        if "ollama/ollama" in url:
            return {"tag_name": "v0.12.1"}
        raise HttpError("no")
    models = [{"name": "qwen3:14b", "digest": "aaa"}, {"name": "same:1b", "digest": "bbb"}]
    out = upkeep.check_updates("http://x", models, force=True, fetch=fetch,
                               digest=lambda n: "zzz" if n == "qwen3:14b" else "bbb")
    ids = {i["id"] for i in out}
    assert ids == {"update-ollama", "refresh-qwen3:14b"}
    assert all(i["optional"] for i in out)
    assert upkeep.known_updates() == out


def test_update_check_tolerates_no_network():
    def fetch(*a, **k):
        raise HttpError("down")
    def digest(n):
        raise OSError("down")
    assert upkeep.check_updates("http://x", [{"name": "a:1b", "digest": "d"}], force=True,
                                fetch=fetch, digest=digest) == []


def test_torch_index():
    assert "cu128" in upkeep.torch_index("nvidia", False)
    assert "rocm" in upkeep.torch_index("amd", False)
    assert "cpu" in upkeep.torch_index("intel", False)
    assert upkeep.torch_index("apple", True) is None


def test_unpack_source_keeps_models(tmp_path):
    import zipfile
    dest = tmp_path / "ComfyUI"
    (dest / "models" / "checkpoints").mkdir(parents=True)
    (dest / "models" / "checkpoints" / "mine.safetensors").write_text("x")
    (dest / "old.py").write_text("old")
    z = tmp_path / "src.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("owner-ComfyUI-abc/main.py", "new")
        f.writestr("owner-ComfyUI-abc/old.py", "new")
        f.writestr("owner-ComfyUI-abc/models/checkpoints/put_here", "")
    upkeep._unpack_source(z, dest)
    assert (dest / "main.py").read_text() == "new"
    assert (dest / "old.py").read_text() == "new"
    assert (dest / "models" / "checkpoints" / "mine.safetensors").exists()


def test_unpack_refuses_unsafe_paths(tmp_path):
    import zipfile
    z = tmp_path / "evil.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("top/../../escape.txt", "x")
    with pytest.raises(ValueError):
        upkeep._unpack_source(z, tmp_path / "ComfyUI")


def test_install_routes(monkeypatch):
    monkeypatch.setattr(system, "package_manager", lambda: None)
    monkeypatch.setattr(system, "WINDOWS", False)
    monkeypatch.setattr(system, "MAC", True)
    monkeypatch.setattr(system, "LINUX", False)
    assert system.install_plan("ollama")["kind"] == "joe"
    assert system.install_plan("comfyui")["kind"] == "joe"
    monkeypatch.setattr(system, "MAC", False)
    monkeypatch.setattr(system, "LINUX", True)
    p = system.install_plan("ollama")
    assert p["kind"] == "command" and "ollama.com/install.sh" in p["cmd"][0]
    monkeypatch.setattr(system, "package_manager", lambda: "apt")
    assert system.install_plan("ollama")["kind"] == "command"     # apt has no Ollama
    from joeai import doctor
    assert "apt" not in doctor.install_how("ollama")


def test_offline_switch(monkeypatch):
    monkeypatch.setenv("JOE_OFFLINE", "1")
    assert upkeep.online() is False
