"use strict";
/* Self-review tab (stage 6): Claude checks its own work on the stitched half-size preview before the creator watches it.
   tools/selfreview.py runs eight checks (a graphic that flashes, text that lands too late to read, an animation that plays
   twice, a graphic on the creator's face, a word said twice in a row, lips drifting from the voice, dead air at a cut, picture and
   sound of different lengths). This tab shows the verdict, which checks actually ran, and each finding with a still, the
   time, and a proposed fix. "Looked, it's fine" dismisses a finding (kept across re-runs). A clean pass is only claimed
   when every check ran and nothing is open. */
(() => {
  const R = { key: null, d: null, loading: false, timer: null, stopAt: null };
  const vid = $("#srVideo");
  const q = () => `work=${encodeURIComponent(R.key.work)}&name=${encodeURIComponent(R.key.name)}`;
  const visible = () => document.body.dataset.view === "build";           // part 2 of the Build & review tab
  const mmss = t => App.fmtT(t, 1);
  const post = async (op, body = {}) => {
    try { R.d = await App.api(`/api/selfreview/${op}`, { ...R.key, ...body }); render(); return true; }
    catch (e) { App.toast(e.message, true, 9000); return false; }
  };

  /* ---------------------------------------------------------------- load */
  async function loadList(pick) {
    const list = await App.api("/api/wf/videos");
    const vids = list.flatMap(w => w.names.map(n => ({ work: w.work, name: n })));
    const sel = $("#srPick"); sel.innerHTML = "";
    for (const v of vids) sel.append(el("option", { value: JSON.stringify([v.work, v.name]) }, v.work === v.name ? v.name : `${v.work} · ${v.name}`));
    $("#srEmpty").hidden = vids.length > 0; $("#srBody").hidden = !vids.length; sel.hidden = !vids.length;
    if (!vids.length) { R.key = null; return; }
    const want = pick ? JSON.stringify([pick.work, pick.name]) : App.videoKey();
    if (want && [...sel.options].some(o => o.value === want)) sel.value = want;
    const [work, name] = JSON.parse(sel.value);
    R.key = { work, name };
    await reload();
  }
  async function reload() {
    if (!R.key || R.loading) return;
    R.loading = true;
    try {
      App.setVideoKey(JSON.stringify([R.key.work, R.key.name]));
      R.d = await App.api(`/api/selfreview?${q()}`);
      render();
    } catch (e) { App.toast(e.message, true, 8000); }
    R.loading = false;
  }
  App.selfreviewReload = () => (visible() ? reload() : Promise.resolve());
  async function run() {
    try { App.watchJob(await App.api("/api/selfreview/run", { ...R.key })); }
    catch (e) { App.toast(e.message, true, 9000); }
  }

  /* ---------------------------------------------------------------- player */
  vid.addEventListener("timeupdate", () => { if (R.stopAt != null && vid.currentTime >= R.stopAt) { vid.pause(); R.stopAt = null; } });
  function watch(f) {
    $("#srPlayerBox").hidden = false;
    $("#srPlayTitle").textContent = `${f.id} · ${mmss(f.t)} · ${f.text.slice(0, 70)}`;
    const url = `/media/${encodeURIComponent(R.key.work)}/${encodeURIComponent(R.d.preview_file || R.key.name + ".preview-half.mp4")}?t=${encodeURIComponent(R.d.generated || "")}`;
    const go = () => { vid.currentTime = Math.max(0, f.t - 1.5); R.stopAt = (f.t_end || f.t) + 2.5; vid.play().catch(() => {}); };
    if (!vid.src.includes(encodeURIComponent(R.key.name))) { vid.src = url; vid.addEventListener("loadedmetadata", go, { once: true }); } else go();
  }
  $("#srPlayClose").onclick = () => { vid.pause(); $("#srPlayerBox").hidden = true; };

  /* ---------------------------------------------------------------- render */
  function renderSetup() {
    const d = R.d, box = $("#srSetup"); box.innerHTML = "";
    const row = el("div", { class: "row" });
    row.append(el("button", { class: d.ran && !d.stale ? "ghost" : "accent", disabled: !d.preview_ready, onclick: run }, d.ran ? "Run the self-review again" : "Run the self-review"));
    if (!d.preview_ready) row.append(el("span", { class: "muted small" }, "Needs the stitched preview: build every section and press Stitch in the Build tab."));
    if (d.generated) row.append(el("span", { class: "muted small" }, `last run ${new Date(d.generated).toLocaleString()}${d.fixed_since_last ? ` · ${d.fixed_since_last} problem${d.fixed_since_last !== 1 ? "s" : ""} fixed since the run before` : ""}`));
    box.append(row);
    if (!d.ran) { box.append(el("div", { class: "srVerdict" }, "Not run yet. It takes about half a minute for a short video: it re-transcribes the preview, looks at every graphic frame by frame, and checks sync.")); return; }
    const notRan = d.checks.filter(c => !c.ran);
    let cls, msg;
    if (d.stale) { cls = "partial"; msg = "The preview changed after this run. Run it again before you trust these results."; }
    else if (d.clean) { cls = "clean"; msg = `✓ Clean pass: all ${d.checks.length} checks ran and nothing is left to fix${d.counts.dismissed ? ` (${d.counts.dismissed} dismissed by you)` : ""}.`; }
    else if (notRan.length) { cls = "partial"; msg = `Not a clean pass: ${notRan.map(c => c.label.toLowerCase()).join("; ")} did not run. ${d.counts.fix} to fix, ${d.counts.look} to look at.`; }
    else { cls = "dirty"; msg = `${d.counts.fix} to fix, ${d.counts.look} to look at${d.counts.dismissed ? `, ${d.counts.dismissed} dismissed` : ""}. Claude fixes the "to fix" items and runs this again before you watch the video.`; }
    box.append(el("div", { class: `srVerdict ${cls}` }, msg));
  }
  function renderChecks() {
    const d = R.d, box = $("#srChecks"); box.innerHTML = "";
    if (!d.ran) return;
    box.append(el("b", {}, "The checks"));
    for (const c of d.checks) {
      const n = d.findings.filter(f => f.check === c.id).length;
      box.append(el("div", { class: `srCheck ${c.ran ? "ok" : "no"}` }, el("span", { class: "ic" }, c.ran ? "✓" : "○"), el("span", {}, c.label),
        el("span", { class: "muted" }, c.note), el("span", { class: n ? "tag2 warn" : "muted" }, c.ran ? (n ? `${n} open` : "0") : "not run")));
    }
  }
  function card(f, dismissed) {
    const img = f.still ? el("img", { src: `/srimg/${encodeURIComponent(R.key.work)}/${f.still}?v=${encodeURIComponent(R.d.generated)}`, loading: "lazy", alt: f.id, onclick: () => watch(f) })
                        : el("div", { class: "srNoImg" }, "no picture");
    const label = (R.d.checks.find(c => c.id === f.check) || {}).label || f.check;
    const box = el("div", { class: `srCard ${f.level}` }, img, el("div", {},
      el("div", { class: "row" }, el("b", {}, mmss(f.t) + (f.t_end ? `–${mmss(f.t_end)}` : "")), el("span", { class: "tag2" }, label),
        f.beat ? el("span", { class: "muted small" }, `${f.beat}${f.section ? " · " + f.section : ""}`) : null),
      el("div", {}, f.text), el("div", { class: "srFix" }, "Fix: " + f.fix),
      dismissed && f.why ? el("div", { class: "muted small" }, `You said: ${f.why}`) : null,
      el("div", { class: "row", style: { marginTop: "6px" } }, f.t != null && f.check !== "av_length" ? el("button", { onclick: () => watch(f) }, "▶ Watch it") : null,
        dismissed ? el("button", { class: "ghost", onclick: () => post("undismiss", { key: f.key }) }, "Undo: it was a problem")
                  : el("button", { class: "ghost", onclick: () => { const why = prompt("You looked and it is fine. Why? (optional, saved so Claude learns your taste)", ""); if (why !== null) post("dismiss", { key: f.key, why }); } }, "I looked, it's fine"))));
    return box;
  }
  function render() {
    if (!R.d) return;
    renderSetup(); renderChecks();
    const list = $("#srList"), dis = $("#srDismissed"); list.innerHTML = ""; dis.innerHTML = "";
    const d = R.d;
    for (const [lvl, title] of [["fix", "To fix"], ["look", "To look at"]]) {
      const fs = d.findings.filter(f => f.level === lvl).sort((a, b) => a.t - b.t);
      if (!fs.length) continue;
      list.append(el("div", { class: "srHead" }, `${title} (${fs.length})`));
      for (const f of fs) list.append(card(f, false));
    }
    if (d.dismissed.length) {
      const det = el("details", { class: "bmPanel" }, el("summary", {}, `Dismissed by you (${d.dismissed.length})`));
      for (const f of d.dismissed) det.append(card(f, true));
      dis.append(det);
    }
  }

  /* ---------------------------------------------------------------- wiring */
  $("#srPick").onchange = () => { const [work, name] = JSON.parse($("#srPick").value); R.key = { work, name }; R.d = null; reload(); };
  $("#srRefresh").onclick = () => loadList(R.key);
  window.addEventListener("videopick", e => { R.key = e.detail; R.d = null; reload(); });      // the Build tab's picker drives this section too
  window.addEventListener("viewchange", e => { if (e.detail === "build") loadList(R.key); else vid.pause(); });
  window.addEventListener("focus", () => { if (visible()) reload(); });
  if (visible()) loadList();
})();
