"use strict";
/* Final tab (stage 8): the full-quality render. It needs a stitched half-size preview and nothing else (no approval gate: unfinished work only warns).
   tools/finalrender.py rebuilds the picture at 1080p from the same cut lists as the preview, runs the voice chain on the
   continuous recording, mixes music and sound effects by explicit file name, sets loudness to -14 LUFS, checks the finished
   file, and writes chapters and a description. This tab shows what will be mixed (and what cannot be matched and will NOT
   be mixed), runs the render, and shows each finished version with its checks. */
(() => {
  const F = { key: null, d: null, loading: false };
  const vid = $("#finVideo");
  const visible = () => document.body.dataset.view === "final";
  const q = () => `work=${encodeURIComponent(F.key.work)}&name=${encodeURIComponent(F.key.name)}`;
  const tc = t => App.fmtT(t, 0);

  /* ---------------------------------------------------------------- load */
  async function loadList(pick) {
    const list = await App.api("/api/wf/videos");
    const vids = list.flatMap(w => w.names.map(n => ({ work: w.work, name: n })));
    const sel = $("#finPick"); sel.innerHTML = "";
    for (const v of vids) sel.append(el("option", { value: JSON.stringify([v.work, v.name]) }, v.work === v.name ? v.name : `${v.work} · ${v.name}`));
    $("#finEmpty").hidden = vids.length > 0; $("#finBody").hidden = !vids.length; sel.hidden = !vids.length;
    if (!vids.length) { F.key = null; return; }
    const want = pick ? JSON.stringify([pick.work, pick.name]) : App.videoKey();
    if (want && [...sel.options].some(o => o.value === want)) sel.value = want;
    const [work, name] = JSON.parse(sel.value);
    F.key = { work, name };
    await reload();
  }
  async function reload() {
    if (!F.key || F.loading) return;
    F.loading = true;
    try {
      App.setVideoKey(JSON.stringify([F.key.work, F.key.name]));
      F.d = await App.api(`/api/final?${q()}`);
      render();
    } catch (e) { App.toast(e.message, true, 8000); }
    F.loading = false;
  }
  App.finalReload = () => (visible() ? reload() : Promise.resolve());
  async function run() {
    const d = F.d, nm = (d.plan && d.plan.not_mixed) || [];
    const msg = `Render "${d.title} v${d.next_version} (1080p).mp4" at full quality?` + (nm.length ? `\n\n${nm.length} music/sound-effect entr${nm.length === 1 ? "y" : "ies"} could not be matched and will NOT be mixed.` : "")
      + (d.warnings.length ? `\n\nStill open:\n- ${d.warnings.join("\n- ")}` : "")
      + "\n\nExisting versions are never overwritten.";
    if (!confirm(msg)) return;
    try { App.watchJob(await App.api("/api/final/run", { ...F.key })); }
    catch (e) { App.toast(e.message, true, 9000); }
  }
  function play(f) {
    $("#finPlayerBox").hidden = false; $("#finPlayTitle").textContent = f.file;
    vid.src = `/media/${encodeURIComponent(F.key.work)}/${encodeURIComponent(f.file)}?t=${f.mtime}`; vid.play().catch(() => {});
  }
  $("#finPlayClose").onclick = () => { vid.pause(); $("#finPlayerBox").hidden = true; };

  /* ---------------------------------------------------------------- render */
  function renderSetup() {
    const d = F.d, box = $("#finSetup"); box.innerHTML = "";
    if (!d.can_render) box.append(el("div", { class: "bdGate" }, d.why_not, " ", el("a", { style: { cursor: "pointer", textDecoration: "underline" }, onclick: () => App.setView("build") }, "Go to Build & review")));
    for (const w of d.warnings) box.append(el("div", { class: "bdWarn" }, "⚠ " + w));
    box.append(el("div", { class: "muted small" }, "1080p · 30 fps · picture rebuilt from the same cut lists as the preview · your voice chain (warmer, less bright) on the whole recording · music 26 LU under the speech, ducked 9 dB while you talk · loudness -14 LUFS, true peak -1.5 dB. Change the music level and ducking in the Dashboard tab."));
    box.append(el("div", { class: "row" }, el("button", { class: "accent", disabled: !d.ready, onclick: run }, `Render the final: ${d.title} v${d.next_version}`),
      !d.ready && d.can_render ? el("span", { class: "muted small" }, "Needs every section built and stitched (Build tab).") : null));
  }
  function renderPlan() {
    const d = F.d, box = $("#finPlan"); box.innerHTML = "";
    if (!d.plan) return;
    box.append(el("b", {}, "What will be mixed"));
    const rows = [];
    for (const b of d.plan.beds) rows.push([!!b.file, `Music: ${b.name}`, b.file ? `${tc(b.start)}–${tc(b.end)}${b.why ? " · " + b.why : ""}` : `NOT MIXED: ${b.why}`]);
    for (const s of d.plan.sfx) rows.push([true, `Sound effect: ${s.name}`, `at ${tc(s.t)}`]);
    for (const m of d.plan.not_mixed.filter(x => x.kind === "sfx")) rows.push([false, `Sound effect: ${m.name}`, `NOT MIXED: ${m.why}`]);
    if (!rows.length) rows.push([true, "No music or sound effects in the beat map", "the speech goes out on its own"]);
    for (const [ok, a, b] of rows) box.append(el("div", { class: `finRow ${ok ? "ok" : "no"}` }, el("span", { class: "ic" }, ok ? "✓" : "✗"), el("span", {}, a), el("span", { class: "muted" }, b)));
    if (d.plan.not_mixed.length)
      box.append(el("div", { class: "muted small" }, "Names are matched exactly, never guessed. Fix them in the Beat map tab (Music: a track name from the Music folder, e.g. “TrackTribe - Boardwalk”; Sound effects: “file name @ seconds” or “file name @graphic”), then render."));
    box.append(el("div", { class: "small" }, d.chapters.length ? `Chapters (${d.chapters.length}): ` + d.chapters.map(c => `${tc(c.t)} ${c.title}`).join(" · ")
      : "Chapters: YouTube needs at least 3, each 10 s or longer, so none will be written."));
  }
  function renderList() {
    const d = F.d, box = $("#finList"); box.innerHTML = "";
    if (!d.finals.length) { box.append(el("div", { class: "muted small" }, "No final render yet.")); return; }
    d.finals.forEach((f, i) => {
      const bad = (f.checks || []).filter(c => !c.ok);
      const card = el("div", { class: `finCard ${bad.length ? "bad" : ""}` },
        el("div", { class: "row" }, el("b", {}, f.file), el("span", { class: "muted small" }, `${f.size_mb} MB${f.dur ? " · " + tc(f.dur) : ""}${f.loudness && f.loudness.I != null ? ` · ${f.loudness.I} LUFS` : ""}${f.created ? " · " + new Date(f.created).toLocaleString() : ""}`),
          el("span", { class: "spacer" }), el("button", { onclick: () => play(f) }, "▶ Play")));
      if (f.checks) {
        card.append(el("div", { class: "small", style: { marginTop: "4px" } }, bad.length ? `${bad.length} check${bad.length !== 1 ? "s" : ""} failed:` : "All checks passed:"));
        for (const c of f.checks) card.append(el("div", { class: `finRow ${c.ok ? "ok" : "no"}` }, el("span", { class: "ic" }, c.ok ? "✓" : "✗"), el("span", {}, c.id.replace("_", " ")), el("span", { class: "muted" }, c.note)));
      } else card.append(el("div", { class: "muted small" }, "(made before the final-render tool: no check record)"));
      if (f.delivered) card.append(el("div", { class: f.delivered.ok ? "small" : "bdWarn" }, f.delivered.ok
        ? `Copied for uploading to your project folder: ${f.delivered.folder} (${f.delivered.files.map(x => x.file + (x.skipped ? " (already there)" : "")).join(", ")})`
        : `Not copied to your project folder: ${f.delivered.why}`));
      if (i === 0) {
        if (f.audio && f.audio.not_mixed && f.audio.not_mixed.length)
          card.append(el("div", { class: "bdWarn" }, `Not mixed: ${f.audio.not_mixed.map(m => `${m.kind} “${m.name}”`).join(", ")}`));
        if (d.chapters_text) card.append(el("details", {}, el("summary", { class: "small" }, "Chapters for the YouTube description"), el("div", { class: "finPre" }, d.chapters_text),
          el("button", { class: "ghost", onclick: () => navigator.clipboard.writeText(d.chapters_text).then(() => App.toast("Copied")) }, "Copy chapters")));
        if (d.description) card.append(el("details", {}, el("summary", { class: "small" }, "Description draft (fill the [FILL] lines)"), el("div", { class: "finPre" }, d.description),
          el("button", { class: "ghost", onclick: () => navigator.clipboard.writeText(d.description).then(() => App.toast("Copied")) }, "Copy description")));
        if (d.joins_sheet) card.append(el("details", {}, el("summary", { class: "small" }, "Every cut: the frame just before and just after"), el("img", { class: "finJoins", src: `/finalimg/${encodeURIComponent(F.key.work)}/joins.jpg?t=${f.mtime}`, loading: "lazy", alt: "cuts" })));
      }
      box.append(card);
    });
  }
  function render() { if (F.d) { renderSetup(); renderPlan(); renderList(); } }

  /* ---------------------------------------------------------------- wiring */
  $("#finPick").onchange = () => { const [work, name] = JSON.parse($("#finPick").value); F.key = { work, name }; F.d = null; reload(); };
  $("#finRefresh").onclick = () => loadList(F.key);
  window.addEventListener("viewchange", e => { if (e.detail === "final") loadList(F.key); else vid.pause(); });
  window.addEventListener("focus", () => { if (visible()) reload(); });
  if (visible()) loadList();
})();
