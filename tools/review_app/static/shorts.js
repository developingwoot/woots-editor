"use strict";
/* Shorts tab: vertical YouTube Shorts from a finished video. Claude (or the creator, by time) proposes shorts; each one shows its hook, the
   source ranges, a vertical preview and the pieces it is cut into. Per piece the creator can click the frame to re-centre the crop, change the
   zoom or the fit, and fix a caption word. Nothing here costs tokens except "Ask Claude for shorts" (one short headless run).
   Logic and file formats: tools/shortsapp.py (state and edits) and tools/shorts.py (the render). Everything is stored in <name>.shorts.json. */
(() => {
  const S = { key: null, d: null, loading: false, open: null, plans: {}, job: null, videos: null, view: {} };
  const visible = () => document.body.dataset.view === "shorts";
  const q = () => `work=${encodeURIComponent(S.key.work)}&name=${encodeURIComponent(S.key.name)}`;
  const post = (op, body) => App.api(`/api/shorts/${op}`, { ...S.key, ...body });
  const mmss = s => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`;
  const fmtRanges = rs => rs.map(r => `${r[0]}-${r[1]}`).join(", ");
  const parseRanges = t => String(t).split(/[,;]+/).map(x => x.trim()).filter(Boolean).map(x => {
    const m = x.match(/^(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)$/);
    if (!m) throw new Error(`"${x}" is not a range like 20.6-40.7`);
    return [+m[1], +m[2]];
  });
  const STATUS = { proposed: "proposed", approved: "approved", rejected: "rejected" };

  /* ---------------------------------------------------------------- loading */
  async function loadList(pick) {
    const list = await App.api("/api/shorts/list");
    const sel = $("#shPick"); sel.innerHTML = "";
    for (const p of list) sel.append(el("option", { value: JSON.stringify([p.work, p.name]) }, `${p.name} · ${p.shorts} short${p.shorts !== 1 ? "s" : ""}${p.approved ? `, ${p.approved} approved` : ""}`));
    $("#shEmpty").hidden = list.length > 0; $("#shBody").hidden = !list.length; sel.hidden = !list.length;
    for (const id of ["shFind", "shTightAll", "shTitles", "shFinish", "shAdd", "shRefresh"]) $("#" + id).hidden = !list.length;
    if (!list.length) { S.key = null; return; }
    const want = pick ? JSON.stringify([pick.work, pick.name]) : (S.key ? JSON.stringify([S.key.work, S.key.name]) : null);
    if (want && [...sel.options].some(o => o.value === want)) sel.value = want;
    const [work, name] = JSON.parse(sel.value);
    S.key = { work, name };
    await reload();
  }
  async function reload() {
    if (!S.key || S.loading) return;
    S.loading = true;
    try { S.d = await App.api(`/api/shorts?${q()}`); render(); }
    catch (e) { App.toast(e.message, true, 8000); }
    S.loading = false;
  }
  async function act(op, body, msg) {
    try { S.d = await post(op, body); if (body && body.id) delete S.plans[body.id]; render(); if (body && body.id && S.open === body.id) loadPlan(body.id); if (msg) App.toast(msg); return true; }
    catch (e) { App.toast(e.message, true, 9000); return false; }
  }
  async function loadPlan(id, force) {
    if (S.plans[id] && !force) return S.plans[id];
    S.plans[id] = { loading: true }; renderCard(id);
    try { S.plans[id] = await App.api(`/api/shorts/plan?${q()}&id=${id}`); }
    catch (e) { S.plans[id] = { error: e.message }; }
    renderCard(id);
    return S.plans[id];
  }

  /* ---------------------------------------------------------------- jobs (render, Claude, new project) */
  async function runJob(startFn, label, after) {
    let job;
    try { job = await startFn(); } catch (e) { return App.toast(e.message, true, 9000); }
    S.job = { id: job.id, label, steps: job.steps, step: 0, log: "", done: false };
    renderJob();
    const poll = async () => {
      let j;
      try { j = await App.api(`/api/jobs/${job.id}`); } catch { return setTimeout(poll, 2500); }
      S.job = { ...S.job, step: j.step, log: j.log, done: j.done, ok: j.ok, elapsed: j.elapsed };
      renderJob();
      if (!j.done) return setTimeout(poll, 1500);
      App.toast(j.ok ? `${label}: done` : `${label}: failed (see the log)`, !j.ok, 7000);
      if (after) await after(j);
    };
    poll();
  }
  function renderJob() {
    const box = $("#shJob"), j = S.job;
    box.hidden = !j; if (!j) return;
    box.innerHTML = "";
    box.append(el("div", { class: "row" },
      el("b", {}, j.done ? (j.ok ? "✓ " : "✗ ") + j.label : "⟳ " + j.label),
      el("span", { class: "muted small" }, j.done ? `${j.elapsed || ""} s` : (j.steps[Math.min(j.step, j.steps.length - 1)] || "")),
      el("span", { class: "spacer" }), j.done ? el("button", { class: "ghost", onclick: () => { S.job = null; renderJob(); } }, "Close") : null));
    if (j.log) box.append(el("details", { open: j.done && !j.ok }, el("summary", { class: "muted small" }, "Details"), el("pre", { class: "log" }, j.log)));
  }

  /* ---------------------------------------------------------------- the cards */
  function render() {
    const d = S.d; if (!d) return;
    $("#shInfo").textContent = `${d.source ? d.source.split(/[\\/]/).pop() : ""} · caption font: ${d.font}${d.has_speakers ? "" : " · speakers not detected"}${d.faces ? " · faces: MediaPipe" : " · face finder missing (crops are rougher)"}`;
    if (d.last_find) $("#shInfo").textContent += ` · last request: asked ${d.last_find.asked || "the recommended number"}, added ${d.last_find.added}${d.last_find.skipped.length ? `, left out ${d.last_find.skipped.length} (${d.last_find.skipped[0]})` : ""}`;
    if (document.activeElement !== $("#shLink")) $("#shLink").value = d.full_video_url || "";
    const box = $("#shList"); box.innerHTML = "";
    if (!d.shorts.length) box.append(el("div", { class: "card muted small" }, "No shorts yet. “✦ Ask Claude for shorts” reads the transcript and proposes 6 to 10 (one short Claude run); “+ Add a short by time” adds one from a start and end you type."));
    for (const s of d.shorts) box.append(el("div", { class: "card shCard", id: `sh_${s.id}` }));
    for (const s of d.shorts) renderCard(s.id);
  }

  function renderCard(id) {
    const host = $(`#sh_${id}`); const s = S.d && S.d.shorts.find(x => x.id === id);
    if (!host || !s) return;
    host.innerHTML = ""; host.dataset.status = s.status;
    const r = s.render, open = S.open === id;
    const len = r.exists && r.dur ? `${r.dur.toFixed(0)} s` : `~${s.estimate.toFixed(0)} s of speech`;
    host.append(el("div", { class: "row" },
      el("span", { class: `chip shSt ${s.status}` }, STATUS[s.status]),
      el("b", { class: "shTitle" }, s.id.toUpperCase() + "  " + s.title),
      el("span", { class: "muted small" }, len),
      el("span", { class: `chip ${r.exists && !r.stale ? "restored" : "pend"}`, title: "Quick half-size preview, for checking while you edit" }, r.exists ? (r.stale ? "preview out of date" : "preview ok") : "no preview"),
      s.status === "approved" || r.final.exists ? el("span", { class: `chip ${r.final.exists && !r.final.stale ? "restored" : "pend"}`, title: "1080x1920 at the best quality setting; made when you press Finish approved" }, r.final.exists ? (r.final.stale ? "final out of date" : "final ✓") : "no final yet") : null,
      s.delivered && s.delivered.file ? el("span", { class: "chip restored", title: s.delivered.file }, "saved in the video's folder") : null,
      el("span", { class: "spacer" }),
      el("button", { class: "ghost", onclick: () => { S.open = open ? null : id; if (!open) loadPlan(id); renderCard(id); } }, open ? "▲ Close" : "▼ Open"),
    ));
    if (s.why) host.append(el("div", { class: "muted small shWhy" }, s.why));
    if (s.thought && s.thought.point) host.append(el("div", { class: "small shWhy" }, el("b", {}, "Story: "), `${s.thought.setup} → ${s.thought.point} → ${s.thought.payoff}`));
    if (s.visual) host.append(el("div", { class: "muted small shWhy" }, "On screen: " + s.visual));
    if (!open) { host.append(el("div", { class: "shHook" }, (s.hook || "").replace(/\|/g, "  /  "))); return; }

    const f = (label, value, onSave, hint) => {
      const inp = el("input", { type: "text", value, title: hint || "", class: "shIn" });
      inp.addEventListener("change", () => onSave(inp.value));
      return el("label", { class: "shField" }, el("span", { class: "muted small" }, label), inp);
    };
    const paceSel = el("select", { class: "shIn" }, Object.entries(S.d.paces).map(([k, l]) => el("option", { value: k, selected: k === s.pace }, l)));
    paceSel.addEventListener("change", () => act("edit", { id, pace: paceSel.value }, "Pace changed: re-render to see it"));
    host.append(el("div", { class: "shEdit" },
      el("label", { class: "shField" }, el("span", { class: "muted small" }, "Pace of the cuts"), paceSel),
      f("Title (for you)", s.title, v => act("edit", { id, title: v })),
      f("Hook shown on screen (| = new line)", s.hook, v => act("edit", { id, hook: v }), "First 2.8 s, uppercase"),
      f("Source ranges, seconds (played in this order)", fmtRanges(s.ranges), v => { try { act("edit", { id, ranges: parseRanges(v) }); } catch (e) { App.toast(e.message, true, 7000); } }, "e.g. 20.6-40.7, 58.2-71.9"),
      f("Cut out of the ranges", fmtRanges(s.drop), v => { try { act("edit", { id, drop: parseRanges(v) }); } catch (e) { App.toast(e.message, true, 7000); } }, "e.g. 24.4-25.0 (leave empty for none)")));
    host.append(gfxBox(id, s));
    host.append(publishBox(id, s));
    const player = el("div", { class: "shPlayer" });
    const showFinal = S.view[id] === "final" && r.final.exists, rr = showFinal ? r.final : r;
    if (r.exists && r.final.exists) player.append(el("div", { class: "chips" },
      el("button", { class: showFinal ? "" : "on", onclick: () => { S.view[id] = "preview"; renderCard(id); } }, "Preview"),
      el("button", { class: showFinal ? "on" : "", onclick: () => { S.view[id] = "final"; renderCard(id); } }, "Final")));
    if (rr.exists) player.append(el("video", { controls: true, playsinline: true, src: `/shortmedia/${encodeURIComponent(S.key.work)}/${encodeURIComponent(rr.file)}?t=${rr.mtime}` }));
    else player.append(el("div", { class: "muted small shNoVid" }, "No preview yet. A few seconds."));
    const acts = el("div", { class: "row" },
      el("button", { class: "accent", title: "Quick half-size preview. The final-quality render is made for approved shorts by Finish approved.", onclick: () => runJob(() => post("render", { id }), `Preview ${id.toUpperCase()}`, async () => { await reload(); }) }, r.exists ? (r.stale ? "↻ Update preview" : "↻ Preview again") : "▶ Preview (quick)"),
      el("button", { class: s.status === "approved" ? "" : "ghost", onclick: async () => { const approving = s.status !== "approved"; const ok = await act("edit", { id, status: approving ? "approved" : "proposed" }); if (ok && approving && !s.gfx) planGfx(id); } }, s.status === "approved" ? "✓ Approved (click to undo)" : "✓ Approve"),
      el("button", { class: "ghost", onclick: () => act("edit", { id, status: s.status === "rejected" ? "proposed" : "rejected" }) }, s.status === "rejected" ? "Un-reject" : "✕ Reject"),
      el("button", { class: "ghost", title: "Whole short as one fitted picture (use for shots with burned-in overlays)", onclick: () => act("edit", { id, layout_all: s.layout_all ? "" : "blur" }) }, s.layout_all ? "Fit: whole frame (on)" : "Fit whole frame"),
      el("button", { class: "ghost", title: "Claude cuts filler, tangents and repeats out of this short (one short run, a few cents); you can click any word afterwards to cut or restore it", onclick: () => tighten([id]) }, s.tightened ? "✂ Tighten again" : "✂ Tighten with Claude"),
      s.tightened ? el("button", { class: "ghost", onclick: () => act("untighten", { id }, "Back to the selection before the tighten") }, "↶ Undo tighten") : null,
      el("span", { class: "spacer" }),
      el("button", { class: "ghost", onclick: () => { if (confirm(`Delete ${id.toUpperCase()} and its rendered file?`)) act("delete", { id }); } }, "Delete"));
    host.append(el("div", { class: "shMain" }, player, el("div", { class: "shSide" }, acts,
      s.tighten_note ? el("div", { class: "shNote small" }, el("b", {}, "Claude's cuts: "), s.tighten_note) : null,
      wordsPanel(id, s), pieces(id, s))));
  }

  /* ---------------------------------------------------------------- graphics plan of an approved short (ADR 0006 phase 2) */
  const GFX = {};                                              // id -> the strip data from /api/shorts/gfx
  const LOOK = { brand: "plain brand card", depth: "3D depth", sticker: "comic sticker", ui: "UI explainer", kinetic: "kinetic type", "": "no look chosen" };
  const gfxUrl = (path, extra) => `/api/shorts/${path}?${q()}&${extra}`;
  async function loadGfx(id, force) {
    if (GFX[id] && !force) return;
    GFX[id] = { loading: true }; renderCard(id);
    try { GFX[id] = await App.api(gfxUrl("gfx", `id=${id}`)); } catch (e) { GFX[id] = { error: e.message }; }
    renderCard(id);
  }
  function planGfx(id) {
    runJob(() => post("gfxplan", { id }), `Plan the graphics for ${id.toUpperCase()}`, async () => { await reload(); await loadGfx(id, true); });
  }
  async function markGfx(id, g, status, note) {
    try { await post("gfxmark", { id, g, status, note: note || "" }); await reload(); await loadGfx(id, true); }
    catch (e) { App.toast(e.message, true, 8000); }
  }
  function gfxBox(id, s) {
    const box = el("div", { class: "card gxBox" });
    box.append(el("div", { class: "row" }, el("b", {}, "Graphics plan"),
      el("span", { class: "muted small" }, "where each graphic goes and what it will be; nothing is built until you say so")));
    if (s.status !== "approved") {
      box.append(el("div", { class: "muted small" }, "Approve this short and Claude plans its graphics (one small run, about a minute)."));
      return box;
    }
    if (!s.gfx) {
      box.append(el("div", { class: "row" }, el("button", { class: "accent", onclick: () => planGfx(id) }, "✦ Plan the graphics"),
        el("span", { class: "muted small" }, "Claude reads the words and the video's own graphics, then proposes where graphics go and what they show.")));
      return box;
    }
    const v = GFX[id];
    if (!v) { loadGfx(id); box.append(el("div", { class: "muted small" }, "Drawing the strip…")); return box; }
    if (v.loading) { box.append(el("div", { class: "muted small" }, "Drawing the strip (the first time works out the crops: a few seconds)…")); return box; }
    if (v.error) { box.append(el("div", { class: "clWarn" }, v.error)); return box; }
    const total = Math.max(v.total, 0.1), pct = t => `${(100 * t / total).toFixed(2)}%`;
    const c = { ok: 0, change: 0, cut: 0 };
    v.graphics.forEach(g => { if (c[g.status] != null) c[g.status]++; });
    box.append(el("div", { class: "small" }, `${v.graphics.length} graphic${v.graphics.length !== 1 ? "s" : ""} planned for ${v.total.toFixed(0)} s · ${c.ok} OK · ${c.change} to change · ${c.cut} cut`
      + (v.note ? ` · ${v.note}` : "")));
    const track = el("div", { class: "gxTrack" });
    v.cuts.slice(1).forEach(t => track.append(el("i", { class: "gxCut", style: { left: pct(t) }, title: "cut" })));
    v.graphics.forEach(g => track.append(el("span", { class: `gxBar ${g.status || "new"}`, style: { left: pct(g.ts0), width: pct(Math.max(g.ts1 - g.ts0, 0.3)) }, title: `${g.id.toUpperCase()}: ${g.what}` }, g.id.toUpperCase())));
    const words = el("div", { class: "gxWords" });
    for (const w of v.words) {
      const hit = v.graphics.find(g => w.s >= g.ts0 - 0.05 && w.e <= g.ts1 + 0.05 && g.status !== "cut");
      words.append(el("span", { class: hit ? "gxHit" : "", title: hit ? `${hit.id.toUpperCase()} lands here` : "" }, w.w + " "));
    }
    box.append(el("div", { class: "gxStrip" }, track, el("div", { class: "gxAxis muted small" }, el("span", {}, "0 s"), el("span", {}, `${v.total.toFixed(0)} s`)), words));
    for (const g of v.graphics) {
      const note = el("input", { type: "text", class: "shIn", placeholder: "What should change?", value: g.note || "" });
      const st = (name, label, cls) => el("button", { class: g.status === name ? `on ${cls}` : "ghost", onclick: () => markGfx(id, g.id, g.status === name ? "" : name, note.value) }, label);
      box.append(el("div", { class: `gxCard ${g.status || "new"}` },
        el("div", { class: "row" }, el("b", {}, `${g.id.toUpperCase()}  ${g.text || ""}`),
          el("span", { class: "muted small" }, `${g.ts0.toFixed(1)}–${g.ts1.toFixed(1)} s · ${LOOK[g.look] || g.look} · ${g.place}`)),
        el("div", { class: "small" }, el("b", {}, "Shows: "), g.what), el("div", { class: "small" }, el("b", {}, "Moves: "), g.how),
        el("div", { class: "muted small" }, `Lands on: “${g.words}”${g.reuse ? ` · re-uses the main video's graphic ${g.reuse}` : ""}`),
        el("div", { class: "gxStills" }, ...g.moments.map((m, k) => el("figure", {},
          el("img", { loading: "lazy", alt: "", src: gfxUrl("gfxstill", `id=${id}&g=${g.id}&k=${k}&w=270&v=${Math.round(s.gfx.at)}`) }),
          el("figcaption", { class: "muted small" }, `${m.ts.toFixed(1)} s · ${m.what}`)))),
        el("div", { class: "row" }, st("ok", "✓ OK", "ok"), st("change", "✎ Change", "chg"), st("cut", "✕ Cut", "cutb"), note)));
    }
    if (v.skipped.length) box.append(el("div", { class: "muted small" }, `Claude proposed more, left out because they broke the rules: ${v.skipped.join("; ")}`));
    box.append(el("div", { class: "row" }, el("button", { class: "ghost", onclick: () => confirm("Ask Claude for a fresh graphics plan? Your OK / change / cut marks on this plan are replaced.") && planGfx(id) }, "↻ Plan again"),
      el("span", { class: "muted small" }, "These are draft stills on the real frame: placement and content, not the animation. Building the graphics you mark OK is the next step.")));
    return box;
  }

  function publishBox(id, s) {
    const pub = s.publish || {};
    const det = el("details", { class: "shPub", open: s.status === "approved" && !pub.title });
    det.append(el("summary", {}, "YouTube title, description, tags, file name ", pub.title ? el("span", { class: "chip restored" }, "written") : el("span", { class: "chip pend" }, "not written yet")));
    const save = () => act("publish", { id, title: t.value, description: d.value, tags: g.value, filename: fn.value });
    const t = el("input", { type: "text", class: "shIn", value: pub.title || "", maxlength: 100 });
    const cnt = el("span", { class: "muted small" }, `${(pub.title || "").length} / 100 (about 60 shows in full)`);
    t.addEventListener("input", () => { cnt.textContent = `${t.value.length} / 100 (about 60 shows in full)`; });
    const d = el("textarea", { class: "shIn", rows: 8 }); d.value = pub.description || "";
    const g = el("input", { type: "text", class: "shIn", value: (pub.tags || []).join(", ") });
    const fn = el("input", { type: "text", class: "shIn", value: pub.filename || "" });
    for (const e of [t, d, g, fn]) e.addEventListener("change", save);
    det.append(el("div", { class: "shPubGrid" },
      el("label", { class: "shField" }, el("span", { class: "muted small" }, "Title"), t, cnt),
      el("label", { class: "shField" }, el("span", { class: "muted small" }, "Description"), d),
      el("label", { class: "shField" }, el("span", { class: "muted small" }, "Tags (comma separated)"), g),
      el("label", { class: "shField" }, el("span", { class: "muted small" }, "File name when saved (search-friendly, no spaces)"), fn)),
      el("div", { class: "row" }, el("button", { class: "ghost", onclick: () => titles([id]) }, pub.title ? "✦ Write again with Claude" : "✦ Write with Claude"),
        el("span", { class: "muted small" }, "One short Claude run (a cent or two). Edit anything after.")));
    return det;
  }

  function titles(ids) {
    if (!ids.length) return App.toast("Nothing to write titles for: approve some shorts first", true);
    if (!confirm(`Ask Claude to write YouTube titles, descriptions, tags and file names for ${ids.length === 1 ? ids[0].toUpperCase() : ids.length + " shorts"}?\nOne short Claude run (a few cents). You can edit everything afterwards.`)) return;
    runJob(() => post("titles", { ids }), "Claude writes the titles", async () => { await reload(); });
  }
  function finish() {
    const ap = S.d.shorts.filter(x => x.status === "approved");
    if (!ap.length) return App.toast("Approve the shorts you want first", true);
    const need = ap.filter(x => !x.render.final.exists || x.render.final.stale).length;
    if (!confirm(`Finish ${ap.length} approved short${ap.length > 1 ? "s" : ""}?\n\n1. ${need ? `Render ${need} at final quality (1080x1920, best quality, about 10 s each)` : "All finals are already current"}\n2. Copy them, with their generated file names and a text file of title, description and tags, into:\n${S.d.folder}\n\nNothing there is ever overwritten. No Claude tokens are used.`)) return;
    runJob(() => post("finish", {}), "Finish approved shorts", async () => { await reload(); });
  }

  function wordsPanel(id, s) {
    const p = S.plans[id], box = el("div", { class: "shText" });
    if (!p || !p.text) return box;
    let kept = 0, cut = 0;
    for (const r of p.text) for (const w of r.words) (w.cut ? cut++ : kept++);
    box.append(el("div", { class: "muted small" }, `What is said: click a word to cut it out (struck through) or put it back. ${kept} words kept, ${cut} cut · about ${p.total} s once the pauses are gone. Re-render to hear it.`));
    for (const r of p.text) {
      const para = el("div", { class: "shPara" }, el("span", { class: "muted small" }, `${r.range[0]}–${r.range[1]} s  `));
      for (const w of r.words) para.append(el("span", {
        class: `shT${w.cut ? " cut" : ""}`, title: w.cut ? `cut (${w.why}): click to put it back` : "click to cut this word",
        onclick: () => act("cut", { id, start: w.s, end: w.e, cut: !w.cut }) }, w.w), " ");
      box.append(para);
    }
    return box;
  }

  function tighten(ids) {
    const many = ids.length > 1;
    if (!confirm(`Ask Claude to cut ${many ? ids.length + " shorts" : ids[0].toUpperCase()} down to the point?\nOne short Claude run per short (a few cents each, about 30 seconds). It only deletes words; ${many ? "each short keeps" : "this short keeps"} an undo.`)) return;
    runJob(() => post("tighten", { ids }), `Claude tightens ${many ? ids.length + " shorts" : ids[0].toUpperCase()}`, async () => { ids.forEach(i => delete S.plans[i]); await reload(); ids.forEach(i => { if (S.open === i) loadPlan(i, true); }); });
  }

  function pieces(id, s) {
    const p = S.plans[id];
    const box = el("div", { class: "shPieces" });
    if (!p || p.loading) { box.append(el("div", { class: "muted small" }, "Working out the crops (first time: a few seconds)…")); return box; }
    if (p.error) { box.append(el("div", { class: "bdWarn small" }, p.error)); return box; }
    box.append(el("div", { class: "muted small" }, `${p.pieces.length} pieces · ${p.total} s. Click a picture to put the vertical crop there. Click a caption word to correct it.`));
    for (const pc of p.pieces) box.append(pieceRow(id, s, p, pc));
    return box;
  }

  function pieceRow(id, s, p, pc) {
    const live = pc.layout !== "graphic";
    const [SW, SH] = p.src;
    const img = el("img", { src: `/api/shorts/frame?${q()}&t=${pc.t}&w=480`, loading: "lazy", draggable: "false" });
    const frame = el("div", { class: "shFrame", title: live ? "Click to centre the crop here" : "" }, img);
    if (pc.box) {
      const [x, y, w, h] = pc.box;
      frame.append(el("div", { class: "shBox", style: { left: `${x / SW * 100}%`, top: `${y / SH * 100}%`, width: `${w / SW * 100}%`, height: `${h / SH * 100}%` } }));
    }
    if (live && pc.layout === "live") frame.addEventListener("click", ev => {
      const r = frame.getBoundingClientRect();
      act("crop", { id, t: pc.t, a: pc.a, b: pc.b, cx: (ev.clientX - r.left) / r.width, cy: Math.min(0.5, Math.max(0.3, (ev.clientY - r.top) / r.height)) });
    });
    const sel = (value, opts, onChange) => {
      const e = el("select", { class: "shSel" }, opts.map(([v, l]) => el("option", { value: v, selected: String(v) === String(value) }, l)));
      e.addEventListener("change", () => onChange(e.value));
      return e;
    };
    const ctl = el("div", { class: "row small" },
      el("span", { class: "muted" }, `${pc.i}  ${pc.a}–${pc.b}s · ${pc.speaker || ""}${pc.cont ? " · zoom cut" : ""}`),
      sel(pc.layout, [["live", "Vertical crop"], ["blur", "Whole frame"], ["graphic", "Graphic"]], v => act("crop", { id, t: pc.t, a: pc.a, b: pc.b, layout: v })),
      pc.layout === "live" ? sel(pc.zoom, [[1, "Zoom 1.0"], [1.15, "1.15"], [1.3, "1.3"], [1.5, "1.5"]], v => act("crop", { id, t: pc.t, a: pc.a, b: pc.b, zoom: +v })) : null,
      pc.layout === "graphic" ? sel(pc.gzoom, [[1, "Whole card"], [1.15, "Closer 1.15"], [1.3, "Closer 1.3"], [1.45, "Closer 1.45"]], v => act("crop", { id, t: pc.t, a: pc.a, b: pc.b, gzoom: +v })) : null,
      s.crops.some(c => c.t >= pc.a - 0.05 && c.t <= pc.b + 0.05) ? el("button", { class: "ghost", title: "Back to the automatic guess", onclick: () => act("crop", { id, t: pc.t, a: pc.a, b: pc.b, reset: true }) }, "reset") : null);
    const words = el("div", { class: "shWords" }, pc.words.map(w => el("span", {
      class: `shW${s.words[`${+w.s}`] !== undefined ? " fixed" : ""}`, title: "Click to correct this word (empty = remove it)",
      onclick: () => {
        const cur = s.words[`${+w.s}`] !== undefined ? s.words[`${+w.s}`] : w.w;
        const t = prompt("Caption word (empty removes it; type the original to keep):", cur);
        if (t === null) return;
        act("word", { id, start: w.s, text: t.trim() });
      } }, s.words[`${+w.s}`] === "" ? "∅" : (s.words[`${+w.s}`] ?? w.w))));
    return el("div", { class: "shPiece" }, frame, el("div", { class: "shPcBody" }, ctl, words));
  }

  /* ---------------------------------------------------------------- new project, add, find */
  async function showNew() {
    const box = $("#shNewBox");
    if (!box.hidden) { box.hidden = true; return; }
    box.hidden = false; box.innerHTML = "";
    box.append(el("div", { class: "muted small" }, "Looking for finished videos…"));
    let vids;
    try { vids = S.videos || (S.videos = await App.api("/api/shorts/videos")); } catch (e) { box.hidden = true; return App.toast(e.message, true); }
    box.innerHTML = "";
    const sel = el("select", { class: "shIn" }, vids.map(v => el("option", { value: v.path }, `${v.folder} · ${v.file} (${v.mb} MB)`)));
    const nm = el("input", { type: "text", class: "shIn", placeholder: "short name, e.g. sphere" });
    const ppl = el("input", { type: "text", class: "shIn", value: "", placeholder: "default: the names in your channel profile", title: "People in the video, the first one is the voice in the reference clip" });
    const rs = el("input", { type: "number", class: "shIn narrow", value: 1, step: 1 }), rl = el("input", { type: "number", class: "shIn narrow", value: 12, step: 1 });
    box.append(el("b", {}, "New shorts project from a finished video"),
      el("label", { class: "shField" }, el("span", { class: "muted small" }, "Video"), sel),
      el("label", { class: "shField" }, el("span", { class: "muted small" }, "Name for this project"), nm),
      el("div", { class: "row" },
        el("label", { class: "shField" }, el("span", { class: "muted small" }, "People (first = the host)"), ppl),
        el("label", { class: "shField" }, el("span", { class: "muted small" }, "Host talks alone from (s)"), rs),
        el("label", { class: "shField" }, el("span", { class: "muted small" }, "for (s)"), rl)),
      el("div", { class: "row" }, el("button", { class: "accent", onclick: () => {
        const name = nm.value.trim().replace(/\s+/g, "-").toLowerCase();
        if (!name) return App.toast("Give the project a name", true);
        box.hidden = true;
        runJob(() => App.api("/api/shorts/new", { work: `${name}-shorts`, name, source: sel.value, people: ppl.value, ref_start: +rs.value, ref_len: +rl.value }),
          "Prepare the video (transcribe + voices)", () => loadList({ work: `${name}-shorts`, name }));
      } }, "Prepare it (about a minute)"), el("button", { class: "ghost", onclick: () => { box.hidden = true; } }, "Cancel"),
        el("span", { class: "muted small" }, "Uses the free local tools. The host's voice is learned from the clip you name (a stretch where only they talk).")));
  }
  function addByTime() {
    const t = prompt("Start-end in seconds of the finished video, e.g. 20.6-40.7 (several ranges: 20.6-40.7, 58.2-71.9):");
    if (!t) return;
    let ranges; try { ranges = parseRanges(t); } catch (e) { return App.toast(e.message, true, 7000); }
    const title = prompt("A name for it (for you):", "New short") || "New short";
    act("add", { ranges, title, hook: title.toUpperCase() }, "Added: open it to render");
  }
  function ask() {
    if (!confirm("Ask Claude to choose the best shorts (the recommended number)?\nOne short Claude run (a few cents of your plan, about a minute). It only adds proposals; nothing you edited changes.")) return;
    runJob(() => post("find", {}), "Claude proposes shorts", async () => { await reload(); });
  }

  /* ---------------------------------------------------------------- make shorts from a main video (ADR 0006) */
  const M = { videos: [], key: null, rec: null, count: null };
  const plural = (n, w) => `${n} ${w}${n !== 1 ? "s" : ""}`;
  async function loadMake() {
    try { M.videos = await App.api("/api/wf/videos"); } catch { M.videos = []; }
    const opts = M.videos.flatMap(v => v.names.map(n => [v.work, n]));
    const box = $("#shMake");
    if (!opts.length) { box.hidden = true; return; }
    box.hidden = false;
    let want = M.key || (S.key ? [S.key.work, S.key.name] : null);
    if (!want) { try { want = JSON.parse(App.videoKey() || "null"); } catch { want = null; } }
    M.key = opts.find(o => want && o[0] === want[0] && o[1] === want[1]) || opts[0];
    await loadRec();
  }
  async function loadRec() {
    try { M.rec = await App.api(`/api/shorts/recommend?work=${encodeURIComponent(M.key[0])}&name=${encodeURIComponent(M.key[1])}`); }
    catch (e) { M.rec = null; App.toast(e.message, true, 8000); }
    M.count = M.rec ? (M.rec.recommended || 1) : null;
    renderMake();
  }
  function renderMake() {
    const box = $("#shMake"), r = M.rec; box.innerHTML = "";
    const opts = M.videos.flatMap(v => v.names.map(n => [v.work, n]));
    const pick = el("select", {}, ...opts.map(o => el("option", { value: JSON.stringify(o), selected: o[0] === M.key[0] && o[1] === M.key[1] }, o[1])));
    pick.onchange = () => { M.key = JSON.parse(pick.value); loadRec(); };
    box.append(el("div", { class: "row" }, el("b", {}, "Make shorts from the main video"), pick, el("span", { class: "spacer" }),
      el("span", { class: "muted small" }, "Shorts are clips of the video (they can come from several sections), 10 seconds to 3 minutes, mostly under a minute.")));
    if (!r) return;
    if (!r.recommended) { box.append(el("div", { class: "mkBig" }, "There is nothing to cut shorts from yet."), ...r.reasons.map(x => el("div", { class: "muted small" }, x))); return; }
    box.append(el("div", { class: "mkBig" }, `From this video I believe we could make ${plural(r.recommended, "short")}.`));
    for (const x of r.reasons) box.append(el("div", { class: "muted small" }, x));
    if (r.moments.length) box.append(el("details", { class: "small" }, el("summary", { class: "muted" }, `The strong visual moments I found (${r.moments.length})`),
      el("div", { class: "mkMoments" }, ...r.moments.map(m => el("div", {}, `${mmss(m.start)}–${mmss(m.end)} · ${Math.round(m.dur)} s · ${m.why || "a motion graphic or teaching point"}`)))));
    const choices = [...new Set([r.recommended, 1, 3, 5].filter(n => n >= 1 && n <= r.max))].sort((a, b) => a - b);
    const num = el("input", { type: "number", min: 1, max: r.max, value: M.count, title: `1 to ${r.max}` });
    const sync = () => { box.querySelectorAll(".mkCounts button[data-n]").forEach(b => b.classList.toggle("on", +b.dataset.n === M.count)); go.textContent = `Go: make ${plural(M.count, "short")}`; weak.hidden = !(r.has_beatmap && M.count > r.strong); };
    const row = el("div", { class: "mkCounts" }, el("span", { class: "muted small" }, "How many?"),
      ...choices.map(n => el("button", { class: "ghost", "data-n": n, onclick: () => { M.count = n; num.value = n; sync(); } }, n === r.recommended ? `${n} (recommended)` : String(n))), "or", num);
    num.onchange = () => { M.count = Math.max(1, Math.min(r.max, +num.value || 1)); num.value = M.count; sync(); };
    const go = el("button", { class: "accent", disabled: !r.final, onclick: () => makeShorts() }, "");
    const weak = el("div", { class: "small", hidden: true, style: { color: "var(--orange)" } }, `I only found ${r.strong} strong visual moment${r.strong !== 1 ? "s" : ""}: the extra ones will be weaker.`);
    row.append(go); box.append(row, weak);
    if (!r.final) box.append(el("div", { class: "small", style: { color: "var(--orange)" } }, "Render the final first (Final tab): shorts are cut from the final video."));
    if (r.has_project) box.append(el("div", { class: "muted small" }, "This video already has shorts below. Go adds more and does not repeat those."));
    sync();
  }
  function makeShorts() {
    const [work, name] = M.key, n = M.count;
    if (!confirm(`Make ${plural(n, "short")} from "${name}"?\n\n${M.rec.has_project ? "" : "First the final video is transcribed (free, local, about a minute). "}Then one Claude run chooses the best ${n === 1 ? "moment" : n + " moments"} (about a minute, a few cents of your plan). Nothing is rendered yet.`)) return;
    runJob(() => App.api("/api/shorts/make", { work, name, count: n }), `Make ${plural(n, "short")}`, async () => { await loadList({ work, name }); await loadRec(); });
  }

  /* ---------------------------------------------------------------- wiring */
  $("#shPick").addEventListener("change", () => { const [work, name] = JSON.parse($("#shPick").value); S.key = { work, name }; S.open = null; S.plans = {}; reload(); });
  $("#shTightAll").onclick = () => { const ids = S.d.shorts.filter(x => x.status !== "rejected" && !x.tightened).map(x => x.id); ids.length ? tighten(ids) : App.toast("Everything that is not rejected is already tightened"); };
  $("#shTitles").onclick = () => { const ap = S.d.shorts.filter(x => x.status === "approved"); const miss = ap.filter(x => !(x.publish || {}).title); titles((miss.length ? miss : ap).map(x => x.id)); };
  $("#shFinish").onclick = finish;
  $("#shLink").addEventListener("change", () => act("project", { full_video_url: $("#shLink").value }, "Link saved: used in the descriptions Claude writes"));
  $("#shNew").onclick = showNew; $("#shAdd").onclick = addByTime; $("#shFind").onclick = ask; $("#shRefresh").onclick = reload;
  window.addEventListener("viewchange", e => { if (e.detail === "shorts") { loadList(); loadMake(); } });
  if (visible()) { loadList(); loadMake(); }
})();
