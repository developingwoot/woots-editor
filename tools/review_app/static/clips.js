"use strict";
/* Clips tab: after the footage is transcribed, tools/clipmap.py matches every take to the
   script and ranks the takes for each line. Here the creator sees what each clip (or part of a clip) is about, plays it,
   and corrects: swap the take for a line, rename a topic, change which script lines a span covers, split or
   merge spans, skip unusable ones. Every correction is saved in <name>.clips.json ("corrections", with the
   optional "why") so Claude learns his taste. Approval happens in the Dashboard tab. */
(() => {
  const C = { key: null, data: null, foot: null, mode: App.store.get("clMode", "lines"), loading: false, playing: null, stopAt: null };
  const vid = $("#clVideo");
  const q = () => `work=${encodeURIComponent(C.key.work)}&name=${encodeURIComponent(C.key.name)}`;
  const post = (path, body) => App.api(path, { ...C.key, ...body });
  const visible = () => document.body.dataset.view === "clips";
  const enc = rel => rel.split("/").map(encodeURIComponent).join("/");
  const mediaUrl = rel => `/fmedia/${encodeURIComponent(C.key.work)}/${encodeURIComponent(C.key.name)}/${enc(rel)}`;
  const thumb = (rel, t) => `/thumb?${q()}&file=${encodeURIComponent(rel)}&t=${Math.max(0, t).toFixed(1)}`;
  const tc = t => App.fmtT(t, 1);
  const spans = () => (C.data && C.data.clips ? C.data.clips.clips : []).flatMap(c => c.spans.map(s => ({ ...s, rel: c.rel, clip: c })));
  const spanById = id => spans().find(s => s.id === id);
  const lineText = id => ((C.data.script.lines.find(l => l.id === id) || {}).said) || "";

  /* ---------------------------------------------------------------- loading */
  async function loadList(pick) {
    const list = await App.api("/api/wf/videos");
    const vids = list.flatMap(w => w.names.map(n => ({ work: w.work, name: n })));
    const sel = $("#clPick"); sel.innerHTML = "";
    for (const v of vids) sel.append(el("option", { value: JSON.stringify([v.work, v.name]) }, v.work === v.name ? v.name : `${v.work} · ${v.name}`));
    $("#clEmpty").hidden = vids.length > 0; $("#clBody").hidden = !vids.length; sel.hidden = !vids.length;
    if (!vids.length) { C.key = null; return; }
    const want = pick ? JSON.stringify([pick.work, pick.name]) : App.videoKey();   // same choice as the Dashboard tab
    if (want && [...sel.options].some(o => o.value === want)) sel.value = want;
    const [work, name] = JSON.parse(sel.value);
    C.key = { work, name };
    await reload();
  }
  async function reload() {
    if (!C.key || C.loading) return;
    C.loading = true;
    try {
      App.setVideoKey(JSON.stringify([C.key.work, C.key.name]));
      const [data, foot] = await Promise.all([
        App.api(`/api/clips?${q()}`),
        App.api(`/api/footage?${q()}`).catch(() => null)]);
      C.data = data; C.foot = foot;
      render();
    } catch (e) { App.toast(e.message, true, 8000); }
    C.loading = false;
  }
  App.clipsReload = () => (visible() ? reload() : Promise.resolve());

  /* ---------------------------------------------------------------- setup strip */
  const analysable = () => ((C.foot && C.foot.clips) || []).filter(c => ["aroll", "unassigned"].includes(c.role));
  function renderSetup() {
    const box = $("#clSetup"); box.innerHTML = "";
    const S = C.data.script, F = C.foot || {}, clips = analysable();
    const done = clips.filter(c => c.analysis).length, todo = clips.filter(c => !c.analysis);
    // 1 script
    box.append(el("div", { class: "clStat" }, el("b", {}, "1 · Script"),
      S.exists ? el("span", {}, `${S.lines.length} lines with ids`) : el("span", { class: "clWarn" }, "no script yet: ask Claude to write it, then open the Script tab")));
    // 2 footage
    const row2 = el("div", { class: "clStat" }, el("b", {}, "2 · Footage"),
      el("span", { class: "muted" }, F.folder || "no folder chosen"),
      el("button", { class: F.folder ? "ghost" : "accent", onclick: chooseFolder }, F.folder ? "Change…" : "Choose folder…"));
    if (F.folder) row2.append(el("span", {}, `${clips.length} talking clips, ${done} transcribed`));
    if (F.scan_error) row2.append(el("span", { class: "clWarn" }, F.scan_error));
    box.append(row2);
    if (F.folder && todo.length)
      box.append(el("div", { class: "clStat" }, el("b", {}, ""), el("button", { class: "accent", onclick: () => transcribe(todo) },
        `Transcribe ${todo.length} clip${todo.length !== 1 ? "s" : ""}`),
        el("span", { class: "muted small" }, "Uses the GPU, about a minute for a few clips. Intro/outro and B-roll clips are skipped (sort the clips in the list above).")));
    if (F.folder && (F.clips || []).length) box.append(roleList(F));
    // 3 map
    const can = S.exists && S.lines.length && C.data.has_footage;
    const row3 = el("div", { class: "clStat" }, el("b", {}, "3 · Match to script"),
      el("button", { class: C.data.clips ? "ghost" : "accent", disabled: !can, onclick: mapClips },
        C.data.clips ? "Match again (keeps your corrections)" : "Match takes to the script"));
    if (C.data.clips) row3.append(el("span", { class: "muted small" }, `matched ${new Date(C.data.clips.generated).toLocaleString()}`));
    box.append(row3);
  }
  /* What the Footage tab used to do: say what each clip is (A-roll = you talking, B-roll = cutaways, intro/outro, or leave it on auto). */
  const ROLE_LABEL = { aroll: "A-roll (me talking)", broll: "B-roll", intro: "Intro", outro: "Outro", unassigned: "Not sorted yet" };
  function roleList(F) {
    const counts = {};
    for (const c of F.clips) counts[c.role] = (counts[c.role] || 0) + 1;
    const d = el("details", { class: "clStat" }, el("summary", { class: "small" }, `Clips in the folder (${F.clips.length}): ` +
      Object.entries(counts).map(([r, n]) => `${n} ${ROLE_LABEL[r] || r}`).join(" · ") + " — click to sort them"));
    for (const c of F.clips) {
      const sel = el("select", {}, el("option", { value: "auto" }, `Auto (${ROLE_LABEL[c.auto] || c.auto})`),
        ...["aroll", "broll", "intro", "outro", "unassigned"].map(r => el("option", { value: r, selected: c.override && c.role === r }, ROLE_LABEL[r])));
      sel.onchange = async () => { try { await post("/api/footage/role", { file: c.rel, role: sel.value }); await reload(); } catch (e) { App.toast(e.message, true, 8000); } };
      d.append(el("div", { class: "row small" }, el("span", { title: c.rel }, c.rel), el("span", { class: "spacer" }), sel));
    }
    return d;
  }
  async function chooseFolder() {
    const F = C.foot || {};
    App.pickFolder({ suggest: F.suggest || [], start: F.folder, pick: async folder => {
      await post("/api/footage/folder", { folder }); App.toast("Folder saved"); await reload(); } });
  }
  async function transcribe(todo) {
    try { App.watchJob(await post("/api/footage/analyze", { files: todo.map(c => c.rel) })); }
    catch (e) { App.toast(e.message, true, 8000); }
  }
  async function mapClips() {
    try { App.watchJob(await post("/api/clips/map", {})); }
    catch (e) { App.toast(e.message, true, 8000); }
  }

  /* ---------------------------------------------------------------- notices */
  function renderNotice() {
    const n = $("#clNotice"); n.innerHTML = "";
    const D = C.data.clips;
    if (!D) return;
    if (C.data.stale) n.append(el("div", { class: "clNote" }, "The script changed since the takes were matched: press “Match again” (your corrections are kept)."));
    if (D.missing_lines && D.missing_lines.length)
      n.append(el("div", { class: "clNote" }, `No usable take yet for ${D.missing_lines.length} line${D.missing_lines.length !== 1 ? "s" : ""}: ${D.missing_lines.join(", ")}. Record them, or assign a span to them.`));
  }

  /* ---------------------------------------------------------------- player */
  function play(s, from) {
    $("#clPlayerBox").hidden = false;
    C.playing = { id: s.id, rel: s.rel, start: s.start, end: s.end };
    $("#clPlayTitle").textContent = `${base(s.rel)}  ${tc(s.start)}–${tc(s.end)}`;
    const url = mediaUrl(s.rel);
    const go = () => { vid.currentTime = from ?? s.start; vid.play().catch(() => {}); };
    if (!vid.src.endsWith(url)) { vid.src = url; vid.addEventListener("loadedmetadata", go, { once: true }); } else go();
    drawPlayBar();
  }
  vid.addEventListener("timeupdate", () => { if (C.playing && vid.currentTime >= C.playing.end) { vid.pause(); } drawPlayBar(true); });
  function drawPlayBar(light) {
    const bar = $("#clPlayBar"), p = C.playing;
    if (!p) return;
    const s = spanById(p.id);
    const inside = vid.currentTime > p.start + 0.4 && vid.currentTime < p.end - 0.4;
    if (light) { const b = $("#clSplitBtn"); if (b) { b.disabled = !inside; b.textContent = `✂ Split at ${tc(vid.currentTime)}`; } return; }
    bar.innerHTML = "";
    bar.append(el("button", { onclick: () => play(s || p) }, "↺ From the start"),
      el("button", { id: "clSplitBtn", class: "ghost", disabled: !inside, onclick: () => split(p.id, vid.currentTime) }, `✂ Split at ${tc(vid.currentTime)}`),
      el("span", { class: "muted small" }, s ? `“${s.text.slice(0, 120)}${s.text.length > 120 ? "…" : ""}”` : ""));
  }
  $("#clPlayClose").onclick = () => { vid.pause(); C.playing = null; $("#clPlayerBox").hidden = true; };

  /* ---------------------------------------------------------------- corrections */
  async function edit(op, body) {
    const why = $("#clWhy").value.trim();
    try {
      C.data = await post(`/api/clips/${op}`, { ...body, ...(why ? { why } : {}) });
      if (why) $("#clWhy").value = "";
      render();
    } catch (e) { App.toast(e.message, true, 8000); }
  }
  const split = (id, at) => { if (!confirm(`Split this span at ${tc(at)}? The two halves are matched to the script again.`)) return; edit("split", { id, at }); };
  const merge = id => { if (!confirm("Join this span with the one after it?")) return; edit("merge", { id }); };

  /* ---------------------------------------------------------------- views */
  function flagChips(s) {
    return (s.flags || []).map(f => el("span", { class: `tag2 ${/restart|not in the script|only \d+%|slow/.test(f) ? "warn" : ""}` }, f));
  }
  function render() {
    renderSetup(); renderNotice();
    const main = $("#clMain"); main.innerHTML = "";
    $$("#clMode button").forEach(b => b.classList.toggle("on", b.dataset.m === C.mode));
    if (!C.data.clips) {
      main.append(el("div", { class: "card" }, el("b", {}, "Nothing matched yet."),
        el("p", { class: "muted small" }, "Choose the footage folder, transcribe the clips, then match them to the script. You can correct everything afterwards.")));
      return;
    }
    (C.mode === "lines" ? renderLines : renderClips)(main);
  }

  function takeRow(lid, sid, ent, isPicked) {
    const s = spanById(sid); if (!s) return null;
    const row = el("div", { class: "clTake" },
      el("button", { onclick: () => play(s) }, "▶"),
      el("span", {}, `${base(s.rel)} ${tc(s.start)}–${tc(s.end)} (${Math.round(s.dur)} s)`),
      el("span", { class: "muted" }, `score ${ent.score[sid]}`),
      s.script_lines.length > 1 ? el("span", { class: "tag2" }, `also ${s.script_lines.filter(x => x !== lid).join(", ")}`) : null,
      ...flagChips(s));
    if (!isPicked) row.append(el("button", { class: "ghost", onclick: () => edit("pick", { line: lid, span: sid }) }, "Use this take"));
    return row;
  }
  function renderLines(main) {
    const D = C.data.clips; let lastHead = null;
    for (const ln of C.data.script.lines) {
      if (ln.heading !== lastHead) { lastHead = ln.heading; if (ln.heading) main.append(el("div", { class: "clHead" }, ln.heading)); }
      const ent = D.by_line[ln.id] || { candidates: [], picked: null, score: {}, reason: "not matched yet" };
      const others = ent.candidates.filter(x => x !== ent.picked && (!spanById(x) || !spanById(x).skip || $("#clSkipped").checked));
      const box = el("div", { class: `clLine ${ent.picked ? (ent.picked_by === "user" ? "user" : "picked") : "none"}` },
        el("div", { class: "clId" }, ln.id),
        el("div", {}, el("div", { class: "clSaid" }, ln.said),
          ent.picked ? takeRow(ln.id, ent.picked, ent, true) : el("div", { class: "clTake" }, el("span", { class: "tag2 warn" }, "no take"), el("span", { class: "muted" }, ent.reason)),
          ent.picked ? el("div", { class: "muted small" }, ent.reason) : null,
          (others.length || ent.picked) ? el("details", { class: "clAlt" }, el("summary", {}, `${others.length} other take${others.length !== 1 ? "s" : ""}`),
            ...others.map(x => takeRow(ln.id, x, ent, false)),
            ent.picked ? el("div", { class: "clTake" }, el("button", { class: "ghost", onclick: () => edit("pick", { line: ln.id, span: null }) }, "Use no take for this line")) : null) : null));
      main.append(box);
    }
  }

  function linesBox(s) {
    const sel = new Set(s.script_lines);
    const box = el("div", { class: "clLinesBox", hidden: true });
    for (const ln of C.data.script.lines)
      box.append(el("label", {}, el("input", { type: "checkbox", value: ln.id, checked: sel.has(ln.id) }), el("b", {}, ln.id), ln.said.slice(0, 90)));
    box.append(el("div", { class: "row" }, el("button", { class: "accent", onclick: () =>
      edit("edit", { id: s.id, script_lines: $$("input:checked", box).map(i => i.value) }) }, "Apply"),
      el("button", { class: "ghost", onclick: () => (box.hidden = true) }, "Cancel")));
    return box;
  }
  function renderClips(main) {
    const showSkipped = $("#clSkipped").checked;
    for (const c of C.data.clips.clips) {
      const box = el("div", { class: "clClip" }, el("h3", {}, c.name, el("span", { class: "muted small" }, `  ${c.rel !== c.name ? c.rel + " · " : ""}${c.spans.length} span${c.spans.length !== 1 ? "s" : ""}`)));
      c.spans.forEach((sp, i) => {
        if (sp.skip && !showSkipped) return;
        const s = { ...sp, rel: c.rel };
        const lb = linesBox(s);
        const chips = el("div", { class: "clChips" },
          ...(s.script_lines.length ? s.script_lines.map(l => el("span", { class: "tag2 good", title: lineText(l) }, l)) : [el("span", { class: "tag2 warn" }, "no script line")]),
          el("button", { class: "ghost", style: { minHeight: "24px", padding: "0 8px", fontSize: "12px" }, onclick: () => (lb.hidden = !lb.hidden) }, "✎ lines"),
          ...flagChips(s));
        const topic = el("input", { type: "text", value: s.topic, placeholder: "What is this about?" });
        topic.onchange = () => edit("edit", { id: s.id, topic: topic.value });
        const sum = el("textarea", {}, s.summary);
        sum.onchange = () => edit("edit", { id: s.id, summary: sum.value });
        const note = el("input", { type: "text", value: s.note || "", placeholder: "Note (optional)" });
        note.onchange = () => edit("edit", { id: s.id, note: note.value });
        box.append(el("div", { class: `clSpan ${s.skip ? "skip" : ""} ${(s.flags || []).length ? "low" : ""}` },
          el("img", { src: thumb(c.rel, s.start + 0.3), loading: "lazy", alt: "", onclick: () => play(s) }),
          el("div", {}, el("div", { class: "row" }, el("b", {}, `${tc(s.start)}–${tc(s.end)}`), el("span", { class: "muted small" }, `${Math.round(s.dur)} s · ${s.wpm} wpm · ${Math.round(s.confidence * 100)}% on script`),
              s.edited ? el("span", { class: "tag2" }, "edited by you") : null),
            topic, sum, chips, lb, note,
            el("div", { class: "clBtns" }, el("button", { onclick: () => play(s) }, "▶ Play"),
              i + 1 < c.spans.length ? el("button", { class: "ghost", onclick: () => merge(s.id) }, "Join with next") : null,
              el("button", { class: "ghost", onclick: () => edit("edit", { id: s.id, skip: !s.skip }) }, s.skip ? "Use this span again" : "Skip: unusable")))));
      });
      main.append(box);
    }
  }

  /* ---------------------------------------------------------------- wiring */
  $("#clMode").addEventListener("click", e => { const b = e.target.closest("button"); if (!b) return; C.mode = b.dataset.m; App.store.set("clMode", C.mode); if (C.data) render(); });
  $("#clSkipped").onchange = () => C.data && C.data.clips && render();
  $("#clPick").onchange = () => { const [work, name] = JSON.parse($("#clPick").value); C.key = { work, name }; C.data = null; reload(); };
  $("#clRefresh").onclick = () => loadList(C.key);
  window.addEventListener("viewchange", e => { if (e.detail === "clips") loadList(C.key); else vid.pause(); });
  window.addEventListener("focus", () => { if (visible()) reload(); });
  if (visible()) loadList();
})();
