"use strict";
/* Graphics tab (replaces the first-version Graphics editor), two parts:
   1 · Plan the look: one card per graphic from the beat map, with its storyboard still. The creator picks a look for each (plain brand card, 3D depth,
       comic sticker, UI explainer, kinetic type), adds a note, and marks it OK, needs a change, or cut. There is no approval (docs/adr/0003).
       The beat map is not changed by this: his choices are kept in <name>.graphicsplan.json and laid on top of it (tools/gfxplan.py).
   2 · Review the built graphics: each graphic plays in context in the stitched half-size preview; he marks it OK or says what to change. A change request
       makes the graphic "not built" again; rebuilding that section in the Build & review tab gives Claude his note. Graphics render once at full size, so check them before the final (unfinished ones only warn). */
(() => {
  const G = { key: null, plan: null, rev: null, loading: false, stopAt: null };
  const vid = $("#grVideo");
  const visible = () => document.body.dataset.view === "graphics";
  const q = () => `work=${encodeURIComponent(G.key.work)}&name=${encodeURIComponent(G.key.name)}`;
  const tc = t => App.fmtT(t, 1);

  async function loadList(pick) {
    const list = await App.api("/api/wf/videos");
    const vids = list.flatMap(w => w.names.map(n => ({ work: w.work, name: n })));
    const sel = $("#grPick"); sel.innerHTML = "";
    for (const v of vids) sel.append(el("option", { value: JSON.stringify([v.work, v.name]) }, v.work === v.name ? v.name : `${v.work} · ${v.name}`));
    $("#grEmpty").hidden = vids.length > 0; $("#grBody").hidden = !vids.length; sel.hidden = !vids.length;
    if (!vids.length) { G.key = null; return; }
    const want = pick ? JSON.stringify([pick.work, pick.name]) : App.videoKey();
    if (want && [...sel.options].some(o => o.value === want)) sel.value = want;
    const [work, name] = JSON.parse(sel.value);
    G.key = { work, name };
    await reload();
  }
  async function reload() {
    if (!G.key || G.loading) return;
    G.loading = true;
    try {
      App.setVideoKey(JSON.stringify([G.key.work, G.key.name]));
      [G.plan, G.rev] = await Promise.all([App.api(`/api/gfxplan?${q()}`), App.api(`/api/gfxreview?${q()}`)]);
      const src = G.rev.preview ? `/media/${encodeURIComponent(G.key.work)}/${encodeURIComponent(G.rev.preview.file)}?t=${G.rev.preview.mtime}` : "";
      if (src && !vid.src.endsWith(src.slice(src.indexOf("/media/")))) vid.src = src;
      render();
    } catch (e) { App.toast(e.message, true, 8000); }
    G.loading = false;
  }
  App.graphicsReload = () => (visible() ? reload() : Promise.resolve());
  const post = async (path, body) => {
    try { const d = await App.api(path, { ...G.key, ...body }); if (path.includes("gfxplan")) G.plan = d; else G.rev = d; render(); App.dashRefresh && App.dashRefresh(); return true; }
    catch (e) { App.toast(e.message, true, 9000); return false; }
  };

  /* ---------------------------------------------------------------- 1 · the plan */
  function planCard(c) {
    const P = G.plan;
    const img = c.still ? el("img", { class: "grStill", src: `/sbimg/${encodeURIComponent(G.key.work)}/${c.still}`, loading: "lazy", alt: c.beat }) : el("div", { class: "grStill ph" }, "no still");
    const looks = el("div", { class: "chips" }, ...P.styles.map(s => el("button", { class: c.style === s.id ? "on" : "", title: s.desc,
      onclick: () => post("/api/gfxplan/set", { beat: c.beat, style: c.style === s.id ? "" : s.id }) }, s.label)));
    const note = el("input", { placeholder: "Note for Claude: what should it look like, what must it show?", value: c.note, style: { width: "100%" } });
    note.onchange = () => post("/api/gfxplan/set", { beat: c.beat, note: note.value });
    const stat = el("div", { class: "grStat" }, ...[["ok", "✓ OK"], ["change", "✎ Needs a change"], ["cut", "✕ Cut it"]].map(([v, l]) =>
      el("button", { class: c.status === v ? `on ${v}` : "", onclick: () => post("/api/gfxplan/set", { beat: c.beat, status: c.status === v ? "" : v }) }, l)));
    const chosen = P.styles.find(s => s.id === c.style);
    return el("div", { class: `grCard ${c.status || "new"}` }, img,
      el("div", { class: "grBody" },
        el("div", { class: "row" }, el("b", {}, c.beat), el("span", { class: "spKind" }, c.kind), c.is_card ? el("span", { class: "muted small" }, "title / end card") : null,
          c.strength ? el("span", { class: "muted small", title: "Claude's rating of how much this graphic earns its place (1 = weakest)" }, `strength ${c.strength}/5`) : null,
          el("span", { class: "muted small" }, `${c.dur ? c.dur + " s" : ""}${c.start != null ? " · at " + tc(c.start) : ""}`)),
        el("div", {}, c.idea || "(no idea written)"),
        c.text ? el("div", { class: "small" }, `On-screen text: “${c.text}”`) : null,
        c.words ? el("div", { class: "small muted" }, `Lands on the words: “${c.words}”`) : null,
        c.why ? el("div", { class: "small muted" }, `Why it is here: ${c.why}`) : null,
        el("div", { class: "small muted" }, "Look:"), looks,
        chosen ? el("div", { class: "small muted" }, chosen.desc) : null,
        note, stat));
  }
  function renderPlan() {
    const P = G.plan, box = $("#grPlan"); box.innerHTML = "";
    if (!P.beatmap_ready) { box.append(el("div", { class: "card" }, el("b", {}, "No beat map yet."), el("div", { class: "muted small" }, "The graphics are planned from the beat map."))); return; }
    const c = P.counts;
    const top = el("div", { class: "card" }, el("div", { class: "row" }, el("b", {}, "1 · Plan the look"),
      el("span", { class: "muted small" }, `${c.graphics} motion explainers · ${c.popups} pop-ups · ${c.cards} title/end cards · ${c.styled} with a look · ${c.ok} OK · ${c.change} need a change · ${c.cut} cut`),
      el("span", { class: "spacer" })),
      el("div", { class: "muted small" }, "Choose how each graphic should look before anything is built; changing a look after it is built means rebuilding it. Cut the ones that are not earning their place. Nothing here changes your beat map."));
    for (const w of P.warnings) top.append(el("div", { class: "bdWarn" }, "⚠ " + w));
    if (P.stale) top.append(el("button", { class: "accent", onclick: () => post("/api/gfxplan/ack", {}) }, "I've seen the changes"));
    box.append(top);
    for (const card of P.cards) box.append(planCard(card));
    if (!P.cards.length) box.append(el("div", { class: "card muted small" }, "The beat map has no graphics, so there is nothing to plan."));
  }

  /* ---------------------------------------------------------------- 2 · the review */
  function playIn(c) {
    if (c.t == null) return;
    vid.currentTime = Math.max(0, c.t - 1); G.stopAt = c.t + (c.dur || 3) + 1; vid.play().catch(() => {});
    vid.scrollIntoView({ block: "center" });
  }
  vid.addEventListener("timeupdate", () => { if (G.stopAt != null && vid.currentTime >= G.stopAt) { vid.pause(); G.stopAt = null; } });
  function reviewCard(c) {
    const note = el("input", { placeholder: "If it needs a change: what exactly? (Claude gets this when the section is rebuilt)", value: c.note || "", style: { width: "100%" } });
    const mark = (status) => post("/api/gfxreview/mark", { beat: c.beat, status, note: note.value });
    const badge = !c.built ? el("span", { class: "chip pend" }, "not built yet") : c.rebuilt ? el("span", { class: "chip pend" }, "rebuilt with your note: look again")
      : c.looked_at_older ? el("span", { class: "chip pend" }, "rebuilt since you looked") : null;
    return el("div", { class: `grCard ${c.status || "new"}` },
      el("div", { class: "grBody" },
        el("div", { class: "row" }, el("b", {}, c.beat), el("span", { class: "spKind" }, c.kind), badge, c.style ? el("span", { class: "muted small" }, `look: ${c.style}`) : null,
          el("span", { class: "spacer" }), el("button", { disabled: c.t == null, title: c.t == null ? "needs a built section and a stitched preview" : "Play this graphic in the video", onclick: () => playIn(c) }, "▶ Play in context")),
        el("div", { class: "small" }, c.idea), c.text ? el("div", { class: "small muted" }, `Text: “${c.text}”`) : null,
        c.plan_note ? el("div", { class: "small muted" }, `Your design note: ${c.plan_note}`) : null,
        note,
        el("div", { class: "grStat" },
          el("button", { class: c.status === "ok" ? "on ok" : "", disabled: !c.built, onclick: () => mark(c.status === "ok" ? "" : "ok") }, "✓ OK"),
          el("button", { class: c.status === "change" ? "on change" : "", disabled: !c.built, onclick: () => mark("change") }, "✎ Needs a change"))));
  }
  function renderReview() {
    const R = G.rev, box = $("#grReview"); box.innerHTML = "";
    $("#grPlayer").hidden = !R.preview;
    if (!R.beatmap_ready) return;
    const c = R.counts;
    const top = el("div", { class: "card" }, el("div", { class: "row" }, el("b", {}, "2 · Review the built graphics"),
      el("span", { class: "muted small" }, `${c.graphics} graphics · ${c.built} built · ${c.ok} OK · ${c.change} need a change · ${c.unseen} not looked at`),
      el("span", { class: "spacer" }), el("button", { class: "ghost", onclick: () => App.setView("build") }, "Go to Build & review")),
      el("div", { class: "muted small" }, "Play each graphic where it sits in the video. Mark it OK, or say what to change: it becomes 'not built' and the Build tab offers a rebuild that gives Claude your note."));
    for (const w of R.warnings) top.append(el("div", { class: "bdWarn" }, "⚠ " + w));
    box.append(top);
    for (const card of R.cards) box.append(reviewCard(card));
  }
  function render() { if (G.plan && G.rev) { renderPlan(); renderReview(); } }

  /* ---------------------------------------------------------------- wiring */
  $("#grPick").onchange = () => { const [work, name] = JSON.parse($("#grPick").value); G.key = { work, name }; G.plan = G.rev = null; window.dispatchEvent(new CustomEvent("videopick", { detail: { work, name } })); reload(); };
  $("#grRefresh").onclick = () => loadList(G.key);
  for (const b of document.querySelectorAll("#grCol [data-jump]")) b.onclick = () => document.getElementById(b.dataset.jump).scrollIntoView({ behavior: "smooth", block: "start" });
  window.addEventListener("videopick", e => { if (G.key && (G.key.work !== e.detail.work || G.key.name !== e.detail.name)) { G.key = e.detail; G.plan = G.rev = null; if (visible()) reload(); } });
  window.addEventListener("viewchange", e => { if (e.detail === "graphics") loadList(G.key); else vid.pause(); });
  window.addEventListener("focus", () => { if (visible()) reload(); });
  if (visible()) loadList();
})();
