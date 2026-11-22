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
    r = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
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
