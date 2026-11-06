"""whisper.cpp transcriber: names, JSON reading, choosing it."""
from pathlib import Path

from joeai import tools, whispercpp as wc
from joeai.config import Settings


def test_model_names():
    assert wc.model_name("base.en") == "base.en"
    assert wc.model_name("large") == "large-v3"
    assert wc.model_name("turbo") == "large-v3-turbo"
    assert wc.model_name("weird") == "base.en"
    assert wc.model_file("small").name == "ggml-small.bin"


def test_parse_json_segments_and_words():
    data = {"result": {"language": "es"}, "transcription": [
        {"offsets": {"from": 0, "to": 400}, "text": " Hola"},
        {"offsets": {"from": 400, "to": 900}, "text": " amigos."},
        {"offsets": {"from": 3000, "to": 3500}, "text": " Bien"},
        {"offsets": {"from": 3500, "to": 3600}, "text": " "}]}
    r = wc.parse_json(data)
    assert r["language"] == "es" and len(r["segments"]) == 3 and r["segments"][1] == {"s": 0.4, "e": 0.9, "t": "amigos."}
    w = wc.parse_json(data, words=True)
    assert [s["t"] for s in w["segments"]] == ["Hola amigos.", "Bien"]     # joined, split at the pause/full stop
    assert len(w["words"]) == 3 and w["seconds"] == 3.5


def test_backend_choice(monkeypatch):
    s = Settings()
    monkeypatch.setattr(wc, "exe", lambda: None)
    assert tools.hearing_backend(s) == "faster-whisper"
    monkeypatch.setattr(wc, "exe", lambda: "/usr/bin/whisper-cli")
    assert tools.hearing_backend(s) == "whisper.cpp" and tools.hearing_ready(s, voice_ok=False)
    s.voice.transcriber = "faster-whisper"
    assert tools.hearing_backend(s) == "faster-whisper" and not tools.hearing_ready(s, voice_ok=False)
    st = {t["id"]: t for t in tools.tool_status({"voice": False, "whispercpp": True, "ffmpeg": True})}
    assert st["transcribe"]["ok"]


def test_transcribe_runs_cli(tmp_path, monkeypatch):
    import json
    import subprocess
    wav = tmp_path / "rec.wav"
    wav.write_bytes(b"RIFF")
    model = tmp_path / "ggml-base.en.bin"
    model.write_bytes(b"m")
    monkeypatch.setattr(wc, "exe", lambda: "whisper-cli")
    monkeypatch.setattr(wc, "get_model", lambda n, log, progress=None: model)
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        Path(cmd[cmd.index("-of") + 1] + ".json").write_text(json.dumps(
            {"result": {"language": "en"}, "transcription": [{"offsets": {"from": 0, "to": 1000}, "text": " hi"}]}))
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(wc.subprocess, "run", fake_run)
    r = wc.transcribe(wav, "base.en", "es", words=True, log=lambda m: None)
    assert r["ok"] and r["segments"][0]["t"] == "hi"
    assert seen["cmd"][seen["cmd"].index("-l") + 1] == "en"          # *.en models: English
    assert "-sow" in seen["cmd"] and not (tmp_path / "rec.json").exists()
