"use strict";
/* Watch and note (part 3 of the Build & review tab; stage 7): The creator watches the whole stitched half-size video and pins a note to the
   exact moment (N, or the button). Each note records the time, frame, section, beat, script line and the words being said, so Claude can
   act on it without guessing from a time code. Notes never block anything: they are the list Claude fixes from.
   Logic: tools/watchnotes.py, notes in <name>.watchnotes.json. */
(() => {
  const W = { key: null, d: null, loading: false, at: 0 };
  const vid = $("#wtVideo");
  const visible = () => document.body.dataset.view === "build";
  const q = () => `work=${encodeURIComponent(W.key.work)}&name=${encodeURIComponent(W.key.name)}`;
  const post = (op, body) => App.api(`/api/watch/${op}`, { ...W.key, ...body });
  const tc = t => App.fmtT(t, 1);
  const FPS = 30;

  async function loadList(pick) {
    const list = await App.api("/api/wf/videos");
    const vids = list.flatMap(w => w.names.map(n => ({ work: w.work, name: n })));
    if (!vids.length) { W.key = null; $("#wtBody").hidden = true; $("#wtEmpty").hidden = true; return; }
    const want = pick ? JSON.stringify([pick.work, pick.name]) : App.videoKey();
    const hit = vids.find(v => JSON.stringify([v.work, v.name]) === want) || vids[0];
    W.key = { work: hit.work, name: hit.name };
    await reload();
  }
  async function reload() {
    if (!W.key || W.loading) return;
    W.loading = true;
    try {
      const was = W.d && W.d.mtime;
      W.d = await App.api(`/api/watch?${q()}`);
      if (W.d.exists && W.d.mtime !== was) { vid.src = `/media/${encodeURIComponent(W.key.work)}/${encodeURIComponent(W.d.file)}?t=${W.d.mtime}`; }
      render();
    } catch (e) { App.toast(e.message, true, 8000); }
    W.loading = false;
  }
  App.watchReload = () => (visible() ? reload() : Promise.resolve());
  window.addEventListener("videopick", e => { W.key = e.detail; W.d = null; vid.removeAttribute("src"); reload(); });

  /* ---------------------------------------------------------------- render */
  function renderTop() {
    const d = W.d, box = $("#wtTop"); box.innerHTML = "";
    box.append(el("div", { class: "row" }, el("b", {}, "Watch the whole video"),
      el("span", { class: "muted small" }, `${d.dur ? tc(d.dur) : ""}${d.stitched ? ` · stitched ${new Date(d.stitched).toLocaleString()}` : ""} · ${d.open} open note${d.open !== 1 ? "s" : ""}, ${d.done} done`),
      el("span", { class: "spacer" }), el("button", { class: "ghost", onclick: () => App.setView("final") }, "Go to Final")));
    box.append(el("div", { class: "muted small" }, "Watch it once, all the way through. Press N (or the button) at any moment to pin a note there. , and . step one frame. Notes are the list Claude fixes from."));
  }
  function renderList() {
    const d = W.d, box = $("#wtList"); box.innerHTML = "";
    if (!d.notes.length) { box.append(el("div", { class: "muted small" }, "No notes yet.")); return; }
    for (const n of d.notes) {
      const where = [n.section ? `section ${n.section}` : null, n.beat ? `beat ${n.beat}` : null, n.line ? `line ${n.line}` : null].filter(Boolean).join(" · ");
      box.append(el("div", { class: `wtNote ${n.status}` },
        el("div", { class: "row" }, el("button", { class: "ghost", title: "Jump to this moment", onclick: () => { vid.currentTime = n.t; vid.scrollIntoView({ block: "center" }); } }, `▶ ${tc(n.t)}`),
          el("span", { class: "muted small" }, `frame ${n.frame}${where ? " · " + where : ""}`), n.older ? el("span", { class: "chip pend" }, "older preview") : null,
          el("span", { class: "spacer" }),
          el("button", { class: "ghost", onclick: () => act(n.status === "done" ? "reopen" : "done", { id: n.id }) }, n.status === "done" ? "Reopen" : "✓ Done"),
          el("button", { class: "ghost", onclick: () => { if (confirm("Delete this note?")) act("delete", { id: n.id }); } }, "✕")),
        el("div", { class: "wtText" }, n.text), n.said ? el("div", { class: "muted small" }, `“${n.said}”`) : null));
    }
  }
  function render() {
    const d = W.d;
    $("#wtEmpty").hidden = d.exists; $("#wtBody").hidden = !d.exists;
    if (d.exists) { renderTop(); renderList(); }
  }
  async function act(op, body) {
    try { W.d = await post(op, body); render(); } catch (e) { App.toast(e.message, true, 9000); }
  }

  /* ---------------------------------------------------------------- pinning */
  function openForm() {
    W.at = vid.currentTime; vid.pause();
    $("#wtNow").textContent = `Note at ${tc(W.at)} (frame ${Math.round(W.at * FPS)})`;
    $("#wtForm").hidden = false; $("#wtText").value = ""; $("#wtText").focus();
  }
  async function save() {
    const text = $("#wtText").value.trim(); if (!text) return;
    try { W.d = await post("add", { t: W.at, text }); $("#wtForm").hidden = true; $("#wtNow").textContent = ""; render(); App.toast("Note pinned"); }
    catch (e) { App.toast(e.message, true, 9000); }
  }
  $("#wtPin").onclick = openForm;
  $("#wtSave").onclick = save;
  $("#wtCancel").onclick = () => { $("#wtForm").hidden = true; $("#wtNow").textContent = ""; };
  $("#wtText").onkeydown = e => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); save(); } if (e.key === "Escape") $("#wtCancel").click(); };
  $("#wtBack").onclick = () => { vid.pause(); vid.currentTime = Math.max(0, vid.currentTime - 1 / FPS); };
  $("#wtFwd").onclick = () => { vid.pause(); vid.currentTime += 1 / FPS; };
  document.addEventListener("keydown", e => {
    const tag = (document.activeElement || {}).tagName;
    if (!visible() || ["INPUT", "TEXTAREA", "SELECT"].includes(tag) || e.ctrlKey || e.metaKey || e.altKey || $("#wtBody").hidden) return;
    const r = vid.getBoundingClientRect();
    if (r.bottom < 0 || r.top > innerHeight) return;                      // only when the player is on screen
    if (e.key === "n" || e.key === "N") { e.preventDefault(); openForm(); }
    else if (e.key === ",") { e.preventDefault(); $("#wtBack").click(); }
    else if (e.key === ".") { e.preventDefault(); $("#wtFwd").click(); }
  });

  window.addEventListener("viewchange", e => { if (e.detail === "build") loadList(W.key); else vid.pause(); });
  window.addEventListener("focus", () => { if (visible()) reload(); });
  if (visible()) loadList();
})();
