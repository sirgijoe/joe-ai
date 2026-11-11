"""2.2 dev: Joe's face in Talk (NEXT_STEPS 'Chat 2'). The picture (ui/joe.svg), the code that
changes his face (ui/joe.js), where the window hooks in (app.js), the Setup switch, the night-shift
note that makes him sleepy, and the page security rules staying as they were."""
import json
import re
import shutil
import subprocess
import threading
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from joeai import schedule
from joeai.config import Settings, VoiceSettings
from joeai.sandbox import Sandbox

from test_core import env  # noqa: F401  (shared fixture)

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "joeai" / "ui"
NS = "{http://www.w3.org/2000/svg}"
EYES = {"neutral", "listen", "wide", "up", "happy", "blink", "heart", "ko", "angry", "sad"}
TALK = {"closed", "small", "wideopen", "ooh", "ee"}
MOUTHS = TALK | {"smile", "grin", "flat", "soft", "wobble", "o", "dots"}


def _svg():
    return ET.parse(UI / "joe.svg").getroot()


def _groups(root, kind):
    return {g.get(f"data-{kind}"): g for g in root.iter(NS + "g") if g.get(f"data-{kind}")}


# -- the picture -----------------------------------------------------------------------------------
def test_picture_has_every_face_as_its_own_layer():
    root = _svg()
    assert root.tag == NS + "svg" and root.get("viewBox") == "0 0 400 470"
    face = [g for g in root.iter(NS + "g") if g.get("id") == "jf-face"]
    assert len(face) == 1
    eyes, mouths = _groups(face[0], "eyes"), _groups(face[0], "mouth")
    assert set(eyes) == EYES and set(mouths) == MOUTHS          # incl. the new listening face
    # one eye set and one mouth showing to start with: neutral + smile
    assert [k for k, g in eyes.items() if g.get("display") != "none"] == ["neutral"]
    assert [k for k, g in mouths.items() if g.get("display") != "none"] == ["smile"]
    assert any(e.get("id") == "jf-cursor" for e in root.iter())   # the antenna light that blinks


def test_new_ee_mouth_is_wider_than_the_others():
    mouths = _groups(_svg(), "mouth")

    def width(g):
        xs = []
        for el in g:
            if el.get("width"):
                xs += [float(el.get("x")), float(el.get("x")) + float(el.get("width"))]
            elif el.get("rx") and el.get("cx"):
                xs += [float(el.get("cx")) - float(el.get("rx")), float(el.get("cx")) + float(el.get("rx"))]
            elif el.get("d"):
                xs += [float(a) for a in re.findall(r"[MLQ]\s*(-?[\d.]+)", el.get("d"))]
        return max(xs) - min(xs)
    ee = width(mouths["ee"])
    assert ee >= 50
    assert all(ee > width(mouths[m]) + 10 for m in TALK - {"ee"})


def test_listening_face_has_sound_waves():
    listen = _groups(_svg(), "eyes")["listen"]
    assert len([p for p in listen if p.tag == NS + "path"]) == 4     # two waves each side
    assert len([r for r in listen if r.tag == NS + "rect"]) >= 2     # and both eyes


def test_picture_is_only_a_picture():
    text = (UI / "joe.svg").read_text(encoding="utf-8")
    low = text.lower()
    for bad in ("<script", "foreignobject", "javascript:", "<image", "<use", "@import", "<style"):
        assert bad not in low, bad
    assert not re.search(r"\son[a-z]+\s*=", low)                     # no onload= etc.
    # the only addresses are XML namespaces (the copy on a PC may carry a content-credentials
    # <metadata> block, c2pa, added when the file was delivered: inert data, never shown or run)
    assert set(re.findall(r"https?://[^\"']+", text)) <= {"http://www.w3.org/2000/svg", "http://c2pa.org/manifest"}
    assert re.findall(r'href\s*=', low) == []
    ids = re.findall(r'\bid="([^"]+)"', text)
    assert ids and all(i.startswith("jf-") for i in ids)              # can't clash with the page
    page_ids = set(re.findall(r'\bid="([^"]+)"', (UI / "index.html").read_text(encoding="utf-8")))
    assert not page_ids & set(ids)
    assert len(text.encode()) < 40_000


# -- the window ------------------------------------------------------------------------------------
def test_page_rules_unchanged_and_face_loads_as_its_own_file(env):  # noqa: F811
    from joeai.server import App, serve
    s, sb, _ = env
    app = App(s)
    httpd = serve(app)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            csp = r.headers["Content-Security-Policy"]
            page = r.read().decode()
        assert "script-src 'self';" in csp and "unsafe-eval" not in csp
        assert re.search(r"script-src 'self'[^;]*'unsafe-inline'", csp) is None
        assert page.index('src="/joe.js"') < page.index('src="/app.js"')
        assert re.findall(r"<script(?![^>]*\bsrc=)[^>]*>", page) == []   # no inline script
        with urllib.request.urlopen(url + "joe.js", timeout=5) as r:      # no token needed: it's code
            assert r.headers["Content-Type"].startswith("text/javascript")
            assert b"const JoeFace" in r.read()
        with urllib.request.urlopen(url + "joe.svg", timeout=5) as r:
            assert r.headers["Content-Type"] == "image/svg+xml"
            assert r.headers["X-Content-Type-Options"] == "nosniff"
            assert r.headers["Content-Security-Policy"].startswith("default-src 'none'")
            assert r.read() == (UI / "joe.svg").read_bytes()
        st = app.state()
        assert st["night"] is False
    finally:
        httpd.shutdown()


def test_talk_screen_has_the_face_beside_the_chat():
    html = (UI / "index.html").read_text(encoding="utf-8")
    talk = html[html.index('id="s-talk"'):html.index("</main>", html.index('id="s-talk"'))]
    assert 'id="joe-face"' in talk and 'aria-hidden="true"' in talk
    assert talk.index('id="talk-log"') < talk.index('id="joe-face"')
    css = (UI / "app.css").read_text(encoding="utf-8")
    assert ".joeface" in css and ".talk > .talkbody" in css


def test_app_js_tells_the_face_what_is_going_on():
    js = (UI / "app.js").read_text(encoding="utf-8")
    assert "JoeFace.voice(audioEl, speechBlobs.get(url))" in js                      # mouths follow each clip
    assert 'JoeFace.setMode(faceMode)' in js and "v.settings.face" in js
    assert 'JoeFace.mood(f.ok ? "happy" : "worried")' in js          # run done / failed
    assert 'JoeFace.mood("worried")' in js                           # a Talk answer that failed
    probe = js[js.index("JoeFace.watch("):js.index("}));", js.index("JoeFace.watch("))]
    for want in ("audio: audioEl", "talkAbort", "busyTalking", "micStream", "rec",
                 '$("#saver").hidden', "state.night"):
        assert want in probe, want
    assert js.count("typeof JoeFace") >= 4      # the window still works if joe.js didn't load


def test_face_code_is_plain_and_respects_reduce_motion():
    js = (UI / "joe.js").read_text(encoding="utf-8")
    for bad in ("eval(", "new Function", "innerHTML", "outerHTML", "insertAdjacentHTML", "document.write",
                "localStorage", "http://", "https://"):
        assert bad not in js, bad
    assert "prefers-reduced-motion: reduce" in js
    assert 'fetch("/joe.svg"' in js
    for state, look in {"idle": '["neutral", "smile"]', "listening": '["listen", "soft"]',
                        "thinking": '["up", "dots"]', "happy": '["happy", "grin"]',
                        "worried": '["sad", "wobble"]', "sleepy": '["blink", "flat"]'}.items():
        assert f"{state}: {look}" in js, state


NODE_TEST = r"""
const vm = require("vm"), fs = require("fs");
let reduce = false;
const ctx = { window: {}, document: { hidden: false }, performance: { now: () => Date.now() },
              setInterval: () => 1, console };
ctx.window.matchMedia = () => ({ get matches() { return reduce; }, addEventListener() {} });
ctx.matchMedia = ctx.window.matchMedia;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8") + "\nthis.JoeFace = JoeFace;", ctx);
const F = ctx.JoeFace, out = {};
out.mouths = [0, 0.05, 0.2, 0.5, 0.5, 0.9].map((v, i) => F._mouthFor(v, i === 4));
let p = {};
F.watch(() => p);
const look = () => F._lookNow(Date.now());
out.idle = look();
p = { listening: true }; out.listening = look();
p = { listening: true, sleepy: true }; out.sleepy = look();
p = { busy: true, listening: true }; out.thinking = look();
p = { audio: { paused: false, ended: false }, busy: true }; out.speaking = look();
p = { busy: true }; out.pause = look();                 // between two sentences
p = {}; F.mood("happy"); out.happy = look();
F.mood("worried"); out.worried = look();
p = { busy: true }; out.busyOverMood = look();
F.mood("nonsense"); out.badMood = "ok";
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js isn't installed (only used to test joe.js)")
def test_face_states_and_mouth_picks_in_node(tmp_path):
    script = tmp_path / "t.js"
    script.write_text(NODE_TEST, encoding="utf-8")
    r = subprocess.run(["node", str(script), str(UI / "joe.js")], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["mouths"] == ["closed", "closed", "small", "ooh", "ee", "wideopen"]
    assert out["idle"] == "idle" and out["listening"] == "listening" and out["sleepy"] == "sleepy"
    assert out["thinking"] == "thinking" and out["speaking"] == "speaking" and out["pause"] == "pause"
    assert out["happy"] == "happy" and out["worried"] == "worried" and out["busyOverMood"] == "pause"


# -- Setup switch ------------------------------------------------------------------------------------
def test_setup_switch_on_still_off(tmp_path):
    assert VoiceSettings().face == "on"
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"voice": {"face": "off"}}), encoding="utf-8")
    assert Settings.load(p).voice.face == "off"
    p.write_text(json.dumps({"voice": {"face": 3}}), encoding="utf-8")       # wrong type: default kept
    assert Settings.load(p).voice.face == "on"
    html = (UI / "index.html").read_text(encoding="utf-8")
    sel = html[html.index('data-path="voice.face"'):]
    sel = sel[:sel.index("</select>")]
    assert re.findall(r'value="(\w+)"', sel) == ["on", "still", "off"]


# -- night shift: sleepy ---------------------------------------------------------------------------
def test_night_shift_note(tmp_path):
    sb = Sandbox(tmp_path / "ws").ensure()
    assert not schedule.night_started(sb)
    schedule.mark_night(sb)
    assert schedule.night_started(sb)
    schedule.clear_stop(sb)                       # the run ended: the note goes with the stop time
    assert not schedule.night_started(sb)
    old = (datetime.now() - timedelta(hours=21)).isoformat(timespec="seconds")
    (sb.meta / schedule.NIGHT_FILE).write_text(json.dumps({"started": old}), encoding="utf-8")
    assert not schedule.night_started(sb)         # a note left by a crash doesn't last forever
    (sb.meta / schedule.NIGHT_FILE).write_text("{bad", encoding="utf-8")
    assert not schedule.night_started(sb)


def test_tonight_marks_the_run(tmp_path, monkeypatch):
    monkeypatch.setenv("JOE_CONFIG", str(tmp_path / "settings.json"))
    s = Settings()
    s.workspace = str(tmp_path / "ws")
    s.save()
    sb = Sandbox(s.workspace_path).ensure()
    (sb.missions / "Tonight").mkdir(parents=True, exist_ok=True)
    (sb.missions / "Tonight" / "plan.txt").write_text("TASK: x\n", encoding="utf-8")
    import joeai.app as app_mod
    monkeypatch.setattr(app_mod, "_existing_url", lambda: "http://127.0.0.1:1/")   # window open
    assert schedule.tonight() == 0
    assert schedule.night_started(sb)


def test_no_personal_data_in_the_new_files():
    for f in (UI / "joe.js", UI / "joe.svg"):
        low = f.read_text(encoding="utf-8").lower()
        for word in ("bloom", "lotus", "outdoor", "miranda", "perrin", "joseph", "sirgijoe", "c:\\users"):
            assert word not in low, (f.name, word)
