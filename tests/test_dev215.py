"""2.1.5: the pickle-file rule, signed versions, safe add-on arguments and the small fixes from
the outside review (NEXT_STEPS 'Chat 1')."""
import json
import os
import time
from pathlib import Path

import pytest

from joeai import comfy, community, describe, doctor, engine, stylemodels, update
from joeai.config import Settings
from joeai.server import App

from fake_ollama import FakeOllama

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def models(tmp_path, monkeypatch):
    monkeypatch.setattr(comfy, "_pickle_ok_path", lambda: tmp_path / "pickle-ok.json")
    m = tmp_path / "models"
    (m / "checkpoints").mkdir(parents=True)
    (m / "loras").mkdir()
    (m / "checkpoints" / "old.ckpt").write_bytes(b"x" * 100)
    (m / "checkpoints" / "new.safetensors").write_bytes(b"x" * 100)
    return m


# -- 1. pickle files -----------------------------------------------------------------------------
def test_joe_never_picks_a_pickle_himself():
    mk = lambda n, t: comfy.ImageModel(n, "checkpoints", 6.5, "sdxl", t)  # noqa: E731
    assert comfy.best_image_model([mk("a.ckpt", 9), mk("b.pt", 8)], 12) is None
    # a name someone gave: the .safetensors copy wins when both exist
    both = [mk("dream.ckpt", 9), mk("dream.safetensors", 1)]
    assert comfy.best_image_model(both, 12, want="dream").name == "dream.safetensors"
    assert comfy.best_image_model([mk("dream.ckpt", 9)], 12, want="dream").name == "dream.ckpt"


def test_pickle_needs_a_yes_for_that_exact_file(models):
    assert comfy.pickle_allowed("new.safetensors", models)
    assert not comfy.pickle_allowed("old.ckpt", models)
    assert comfy.allow_pickle("old.ckpt", models) == 100
    assert comfy.pickle_allowed("old.ckpt", models)
    assert comfy.pickle_allowed("checkpoints\\old.ckpt", models)  # however ComfyUI spells the path
    assert not comfy.pickle_allowed("sub/old.ckpt", models)        # no such file: never a YES
    (models / "checkpoints" / "old.ckpt").write_bytes(b"y" * 101)  # swapped for another file
    assert not comfy.pickle_allowed("old.ckpt", models)
    comfy.forget_pickle("old.ckpt")
    assert comfy.pickle_approvals() == {}
    with pytest.raises(ValueError):
        comfy.allow_pickle("missing.ckpt", models)
    with pytest.raises(ValueError):
        comfy.allow_pickle("new.safetensors", models)


def test_swapped_file_of_the_same_size_needs_a_new_yes(models):
    f = models / "checkpoints" / "old.ckpt"
    comfy.allow_pickle("old.ckpt", models)
    st = f.stat()
    f.write_bytes(b"y" * 100)                                      # same size, different file
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    assert not comfy.pickle_allowed("old.ckpt", models)
    comfy.allow_pickle("old.ckpt", models)
    assert comfy.pickle_allowed("old.ckpt", models)


def test_a_yes_never_covers_a_same_named_file_somewhere_else(models):
    comfy.allow_pickle("old.ckpt", models)
    (models / "loras" / "old.ckpt").write_bytes(b"z" * 100)        # same name and size, other folder
    assert not comfy.pickle_allowed("old.ckpt", models)            # could mean either: both need a YES
    assert not comfy.pickle_allowed("loras/old.ckpt", models)
    assert comfy.pickle_allowed("checkpoints/old.ckpt", models)
    assert comfy.allow_pickle("loras/old.ckpt", models) == 100
    assert comfy.pickle_allowed("old.ckpt", models)
    comfy.forget_pickle("loras/old.ckpt")
    assert not comfy.pickle_allowed("old.ckpt", models) and len(comfy.pickle_approvals()) == 1


def test_every_older_format_counts_wherever_the_graph_names_it():
    for n in ("a.ckpt", "a.pt", "a.pt2", "a.pth", "a.bin", "a.pkl", "a.pickle", "A.PKL"):
        assert comfy.is_pickle(n), n
    assert not comfy.is_pickle("a.safetensors") and not comfy.is_pickle("a.gguf")
    g = {"1": {"inputs": {"a": ["evil.ckpt"], "b": {"model": {"name": "deep.pkl"}}, "c": ["2", 0], "d": 3}}}
    assert comfy.graph_pickles(g) == ["evil.ckpt", "deep.pkl"]


def test_no_models_folder_means_no_pickle(models):
    comfy.allow_pickle("old.ckpt", models)
    assert not comfy.pickle_allowed("old.ckpt", None)


def test_every_graph_is_checked_before_comfyui_sees_it(models, monkeypatch):
    sent = []
    monkeypatch.setattr(comfy, "request_json", lambda *a, **k: sent.append(a) or {"prompt_id": "1"})
    g = {"1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "old.ckpt"}},
         "2": {"class_type": "LoraLoader", "inputs": {"lora_name": "style.safetensors", "strength": 1}}}
    c = comfy.ComfyClient("http://127.0.0.1:9", models_dir=models)
    with pytest.raises(comfy.WorkflowError, match="YES"):
        c.submit(g)
    assert not sent
    comfy.allow_pickle("old.ckpt", models)
    assert c.submit(g) == "1" and sent
    # a LoRA (or any other loader) that names a pickle is caught the same way
    g["2"]["inputs"]["lora_name"] = "evil.pt"
    with pytest.raises(comfy.WorkflowError):
        c.submit(g)
    # a client that doesn't know the models folder allows no pickle at all
    g["2"]["inputs"]["lora_name"] = "style.safetensors"
    with pytest.raises(comfy.WorkflowError):
        comfy.ComfyClient("http://127.0.0.1:9").submit(g)


def test_downloads_folder_import_leaves_pickles_alone(tmp_path):
    dl = tmp_path / "dl"
    dl.mkdir()
    (dl / "big.ckpt").write_bytes(b"x" * (stylemodels.MIN_BYTES + 1))
    (dl / "big.safetensors").write_bytes(b"x" * (stylemodels.MIN_BYTES + 1))
    assert [p.name for p in stylemodels.found(tmp_path / "models", dl)] == ["big.safetensors"]


def test_model_downloads_refuse_pickles(tmp_path, monkeypatch):
    logs = []
    assert doctor.refuse_pickle("x.pth", logs.append) and "hidden code" in logs[-1]
    assert not doctor.refuse_pickle("x.safetensors", logs.append)
    from joeai import picturetools
    p = picturetools.PACKS["upscale"]
    bad = type(p)(**{**p.__dict__, "files": (("upscale_models", "x4.pth", "https://example.invalid/x4.pth", 0.1),)})
    monkeypatch.setitem(picturetools.PACKS, "upscale", bad)
    monkeypatch.setattr(doctor, "comfy_models_dir", lambda s: tmp_path)
    monkeypatch.setattr(doctor, "_download", lambda *a, **k: pytest.fail("must not download"))
    assert not picturetools.download_pack(Settings(), "upscale", logs.append, approved=True)


def test_inventory_says_which_pickles_have_a_yes(models):
    comfy.allow_pickle("old.ckpt", models)
    inv = stylemodels.inventory(models, [], None)
    assert inv["unsafe"] == ["old.ckpt"] and inv["allowed"] == ["old.ckpt"]


def test_window_has_allow_button_and_server_route():
    js = (ROOT / "joeai/ui/app.js").read_text(encoding="utf-8")
    assert "/api/models/pickle" in js and "YES, I TRUST IT" in js
    srv = (ROOT / "joeai/server.py").read_text(encoding="utf-8")
    assert '"/api/models/pickle"' in srv
    assert "pickle" not in (ROOT / "joeai/phone.py").read_text(encoding="utf-8").lower()


# -- 2. update box ------------------------------------------------------------------------------
def test_update_box_tidies_notes_and_reports_failures():
    js = (ROOT / "joeai/ui/app.js").read_text(encoding="utf-8")
    assert "function notesText" in js and "notesText(r.notes)" in js
    assert 'fr.action === "update-joe"' in js and "The update didn't finish" in js


# -- 3. version inside the signed list -----------------------------------------------------------
def _signed_release(tmp_path, monkeypatch, listed: str, latest: str):
    import contextlib
    import hashlib
    import io
    import joeai
    from joeai import sign
    payload = b"installer bytes"
    name = f"Joe-Setup-{latest}-windows-x64.exe"
    sums = f"{hashlib.sha256(payload).hexdigest()}  {name}\n".encode()
    if listed:
        sums += f"# joe-ai version {listed}\n".encode()
    seed = b"\x07" * 32
    files = {"inst": payload, "sums": sums, "sig": sign.sign_file_text(sign.b64(seed), sums).encode()}

    class R(io.BytesIO):
        headers = {}
    monkeypatch.setattr(update, "updates_dir", lambda: tmp_path)
    monkeypatch.setattr(joeai, "SIGN_PUBLIC_KEY", sign.b64(sign.public_key(seed)))
    logs = []
    got = update.download({"asset": {"name": name, "url": "inst"}, "sums": "sums", "sig": "sig", "latest": latest},
                          logs.append, opener=lambda u, timeout=0: contextlib.closing(R(files[u])))
    return got, logs


def test_signed_list_must_name_the_offered_version(tmp_path, monkeypatch):
    assert _signed_release(tmp_path, monkeypatch, "99.0.0", "99.0.0")[0]
    got, logs = _signed_release(tmp_path, monkeypatch, "2.0.0", "99.0.0")    # an old list replayed
    assert got is None and "version 2.0.0" in logs[-1]
    got, logs = _signed_release(tmp_path, monkeypatch, "", "99.0.0")         # no version in it
    assert got is None
    got, logs = _signed_release(tmp_path, monkeypatch, "1.0.0", "1.0.0")     # older than this Joe
    assert got is None


def test_release_workflow_writes_the_version_line():
    yml = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert update.VERSION_LINE.strip() in yml
    assert update.listed_version("abc  x.exe\n# joe-ai version 2.1.5\n") == "2.1.5"


# -- 4. appimagetool checked ---------------------------------------------------------------------
def test_appimagetool_is_pinned_and_checked():
    sh = (ROOT / "installer/linux/build_appimage.sh").read_text(encoding="utf-8")
    assert "continuous" not in sh and "sha256sum" in sh and "ait_sha" in sh


# -- 5. add-on arguments -------------------------------------------------------------------------
def test_typed_text_never_becomes_an_option(tmp_path):
    tool = {"program": "prog", "output": "{stem}.txt", "args": ["{text}", "--title={text}", "{input}"]}
    ok = community.command_line(tool, Path("prog"), tmp_path / "a.png", tmp_path, set(), {}, "hello")
    assert ok[1] == "hello" and ok[2] == "--title=hello"
    with pytest.raises(ValueError, match="switch"):
        community.command_line(tool, Path("prog"), tmp_path / "a.png", tmp_path, set(), {}, "--output=/etc/x")
    tool["args"] = ["{option:mode}"]
    with pytest.raises(ValueError):
        community.command_line(tool, Path("prog"), tmp_path / "a.png", tmp_path, set(), {"mode": "-rf"}, "")
    tool["args"] = ["--title={text}"]                        # inside an option the template made: fine
    assert community.command_line(tool, Path("prog"), tmp_path / "a.png", tmp_path, set(), {}, "-x")[-1] == "--title=-x"


# -- 6. esc() -----------------------------------------------------------------------------------
def test_window_esc_escapes_single_quotes():
    js = (ROOT / "joeai/ui/app.js").read_text(encoding="utf-8")
    line = next(ln for ln in js.splitlines() if ln.startswith("const esc ="))
    assert "&#39;" in line


# -- 7. old problem files ------------------------------------------------------------------------
def test_status_leaves_out_week_old_problem_files(tmp_path, monkeypatch):
    from joeai import mcp
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    j = mcp.Joe(s)
    probs = j.sb.missions / "Queue" / "problems"
    probs.mkdir(parents=True, exist_ok=True)
    (probs / "old.txt").write_text("TASK: x")
    (probs / "new.txt").write_text("TASK: y")
    old = time.time() - 9 * 86400
    os.utime(probs / "old.txt", (old, old))
    st = j.status()
    assert "new.txt" in st and "old.txt" not in st


# -- 8. a typed mission keeps its SAVE ------------------------------------------------------------
@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "settings.json"))
    fake = FakeOllama()
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    s.ollama.url = fake.url
    s.comfy.url = "http://127.0.0.1:9"
    a = App(settings=s)
    a.fake = fake
    yield a
    fake.close()


def test_pasted_mission_runs_as_written(app):
    text = ("TASK: Fix check  SAVE: fix-check/note.md  EXPORT: docx, pdf, html\n"
            "PART: ## Morning. Two short sentences about a robot making coffee.\n")
    r = describe.draft(app, text)
    assert r["ok"], r
    assert "SAVE: fix-check/note.md" in r["mission"] and r["mission"] == text.strip()
    assert describe.ready_mission(app, "make me 10 captions for my shop") is None


# -- 9. short parts aren't retried for being short -----------------------------------------------
def test_sentence_lengths_count_as_asked_words():
    assert engine.asked_words("Two short sentences per section.") == 30
    assert engine.asked_words("a sentence or two") == 15
    assert engine.asked_words("one or two sentences") == 15
    assert engine.asked_words("This is a sentence about cats") == 0
    assert engine.asked_words("about 60 words") == 60
    assert engine.thin_reply_words(0, 0, engine.asked_words("Two short sentences")) == 15


# -- 10. tests don't see this PC's programs ------------------------------------------------------
def test_real_services_are_hidden_from_tests():
    import socket
    s = socket.socket()
    try:
        with pytest.raises(ConnectionRefusedError):
            s.connect(("127.0.0.1", 11434))
    finally:
        s.close()
    assert "Joe-ai" not in str(Path.home()) and Path.home().name.startswith("home")


# -- 11. README -----------------------------------------------------------------------------------
def test_readme_says_what_to_do_when_update_fails():
    assert "If UPDATE doesn't work" in (ROOT / "README.md").read_text(encoding="utf-8")
