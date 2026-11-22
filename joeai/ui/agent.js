/* The agent window: a small page that shows one agent working. It only READS the agent's state and can ASK
   to stop it (after a yes/no). It cannot start an agent or turn any ability on, so it is no way around
   the risk screens. The window key comes in the address's #t=... part, like Joe's main window. */
"use strict";
let TOKEN = "";
function takeKey() {                            // the key in #t=... is kept for this window, then taken out of the address
  const m = /[#&]t=([\w-]+)/.exec(location.hash || "");
  try {
    if (m) { TOKEN = m[1]; sessionStorage.setItem("joeToken", TOKEN); history.replaceState(null, "", location.pathname); }
    else if (!TOKEN) TOKEN = sessionStorage.getItem("joeToken") || "";
  } catch (e) { if (m) TOKEN = m[1]; }          // storage off: the key still works until a reload
}
takeKey();
window.addEventListener("hashchange", takeKey);  // OPEN WINDOW pressed again while this window is open
const $ = (s) => document.querySelector(s);
const MODERN = ["modern-auto", "modern-night", "modern-day", "futuristic", "contrast-dark", "contrast-light"];
const LARGE = { normal: 1, large: 1.3, larger: 1.6 };
async function api(path, body) {
  const opt = { headers: { "X-NR-Token": TOKEN } };
  if (body !== undefined) { opt.method = "POST"; opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
  let r;
  try { r = await fetch(path, opt); } catch (e) { throw new Error(tr("Joe isn't answering. Is Joe still open?")); }
  if (!r.ok) throw new Error(tr(r.status === 401 ? "This window lost its key. Close it and open it again from Joe." : "Joe didn't answer."));
  return r.json();
}
/* Joe's screens in other languages: the same lines file as the main window (English text -> the other
   language; {1}, {2}... stand for numbers and names). The agent's own words are never changed. */
const LANG = { code: "en", exact: new Map(), pats: [] };
function tr(text) {
  const hit = LANG.exact.get(text);
  if (hit !== undefined) return hit;
  for (const [re, out] of LANG.pats) {
    const m = re.exec(text);
    if (m) return out.replace(/\{(\d+)\}/g, (_, n) => m[Number(n)] ?? "");
  }
  return text;
}
async function loadLang(code) {
  LANG.code = code; LANG.exact = new Map(); LANG.pats = [];
  if (code && code !== "en") {
    try {
      const r = await api("/api/lang?code=" + encodeURIComponent(code));
      for (const [k, v] of Object.entries(r.lines || {})) {
        if (/\{\d+\}/.test(k)) LANG.pats.push([new RegExp("^" + k.replace(/[.*+?^$()|[\]\\]/g, "\\$&").replace(/\\?\{(\d+)\\?\}/g, "(.+?)") + "$"), v]);
        else LANG.exact.set(k, v);
      }
      document.documentElement.dir = r.rtl ? "rtl" : "ltr";
    } catch (e) { /* stays in English */ }
  } else document.documentElement.dir = "ltr";
  document.documentElement.lang = code || "en";
  document.querySelectorAll("[data-t]").forEach((el) => {      // the words that are always on the page
    if (!el.dataset.t) el.dataset.t = el.textContent;
    el.textContent = tr(el.dataset.t);
  });
  lastDraw = "";                                               // draw the rest again in the new language
}
function look(ui, vars) {                       // same look as the main window
  if (!ui) return;
  const ph = /^custom:/.test(ui.phosphor) ? "custom" : ui.phosphor, modern = MODERN.includes(ph), big = LARGE[ui.large_text] || 1;
  document.body.className = `agentwin ph-${ph} crt-${modern ? 0 : ui.crt}${modern ? " modern" : ""}${ui.easy_read ? " easyread" : ""}${big > 1 ? " large" : ""}`;
  document.documentElement.style.setProperty("--fs", Math.round(ui.text_size * big) + "px");
  for (const k in (vars || {})) if (/^--[\w-]+$/.test(k)) document.body.style.setProperty(k, vars[k]);
  if (ui.easy_read) document.body.style.setProperty("--font", '"Atkinson Hyperlegible", system-ui, sans-serif');
}
let wasLive = false, lastName = "", lastKey = "", lastLook = "", lastDraw = "", lastT0 = 0, stopAsked = false, ended = null;
/* Joe's face (ui/joe.js, the picture from Talk; the same on / still / off switch as Talk's). Thinking while he
   plans or picks a step, plain while a step or a helper works, happy on a pass or when he's done, worried on
   a fail or when he's stuck. It is aria-hidden: the status line and the polite line carry the news. */
let faceThinking = false, faceLastStep = "";
const hasFace = typeof JoeFace !== "undefined";
async function faceStart() {
  if (!hasFace) return;
  let mode = "on";
  try { mode = ((await api("/api/voice/status")).settings || {}).face || "on"; } catch (e) { /* the moving face */ }
  const el = $("#aw-sprite");
  el.hidden = mode === "off";
  JoeFace.attach(el, mode);
  JoeFace.watch(() => ({ audio: null, busy: faceThinking, listening: false, sleepy: false }));
}
function faceFor(lv, attention) {
  if (!hasFace) return;
  faceThinking = !attention && /plan|picking|checkpoint|checking|Planner|Checker/i.test(lv.doing || "");
  const st = lv.steps || [], last = st.length ? st[st.length - 1] : "";
  if (last && last !== faceLastStep) {                      // one look per finished step
    faceLastStep = last;
    if (/NOT working|failed|set aside|cut off/i.test(last)) JoeFace.mood("worried");
    else if (/passes its|: done/i.test(last)) JoeFace.mood("happy");
  }
  if (attention) JoeFace.mood("worried");
}
function say(t) { $("#aw-live").textContent = t; }       // the polite line: step changes, finish, stuck only
function list(el, items, mark) {
  el.innerHTML = "";
  items.forEach((x) => { const li = document.createElement("li"); li.textContent = mark(x); el.appendChild(li); });
}
function showLive(lv, attention) {
  const pts = lv.plan || [], done = pts.filter((p) => p.done).length, st = lv.steps || [];
  const doing = attention ? tr(`Needs your answer: ${attention}`)
    : (lv.step ? tr(`Step ${lv.step} of ${lv.of}.`) + " " : "") + (lv.doing || tr("Working")) + " " + tr(`(${lv.minutes} min)`);
  $("#aw-status").textContent = doing;
  $("#aw-stop").hidden = false;
  const draw = JSON.stringify([lv.name, lv.step, lv.of, pts, st]);
  if (draw !== lastDraw) {                                  // the lists are only built again when something changed
    lastDraw = draw;
    $("#aw-title").textContent = tr(`AGENT: ${lv.name}`);
    document.title = `${lv.name} - Joe`;
    $("#aw-bar").style.width = (lv.step && lv.of ? Math.round(100 * (lv.step - 1) / lv.of) : pts.length ? Math.round(100 * done / pts.length) : 0) + "%";
    $("#aw-planbox").hidden = false; $("#aw-end").hidden = true;
    list($("#aw-plan"), pts, (p) => (p.done ? "[x] " : "[ ] ") + p.point);
    list($("#aw-steps"), st.length ? st : [tr("(none yet)")], (x) => x);
    const lis = $("#aw-steps").children;                    // a line with the same number as the one before (a check
    for (let i = 1; i < st.length; i++) {                   // that sent a step back) is shown indented under it
      const a = /^(\d+)\. /.exec(st[i - 1]), b = /^(\d+)\. /.exec(st[i]);
      if (a && b && a[1] === b[1]) { lis[i].textContent = "↳ " + st[i].replace(/^\d+\. /, ""); lis[i].className = "aw-sub"; }
    }
  }
  const key = attention ? "attn" : lv.step + "|" + done;
  if (key !== lastKey) { lastKey = key; say(doing); }
  faceFor(lv, attention);
}
async function findEnd(name, t0) {              // how the run ended: done, stuck, stopped, or not known
  let run = null;
  try {
    const r = await api("/api/agents");
    const a = (r.agents || []).find((x) => x.name === name);
    run = a && a.last_run && a.last_run.status ? a.last_run : null;
    // A stopped run saves no record of its own, so an older run's result must not be shown as this one's.
    const when = run ? Date.parse(run.when) : NaN;
    if (run && t0 && !(when >= t0 * 1000 - 5000)) run = { status: "stopped" };
    if (stopAsked && run && run.status !== "done") run = { status: "stopped" };
  } catch (e) { /* say the plain version below */ }
  return run;
}
function showEnd() {
  const name = ended.name, run = ended.run;
  $("#aw-stop").hidden = true; $("#aw-planbox").hidden = true; $("#aw-end").hidden = false; $("#aw-bar").style.width = "0";
  $("#aw-title").textContent = tr(`AGENT: ${name}`);
  const dot = (s) => (/[.!?]$/.test(s) ? s : s + ".");
  let h, text;
  if (!run) { h = tr("FINISHED"); text = tr(`${name} has stopped. Look in Tools > Agents for its report.`); }
  else if (run.status === "done") {
    h = tr("DONE");
    text = dot((run.note || tr("It finished.")).replace(/\s*\(see [^)]*\)?\s*$/, "")) + " " +
      tr(`The report (AGENT REPORT.md) is in the run's folder (${run.folder || tr("Joe's folder")}). See it in Files (F7).`);
  }
  else if (run.status === "stopped") { h = tr("STOPPED"); text = tr("It was stopped. What it did so far is kept, with its report (see Files, F7)."); }
  else { h = tr("STUCK"); text = dot((run.note || tr("It got stuck.")).replace(/\s*\(see [^)]*\)?\s*$/, "")) + " " + tr("Open the report in Files (F7) to see why and what would help."); }
  faceThinking = false;
  if (hasFace) JoeFace.mood(run && run.status === "done" ? "happy" : "worried");
  $("#aw-end-h").textContent = h; $("#aw-end-text").textContent = text;
  $("#aw-status").textContent = `${name}: ${h}.`;
  return `${name}: ${h}. ${text}`;
}
let busy = false;
async function tick() {
  if (busy) return;
  busy = true;
  try {
    const s = await api("/api/state");
    $("#aw-err").hidden = true;
    const lk = JSON.stringify([s.ui, s.theme]);
    if (lk !== lastLook) { look(s.ui, s.theme); lastLook = lk; }
    const code = (s.ui && s.ui.language) || "en";
    if (code !== LANG.code) { await loadLang(code); if (ended) showEnd(); }
    const lv = s.agent && s.agent.name ? s.agent : null;
    if (lv) {
      ended = null;
      showLive(lv, s.attention);                  // attention: Joe needs the person (e.g. ComfyUI isn't running)
      wasLive = true; lastName = lv.name; lastT0 = lv.t0 || lastT0;
    } else if (wasLive) {
      wasLive = false; lastKey = ""; lastDraw = "";
      ended = { name: lastName, run: await findEnd(lastName, lastT0) };
      stopAsked = false;
      say(showEnd());
    }
  } catch (e) {
    $("#aw-err").hidden = false; $("#aw-err").textContent = e.message || String(e);
  } finally { busy = false; }
}
let opener = null;
function ask() { opener = document.activeElement; $("#aw-confirm").hidden = false; $("#aw-no").focus(); }
function closeAsk() { $("#aw-confirm").hidden = true; if (opener && opener.focus) opener.focus(); }
$("#aw-stop").addEventListener("click", ask);
$("#aw-no").addEventListener("click", closeAsk);
$("#aw-yes").addEventListener("click", async () => {
  closeAsk();
  try {
    await api("/api/stop", {}); stopAsked = true;
    $("#aw-status").textContent = tr("Stopping… it finishes the current step first."); say(tr("Stopping. It finishes the current step first."));
  } catch (e) { $("#aw-err").hidden = false; $("#aw-err").textContent = e.message || String(e); }
});
$("#aw-close").addEventListener("click", () => {
  window.close();                                // works when Joe opened this window; a tab you opened yourself stays
  setTimeout(() => { $("#aw-err").hidden = false; $("#aw-err").textContent = tr("You can close this tab now."); }, 400);
});
document.addEventListener("keydown", (ev) => {
  if ($("#aw-confirm").hidden) return;
  if (ev.key === "Escape") { ev.preventDefault(); closeAsk(); }
  if (ev.key === "Tab") {                          // keep Tab inside the question
    const b = [$("#aw-no"), $("#aw-yes")], i = b.indexOf(document.activeElement);
    ev.preventDefault(); b[(i + (ev.shiftKey ? b.length - 1 : 1)) % b.length].focus();
  }
});
faceStart(); tick(); setInterval(tick, 1500);
