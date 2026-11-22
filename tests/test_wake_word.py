"""The wake word (2.3): with it on, the open mic listens on every screen and Joe answers to "Hey Joe".
The deciding function (wakeSplit in app.js) is run here with node, like the open mic's check."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from joeai.config import Settings, clean_wake_words

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "joeai" / "ui" / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "joeai" / "ui" / "index.html").read_text(encoding="utf-8")


def _split(cases, phrase="hey joe"):
    node = shutil.which("node")
    if not node:
        pytest.skip("node isn't installed here (GitHub's test machines have it)")
    assert "// >>> wake-word" in JS and "// <<< wake-word" in JS
    code = JS.split("// >>> wake-word")[1].split("// <<< wake-word")[0]
    script = code + "\nconsole.log(JSON.stringify(%s.map((t) => wakeSplit(t, %s))));" % (json.dumps(cases), json.dumps(phrase))
    r = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr[-800:]
    return json.loads(r.stdout)


def test_hey_joe_then_the_question():
    got = _split(["Hey Joe, how hot is the sun?", "hey joe what's left in the queue", "Hey, Joe. Read me the report."])
    assert got == ["how hot is the sun?", "what's left in the queue", "Read me the report."]


def test_the_ways_hey_joe_gets_heard():
    got = _split(["Hey Joel, what time is it?", "Hi Joe, what time is it?", "Okay Joe what time is it",
                  "A Joe, what time is it?", "Hey Jo! What time is it?", "Hey Joey what time is it",
                  "Um, hey Joe, what time is it?"])
    assert all(g and g.lower().rstrip("?").endswith("what time is it") for g in got), got


def test_just_the_wake_words_gives_an_empty_question():
    assert _split(["Hey Joe.", "hey joe", "Hey, Joe!"]) == ["", "", ""]


def test_talk_that_isnt_for_joe_is_not_taken():
    got = _split(["I told him hey Joe yesterday", "Joe said he would come", "Hey, what's for dinner?",
                  "The weather is nice today", "", "hey", "Say hey Joe to start", "hey john, come here",
                  "They enjoyed the show", "Hey Joanna, dinner!"])
    assert got == [None] * 10, got


def test_their_own_wake_words():
    got = _split(["Computer wake up, play the report", "Hey Joe, play the report", "computer wakes up now",
                  "Computer, wake up."], "computer wake up")
    assert got == ["play the report", None, None, ""]


def test_only_two_fillers_may_come_first():
    assert _split(["so um hey joe hello", "well so um hey joe hello", "banana hey joe hello"]) == ["hello", None, None]


def test_the_setting_is_off_until_ticked_and_kept_clean(tmp_path):
    s = Settings()
    assert s.voice.wake is False and s.voice.wake_words == "hey joe"
    assert clean_wake_words("  Hey,  JOE!! ") == "hey joe"
    assert clean_wake_words("joe") == "hey joe"                       # one word alone fires on everyday talk
    assert clean_wake_words("<script>alert(1)</script>") == "script alert 1 script"
    assert clean_wake_words("ok computer please wake up now") == "ok computer please wake"
    assert clean_wake_words(None) == "hey joe" and clean_wake_words("hey j") == "hey joe"
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"voice": {"wake": "yes", "wake_words": "YO, Robot"}}))
    s = Settings.load(p)
    assert s.voice.wake is False and s.voice.wake_words == "yo robot"       # only a real tick turns it on
    p.write_text(json.dumps({"voice": {"wake": True}}))
    assert Settings.load(p).voice.wake is True


def test_setup_has_the_tick_box_and_says_what_it_means():
    assert 'data-path="voice.wake"' in HTML and 'data-path="voice.wake_words"' in HTML
    box = HTML.split('data-path="voice.wake"')[0].rsplit("<label", 1)[1]
    for words in ("Off unless you tick it", "dropped at once", "not sent anywhere", "push-to-talk"):
        assert words in box


def test_overheard_talk_is_dropped_before_anything_is_shown():
    send = JS.split("async function sendAudio(")[1].split("\n// --- open mic")[0]
    wake = send.split("if (wake) {")[1]
    assert wake.index("if (rest === null) { busyTalking = false; return; }") < wake.index("talkSend(rest)")
    assert wake.index("if (rest === null)") < wake.index('show("talk")')
    assert 'heads["X-Joe-Wake"] = "1"' in send and "if (report && !wake)" in send        # no levels logged either
    assert "talkLog.push" not in wake.split("if (rest === null)")[0]


def test_the_mic_only_stays_open_off_talk_with_the_wake_word_on():
    start = JS.split("async function openMicStart() {")[1].split("\n}")[0]
    assert '(current !== "talk" && !wakeOn)) return;' in start
    assert 'sendAudio(c, report, current !== "talk" || performance.now() < wakeUntil)' in start
    apply = JS.split("function wakeApply() {")[1].split("\n}")[0]
    assert "else openMicStop();" in apply and 'talkMode === "open"' in apply and "!micMuted" in apply
