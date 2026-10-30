"use strict";
/* Woot's review app: shared core. Helpers ($, el, esc), App.api / toast / store, the video key (which video the tabs show),
   the render-job chip + console, and the tab switcher. Each tab lives in its own file and loads after this one. */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") e.className = v;
    else if (k === "text") e.textContent = v;
    else if (k === "html") e.innerHTML = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (k === "style" && typeof v === "object") Object.assign(e.style, v);
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids.flat()) if (k != null) e.append(k.nodeType ? k : document.createTextNode(k));
  return e;
}
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const base = p => String(p || "").split(/[\\/]/).pop();
const stem = p => base(p).replace(/\.[^.]+$/, "");

const App = window.App = {};

/* ------------------------------------------------------------------ utils */
async function api(path, body) {
  const r = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" },
                                       body: JSON.stringify(body) } : { cache: "no-store" });
  let j;
  try { j = await r.json(); } catch { throw new Error(`${r.status} ${r.statusText}`); }
  if (!r.ok || (j && j.error)) throw new Error((j && j.error) || r.statusText);
  return j;
}
App.api = api;

let toastTimer;
function toast(msg, err = false, ms = 3200) {
  const t = $("#toast");
  t.textContent = msg; t.className = err ? "err" : ""; t.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => (t.hidden = true), ms);
}
App.toast = toast;
/* the app runs the code it had when it started: say so when the files on disk are newer, so a rebuild is never made with old code */
(() => {
  const bar = document.createElement("div");
  bar.id = "codeStale"; bar.hidden = true;
  bar.textContent = "The app was updated after it started. Close the console window, run start.bat, then press Ctrl+F5: until you do, builds use the OLD code and some changes will be ignored.";
  document.addEventListener("DOMContentLoaded", () => document.body.prepend(bar));
  let boot = null, stat = null, pending = false;
  const typing = () => { const a = document.activeElement; return a && /^(INPUT|TEXTAREA)$/.test(a.tagName) && a.value; };
  const playing = () => [...document.querySelectorAll("video")].some(v => !v.paused && !v.ended);
  const check = async () => {
    try {
      const r = await fetch("/api/code", { cache: "no-store" }).then(x => x.json());
      if (boot === null) { boot = r.boot; stat = r.static; }
      bar.hidden = !(r.stale && !r.supervised);                               // under the supervisor the app restarts itself: no banner
      if (r.boot !== boot || r.static !== stat) {                             // a new server, or newer page files: load them (not while he is typing or watching)
        if (typing() || playing()) { if (!pending) { pending = true; App.toast("The app was updated: it will reload when you stop typing or playing", false, 6000); } return; }
        location.reload();
      }
    } catch { /* the server is restarting: try again */ }
  };
  setTimeout(check, 1500); setInterval(check, 3000); window.addEventListener("focus", check);
})();

function fmtT(t, dec = 2) {
  if (t == null || isNaN(t)) return "–";
  const neg = t < 0; t = Math.abs(t);
  const m = Math.floor(t / 60), s = t - m * 60;
  return (neg ? "-" : "") + `${m}:${s.toFixed(dec).padStart(dec ? 3 + dec : 2, "0")}`;
}
App.fmtT = fmtT;

const store = {
  get(k, d) { try { const v = localStorage.getItem("wr." + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("wr." + k, JSON.stringify(v)); } catch { /* private mode */ } },
};
App.store = store;

/* Every video player in the app remembers the volume (and mute) you last set: the setting is saved when it changes and put back whenever a player loads something. */
{
  let applying = false;
  const apply = v => {
    const vol = store.get("volume", null), muted = store.get("muted", null);
    if (vol == null && muted == null) return;
    applying = true;
    if (vol != null && v.volume !== vol) v.volume = vol;
    if (muted != null && v.muted !== muted) v.muted = muted;
    applying = false;
  };
  document.addEventListener("volumechange", e => {
    if (applying || !(e.target instanceof HTMLVideoElement)) return;
    store.set("volume", e.target.volume); store.set("muted", e.target.muted);
  }, true);
  for (const ev of ["loadstart", "loadedmetadata", "play"])
    document.addEventListener(ev, e => { if (e.target instanceof HTMLVideoElement) apply(e.target); }, true);
  document.querySelectorAll("video").forEach(apply);
}

/* The video being worked on. The address bar says which (?wv=<work> or ?wv=<work>|<name>), so two browser tabs can show two videos;
   without it the last video used is opened. Every tab asks App.videoKey() and tells App.setVideoKey() when the choice changes. */
App.videoKey = () => {
  try {
    const wv = new URLSearchParams(location.search).get("wv");
    if (wv) { const [work, name] = wv.split("|"); return JSON.stringify([work, name || work]); }
  } catch { /* fall back to the stored choice */ }
  return store.get("wfVideo");
};
App.setVideoKey = json => {
  store.set("wfVideo", json);
  try {
    const [work, name] = JSON.parse(json);
    const u = new URL(location.href);
    u.searchParams.set("wv", name === work ? work : `${work}|${name}`);
    history.replaceState(null, "", u);
  } catch { /* the address is a convenience */ }
};

function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text).then(() => toast("Copied"));
  const ta = el("textarea", { style: { position: "fixed", opacity: 0 } }); ta.value = text;
  document.body.append(ta); ta.select();
  try { document.execCommand("copy"); toast("Copied"); } catch { toast("Copy failed: select the text by hand", true); }
  ta.remove();
}
App.copyText = copyText;

const KIND_NAME = { shorts: "Shorts job", rough: "Preview re-render", final: "Final render", remix: "Sound rebuild", bookend: "Intro/outro", analyze: "Analyzing takes",
                    clipmap: "Matching takes to the script", storyboard: "Drawing the storyboard", selfreview: "Self-review", final: "Final render" };

/* A small status chip in the top bar; its details (steps + full log) live in a console drawer that
   opens and closes from the chip and stays out of the way otherwise. */
const consoleOpen = () => store.get("consoleOpen", false);
function setConsole(open) { store.set("consoleOpen", open); $("#console").hidden = !open || !(App.runningJob || App.lastJob); }
$("#conClose").onclick = () => setConsole(false);
$("#jobChip").addEventListener("click", e => { if (e.target.closest("button")) return; setConsole($("#console").hidden); });

function drawJob(j) {
  const secs = Math.round(j.elapsed ?? (Date.now() / 1000 - j.started));
  const clock = `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, "0")}`;
  const name = KIND_NAME[j.pipeline] || "Render";
  const copyErr = () => copyText(`The review app's ${name} failed for ${App.videoKey() || "(no video chosen)"}. Last log lines:\n` +
                                 `${j.log.trim().split("\n").slice(-30).join("\n")}\nPlease fix it.`);
  // chip
  const chip = $("#jobChip"); chip.hidden = false; chip.innerHTML = "";
  chip.className = j.done ? (j.ok ? "ok" : "bad") : "run";
  chip.title = $("#console").hidden ? "Show details" : "Hide details";
  chip.append(el("span", { class: "ic" }, j.done ? (j.ok ? "✓" : "✗") : "⟳"),
              el("span", { class: "lbl" }, j.done ? `${name} ${j.ok ? "done" : "failed"} · ${clock}`
                                                  : `${name} · ${clock}${j.steps.length > 1 ? ` · step ${j.step + 1}/${j.steps.length}` : ""}`));
  if (j.done && !j.ok) chip.append(el("button", { class: "ghost", onclick: copyErr }, "Copy error for Claude"));
  if (j.done) chip.append(el("button", { class: "x", title: "Dismiss", onclick: () => {
    App.lastJob = null; chip.hidden = true; $("#console").hidden = true; } }, "✕"));
  // console
  $("#conTitle").textContent = `${name}${j.done ? (j.ok ? `: done in ${clock}` : ": failed") : `: running ${clock}`}`;
  $("#conSteps").innerHTML = "";
  $("#conSteps").append(...j.steps.map((s, i) => {
    const st = j.done ? (j.ok || i < j.step ? "ok" : i === j.step ? "bad" : "") : i < j.step ? "ok" : i === j.step ? "now" : "";
    return el("div", { class: "st " + st }, `${{ ok: "✓", bad: "✗", now: "▶" }[st] || "·"} ${s}`);
  }));
  const acts = $("#conActs"); acts.innerHTML = "";
  if (j.pipeline === "rough" && j.ok) acts.append(el("span", { class: "muted small" }, "Check the double-cut report (both checks should say 0)  "));
  acts.append(el("button", { class: "ghost", onclick: () => copyText(j.log) }, "Copy log"));
  const pre = $("#conLog"), atEnd = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 20;
  pre.textContent = j.log.trim();
  if (atEnd) pre.scrollTop = pre.scrollHeight;              // follow the log unless the creator scrolled up to read
  $("#console").hidden = !consoleOpen();
  // A failure opens the console once so the reason isn't missed.
  if (j.done && !j.ok && !j._shown) { j._shown = true; setConsole(true); }
}

/* Follow a render the server runs: draw the chip and console, and tell the tab that asked for it when it is done. */
function watchJob(job) {
  App.runningJob = job; App.lastJob = null;
  const poll = async () => {
    let j;
    try { j = await api(`/api/jobs/${job.id}`); } catch { return setTimeout(poll, 3000); }
    drawJob(j);
    if (!j.done) return setTimeout(poll, 1500);
    App.runningJob = null; App.lastJob = j;
    toast(j.ok ? `${KIND_NAME[j.pipeline]} finished` : `${KIND_NAME[j.pipeline]} failed: see the log`, !j.ok, 8000);
    if (["analyze", "clipmap"].includes(j.pipeline) && App.clipsReload) await App.clipsReload();
    if (j.pipeline === "selfreview" && App.selfreviewReload) await App.selfreviewReload();
    if (j.pipeline === "final" && App.finalReload) await App.finalReload();
    if (j.pipeline === "storyboard" && App.storyboardReload) await App.storyboardReload();
    drawJob(j);
  };
  poll();
}
App.watchJob = watchJob;
// A render keeps running on the server if the page is reloaded (or opened on the phone): pick it up.
api("/api/jobs").then(js => { const r = js.find(j => !j.done); if (r) watchJob(r); }).catch(() => { /* older server */ });

/* ------------------------------------------------------------------ tabs */
const VIEWS = ["workflow", "script", "shootplan", "clips", "beatmap", "storyboard", "graphics", "build", "final", "shorts"];
function setView(v) {
  document.body.dataset.view = v;
  $$("#views button").forEach(b => b.classList.toggle("on", b.dataset.view === v));
  store.set("view", v);
  try { const u = new URL(location.href); u.searchParams.set("tab", v); history.replaceState(null, "", u); } catch { /* the address is a convenience */ }
  $$("video").forEach(x => x.pause());
  window.dispatchEvent(new CustomEvent("viewchange", { detail: v }));
}
App.setView = setView;
$$("#views button").forEach(b => (b.onclick = () => setView(b.dataset.view)));

/* Tabs that moved or were removed: a remembered view from an older layout opens the tab that took its place. */
const MOVED = { selfreview: "build", footage: "clips", review: "workflow", paper: "workflow", gfx: "graphics" };
{
  const v0 = new URLSearchParams(location.search).get("tab") || store.get("view", "workflow");     // the address wins, so a bookmarked link opens the same tab and video
  const v = MOVED[v0] || v0;
  setView(VIEWS.includes(v) ? v : "workflow");
}
