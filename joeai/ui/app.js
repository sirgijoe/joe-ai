/* Joe UI — talks to the local server on 127.0.0.1 with a per-launch token. */
"use strict";
const TOKEN = document.querySelector('meta[name="nr-token"]').content;
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

async function api(path, body) {
  const opt = { headers: { "X-NR-Token": TOKEN } };
  if (body !== undefined) {
    opt.method = "POST";
    opt.headers["Content-Type"] = "application/json";
    opt.body = JSON.stringify(body);
  }
  const r = await fetch(path, opt);
  const j = await r.json();
  if (!r.ok && j.error) throw new Error(j.error);
  return j;
}

/* ---------------- screens ---------------- */
// Left to right on the tab bar: make (F2-F4, F6), see results (F7-F9), set up (F10), help (F1).
const SCREENS = { F1: "help", F2: "queue", F3: "tools", F4: "talk", F6: "builder", F7: "files", F8: "report", F9: "stats", F10: "setup" };
let current = "queue";
function show(name, page) {
  current = name;
  if (name === "setup" && page && typeof setupPage === "function") setupPage(page);
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === "s-" + name));
  $("#title-screen").textContent = name.toUpperCase();
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("on", (SCREENS[b.dataset.key] || "") === name || (name === "about" && b.dataset.key === "F1")));
  if (name === "files") loadDir(dirPath, true);
  if (name === "stats") { loadStats(); loadStorage(); }
  if (name === "setup") loadSetup();
  if (name === "report") loadReport();
  if (name === "builder") loadBuilder();
  if (name === "tools") loadTools();
  if (name === "talk") loadTalk(); else if (typeof openMicStop === "function") openMicStop();
}

let toastTimer;
function toast(msg, ms = 2600) {
  const t = $("#toast");
  t.textContent = " " + msg + " ";
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), ms);
}

let confirmCb = null, confirmNo = null;
const confirmWaiting = [];
function confirmBox(text, cb, noCb) {
  if (!$("#confirm").hidden) { confirmWaiting.push([text, cb, noCb]); return; }
  $("#confirm-text").textContent = text;
  $("#confirm-text").style.whiteSpace = "pre-wrap";
  $("#confirm").hidden = false;
  confirmCb = cb; confirmNo = noCb || null;
}
document.getElementById("confirm-yes").addEventListener("click", (ev) => { ev.stopPropagation(); confirmClose(true); });
document.getElementById("confirm-no").addEventListener("click", (ev) => { ev.stopPropagation(); confirmClose(false); });
function confirmClose(yes) {
  $("#confirm").hidden = true;
  const f = yes ? confirmCb : confirmNo;
  confirmCb = confirmNo = null;
  if (f) f();
  if (confirmWaiting.length) setTimeout(() => confirmBox(...confirmWaiting.shift()), 150);
}

/* ---------------- state polling ---------------- */
let state = null, fails = 0;
function bar(done, total, width = 28) {
  const n = total ? Math.round((done / total) * width) : 0;
  return "█".repeat(n) + "░".repeat(width - n);
}
function fmtEta(s) {
  if (s == null) return "";
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return h ? `${h}h${String(m).padStart(2, "0")}m` : `${m}m`;
}
const THEME_VARS = ["--ph", "--ph-dim", "--ph-faint", "--bg", "--glow", "--accent", "--font"];
function applyTheme(vars) {
  THEME_VARS.forEach((k) => document.body.style.removeProperty(k));
  if (vars) Object.entries(vars).forEach(([k, v]) => document.body.style.setProperty(k, v));
}
// Retro looks (green / amber / white / custom) keep the CRT effect; the modern looks don't use it.
const MODERN = ["modern-auto", "modern-night", "modern-day", "futuristic"];
function applyUI(ui, themeVars) {
  const ph = /^custom:/.test(ui.phosphor) ? "custom" : ui.phosphor;
  const modern = MODERN.includes(ph);
  document.body.className = `ph-${ph} crt-${modern ? 0 : ui.crt}${modern ? " modern" : ""}${ui.easy_read ? " easyread" : ""}`;
  document.documentElement.style.setProperty("--fs", ui.text_size + "px");
  applyTheme(themeVars);
  // Easy-to-read font wins over every look (set inline, like a custom theme's own font).
  if (ui.easy_read) document.body.style.setProperty("--font", '"Atkinson Hyperlegible", system-ui, sans-serif');
  else if (!(themeVars && themeVars["--font"])) document.body.style.removeProperty("--font");
}

let lastLogLen = -1, lastUI = "", lastBusy = "", lastMedia = "", viewing = "", lastFix = -1;
const isVid = (p) => /\.(mp4|webm|mov|mkv|m4v)$/i.test(p);
const playerUrl = (p) => "/player?t=" + encodeURIComponent(TOKEN) + "&path=" + encodeURIComponent(p);
function mediaButtons(p) {
  return `<div class="gbtns"><button type="button" data-window="${esc(p)}" title="Open it big in its own window.">[ BIG WINDOW ]</button>` +
    `<button type="button" data-system="${esc(p)}" title="Open it in your usual picture or video program.">[ OPEN IN PLAYER ]</button>` +
    `<button type="button" data-open="${esc(p)}" title="Find it in Files (F7) to see how it was made, keep or reject it.">[ DETAILS F7 ]</button></div>`;
}
// When the browser can't play a format (e.g. HEVC .mp4, .mkv), say so and offer the PC's player.
function watchVideoErrors(root) {
  root.querySelectorAll("video[data-src-path]").forEach((v) => v.addEventListener("error", () => {
    const box = document.createElement("div");
    box.className = "vfail dim";
    box.textContent = "This video format can't play here. Use OPEN IN PLAYER.";
    v.replaceWith(box);
  }, { once: true }));
}
const EMPTY_JOBS = '<div class="dim">Nothing running. Tell Joe what you need on the left, or build it step by step with F6.</div>';
const EMPTY_GALLERY = '<div class="dim">Pictures and videos Joe makes show up here as soon as each one is done.</div>';
function renderGallery(m) {
  if (!m.length) { $("#gallery").innerHTML = EMPTY_GALLERY; return; }
  const big = isVid(viewing)
    ? `<video class="gbig" src="${rawSrc(viewing)}" data-src-path="${esc(viewing)}" controls muted loop autoplay playsinline></video>`
    : `<img class="gbig" src="${rawSrc(viewing)}" alt="" data-open="${esc(viewing)}">`;
  const thumbs = m.map((p) => isVid(p)
    ? `<span class="gvid${p === viewing ? " on" : ""}" data-view="${esc(p)}"><video class="gth" src="${rawSrc(p)}#t=0.5" muted preload="metadata"></video><b>▶</b></span>`
    : `<img class="gth${p === viewing ? " on" : ""}" src="${rawSrc(p)}" alt="" loading="lazy" data-view="${esc(p)}">`).join("");
  $("#gallery").innerHTML = `<div class="gmain">${big}</div><div class="gname dim">${esc(viewing.split("/").pop())}</div>` +
    mediaButtons(viewing) + `<div class="gstrip">${thumbs}</div>`;
  watchVideoErrors($("#gallery"));
}
document.addEventListener("click", async (ev) => {
  const w = ev.target.closest("[data-window]");
  if (w) { window.open(playerUrl(w.dataset.window), "_blank", "width=1100,height=760"); return; }
  const sy = ev.target.closest("[data-system]");
  if (sy) { const r = await api("/api/open", { path: sy.dataset.system, how: "default" }); if (!r.ok) toast(r.error || "Could not open"); }
});
document.addEventListener("click", (ev) => {
  const t = ev.target.closest("[data-view]");
  if (t) { viewing = t.dataset.view; renderGallery((state && state.media) || []); }
});
let lastRunKey = "";
async function poll() {
  try {
    state = await api("/api/state");
    fails = 0;
  } catch (e) {
    if (++fails === 3) $("#status").innerHTML = "&nbsp;CONNECTION LOST — close this window and start Joe again";
    return;
  }
  heldPlanTick();
  if ((state.attention || "") !== (window._lastAttention || "")) {      // ComfyUI needs the person
    window._lastAttention = state.attention || "";
    if (state.attention) toast(state.attention, 15000);
  }
  const rb = $("#runbtn");
  if (rb) { rb.firstChild.textContent = state.running ? "STOP" : "RUN"; rb.classList.toggle("going", !!state.running); }
  const uiKey = JSON.stringify([state.ui, state.theme]);
  if (uiKey !== lastUI) {
    applyUI(state.ui, state.theme); lastUI = uiKey;
    $("#ver").textContent = "v" + state.version;
    $("#about-ver").textContent = `Joe v${state.version} · GPL-3.0-or-later`;
  }

  // jobs
  const jl = $("#joblist");
  if (!state.jobs.length) { if (jl.dataset.empty !== "1") { jl.innerHTML = EMPTY_JOBS; jl.dataset.empty = "1"; } }
  else {
    jl.dataset.empty = "";
    jl.innerHTML = state.jobs.map((j) => {
      const mark = j.current && state.running ? '<span class="blink">►</span>' : j.status === "done" ? "√" : "·";
      const st = j.status.toUpperCase();
      return `<div class="job ${j.status}">
        <div class="name">${mark} <span class="${j.current ? "bright" : ""}">${esc(j.name)}</span><span class="st">${st}</span></div>
        <div class="bar">${bar(j.parts_done, j.parts_total)} ${j.parts_done}/${j.parts_total}</div>
        <div class="meta">${j.media ? `${j.items} file(s) · ${j.phase === "prompts" ? "writing prompts" : j.phase === "render" ? "rendering" : "AI-generated"}` : `${j.items} items · ${j.words.toLocaleString()} words`} · ${j.retries} retries${j.flags ? " · " + j.flags + " flags" : ""}${j.short ? " · " + j.short + " short" : ""}${j.note ? " · " + esc(j.note) : ""}</div>
      </div>`;
    }).join("");
  }
  // queued missions (run after the current one)
  $("#queued").innerHTML = state.queued && state.queued.length
    ? `<h2 class="sub">NEXT UP</h2>` + state.queued.map((q, i) => `<div class="qrow"><span>${i + 1}.</span><span class="t">${esc(q)}</span><button data-unqueue="${i}">[ X ]</button></div>`).join("")
    : "";
  // newest pictures / videos, shown as soon as each one is made
  const mkey = (state.media || []).join("|");
  if (mkey !== lastMedia) {
    const m = state.media || [];
    if (!m.includes(viewing) || (m[0] && lastMedia.split("|")[0] !== m[0])) viewing = m[0] || "";
    lastMedia = mkey;
    renderGallery(m);
  }
  // log
  if (!state.log.length && lastLogLen) { $("#log").innerHTML = ""; lastLogLen = 0; }
  if (state.log.length !== lastLogLen || state.running) {
    const lg = $("#log");
    const atBottom = lg.scrollTop + lg.clientHeight >= lg.scrollHeight - 30;
    lg.innerHTML = state.log.map((l) => /Finished|Mission|skipped|failed|ERROR|crash/i.test(l) ? `<span class="hl">${esc(l)}</span>` : esc(l)).join("\n");
    if (atBottom) lg.scrollTop = lg.scrollHeight;
    lastLogLen = state.log.length;
  }
  // status bar + F5 label
  const sv = state.services;
  const done = state.jobs.reduce((a, j) => a + j.parts_done, 0);
  const total = state.jobs.reduce((a, j) => a + j.parts_total, 0);
  const loaded = (sv.loaded || [])[0];
  // Plain words: is writing / are pictures ready? (Joe starts Ollama and ComfyUI by himself when needed.)
  const dd = doctorData;
  const plain = (up, inst, busy) => up ? "READY" : busy ? "BUSY" : (dd && !inst) ? "NOT SET UP" : "STARTS WHEN NEEDED";
  const parts = [
    `OLLAMA (THINKING) ${plain(sv.ollama, dd && dd.ollama.installed, false)}`,
    `COMFYUI (MEDIA) ${plain(sv.comfyui, dd && dd.comfyui.installed, state.running)}`,   // a big model loading can keep it from answering
    `MODEL ${state.model}${loaded ? " " + loaded.gpu_pct + "% GPU" : ""}`,
    state.running ? (state.stopping ? "STOPPING…" : `RUNNING ${done}/${total} ETA ${fmtEta(state.eta_s)}` + (state.queued_eta_s ? ` · ALL ${(state.queued || []).length + 1} MISSIONS ~${fmtEta((state.eta_s || 0) + state.queued_eta_s)}` : "")) : (state.busy ? state.busy.toUpperCase() + (state.busy_pct != null ? " " + Math.round(state.busy_pct) + "%" : "") + "…" : "IDLE"),
  ];
  const hw = state.hw;
  let gpuHtml = "";
  if (hw) {
    const t = hw.temp_c, lim = state.pause_c;
    const hot = t != null && lim && t >= lim - 5;
    const bits = [t != null ? `${t}°C` : null, hw.util_pct != null ? `${hw.util_pct}%` : null,
      hw.vram_total_mb ? `${(hw.vram_used_mb / 1024).toFixed(1)}/${(hw.vram_total_mb / 1024).toFixed(0)}G` : null,
      hw.power_w != null ? `${Math.round(hw.power_w)}W` : null, hw.fan_pct != null ? `FAN ${hw.fan_pct}%` : null].filter(Boolean);
    gpuHtml = `<span class="${hot ? "hot blink" : ""}" title="${esc(hw.name || "GPU")}">GPU ${esc(bits.join(" "))}</span>`;
  }
  $("#status").innerHTML = parts.map((p) => `<span>${esc(p)}</span>`).join("") + gpuHtml;
  if (state.busy !== lastBusy) { lastBusy = state.busy; if (!state.busy) loadDoctor(); }
  const fr = state.fix_result || {};
  if (fr.n && fr.n !== lastFix) {
    if (lastFix !== -1 && !fr.ok) confirmBox("That setup didn't finish.\n\nThe log on the main screen says why. If you're stuck, Setup (F10) > System check > MAKE A HELP FILE packs up what's needed for someone to help.\n\nOpen the log now?", () => show("queue"));
    else if (lastFix !== -1 && fr.ok) toast("Setup finished");
    lastFix = fr.n;
  } else if (lastFix === -1) lastFix = fr.n || 0;
  $("#busy") && ($("#busy").textContent = state.busy ? state.busy + (state.busy_pct != null ? ` ${Math.round(state.busy_pct)}%` : "") + "…" : "");
  $("#f5label").textContent = state.running ? "Stop" : "Run";
  const runKey = `${state.running}:${(state.finished || {}).n}:${state.chain}`;
  if (runKey !== lastRunKey) { if (lastRunKey) loadChats(); lastRunKey = runKey; }   // runs show up in the chat list
  welcomeTick();
  comfortTick();
  $("#btn-run").innerHTML = state.running ? '[ STOP <span class="k">F5</span> ]' : '[ RUN <span class="k">F5</span> ]';
}

/* ---------------- "just describe it": plain words -> plan -> RUN ---------------- */
function showPlan(r) {
  $("#plan-list").innerHTML = r.summary.map((s) => `<li>${esc(s)}</li>`).join("");
  $("#plan-time").textContent = "— " + r.time;
  $("#plan-warn").innerHTML = (r.warnings || []).map((w) => `<div class="warn">! ${esc(w)}</div>`).join("");
  $("#plancard").hidden = false;
}
function hidePlan() { $("#plancard").hidden = true; $("#plan-list").innerHTML = ""; }
async function refreshPlan() {                 // keep the plain plan in step with the mission text
  const text = $("#mission").value;
  if (!text.trim()) { hidePlan(); return; }
  try { const r = await api("/api/summary", { text }); if (r.ok) showPlan(r); else hidePlan(); } catch (e) {}
}
let describing = false;
// One box for everything: short words run right away, questions go to Talk, work gets a plan.
const COMMAND_SAY = { run: "Starting the plan.", stop: "Stopping after the current step.",
  help: "Here's the help page.", report: "Here's the last report.", files: "Here are your files.",
  tools: "Here are the tools.", setup: "Here's Setup.", check: "Here's what Joe found on this PC.",
  updates: "Checking for updates to Joe, Ollama, ComfyUI and your models…", new: "New chat: a fresh start.",
  talk: "Talk to Joe here.", builder: "Build it step by step here.", stats: "Here are the numbers." };
async function doCommand(cmd) {
  const say = COMMAND_SAY[cmd] || "";
  if (cmd === "run") {
    if (state && state.running) return "Joe is already working. Say stop to stop.";
    if (!$("#mission").value.trim()) return "There's no plan yet. Tell Joe what to make first, then say go.";
    await runOrStop(); return say;
  }
  if (cmd === "stop") { if (state && state.running) { await api("/api/stop", {}); return say; } return "Nothing is running."; }
  if (cmd === "new") { await freshStart(); return say; }
  if (cmd === "check") { show("setup", "system"); loadDoctor(); return say; }
  if (cmd === "updates") { show("setup", "system"); await checkUpdate(true); setTimeout(loadDoctor, 6000); return say; }
  const scr = { help: "help", report: "report", files: "files", tools: "tools", setup: "setup", talk: "talk",
    builder: "builder", stats: "stats" }[cmd];
  if (scr) show(scr);
  return say;
}
async function routeText(text) {
  try { return await api("/api/route", { text }); } catch (e) { return { kind: "plan" }; }
}
async function describeIt() {
  const text = $("#describe").value.trim();
  if (!text) { $("#describe-msg").textContent = "Type what you need first."; $("#describe").focus(); return; }
  if (describing) return;
  const rt = await routeText(text);
  if (rt.kind === "command") { $("#describe").value = ""; $("#describe-msg").textContent = await doCommand(rt.cmd); return; }
  if (rt.kind === "unclear") { $("#describe-msg").textContent = rt.say; return; }
  if (rt.kind === "chat") { $("#describe").value = ""; $("#describe-msg").textContent = ""; show("talk"); await talkSend(text); return; }
  describing = true;
  $("#btn-describe").disabled = true;
  $("#describe-msg").innerHTML = '<span class="blink">Joe is planning…</span> this takes a few seconds';
  try {
    const r = await api("/api/describe", { text });
    if (!r.ok) { $("#describe-msg").textContent = r.error; return; }
    takePlan(r);
  } catch (e) { $("#describe-msg").textContent = e.message; }
  finally { describing = false; $("#btn-describe").disabled = false; }
}
function takePlan(r) {
    $("#mission").value = r.mission;
    api("/api/mission/save", { text: r.mission });
    $("#plan").textContent = "";
    showPlan(r);
    $("#describe-msg").textContent = "Here's the plan. Change it, or press RUN IT.";
    loadChats();
}
function heldPlanTick() {                        // a request held while Joe was drawing is ready
  const h = state && state.held_plan;
  if (!h || h.status !== "ready") return;
  api("/api/describe/held", {});
  state.held_plan = {};
  if (h.result && h.result.ok) { takePlan(h.result); toast("Joe planned what you asked for earlier. Check it on the Home screen."); }
  else if (h.result) { $("#describe-msg").textContent = h.result.error; }
}
$("#describe").addEventListener("keydown", (ev) => {
  if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); describeIt(); }
});
try { $("#adv").open = localStorage.getItem("joe-adv") === "1"; } catch (e) {}
$("#adv").addEventListener("toggle", () => { try { localStorage.setItem("joe-adv", $("#adv").open ? "1" : "0"); } catch (e) {} });

/* ---------------- queue actions ---------------- */
async function checkMission() {
  const r = await api("/api/check", { text: $("#mission").value });
  refreshPlan();
  if (!r.ok) { $("#plan").textContent = "ERROR: " + r.error; if (!$("#adv").open) toast(r.error); return null; }
  $("#plan").textContent =
    `PROJECT ${r.project || "(none)"}\n` +
    r.jobs.map((j) => ` [${j.type}] ${j.name}: ${j.type === "image" || j.type === "video" ? `${j.prompts} prompt(s) x ${j.variants} = ${j.prompts * j.variants} ${j.type}(s)${j.workflow ? " via " + j.workflow : ""}` : j.guided ? j.parts + " guided parts" : `${j.parts} x ${j.size} = ${j.items} items`} -> Output/${j.save}${j.min_words ? "  (min " + j.min_words + " words)" : ""}${j.project && j.project !== r.project ? "  {" + j.project + "}" : ""}`).join("\n") +
    `\nESTIMATE about ${r.eta_min} min` + (r.warnings && r.warnings.length ? "\nWARNING " + r.warnings.join("\nWARNING ") : "");
  return r;
}
async function runOrStop() {
  if (state && state.running) {
    confirmBox("Stop the run after the current step? It can resume later.", async () => {
      await api("/api/stop", {});
      toast("Stopping after current step");
    });
    return;
  }
  if (!$("#mission").value.trim()) {           // nothing planned yet: plan it first, never auto-run
    show("queue");
    if ($("#describe").value.trim()) await describeIt();
    else { toast("Tell Joe what you need first"); $("#describe").focus(); }
    return;
  }
  const r = await checkMission();
  if (!r) { show("queue"); return; }
  const res = await api("/api/run", { text: $("#mission").value });
  if (!res.ok) { $("#plan").textContent = "ERROR: " + res.error; return; }
  toast("Mission started — safe to close this window");
}
async function loadReport() {
  const r = await api("/api/report");
  $("#report").textContent = r.text || "No report yet. One is written when a run finishes.";
}
let saveTimer;
$("#mission").addEventListener("input", () => {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => { api("/api/mission/save", { text: $("#mission").value }); refreshPlan(); }, 800);
});

/* ---------------- files ---------------- */
let dirPath = "", entries = [], sel = 0, grid = false, dirAI = false, pendingSelect = "";
function openInFiles(p) {                     // jump to a file in F7 and select it
  const parts = p.split("/");
  pendingSelect = parts.pop();
  dirPath = parts.join("/");
  show("files");
}
document.addEventListener("click", (ev) => {
  const t = ev.target.closest("[data-open]");
  if (t) openInFiles(t.dataset.open);
});
try { grid = localStorage.getItem("nr-grid") === "1"; } catch (e) {}
const RV = { keep: "√", reject: "×", star: "★" };
const rawSrc = (p) => "/raw?t=" + encodeURIComponent(TOKEN) + "&path=" + encodeURIComponent(p);
function fmtDate(t) {
  const d = new Date(t * 1000);
  const p = (n) => String(n).padStart(2, "0");
  let h = d.getHours(); const ap = h >= 12 ? "p" : "a"; h = h % 12 || 12;
  return `${p(d.getMonth() + 1)}-${p(d.getDate())}-${String(d.getFullYear()).slice(2)} ${h}:${p(d.getMinutes())}${ap}`;
}
async function loadDir(path, keepSel) {
  let r;
  try { r = await api("/api/files?path=" + encodeURIComponent(path)); }
  catch (e) { toast(e.message); return; }
  dirPath = r.path; dirAI = r.ai;
  entries = (dirPath ? [{ name: "..", dir: true, up: true }] : []).concat(r.entries);
  if (!keepSel) sel = 0;
  if (pendingSelect) {
    const i = entries.findIndex((e) => e.name === pendingSelect);
    if (i >= 0) sel = i;
    pendingSelect = "";
  }
  sel = Math.min(sel, Math.max(entries.length - 1, 0));
  $("#dirpath").textContent = "C:\\JOE\\" + dirPath.replace(/\//g, "\\");
  const files = r.entries.filter((e) => !e.dir), bytes = files.reduce((a, e) => a + e.size, 0);
  $("#dirfoot").textContent = `${files.length} file(s) ${bytes.toLocaleString()} bytes · ${r.entries.length - files.length} dir(s)`;
  renderDir();
  previewSel();
}
function thumb(e) {
  if (e.dir) return `<div class="th ph">${e.up ? ".." : "DIR"}</div>`;
  const p = join(dirPath, e.name);
  if (e.kind === "image") return `<img class="th" loading="lazy" src="${rawSrc(p)}" alt="">`;
  if (e.kind === "video") return `<span class="gvid"><video class="th" preload="metadata" muted src="${rawSrc(p)}#t=0.5"></video><b>▶</b></span>`;
  return `<div class="th ph">${esc((e.name.split(".").pop() || "").toUpperCase().slice(0, 4))}</div>`;
}
function renderDir() {
  const hasMedia = entries.some((e) => e.kind);
  const g = grid && hasMedia;
  $("#dir").classList.toggle("grid", g);
  $("#dir").innerHTML = entries.map((e, i) => `<div class="ent${i === sel ? " sel" : ""}${e.hidden ? " hid" : ""}${e.review ? " rv-" + e.review : ""}" data-i="${i}">
      ${g ? thumb(e) : ""}<span><span class="rv">${RV[e.review] || ""}</span>${esc(e.name)}</span><span class="r">${e.dir ? "&lt;DIR&gt;" : e.size.toLocaleString()}</span><span class="dt">${e.up ? "" : fmtDate(e.mtime)}</span></div>`).join("");
  const el = $("#dir .sel");
  if (el) el.scrollIntoView({ block: "nearest" });
}
const join = (a, b) => (a ? a + "/" + b : b);
function selPath() {
  const e = entries[sel];
  if (!e) return null;
  return e.up ? dirPath.split("/").slice(0, -1).join("/") : join(dirPath, e.name);
}
let pvTimer;
function previewSel() {
  clearTimeout(pvTimer);
  pvTimer = setTimeout(async () => {
    const e = entries[sel], pv = $("#preview");
    if (!e) { pv.innerHTML = ""; return; }
    if (e.dir) { pv.innerHTML = `<pre class="dim">${e.up ? "Parent folder" : "Folder — Enter to open"}</pre>`; return; }
    const p = selPath();
    let r;
    try { r = await api("/api/preview?path=" + encodeURIComponent(p)); } catch (err) { pv.textContent = err.message; return; }
    const src = rawSrc(p);
    if (r.kind === "image" || r.kind === "video") {
      const m = r.meta || {}, ai = m.ai_generated || dirAI;
      const rows = [["prompt", m.prompt], ["negative", m.negative], ["seed", m.seed], ["model", m.model],
        ["workflow", m.workflow], ["size", m.size], ["made", m.created], ["review", m.review ? RV[m.review] + " " + m.review : ""]]
        .filter(([, v]) => v !== undefined && v !== "" && v !== null);
      pv.innerHTML = (r.kind === "image" ? `<img src="${src}" alt="${esc(r.name)}">` : `<video src="${src}" data-src-path="${esc(p)}" controls loop playsinline></video>`) +
        mediaButtons(p).replace(/<button type="button" data-open[^]*?<\/button>/, "") +
        (ai ? `<div><span class="aitag inv">AI-GENERATED</span> <span class="dim small">not a photo of a real product</span></div>` : "") +
        `<div class="meta-panel"><div class="dim">${esc(r.name)} · ${r.size.toLocaleString()} bytes</div>` +
        rows.map(([k, v]) => `<div><b>${k}</b> ${esc(v)}</div>`).join("") +
        `<div class="dim small">K keep · X reject · S star · M make MP4</div></div>`;
      watchVideoErrors(pv);
    }
    else if (r.kind === "text") pv.innerHTML = `<pre>${esc(r.text)}${r.truncated ? "\n\n…(preview cut off — press E to open the whole file)" : ""}</pre>`;
    else pv.innerHTML = `<pre class="dim">${esc(r.name)}\n${r.size.toLocaleString()} bytes\nNo preview. Enter opens it in its usual program.</pre>`;
  }, 90);
}
async function openSel(how) {
  const p = selPath(); if (p == null) return;
  const r = await api("/api/open", { path: p, how });
  if (!r.ok) toast(r.error || "Could not open");
}
async function reviewSel(mark) {
  const e = entries[sel]; if (!e || e.dir) return;
  const r = await api("/api/review", { path: selPath(), mark });
  if (!r.ok) { toast(r.error); return; }
  e.review = r.mark; renderDir(); previewSel();
  toast(r.mark ? `Marked ${r.mark}` : "Mark cleared");
  if (r.mark && sel < entries.length - 1) { sel++; renderDir(); previewSel(); }
}
async function mp4Sel() {
  const e = entries[sel]; if (!e || e.dir) return;
  toast("Converting…");
  const r = await api("/api/to_mp4", { path: selPath() });
  if (!r.ok) { toast(r.error); return; }
  toast("Saved " + r.name); loadDir(dirPath, true);
}
async function loadMissionSel() {
  const p = selPath(); if (p == null || entries[sel].dir) return;
  const r = await api("/api/load_mission", { path: p });
  if (!r.ok) { toast(r.error); return; }
  $("#mission").value = r.text;
  show("queue");
  checkMission();
  toast("Mission loaded — F5 to run");
}
function enterSel() {
  const e = entries[sel]; if (!e) return;
  if (e.dir) { loadDir(selPath(), false); } else { openSel("default"); }
}
// Update the highlight in place (rebuilding the rows between clicks breaks double-click).
function markSel() {
  document.querySelectorAll("#dir .ent").forEach((el) => el.classList.toggle("sel", +el.dataset.i === sel));
}
// Double-click is detected by hand (two presses on the same row within 500 ms),
// so it works no matter how the browser counts clicks.
let lastPress = { i: -1, t: 0 };
$("#dir").addEventListener("mousedown", (ev) => {
  const row = ev.target.closest(".ent"); if (!row || ev.button !== 0) return;
  ev.preventDefault();                       // no text selection on double-click
  $("#dir").focus();
  const i = +row.dataset.i, now = performance.now();
  const dbl = lastPress.i === i && now - lastPress.t < 500;
  lastPress = dbl ? { i: -1, t: 0 } : { i, t: now };
  if (i !== sel) { sel = i; markSel(); previewSel(); }
  if (dbl) enterSel();
});

/* ---------------- stats ---------------- */
async function loadStats() {
  const s = await api("/api/stats");
  const n = (x) => Number(x).toLocaleString();
  const cards = [
    [n(s.words), "words written"], [n(s.items), "items"], [n(s.files), "files"],
    [n(s.code_lines), "lines of code"], [n(s.tasks), "tasks"], [n(s.parts), "parts done"],
    [n(s.retries), "retries"], [n(s.nights), "nights run"], [s.model_hours + " h", "model run time"],
    [n(s.tokens_in + s.tokens_out), "local tokens"], ["$" + s.cloud_cost_avoided.toFixed(2), "est. cloud cost avoided"],
    ["$" + s.electricity_cost.toFixed(2), "est. electricity"],
  ];
  $("#stats").innerHTML = cards.map(([v, l]) => `<div class="stat"><div class="v">${esc(v)}</div><div class="l">${esc(l)}</div></div>`).join("") +
    (Object.keys(s.models).length ? `<div class="stat"><div class="l">models used</div><pre class="out">${esc(Object.entries(s.models).map(([m, c]) => `${m}  ${c} calls`).join("\n"))}</pre></div>` : "");
}

/* ---------------- storage (F9) ---------------- */
function fmtBytes(b) {
  const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0; b = Number(b) || 0;
  while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
  return (i ? b.toFixed(b < 10 ? 1 : 0) : b) + " " + u[i];
}
async function loadStorage() {
  let s;
  try { s = await api("/api/storage"); } catch (e) { $("#storage").textContent = e.message; return; }
  const max = Math.max(1, ...s.rows.map((r) => r.bytes));
  const disk = s.disk ? `<div class="srow total"><span class="sl">Disk free</span><span class="sb">${fmtBytes(s.disk.free)} of ${fmtBytes(s.disk.total)}</span><span class="sbar">${bar(s.disk.total - s.disk.free, s.disk.total, 24)}</span></div>` : "";
  $("#storage").innerHTML =
    s.rows.map((r) => `<div class="srow" title="${esc(r.path)}"><span class="sl">${esc(r.label)}</span><span class="sb">${fmtBytes(r.bytes)} · ${Number(r.files).toLocaleString()} file${r.files === 1 ? "" : "s"}</span><span class="sbar">${bar(r.bytes, max, 24)}</span></div>`).join("") +
    `<div class="srow total"><span class="sl">Workspace total</span><span class="sb">${fmtBytes(s.workspace_bytes)}</span><span class="sbar"></span></div>` + disk;
  $("#cleanups").innerHTML = s.cleanups.map((c) =>
    `<div class="issue"><span class="t">${esc(c.label)}: ${c.count ? `${c.count} item${c.count === 1 ? "" : "s"}, ${fmtBytes(c.bytes)}` : '<span class="dim">nothing to clean</span>'}</span>` +
    (c.count ? `<button type="button" title="Move these to the Recycle Bin (asks first)." data-clean="${esc(c.kind)}" data-label="${esc(c.label)}" data-count="${c.count}" data-bytes="${c.bytes}">[ CLEAN ]</button>` : "") + "</div>").join("");
}
$("#cleanups").addEventListener("click", (ev) => {
  const b = ev.target.closest("[data-clean]"); if (!b) return;
  const d = b.dataset;
  confirmBox(`${d.label}\n\nMove ${d.count} item${d.count === "1" ? "" : "s"} (${fmtBytes(d.bytes)}) to the Recycle Bin?`, async () => {
    try {
      const r = await api("/api/storage/clean", { kind: d.clean });
      toast(r.error ? r.error : `Freed ${fmtBytes(r.freed)} (${r.moved} moved to the Recycle Bin)` + (r.errors && r.errors.length ? `, ${r.errors.length} skipped` : ""));
    } catch (e) { toast(e.message); }
    loadStorage();
  });
});

/* ---------------- setup ---------------- */
const getPath = (o, p) => p.split(".").reduce((a, k) => (a == null ? a : a[k]), o);
function setPath(o, p, v) { const ks = p.split("."); let cur = o; ks.slice(0, -1).forEach((k) => (cur = cur[k] = cur[k] || {})); cur[ks.at(-1)] = v; }
// --- chats list (left of Talk) -----------------------------------------------------------
let chatCurrent = "", chatFindTimer = null;
const kb = (n) => n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(0)} KB` : `${(n / 1048576).toFixed(1)} MB`;
function chatGroup(iso) {
  const d = new Date(iso), now = new Date();
  const day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((day(now) - day(d)) / 86400000);
  if (isNaN(diff)) return "Older";
  return diff <= 0 ? "Today" : diff === 1 ? "Yesterday" : diff < 7 ? "Previous 7 days" : diff < 30 ? "Previous 30 days" : "Older";
}
async function loadChats() {
  const q = ($("#chat-find").value || "").trim();
  let d;
  try { d = await api("/api/chats" + (q ? "?q=" + encodeURIComponent(q) : "")); }
  catch (e) { $("#chat-list").textContent = e.message; return; }
  chatCurrent = d.current || "";
  let last = "", html = "";
  for (const c of d.chats) {
    const g = chatGroup(c.updated || c.started);
    if (g !== last) { html += `<div class="chatgroup">${g.toUpperCase()}</div>`; last = g; }
    html += `<div class="chatrow${c.id === chatCurrent ? " on" : ""}" tabindex="0" data-chat="${esc(c.id)}" title="${esc(c.title)}">` +
      `<span class="t">${esc(c.title)}</span><button type="button" class="x" data-chatdel="${esc(c.id)}" title="Delete this chat">✕</button></div>`;
  }
  $("#chat-list").innerHTML = html || `<div class="dim small">${q ? "No chats match." : "Your chats with Joe show up here. Each time Joe opens you get a fresh one."}</div>`;
  $("#chat-foot").textContent = d.chats.length ? `${d.chats.length} chat(s), ${kb(d.bytes)}` +
    (d.keep_days > 0 ? ` · older than ${d.keep_days} days are deleted` : " · kept until you delete them") : "";
  document.querySelector('[data-act="chats-delall"]').hidden = !d.chats.length || !!q;
}
async function chatOpen(id) {
  if (current !== "talk") show("talk");
  if (id === chatCurrent) return;
  talkStop();
  const r = await api("/api/chats/open", { id });
  if (!r.ok) { toast(r.error); return loadChats(); }
  talkLog = r.chat.messages.map((m) => ({ ...m, mission: m.mission || "", sources: m.sources || [] }));
  renderTalk(); loadChats();
  $("#talk-in").focus();
}
function chatDelete(id) {
  confirmBox("Delete this chat? It can't be brought back.", async () => {
    if (id === chatCurrent) talkStop();
    const r = await api("/api/chats/delete", { id });
    if (r.was_current) { talkLog = []; renderTalk(); }
    loadChats();
  });
}
document.addEventListener("click", (ev) => {
  const x = ev.target.closest && ev.target.closest("[data-chatdel]");
  if (x) { ev.stopPropagation(); chatDelete(x.dataset.chatdel); return; }
  const row = ev.target.closest && ev.target.closest(".chatrow");
  if (row) chatOpen(row.dataset.chat);
});
$("#chat-list").addEventListener("keydown", (ev) => {
  const row = ev.target.closest(".chatrow"); if (!row) return;
  if (ev.key === "Enter") { ev.preventDefault(); chatOpen(row.dataset.chat); }
  if (ev.key === "Delete") { ev.preventDefault(); chatDelete(row.dataset.chat); }
  if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
    ev.preventDefault();
    const rows = [...document.querySelectorAll("#chat-list .chatrow")], i = rows.indexOf(row);
    const n = rows[i + (ev.key === "ArrowDown" ? 1 : -1)]; if (n) n.focus();
  }
});
// The chat list sits on the left of every screen (like a chat app); hide it with « or the
// Chats button at the top. Remembered on this PC.
function chatsShown(on) {
  document.body.classList.toggle("nochats", !on);
  $("#chats-btn").classList.toggle("on", on);
  try { localStorage.setItem("joe-chats", on ? "1" : "0"); } catch (e) {}
}
(() => { let on = true; try { on = localStorage.getItem("joe-chats") !== "0"; } catch (e) {} chatsShown(on); loadChats(); })();
$("#chat-find").addEventListener("input", () => { clearTimeout(chatFindTimer); chatFindTimer = setTimeout(loadChats, 250); });

// --- quality vs speed: show what the chosen level means, right under it ----------------------
// Which System-check offer fits each kind of work at each level (first one found wins).
const Q_ADVICE = {
  writing: { low: ["pull-model", "pull-small-model"], medium: ["pull-model", "upgrade-model"], high: ["pull-model", "upgrade-model"] },
  pictures: { low: ["get-image-model"], medium: ["get-image-model"], high: ["get-image-model"] },
  video: { low: ["get-video-model", "get-video-turbo"], medium: ["get-video-model", "get-video-turbo"], high: ["get-video-model"] },
};
const Q_LEVEL = { low: "Low", medium: "Medium", high: "High" };
function qualityHelp() {
  document.querySelectorAll(".qhelp").forEach((d) => {
    const sel = document.querySelector(`[data-path="quality.${d.dataset.q}"]`);
    d.textContent = sel ? (d.dataset[sel.value] || "") : "";
    let adv = d.nextElementSibling;
    if (!adv || !adv.classList.contains("qadvice")) { adv = document.createElement("div"); adv.className = "qadvice"; d.after(adv); }
    const issues = (doctorData && doctorData.issues) || [];
    const ids = sel ? Q_ADVICE[d.dataset.q][sel.value] : [];
    const i = issues.findIndex((it) => ids.includes(it.id) && it.what);
    adv.innerHTML = i < 0 ? "" : `<span>Based on your ${Q_LEVEL[sel.value]} setting, I'd recommend ${esc(issues[i].what)} for this. Should we install it?</span>` +
      ` <button type="button" data-fix="${i}" title="Joe asks once more, then downloads it. You can keep using him meanwhile.">[ YES, INSTALL IT ]</button>`;
  });
}
document.addEventListener("change", async (ev) => {
  if (!(ev.target.dataset && /^quality\./.test(ev.target.dataset.path || ""))) return;
  qualityHelp();
  await saveSetup();                  // the advice depends on the saved level (e.g. Low writing)
  await loadDoctor(); qualityHelp();
});

// --- permissions ------------------------------------------------------------------
async function micPermission() {
  try { return (await navigator.permissions.query({ name: "microphone" })).state; }   // granted | prompt | denied
  catch (e) { return "unknown"; }
}
async function showPerms() {
  const el = $("#perm-mic"); if (!el) return;
  const st = await micPermission();
  el.textContent = { granted: "allowed", prompt: "not asked yet", denied: "blocked", unknown: "unknown" }[st];
  $("#perm-mic-help").textContent = st === "denied"
    ? "It's blocked. Click the lock or microphone icon at the top of this window, set Microphone to Allow, then press ALLOW MICROPHONE again. If it's still blocked, check Windows Settings > Privacy & security > Microphone."
    : st === "granted" ? "Joe remembers this. You won't be asked again." : "";
}
async function allowMic() {
  try {
    const s = await navigator.mediaDevices.getUserMedia({ audio: true });
    s.getTracks().forEach((t) => t.stop());
    toast("Microphone allowed. Joe will remember.");
  } catch (e) { toast("The microphone wasn't allowed."); }
  showPerms();
}

let doctorData = null;
async function loadDoctor() {
  let d;
  try { d = await api("/api/doctor"); } catch (e) { $("#doctor").textContent = e.message; return null; }
  doctorData = d;
  readyBanner(d);
  const g = d.gpu, o = d.ollama, c = d.comfyui;
  const tl = $("#dl-talkmodels"); if (tl) tl.innerHTML = o.models.map((m) => `<option value="${esc(m.name)}">`).join("");
  const yes = (b) => (b ? "YES" : "no ");
  $("#doctor").textContent =
    `GPU      ${g ? `${g.name}  ${d.vram_gb ? `${d.vram_gb} GB ${g.unified ? "shared memory" : "VRAM"}` : "(shares main memory)"}` : "no graphics card found"}   RAM ${d.ram_gb} GB   ${d.os || ""}  installs: ${d.pkg || "by hand"}\n` +
    (d.gpu_advice ? `         ${d.gpu_advice}\n` : "") +
    `OLLAMA   installed ${yes(o.installed)} running ${yes(o.running)}  models: ${o.models.map((m) => m.name).join(", ") || "none"}\n` +
    `         best fit installed: ${o.best || "-"}   in use: ${o.configured}\n` +
    `COMFYUI  installed ${yes(c.installed)} running ${yes(c.running)}  ${c.url}\n` +
    (c.found ? `         found: ${c.found.label}  ${c.found.command}\n         models folder: ${c.found.models_dir || "not found"}\n` : "") +
    `         models: ${c.models.length} (${[...new Set(c.models.map((m) => m.family))].join(", ") || "none"})  best image: ${c.best_image || "-"}  best video: ${c.best_video || "-"}\n` +
    `FFMPEG   ${d.ffmpeg || "not found"}\n` +
    `PANDOC   ${d.pandoc || "not found"}`;
  if (typeof qualityHelp === "function") setTimeout(qualityHelp, 0);
  $("#issues").innerHTML = d.issues.length ? d.issues.map((it, i) =>
    `<div class="issue"><span class="t">${it.optional ? "·" : "!"} ${esc(it.text)}</span><button type="button" data-fix="${i}">[ ${{ install: "INSTALL", update: "UPDATE", start: "START", use: "USE IT", "install-voice": "SET UP", "install-pandoc": "INSTALL", "install-clone": "SET UP" }[it.action] || "DOWNLOAD"} ]</button></div>`).join("")
    : '<div class="dim">All good. Everything Joe needs is installed and running.</div>';
  return d;
}
// Banner on the main screen while Joe can't work yet (writing not set up), with one button.
function readyBanner(d) {
  const bar = $("#readybar"); if (!bar || !d) return;
  const need = d.issues.find((it) => !it.optional);
  const ups = d.issues.filter((it) => it.group === "updates").length;
  if (need) {
    $("#readybar-text").textContent = "Joe can't work yet: " + need.text;
    bar.querySelector("button").textContent = "[ FINISH SETTING UP ]"; bar.dataset.mode = "setup"; bar.hidden = false;
  } else if (ups) {
    $("#readybar-text").textContent = `${ups} update${ups > 1 ? "s" : ""} for Joe's helpers or models (optional).`;
    bar.querySelector("button").textContent = "[ SEE UPDATES ]"; bar.dataset.mode = "updates"; bar.hidden = false;
  } else bar.hidden = true;
}
function askFix(it) {
  const pkg = (doctorData && doctorData.pkg) || "";
  const viaPkg = pkg ? `Install it now with ${pkg}? Your system may ask for permission.` : "Open the official download page?";
  const what = { install: it.how || viaPkg, update: "Update it now? Your files and models are kept.", start: "Start it now?",
    use: "Switch to this model?", pull: "Download it now?", "download-image-model": "Download it now?",
    "download-video-model": "Download it now? About 18 GB in 3 files; it can take an hour or more.",
    "download-video-turbo": "Download it now? Under 1 GB. Restart ComfyUI afterwards.",
    "install-voice": "Set it up now? It downloads about 500 MB and takes a few minutes. Your system may ask for permission.",
    "install-pandoc": viaPkg,
    "install-clone": "Set it up now? About 3 GB (PyTorch for NVIDIA cards + the Chatterbox model). It can take a while." }[it.action];
  confirmBox(`${it.text}\n\n${what}`, async () => {
    const r = await api("/api/doctor/fix", { ...it, approved: true });
    if (!r.ok) { toast(r.error); return; }
    toast(r.started ? r.started + "…" : "Done");
    if (!r.started) loadDoctor();
  });
}
async function loadThemes() {
  const r = await api("/api/themes");
  const sel = $("#theme-select"), cur = sel.value;
  sel.querySelectorAll("option.custom").forEach((o) => o.remove());
  r.themes.forEach((t) => { const o = document.createElement("option"); o.value = "custom:" + t.id; o.textContent = t.name; o.className = "custom"; sel.appendChild(o); });
  if (cur) sel.value = cur;
  $("#swatches").innerHTML = r.themes.map((t) => `<div class="swatch${sel.value === "custom:" + t.id ? " on" : ""}">
      <i style="background:${t.bg}"></i><i style="background:${t.fg}"></i><i style="background:${t.accent}"></i>
      <span>${esc(t.name)}</span><button type="button" data-theme-use="${t.id}" data-crt="${t.crt}">[ USE ]</button>
      <button type="button" data-theme-del="${t.id}">[ DEL ]</button></div>`).join("") || '<span class="dim small">No custom themes yet.</span>';
  return r.themes;
}
async function loadSetup() {
  loadDoctor(); showPerms();
  try {
    const v = await api("/api/voice/status");
    voiceReady = v.voice; talkMode = v.settings.talk_mode === "push" ? "push" : "open"; pttKey = (v.settings.ptt_key === "F6" ? "F4" : v.settings.ptt_key) || "F4";   // Talk moved from F6 to F4
    $("#voice-select").innerHTML = Object.entries(v.voices).map(([id, n]) => `<option value="${id}">${esc(n)}</option>`).join("");
  } catch (e) {}
  setTimeout(loadMyVoice, 0);
  await loadThemes().catch(() => {});
  const s = await api("/api/settings");
  document.querySelectorAll("#setup [data-path]").forEach((el) => {
    const v = getPath(s, el.dataset.path);
    if (el.type === "checkbox") el.checked = !!v; else el.value = v ?? "";
  });
  qualityHelp();
  $("#setup-msg").textContent = "";
  $("#set-dirty").hidden = true;
}
async function saveSetup(ev) {
  if (ev) ev.preventDefault();
  const out = {};
  document.querySelectorAll("#setup [data-path]").forEach((el) => {
    let v = el.type === "checkbox" ? el.checked : el.value;
    if (el.type === "number" || el.dataset.path === "ui.crt") v = Number(v);
    setPath(out, el.dataset.path, v);
  });
  const r = await api("/api/settings", out);
  $("#setup-msg").textContent = r.ok ? "Saved." : "ERROR: " + r.error;
  if (r.ok) { toast("Settings saved"); voiceSettings(); $("#set-dirty").hidden = true; }
}
$("#setup").addEventListener("submit", saveSetup);

// --- setup side menu: one section at a time, a find box, and an "unsaved" note ---------------
let setupPageName = "system";
try { setupPageName = localStorage.getItem("joe-setup-page") || "system"; } catch (e) {}
function setupPage(name) {
  if (!document.querySelector(`.setpage[data-page="${name}"]`)) name = "system";
  setupPageName = name;
  try { localStorage.setItem("joe-setup-page", name); } catch (e) {}
  const find = $("#set-find");
  if (find.value) { find.value = ""; setupFind(); }
  document.querySelectorAll(".setpage").forEach((p) => p.classList.toggle("on", p.dataset.page === name));
  document.querySelectorAll(".setnav button[data-page]").forEach((b) => b.classList.toggle("on", b.dataset.page === name));
  $(".setpages").scrollTop = 0;
}
// Shows every section, hiding settings whose name and hint don't match. Opens "More options"
// when a match is inside it. Empty box = back to the section you were on.
function setupFind() {
  const q = $("#set-find").value.trim().toLowerCase();
  const nav = $(".setnav");
  const items = "fieldset > label, fieldset > .row, fieldset > .qrow, fieldset > .dim, details.more > label";
  document.querySelectorAll(".setup .hide").forEach((el) => el.classList.remove("hide"));
  nav.classList.toggle("finding", !!q);
  if (!q) {
    document.querySelectorAll(".setup details.more").forEach((d) => { if (d.dataset.found) { d.open = false; delete d.dataset.found; } });
    $(".setnone").hidden = true;
    document.querySelectorAll(".setpage").forEach((p) => p.classList.toggle("on", p.dataset.page === setupPageName));
    document.querySelectorAll(".setnav button[data-page]").forEach((b) => { b.classList.remove("hit"); b.classList.toggle("on", b.dataset.page === setupPageName); });
    return;
  }
  const words = (el) => (el.textContent + " " + (el.title || "") + " " + Array.from(el.querySelectorAll("[title],[placeholder],option")).map((x) => (x.title || "") + " " + (x.placeholder || "") + " " + x.textContent).join(" ")).toLowerCase();
  let any = false;
  document.querySelectorAll(".setpage").forEach((page) => {
    let pageHit = false;
    const pageNameHit = (page.dataset.title || "").toLowerCase().includes(q);
    page.querySelectorAll("fieldset").forEach((fs) => {
      const legendHit = pageNameHit || (fs.querySelector("legend") || {}).textContent.toLowerCase().includes(q);
      let fsHit = legendHit;
      fs.querySelectorAll(items).forEach((el) => {
        const hit = legendHit || words(el).includes(q);
        el.classList.toggle("hide", !hit);
        if (hit) { fsHit = true; const d = el.closest("details.more"); if (d && !legendHit && !d.open) { d.open = true; d.dataset.found = "1"; } }
      });
      fs.querySelectorAll("details.more").forEach((d) => d.classList.toggle("hide", !legendHit && !d.querySelector(":scope > label:not(.hide)")));
      fs.classList.toggle("hide", !fsHit);
      if (fsHit) pageHit = true;
    });
    page.classList.toggle("on", pageHit);
    const btn = document.querySelector(`.setnav button[data-page="${page.dataset.page}"]`);
    btn.classList.toggle("hit", pageHit); btn.classList.remove("on");
    if (pageHit) any = true;
  });
  $(".setnone").hidden = any;
}
document.querySelector(".setnav").addEventListener("click", (ev) => {
  const b = ev.target.closest("button[data-page]");
  if (b) setupPage(b.dataset.page);
});
$("#set-find").addEventListener("input", setupFind);
$("#set-find").addEventListener("keydown", (ev) => {
  if (ev.key === "Escape" && ev.target.value) { ev.stopPropagation(); ev.preventDefault(); ev.target.value = ""; setupFind(); }
  if (ev.key === "Enter") ev.preventDefault();   // don't submit the form
});
$("#setup").addEventListener("input", (ev) => { if (ev.target.dataset && ev.target.dataset.path) $("#set-dirty").hidden = false; });
$("#setup").addEventListener("change", (ev) => { if (ev.target.dataset && ev.target.dataset.path) $("#set-dirty").hidden = false; });
setupPage(setupPageName);

/* ---------------- buttons ---------------- */
document.addEventListener("click", async (ev) => {
  const b = ev.target.closest("button"); if (!b) return;
  if (b.dataset.key) { handleKey(b.dataset.key); return; }
  const act = b.dataset.act;
  try {
    if (act === "describe") await describeIt();
    if (act === "finish-setup") {
      if ($("#readybar").dataset.mode === "updates") show("setup", "system");
      else { await loadThemes().catch(() => {}); welcomeOpen(2); }
    }
    if (act === "plan-run") {
      if (state && state.running) {
        const r = await api("/api/queue/add", { text: $("#mission").value });
        toast(r.ok ? `Joe is busy, so it's in line (${r.queued} waiting)` : r.error);
      } else await runOrStop();
    }
    if (act === "check") await checkMission();
    if (act === "run") await runOrStop();
    if (act === "report") show("report");
    if (act === "talk-send") await talkSend();
    if (act === "talk-clear") {
      await freshStart();
      toast("New chat: a fresh start. The last one is saved on the left.");
      if (current === "talk") $("#talk-in").focus(); else if (current === "queue") $("#describe").focus();
    }
    if (act === "chats-toggle") { chatsShown(document.body.classList.contains("nochats")); return; }
    if (act === "chats-delall") {
      confirmBox("Delete ALL saved chats, including this one? They can't be brought back.", async () => {
        talkStop();
        const r = await api("/api/chats/delete", { all: true });
        talkLog = []; renderTalk(); toast(`Deleted ${r.deleted} chat(s)`); loadChats();
      });
      return;
    }
    if (act === "hush") hush();
    if (act === "talk-stop") { talkStop(); return; }
    if (act === "read-report") await say($("#report").textContent.replace(/[|#*`-]{2,}/g, " ").slice(0, 5000), true);
    if (act === "hear-story") await say(storyText(), true);
    if (act === "set-ptt") { settingKey = true; $("#ptt-key").value = "press a key…"; return; }
    if (act === "test-voice") { await saveSetup(); await say("Hi, I'm Joe. Humans can't say my real name, so Joe is fine.", true); }
    if (b.dataset.topen !== undefined) { dirPath = b.dataset.topen; pendingSelect = ""; show("files"); return; }
    if (b.dataset.tmission !== undefined) { await importToBuilder(talkLog[+b.dataset.tmission].mission); show("builder"); return; }
    if (b.dataset.trun !== undefined) {
      const m = talkLog[+b.dataset.trun].mission;
      confirmBox("Run this mission now? (Joe adds it to the queue if he's busy.)", async () => {
        const r = await api("/api/queue/add", { text: m });
        toast(r.ok ? (r.queued ? "Queued" : "Started") : r.error);
      });
      return;
    }
    if (act === "queue-add") {
      const r = await api("/api/queue/add", { text: $("#mission").value });
      if (!r.ok) { $("#plan").textContent = "ERROR: " + r.error; return; }
      toast(r.queued ? `Queued — ${r.queued} waiting` : "Started — safe to close this window");
    }
    if (act === "to-builder") { await importToBuilder($("#mission").value); show("builder"); }
    if (b.dataset.unqueue !== undefined) { await api("/api/queue/remove", { index: +b.dataset.unqueue }); return; }
    if (b.dataset.b) { await builderAction(b.dataset.b); return; }
    if (b.dataset.hload) { const r = await api("/api/load_mission", { path: b.dataset.hload }); if (r.ok) { await importToBuilder(r.text); toast("Loaded into the builder"); } return; }
    if (b.dataset.hrun) {
      const r0 = await api("/api/load_mission", { path: b.dataset.hrun });
      if (!r0.ok) { toast(r0.error); return; }
      confirmBox("Run this mission again? Unfinished tasks pick up where they stopped; finished ones are written again as _v2.", async () => {
        const r = await api("/api/queue/add", { text: r0.text });
        toast(r.ok ? (r.queued ? "Queued" : "Started") : r.error);
      });
      return;
    }
    if (act === "speedtest") {
      $("#setup-msg").textContent = "Testing… (about half a minute)";
      const r = await api("/api/speedtest", {});
      $("#setup-msg").textContent = r.ok ? r.text : "The test didn't work: " + r.error;
      return;
    }
    if (act === "test-ping") {
      $("#ping-msg").textContent = "Sending…";
      const topic = document.querySelector('[data-path="comfort.ntfy_topic"]').value.trim();
      const server = document.querySelector('[data-path="comfort.ntfy_server"]').value.trim();
      const r = await api("/api/notify/test", { topic, server });
      $("#ping-msg").textContent = r.ok ? "Sent. Check your phone. (Press SAVE to keep the topic.)" : "Didn't work: " + r.error;
      return;
    }
    if (act === "welcome") { await loadThemes().catch(() => {}); welcomeOpen(); return; }
    if (act === "about") { show("about"); return; }
    if (act === "help-file") {
      $("#setup-msg").textContent = "Making the help file…";
      try { const r = await api("/api/help-file", {}); $("#setup-msg").textContent = `Saved ${r.path} in Output (the folder opens). Look inside before you send it.`; }
      catch (e) { $("#setup-msg").textContent = e.message; }
      return;
    }
    if (act === "check-update") { $("#setup-msg").textContent = "Checking GitHub…"; await checkUpdate(true); return; }
    if (act === "clear") {
      $("#mission").value = ""; $("#plan").textContent = ""; $("#describe").value = ""; $("#describe-msg").textContent = "";
      hidePlan(); api("/api/mission/save", { text: "" });
    }
    if (b.dataset.fix !== undefined && doctorData) { askFix(doctorData.issues[+b.dataset.fix]); return; }
    if (b.dataset.themeUse) {
      $("#theme-select").value = "custom:" + b.dataset.themeUse;
      document.querySelector('[data-path="ui.crt"]').value = b.dataset.crt;
      await saveSetup(); loadThemes(); return;
    }
    if (b.dataset.themeDel) {
      confirmBox("Delete this theme file?", async () => { await api("/api/theme/delete", { id: b.dataset.themeDel }); loadSetup(); });
      return;
    }
    if (act === "doctor") { $("#doctor").textContent = "Checking…"; await loadDoctor(); }
    if (act === "perm-mic") { await allowMic(); return; }
    if (act === "web-test") {
      await saveSetup(); $("#web-msg").textContent = "Searching…";
      const r = await api("/api/web/test", {}).catch((e) => ({ ok: false, error: e.message }));
      $("#web-msg").textContent = r.ok ? r.text : "Didn't work: " + r.error;
      return;
    }
    if (act === "test-hello") { await saveSetup(); startupSound(); return; }
    if (act === "make-theme") {
      const desc = $("#theme-desc").value.trim();
      if (!desc) { $("#theme-msg").textContent = "Describe the look first."; return; }
      $("#theme-msg").textContent = "Designing…";
      const r = await api("/api/theme/make", { description: desc });
      if (!r.ok) { $("#theme-msg").textContent = "ERROR: " + r.error; return; }
      applyTheme(r.vars); document.body.className = `ph-custom crt-${r.theme.crt}`;   // custom themes are retro-style
      $("#theme-msg").textContent = `Previewing "${r.theme.name}". Press USE to keep it.`;
      await loadThemes();
      return;
    }
    if (act === "start-ollama" || act === "start-comfy") {
      $("#setup-msg").textContent = "Starting…";
      const r = await api("/api/services/start", { which: act === "start-ollama" ? "ollama" : "comfyui" });
      $("#setup-msg").textContent = r.ok ? "Running." : "Could not start it. Check the address / start command.";
    }
  } catch (e) { toast(e.message); }
});

/* ---------------- keyboard ---------------- */
function handleKey(key) {
  if (SCREENS[key]) { show(SCREENS[key]); return true; }
  if (key === "R") { show("report"); return true; }
  if (key === "F5") { runOrStop().catch((e) => toast(e.message)); return true; }
  if (key === "Escape") {
    if (current === "talk" && talkBusy()) { talkStop(); return true; }     // Esc = stop Joe talking
    if (document.activeElement && document.activeElement !== document.body) document.activeElement.blur();
    if (current !== "queue") show("queue");
    return true;
  }
  return false;
}
document.addEventListener("keydown", (ev) => {
  if (ev.key === "F4") { ev.preventDefault(); if (!ev.repeat && $("#welcome").hidden) f6Down(); return; }
  if (!$("#confirm").hidden) {
    ev.preventDefault();
    if (ev.key === "y" || ev.key === "Y" || ev.key === "Enter") confirmClose(true);
    else if (ev.key === "n" || ev.key === "N" || ev.key === "Escape") confirmClose(false);
    return;
  }
  if (!$("#welcome").hidden) {                 // the setup helper is up: only Esc (close) works
    if (/^F\d+$/.test(ev.key)) ev.preventDefault();
    if (ev.key === "Escape") { ev.preventDefault(); welcomeClose(); }
    return;
  }
  const typing = /^(TEXTAREA|INPUT|SELECT)$/.test(ev.target.tagName);
  if (/^F\d+$/.test(ev.key) || ev.key === "Escape") { ev.preventDefault(); handleKey(ev.key); return; }
  if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "s" && current === "setup") { ev.preventDefault(); saveSetup(); return; }
  if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
  if (typing) return;
  const k = ev.key;
  if (current === "queue" && (k === "r" || k === "R")) { show("report"); return; }
  if (current === "report" && (k === "c" || k === "C")) {
    navigator.clipboard.writeText($("#report").textContent).then(() => toast("Report copied — paste it to Claude"));
    return;
  }
  if (current !== "files") return;
  if (k === "ArrowDown") { sel = Math.min(sel + 1, entries.length - 1); renderDir(); previewSel(); ev.preventDefault(); }
  else if (k === "ArrowUp") { sel = Math.max(sel - 1, 0); renderDir(); previewSel(); ev.preventDefault(); }
  else if (k === "PageDown") { sel = Math.min(sel + 15, entries.length - 1); renderDir(); previewSel(); ev.preventDefault(); }
  else if (k === "PageUp") { sel = Math.max(sel - 15, 0); renderDir(); previewSel(); ev.preventDefault(); }
  else if (k === "Home") { sel = 0; renderDir(); previewSel(); }
  else if (k === "End") { sel = entries.length - 1; renderDir(); previewSel(); }
  else if (k === "Enter") enterSel();
  else if (k === "Backspace") { if (dirPath) loadDir(dirPath.split("/").slice(0, -1).join("/"), false); ev.preventDefault(); }
  else if (k === "o" || k === "O") openSel("folder").catch((e) => toast(e.message));
  else if (k === "l" || k === "L") loadMissionSel().catch((e) => toast("Load failed: " + e.message));
  else if (k === "e" || k === "E") openSel("editor").catch((e) => toast(e.message));
  else if (k === "t" || k === "T") { grid = !grid; try { localStorage.setItem("nr-grid", grid ? "1" : "0"); } catch (e) {} renderDir(); }
  else if (k === "k" || k === "K") reviewSel("keep").catch((e) => toast(e.message));
  else if (k === "x" || k === "X") reviewSel("reject").catch((e) => toast(e.message));
  else if (k === "s" || k === "S") reviewSel("star").catch((e) => toast(e.message));
  else if (k === "m" || k === "M") mp4Sel().catch((e) => toast(e.message));
  else if (k === "p" || k === "P") {
    const e2 = entries[sel]; if (!e2 || e2.dir || !/\.(md|txt)$/i.test(e2.name)) { toast("Pick a .md or .txt file"); return; }
    confirmBox(`Make Word and PDF copies of ${e2.name}?`, async () => {
      toast("Making documents…");
      const r = await api("/api/export", { path: selPath(), formats: ["docx", "pdf"] });
      toast(r.ok ? "Made " + r.made.join(", ") : r.error); loadDir(dirPath, true);
    });
  }
  else if (grid && k === "ArrowRight") { sel = Math.min(sel + 1, entries.length - 1); renderDir(); previewSel(); }
  else if (grid && k === "ArrowLeft") { sel = Math.max(sel - 1, 0); renderDir(); previewSel(); }
  else if (k === "c" || k === "C") {
    const p = selPath(); if (p == null) return;
    const abs = (state ? state.workspace : "") + "\\" + p.replace(/\//g, "\\");
    navigator.clipboard.writeText(abs).then(() => toast("Path copied"));
  }
});
// Block the browser's own reload/help on F5/F1 even when focus is in the textarea.
window.addEventListener("help", (e) => e.preventDefault());

/* ---------------- boot screen: 01000001 01001001 ---------------- */
function boot() {
  const el = $("#boot"), bin = "01000001 01001001";
  let shown = false;
  try { shown = sessionStorage.getItem("joe-booted") === "1"; sessionStorage.setItem("joe-booted", "1"); } catch (e) {}
  const done = () => { el.classList.add("gone"); setTimeout(() => el.remove(), 600); };
  const introOff = (document.querySelector('meta[name="joe-intro"]') || {}).content === "0";
  if (!shown) startupSound();                       // the sound has its own on/off; it plays even with no intro screen
  if (shown || introOff || matchMedia("(prefers-reduced-motion: reduce)").matches) { el.remove(); return; }
  el.addEventListener("click", done);
  document.addEventListener("keydown", done, { once: true });
  let i = 0;
  const t = setInterval(() => {
    $("#boot-bin").textContent = bin.slice(0, ++i) + (i < bin.length ? "█" : "");
    if (i >= bin.length) {
      clearInterval(t);
      setTimeout(() => $("#boot-name").classList.add("on"), 250);
      setTimeout(done, 2900);                       // long enough to read (click or any key skips it)
    }
  }, 55);
}
// When Joe opens: his 8-bit theme, then (with his voice set up) "Joe is now reporting
// for duty." Setup > Display & sound > "Intro sound" picks jingle, voice, both or off. Quiet hours = silent.
let bootCtx = null;
// Joe's 8-bit intro theme. Resolves with its length (seconds) once it starts, so his spoken
// hello can wait until the tune is done.
function playTheme() {
  return new Promise((ok, fail) => {
    const a = new Audio("/sounds/intro.wav");
    a.volume = 0.8;
    a.addEventListener("error", () => fail(new Error("no theme")), { once: true });
    a.play().then(() => ok(isFinite(a.duration) && a.duration > 0 ? a.duration : 3.2)).catch(fail);
  });
}
function jingle(retro) {
  try {
    const actx = bootCtx = bootCtx || new AudioContext();
    const notes = [392, 523.25, 659.25, 783.99, 1046.5];             // G C E G C, a little "power on"
    notes.forEach((f, i) => {
      const o = actx.createOscillator(), g = actx.createGain();
      const t = actx.currentTime + 0.05 + i * 0.11, last = i === notes.length - 1, len = last ? 0.9 : 0.22;
      o.type = retro ? "square" : "triangle"; o.frequency.value = f;
      const vol = (retro ? 0.045 : 0.11) * (last ? 1.1 : 1);
      g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(vol, t + 0.015); g.gain.exponentialRampToValueAtTime(0.001, t + len);
      o.connect(g).connect(actx.destination); o.start(t); o.stop(t + len + 0.05);
    });
  } catch (e) {}
  return 0.05 + 4 * 0.11 + 0.5;                    // seconds until the jingle has mostly rung out
}
async function startupSound() {
  let s;
  try { s = await api("/api/settings"); } catch (e) { return; }
  const mode = (s.ui && s.ui.startup_sound) || "both";
  if (mode === "off") return;
  let quiet = false;
  try { quiet = (await api("/api/state")).quiet; } catch (e) {}
  if (quiet) return;
  const retro = ["green", "amber", "white"].includes(s.ui.phosphor);
  let wait = 0;
  if (mode === "jingle" || mode === "both") {
    if (s.ui.jingle === "chime") wait = jingle(retro) * 1000;
    else wait = await playTheme().catch(() => jingle(retro)) * 1000;   // the tones if the file won't play
  }
  if (mode !== "voice" && mode !== "both") return;
  const hello = fetch("/api/voice/hello", { method: "POST", headers: { "X-NR-Token": TOKEN, "Content-Type": "application/json" }, body: "{}" })
    .then((r) => (r.headers.get("content-type") || "").startsWith("audio/") ? r.blob() : null).catch(() => null);
  const [blob] = await Promise.all([hello, new Promise((r) => setTimeout(r, wait))]);
  if (!blob) return;                               // voice not set up yet: the jingle is enough
  const a = new Audio(URL.createObjectURL(blob));
  a.play().catch(() => {});
}
boot();

/* ---------------- start ---------------- */
function tick() {
  const d = new Date();
  $("#clock").textContent = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
(async () => {
  tick(); setInterval(tick, 10000);
  await new Promise((r) => setTimeout(r, 0));   // let the rest of this file load first
  await freshStart();                          // every time Joe opens: a new chat, a clean screen
  await poll();
  setInterval(poll, 1000);
  // First thing on launch: make sure the tools are there. Ask before fixing anything.
  // The very first time, the welcome helper walks through it step by step instead.
  try {
    if (state && !state.ui.welcomed && !state.running) { await loadThemes().catch(() => {}); welcomeOpen(); }
    else {
      const d = await loadDoctor();
      const need = d && d.issues.find((it) => !it.optional);
      if (need && !(state && state.running)) askFix(need);
    }
  } catch (e) {}
  await voiceSettings();
  // Fresh start, unless the last run didn't finish.
  try {
    const o = await api("/api/resume");
    if (o.offer) {
      confirmBox(`The last run didn't finish: ${o.tasks} task(s) left` +
        (o.names.length ? `\n  ${o.names.join("\n  ")}` : "") +
        `\n\nY = resume where it stopped    N = start fresh (it stays in F6 > History)`,
        async () => { const r = await api("/api/resume", { action: "resume" }); toast(r.ok ? "Resuming" : r.error); },
        async () => { await api("/api/resume", { action: "fresh" }); });
    }
  } catch (e) {}
})();

/* ---------------- builder (F6): missions without typing keys ---------------- */
const KINDS = { list: "A list of things (posts, descriptions, emails…)", doc: "A document, section by section",
  sheet: "A spreadsheet (a table)", image: "Pictures", video: "Short video clips" };
const KIND_SHORT = { list: "list", doc: "document", sheet: "spreadsheet", image: "pictures", video: "video" };
const SIZES = [["", "Joe picks"], ["1024x1024", "Square"], ["1216x832", "Wide (landscape)"],
  ["832x1216", "Tall (portrait)"], ["1344x768", "Extra wide"], ["512x512", "Small square (older models)"]];
// "How many?" -> small batches, so the model stays sharp. Exact when it can be.
function batches(n, media) {
  n = Math.max(1, Math.min(Math.round(n) || 1, media ? 400 : 5000));
  if (n <= (media ? 6 : 10)) return [1, n];
  for (const s of media ? [4, 3, 5, 6, 2] : [8, 10, 6, 5, 7, 9, 4]) if (n % s === 0 && n / s <= 500) return [n / s, s];
  const s = media ? 4 : 8; return [Math.ceil(n / s), s];       // rounds up a little
}
let bMore = false;
const B = { project: "", rules: "", tasks: [], sel: 0, lists: { projects: [], workflows: [], inbox: [], image_models: [] } };
const newTask = (n) => ({ name: `Task ${n}`, save: "", type: "text", project: "", parts: 4, part_size: 5, part_prompts: [],
  format: "", rules: "", min_words: 0, header: "", inputs: [], export: [], model: "", notes: "", workflow: "", negative: "",
  width: 0, height: 0, variants: 1, seed: "random", fps: 16, prompts_as_written: false, _kind: "list" });
function kindOf(t) {
  if (t._kind) return t._kind;
  if (t.type === "image" || t.type === "video") return t.type;
  if (t.header || /\.csv$/i.test(t.save || "")) return "sheet";
  return (t.part_prompts || []).length ? "doc" : "list";
}
let builderLoaded = false;
async function loadBuilder() {
  try { B.lists = await api("/api/lists"); } catch (e) {}
  $("#dl-projects").innerHTML = B.lists.projects.map((p) => `<option value="${esc(p)}">`).join("");
  $("#dl-models").innerHTML = B.lists.image_models.map((p) => `<option value="${esc(p)}">`).join("");
  if (!builderLoaded) { builderLoaded = true; if (!B.tasks.length) B.tasks.push(newTask(1)); }
  $("#b-project").value = B.project; $("#b-rules").value = B.rules;
  renderTasks(); renderForm(); scheduleBuild(); loadHistory();
}
async function importToBuilder(text) {
  if (!text.trim()) { toast("Nothing to import"); return false; }
  const r = await api("/api/mission/parse", { text });
  if (!r.ok) { toast("Can't read it: " + r.error); return false; }
  B.project = r.project; B.rules = r.rules;
  B.tasks = r.tasks.map((t) => ({ ...newTask(1), ...t, _kind: undefined }));
  B.tasks.forEach((t) => (t._kind = kindOf(t)));
  B.sel = 0; builderLoaded = true;
  if (current === "builder") loadBuilder();
  return true;
}
function taskSize(t) {
  const k = t._kind, n = (t.part_prompts || []).filter((x) => x.trim()).length;
  if (k === "doc") return `${n} section${n === 1 ? "" : "s"}`;
  if (k === "image" || k === "video") {
    const p = n || t.parts * t.part_size, all = p * (t.variants || 1);
    return `${all} ${k === "image" ? "picture" : "clip"}${all === 1 ? "" : "s"}`;
  }
  const c = t.parts * t.part_size;
  return `${c} ${k === "sheet" ? "row" : "item"}${c === 1 ? "" : "s"}`;
}
function renderTasks() {
  $("#b-tasks").innerHTML = B.tasks.map((t, i) => `<div class="btask${i === B.sel ? " sel" : ""}" data-i="${i}" title="Click to change this one">` +
    `<span class="n">${i + 1}.</span><span class="t">${esc(t.name)} <span class="kind">(${KIND_SHORT[t._kind]})</span></span><span>${taskSize(t)}</span></div>`).join("")
    || '<div class="dim">Nothing yet. Press + ADD SOMETHING.</div>';
}
function field(label, html, hint, tip) {
  return `<label${tip ? ` title="${esc(tip)}"` : ""}>${label} ${html}</label>${hint ? `<div class="hint">${hint}</div>` : ""}`;
}
function renderForm() {
  const t = B.tasks[B.sel], f = $("#b-form");
  if (!t) { f.innerHTML = '<div class="dim">Press + ADD SOMETHING to start.</div>'; return; }
  const k = t._kind, media = k === "image" || k === "video";
  const v = (x) => esc(x ?? "");
  const lines = (t.part_prompts || []).join("\n");
  const briefs = (t.part_prompts || []).filter((x) => x.trim()).length;
  let h = field("What is it?", `<select data-f="_kind">${Object.entries(KINDS).map(([a, b]) => `<option value="${a}"${a === k ? " selected" : ""}>${b}</option>`).join("")}</select>`);
  h += field("Call it", `<input data-f="name" value="${v(t.name)}" placeholder="e.g. Mug descriptions">`, "", "A short name. It becomes the file name too.");
  if (k === "doc") {
    h += field("Sections, in order", `<textarea data-f="part_prompts" rows="5" placeholder="Welcome. Who we are and what we make.\nHow to order. Steps, shipping, returns.\nCare. How to wash and store each piece.">${v(lines)}</textarea>`,
      "One section per line: its title, then what goes in it. Joe writes them in this order.");
  } else if (!(media && briefs)) {
    const count = t.parts * t.part_size;
    const q = { list: "How many?", sheet: "How many rows?", image: "How many pictures?", video: "How many clips?" }[k];
    const unit = { list: "items", sheet: "rows", image: "different pictures", video: "clips" }[k];
    h += field(q, `<input type="number" min="1" max="${media ? 400 : 5000}" data-f="_count" value="${count}">`,
      media ? `Joe writes a description for each one, then draws it.` : `Joe writes them ${t.part_size} at a time so the AI stays sharp.`
      + (t._asked && t._asked !== count ? ` (He'll make ${count} ${unit} so the batches come out even.)` : ""));
  }
  if (k === "image") h += field("Versions of each picture", `<input type="number" min="1" max="16" data-f="variants" value="${t.variants}">`,
    `${(briefs || t.parts * t.part_size) * t.variants} pictures in all. More versions = more to choose from.`);
  if (k === "sheet") h += field("Columns", `<input data-f="header" value="${v(t.header)}" placeholder="Name, Description, Price">`, "The column names, separated by commas. Joe checks every row has them all.");
  const fmtLabel = { list: "What each one looks like", doc: "How to write it", sheet: "What goes in each row", image: "What the pictures show", video: "What happens in the clips" }[k];
  const fmtPh = { list: "A catchy title, then one short paragraph about look, feel and use. End with a care tip.",
    doc: "Friendly and plain. Short paragraphs. Use a table where it helps.",
    sheet: "One row per product. Leave Price empty if you don't know it.",
    image: "Handmade mugs on a wooden table, soft morning light, muted earth tones, no people.",
    video: "Slow pan across a pottery shelf, warm light, steam rising from a mug." }[k];
  h += field(fmtLabel, `<textarea data-f="format" rows="3" placeholder="${fmtPh}">${v(t.format)}</textarea>`, "", "Say it the way you'd tell a person. Tone, length, style, what to include or avoid.");
  if (media) {
    h += field("Or describe each one yourself", `<textarea data-f="part_prompts" rows="3" placeholder="optional, one ${k === "image" ? "picture" : "clip"} per line">${v(lines)}</textarea>`,
      briefs ? `Joe makes these ${briefs} instead of a count.` : "Leave it empty and Joe comes up with them from the box above.");
    if (briefs) h += field("Use my words exactly", `<input type="checkbox" data-f="prompts_as_written"${t.prompts_as_written ? " checked" : ""}>`, "Off = Joe adds detail to each one first (usually better).");
  }
  if (k === "list" || k === "doc") {
    h += field("At least … words each", `<input type="number" min="0" max="2000" data-f="min_words" value="${t.min_words}">`, "0 = any length. Joe expands anything too short.");
    h += field("Also make", `<span class="checks">${["docx", "pdf", "epub"].map((x) => `<label class="inline"><input type="checkbox" data-ex="${x}"${(t.export || []).includes(x) ? " checked" : ""}> ${{ docx: "Word", pdf: "PDF", epub: "e-book" }[x]}</label>`).join("")}</span>`, "Finished copies of the writing, ready to print or send.");
  }
  if (B.lists.inbox.length) h += field("Use these files as facts", `<span class="checks">${B.lists.inbox.map((n) => `<label class="inline"><input type="checkbox" data-in="${esc(n)}"${(t.inputs || []).includes(n) ? " checked" : ""}> ${esc(n)}</label>`).join("")}</span>`, "From your Inbox folder (price lists, notes, old descriptions…).");
  if (k === "image") {
    const sz = t.width && t.height ? `${t.width}x${t.height}` : "";
    h += field("Shape", `<select data-f="_size">${SIZES.map(([a, b]) => `<option value="${a}"${a === sz ? " selected" : ""}>${b}</option>`).join("")}${sz && !SIZES.some(([a]) => a === sz) ? `<option value="${sz}" selected>${sz}</option>` : ""}</select>`);
    h += field("Leave out", `<input data-f="negative" value="${v(t.negative)}" placeholder="e.g. text, watermark, blurry">`);
  }
  // Everything below is optional; most people never open it.
  let m = field("Rules just for this one", `<textarea data-f="rules" rows="2" placeholder="optional">${v(t.rules)}</textarea>`);
  m += field("Save as", `<input data-f="save" value="${v(t.save)}" placeholder="blank = Joe picks (recommended)">`,
    "A file or folder name inside Output. Joe never overwrites: a second run saves a _v2.");
  m += field("Profile", `<input data-f="project" list="dl-projects" value="${v(t.project)}" placeholder="same as everything else">`, "A business or project profile from the Projects folder.");
  if (k !== "doc" && !(media && briefs)) m += field("Batches", `<span class="inline"><input type="number" min="1" max="500" data-f="parts" value="${t.parts}"> batches of <input type="number" min="1" max="50" data-f="part_size" value="${t.part_size}"></span>`, "How Joe splits the work. Smaller batches keep the AI sharp.");
  if (media) {
    m += field("Picture model", `<input data-f="model" list="dl-models" value="${v(t.model)}" placeholder="best fit for your graphics card">`);
    m += field("ComfyUI workflow", `<select data-f="workflow"><option value="">${k === "video" ? "built-in video (Wan 2.2)" : "built-in"}</option>${B.lists.workflows.map((w) => `<option${w === t.workflow ? " selected" : ""}>${esc(w)}</option>`).join("")}</select>`,
      "Your own ComfyUI files from the Workflows folder (ComfyUI: Workflow > Export (API)).");
    m += field("Seed", `<input data-f="seed" value="${v(t.seed)}">`, "random, or a number to repeat a run exactly.");
    if (k === "video") m += field("Frames per second", `<input type="number" min="1" max="60" data-f="fps" value="${t.fps}">`);
    if (k === "video") m += field("Versions of each clip", `<input type="number" min="1" max="16" data-f="variants" value="${t.variants}">`);
  } else {
    m += field("Writing model", `<input data-f="model" value="${v(t.model)}" placeholder="the Setup default">`);
  }
  h += `<details class="more"${bMore ? " open" : ""}><summary title="File names, batches, models and other fine-tuning">MORE OPTIONS</summary>${m}</details>`;
  f.innerHTML = h;
  f.querySelector("details.more").addEventListener("toggle", (ev) => (bMore = ev.target.open));
}
function readField(t, el) {
  const key = el.dataset.f;
  if (el.dataset.ex !== undefined) {
    const x = el.dataset.ex; t.export = (t.export || []).filter((y) => y !== x); if (el.checked) t.export.push(x); return;
  }
  if (el.dataset.in !== undefined) {
    const n = el.dataset.in; t.inputs = (t.inputs || []).filter((x) => x !== n); if (el.checked) t.inputs.push(n); return;
  }
  let val = el.type === "checkbox" ? el.checked : el.value;
  if (el.type === "number") val = Number(val) || 0;
  if (key === "_count") {
    if (!val) return;
    const media = t._kind === "image" || t._kind === "video";
    [t.parts, t.part_size] = batches(val, media);
    t._asked = val;
    return;
  }
  if (key === "part_prompts") {
    const before = (t.part_prompts || []).length > 0;
    t.part_prompts = val.split("\n").map((x) => x.trim()).filter(Boolean);
    if (before !== t.part_prompts.length > 0 && (t._kind === "image" || t._kind === "video")) t._rerender = true;
    return;
  }
  if (key === "_size") { const [w, h2] = (val || "0x0").split("x").map(Number); t.width = w || 0; t.height = h2 || 0; return; }
  t[key] = val;
  if (key === "parts" || key === "part_size") t._asked = 0;
  if (key === "_kind") {
    t.type = val === "image" || val === "video" ? val : "text";
    if (val === "sheet" && t.save && !/\.csv$/i.test(t.save)) t.save = t.save.replace(/\.\w+$/, "") + ".csv";
    if (val !== "sheet") t.header = "";
    if (val !== "doc" && val !== "image" && val !== "video") t.part_prompts = [];
    if (val === "image" || val === "video") [t.parts, t.part_size] = val === "video" ? [1, 2] : [1, 4];
    else if (t.part_size < 4) [t.parts, t.part_size] = [2, 5];
    t._rerender = true;
  }
}
$("#b-form").addEventListener("input", (ev) => {
  const t = B.tasks[B.sel]; if (!t) return;
  readField(t, ev.target); renderTasks(); scheduleBuild();
  if (t._rerender && ev.target.tagName === "SELECT") { t._rerender = false; renderForm(); }
});
// Hints that depend on a number (or on briefs being there) refresh when you leave the box.
$("#b-form").addEventListener("change", (ev) => {
  const t = B.tasks[B.sel]; if (!t) return;
  if (ev.target.tagName === "SELECT" || ev.target.type === "checkbox") { readField(t, ev.target); renderTasks(); scheduleBuild(); }
  if (t._rerender || ["_count", "variants", "parts", "part_size"].includes(ev.target.dataset.f)) { t._rerender = false; renderForm(); }
});
$("#b-form").addEventListener("submit", (ev) => ev.preventDefault());
["#b-project", "#b-rules"].forEach((id) => $(id).addEventListener("input", () => { B.project = $("#b-project").value; B.rules = $("#b-rules").value; scheduleBuild(); }));
$("#b-tasks").addEventListener("mousedown", (ev) => {
  const row = ev.target.closest(".btask"); if (!row) return;
  B.sel = +row.dataset.i; renderTasks(); renderForm();
});
let buildTimer, built = { ok: false, text: "" };
function scheduleBuild() { clearTimeout(buildTimer); buildTimer = setTimeout(build, 300); }
async function build() {
  const tasks = B.tasks.map(({ _kind, ...t }) => t);
  if (!tasks.length) { $("#b-out").textContent = ""; $("#b-status").textContent = ""; $("#b-sum").innerHTML = ""; built = { ok: false, text: "" }; return built; }
  const r = await api("/api/mission/build", { project: B.project, rules: B.rules, tasks });
  built = r;
  $("#b-out").textContent = r.text;
  $("#b-status").textContent = r.ok ? "— " + r.time : "";
  $("#b-sum").innerHTML = r.ok ? r.summary.map((x) => `<li>${esc(x)}</li>`).join("") +
      (r.check.warnings || []).map((w) => `<li class="warn">! ${esc(w)}</li>`).join("")
    : `<li class="warn">! ${esc(r.error)}</li>`;
  return r;
}
function splitTask(t) {
  const a = { ...t, part_prompts: [...(t.part_prompts || [])] }, b = { ...t, part_prompts: [...(t.part_prompts || [])] };
  if (a.part_prompts.length > 1) {
    const h = Math.ceil(a.part_prompts.length / 2);
    a.part_prompts = t.part_prompts.slice(0, h); b.part_prompts = t.part_prompts.slice(h);
  } else if (t.parts > 1) {
    a.parts = Math.ceil(t.parts / 2); b.parts = t.parts - a.parts;
  } else return null;
  b.name = t.name + " (2)";
  b.save = (t.save || "").replace(/(\.\w+)?$/, (m) => "_2" + m);
  return [a, b];
}
async function builderAction(a) {
  const T = B.tasks, i = B.sel;
  if (a === "add") { T.splice(i + 1, 0, newTask(T.length + 1)); B.sel = Math.min(i + 1, T.length - 1); }
  if (a === "dup" && T[i]) { T.splice(i + 1, 0, { ...T[i], part_prompts: [...T[i].part_prompts], inputs: [...(T[i].inputs || [])], name: T[i].name + " copy" }); B.sel = i + 1; }
  if (a === "up" && i > 0) { [T[i - 1], T[i]] = [T[i], T[i - 1]]; B.sel = i - 1; }
  if (a === "down" && i < T.length - 1) { [T[i + 1], T[i]] = [T[i], T[i + 1]]; B.sel = i + 1; }
  if (a === "split" && T[i]) { const s = splitTask(T[i]); if (!s) { toast("Needs 2+ parts or sections to split"); return; } T.splice(i, 1, ...s); }
  if (a === "del" && T[i]) { T.splice(i, 1); B.sel = Math.max(0, Math.min(i, T.length - 1)); }
  if (a === "clear") { confirmBox("Start over with an empty mission?", () => { B.project = B.rules = ""; B.tasks = [newTask(1)]; B.sel = 0; loadBuilder(); }); return; }
  if (a === "import") { if (await importToBuilder($("#b-paste").value)) { $("#b-paste").value = ""; toast("Imported — reorder or split as you like"); } return; }
  if (a === "import-box") { if (await importToBuilder($("#mission").value)) toast("Imported from F2"); return; }
  if (["run", "queue", "send", "save"].includes(a)) {
    const r = await build();
    if (!r.ok) { toast(r.error || "Fix the mission first"); return; }
    if (a === "send") { $("#mission").value = r.text; api("/api/mission/save", { text: r.text }); show("queue"); checkMission(); return; }
    if (a === "save") {
      const s = await api("/api/mission/save_as", { name: $("#b-name").value, text: r.text });
      toast(s.ok ? "Saved to " + s.path : s.error); loadHistory(); return;
    }
    if (a === "run" && state && state.running) { toast("Joe is busy — use ADD TO QUEUE"); return; }
    const q = await api("/api/queue/add", { text: r.text });
    if (!q.ok) { toast(q.error); return; }
    toast(q.queued ? `Queued — ${q.queued} waiting` : "Started — safe to close this window");
    $("#mission").value = r.text;
    if (a === "run") show("queue");
    return;
  }
  renderTasks(); renderForm(); scheduleBuild();
}
async function loadHistory() {
  let r; try { r = await api("/api/history"); } catch (e) { return; }
  $("#b-history").innerHTML = r.missions.length ? r.missions.map((m) =>
    `<div class="h"><span class="dim">${esc(m.when)}</span><span class="t">${esc(m.label)}</span><span class="dim">${m.done}/${m.tasks} done</span><button data-hload="${esc(m.file)}" title="Open it here so you can change it.">[ LOAD ]</button><button data-hrun="${esc(m.file)}" title="Run it again.">[ RUN ]</button></div>`).join("")
    : '<div class="dim small">Missions you run show up here.</div>';
}
document.addEventListener("keydown", (ev) => {
  if (current !== "builder" || !$("#confirm").hidden) return;
  if (/^(TEXTAREA|INPUT|SELECT)$/.test(ev.target.tagName)) return;
  if (ev.key === "ArrowDown" && B.sel < B.tasks.length - 1) { B.sel++; renderTasks(); renderForm(); ev.preventDefault(); }
  if (ev.key === "ArrowUp" && B.sel > 0) { B.sel--; renderTasks(); renderForm(); ev.preventDefault(); }
});

/* ---------------- talk + voice (F4) ---------------- */
let speakReplies = true;
let voiceReady = false, talkLog = [], audioEl = null, rec = null, recStart = 0, f6Timer = null;
async function loadTalk() {
  api("/api/talk/warm", {}).catch(() => {});      // load the thinking + voice models now, not on the first question
  loadChats();
  await voiceSettings();
  pttLabel();
  $("#talk-note").textContent = voiceReady ? (talkMode === "push" ? `Voice is on. Hold ${keyName(pttKey)} anywhere and speak; let go to send.`
    : "Voice is on and the mic is open while this screen is up. Just talk; Joe answers when you pause.")
    : "Typing works now. For voice, set it up once in F10 > System check (\"Joe's voice\").";
  renderTalk();
  if (!(talkMode === "push" && /^(Key|Digit|Space)/.test(pttKey))) setTimeout(() => $("#talk-in").focus(), 50);
  openMicStart();
}
async function voiceSettings() {
  try {
    const v = await api("/api/voice/status");
    voiceReady = v.voice; speakReplies = v.settings.speak_replies;
    talkMode = v.settings.talk_mode === "push" ? "push" : "open"; pttKey = (v.settings.ptt_key === "F6" ? "F4" : v.settings.ptt_key) || "F4";   // Talk moved from F6 to F4
  } catch (e) {}
}
async function freshStart() {
  talkStop();
  let r = {};
  try { r = await api("/api/session/new", {}); } catch (e) {}
  talkLog = []; renderTalk();
  $("#mission").value = ""; $("#plan").textContent = ""; $("#describe").value = ""; $("#describe-msg").textContent = "";
  hidePlan();
  if (!r.running) { $("#log").innerHTML = ""; lastLogLen = 0; lastMedia = ""; viewing = ""; $("#gallery").innerHTML = EMPTY_GALLERY; }
  try { if (toolOpen) { toolOpen = null; toolFiles = []; if (toolCat) renderToolGrid(); } } catch (e) {}   // not loaded yet at start
  loadChats();
  return r;
}
function talkExtra(m, i) {            // plans, runs and results saved in the chat
  if (m.kind === "plan" || m.kind === "run") {
    const list = (m.summary || []).length ? `<ul class="tsum">${m.summary.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : "";
    return list + `<details class="tmore"><summary>Mission</summary><pre class="mission">${esc(m.mission)}</pre></details>` +
      `<button data-tmission="${i}">[ OPEN IN BUILDER ]</button> <button data-trun="${i}">[ ${m.kind === "run" ? "RUN AGAIN" : "RUN IT"} ]</button>`;
  }
  if (m.kind === "result") {
    const rows = (m.tasks || []).map((t) => `<div class="trow ${esc(t.status)}"><span>${t.status === "done" ? "√" : "!"} ${esc(t.name)}</span>` +
      `<span class="dim">${esc(t.status)} ${t.done}/${t.total}${t.flags ? " · " + t.flags + " to check" : ""}${t.note ? " · " + esc(t.note) : ""}</span>` +
      (t.output ? `<button data-topen="${esc(t.output)}" title="${esc(t.output)}">[ OPEN ]</button>` : "") + `</div>`).join("");
    const media = (m.media || []).map((p) => isVid(p)
      ? `<video class="tth" src="${rawSrc(p)}#t=0.5" muted preload="metadata" data-open="${esc(p)}" title="${esc(p)}"></video>`
      : `<img class="tth" src="${rawSrc(p)}" alt="" loading="lazy" data-open="${esc(p)}" title="${esc(p)}">`).join("");
    return `<div class="tresult">${rows}</div>` + (media ? `<div class="tmedia">${media}</div>` : "") +
      (m.report ? `<details class="tmore"><summary>Report</summary><pre class="mission">${esc(m.report)}</pre></details>` : "") +
      ((m.log || []).length ? `<details class="tmore"><summary>Log (${m.log.length} lines)</summary><pre class="mission">${esc(m.log.join("\n"))}</pre></details>` : "");
  }
  return m.mission ? `<pre class="mission">${esc(m.mission)}</pre><button data-tmission="${i}">[ OPEN IN BUILDER ]</button> <button data-trun="${i}">[ RUN IT ]</button>` : "";
}
function renderTalk() {
  $("#talk-log").innerHTML = talkLog.length ? talkLog.map((m, i) => `<div class="msg ${m.who}${m.kind ? " k-" + m.kind : ""}"><span class="who">${m.who === "joe" ? "JOE>" : "YOU>"}</span>${esc(m.text)}` +
    talkExtra(m, i) +
    (m.sources && m.sources.length ? `<div class="sources">Sources: ${m.sources.map((s, k) =>
      `<a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer" title="${esc(s.url)}">[${k + 1}] ${esc(s.title)}</a>`).join(" ")}</div>` : "") + `</div>`).join("")
    : '<div class="dim">Joe: "What can I help you with?"</div>';
  const lg = $("#talk-log"); lg.scrollTop = lg.scrollHeight;
}
// Joe's reply streams in a few words at a time; each finished sentence goes straight to his
// voice, so he starts talking while he's still thinking up the rest.
const cleanSpeech = (t) => t.replace(/```[\s\S]*?```/g, " ").replace(/[*_#`>|]+/g, "").replace(/^\s*[-•]\s+/gm, "").replace(/\s+/g, " ").trim();
// STOP: cuts off Joe's reply mid-sentence (the model stops writing too) and his voice.
let talkAbort = null, talkMsg = null;
function talkBusy() { return !!talkAbort || speaking || (audioEl && !audioEl.paused); }
function talkStop() {
  const was = talkBusy();
  if (talkAbort) { talkAbort.abort(); talkAbort = null; }
  hush(); speechList = []; speechOpen = false;
  if (talkMsg && was && !/\(stopped\)$/.test(talkMsg.text)) { talkMsg.text = (talkMsg.text === "…" ? "" : talkMsg.text + " ") + "(stopped)"; renderTalk(); }
  talkStopBtn();
  return was;
}
function talkStopBtn() { const b = $("#talk-stop"); if (b) b.hidden = !talkBusy(); }
setInterval(talkStopBtn, 400);
async function talkSend(textArg) {
  const text = (textArg ?? $("#talk-in").value).trim();
  if (talkAbort) talkStop();                     // a new question cuts off the old answer
  const sent = (typeof talkFiles !== "undefined") ? talkFiles.filter((f) => !f.busy) : [];
  if (!text && !sent.length) return;
  if (text && !sent.length && text.length <= 40) {        // "go", "stop", "report"...: do it, no AI
    const rt = await routeText(text);
    if (rt.kind === "command" && !["talk", "new"].includes(rt.cmd)) {
      $("#talk-in").value = "";
      const said = await doCommand(rt.cmd);
      talkLog.push({ who: "you", text }, { who: "joe", text: said });
      if (current === "talk") renderTalk();
      return;
    }
  }
  $("#talk-in").value = "";
  if (sent.length) { talkFiles = talkFiles.filter((f) => f.busy); renderFiles(); }
  talkLog.push({ who: "you", text: (text || "(file)") + sent.map((f) => `  📎 ${f.name}`).join("") });
  const msg = { who: "joe", text: "…" };
  talkLog.push(msg); talkMsg = msg;
  renderTalk();
  const ctrl = new AbortController(); talkAbort = ctrl; talkStopBtn();
  const voice = voiceReady && speakReplies;
  if (voice) speechStart();
  let raw = "", spokenUpTo = 0, final = null, lastPaint = 0;
  const speakable = () => { const i = raw.search(/===\s*JOE\s+MISSION/i); return i < 0 ? raw : raw.slice(0, i); };
  const feed = (end) => {                       // queue every finished sentence for speaking
    if (!voice) return;
    const sp = speakable();
    const rest = sp.slice(spokenUpTo);
    const m = end ? rest.length : (() => { let cut = -1; const re = /[.!?](\s|$)/g; let x;
      while ((x = re.exec(rest))) { if (x.index + 1 >= 25 || cut >= 0) cut = x.index + 1; }
      return cut; })();
    if (m > 0) { const piece = cleanSpeech(rest.slice(0, m)); spokenUpTo += m; if (piece) speechQueue(piece); }
  };
  try {
    const res = await fetch("/api/talk/stream", { method: "POST", signal: ctrl.signal, headers: { "X-NR-Token": TOKEN, "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
    const reader = res.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let nl;
      while ((nl = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, nl); buf = buf.slice(nl + 1);
        if (!line.trim()) continue;
        const ev = JSON.parse(line);
        if (ev.t === "delta") {
          raw += ev.text; feed(false);
          if (performance.now() - lastPaint > 120) { msg.text = cleanSpeech(speakable()) || "…"; renderTalk(); lastPaint = performance.now(); }
        } else if (ev.t === "status") { msg.text = ev.text; renderTalk(); }
        else if (ev.t === "done") final = ev;
      }
    }
  } catch (e) {
    if (ctrl.signal.aborted) { if (talkAbort === ctrl) talkAbort = null; talkStopBtn(); loadChats(); return; }   // STOP pressed
    final = { ok: false, error: e.message };
  }
  if (talkAbort === ctrl) talkAbort = null;
  talkStopBtn();
  if (!final) final = { ok: false, error: "Joe stopped talking unexpectedly" };
  if (final.ok) {
    if (!raw) raw = final.say;                  // read-aloud / status replies come in one piece
    feed(true);
    msg.text = final.say; msg.mission = final.mission; msg.sources = final.sources || [];
  } else msg.text = "(" + final.error + ")";
  renderTalk();
  loadChats();                                   // a new chat appears in the list after its first reply
  if (voice) speechEnd();
}
$("#talk-in").addEventListener("keydown", (ev) => {
  if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); talkSend(); }
});
// Joe speaks a sentence or two at a time: the first piece plays while the next is being made,
// so he starts talking in about a second instead of after the whole reply is ready.
let speaking = false, sayGen = 0, playRate = 1;
try { playRate = Math.min(1.8, Math.max(0.7, parseFloat(localStorage.getItem("joe-voice-rate")) || 1)); } catch (e) {}
function showRate() { $("#talk-speed").value = playRate; $("#talk-speed-v").textContent = playRate.toFixed(2) + "×"; }
showRate();
$("#talk-speed").addEventListener("input", (ev) => {
  playRate = parseFloat(ev.target.value) || 1;
  showRate();
  if (audioEl) audioEl.playbackRate = playRate;          // takes effect mid-sentence
  try { localStorage.setItem("joe-voice-rate", String(playRate)); } catch (e) {}
});
function hush() { sayGen++; speaking = false; if (audioEl) { audioEl.pause(); audioEl = null; } }
function speechPieces(text, max = 180) {
  const out = []; let cur = "";
  for (const s of text.replace(/\s+/g, " ").split(/(?<=[.!?;:])\s+/)) {
    if (!s) continue;
    if (cur && (cur + " " + s).length > max) { out.push(cur); cur = s; } else cur = cur ? cur + " " + s : s;
    if (out.length === 0 && cur.length > 60) { out.push(cur); cur = ""; }   // keep the first piece short
  }
  if (cur) out.push(cur);
  return out;
}
async function fetchSpeech(text) {
  const r = await fetch("/api/voice/speak", { method: "POST", headers: { "X-NR-Token": TOKEN, "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
  if (!(r.headers.get("Content-Type") || "").startsWith("audio/")) {
    const j = await r.json().catch(() => ({})); throw new Error(j.error || "Joe lost his voice");
  }
  return URL.createObjectURL(await r.blob());
}
// Speech queue: pieces are made in order (one at a time, so the first comes back fastest)
// and played back-to-back. hush() cancels everything.
let speechList = [], speechOpen = false, speechLoop = null;
function speechStart() { hush(); speechList = []; speechOpen = true; speaking = true; const gen = sayGen; speechLoop = playSpeech(gen); }
function speechQueue(text) { speechList.push({ text, url: null, made: null }); makeNext(sayGen); }
function speechEnd() { speechOpen = false; }
let makingGen = -1;
async function makeNext(gen) {
  if (makingGen === gen) return;                  // this conversation's maker is already running
  makingGen = gen;
  const list = speechList;
  try {
    for (let i = 0; i < list.length; i++) {
      if (gen !== sayGen) break;
      const item = list[i];
      if (item.made) continue;
      item.made = fetchSpeech(item.text).catch((e) => { toast(e.message); return null; });
      item.url = await item.made;
    }
  } finally { if (makingGen === gen) makingGen = -1; }
  if (gen === sayGen && list.some((i) => !i.made)) makeNext(gen);
}
async function playSpeech(gen) {
  let i = 0;
  while (gen === sayGen) {
    const item = speechList[i];
    if (!item) {
      if (!speechOpen) break;
      await new Promise((r) => setTimeout(r, 60));
      continue;
    }
    if (!item.made) { await new Promise((r) => setTimeout(r, 40)); continue; }
    const url = await item.made;
    if (gen !== sayGen) { if (url) URL.revokeObjectURL(url); break; }
    if (url) {
      await new Promise((res) => {
        audioEl = new Audio(url);
        audioEl.preservesPitch = true; audioEl.playbackRate = playRate;   // faster, same voice
        audioEl.addEventListener("ended", res); audioEl.addEventListener("error", res); audioEl.addEventListener("pause", res);
        audioEl.play().catch(res);
      });
      URL.revokeObjectURL(url);
    }
    i++;
  }
  if (gen === sayGen) speaking = false;
}
async function say(text, loud) {
  if (!text || !text.trim()) return;
  if (!voiceReady) {
    try { voiceReady = (await api("/api/voice/status")).voice; } catch (e) {}
    if (!voiceReady) { if (loud) toast("Set up Joe's voice first: F10 > System check"); return; }
  }
  speechStart();
  for (const p of speechPieces(text)) speechQueue(p);
  speechEnd();
}
function storyText() {
  const t = document.querySelector("#s-about pre").textContent;
  const m = t.match(/JOE'S STORY\s*─+\s*([\s\S]*?)\n\s*\n/);
  return "Meet zero one zero zero zero zero zero one, zero one zero zero one zero zero one. Humans can't say that, so we just call him Joe. " +
    (m ? m[1].replace(/\s+/g, " ").replace("01000001 01001001", "Joe").replace(".dll", "dot D L L") : "");
}
// Talking. "open" (default): while the Talk screen is up the mic listens; each time you
// speak and pause, Joe hears it. He doesn't listen while he's talking or thinking, and the
// mic closes when you leave Talk or press MIC OFF. "push": hold your chosen key anywhere.
let talkMode = "open", pttKey = "F4", micMuted = false, micStream = null, micCtx = null, micLoop = null;
let busyTalking = false, settingKey = false, micGen = 0;
const keyName = (k) => (k || "").replace(/^Key|^Digit/, "");
function pttLabel() {
  if (!voiceReady) { $("#ptt").textContent = "[ SET UP VOICE ]"; return; }
  if (talkMode === "push") $("#ptt").textContent = rec ? "[ LISTENING ]" : `[ HOLD ${keyName(pttKey).toUpperCase()} ]`;
  else $("#ptt").textContent = micMuted ? "[ MIC OFF ]" : "[ MIC ON ]";
}
function badge(text) {
  document.querySelector(".rec-badge")?.remove();
  if (!text) return;
  const b = document.createElement("div"); b.className = "rec-badge"; b.textContent = text; document.body.appendChild(b);
}
async function sendAudio(chunks) {
  if (!chunks.length) return;
  let blob = new Blob(chunks, { type: chunks[0].type || "audio/webm" });
  try { blob = await toWav(blob, 16000); } catch (e) {}   // plain 16 kHz WAV: no decoder needed
  busyTalking = true;
  const r = await fetch("/api/voice/listen", { method: "POST", headers: { "X-NR-Token": TOKEN, "Content-Type": blob.type }, body: blob })
    .then((x) => x.json()).catch((e) => ({ ok: false, error: e.message }));
  if (!r.ok || !r.text || r.text.replace(/[^a-z]/gi, "").length < 2) {
    busyTalking = false;
    if (!r.ok) { talkLog.push({ who: "joe", text: "(I couldn't hear that: " + (r.error || "unknown problem") + ")" }); renderTalk(); }
    return;
  }
  if (talkMode === "push" && current !== "talk") show("talk");   // push-to-talk works from any screen
  await talkSend(r.text);
  busyTalking = false;
}
// --- open mic -------------------------------------------------------------------
async function openMicStart() {
  if (micStream || talkMode !== "open" || micMuted || !voiceReady || current !== "talk") return;
  try { micStream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } }); }
  catch (e) { toast("Joe can't hear you: allow the microphone for this window"); micMuted = true; pttLabel(); return; }
  if (current !== "talk" || micMuted) { openMicStop(); return; }
  micCtx = new AudioContext();
  if (micCtx.state === "suspended") await micCtx.resume().catch(() => {});
  const an = micCtx.createAnalyser(); an.fftSize = 1024;
  micCtx.createMediaStreamSource(micStream).connect(an);
  const buf = new Float32Array(an.fftSize);
  let floor = 0.01, utter = null, chunks = [], start = 0, lastLoud = 0;
  const gen = ++micGen;                       // anything recorded after leaving Talk is thrown away
  badge(" ● MIC ON — just talk ");
  micLoop = setInterval(() => {
    an.getFloatTimeDomainData(buf);
    let sum = 0; for (const v of buf) sum += v * v;
    const rms = Math.sqrt(sum / buf.length), now = performance.now();
    meter(rms);
    const joeBusy = busyTalking || speaking || (audioEl && !audioEl.paused);
    if (!utter) floor = floor * 0.97 + rms * 0.03;                   // learn the room's background noise
    const loud = rms > Math.max(0.015, floor * 3);
    if (!utter && loud && !joeBusy) {                                 // you started talking
      chunks = []; utter = new MediaRecorder(micStream);
      utter.ondataavailable = (e) => e.data.size && chunks.push(e.data);
      utter.onstop = () => {
        const c = chunks, long = lastLoud - start > 500; utter = null;
        if (gen !== micGen) return;
        badge(" ● MIC ON — just talk ");
        if (long) sendAudio(c);
      };
      utter.start(); start = lastLoud = now; badge(" ● LISTENING… ");
    } else if (utter) {
      if (loud) lastLoud = now;
      if (now - lastLoud > 850 || now - start > 30000) utter.stop();   // you paused: Joe's turn
    }
  }, 80);
}
function meter(rms) {                  // live mic level, so you can see Joe hears you
  const m = $("#mic-meter"); if (!m) return;
  const n = Math.min(20, Math.round(rms * 160));
  m.textContent = "MIC " + "█".repeat(n) + "░".repeat(20 - n);
}
function openMicStop() {
  micGen++;
  if ($("#mic-meter")) $("#mic-meter").textContent = "";
  if (micLoop) { clearInterval(micLoop); micLoop = null; }
  if (micCtx) { micCtx.close().catch(() => {}); micCtx = null; }
  if (micStream) { micStream.getTracks().forEach((t) => t.stop()); micStream = null; }
  badge("");
}
// --- push-to-talk -----------------------------------------------------------------
async function recStartFn() {
  if (rec) return;
  if (!voiceReady) { show("talk"); return; }
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
  catch (e) { toast("Joe can't hear you: allow the microphone for this window"); return; }
  const chunks = [];
  rec = new MediaRecorder(stream);
  rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  rec.onstop = () => {
    stream.getTracks().forEach((t) => t.stop());
    $("#ptt").classList.remove("rec"); badge("");
    const ms = performance.now() - recStart; rec = null; pttLabel();
    if (ms >= 400) sendAudio(chunks);
  };
  hush();
  recStart = performance.now();
  rec.start();
  $("#ptt").classList.add("rec"); pttLabel();
  badge(` ● LISTENING — let go of ${keyName(pttKey)} to send `);
}
function recStopFn() { if (rec && rec.state === "recording") rec.stop(); }
function isPtt(ev) { return talkMode === "push" && (ev.key === pttKey || ev.code === pttKey); }
// Capture keys before anything else: setting the key, and holding it to talk.
window.addEventListener("keydown", (ev) => {
  if (settingKey) {
    ev.preventDefault(); ev.stopImmediatePropagation();
    if (ev.key !== "Escape") { pttKey = ev.key.length === 1 ? ev.code : ev.key; $("#ptt-key").value = pttKey; saveSetup(); }
    settingKey = false; toast(`Push-to-talk key: ${keyName(pttKey)}`);
    return;
  }
  // F-keys, Ctrl, Alt etc. work even while typing; a letter key only when you're not typing.
  const typingNow = /^(TEXTAREA|INPUT|SELECT)$/.test(ev.target.tagName) && /^(Key|Digit|Space|Minus|Equal|Bracket|Semicolon|Quote|Comma|Period|Slash|Backslash|Backquote)/.test(pttKey);
  if (isPtt(ev) && !typingNow) {
    ev.preventDefault(); ev.stopImmediatePropagation();
    if (!ev.repeat) recStartFn();
  }
}, true);
window.addEventListener("keyup", (ev) => { if (isPtt(ev)) { ev.preventDefault(); recStopFn(); } }, true);
function f6Down() { show("talk"); }                 // F4 opens Talk (open mic starts there)
$("#ptt").addEventListener("mousedown", (ev) => {
  ev.preventDefault();
  if (!voiceReady) { show("setup", "system"); toast("Press SET UP next to \"Joe's voice\" in the System check"); return; }
  if (talkMode === "push") { recStartFn(); return; }
  micMuted = !micMuted; pttLabel();
  if (micMuted) openMicStop(); else openMicStart();
});
["mouseup", "mouseleave"].forEach((e) => $("#ptt").addEventListener(e, () => { if (talkMode === "push") recStopFn(); }));

/* ---------------- make Joe sound like me (voice copy) ---------------- */
const MV_SCRIPT = "Hi, this is my voice for Joe. The quick brown fox jumps over the lazy dog, and the five " +
  "boxing wizards jump quickly. In the morning I'd like Joe to tell me what's finished, what went wrong, and " +
  "what still needs a look. Let's keep it simple: clear words, a steady pace, and a little bit of fun. " +
  "Thanks, Joe. That's all for now.";
let mvRec = null, mvTimer = null;
async function loadMyVoice() {
  let v; try { v = await api("/api/voice/status"); } catch (e) { return; }
  const sel = $("#voice-select");
  if (v.my_voice && !sel.querySelector('option[value="mine"]')) {
    const o = document.createElement("option"); o.value = "mine"; o.textContent = "My voice (this PC only)"; sel.prepend(o);
  }
  const st = await api("/api/settings").catch(() => null);
  if (st) sel.value = st.voice.voice;
  $("#mv-record").disabled = !v.clone;
  $("#mv-status").textContent = !v.voice ? "Set up Joe's voice first (System check)."
    : !v.clone ? "Needs the Voice copy add-on: System check > Voice copy > SET UP (NVIDIA card, about 3 GB)."
    : v.my_voice ? "Joe has your voice. Pick \"My voice\" above, or record again to replace it. (While Joe works overnight he uses the built-in voice so the graphics card stays free.)"
    : "Tick the box, press RECORD and read the passage out loud (about 30 seconds).";
}
function wavFromBuffer(buf) {            // mono 16-bit PCM WAV
  const data = buf.getChannelData(0), rate = buf.sampleRate, n = data.length;
  const out = new DataView(new ArrayBuffer(44 + n * 2));
  const w = (o, s) => [...s].forEach((c, i) => out.setUint8(o + i, c.charCodeAt(0)));
  w(0, "RIFF"); out.setUint32(4, 36 + n * 2, true); w(8, "WAVE"); w(12, "fmt ");
  out.setUint32(16, 16, true); out.setUint16(20, 1, true); out.setUint16(22, 1, true);
  out.setUint32(24, rate, true); out.setUint32(28, rate * 2, true); out.setUint16(32, 2, true); out.setUint16(34, 16, true);
  w(36, "data"); out.setUint32(40, n * 2, true);
  for (let i = 0; i < n; i++) out.setInt16(44 + i * 2, Math.max(-1, Math.min(1, data[i])) * 0x7fff, true);
  return new Blob([out.buffer], { type: "audio/wav" });
}
async function mvToWav(blob) { return toWav(blob, 24000); }
async function toWav(blob, rate) {
  const ctx = new AudioContext();
  const decoded = await ctx.decodeAudioData(await blob.arrayBuffer());
  ctx.close();
  const off = new OfflineAudioContext(1, Math.max(1, Math.ceil(decoded.duration * rate)), rate);
  const src = off.createBufferSource(); src.buffer = decoded; src.connect(off.destination); src.start();
  return wavFromBuffer(await off.startRendering());
}
async function mvRecord() {
  if (mvRec) { mvRec.stop(); return; }
  if (!$("#mv-consent").checked) { toast("Tick the box to confirm it's your own voice"); return; }
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: true } }); }
  catch (e) { toast("Allow the microphone for this window"); return; }
  const chunks = [];
  mvRec = new MediaRecorder(stream);
  mvRec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  mvRec.onstop = async () => {
    stream.getTracks().forEach((t) => t.stop());
    clearInterval(mvTimer); mvRec = null;
    $("#mv-record").textContent = "[ RECORD MY VOICE ]"; $("#mv-script").hidden = true;
    $("#mv-status").textContent = "Saving your voice…";
    try {
      const wav = await mvToWav(new Blob(chunks, { type: chunks[0]?.type || "audio/webm" }));
      const r = await fetch("/api/voice/myvoice", { method: "POST", body: wav,
        headers: { "X-NR-Token": TOKEN, "Content-Type": "audio/wav", "X-Consent": "my-own-voice" } }).then((x) => x.json());
      toast(r.ok ? "Got it. Joe will talk like you now." : r.error);
    } catch (e) { toast("Couldn't save the recording: " + e.message); }
    loadMyVoice();
  };
  hush();
  mvRec.start();
  let left = 35;
  $("#mv-script").hidden = false;
  const paint = () => { $("#mv-script").textContent = `● RECORDING — read this out loud (${left}s, press STOP when done)\n\n${MV_SCRIPT}`; };
  paint();
  $("#mv-record").textContent = "[ STOP ]";
  mvTimer = setInterval(() => { left--; paint(); if (left <= 0 && mvRec) mvRec.stop(); }, 1000);
}
document.addEventListener("click", async (ev) => {
  const b = ev.target.closest("button"); if (!b) return;
  if (b.dataset.act === "mv-record") mvRecord().catch((e) => toast(e.message));
  if (b.dataset.act === "mv-delete") confirmBox("Delete your voice recording? Joe goes back to a built-in voice.", async () => {
    await api("/api/voice/myvoice/delete", {}); toast("Deleted"); loadMyVoice();
  });
});

/* ---------------- drop files into Talk ---------------- */
let talkFiles = [];
function renderFiles() {
  $("#talk-files").innerHTML = talkFiles.map((f, i) => `<span class="chip${f.busy ? " busy" : ""}">📎 ${esc(f.name)}` +
    (f.busy ? " …" : f.kind === "image" ? " (picture)" : ` (${f.chars.toLocaleString()} chars${f.truncated ? ", long" : ""})`) +
    (f.busy ? "" : ` <button data-unattach="${i}">×</button>`) + `</span>`).join("");
}
async function attachFiles(list) {
  if (current !== "talk") show("talk");
  for (const file of list) {
    const f = { name: file.name, busy: true };
    talkFiles.push(f); renderFiles();
    try {
      const r = await fetch("/api/talk/attach", { method: "POST", body: file,
        headers: { "X-NR-Token": TOKEN, "Content-Type": "application/octet-stream", "X-Filename": encodeURIComponent(file.name) } }).then((x) => x.json());
      if (!r.ok) { talkFiles.splice(talkFiles.indexOf(f), 1); toast(r.error); }
      else Object.assign(f, r, { busy: false });
    } catch (e) { talkFiles.splice(talkFiles.indexOf(f), 1); toast("Couldn't attach " + file.name); }
    renderFiles();
  }
  if (talkFiles.length) toast('Attached. Ask about it, or say "read it".');
}
let dragDepth = 0;
window.addEventListener("dragenter", (ev) => { if ([...ev.dataTransfer.types].includes("Files")) { dragDepth++; $("#dropveil").hidden = false; } });
window.addEventListener("dragleave", () => { if (--dragDepth <= 0) { dragDepth = 0; $("#dropveil").hidden = true; } });
window.addEventListener("dragover", (ev) => ev.preventDefault());       // never let the window open the file itself
window.addEventListener("drop", (ev) => {
  ev.preventDefault(); dragDepth = 0; $("#dropveil").hidden = true;
  const files = [...(ev.dataTransfer?.files || [])];
  if (!files.length) return;
  if (current === "tools" || (current !== "talk" && typeof toolFor === "function" && toolFor(files))) { toolsDrop(files); return; }
  attachFiles(files);
});
$("#talk-file").addEventListener("change", (ev) => { attachFiles([...ev.target.files]); ev.target.value = ""; });
document.addEventListener("click", async (ev) => {
  const b = ev.target.closest("button"); if (!b) return;
  if (b.dataset.act === "talk-attach") $("#talk-file").click();
  if (b.dataset.unattach !== undefined) {
    const f = talkFiles.splice(+b.dataset.unattach, 1)[0];
    if (f && f.id) api("/api/talk/detach", { id: f.id });
    renderFiles();
  }
});

/* ---------------- update check ---------------- */
async function checkUpdate(manual) {
  let r;
  try { r = await api("/api/update" + (manual ? "?force=1" : "?auto=1")); } catch (e) { r = { ok: false, error: e.message }; }
  if (r.off) return;
  if (!r.ok) { if (manual) $("#setup-msg").textContent = `You have ${r.current || "?"}. ${r.error}`; return; }
  if (!r.newer) { if (manual) $("#setup-msg").textContent = `You have the newest version (${r.current}).`; return; }
  if (manual) $("#setup-msg").textContent = `Joe ${r.latest} is out (you have ${r.current}).`;
  const notes = r.notes ? r.notes.slice(0, 600) + "\n\n" : "";
  if (r.asset) {
    const mb = r.asset.size ? ` (${Math.round(r.asset.size / 1048576)} MB)` : "";
    const how = { "windows-installer": "Joe closes while it installs and opens again by himself.",
      "mac-app": "When it's downloaded, drag the new Joe onto Applications.",
      "linux-appimage": "Joe swaps in the new version and restarts." }[r.kind] || "";
    confirmBox(`Joe ${r.latest} is out. You have ${r.current}.\n\n${notes}Download and install it now${mb}? It's checked against the release's checksum first. ${how} Your files and settings are kept.`,
      async () => {
        const x = await api("/api/doctor/fix", { action: "update-joe", approved: true });
        $("#setup-msg").textContent = x.ok ? "Downloading the update…" : x.error;
      });
    return;
  }
  confirmBox(`Joe ${r.latest} is out. You have ${r.current}.\n\n${notes}Open the download page?`,
    () => window.open(r.url, "_blank", "noopener"));
}
setTimeout(() => checkUpdate(false), 8000);

/* ---------------- first-start welcome (setup helper) ---------------- */
// One small step at a time, in plain words. Each YES is the person's OK for that one install;
// the System check (F10) does the actual work underneath.
// Four short steps. "Get set up" is one ticked list (Joe's picks for this PC already ticked)
// and one button; things that only appear after an install (the writing model once Ollama is
// in, picture models once ComfyUI is in) are added to the same run by themselves.
const W_GROUPS = [
  { id: "writing", name: "Writing (needed)", ids: ["install-ollama", "start-ollama", "pull-model", "use-model", "upgrade-model"] },
  { id: "pictures", name: "Pictures and video", ids: ["install-comfyui", "start-comfyui", "get-image-model", "get-video-model", "get-video-turbo", "pack-bg", "pack-upscale", "pack-edit"] },
  { id: "talk", name: "Talking", ids: ["install-voice", "pull-talk-model", "pull-vision", "install-clone"] },
  { id: "extras", name: "Little helpers", ids: ["install-pandoc", "install-ffmpeg", "pull-embed", "pack-music", "pack-sfx"] },
];
const W_STEPS = [
  { id: "hello", name: "Hello" },
  { id: "pc", name: "Your PC" },
  { id: "pick", name: "Get set up" },
  { id: "look", name: "Look" },
  { id: "done", name: "Ready" },
];
const W_TEXT = {
  "install-ollama": ["Joe needs Ollama: a free program that runs AI writing models on your own PC.", "YES, INSTALL OLLAMA", "Your computer may ask for permission."],
  "start-ollama": ["Ollama is installed but switched off.", "YES, START IT", ""],
  "pull-model": [null, "YES, DOWNLOAD IT", "It can take a while. You can keep going while it downloads."],
  "use-model": [null, "YES, USE IT", ""],
  "upgrade-model": [null, "YES, GET THE BETTER ONE", "It can take a while. Joe uses it as soon as it's done."],
  "get-video-turbo": ["The Turbo add-on makes videos several times faster (under 1 GB).", "YES, DOWNLOAD IT", "Restart ComfyUI when it's done."],
  "pull-talk-model": ["A small, quick model just for talking, so Joe answers faster.", "YES, DOWNLOAD IT", ""],
  "install-comfyui": ["For pictures and video, Joe uses ComfyUI: a free drawing program.", "YES, INSTALL COMFYUI", "Your computer may ask for permission. Skip this if you only want writing."],
  "get-image-model": ["ComfyUI needs a picture model to draw with.", "YES, DOWNLOAD ONE", ""],
  "get-video-model": ["For short video clips, Joe can get a video model. It's big: about 18 GB, an hour or more to download.", "YES, DOWNLOAD IT", "Restart ComfyUI when it's done."],
  "install-voice": ["So you can talk to Joe and hear him answer. About 500 MB.", "YES, SET UP HIS VOICE", "Runs on the regular processor, so it never slows the night's work."],
  "pull-vision": ["So Joe can look at pictures you show him.", "YES, DOWNLOAD IT", ""],
  "pull-embed": ["A small search model (about 270 MB) so Ask my files finds the right parts of your documents.", "YES, DOWNLOAD IT", ""],
  "install-clone": ["Optional fun: make Joe talk in YOUR voice (stays on this PC). About 3 GB.", "YES, SET IT UP", "You record yourself later in Setup > Voice & Talk."],
  "install-pandoc": ["To make finished Word and PDF copies of what Joe writes.", "YES, INSTALL IT", ""],
  "install-ffmpeg": ["To turn animations into MP4 videos you can share.", "YES, INSTALL IT", ""],
};
let W = { open: false, i: 0, d: null, busyWas: "", asked: {}, pick: null, queue: [], auto: false, tried: {} };
// The checklist: everything Joe could install, grouped, with sizes. Small and needed things
// start ticked; big downloads (picture editor, video, music) start unticked. Nothing is
// installed until the person presses INSTALL WHAT'S TICKED.
const W_SMALL = ["install-voice", "install-ffmpeg", "install-pandoc", "pull-vision", "pull-embed",
  "pull-talk-model", "pack-bg", "pack-upscale", "get-video-turbo"];
function wSizeGB(it) {
  const m = /(?:about |under )?(\d+(?:\.\d+)?)\s*(GB|MB)/i.exec((it.what || "") + " " + it.text);
  return m ? (m[2].toUpperCase() === "MB" ? +m[1] / 1024 : +m[1]) : 0;
}
function wDefaultTick(it, d) {
  if (!it.optional) return true;
  const strongCard = d && d.gpu && d.vendor === "nvidia" && d.vram_gb >= 8;
  if (W_SMALL.includes(it.id)) return true;
  if (["install-comfyui", "get-image-model"].includes(it.id)) return !!strongCard;
  return false;
}
function wPickList() {
  const d = W.d; if (!d) return '<div class="blink">Checking…</div>';
  W.pick = W.pick || {};
  d.issues.forEach((it) => { if (!(it.id in W.pick)) W.pick[it.id] = wDefaultTick(it, d); });   // new choices appear after installs
  const groups = W_GROUPS;
  const seen = new Set();
  const list = d.issues.filter((it) => it.group !== "updates");
  if (!list.length) return '<p class="bright">√ Everything Joe needs is here. Press NEXT.</p>';
  let h = "<p>Joe ticked what fits this PC. Change anything you like, then press the button: he installs it all, one thing after another. Nothing downloads before that. You can add more later in Setup (F10).</p>";
  if (list.some((it) => it.id === "install-ollama" || it.id === "install-comfyui"))
    h += '<p class="dim small">The writing model (and picture models) are picked and added by themselves once Ollama (and ComfyUI) are in.</p>';
  groups.forEach((g) => {
    const its = list.filter((it) => g.ids.includes(it.id));
    its.forEach((it) => seen.add(it.id));
    if (!its.length) return;
    h += `<div class="wgroup"><b>${esc(g.name)}</b>` + its.map((it) => {
      const gb = wSizeGB(it), size = gb ? (gb >= 1 ? `${gb.toFixed(gb < 10 ? 1 : 0)} GB` : `${Math.round(gb * 1024)} MB`) : "";
      return `<label class="wpick"><input type="checkbox" data-wpick="${esc(it.id)}"${W.pick[it.id] ? " checked" : ""}${!it.optional ? " disabled" : ""}> ${esc(it.text)}${size ? ` <span class="dim">(${size})</span>` : ""}</label>`;
    }).join("") + "</div>";
  });
  const rest = list.filter((it) => !seen.has(it.id));
  if (rest.length) h += `<div class="wgroup"><b>Other</b>` + rest.map((it) => `<label class="wpick"><input type="checkbox" data-wpick="${esc(it.id)}"${W.pick[it.id] ? " checked" : ""}> ${esc(it.text)}</label>`).join("") + "</div>";
  const picked = list.filter((it) => W.pick[it.id]);
  const total = picked.reduce((a, it) => a + wSizeGB(it), 0);
  h += `<p class="bright">You picked ${picked.length} thing(s), about ${total >= 1 ? total.toFixed(0) + " GB" : Math.round(total * 1024) + " MB"} to download.</p>`;
  if (W.queue.length || (state && state.busy)) h += `<div class="blink">Installing${state && state.busy ? ": " + esc(state.busy) + (state.busy_pct != null ? ` ${Math.round(state.busy_pct)}%` : "") : "…"} (${W.queue.length} more after this)</div>`;
  else h += picked.length ? `<button class="primary" data-wpickgo="1">[ INSTALL WHAT'S TICKED ]</button>` : "";
  return h;
}
function wFollowOns() {                          // new choices after an install join the same run
  if (!W.auto || !W.d) return;
  W.pick = W.pick || {};
  W.d.issues.forEach((it) => {
    if (it.group === "updates") return;
    if (!(it.id in W.pick)) W.pick[it.id] = wDefaultTick(it, W.d);
    if (W.pick[it.id] && !W.tried[it.id] && !W.queue.includes(it.id)) W.queue.push(it.id);
  });
}
async function wPickNext() {
  wFollowOns();
  if (!W.queue.length) { if (W.auto && !(state && state.busy)) { W.auto = false; wRender(); } return; }
  if (state && state.busy) return;
  const id = W.queue.shift();
  W.tried[id] = true;
  const it = W.d && W.d.issues.find((x) => x.id === id);
  if (!it) { wPickNext(); return; }
  try {
    const r = await api("/api/doctor/fix", { ...it, approved: true });
    if (!r.ok) toast(r.error);
    if (!r.started) { await wCheck(); wPickNext(); }
  } catch (e) { toast(e.message); }
  wRender();
}
function welcomeOpen(at = 0) {
  W.open = true; W.i = at; W.asked = {};
  $("#welcome").hidden = false;
  wRender(); wCheck();
}
async function welcomeClose() {
  W.open = false; $("#welcome").hidden = true;
  try { await api("/api/settings", { ui: { welcomed: true } }); } catch (e) {}
}
async function wCheck() {
  try { W.d = await api("/api/doctor"); doctorData = W.d; } catch (e) { W.d = null; }
  if (typeof readyBanner === "function") readyBanner(W.d);
  if (W.open) wRender();
}
function wIssues(step) {
  const ids = step.ids || [];
  return W.d ? W.d.issues.filter((it) => ids.includes(it.id)).sort((a, b) => ids.indexOf(a.id) - ids.indexOf(b.id)) : [];
}
function wGpuLine(d) {
  if (!d) return "Checking your computer…";
  if (!d.gpu) return `I couldn't find a graphics card I can use. I can still write, just more slowly, but pictures and video need one. Memory: ${d.ram_gb} GB.`;
  const v = d.vram_gb, g = d.gpu;
  if (g.vendor !== "nvidia") {
    const mem = v ? (g.unified ? ` (${v} GB of the shared memory for graphics)` : ` with ${v} GB of video memory`) : "";
    return `Graphics: ${g.name}${mem}.\n${d.gpu_advice || ""}\nMemory: ${d.ram_gb} GB.`;
  }
  const verdict = v >= 16 ? "Plenty for writing, pictures and short videos." : v >= 10 ? "Great for writing and pictures, and fine for short videos."
    : v >= 6 ? "Good for writing and pictures." : "Enough for small writing models; pictures will be slow.";
  return `Graphics card: ${g.name || "NVIDIA"} with ${v} GB of video memory. ${verdict}\nMemory: ${d.ram_gb} GB.`;
}
function wItem(it) {
  const [say, yes, note] = W_TEXT[it.id] || [it.text, "YES", ""];
  const busy = state && state.busy;
  const mine = W.asked[it.id];
  const pct = busy && state.busy_pct != null ? ` ${Math.round(state.busy_pct)}%` : "";
  return `<div class="witem"><div>${esc(say || it.text)}</div>${say ? "" : ""}` +
    (note ? `<div class="dim small">${esc(note)}</div>` : "") +
    (mine && busy ? `<div class="blink">Working on it…${pct}</div>`
      : `<button data-wfix="${esc(it.id)}"${busy ? " disabled title=\"Wait for the current setup to finish\"" : ""}>[ ${yes} ]</button>`) + `</div>`;
}
function wRender() {
  const st = W_STEPS[W.i], d = W.d;
  $("#w-steps").innerHTML = W_STEPS.map((s, i) => `<span class="${i === W.i ? "on" : i < W.i ? "done" : "dim"}">${i < W.i ? "√" : i + 1}. ${s.name}</span>`).join("");
  $("#w-title").textContent = st.id === "hello" ? "HI, I'M JOE" : st.name.toUpperCase();
  let h = "";
  if (st.id === "hello") {
    h = `<p>01000001 01001001, if you're fancy. Humans can't say that, so just call me Joe.</p>
      <p>I do the grunt work on your own computer while you sleep: lists, descriptions, documents, spreadsheets, pictures and short videos. Free and private: your files never leave this PC. Setting me up needs the internet to download programs and models, and I ask before each one.</p>
      <p>Let's get me set up. It's a few short steps, and I ask before installing anything.</p>`;
  } else if (st.id === "pc") {
    h = `<pre class="out">${esc(wGpuLine(d))}</pre>`;
  } else if (st.ids) {
    const left = wIssues(st);
    const intro = { writing: "This is the part Joe can't work without: a free program and a writing model.",
      pictures: "Optional. Skip it if you only want writing.", talk: "Optional. You can always type instead.",
      extras: "Optional little helpers." }[st.id];
    h = `<p class="dim">${intro}</p>`;
    if (!d) h += '<div class="blink">Checking…</div>';
    else if (!left.length) {
      const ok = { writing: `√ Ready. Joe writes with ${d.ollama.best || d.ollama.configured}.`,
        pictures: d.comfyui.installed ? `√ Ready. Pictures: ${d.comfyui.best_image || "ComfyUI found"}${d.comfyui.best_video ? "; video: " + d.comfyui.best_video : ""}.` : "√ Nothing to do here.",
        talk: d.voice ? "√ Ready. Press F4 any time to talk to Joe." : "√ Nothing to do here.",
        extras: "√ All set." }[st.id];
      h += `<div class="bright">${esc(ok)}</div>`;
      if (st.id === "writing") h += `<div class="witem"><div>How fast is this PC? One quick test (about half a minute) makes Joe's time estimates fit your computer.</div>` +
        (W.speed ? `<div class="bright">${esc(W.speed)}</div>` : `<button data-wspeed="1"${W.speeding ? " disabled" : ""}>[ ${W.speeding ? "TESTING…" : "TEST MY SPEED"} ]</button>`) + `</div>`;
    } else h += left.map(wItem).join("");
  } else if (st.id === "pick") {
    h = wPickList();
  } else if (st.id === "look") {
    const opts = [...$("#theme-select").options].map((o) => [o.value, o.textContent]);
    const cur = state ? state.ui.phosphor : "";
    h = `<p>Pick a look. You can change it any time in Setup (F10).</p><div class="wlooks">` +
      opts.map(([v, n]) => `<button data-wlook="${esc(v)}" class="${v === cur ? "on" : ""}">[ ${esc(n)} ]</button>`).join("") + "</div>";
  } else if (st.id === "done") {
    const need = W.d && W.d.issues.find((it) => !it.optional);
    const how = `<ol class="planlist"><li>Type what you need in the big box, in your own words. Questions work too.</li>
        <li>Joe shows you a plan. Press RUN IT.</li><li>Go to bed. In the morning, see the report.</li></ol>
        <p class="dim small">Short words work in the box: go, stop, help, report, files, tools, update. Hover over any button to see what it does.</p>`;
    h = need ? `<p>Almost: Joe still needs his writing setup. Go BACK to "Get set up" and press the button, or finish later from the banner on the main screen.</p>` + how
      : `<p>All set. Here's how it works:</p>` + how +
        `<div class="witem"><div>Optional: a half-minute speed test makes Joe's time estimates fit your computer.</div>` +
        (W.speed ? `<div class="bright">${esc(W.speed)}</div>` : `<button data-wspeed="1"${W.speeding ? " disabled" : ""}>[ ${W.speeding ? "TESTING…" : "TEST MY SPEED"} ]</button>`) + `</div>`;
  }
  $("#w-body").innerHTML = h;
  $("#w-back").disabled = W.i === 0;
  $("#w-next").textContent = W.i === W_STEPS.length - 1 ? "[ START USING JOE ]" : "[ NEXT ▸ ]";
}
function welcomeTick() {                          // called by poll(): show progress, re-check when a setup ends
  if (!state || (!W.open && !W.auto)) return;      // the ticked installs keep going after the helper closes
  if (state.busy !== W.busyWas) {
    const ended = W.busyWas && !state.busy;
    W.busyWas = state.busy;
    if (ended) wCheck().then(() => wPickNext()); else if (W.open) wRender();
  } else if (state.busy && W.open) wRender();
}
$("#welcome").addEventListener("click", async (ev) => {
  const b = ev.target.closest("button"); if (!b) return;
  ev.stopPropagation();
  if (b.id === "w-back" && W.i > 0) { W.i--; wRender(); }
  if (b.id === "w-next") { if (W.i === W_STEPS.length - 1) { welcomeClose(); show("queue"); setTimeout(() => $("#describe").focus(), 50); } else { W.i++; wRender(); wCheck(); } }
  if (b.id === "w-skip") welcomeClose();
  if (b.dataset.wfix) {
    const it = W.d && W.d.issues.find((x) => x.id === b.dataset.wfix); if (!it) return;
    W.asked[it.id] = true;
    b.disabled = true; b.textContent = "[ STARTING… ]";
    try {
      const r = await api("/api/doctor/fix", { ...it, approved: true });
      if (!r.ok) { toast(r.error); W.asked[it.id] = false; }
      else if (!r.started) await wCheck();
    } catch (e) { toast(e.message); }
    wRender();
  }
  if (b.dataset.wpickgo) {
    W.auto = true; W.tried = {};
    W.queue = (W.d ? W.d.issues : []).filter((it) => W.pick[it.id] && it.group !== "updates").map((it) => it.id);
    wPickNext();
  }
  if (b.dataset.wspeed) {
    W.speeding = true; wRender();
    try { const r = await api("/api/speedtest", {}); W.speed = r.ok ? r.text : "The test didn't work: " + r.error; }
    catch (e) { W.speed = e.message; }
    W.speeding = false; wRender();
  }
  if (b.dataset.wlook) {
    try {
      const look = b.dataset.wlook;
      await api("/api/settings", { ui: { phosphor: look } });
      $("#theme-select").value = look;
    } catch (e) { toast(e.message); }
    setTimeout(wRender, 1100);                       // poll() applies the new look
  }
});

/* ---------------- hover hints + button labels that suit every look ---------------- */
// Anything with a title shows its hint in the footer as soon as the mouse is over it
// (the browser's own tooltip takes a second or two to appear).
const HINT0 = "Hover over anything to see what it does.";
document.addEventListener("mouseover", (ev) => {
  const el = ev.target.closest && ev.target.closest("[title]");
  $("#hintline").textContent = el && el.title ? el.title : HINT0;
});
// Buttons are written "[ RUN ]" (the retro look). Strip the brackets once and let the CSS put
// them back only on the retro looks, so modern looks get clean rounded buttons.
function debracket(btn) {
  const first = btn.firstChild, last = btn.lastChild;
  if (first && first.nodeType === 3 && /^\s*\[\s?/.test(first.nodeValue)) {
    first.nodeValue = first.nodeValue.replace(/^\s*\[\s?/, "");
    if (last && last.nodeType === 3) last.nodeValue = last.nodeValue.replace(/\s?\]\s*$/, "");
    btn.classList.add("br");
  }
}
function debracketAll(root) {
  if (root.nodeType !== 1) return;
  if (root.tagName === "BUTTON") debracket(root);
  root.querySelectorAll && root.querySelectorAll("button").forEach(debracket);
}
debracketAll(document.body);
new MutationObserver((muts) => {
  for (const m of muts) {
    if (m.type === "characterData") { const b = m.target.parentElement && m.target.parentElement.closest("button"); if (b) debracket(b); }
    else { if (m.target.closest && m.target.closest("button")) debracket(m.target.closest("button")); m.addedNodes.forEach(debracketAll); }
  }
}).observe(document.body, { childList: true, subtree: true, characterData: true });

/* ---------------- comfort: chime when done, screen saver ---------------- */
let lastFinished = -1, actx = null;
function chime(ok) {
  try {
    actx = actx || new AudioContext();
    const notes = ok ? [523.25, 659.25, 783.99] : [392, 311.13];      // C-E-G, or a soft low pair
    notes.forEach((f, i) => {
      const o = actx.createOscillator(), g = actx.createGain(), t = actx.currentTime + i * 0.18;
      o.type = "sine"; o.frequency.value = f;
      g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(0.12, t + 0.02); g.gain.exponentialRampToValueAtTime(0.001, t + 0.6);
      o.connect(g).connect(actx.destination); o.start(t); o.stop(t + 0.65);
    });
  } catch (e) {}
}
let lastInput = Date.now(), saverMove = 0;
["mousemove", "mousedown", "keydown", "wheel", "touchstart"].forEach((e) =>
  window.addEventListener(e, () => { lastInput = Date.now(); if (!$("#saver").hidden) $("#saver").hidden = true; }, { capture: true, passive: true }));
function comfortTick() {
  const f = state.finished || { n: 0 };
  if (lastFinished >= 0 && f.n > lastFinished) {
    if (state.ui.sounds && !state.quiet) chime(f.ok);
    toast(f.text || "Joe is done");
  }
  lastFinished = f.n;
  const mins = (state.comfort || {}).screensaver_min || 0;
  const saver = $("#saver");
  const busyWithUs = !$("#welcome").hidden || !$("#confirm").hidden || (typeof micStream !== "undefined" && micStream);
  if (mins > 0 && !busyWithUs && Date.now() - lastInput > mins * 60000) {
    if (saver.hidden) { saver.hidden = false; saverMove = 0; }
    const done = state.jobs.reduce((a, j) => a + j.parts_done, 0), total = state.jobs.reduce((a, j) => a + j.parts_total, 0);
    $("#saver-line").textContent = state.running ? `working · ${done}/${total}` + (state.eta_s != null ? ` · about ${fmtEta(state.eta_s)} left` : "")
      : "resting · move the mouse to wake me";
    if (saverMove++ % 20 === 0) {                     // drift slowly so nothing burns in
      const b = $("#saver-box");
      b.style.left = Math.round(10 + Math.random() * 60) + "vw"; b.style.top = Math.round(10 + Math.random() * 65) + "vh";
    }
  }
}


/* ---------------- Tools tab (F3): one card per tool, a short form, same engine ---------------- */
let toolCat = null, toolHave = {}, toolOpen = null, toolFiles = [];
async function loadTools() {
  if (!toolCat) {
    try { const r = await api("/api/tools"); toolCat = r; toolHave = r.have || {}; toolBadge(r.status); }
    catch (e) { $("#toolgrid").textContent = e.message; return; }
  } else {
    api("/api/tools").then((r) => { toolHave = r.have || {}; toolBadge(r.status); if (toolOpen) toolNeeds(); else renderToolGrid(); }).catch(() => {});
  }
  if (!toolOpen) renderToolGrid();
}
function renderToolGrid(lit) {     // lit: tool ids to highlight (files waiting for a pick)
  const by = {};
  toolCat.tools.forEach((t) => (by[t.group] = by[t.group] || []).push(t));
  Object.values(by).forEach((list) => list.sort((x, y) => y.ready - x.ready));     // ready tools first
  const groups = toolCat.groups.filter((g) => by[g]).sort((x, y) => by[y][0].ready - by[x][0].ready);
  $("#toolgrid").innerHTML = groups.map((g) =>
    `<div class="tgroup"><h3 class="tgname">${esc(g)}</h3><div class="tcards">` +
    by[g].map((t) => { const st = toolStat[t.id], miss = t.ready && st && !st.ok;
      return `<button type="button" class="tcard${t.ready ? "" : " soon"}${miss ? " needs" : ""}${lit && lit.includes(t.id) ? " lit" : ""}" data-tool="${t.id}"` +
      ` title="${esc(!t.ready ? "Coming soon: " + t.blurb : miss ? "Not ready yet: " + st.why + ". Open it to get what's missing." : t.blurb)}"${t.ready ? "" : " disabled"}>` +
      `<span class="tcn">${esc(t.name)}</span><span class="tcb">${esc(t.blurb)}</span>` +
      (!t.ready ? `<span class="tsoon">Coming soon</span>` : miss ? `<span class="tsoon tneed">${esc(st.why.replace(/^needs /, "Needs "))} · GET IT</span>`
        : st ? `<span class="tsoon tok">√ Ready</span>` : "") + `</button>`; }).join("") +
    `</div></div>`).join("");
  $("#toolgrid").hidden = false; $("#toolform").hidden = true;
}
function toolById(id) { return toolCat && toolCat.tools.find((t) => t.id === id); }
let toolPending = null;            // files dropped while several tools fit: waiting for a pick
function toolsFor(files) {         // every ready tool that can use all these files
  if (!toolCat) return [];
  const ext = (f) => "." + f.name.split(".").pop().toLowerCase();
  return toolCat.tools.filter((t) => t.ready && files.every((f) => t.accepts.includes(ext(f))));
}
function toolFor(files) {          // dropped outside Tools: recordings go to Transcribe; pictures and
  const fit = toolsFor(files);     // documents still attach to Talk as before
  return fit.length === 1 && fit[0].id === "transcribe" ? fit[0] : null;
}
function toolNeeds() {
  const t = toolOpen, msgs = [], needs = t.needs || [];
  if (needs.includes("voice") && !toolHave.voice) msgs.push("This needs Joe's voice add-on first: Setup (F10) > System check > \"Joe's voice\" > SET UP. It's a one-time download of about 500 MB.");
  if (t.id === "transcribe" && !toolHave.ffmpeg) msgs.push("FFmpeg isn't installed, so only .wav files can be read. Setup (F10) > System check installs it.");
  if (needs.includes("vision") && toolHave.vision === false) msgs.push("This needs a vision model (one that can look at pictures). Setup (F10) > System check offers a free one to download.");
  if (needs.includes("vision") && !toolHave.ffmpeg) msgs.push("Without FFmpeg, only JPG, PNG and WebP photos under 6 MB can be used. Setup (F10) > System check installs it.");
  if (t.id === "read-aloud" && !toolHave.ffmpeg) msgs.push("FFmpeg isn't installed, so Joe saves WAV files (much bigger) instead of MP3. Setup (F10) > System check installs it.");
  let html = msgs.map(esc).join("<br>");
  if (needs.includes("comfy")) {
    if (!toolHave.comfy) html += (html ? "<br>" : "") + esc("This runs in ComfyUI, which isn't installed yet. Setup (F10) > System check installs it.");
    else {
      const kind = (document.querySelector('#tf-options [data-pick="kind"]') || {}).value || "";
      const want = { "remove-bg": ["bg"], "edit-picture": ["edit"], "restore-photo": ["edit"],
        "animate-photo": ["video"], music: [kind === "sfx" ? "sfx" : "music"] }[t.id] || [];
      const packs = toolHave.packs || {};
      want.filter((p) => packs[p] && !packs[p].ready).forEach((p) => {
        html += (html ? "<br>" : "") + esc(`This needs ${packs[p].offer}, once. It comes from Hugging Face and goes into ComfyUI's models folder.`) +
          (p === "video" ? esc(" Setup (F10) > System check offers it.") : ` <button type="button" data-pack="${esc(p)}">[ DOWNLOAD IT ]</button>`);
      });
    }
  }
  $("#tf-need").innerHTML = html;
  $("#tf-need").hidden = !html;

}
function openTool(id) {
  const t = toolById(id); if (!t || !t.ready) return;
  toolOpen = t; toolFiles = [];
  $("#tf-title").textContent = t.name;
  $("#tf-blurb").textContent = t.blurb;
  $("#tf-accepts").textContent = "Works with: " + t.accepts.join(" ");
  $("#tf-drop").hidden = !t.accepts.length; $("#tf-files").hidden = !t.accepts.length;
  $("#tf-file").accept = t.accepts.join(",");
  $("#tf-help").textContent = t.help || "";
  $("#tf-options").innerHTML = t.options.map((o) => o.multi
    ? `<div class="tfmulti" title="${esc(o.hint)}"><span>${esc(o.label)}</span>` +
      o.choices.map(([v, l]) => `<label class="tfopt"><input type="checkbox" data-multi="${o.key}" value="${esc(v)}"> ${esc(l)}</label>`).join("") +
      `</div>`
    : o.choices && o.choices.length
    ? `<label class="tfopt tfpick" title="${esc(o.hint)}">${esc(o.label)} <select data-pick="${o.key}">` +
      o.choices.map(([v, l]) => `<option value="${esc(v)}"${v === o.value ? " selected" : ""}>${esc(l)}</option>`).join("") +
      `</select></label>`
    : `<label class="tfopt" title="${esc(o.hint)}"><input type="checkbox" data-opt="${o.key}"${o.default ? " checked" : ""}> ${esc(o.label)}</label>`).join("");
  $("#tf-markrow").hidden = !t.mark; $("#tf-mark").value = ""; $("#tf-logoname").textContent = "";
  $("#tf-name").value = ""; $("#tf-extra").value = ""; $("#tf-plan").textContent = "";
  $("#tf-extra").placeholder = t.extra_hint || "optional, e.g. focus on dates and to-dos";
  $("#tf-extra-label").textContent = t.extra_label || "Anything else?";
  renderToolFiles(); toolNeeds();
  $("#toolgrid").hidden = true; $("#toolform").hidden = false;
}
function renderToolFiles() {
  $("#tf-files").innerHTML = toolFiles.map((f, i) =>
    `<span class="chip${f.busy ? " busy" : ""}">${esc(f.name)}${f.busy ? ` … ${f.pct || 0}%` : f.err ? " ✗" : ""}` +
    (f.busy ? "" : ` <button type="button" data-tfrm="${i}" title="Remove from this job (the file stays in Inbox).">×</button>`) + `</span>`).join("");
}
function uploadOne(file, f) {      // XHR so a big recording shows progress
  return new Promise((resolve) => {
    const x = new XMLHttpRequest();
    x.open("POST", "/api/tools/upload?tool=" + encodeURIComponent(toolOpen.id));
    x.setRequestHeader("X-NR-Token", TOKEN);
    x.setRequestHeader("Content-Type", "application/octet-stream");
    x.setRequestHeader("X-Filename", encodeURIComponent(file.name));
    x.upload.onprogress = (e) => { if (e.lengthComputable) { f.pct = Math.round(e.loaded * 100 / e.total); renderToolFiles(); } };
    x.onload = () => { let r = {}; try { r = JSON.parse(x.responseText); } catch (e) {} resolve(r); };
    x.onerror = () => resolve({ ok: false, error: "Couldn't send " + file.name });
    x.send(file);
  });
}
async function toolsDrop(files) {
  if (current !== "tools") show("tools");
  if (!toolCat) await loadTools();
  if (!toolOpen) {
    const fit = toolsFor(files);
    if (!fit.length) { toast("Pick a tool first, then drop the files on it."); return; }
    if (fit.length > 1) {          // e.g. a document: read it aloud or proofread it? Let them pick.
      toolPending = files; renderToolGrid(fit.map((t) => t.id));
      toast("Which tool? Pick one of the lit-up cards: " + fit.map((t) => t.name).join(" or "));
      return;
    }
    openTool(fit[0].id);
  }
  for (const file of files) {
    const ext = "." + file.name.split(".").pop().toLowerCase();
    if (!toolOpen.accepts.includes(ext)) { toast(`${toolOpen.name} can't use ${ext} files`); continue; }
    const f = { name: file.name, busy: true, pct: 0 };
    toolFiles.push(f); renderToolFiles();
    const r = await uploadOne(file, f);
    if (r.ok) Object.assign(f, { busy: false, input: r.input, name: r.name });
    else { toolFiles.splice(toolFiles.indexOf(f), 1); toast(r.error || "Upload failed"); }
    renderToolFiles();
  }
}
function toolRequest() {
  return { tool: toolOpen.id, files: toolFiles.filter((f) => f.input).map((f) => f.input),
    options: [...document.querySelectorAll("#tf-options [data-opt]")].filter((c) => c.checked).map((c) => c.dataset.opt)
      .concat([...document.querySelectorAll("#tf-options [data-pick]")].map((x) => x.dataset.pick + " " + x.value))
      .concat([...document.querySelectorAll("#tf-options [data-multi]")].filter((c) => c.checked).map((c) => c.dataset.multi + " " + c.value)),
    name: $("#tf-name").value.trim(), extra: $("#tf-extra").value.trim(),
    mark: toolOpen.mark ? $("#tf-mark").value.trim() : "" };
}
async function toolPlan(run) {
  if (toolFiles.some((f) => f.busy)) { toast("Still adding files…"); return; }
  const req = toolRequest();
  if (!req.files.length) { toast("Add at least one file first"); return; }
  if (!req.options.length && toolOpen.options.length) req.options = ["none"];
  let r;
  try { r = await api("/api/tools/mission", req); } catch (e) { r = { ok: false, error: e.message }; }
  if (!r.ok) { $("#tf-plan").textContent = r.error; return; }
  $("#tf-plan").textContent = r.summary.join("\n") + `\nTime: ${r.time}` +
    (r.warnings.length ? "\n\n" + r.warnings.map((w) => "! " + w).join("\n") : "") +
    (run ? "" : "\n\nMission:\n" + r.mission);
  if (!run) return;
  const q = await api("/api/queue/add", { text: r.mission });
  if (!q.ok) { $("#tf-plan").textContent = "ERROR: " + q.error; return; }
  toast(q.queued ? `Queued: it runs after the current work (${q.queued} waiting)` : "Started — safe to close this window");
  toolFiles = []; renderToolFiles();
}
$("#tf-file").addEventListener("change", (ev) => { toolsDrop([...ev.target.files]); ev.target.value = ""; });
$("#tf-logo").addEventListener("change", async (ev) => {       // a logo .png as the watermark
  const file = ev.target.files[0]; ev.target.value = "";
  if (!file || !toolOpen) return;
  if (!file.name.toLowerCase().endsWith(".png")) { toast("A logo needs to be a .png file"); return; }
  $("#tf-logoname").textContent = "Adding " + file.name + "…";
  const r = await uploadOne(file, {});
  if (!r.ok) { $("#tf-logoname").textContent = ""; toast(r.error || "Couldn't add the logo"); return; }
  $("#tf-mark").value = r.input; $("#tf-logoname").textContent = "Logo: " + r.name;
});
$("#tf-drop").addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); $("#tf-file").click(); } });
document.addEventListener("click", (ev) => {
  if (ev.target.closest("#tf-drop")) { $("#tf-file").click(); return; }
  const b = ev.target.closest("button"); if (!b) return;
  if (b.dataset.tool) {
    openTool(b.dataset.tool);
    const waiting = toolPending; toolPending = null;
    if (waiting && toolOpen) toolsDrop(waiting);
  }
  else if (b.dataset.act === "tool-back") { toolOpen = null; toolPending = null; renderToolGrid(); }
  else if (b.dataset.act === "tool-logo") $("#tf-logo").click();
  else if (b.dataset.act === "tool-run") toolPlan(true).catch((e) => toast(e.message));
  else if (b.dataset.act === "tool-plan") toolPlan(false).catch((e) => toast(e.message));
  else if (b.dataset.tfrm !== undefined) { toolFiles.splice(+b.dataset.tfrm, 1); renderToolFiles(); }
  else if (b.dataset.pack) {
    const p = b.dataset.pack, offer = ((toolHave.packs || {})[p] || {}).offer || "this model";
    confirmBox(`Download ${offer}? It goes into ComfyUI's models folder; restart ComfyUI afterwards. Progress shows in Setup > System check.`, async () => {
      const r = await api("/api/doctor/fix", { action: "download-pack", pack: p, approved: true });
      toast(r.ok ? "Downloading… (Setup > System check shows progress)" : (r.error || "Couldn't start the download"));
    });
  }
});
api("/api/tools").then((r) => { toolCat = toolCat || r; toolHave = r.have || {}; toolBadge(r.status); }).catch(() => {});

/* TOOLS n/m badge: what's ready, hover for what's missing, click for System check. */
let toolStat = {};
function toolBadge(status) {
  if (status) toolStat = Object.fromEntries(status.map((t) => [t.id, t]));
  const b = $("#toolsbadge"); if (!b || !status) return;
  const ok = status.filter((t) => t.ok).length;
  b.textContent = `TOOLS ${ok}/${status.length}`;
  b.classList.toggle("allok", ok === status.length);
  b.classList.toggle("some", ok < status.length);
  b.title = status.map((t) => (t.ok ? "√ " : "× ") + t.name + (t.ok ? "" : " — " + t.why)).join("\n") +
    "\n\nClick: Setup > System check, to install what's missing.";
}
function refreshBadge() { api("/api/tools").then((r) => { toolHave = r.have || toolHave; toolBadge(r.status); }).catch(() => {}); }
setInterval(refreshBadge, 120000);
document.addEventListener("click", (ev) => { if (ev.target.closest && ev.target.closest("#toolsbadge")) show("setup", "system"); });
// Music form: switching between music and sound effects changes which model it needs.
document.addEventListener("change", (ev) => {
  if (toolOpen && ev.target && ev.target.matches && ev.target.matches('#tf-options [data-pick="kind"]')) toolNeeds();
});

// Checklist ticks in the setup helper.
document.addEventListener("change", (ev) => {
  const c = ev.target; if (!c || !c.dataset || !c.dataset.wpick || !W.pick) return;
  W.pick[c.dataset.wpick] = c.checked; wRender();
});
