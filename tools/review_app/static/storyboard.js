"use strict";
/* Storyboard tab: one frame per beat for the whole video, drawn by tools/storyboard.py from the real
   A-roll frames and the beat map (graphics as brand-style DRAFT cards placed where they don't cover
   the creator's face). The creator looks at every frame, marks it OK or "needs a change" (with a note); there is no approval (docs/adr/0003). A frame whose beat changed becomes "outdated" and loses its mark. Claude reads the notes and fixes the
   graphic's design, not the beat map, unless the creator wants the idea itself gone. */
(() => {
  const S = { key: null, d: null, wf: null, filter: App.store.get("sbFilter", "all"), loading: false, open: null };
  const q = () => `work=${encodeURIComponent(S.key.work)}&name=${encodeURIComponent(S.key.name)}`;
  const visible = () => document.body.dataset.view === "storyboard";
  const dlg = $("#sbDlg");
  const WHAT = { ok: "OK", change: "needs a change", unseen: "not looked at yet", outdated: "changed: rebuild", unbuilt: "not drawn yet" };

  /* ---------------------------------------------------------------- load */
  async function loadList(pick) {
    const list = await App.api("/api/wf/videos");
    const vids = list.flatMap(w => w.names.map(n => ({ work: w.work, name: n })));
    const sel = $("#sbPick"); sel.innerHTML = "";
    for (const v of vids) sel.append(el("option", { value: JSON.stringify([v.work, v.name]) }, v.work === v.name ? v.name : `${v.work} · ${v.name}`));
    $("#sbEmpty").hidden = vids.length > 0; $("#sbBody").hidden = !vids.length; sel.hidden = !vids.length;
    if (!vids.length) { S.key = null; return; }
    const want = pick ? JSON.stringify([pick.work, pick.name]) : App.videoKey();
    if (want && [...sel.options].some(o => o.value === want)) sel.value = want;
    const [work, name] = JSON.parse(sel.value);
    S.key = { work, name };
    await reload();
  }
  async function reload() {
    if (!S.key || S.loading) return;
    S.loading = true;
    try {
      App.setVideoKey(JSON.stringify([S.key.work, S.key.name]));
      S.d = await App.api(`/api/storyboard?${q()}`);
      render();
      if (dlg.open) showDlg(S.open);
    } catch (e) { App.toast(e.message, true, 8000); }
    S.loading = false;
  }
  App.storyboardReload = () => (visible() ? reload() : Promise.resolve());

  async function build(full) {
    try { App.watchJob(await App.api("/api/storyboard/build", { ...S.key, full: !!full })); }
    catch (e) { App.toast(e.message, true, 8000); }
  }
  async function mark(id, status, note = "") {
    try { S.d = await App.api("/api/storyboard/mark", { ...S.key, beat: id, status, note }); render(); }
    catch (e) { App.toast(e.message, true, 8000); }
  }

  /* ---------------------------------------------------------------- setup strip */
  function renderSetup() {
    const d = S.d, box = $("#sbSetup"); box.innerHTML = "";
    if (!d) return;
    if (!d.beatmap_ready) {
      box.append(el("div", { class: "row" }, el("b", {}, "No beat map yet."), el("span", { class: "muted small" }, "The storyboard is drawn from the beat map: build that first.")));
      return;
    }
    const c = d.counts, row = el("div", { class: "row" });
    row.append(el("button", { class: d.built ? "ghost" : "accent", onclick: () => build(false) },
      d.built ? (d.stale ? "Update the changed frames" : "Update (nothing changed)") : "Draw the storyboard"));
    if (d.built) row.append(el("button", { class: "ghost", onclick: () => confirm("Redraw every frame? Your OK marks stay on frames that did not change.") && build(true) }, "Redraw all"));
    box.append(row);
    const chips = [`${d.total} frames`, `${c.ok} OK`, `${c.change} need a change`, `${c.unseen} not looked at yet`];
    if (c.outdated + c.unbuilt) chips.push(`${c.outdated + c.unbuilt} need redrawing`);
    box.append(el("div", { class: "bmTotals" }, ...chips.map((t, i) => el("span", { class: (i === 2 && c.change) || (i === 4) ? "over" : "" }, t)),
      d.fix_flags ? el("span", { class: "over" }, `${d.fix_flags} with a problem`) : null));
    if (d.built && d.face_model === false)
      box.append(el("div", { class: "sbFlag" }, "No face model was available when these were drawn, so graphics were not checked against your face."));
    if (d.stale && d.built) box.append(el("div", { class: "sbFlag" }, "The beat map changed since the storyboard was drawn: update the changed frames."));
  }

  /* ---------------------------------------------------------------- grid */
  const shown = f => ({ all: true, graphics: !!f.kind, change: f.status === "change", unseen: f.status === "unseen" || f.status === "outdated" || f.status === "unbuilt",
                        problems: f.flags.some(x => x.level === "fix") })[S.filter];
  function renderFilter() {
    const box = $("#sbFilter"); box.innerHTML = "";
    for (const [k, l] of [["all", "All"], ["unseen", "Not looked at yet"], ["graphics", "With a graphic"], ["change", "Needs a change"], ["problems", "With a problem"]])
      box.append(el("button", { class: S.filter === k ? "on" : "", onclick: () => { S.filter = k; App.store.set("sbFilter", k); render(); } }, l));
  }
  function card(f) {
    const box = el("div", { class: `sbCard ${f.status}`, id: "sb-" + f.id });
    box.append(f.img ? el("img", { src: `/sbimg/${encodeURIComponent(S.key.work)}/${f.img}`, loading: "lazy", alt: f.id, onclick: () => openDlg(f.id) })
                     : el("div", { class: "muted small", style: { padding: "40px 10px", textAlign: "center" } }, "not drawn yet"));
    box.append(el("div", { class: "sbCap" }, el("b", {}, f.id), `  ${f.script_lines.join(", ")} · ${App.fmtT(f.start, 0)} · ${f.shot}${f.kind ? " + " + f.kind : ""}`, el("br"), f.said));
    for (const x of f.flags) box.append(el("div", { class: `sbFlag ${x.level}` }, (x.level === "fix" ? "✗ " : "◔ ") + x.text));
    if (f.status === "change" && f.mark_note) box.append(el("div", { class: "sbNote" }, f.mark_note));
    if (f.status === "outdated") box.append(el("div", { class: "sbFlag" }, "This beat changed: redraw before you look at it"));
    else if (f.img) box.append(el("div", { class: "row" },
      el("button", { class: f.status === "ok" ? "accent" : "ghost", onclick: () => mark(f.id, f.status === "ok" ? "" : "ok") }, "✓ OK"),
      el("button", { class: f.status === "change" ? "accent" : "ghost", onclick: () => openDlg(f.id, true) }, "✎ Change")));
    return box;
  }
  function render() {
    renderSetup(); renderFilter();
    const grid = $("#sbGrid"); grid.innerHTML = "";
    if (!S.d || !S.d.beatmap_ready) return;
    if (!S.d.built) { grid.append(el("div", { class: "card", style: { gridColumn: "1 / -1" } }, el("b", {}, "Nothing drawn yet."),
      el("p", { class: "muted small" }, "Press “Draw the storyboard”: it grabs a real frame of the planned take for every beat and drafts each graphic over it. Takes about a minute."))); return; }
    let sec = null, n = 0;
    for (const f of S.d.frames) {
      if (!shown(f)) continue;
      n++;
      if (f.section !== sec) { sec = f.section; if (sec) grid.append(el("div", { class: "sbHead" }, sec)); }
      grid.append(card(f));
    }
    if (!n) grid.append(el("div", { class: "muted", style: { gridColumn: "1 / -1" } }, "No frames match this filter."));
  }

  /* ---------------------------------------------------------------- big view with keys */
  const frames = () => (S.d ? S.d.frames.filter(f => f.img) : []);
  function openDlg(id, focusNote) { S.open = id; if (!dlg.open) dlg.showModal(); showDlg(id); if (focusNote) $("#sbDlgNote").focus(); }
  function showDlg(id) {
    const f = S.d && S.d.frames.find(x => x.id === id);
    if (!f) return dlg.open && dlg.close();
    $("#sbDlgTitle").textContent = `${f.id} · ${f.script_lines.join(", ")} · ${f.shot}${f.kind ? " + " + f.kind : ""} · ${WHAT[f.status]}`;
    $("#sbDlgImg").src = `/sbimg/${encodeURIComponent(S.key.work)}/${f.img}`;
    const info = $("#sbDlgInfo"); info.innerHTML = "";
    info.append(el("div", {}, f.said));
    if (f.idea) info.append(el("div", { class: "muted" }, `Graphic: ${f.idea}`));
    for (const x of f.flags) info.append(el("div", { class: `sbFlag ${x.level}` }, (x.level === "fix" ? "✗ " : "◔ ") + x.text));
    $("#sbDlgNote").value = f.mark_note || "";
  }
  function step(dir) {
    const list = frames(), i = list.findIndex(f => f.id === S.open);
    const next = list[i + dir]; if (next) { S.open = next.id; showDlg(next.id); }
  }
  async function okAndNext() { await mark(S.open, "ok"); step(1); }
  async function change() {
    const note = $("#sbDlgNote").value.trim();
    if (!note && !confirm("Mark this as needing a change without saying what?")) return;
    await mark(S.open, "change", note); step(1);
  }
  $("#sbPrev").onclick = () => step(-1); $("#sbNext").onclick = () => step(1);
  $("#sbOk").onclick = okAndNext; $("#sbChange").onclick = change;
  $("#sbDlgClose").onclick = () => dlg.close();
  dlg.addEventListener("keydown", e => {
    if (e.target.tagName === "INPUT") return;                  // typing a note
    if (e.key === "ArrowRight") { e.preventDefault(); step(1); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); step(-1); }
    else if (e.key === "o" || e.key === "O") { e.preventDefault(); okAndNext(); }
    else if (e.key === "c" || e.key === "C") { e.preventDefault(); $("#sbDlgNote").focus(); }
  });
  $("#sbDlgNote").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); change(); } });

  /* ---------------------------------------------------------------- wiring */
  $("#sbPick").onchange = () => { const [work, name] = JSON.parse($("#sbPick").value); S.key = { work, name }; S.d = null; reload(); };
  $("#sbRefresh").onclick = () => loadList(S.key);
  window.addEventListener("viewchange", e => { if (e.detail === "storyboard") loadList(S.key); });
  window.addEventListener("focus", () => { if (visible()) reload(); });
  if (visible()) loadList();
})();
