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
const SCREENS = { F1: "help", F2: "queue", F3: "files", F4: "builder", F6: "talk", F8: "stats", F9: "about", F10: "setup" };
let current = "queue";
function show(name) {
  current = name;
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === "s-" + name));
  $("#title-screen").textContent = name.toUpperCase();
  document.querySelectorAll(".fkeys button").forEach((b) => b.classList.toggle("on", SCREENS[b.dataset.key] === name));
  if (name === "files") loadDir(dirPath, true);
  if (name === "stats") { loadStats(); loadStorage(); }
  if (name === "setup") loadSetup();
  if (name === "report") loadReport();
  if (name === "builder") loadBuilder();
  if (name === "talk") loadTalk(); else if (typeof openMicStop === "function") openMicStop();
}

let toastTimer;
function toast(msg) {
  const t = $("#toast");
  t.textContent = " " + msg + " ";
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), 2600);
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
function applyUI(ui, themeVars) {
  const ph = /^custom:/.test(ui.phosphor) ? "custom" : ui.phosphor;
  document.body.className = `ph-${ph} crt-${ui.crt}`;
  document.documentElement.style.setProperty("--fs", ui.text_size + "px");
  applyTheme(themeVars);
}

let lastLogLen = -1, lastUI = "", lastBusy = "", lastMedia = "", viewing = "", lastFix = -1;
const isVid = (p) => /\.(mp4|webm|mov|mkv|m4v)$/i.test(p);
const playerUrl = (p) => "/player?t=" + encodeURIComponent(TOKEN) + "&path=" + encodeURIComponent(p);
function mediaButtons(p) {
  return `<div class="gbtns"><button type="button" data-window="${esc(p)}">[ BIG WINDOW ]</button>` +
    `<button type="button" data-system="${esc(p)}">[ OPEN IN PLAYER ]</button>` +
    `<button type="button" data-open="${esc(p)}">[ DETAILS F3 ]</button></div>`;
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
function renderGallery(m) {
  if (!m.length) return;
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
async function poll() {
  try {
    state = await api("/api/state");
    fails = 0;
  } catch (e) {
    if (++fails === 3) $("#status").innerHTML = "&nbsp;CONNECTION LOST — close this window and start Joe again";
    return;
  }
  const uiKey = JSON.stringify([state.ui, state.theme]);
  if (uiKey !== lastUI) {
    applyUI(state.ui, state.theme); lastUI = uiKey;
    $("#ver").textContent = "v" + state.version;
    $("#about-ver").textContent = `Joe v${state.version} · GPL-3.0-or-later`;
  }

  // jobs
  const jl = $("#joblist");
  if (state.jobs.length) {
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
  const parts = [
    `OLLAMA ${sv.ollama ? "UP" : "DOWN"}`,
    `COMFYUI ${sv.comfyui ? "UP" : "DOWN"}`,
    `MODEL ${state.model}${loaded ? " " + loaded.gpu_pct + "% GPU" : ""}`,
    state.running ? (state.stopping ? "STOPPING…" : `RUNNING ${done}/${total} ETA ${fmtEta(state.eta_s)}`) : (state.busy ? state.busy.toUpperCase() + (state.busy_pct != null ? " " + Math.round(state.busy_pct) + "%" : "") + "…" : "IDLE"),
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
  if (current === "setup" && state.busy !== lastBusy) { lastBusy = state.busy; if (!state.busy) loadDoctor(); }
  const fr = state.fix_result || {};
  if (fr.n && fr.n !== lastFix) {
    if (lastFix !== -1 && !fr.ok) confirmBox("That setup didn't finish.\n\nThe F2 log says why (it's also saved in\n%LOCALAPPDATA%\\joe-ai\\addons\\install.log).\nCopy the last lines to Claude to get it fixed.\n\nOpen the log now?", () => show("queue"));
    else if (lastFix !== -1 && fr.ok) toast("Setup finished");
    lastFix = fr.n;
  } else if (lastFix === -1) lastFix = fr.n || 0;
  $("#busy") && ($("#busy").textContent = state.busy ? state.busy + (state.busy_pct != null ? ` ${Math.round(state.busy_pct)}%` : "") + "…" : "");
  $("#f5label").textContent = state.running ? "Stop" : "Run";
  $("#btn-run").innerHTML = state.running ? '[ STOP <span class="k">F5</span> ]' : '[ RUN <span class="k">F5</span> ]';
}

/* ---------------- queue actions ---------------- */
async function checkMission() {
  const r = await api("/api/check", { text: $("#mission").value });
  if (!r.ok) { $("#plan").textContent = "ERROR: " + r.error; return null; }
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
  saveTimer = setTimeout(() => api("/api/mission/save", { text: $("#mission").value }), 800);
});

/* ---------------- files ---------------- */
let dirPath = "", entries = [], sel = 0, grid = false, dirAI = false, pendingSelect = "";
function openInFiles(p) {                     // jump to a file in F3 and select it
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

/* ---------------- storage (F8) ---------------- */
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
    (c.count ? `<button type="button" data-clean="${esc(c.kind)}" data-label="${esc(c.label)}" data-count="${c.count}" data-bytes="${c.bytes}">[ CLEAN ]</button>` : "") + "</div>").join("");
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
let doctorData = null;
async function loadDoctor() {
  let d;
  try { d = await api("/api/doctor"); } catch (e) { $("#doctor").textContent = e.message; return null; }
  doctorData = d;
  const g = d.gpu, o = d.ollama, c = d.comfyui;
  const yes = (b) => (b ? "YES" : "no ");
  $("#doctor").textContent =
    `GPU      ${g ? `${g.name}  ${d.vram_gb} GB VRAM` : "no NVIDIA GPU found"}   RAM ${d.ram_gb} GB   winget ${d.winget ? "yes" : "no"}\n` +
    `OLLAMA   installed ${yes(o.installed)} running ${yes(o.running)}  models: ${o.models.map((m) => m.name).join(", ") || "none"}\n` +
    `         best fit installed: ${o.best || "-"}   in use: ${o.configured}\n` +
    `COMFYUI  installed ${yes(c.installed)} running ${yes(c.running)}  ${c.url}\n` +
    `         models: ${c.models.length} (${[...new Set(c.models.map((m) => m.family))].join(", ") || "none"})  best image: ${c.best_image || "-"}  best video: ${c.best_video || "-"}\n` +
    `FFMPEG   ${d.ffmpeg || "not found"}`;
  $("#issues").innerHTML = d.issues.length ? d.issues.map((it, i) =>
    `<div class="issue"><span class="t">${it.optional ? "·" : "!"} ${esc(it.text)}</span><button type="button" data-fix="${i}">[ ${{ install: "INSTALL", start: "START", use: "USE IT", "install-voice": "SET UP", "install-pandoc": "INSTALL", "install-clone": "SET UP" }[it.action] || "DOWNLOAD"} ]</button></div>`).join("")
    : '<div class="dim">All good. Everything Joe needs is installed and running.</div>';
  return d;
}
function askFix(it) {
  const what = { install: "Install it now (winget, Windows may ask for permission)?", start: "Start it now?",
    use: "Switch to this model?", pull: "Download it now?", "download-image-model": "Download it now?",
    "download-video-model": "Download it now? About 18 GB in 3 files; it can take an hour or more.",
    "install-voice": "Set it up now? It downloads about 500 MB and takes a few minutes. Windows may ask for permission.",
    "install-pandoc": "Install it now (winget)?",
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
  loadDoctor();
  try {
    const v = await api("/api/voice/status");
    voiceReady = v.voice; talkMode = v.settings.talk_mode === "push" ? "push" : "open"; pttKey = v.settings.ptt_key || "F6";
    $("#voice-select").innerHTML = Object.entries(v.voices).map(([id, n]) => `<option value="${id}">${esc(n)}</option>`).join("");
  } catch (e) {}
  setTimeout(loadMyVoice, 0);
  await loadThemes().catch(() => {});
  const s = await api("/api/settings");
  document.querySelectorAll("#setup [data-path]").forEach((el) => {
    const v = getPath(s, el.dataset.path);
    if (el.type === "checkbox") el.checked = !!v; else el.value = v ?? "";
  });
  $("#setup-msg").textContent = "";
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
  if (r.ok) { toast("Settings saved"); voiceSettings(); }
}
$("#setup").addEventListener("submit", saveSetup);

/* ---------------- buttons ---------------- */
document.addEventListener("click", async (ev) => {
  const b = ev.target.closest("button"); if (!b) return;
  if (b.dataset.key) { handleKey(b.dataset.key); return; }
  const act = b.dataset.act;
  try {
    if (act === "check") await checkMission();
    if (act === "run") await runOrStop();
    if (act === "report") show("report");
    if (act === "talk-send") await talkSend();
    if (act === "talk-clear") { await api("/api/talk/clear", {}); talkLog = []; renderTalk(); }
    if (act === "hush") hush();
    if (act === "read-report") await say($("#report").textContent.replace(/[|#*`-]{2,}/g, " ").slice(0, 5000), true);
    if (act === "hear-story") await say(storyText(), true);
    if (act === "set-ptt") { settingKey = true; $("#ptt-key").value = "press a key…"; return; }
    if (act === "test-voice") { await saveSetup(); await say("Hi, I'm Joe. Humans can't say my real name, so Joe is fine.", true); }
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
    if (act === "check-update") { $("#setup-msg").textContent = "Checking GitHub…"; await checkUpdate(true); return; }
    if (act === "clear") { $("#mission").value = ""; $("#plan").textContent = ""; api("/api/mission/save", { text: "" }); }
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
    if (act === "make-theme") {
      const desc = $("#theme-desc").value.trim();
      if (!desc) { $("#theme-msg").textContent = "Describe the look first."; return; }
      $("#theme-msg").textContent = "Designing…";
      const r = await api("/api/theme/make", { description: desc });
      if (!r.ok) { $("#theme-msg").textContent = "ERROR: " + r.error; return; }
      applyTheme(r.vars); document.body.className = `ph-custom crt-${r.theme.crt}`;
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
  if (key === "F5") { runOrStop().catch((e) => toast(e.message)); return true; }
  if (key === "Escape") {
    if (document.activeElement && document.activeElement !== document.body) document.activeElement.blur();
    if (current !== "queue") show("queue");
    return true;
  }
  return false;
}
document.addEventListener("keydown", (ev) => {
  if (ev.key === "F6") { ev.preventDefault(); if (!ev.repeat) f6Down(); return; }
  if (!$("#confirm").hidden) {
    ev.preventDefault();
    if (ev.key === "y" || ev.key === "Y" || ev.key === "Enter") confirmClose(true);
    else if (ev.key === "n" || ev.key === "N" || ev.key === "Escape") confirmClose(false);
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
  if (shown || matchMedia("(prefers-reduced-motion: reduce)").matches) { el.remove(); return; }
  el.addEventListener("click", done);
  document.addEventListener("keydown", done, { once: true });
  let i = 0;
  const t = setInterval(() => {
    $("#boot-bin").textContent = bin.slice(0, ++i) + (i < bin.length ? "█" : "");
    if (i >= bin.length) {
      clearInterval(t);
      setTimeout(() => $("#boot-name").classList.add("on"), 250);
      setTimeout(done, 1900);
    }
  }, 55);
}
boot();

/* ---------------- start ---------------- */
function tick() {
  const d = new Date();
  $("#clock").textContent = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
(async () => {
  tick(); setInterval(tick, 10000);
  try { const m = await api("/api/mission"); $("#mission").value = m.text || ""; } catch (e) {}
  await poll();
  setInterval(poll, 1000);
  // First thing on launch: make sure the tools are there. Ask before fixing anything.
  try {
    const d = await loadDoctor();
    const need = d && d.issues.find((it) => !it.optional);
    if (need && !(state && state.running)) askFix(need);
  } catch (e) {}
  await voiceSettings();
  // Fresh start, unless the last run didn't finish.
  try {
    const o = await api("/api/resume");
    if (o.offer) {
      confirmBox(`The last run didn't finish: ${o.tasks} task(s) left` +
        (o.names.length ? `\n  ${o.names.join("\n  ")}` : "") +
        `\n\nY = resume where it stopped    N = start fresh (it stays in F4 > History)`,
        async () => { const r = await api("/api/resume", { action: "resume" }); toast(r.ok ? "Resuming" : r.error); },
        async () => { await api("/api/resume", { action: "fresh" }); });
    }
  } catch (e) {}
})();

/* ---------------- builder (F4): missions without typing keys ---------------- */
const KINDS = { list: "List of items", doc: "Document (sections)", sheet: "Spreadsheet (CSV)", image: "Pictures", video: "Video clips" };
const SIZES = [["", "model default"], ["1024x1024", "1024 × 1024 square"], ["1216x832", "1216 × 832 landscape"],
  ["832x1216", "832 × 1216 portrait"], ["1344x768", "1344 × 768 wide"], ["512x512", "512 × 512 (SD 1.5)"]];
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
function renderTasks() {
  $("#b-tasks").innerHTML = B.tasks.map((t, i) => {
    const k = t._kind, n = (t.part_prompts || []).filter((x) => x.trim()).length;
    const size = k === "doc" ? `${n} sections` : (k === "image" || k === "video") && n ? `${n} briefs × ${t.variants}` :
      `${t.parts} × ${t.part_size}${k === "image" ? " × " + t.variants : ""}`;
    return `<div class="btask${i === B.sel ? " sel" : ""}" data-i="${i}"><span class="n">${i + 1}.</span><span class="t">[${k}] ${esc(t.name)} → ${esc(t.save || "?")}</span><span>${size}</span></div>`;
  }).join("") || '<div class="dim">No tasks yet. Press + ADD or import a mission.</div>';
}
function field(label, html, hint) { return `<label>${label} ${html}</label>${hint ? `<div class="hint">${hint}</div>` : ""}`; }
function renderForm() {
  const t = B.tasks[B.sel], f = $("#b-form");
  if (!t) { f.innerHTML = '<div class="dim">Add a task to start.</div>'; return; }
  const k = t._kind, media = k === "image" || k === "video";
  const v = (x) => esc(x ?? "");
  const lines = (t.part_prompts || []).join("\n");
  let h = field("Name", `<input data-f="name" value="${v(t.name)}">`);
  h += field("Kind", `<select data-f="_kind">${Object.entries(KINDS).map(([a, b]) => `<option value="${a}"${a === k ? " selected" : ""}>${b}</option>`).join("")}</select>`);
  h += field("Save to", `<input data-f="save" value="${v(t.save)}" placeholder="blank = Joe picks (project / task name)">`,
    "Optional. Leave it blank and Joe saves to Output/project/task name. He never overwrites: a second run saves a _v2.");
  h += field("Project", `<input data-f="project" list="dl-projects" value="${v(t.project)}" placeholder="same as the mission">`);
  if (k === "doc") {
    h += field("Sections", `<textarea data-f="part_prompts" rows="5" placeholder="## Overview. Goals and how it works.\n## Details. Tables with example rows.">${v(lines)}</textarea>`,
      "One section per line. Joe writes them in this order and keeps his text as written.");
  } else {
    h += field(media ? "How many" : "How much", `<span class="inline"><input type="number" min="1" max="500" data-f="parts" value="${t.parts}"> parts of <input type="number" min="1" max="50" data-f="part_size" value="${t.part_size}"> ${media ? "prompts" : k === "sheet" ? "rows" : "items"}</span>`,
      `= ${t.parts * t.part_size} ${media ? `prompt(s) Joe writes himself` : k === "sheet" ? "rows" : "items"}. Small parts keep the model sharp.`);
  }
  if (media) {
    h += field("Or your own briefs", `<textarea data-f="part_prompts" rows="3" placeholder="optional, one picture per line">${v(lines)}</textarea>`,
      "If you list briefs, Joe uses these instead of the count above.");
    h += field("Use briefs as written", `<input type="checkbox" data-f="prompts_as_written"${t.prompts_as_written ? " checked" : ""}>`, "Off = Joe turns each brief into a detailed prompt first.");
  }
  if (k === "sheet") h += field("Columns", `<input data-f="header" value="${v(t.header)}" placeholder="SKU,Name,Description,Price">`, "Column names, separated by commas. Joe checks every row.");
  if (k === "list" || k === "doc") h += field("Finished copies", `<span class="checks">${["docx", "pdf", "epub"].map((x) => `<label class="inline"><input type="checkbox" data-ex="${x}"${(t.export || []).includes(x) ? " checked" : ""}> ${{ docx: "Word", pdf: "PDF", epub: "EPUB (e-book)" }[x]}</label>`).join("")}</span>`, "Made from the finished file with Pandoc (F10 > System check installs it).");
  if (k === "list" || k === "doc") h += field("Min words each", `<input type="number" min="0" max="2000" data-f="min_words" value="${t.min_words}">`, "0 = no minimum. Short items get expanded.");
  h += field(media ? "Style / brief" : "Format", `<textarea data-f="format" rows="3" placeholder="${media ? "Soft morning light, linen, muted earth tones, no people." : "One paragraph about look, feel and use. End with a care tip."}">${v(t.format)}</textarea>`);
  h += field("Task rules", `<textarea data-f="rules" rows="2" placeholder="optional, just for this task">${v(t.rules)}</textarea>`);
  if (B.lists.inbox.length) h += field("Reference files", `<span class="checks">${B.lists.inbox.map((n) => `<label class="inline"><input type="checkbox" data-in="${esc(n)}"${(t.inputs || []).includes(n) ? " checked" : ""}> ${esc(n)}</label>`).join("")}</span>`, "From your Inbox folder. Joe uses them as facts.");
  if (media) {
    h += field("Model", `<input data-f="model" list="dl-models" value="${v(t.model)}" placeholder="best fit for your GPU">`);
    const sz = t.width && t.height ? `${t.width}x${t.height}` : "";
    h += field("Size", `<select data-f="_size">${SIZES.map(([a, b]) => `<option value="${a}"${a === sz ? " selected" : ""}>${b}</option>`).join("")}${sz && !SIZES.some(([a]) => a === sz) ? `<option value="${sz}" selected>${sz}</option>` : ""}</select>`);
    h += field("Versions of each", `<input type="number" min="1" max="16" data-f="variants" value="${t.variants}">`);
    h += field("Avoid", `<input data-f="negative" value="${v(t.negative)}" placeholder="e.g. text, watermark, blurry">`);
    h += field("Workflow", `<select data-f="workflow"><option value="">${k === "video" ? "(pick one — video needs a workflow)" : "built-in text-to-image"}</option>${B.lists.workflows.map((w) => `<option${w === t.workflow ? " selected" : ""}>${esc(w)}</option>`).join("")}</select>`,
      "Workflows are ComfyUI files in your Workflows folder (ComfyUI: Workflow > Export (API)).");
    h += field("Seed", `<input data-f="seed" value="${v(t.seed)}">`, "random, or a number to repeat a run exactly.");
    if (k === "video") h += field("Frames per second", `<input type="number" min="1" max="60" data-f="fps" value="${t.fps}">`);
  } else {
    h += field("Model", `<input data-f="model" value="${v(t.model)}" placeholder="the Setup default">`);
  }
  f.innerHTML = h;
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
  if (key === "part_prompts") { t.part_prompts = val.split("\n").map((x) => x.trim()).filter(Boolean); return; }
  if (key === "_size") { const [w, h2] = (val || "0x0").split("x").map(Number); t.width = w || 0; t.height = h2 || 0; return; }
  t[key] = val;
  if (key === "_kind") {
    t.type = val === "image" || val === "video" ? val : "text";
    if (val === "sheet" && t.save && !/\.csv$/i.test(t.save)) t.save = t.save.replace(/\.\w+$/, "") + ".csv";
    if (val !== "sheet") t.header = val === "sheet" ? t.header : "";
    if (val !== "doc" && val !== "image" && val !== "video") t.part_prompts = [];
    renderForm();
  }
}
$("#b-form").addEventListener("input", (ev) => {
  const t = B.tasks[B.sel]; if (!t) return;
  readField(t, ev.target); renderTasks(); scheduleBuild();
});
$("#b-form").addEventListener("change", (ev) => {
  if (ev.target.tagName === "SELECT" || ev.target.type === "checkbox") { const t = B.tasks[B.sel]; if (t) { readField(t, ev.target); renderTasks(); scheduleBuild(); } }
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
  if (!tasks.length) { $("#b-out").textContent = ""; $("#b-status").textContent = ""; built = { ok: false, text: "" }; return built; }
  const r = await api("/api/mission/build", { project: B.project, rules: B.rules, tasks });
  built = r;
  $("#b-out").textContent = r.text;
  $("#b-status").textContent = r.ok ? `— looks good · about ${r.check.eta_min} min` + (r.check.warnings && r.check.warnings.length ? " · " + r.check.warnings.join(" ") : "") : "— ERROR: " + r.error;
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
    `<div class="h"><span class="dim">${esc(m.when)}</span><span class="t">${esc(m.label)}</span><span class="dim">${m.done}/${m.tasks} done</span><button data-hload="${esc(m.file)}">[ LOAD ]</button><button data-hrun="${esc(m.file)}">[ RUN ]</button></div>`).join("")
    : '<div class="dim small">Missions you run show up here.</div>';
}
document.addEventListener("keydown", (ev) => {
  if (current !== "builder" || !$("#confirm").hidden) return;
  if (/^(TEXTAREA|INPUT|SELECT)$/.test(ev.target.tagName)) return;
  if (ev.key === "ArrowDown" && B.sel < B.tasks.length - 1) { B.sel++; renderTasks(); renderForm(); ev.preventDefault(); }
  if (ev.key === "ArrowUp" && B.sel > 0) { B.sel--; renderTasks(); renderForm(); ev.preventDefault(); }
});

/* ---------------- talk + voice (F6) ---------------- */
let speakReplies = true;
let voiceReady = false, talkLog = [], audioEl = null, rec = null, recStart = 0, f6Timer = null;
async function loadTalk() {
  api("/api/talk/warm", {}).catch(() => {});      // load the thinking + voice models now, not on the first question
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
    talkMode = v.settings.talk_mode === "push" ? "push" : "open"; pttKey = v.settings.ptt_key || "F6";
  } catch (e) {}
}
function renderTalk() {
  $("#talk-log").innerHTML = talkLog.length ? talkLog.map((m, i) => `<div class="msg ${m.who}"><span class="who">${m.who === "joe" ? "JOE>" : "YOU>"}</span>${esc(m.text)}` +
    (m.mission ? `<pre class="mission">${esc(m.mission)}</pre><button data-tmission="${i}">[ OPEN IN BUILDER ]</button> <button data-trun="${i}">[ RUN IT ]</button>` : "") + `</div>`).join("")
    : '<div class="dim">Joe: "What can I help you with?"</div>';
  const lg = $("#talk-log"); lg.scrollTop = lg.scrollHeight;
}
// Joe's reply streams in a few words at a time; each finished sentence goes straight to his
// voice, so he starts talking while he's still thinking up the rest.
const cleanSpeech = (t) => t.replace(/```[\s\S]*?```/g, " ").replace(/[*_#`>|]+/g, "").replace(/^\s*[-•]\s+/gm, "").replace(/\s+/g, " ").trim();
async function talkSend(textArg) {
  const text = (textArg ?? $("#talk-in").value).trim();
  const sent = (typeof talkFiles !== "undefined") ? talkFiles.filter((f) => !f.busy) : [];
  if (!text && !sent.length) return;
  $("#talk-in").value = "";
  if (sent.length) { talkFiles = talkFiles.filter((f) => f.busy); renderFiles(); }
  talkLog.push({ who: "you", text: (text || "(file)") + sent.map((f) => `  📎 ${f.name}`).join("") });
  const msg = { who: "joe", text: "…" };
  talkLog.push(msg);
  renderTalk();
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
    const res = await fetch("/api/talk/stream", { method: "POST", headers: { "X-NR-Token": TOKEN, "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
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
        } else if (ev.t === "done") final = ev;
      }
    }
  } catch (e) { final = { ok: false, error: e.message }; }
  if (!final) final = { ok: false, error: "Joe stopped talking unexpectedly" };
  if (final.ok) {
    if (!raw) raw = final.say;                  // read-aloud / status replies come in one piece
    feed(true);
    msg.text = final.say; msg.mission = final.mission;
  } else msg.text = "(" + final.error + ")";
  renderTalk();
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
let talkMode = "open", pttKey = "F6", micMuted = false, micStream = null, micCtx = null, micLoop = null;
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
function f6Down() { show("talk"); }                 // F6 opens Talk (open mic starts there)
$("#ptt").addEventListener("mousedown", (ev) => {
  ev.preventDefault();
  if (!voiceReady) { show("setup"); toast("Press SET UP next to \"Joe's voice\" in the System check"); return; }
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
  if (files.length) attachFiles(files);
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
  confirmBox(`Joe ${r.latest} is out. You have ${r.current}.\n\n${r.notes ? r.notes.slice(0, 600) + "\n\n" : ""}Open the download page?`,
    () => window.open(r.url, "_blank", "noopener"));
}
setTimeout(() => checkUpdate(false), 8000);
