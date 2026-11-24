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
    r = subprocess.run([node, "-e", script], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=30)        # node writes UTF-8; Windows would read it as its own code page
    assert r.returncode == 0, r.stderr[-800:]
    return json.loads(r.stdout)


def test_hey_joe_then_the_question():
    got = _split(["Hey Joe, how hot is the sun?", "hey joe what's left in the queue", "Hey, Joe. Read me the report."])
    assert got == ["how hot is the sun?", "what's left in the queue", "Read me the report."]


def test_the_ways_hey_joe_gets_heard():
    got = _split(["Hey Joel, what time is it?", "Hi Joe, what time is it?", "Okay Joe what time is it",
                  "A Joe, what time is it?", "Hey Jo! What time is it?", "Hey Joe's what time is it",
                  "Um, hey Joe, what time is it?", "Hey Joh, what time is it?", "Hey Jow what time is it"])
    assert all(g and g.lower().rstrip("?").endswith("what time is it") for g in got), got


def test_other_names_dont_wake_him():
    """2026-11-22 review: "Hi Joseph, go" started the saved plan. Only ways of hearing "Joe" itself count,
    not other names people say at home."""
    got = _split(["Hi Joseph, go", "Hey Joseph what time is it", "Hey Joey, dinner!", "Hey Joan, come here",
                  "Hey Joes", "Hey Josephine, go", "Hey Johnny what time is it"])
    assert got[:4] == [None] * 4 and got[5:] == [None, None], got
    assert got[4] == ""                                               # "Joe's" is still "Joe"
    assert "joseph" not in JS.split("const WAKE_JOE = [")[1].split("]")[0]
    assert "joey" not in JS.split("const WAKE_JOE = [")[1].split("]")[0]


def test_own_wake_words_only_wake_on_themselves():
    """Your own wake words: the last word exactly, or with an s ("computers"), not a name that merely starts the same."""
    assert _split(["Hey Joseph, go", "Hey Joe, go", "hey josephs go"], "hey joseph") == ["go", None, "go"]
    assert _split(["hey ann go", "hey anna go", "hey anne go"], "hey ann") == ["go", None, None]


def test_just_the_wake_words_gives_an_empty_question():
    assert _split(["Hey Joe.", "hey joe", "Hey, Joe!"]) == ["", "", ""]


def test_talk_that_isnt_for_joe_is_not_taken():
    got = _split(["I told my brother yesterday that hey Joe is a song", "Joe said he would come", "Hey, what's for dinner?",
                  "The weather is nice today", "", "hey", "hey john, come here",
                  "They enjoyed the show", "Hey Joanna, dinner!", "We watched a Joe movie", "I'm a Joe fan"])
    assert got == [None] * 11, got


def test_a_few_words_before_the_wake_words_are_dropped_with_them():
    """2026-11-22 review (rolling second): the second of sound in front of each recording can carry a word or two
    said just before "Hey Joe". The wake words still count after up to three words, and those words are dropped,
    never passed on. More than that, and it's talk about Joe, not to him."""
    got = _split(["see you later hey Joe what time is it", "Mm. Hey Joe, how hot is the sun?",
                  "okay bye. Hey, Joe. Read me the report.", "one two three four hey joe what time is it"])
    assert got == ["what time is it", "how hot is the sun?", "Read me the report.", None], got


def test_their_own_wake_words():
    got = _split(["Computer wake up, play the report", "Hey Joe, play the report", "computer wakes up now",
                  "Computer, wake up."], "computer wake up")
    assert got == ["play the report", None, None, ""]


def test_only_three_words_may_come_first():
    assert _split(["so um hey joe hello", "well so um hey joe hello", "banana hey joe hello",
                   "well so um uh hey joe hello"]) == ["hello", "hello", "hello", None]


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
    for words in ("Off unless you tick it", "dropped at once", "not sent anywhere", "push-to-talk",
                  "temporary file", "deleted right after", "TV", "asks first", "again"):
        assert words in box, words
    note = HTML.split('id="wake-note">')[1].split("</div>")[0]
    assert note.startswith("When this box is ticked, the microphone turns on by itself every time Joe opens")
    for words in ("dropped at once", "temporary file", "deleted right after", "TV", "asks first", "waits for the wake words again"):
        assert words in note, words
    assert "never leaves this PC" not in note                         # it goes to the voice helper's temporary file


def test_overheard_talk_is_dropped_before_anything_is_shown():
    send = JS.split("async function sendAudio(")[1].split("\n// --- open mic")[0]
    wake = send.split("if (wake) {")[1]
    drop = 'if (t.do === "drop") { busyTalking = false; return; }'
    assert wake.index(drop) < wake.index("talkSend(t.text)") and wake.index(drop) < wake.index('show("talk")')
    assert wake.index(drop) < wake.index("routeText(")                  # not even sent to the router
    assert 'heads["X-Joe-Wake"] = "1"' in send and "if (report && !wake)" in send        # no levels logged either
    assert "talkLog.push" not in wake.split(drop)[0]


def test_the_mic_only_stays_open_off_talk_with_the_wake_word_on():
    start = JS.split("async function openMicStart() {")[1].split("\n}")[0]
    assert '(current !== "talk" && !wakeOn)) return;' in start
    assert "sendAudio(c, report, wakeMode(), ld, lr)" in start
    apply = JS.split("function wakeApply() {")[1].split("\n}")[0]
    assert "else openMicStop();" in apply and 'talkMode === "open"' in apply and "!micMuted" in apply


# --- after the first answer (2026-11-22 review, finding 7): the wake word keeps gating Talk ------------------

def _flow(scenario, routes=None, wake=True, phrase="hey joe"):
    """Run the window's wake-word handling (sendAudio and the yes/no question) under node, with a fake clock,
    no page and no microphone. scenario: JS that calls hear("...") (one recording turned into words),
    tick(ms), and the person's own actions; it ends with done(). routes: what /api/route would say, by text
    (worked out here with joeai.route.classify)."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node isn't installed here (GitHub's test machines have it)")
    from joeai.route import classify
    table = {t: classify(t) for t in (routes or [])}
    parts = [
        JS.split("// >>> wake-word")[1].split("// <<< wake-word")[0],
        "let wakeOn = false" + JS.split("\nlet wakeOn = false")[1].split("// <<< wake-ask")[0],
        "const TALK_ASSIST" + JS.split("\nconst TALK_ASSIST")[1].split("async function talkSend(")[0],
        "async function sendAudio(" + JS.split("async function sendAudio(")[1].split("\n// --- open mic")[0],
    ]
    harness = """
let now = 0, timers = [], tid = 0;
const performance = { now: () => now };
const setInterval = (f, ms) => { const t = { id: ++tid, f, ms, at: now + ms, every: true }; timers.push(t); return t.id; };
const setTimeout = (f, ms) => { const t = { id: ++tid, f, ms, at: now + ms, every: false }; timers.push(t); return t.id; };
const clearInterval = (id) => { timers = timers.filter((t) => t.id !== id); };
async function tick(ms) {
  const end = now + ms;
  for (;;) {
    timers.sort((a, b) => a.at - b.at);
    const t = timers[0];
    if (!t || t.at > end) break;
    now = t.at;
    if (t.every) t.at += t.ms; else timers.shift();
    await t.f();
  }
  now = end;
}
const TOKEN = "x", ROUTES = %s, out = { sent: [], did: [], shown: [], log: [], badge: "", said: [] };
class Blob { constructor(c, o) { this.type = (o && o.type) || ""; } }
async function toWav(b) { return { type: "audio/wav" }; }
let heardNext = "", wakeHeaders = [];
async function fetch(url, o) { wakeHeaders.push(o.headers["X-Joe-Wake"] || ""); return { json: async () => ({ ok: true, text: heardNext }) }; }
let current = "queue", busyTalking = false, voiceReady = true, speakReplies = true, micStream = {}, talkLog = [], talkMode = "open";
function show(name) { current = name; out.shown.push(name); if (name !== "talk") wakeApply(); }
function wakeApply() { if (current === "talk") return; talkMine = false; }
function renderTalk() { out.log = talkLog.map((m) => m.who + ": " + m.text); }
function badge(t) { out.badge = t; }
async function say(t) { out.said.push(t); }
const cleanSpeech = (t) => t;
function talkBusy() { return false; }
async function routeText(t) { return ROUTES[t] || { kind: "chat" }; }
async function talkSend(t) { if (t === undefined) wakeTakeOver(); out.sent.push(t === undefined ? "(typed)" : t); }
async function doCommand(cmd, rt) { out.did.push(cmd); return "Done: " + cmd; }
async function hear(text) { heardNext = text; await sendAudio(["x"], {}, wakeMode(), null, 0); }
function done() { out.mine = talkMine; out.asking = !!wakeAsk; out.headers = wakeHeaders; console.log(JSON.stringify(out)); }
""" % json.dumps(table)
    script = harness + "\n".join(parts) + "\nwakeOn = %s; wakeWords = %s;\n(async () => {\n%s\n})().catch((e) => { console.error(e.stack); process.exit(1); });" % (
        "true" if wake else "false", json.dumps(phrase), scenario)
    r = subprocess.run([node, "-e", script], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=30)        # node writes UTF-8; Windows would read it as its own code page
    assert r.returncode == 0, r.stderr[-1500:]
    return json.loads(r.stdout)


def test_after_joe_answers_he_waits_for_the_wake_words_again():
    out = _flow("""
await hear("Hey Joe, how hot is the sun?");
await hear("and what about the moon?");          // no wake words: dropped, though Talk is on screen now
await tick(60000);
await hear("my phone number is 555 1234");       // still dropped a minute later
await hear("Hey Joe, what about the moon?");
done();""")
    assert out["sent"] == ["how hot is the sun?", "what about the moon?"], out
    assert out["shown"] == ["talk"] and out["mine"] is False
    assert out["headers"] == ["1", "1", "1", "1"]                    # every one sent as wake-word listening (nothing logged)
    assert "Hey Joe" in out["badge"] and "just talk" not in out["badge"]
    assert not any("phone number" in line or "moon?" == line for line in out["log"])


def test_bare_hey_joe_still_takes_the_next_thing_said_then_gates_again():
    out = _flow("""
await hear("Hey Joe.");
const b1 = out.badge;
await hear("how hot is the sun?");               // the question right after "Yes?"
await hear("and the moon?");                     // gated again
await hear("Hey Joe.");
await tick(13000);                               // "Yes?" but nothing said for 12 seconds
const b2 = out.badge;
await hear("and the moon?");
out.b1 = b1; out.b2 = b2;
done();""")
    assert out["sent"] == ["how hot is the sun?"], out
    assert "go ahead" in out["b1"] and "Hey Joe" in out["b2"]
    assert out["log"].count("joe: Yes? I'm listening.") == 2


def test_going_to_talk_yourself_takes_over():
    out = _flow("""
await hear("Hey Joe, how hot is the sun?");
await hear("and the moon?");                     // dropped
wakeTakeOver();                                  // the person clicks the Talk tab / F4 / types / presses the mic button
out.b = out.badge;
await hear("and the moon?");                     // an ordinary Talk session now: just talk
show("files");                                   // left Talk: ...
await hear("Hey Joe, and the stars?");           // ... the next wake word brings it back wake-gated
await hear("and the planets?");
show("files"); show("talk");                     // Talk shown by anything but the person: still wake-gated
await hear("and the comets?");
done();""")
    assert out["sent"] == ["how hot is the sun?", "and the moon?", "and the stars?"], out
    assert "just talk" in out["b"]
    assert out["headers"][2] == ""                                   # the taken-over turn is ordinary Talk


def test_typing_in_talk_is_a_take_over():
    out = _flow("""
await hear("Hey Joe, how hot is the sun?");
await talkSend();                                // typed in Talk and pressed Enter
await hear("and the moon?");
done();""")
    assert out["sent"] == ["how hot is the sun?", "(typed)", "and the moon?"] and out["mine"] is True


ASKS = {
    "Hey Joe, go": ("run", "Start the plan now? Say yes or no."),
    "Hey Joe, start Joe agent": ("agent-start", "Start Joe agent? Say yes or no."),
    "Hey Joe, tell Joe agent to write a poem": ("agent-start", 'Start Joe agent on "write a poem"? Say yes or no.'),
    "Hey Joe, start the newsletter agent": ("agent-start", "Start the newsletter agent? Say yes or no."),
    "Hey Joe, remember that the gate code is 1234": ("memory", 'Remember "the gate code is 1234"? Say yes or no.'),
    "Hey Joe, forget that the gate code is 1234": ("memory", 'Forget "the gate code is 1234"? Say yes or no.'),
    "Hey Joe, remind me at 5 to call the vet": ("remind", None),
    "Hey Joe, add milk to my shopping list": ("list-add", None),
    "Hey Joe, take milk off my shopping list": ("list-done", None),
    "Hey Joe, send my shopping list to my phone": ("list-send", None),
    "Hey Joe, directions to the hardware store": ("directions", None),
    "Hey Joe, where can I buy a cheap air fryer": ("shop", None),
    "Hey Joe, park this: a recipe book": ("park", None),
}


def _routes(said):
    return [said.split(", ", 1)[1]]


@pytest.mark.parametrize("said", list(ASKS))
def test_commands_that_change_things_need_a_yes(said):
    cmd, question = ASKS[said]
    out = _flow("""
await hear(%s);
out.before = out.did.slice(); out.q = out.log[out.log.length - 1]; out.qb = out.badge;
await hear("yes");
done();""" % json.dumps(said), routes=_routes(said))
    assert out["before"] == [] and out["did"] == [cmd], out
    assert out["q"].endswith("Say yes or no.") and out["q"] in ["joe: " + s for s in out["said"]]   # shown and said
    if question:
        assert out["q"] == "joe: " + question
    assert "yes or no" in out["qb"] and out["sent"] == [] and not out["asking"]
    assert out["log"][-2:] == ["you: Yes.", "joe: Done: " + cmd]


@pytest.mark.parametrize("answer", ["no", "No, don't.", "what time is it", "Hey Joe, what time is it?", "yes and also stop"])
def test_no_or_anything_else_cancels_and_is_not_passed_on(answer):
    out = _flow("""
await hear("Hey Joe, go");
await hear(%s);
await hear("yes");                               // too late: the question is closed (and no wake words)
done();""" % json.dumps(answer), routes=["go"])
    assert out["did"] == [] and out["sent"] == [] and not out["asking"], out
    assert out["log"][-1] == "joe: OK, I won't." and "OK, I won't." in out["said"]


def test_silence_cancels_by_itself():
    out = _flow("""
await hear("Hey Joe, go");
await tick(9000);
out.still = !!wakeAsk;
await tick(1500);
await hear("yes");
done();""", routes=["go"])
    assert out["still"] is True and not out["asking"] and out["did"] == [], out
    assert out["log"][-1] == "joe: No answer, so I won't." and "Hey Joe" in out["badge"]


def test_clear_yes_words_and_the_wake_words_may_come_first():
    out = _flow("""
for (const y of ["Yeah.", "Hey Joe, yes.", "Okay, do it.", "Um, yes please", "Sí."]) { await hear("Hey Joe, go"); await hear(y); }
done();""", routes=["go"])
    assert out["did"] == ["run"] * 5, out


def test_the_same_commands_in_your_own_talk_session_run_as_always():
    out = _flow("""
current = "talk"; wakeTakeOver();
await hear("go");
done();""", routes=["go"])
    assert out["headers"] == [""] and out["sent"] == ["go"] and out["did"] == [] and not out["asking"]


def test_reading_and_stopping_need_no_yes():
    out = _flow("""
await hear("Hey Joe, stop");
await hear("Hey Joe, what time is it");
await hear("Hey Joe, what's on my shopping list");
await hear("Hey Joe, what do you remember about me");
done();""", routes=["stop", "what time is it", "what's on my shopping list", "what do you remember about me"])
    assert out["sent"] == ["stop", "what time is it", "what's on my shopping list", "what do you remember about me"]
    assert not out["asking"] and out["did"] == []


def test_a_long_remember_sentence_asks_too():
    said = "Hey Joe, remember that my daughter's birthday is on the third of March every year"
    out = _flow("await hear(%s); done();" % json.dumps(said), routes=_routes(said))
    assert out["asking"] and out["sent"] == [] and out["log"][-1].startswith('joe: Remember "my daughter')


def test_every_command_is_sorted_into_ask_first_or_fine():
    """Each command route.classify can give is either asked about first (through the wake word) or fine as is,
    and the window asks for exactly the first group."""
    import re
    from joeai import route
    cmds = set(route.COMMANDS) | {"agent-start", "memory", "remind", "list-add", "list-done", "list-show",
                                  "list-send", "directions", "shop", "quick", "park", "abilities", "explain"}
    src = (ROOT / "joeai" / "route.py").read_text(encoding="utf-8")
    assert set(re.findall(r'"cmd": "([a-z-]+)"', src)) | set(re.findall(r'\(_[A-Z_]+, "([a-z-]+)"\)', src)) <= cmds
    assert set(route.WAKE_ASK_FIRST) | set(route.WAKE_FINE) == cmds
    assert not set(route.WAKE_ASK_FIRST) & set(route.WAKE_FINE)
    ask = JS.split("function wakeAskFirst(rt) {")[1].split("\n}")[0]
    assert set(re.findall(r'case "([a-z-]+)":', ask)) == set(route.WAKE_ASK_FIRST)


# --- what dropped speech leaves behind on the server (2026-11-22 review, finding 12) --------------------------

from test_voice_docs import app  # noqa: E402,F401


def _listening(app, monkeypatch, reply=None):  # noqa: F811
    from joeai import addons
    monkeypatch.setattr(addons, "voice_ready", lambda: True)
    seen = []

    def call(req, timeout=0):
        p = Path(req["audio"])
        seen.append((p, p.is_file(), p.read_bytes() if p.is_file() else b""))
        if isinstance(reply, Exception):
            raise reply
        return reply or {"ok": True, "text": "and the moon?"}
    monkeypatch.setattr(app.voice, "call", call)
    return seen, addons.voice_dir() / "tmp"


def test_a_wake_word_recording_leaves_no_timing_line_and_no_file(app, monkeypatch):  # noqa: F811
    seen, tmp = _listening(app, monkeypatch)
    assert app.listen(b"RIFFwake", "wav", wake=True)["text"] == "and the moon?"
    assert not getattr(app, "debug_lines", [])                           # nothing about it in MAKE A HELP FILE
    assert seen[0][1] and seen[0][2] == b"RIFFwake" and seen[0][0].name.startswith("heard_")
    assert not list(tmp.glob("heard_*"))
    app.listen(b"RIFFtalk", "wav")                                    # Talk you opened: the timing line, as before
    assert any("Talk timing: hearing" in ln for ln in app.debug_lines)


def test_the_recording_is_deleted_even_when_hearing_fails(app, monkeypatch):  # noqa: F811
    seen, tmp = _listening(app, monkeypatch, reply=RuntimeError("the voice helper fell over"))
    with pytest.raises(RuntimeError):
        app.listen(b"RIFFxx", "wav", wake=True)
    assert seen and not list(tmp.glob("heard_*"))


def test_two_recordings_in_the_same_moment_get_their_own_files(app, monkeypatch):  # noqa: F811
    import time as time_mod
    seen, tmp = _listening(app, monkeypatch)
    monkeypatch.setattr(time_mod, "time", lambda: 1_700_000_000.0)    # the same millisecond
    names = set()

    def call(req, timeout=0):
        names.add(req["audio"])
        if len(names) == 1:
            app.listen(b"RIFFinner", "wav", wake=True)                 # a second one while the first is still being heard
        return {"ok": True, "text": "x"}
    monkeypatch.setattr(app.voice, "call", call)
    app.listen(b"RIFFouter", "wav", wake=True)
    assert len(names) == 2 and not list(tmp.glob("heard_*"))


def test_left_over_recordings_are_swept(app, monkeypatch):  # noqa: F811
    import os
    import time as time_mod
    from joeai.server import sweep_heard
    seen, tmp = _listening(app, monkeypatch)
    tmp.mkdir(parents=True, exist_ok=True)
    old, fresh, other = tmp / "heard_1.wav", tmp / "heard_2.webm", tmp / "say_1.wav"
    for p in (old, fresh, other):
        p.write_bytes(b"x")
    t = time_mod.time() - 3600
    os.utime(old, (t, t))
    os.utime(other, (t, t))
    app.listen(b"RIFFxx", "wav", wake=True)                           # the next recording sweeps first
    assert not old.exists() and fresh.exists() and other.exists()   # one being heard right now is left alone
    os.utime(fresh, (t, t))
    assert sweep_heard(tmp) == 1 and not fresh.exists()


def test_the_server_reads_the_wake_header_and_logs_no_levels_for_it():
    src = (ROOT / "joeai" / "server.py").read_text(encoding="utf-8")
    block = src.split('if u.path == "/api/voice/listen":')[1].split("b = self._body()")[0]
    assert 'wake = self.headers.get("X-Joe-Wake") == "1"' in block
    assert 'note = "" if wake else mic_line(' in block and "app.listen(self.rfile.read(n), ext, wake=wake)" in block
