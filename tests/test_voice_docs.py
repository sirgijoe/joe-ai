import json
import shutil
import sys
import time
from pathlib import Path

import pytest

from joeai import addons, chat
from joeai.config import Settings
from joeai.engine import Engine
from joeai.mission import MissionError, mission_to_dict, parse, to_text
from joeai.sandbox import Sandbox
from joeai.server import App

from fake_ollama import FakeOllama

HERE = Path(__file__).parent


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "settings.json"))
    monkeypatch.setenv("JOE_ADDONS", str(tmp_path / "addons"))
    fake = FakeOllama()
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    s.ollama.url = fake.url
    s.comfy.url = "http://127.0.0.1:9"
    s.engine.retry_backoff_s = 0
    s.engine.gpu_temp_pause_c = 0
    s.engine.keep_awake = False
    a = App(settings=s)
    yield a
    a.voice.close()
    fake.close()


def test_export_key_parses_and_round_trips():
    m = parse("=== JOE MISSION ===\nTASK: Guide  SAVE: g.md  CHUNKS: 1 x 2\nEXPORT: docx, PDF\n=== END ===")
    assert m.jobs[0].export == ["docx", "pdf"]
    d = mission_to_dict(m)
    assert parse(to_text("", "", d["tasks"])).jobs[0].export == ["docx", "pdf"]
    for bad in ["EXPORT: mp3", "TYPE: image\nEXPORT: pdf"]:
        with pytest.raises(MissionError):
            parse(f"=== JOE MISSION ===\nTASK: x  SAVE: a  CHUNKS: 1 x 1\n{bad}\n=== END ===")


@pytest.mark.skipif(not shutil.which("pandoc"), reason="no pandoc")
def test_engine_exports_finished_copies(app):
    m = parse("=== JOE MISSION ===\nTASK: Guide  SAVE: docs/guide.md  CHUNKS: 1 x 2\nEXPORT: docx, epub\n=== END ===")
    st = Engine(app.settings, app.sb, log=lambda x: None).run_mission(m)[0]
    assert st.status == "done", st.note
    assert (app.sb.output / "docs" / "guide.docx").stat().st_size > 1000
    assert (app.sb.output / "docs" / "guide.epub").stat().st_size > 1000
    r = app.export("Output/docs/guide.md", ["odt"])
    assert r["ok"] and r["made"] == ["guide.odt"]


def test_split_reply_strips_markdown_and_finds_mission():
    say, mission = chat.split_reply("**Sure!** Here:\n=== JOE MISSION ===\nTASK: a  SAVE: b\n=== END ===\nEnjoy")
    assert mission.startswith("=== JOE MISSION ===") and "**" not in say and "Enjoy" in say


def test_talk_drafts_a_mission_but_never_runs_it(app):
    r = app.talk("please make a mission for tips")
    assert r["ok"] and r["mission"] and r["say"]
    parse(r["mission"])
    assert not app.running                                  # Joe never starts a run himself
    r2 = app.talk("hi joe")
    assert r2["ok"] and "**" not in r2["say"]
    assert len(app.chat_history) == 4


def test_voice_worker_listen_and_speak(app, monkeypatch):
    monkeypatch.setattr(addons, "voice_ready", lambda: True)
    app.voice = addons.VoiceWorker(python=sys.executable, script=HERE / "fake_voice_worker.py")
    r = app.listen(_wav(2), "wav")
    assert r["ok"] and "mission" in r["text"]
    assert not list((addons.voice_dir() / "tmp").glob("heard_*"))   # recordings are never kept
    audio, err = app.speak("Hello from Joe")
    assert not err and audio.startswith(b"RIFF")
    assert not list((addons.voice_dir() / "tmp").glob("say_*"))


def test_voice_not_set_up_is_friendly(app):
    assert app.listen(b"x", "webm")["ok"] is False
    assert "set up" in app.speak("hi")[1]


def test_installs_need_approval():
    with pytest.raises(PermissionError):
        addons.install_voice(print)
    with pytest.raises(PermissionError):
        addons.install_pandoc(print)


def test_voice_http_routes(app, monkeypatch):
    import urllib.request
    from joeai.server import serve
    import threading
    monkeypatch.setattr(addons, "voice_ready", lambda: True)
    app.voice = addons.VoiceWorker(python=sys.executable, script=HERE / "fake_voice_worker.py")
    httpd = serve(app)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    req = urllib.request.Request(base + "/api/voice/listen", data=_wav(2), method="POST",
                                 headers={"X-NR-Token": app.token, "Content-Type": "audio/wav"})
    assert json.loads(urllib.request.urlopen(req, timeout=10).read())["text"]
    req = urllib.request.Request(base + "/api/voice/speak", data=b'{"text": "hi"}', method="POST",
                                 headers={"X-NR-Token": app.token, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        assert r.headers["Content-Type"] == "audio/wav" and r.read().startswith(b"RIFF")
    req = urllib.request.Request(base + "/api/voice/listen", data=b"abc", method="POST", headers={})
    with pytest.raises(urllib.error.HTTPError):                 # no token, no microphone upload
        urllib.request.urlopen(req, timeout=10)
    httpd.shutdown()


def test_worker_chunks_sentences():
    import importlib.util
    spec = importlib.util.spec_from_file_location("vw", Path(addons.__file__).with_name("voice_worker.py"))
    vw = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vw)                                # imports nothing heavy at load time
    parts = vw.chunks("One. " * 200)
    assert all(len(p) <= 380 for p in parts) and len(parts) > 2


def _wav(seconds):
    import struct
    n = int(24000 * seconds)
    return (b"RIFF" + struct.pack("<I", 36 + n * 2) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, 24000, 48000, 2, 16)
            + b"data" + struct.pack("<I", n * 2) + b"\0\0" * n)


def test_my_voice_needs_consent_and_stays_private(app, monkeypatch):
    assert "own voice" in addons.save_my_voice(_wav(30), consent=False)
    assert "too short" in addons.save_my_voice(_wav(2), consent=True)
    assert "WAV" in addons.save_my_voice(b"nope" * 50000, consent=True)
    assert addons.save_my_voice(_wav(30), consent=True) == "" and addons.has_my_voice()
    # Never inside the workspace (missions, exports and the app folder can't carry it).
    assert app.sb.root not in addons.my_voice_path().parents
    addons.delete_my_voice()
    assert not addons.has_my_voice()


def test_speak_uses_my_voice_only_when_idle(app, monkeypatch):
    monkeypatch.setattr(addons, "voice_ready", lambda: True)
    monkeypatch.setattr(addons, "clone_ready", lambda: True)
    calls = []

    class W:
        def __init__(self, name):
            self.name = name

        def call(self, req, timeout=0):
            calls.append((self.name, req))
            Path(req["out"]).write_bytes(b"RIFFxxxxWAVE")
            return {"ok": True}

        def close(self):
            pass
    app.voice, app.clone = W("kokoro"), W("clone")
    addons.save_my_voice(_wav(30), consent=True)
    app.settings.voice.voice = "mine"
    assert app.speak("hello")[0].startswith(b"RIFF") and calls[-1][0] == "clone"
    assert calls[-1][1]["ref"].endswith("reference.wav")
    monkeypatch.setattr(type(app), "running", property(lambda self: True))
    app.speak("busy now")
    assert calls[-1][0] == "kokoro" and calls[-1][1]["voice"] == "am_adam"   # GPU stays free


def test_my_voice_http_route_requires_consent_header(app):
    import urllib.request, threading
    from joeai.server import serve
    httpd = serve(app)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    def post(headers):
        req = urllib.request.Request(base + "/api/voice/myvoice", data=_wav(20), method="POST",
                                     headers={"X-NR-Token": app.token, "Content-Type": "audio/wav", **headers})
        return json.loads(urllib.request.urlopen(req, timeout=10).read())
    assert post({})["ok"] is False
    assert post({"X-Consent": "my-own-voice"})["ok"] and app.settings.voice.voice == "mine"
    httpd.shutdown()


def test_install_log_is_saved(tmp_path, monkeypatch):
    monkeypatch.setenv("JOE_ADDONS", str(tmp_path / "ad"))
    seen = []
    addons.install_log(seen.append)("step one")
    assert seen == ["step one"] and "step one" in (tmp_path / "ad" / "install.log").read_text()


def test_uv_prefers_joes_own_copy(tmp_path, monkeypatch):
    monkeypatch.setenv("JOE_ADDONS", str(tmp_path / "ad"))
    exe = "uv.exe" if sys.platform == "win32" else "uv"
    own = tmp_path / "ad" / "bin" / exe
    own.parent.mkdir(parents=True)
    own.write_text("x")
    assert addons.uv_exe() == str(own)


def test_real_worker_isnt_shadowed_by_joes_modules():
    # joeai/http.py sits next to the worker; the helper must still get the real http.client.
    import subprocess
    w = Path(addons.__file__).with_name("voice_worker.py")
    for flags in (["-u"], ["-I", "-u"]):
        p = subprocess.run([sys.executable, *flags, str(w)], input='{"cmd": "ping"}\n',
                           capture_output=True, text=True, timeout=30)
        assert '@@JOE@@{"ok": true, "http": "http.client"}' in p.stdout, p.stderr


def test_read_this_reads_the_text_instead_of_making_a_mission(app):
    pasted = ("VOICE SPEED slider at the top of the Talk screen, from 0.7x to 1.8x.\n"
              "* Faster start: Joe now speaks the first sentence while the next ones are made.")
    for msg in (pasted + "\nread this", "read this to me\n" + pasted, "Please read it out loud:\n" + pasted,
                "read this: " + pasted.replace("\n", " ")):
        r = app.talk(msg)
        assert r["ok"] and not r["mission"], msg
        assert r["say"].startswith("VOICE SPEED slider") and "*" not in r["say"]
    assert chat.read_request("read me a story about dragons") == ""        # that's a real request
    assert chat.read_request("hi joe") == ""


def test_talk_streams_pieces_then_done(app):
    import urllib.request, threading
    from joeai.server import serve
    httpd = serve(app)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    req = urllib.request.Request(base + "/api/talk/stream", data=b'{"text": "please make a mission for tips"}',
                                 method="POST", headers={"X-NR-Token": app.token, "Content-Type": "application/json"})
    lines = [json.loads(l) for l in urllib.request.urlopen(req, timeout=20).read().splitlines() if l.strip()]
    assert lines[0]["t"] == "delta" and lines[-1]["t"] == "done"
    assert lines[-1]["ok"] and lines[-1]["mission"] and "raw" not in lines[-1]
    assert len(app.chat_history) == 2
    httpd.shutdown()


def _docx(path, paras):
    import zipfile
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paras)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", f'<w:document xmlns:w="x"><w:body>{body}</w:body></w:document>')


def test_dropped_files_become_text(app, tmp_path):
    from joeai import attach
    p = attach.save_drop(app.sb, "../../evil:name.txt", b"Hello from a text file.")
    assert p.parent == app.sb.inbox / "dropped" and ":" not in p.name and ".." not in p.name
    assert attach.save_drop(app.sb, "evil:name.txt", b"x").name != p.name          # never overwrites
    d = tmp_path / "notes.docx"
    _docx(d, ["First line &amp; more", "Second line"])
    assert attach.extract(d)["text"] == "First line & more\nSecond line"
    h = tmp_path / "page.html"
    h.write_text("<html><script>x()</script><h1>Title</h1><p>Body text</p></html>")
    assert attach.extract(h)["text"].split() == ["Title", "Body", "text"]
    b = tmp_path / "blob.bin"
    b.write_bytes(b"\x00\x01\x02" * 100)
    with pytest.raises(ValueError):
        attach.extract(b)


def test_read_it_reads_the_dropped_file(app):
    f = {"id": "1", "name": "note.md", "kind": "text", "text": "# Hi\n**Joe** reads this file."}
    r = chat.prepare(app, [], "read it", [f])["final"]
    assert r["say"] == "Hi\nJoe reads this file." and not r["mission"]
    p = chat.prepare(app, [], "what does it say?", [f])
    assert "ATTACHED FILE: note.md" in p["msgs"][-1]["content"]


def test_pictures_need_a_vision_model(app):
    pic = {"id": "2", "name": "a.png", "kind": "image", "image_b64": "aGk="}
    r = chat.prepare(app, [], "what is this?", [pic])
    assert "final" in r and "vision model" in r["final"]["say"]


def test_attach_route_and_stream_uses_files(app):
    import urllib.request, urllib.parse, threading
    from joeai.server import serve
    httpd = serve(app)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    req = urllib.request.Request(base + "/api/talk/attach", data=b"Line one. Line two.", method="POST",
                                 headers={"X-NR-Token": app.token, "X-Filename": urllib.parse.quote("my notes.txt")})
    r = json.loads(urllib.request.urlopen(req, timeout=10).read())
    assert r["ok"] and r["kind"] == "text" and r["rel"] == "Inbox/dropped/my notes.txt"
    req = urllib.request.Request(base + "/api/talk/stream", data=b'{"text": "read it to me"}', method="POST",
                                 headers={"X-NR-Token": app.token, "Content-Type": "application/json"})
    lines = [json.loads(l) for l in urllib.request.urlopen(req, timeout=20).read().splitlines() if l.strip()]
    assert lines[-1]["say"] == "Line one. Line two." and app.talk_files == []
    httpd.shutdown()
