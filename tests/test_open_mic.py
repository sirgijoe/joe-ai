"""The open mic's "are you still talking?" check (2.3). Found on a real PC (2026-11-15): "Hey Joe, how hot is
the sun?" arrived as "Hey Joe." Push-to-talk heard the whole question, so the hearing was fine: the open
mic ended the turn while the person was still talking. The check now lives in one small function in app.js
(micStep), run here with node; each recording also reports its levels for MAKE A HELP FILE."""
import json
import shutil
import subprocess
import threading
import urllib.request
from pathlib import Path

import pytest

from test_core import env  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "joeai" / "ui" / "app.js").read_text(encoding="utf-8")
TICK = 80          # the open mic looks at the sound every 80 ms


def _mic(parts, pause=850):
    """Play sound through the open mic's check. parts: (seconds, loudness, joe_is_busy) one after another.
    Returns the recordings it would make, as (start, end) in seconds."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node isn't installed here (GitHub's test machines have it)")
    assert "// >>> mic-step" in JS and "// <<< mic-step" in JS
    code = JS.split("// >>> mic-step")[1].split("// <<< mic-step")[0]
    script = code + """
const parts = %s, pause = %d, st = micState(), clips = [];
let now = 0, begun = null;
for (const [secs, rms, busy] of parts) {
  for (let t = 0; t < secs * 1000; t += %d, now += %d) {
    const ev = micStep(st, rms, now, pause, !!busy);
    if (ev === "start") begun = now;
    if (ev === "stop") { clips.push([begun / 1000, now / 1000]); begun = null; }
  }
}
if (begun !== null) clips.push([begun / 1000, null]);
console.log(JSON.stringify({ clips, floor: st.floor }));
""" % (json.dumps(parts), pause, TICK, TICK)
    r = subprocess.run([node, "-e", script], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=30)        # node writes UTF-8; Windows would read it as its own code page
    assert r.returncode == 0, r.stderr[-800:]
    return json.loads(r.stdout)["clips"]


QUIET = 0.001


def test_a_plain_sentence_is_one_recording_that_ends_after_the_pause():
    clips = _mic([(2, QUIET, 0), (2, 0.05, 0), (3, QUIET, 0)])
    assert len(clips) == 1
    start, end = clips[0]
    assert 2.0 <= start <= 2.1 and 4.8 <= end <= 5.0                 # 2 s of talking + 0.85 s of quiet


def test_the_quieter_rest_of_a_sentence_still_counts_as_talking():
    """ "Hey Joe" said firmly, a short breath, then the rest said softly (a quiet studio microphone)."""
    clips = _mic([(6, QUIET, 0), (0.6, 0.04, 0), (0.24, 0.002, 0), (1.4, 0.008, 0), (3, QUIET, 0)])
    assert len(clips) == 1
    assert clips[0][1] >= 6 + 0.6 + 0.24 + 1.4 + 0.8                  # not cut 0.85 s after "Hey Joe"


def test_talking_right_after_joe_spoke_is_heard_to_the_end():
    """Joe's own voice comes back through the microphone while he speaks. That must not teach the open mic
    that the room is loud, or the next thing you say is taken for quiet."""
    clips = _mic([(6, QUIET, 0), (6, 0.1, 1), (0.4, QUIET, 0), (2.5, 0.03, 0), (3, QUIET, 0)])
    assert len(clips) == 1
    start, end = clips[0]
    assert 12.4 <= start <= 12.6 and end >= 12.4 + 2.5 + 0.8


def test_you_talking_over_joe_doesnt_deafen_the_mic_either():
    clips = _mic([(6, QUIET, 0), (4, 0.06, 1), (0.3, QUIET, 0), (2, 0.02, 0), (3, QUIET, 0)])
    assert len(clips) == 1 and clips[0][1] >= 10.3 + 2 + 0.8


def test_steady_room_noise_is_learned_and_doesnt_start_a_recording():
    clips = _mic([(20, 0.02, 0)])                                    # a fan comes on and stays on
    assert all(end is not None and end < 6 for _, end in clips) and len(clips) <= 2
    clips = _mic([(20, 0.02, 0), (2, 0.09, 0), (3, 0.02, 0)])        # talking over the fan still works
    assert clips[-1][0] >= 19.9 and 22.7 <= clips[-1][1] <= 23.1


def test_a_loud_noise_that_never_pauses_is_recorded_once_then_learned():
    clips = _mic([(6, QUIET, 0), (70, 0.05, 0)])                     # something loud switches on and stays on
    assert len(clips) == 1 and 36.0 <= clips[0][1] <= 36.3            # one half-minute recording, then it's the room


def test_the_wait_setting_is_the_quiet_allowed_inside_a_question():
    said = [(2, QUIET, 0), (1.5, 0.05, 0), (1.2, QUIET, 0), (1.5, 0.05, 0), (4, QUIET, 0)]   # a 1.2 s think in the middle
    assert len(_mic(said, pause=850)) == 2                           # Quick: two halves
    assert len(_mic(said, pause=2000)) == 1                          # Patient: one question
    assert _mic(said, pause=2000)[0][1] >= 6.2 + 1.9


def test_nobody_talks_for_more_than_half_a_minute_in_one_go():
    clips = _mic([(1, QUIET, 0), (40, 0.05, 0)])
    assert 30.9 <= clips[0][1] <= 31.2


def test_the_open_mic_listens_to_the_whole_stretch_and_reports_its_levels():
    assert "an.fftSize = 4096" in JS                                  # 85 ms of sound every 80 ms: no gaps
    assert "micStep(st, rms, now, turnPause, joeBusy)" in JS
    assert '"X-Joe-Mic"' in JS and "micReport(" in JS


def test_quick_is_how_joe_comes(tmp_path):
    from joeai.config import Settings
    assert Settings().voice.turn_pause == "quick"                     # 0.85 s, as it always was
    assert "let turnPause = TURN_PAUSE.quick;" in JS
    assert JS.count("turnPause = TURN_PAUSE[v.settings.turn_pause] || TURN_PAUSE.quick;") == 2


def test_each_recording_leaves_a_line_for_the_help_file(env):  # noqa: F811
    from joeai.server import App, mic_line, serve
    good = json.dumps({"clip": 1.42, "quiet": 0.0011, "loudest": 0.0432, "start": 0.015, "keep": 0.005,
                       "pause": 0.85, "mic": "Headset Microphone (MAONO AU-AM200)"})
    assert mic_line(good) == ("Talk timing: open mic recorded 1.4s (room 0.0011, loudest 0.0432, talking starts "
                              "above 0.0150 and goes on above 0.0050, turn ends after 0.85s of quiet; "
                              "Headset Microphone (MAONO AU-AM200))")
    for junk in ("", None, "not json", "[1, 2]", json.dumps({"clip": "x" * 5000}), "x" * 5000):
        assert mic_line(junk) == "", junk
    assert "\n" not in mic_line(json.dumps({"clip": 1, "mic": "Evil\nmic <b>" + "x" * 500})) \
        and len(mic_line(json.dumps({"clip": 1, "mic": "x" * 500}))) < 300
    s, sb, fake = env
    app = App(s)
    httpd = serve(app)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{httpd.server_address[1]}/api/voice/listen", data=b"RIFFxxxx",
                                     method="POST", headers={"X-NR-Token": app.token, "Content-Type": "audio/wav",
                                                             "X-Joe-Mic": good})
        urllib.request.urlopen(req, timeout=20).read()
    finally:
        httpd.shutdown()
    assert any(ln.endswith(mic_line(good)) for ln in app.debug_lines)


# --- the rolling second (2026-11-22): the first syllable of "Hey Joe" isn't clipped -------------------------

def _ring(script):
    node = shutil.which("node")
    if not node:
        pytest.skip("node isn't installed here (GitHub's test machines have it)")
    assert "// >>> mic-ring" in JS and "// <<< mic-ring" in JS
    code = JS.split("// >>> mic-ring")[1].split("// <<< mic-ring")[0]
    r = subprocess.run([node, "-e", code + script], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=30)        # node writes UTF-8; Windows would read it as its own code page
    assert r.returncode == 0, r.stderr[-800:]
    return json.loads(r.stdout)


def test_the_rolling_second_keeps_only_the_last_second_and_in_order():
    out = _ring("""
const r = micRing(1000, 1);                     // 1000 samples a second
let n = 0; for (let i = 0; i < 37; i++) { r.push(Float32Array.from({ length: 128 }, () => n++)); }
const got = r.take();
console.log(JSON.stringify({ len: got.length, first: got[0], last: got[got.length - 1], size: r.size(), n }));
""")
    assert out["len"] == 1000 and out["size"] == 1000                 # capped at one second, however long it listens
    assert out["last"] == out["n"] - 1 and out["first"] == out["n"] - 1000    # the newest second, oldest first
    out = _ring("const r = micRing(1000, 1); r.push(new Float32Array(300)); console.log(JSON.stringify({ len: r.take().length }));")
    assert out["len"] == 300                                          # less than a second heard: just that


def test_the_rolling_second_is_thrown_away_by_clear():
    out = _ring("""
const r = micRing(1000, 1); r.push(new Float32Array(500).fill(0.5)); r.clear();
console.log(JSON.stringify({ size: r.size(), len: r.take().length }));
""")
    assert out == {"size": 0, "len": 0}


def test_the_open_mic_keeps_the_second_only_while_listening_and_puts_it_in_front():
    start = JS.split("async function openMicStart()")[1].split("function meter(")[0]
    stop = JS.split("function openMicStop()")[1].split("// --- push-to-talk")[0]
    assert "micRing(m.ctx.sampleRate, 1)" in start                    # made only when the open mic starts listening
    assert "lead = ring.take(); ring.clear(); hold = true;" in start   # speech starts: the second goes in front, then stops filling
    assert "if (joeBusy && !utter) ring.clear();" in start            # Joe's own voice is never kept
    assert "ld, lr);" in start and "sendAudio(chunks, report, wake, lead, leadRate)" in JS
    assert "micRoll.ring.clear(); micRoll = null;" in stop and "onaudioprocess = null" in stop   # listening stops: thrown away
    assert "micRing(" not in JS.split("async function recStartFn()")[1].split("function recStopFn")[0]   # push-to-talk keeps nothing
    assert "fetch(" not in JS.split("// >>> mic-ring")[1].split("// <<< mic-ring")[0]       # never sent or saved on its own
    assert "ls.start(0)" in JS and "src.start(pre)" in JS             # in the file, the lead comes first


# --- two starts at once (2026-11-22 review, finding 11): the microphone can't be left on ----------------------

def _starts(scenario):
    """Run openMicStart/openMicStop under node with a fake microphone that answers only when told to.
    Returns what happened to every microphone and sound context handed out."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node isn't installed here (GitHub's test machines have it)")
    parts = [JS.split("// >>> mic-ring")[1].split("// <<< mic-ring")[0],
             JS.split("// >>> mic-step")[1].split("// <<< mic-step")[0],
             JS.split("// >>> mic-start")[1].split("// <<< mic-start")[0]]
    harness = """
const streams = [], ctxs = [], pending = [], toasts = [], loops = new Set();
let n = 0, ctxThrows = false;
const navigator = { mediaDevices: { getUserMedia: () => new Promise((ok, no) => {
  const s = { id: ++n, live: true, getTracks() { return [{ stop: () => { s.live = false; } }]; }, getAudioTracks() { return []; } };
  streams.push(s); pending.push({ ok: () => ok(s), no: () => no(new Error("denied")) });
}) } };
class AudioContext {
  constructor() { if (ctxThrows) throw new Error("no sound card"); this.state = "running"; this.sampleRate = 48000; this.closed = false; this.sp = null; ctxs.push(this); }
  close() { this.closed = true; return Promise.resolve(); }
  resume() { return Promise.resolve(); }
  createAnalyser() { return { fftSize: 0, getFloatTimeDomainData() {}, connect() {} }; }
  createMediaStreamSource() { return { connect() {} }; }
  createScriptProcessor() { const sp = { onaudioprocess: null, attached: true, connect() {}, disconnect() { this.attached = false; } }; this.sp = sp; return sp; }
  createGain() { return { gain: { value: 1 }, connect() {} }; }
  get destination() { return {}; }
}
const setInterval = (f) => { const id = {}; loops.add(id); return id; };
const clearInterval = (id) => { loops.delete(id); };
const $ = () => null;
let talkMode = "open", micMuted = false, voiceReady = true, current = "talk", wakeOn = true;
let micStream = null, micCtx = null, micLoop = null, micRoll = null, micGen = 0;
let busyTalking = false, speaking = false, audioEl = null, turnPause = 850;
function toast(t) { toasts.push(t); } function pttLabel() {} function micName() {} function wakeBadge() {} function badge() {}
function micReport() { return {}; } function sendAudio() {} function wakeMode() { return true; }
const wait = () => new Promise((r) => setTimeout(r, 0));
function report() {
  console.log(JSON.stringify({ live: streams.filter((s) => s.live).map((s) => s.id), open: ctxs.filter((c) => !c.closed).length,
    attached: ctxs.filter((c) => c.sp && c.sp.attached && c.sp.onaudioprocess).length, loops: loops.size,
    current: micStream ? micStream.id : null, asked: streams.length, toasts, starting: micStarting }));
}
"""
    script = harness + "\n".join(parts) + "\n(async () => {\n" + scenario + "\nreport();\n})().catch((e) => { console.error(e.stack); process.exit(1); });"
    r = subprocess.run([node, "-e", script], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=30)        # node writes UTF-8; Windows would read it as its own code page
    assert r.returncode == 0, r.stderr[-1500:]
    return json.loads(r.stdout)


def test_a_second_start_while_the_first_waits_makes_no_second_microphone():
    out = _starts("""
openMicStart(); openMicStart(); openMicStart();     // the wake check, a screen change and opening Talk, all at once
pending[0].ok(); await wait(); await wait();
""")
    assert out["asked"] == 1 and out["live"] == [1] and out["current"] == 1 and out["loops"] == 1 and out["open"] == 1


def test_mic_off_while_the_first_start_waits_leaves_nothing_on():
    out = _starts("""
openMicStart(); openMicStart();
openMicStop();                                      // MIC OFF, or the wake word unticked, before the browser answered
micMuted = true;
pending[0].ok(); await wait(); await wait();
""")
    assert out["live"] == [] and out["open"] == 0 and out["attached"] == 0 and out["loops"] == 0 and out["current"] is None


def test_off_then_on_again_while_waiting_ends_with_exactly_one_microphone():
    out = _starts("""
openMicStart();
openMicStop(); openMicStart();                      // MIC OFF then MIC ON quickly: the second start waits its turn
pending[0].ok(); await wait(); await wait();        // the first one lets go ...
pending[1].ok(); await wait(); await wait();        // ... and a fresh one starts
""")
    assert out["asked"] == 2 and out["live"] == [2] and out["current"] == 2 and out["loops"] == 1 and out["open"] == 1


def test_stop_after_a_start_lets_go_of_everything():
    out = _starts("""
openMicStart(); pending[0].ok(); await wait(); await wait();
openMicStop(); await wait();
""")
    assert out["live"] == [] and out["open"] == 0 and out["attached"] == 0 and out["loops"] == 0 and not out["starting"]


def test_a_start_that_fails_after_the_microphone_lets_it_go():
    out = _starts("""
ctxThrows = true;
openMicStart(); pending[0].ok(); await wait(); await wait();
""")
    assert out["live"] == [] and out["current"] is None and out["loops"] == 0 and not out["starting"]
    assert out["toasts"] == ["Joe's microphone didn't start. Press [ MIC OFF ] to try again."]


def test_a_refused_microphone_says_so_once():
    out = _starts("""
openMicStart(); openMicStart(); pending[0].no(); await wait(); await wait();
""")
    assert out["asked"] == 1                                         # the second start didn't ask again
    assert out["toasts"] == ["Joe can't hear you: allow the microphone for this window"] and out["current"] is None
