/* Joe's face in Talk (F4).

The picture is ui/joe.svg (made by the joe-character script, design H). It is fetched from Joe's
own address and put into the page as inline SVG, so the face can change without redrawing Joe:
inside <g id="jf-face"> every eye set (data-eyes) and every mouth (data-mouth) is its own group,
and only one of each is shown. The picture holds no script; this file only shows and hides groups.

What he looks like:
  idle            neutral, blinks now and then
  mic open        listening
  waiting         thinking (eyes up, dots)
  speaking        talk mouths picked by how loud his voice is right now
  run done        happy, for a few seconds
  failed          worried, for a few seconds
  night shift /
  screen saver    sleepy

Setup > Voice & Talk > "Joe's face in Talk": on (moving) | still | off. "still", and the
computer's own "reduce motion" setting, mean no blinking, no flapping mouth, no blinking light:
he still changes face for each state, and shows one open mouth while he speaks.

app.js tells the face what's going on with JoeFace.watch(fn): fn() returns
{ audio, busy, listening, sleepy }. JoeFace.voice(audio, blob) is called for each piece of speech
(the volume is read from a decoded copy of the clip's Blob, so his voice itself is never
re-routed or changed, and nothing new is fetched: the page rules stay as they are), and
JoeFace.mood("happy" | "worried") after a run or a failed answer.
*/
"use strict";
const JoeFace = (() => {
  const MOOD_MS = 6000, TICK_MS = 50, PAUSE_MS = 1200, WIN_S = 0.03;
  const LOOKS = {                     // state -> [eyes, mouth]
    idle: ["neutral", "smile"], listening: ["listen", "soft"], thinking: ["up", "dots"],
    happy: ["happy", "grin"], worried: ["sad", "wobble"], sleepy: ["blink", "flat"],
    pause: ["neutral", "closed"], speaking: ["neutral", "small"],
  };
  const reduceQ = window.matchMedia ? matchMedia("(prefers-reduced-motion: reduce)") : null;
  let root = null, svg = null, mode = "on", probe = () => ({}), timer = 0, loading = null;
  let mood = null, moodUntil = 0, spokeAt = 0, cur = null;       // cur = { el, env, zmid }
  let blinkUntil = 0, nextBlink = 0, mouthHold = 0, lastMouth = "", flap = 0, shown = "";

  const still = () => mode === "still" || !!(reduceQ && reduceQ.matches);
  const visible = () => !!(root && svg && mode !== "off" && !root.hidden && root.offsetParent !== null && !document.hidden);

  function pick(kind, name) {           // show one group of this kind, hide the rest
    if (!svg) return;
    svg.querySelectorAll(`[data-${kind}]`).forEach((g) => {
      if (g.getAttribute(`data-${kind}`) === name) g.removeAttribute("display");
      else g.setAttribute("display", "none");
    });
  }
  function set(eyes, mouth) {
    const key = eyes + "/" + mouth;
    if (key === shown) return;
    shown = key; pick("eyes", eyes); pick("mouth", mouth);
  }

  async function load() {
    if (svg || loading) return loading;
    loading = (async () => {
      const r = await fetch("/joe.svg", { cache: "force-cache" });
      if (!r.ok) throw new Error("no picture");
      const doc = new DOMParser().parseFromString(await r.text(), "image/svg+xml");
      const el = doc.documentElement;
      if (!el || el.nodeName !== "svg" || doc.querySelector("parsererror")) throw new Error("bad picture");
      el.querySelectorAll("script, foreignObject").forEach((n) => n.remove());   // never expected; never run
      svg = document.importNode(el, true);
      svg.setAttribute("aria-hidden", "true");
      root.appendChild(svg);
      shown = ""; set(...LOOKS.idle);
    })().catch(() => { loading = null; if (root) root.hidden = true; });
    return loading;
  }

  // Volume of each 30 ms of a speech clip (0..1) plus how "bright" it sounds (zero crossings),
  // read from a decoded copy. Bright + middling loud -> "Ee", dark -> "Ooh".
  async function envelope(blob) {
    const buf = await blob.arrayBuffer();
    const Ctx = window.OfflineAudioContext || window.webkitOfflineAudioContext;
    if (!Ctx) return null;
    const audio = await new Ctx(1, 1, 22050).decodeAudioData(buf);
    const data = audio.getChannelData(0), win = Math.max(1, Math.round(audio.sampleRate * WIN_S));
    const rms = [], zc = [];
    for (let i = 0; i < data.length; i += win) {
      let s = 0, z = 0, prev = data[i];
      const end = Math.min(data.length, i + win);
      for (let k = i; k < end; k++) { const v = data[k]; s += v * v; if ((v >= 0) !== (prev >= 0)) z++; prev = v; }
      rms.push(Math.sqrt(s / (end - i))); zc.push(z / (end - i));
    }
    const sorted = rms.slice().sort((a, b) => a - b);
    const top = sorted[Math.floor(sorted.length * 0.95)] || 0;
    if (top <= 0) return null;
    const level = rms.map((v) => Math.min(1, v / top));
    const voiced = zc.filter((_, i) => level[i] > 0.25).sort((a, b) => a - b);
    return { level, zc, zmid: voiced.length ? voiced[voiced.length >> 1] : 0 };
  }

  // Which of the five talk mouths fits this loudness (and brightness).
  function mouthFor(level, bright) {
    if (level < 0.1) return "closed";
    if (level < 0.32) return "small";
    if (level >= 0.72) return "wideopen";
    return bright ? "ee" : "ooh";
  }

  function talkMouth(now) {
    if (still()) return "small";
    if (now < mouthHold) return lastMouth;
    let m;
    const c = cur;
    if (c && c.env) {
      const i = Math.floor(c.el.currentTime / WIN_S);
      const lv = c.env.level[i] || 0;
      m = mouthFor(lv, (c.env.zc[i] || 0) > c.env.zmid);
    } else {                                   // still reading the clip: a plain flap
      m = ["small", "wideopen", "closed", "ooh", "small", "ee"][flap++ % 6];
    }
    mouthHold = now + (c && c.env ? 70 : 110);   // no flicker faster than a mouth can move
    lastMouth = m;
    return m;
  }

  function cursorLight(now, look) {
    const c = svg && svg.querySelector("#jf-cursor");
    if (!c) return;
    const on = still() || look === "sleepy" || Math.floor(now / 530) % 2 === 0;
    c.setAttribute("opacity", look === "sleepy" ? "0.35" : on ? "1" : "0.15");
  }

  function dots(now, look) {                   // the thinking dots light up one after another
    if (!svg) return;
    const ds = svg.querySelectorAll('[data-mouth="dots"] circle');
    const step = Math.floor(now / 300) % 3;
    ds.forEach((d, i) => d.setAttribute("opacity", look !== "thinking" || still() || i === step ? "1" : "0.35"));
  }

  function lookNow(now) {
    let p = {};
    try { p = probe() || {}; } catch (e) {}
    const a = p.audio;
    const playing = !!(a && !a.paused && !a.ended);
    if (playing) spokeAt = now;
    if (cur && cur.el !== a) cur = null;       // that clip is over
    if (playing) return "speaking";
    if (p.busy) return now - spokeAt < PAUSE_MS ? "pause" : "thinking";
    if (mood && now < moodUntil) return mood;
    mood = null;
    if (p.sleepy) return "sleepy";
    if (p.listening) return "listening";
    return "idle";
  }

  function tick() {
    if (!visible()) return;
    const now = performance.now();
    const look = lookNow(now);
    let [eyes, mouth] = LOOKS[look];
    if (look === "speaking") mouth = talkMouth(now);
    if ((look === "idle" || look === "speaking" || look === "listening") && !still()) {   // blink
      if (!nextBlink) nextBlink = now + 2500 + Math.random() * 3500;
      if (now >= nextBlink) { blinkUntil = now + 140; nextBlink = now + 2500 + Math.random() * 3500; }
      if (now < blinkUntil) eyes = "blink";
    }
    set(eyes, mouth);
    cursorLight(now, look);
    dots(now, look);
    root.dataset.look = look;
  }

  return {
    // Put Joe in this element (once). mode: "on" | "still" | "off".
    attach(el, m) {
      if (!el) return;
      root = el;
      this.setMode(m);
      if (!timer) {
        timer = setInterval(tick, TICK_MS);
        if (reduceQ && reduceQ.addEventListener) reduceQ.addEventListener("change", () => this.setMode(mode));
      }
    },
    setMode(m) {
      mode = ["on", "still", "off"].includes(m) ? m : "on";
      if (!root) return;
      root.hidden = mode === "off";
      root.classList.toggle("still", still());
      if (mode !== "off") load();
    },
    watch(fn) { if (typeof fn === "function") probe = fn; },
    voice(el, blob) {                          // a piece of speech (its Blob) is about to play
      if (!el || mode === "off") return;
      const c = { el, env: null };
      cur = c;
      if (still() || !blob || typeof blob.arrayBuffer !== "function") return;
      envelope(blob).then((env) => { if (cur === c) c.env = env; }).catch(() => {});
    },
    mood(kind) {
      if (!LOOKS[kind]) return;
      mood = kind; moodUntil = performance.now() + MOOD_MS;
    },
    // for tests and the curious: the pieces that decide his face
    _mouthFor: mouthFor, _looks: LOOKS, _lookNow: lookNow,
  };
})();
