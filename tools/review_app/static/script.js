"use strict";
/* Script tab (step 1): read and edit the script without Claude, so nothing costs tokens. Click a line to change it, answer a
   [FILL] in a box, tick a [CONFIRM] as checked, add or remove a line, and undo anything from the version list. Every change
   saves the previous version first. Logic and file format: tools/scriptedit.py. Claude still writes and rewrites scripts in chat;
   "Ask Claude about this line" copies the line with its id so you can paste it there. Approval stays on the Dashboard tab. */
(() => {
  const S = { key: null, d: null, loading: false, open: null };      // open = {row, mode} for the editor that is showing
  const visible = () => document.body.dataset.view === "script";
  const q = () => `work=${encodeURIComponent(S.key.work)}&name=${encodeURIComponent(S.key.name)}`;
  const post = (op, body) => App.api(`/api/script/${op}`, { ...S.key, ...body });
  const mmss = s => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`;
  const MARK = /(\[(?:FILL|CONFIRM)[^\]]*\])/;

  async function loadList(pick) {
    const list = await App.api("/api/wf/videos");
    const vids = list.flatMap(w => w.names.map(n => ({ work: w.work, name: n })));
    const sel = $("#scPick"); sel.innerHTML = "";
    for (const v of vids) sel.append(el("option", { value: JSON.stringify([v.work, v.name]) }, v.work === v.name ? v.name : `${v.work} · ${v.name}`));
    $("#scEmpty").hidden = vids.length > 0; $("#scBody").hidden = !vids.length; sel.hidden = !vids.length;
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
      S.d = await App.api(`/api/script?${q()}`);
      render();
    } catch (e) { App.toast(e.message, true, 8000); }
    S.loading = false;
  }
  async function act(op, body, msg) {
    try { S.d = await post(op, body); S.open = null; render(); if (msg) App.toast(msg); return true; }
    catch (e) { App.toast(e.message, true, 9000); return false; }
  }

  /* ---------------------------------------------------------------- top */
  const META = [
    ["Logline", "Logline", "One sentence: who is trying to do what, what stands in the way, what is at stake. Every beat, title and thumbnail is checked against it."],
    ["Thesis", "What the video teaches", "The idea the whole video proves. The failures are the proof."],
    ["Promise", "Promise to the viewer", "What the viewer will know or be able to do when it ends."],
  ];
  function metaRow(d, key, label, hint) {
    const m = d.meta[key], editing = S.open && S.open.meta === key;
    const row = el("div", { class: "scMeta" }, el("div", { class: "muted small" }, label, m && m.draft ? el("span", { class: "chip pend" }, "draft") : null));
    if (editing) {
      const t = textarea(m ? m.text : "", hint, v => act("meta", { key, text: v }, `${label} saved`));
      row.append(t, el("div", { class: "row" }, el("button", { class: "accent", onclick: () => act("meta", { key, text: t.value }, `${label} saved`) }, "Save"),
        el("button", { class: "ghost", onclick: () => { S.open = null; render(); } }, "Cancel")));
      return row;
    }
    row.append(el("div", { class: "scMetaText" }, m ? m.text : el("span", { class: "bdWarn" }, `Not written yet. ${hint}`),
      el("button", { class: "ghost", onclick: () => { S.open = { meta: key }; render(); } }, m ? "✎" : "Write it")));
    return row;
  }
  function renderTop() {
    const d = S.d, st = d.stats, box = $("#scTop"); box.innerHTML = "";
    if (!d.exists) {
      box.append(el("b", {}, "No script yet."), el("div", { class: "muted small" }, "Ask Claude in the chat to write it. It will show up here, and you can edit it from here."));
      return;
    }
    box.append(el("div", { class: "row" }, el("b", {}, d.title || "Script"),
      el("span", { class: "muted small" }, `${st.lines} lines · ${st.words} spoken words · about ${mmss(st.est_s)} at ${st.wpm} words a minute`)));
    for (const [key, label, hint] of META) box.append(metaRow(d, key, label, hint));
    const open = [];
    if (st.fills) open.push(`${st.fills} [FILL] to answer`);
    if (st.confirms) open.push(`${st.confirms} [CONFIRM] to check`);
    if (st.open_notes) open.push(`${st.open_notes} open note${st.open_notes !== 1 ? "s" : ""}`);
    box.append(el("div", { class: open.length ? "bdWarn" : "small muted" }, open.length ? "⚠ Still open: " + open.join(" · ") : "Nothing open: every [FILL] is answered and every [CONFIRM] checked."));
    box.append(el("div", { class: "muted small" }, "Click ✎ to change a line. Nothing here uses Claude, and every change keeps the old version (Versions, top right). Wording help from Claude: “Ask Claude” copies the line, then paste it in the chat."));
    if (d.header.length) box.append(el("details", {}, el("summary", { class: "small muted" }, "About this draft"), el("div", { class: "finPre" }, d.header.join("\n"))));
  }

  /* ---------------------------------------------------------------- versions */
  function renderHist() {
    const d = S.d, box = $("#scHist"); box.innerHTML = "";
    box.hidden = !S.showHist;
    if (!S.showHist) return;
    box.append(el("b", {}, "Versions"), el("div", { class: "muted small" }, "The newest is at the top. Restore puts that version back and keeps the current one in this list."));
    if (!d.history.length) box.append(el("div", { class: "muted small" }, "No earlier versions yet: one is saved every time you change the script here."));
    for (const h of d.history) box.append(el("div", { class: "row small" }, el("span", { class: "muted" }, h.t), el("span", {}, `the script as it was before: ${h.what}`), el("span", { class: "spacer" }),
      el("button", { class: "ghost", onclick: () => { if (confirm(`Put back the script as it was before “${h.what}” (${h.t})? The current script is saved first.`)) act("restore", { file: h.file }, "Restored"); } }, "Restore")));
  }

  /* ---------------------------------------------------------------- lines */
  function textarea(value, ph, onsave, onrow) {
    const t = el("textarea", { placeholder: ph || "", rows: 3, class: "scTa" });
    t.value = value || "";
    t.onkeydown = e => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); onsave(t.value); }
      if (e.key === "Escape") { S.open = null; render(); }
    };
    setTimeout(() => t.focus(), 0);
    return t;
  }
  function editor(r) {
    const o = S.open;
    if (!o || o.row !== r.i) return null;
    const box = el("div", { class: "scEdit" });
    if (o.mode === "edit") {
      const t = textarea(r.body, "", v => act("edit", { row: r.i, old: r.text, text: v }, `${r.id} saved`));
      box.append(el("div", { class: "muted small" }, `Editing ${r.id}. [bracketed notes] stay in the line; delete them if you are done with them. Ctrl+Enter saves, Esc cancels.`), t,
        el("div", { class: "row" }, el("button", { class: "accent", onclick: () => act("edit", { row: r.i, old: r.text, text: t.value }, `${r.id} saved`) }, "Save"),
          el("button", { class: "ghost", onclick: () => { S.open = null; render(); } }, "Cancel"),
          el("button", { class: "ghost", onclick: () => navigator.clipboard.writeText(t.value).then(() => App.toast("Copied")) }, "Copy")));
    } else if (o.mode === "add") {
      const t = textarea("", "The new spoken line");
      box.append(el("div", { class: "muted small" }, `A new line goes right after ${r.id} and gets the next free id (the others keep theirs, so the shoot plan and clips still point at the right lines).`), t,
        el("div", { class: "row" }, el("button", { class: "accent", onclick: () => act("insert", { after: r.i, text: t.value }, "Line added") }, "Add the line"),
          el("button", { class: "ghost", onclick: () => { S.open = null; render(); } }, "Cancel")));
    } else if (o.mode === "mark") {
      const mk = r.markers[o.k];
      if (!mk) return null;
      if (mk.kind === "FILL") {
        const t = textarea("", "Your answer (it replaces the marker in the line)");
        box.append(el("div", { class: "muted small" }, mk.text), t,
          el("div", { class: "row" }, el("button", { class: "accent", onclick: () => act("fill", { row: r.i, old: r.text, k: o.k, answer: t.value }, "Answer saved") }, "Save the answer"),
            el("button", { class: "ghost", onclick: () => { S.open = null; render(); } }, "Cancel")));
      } else {
        box.append(el("div", { class: "muted small" }, mk.text),
          el("div", { class: "row" }, el("button", { class: "accent", onclick: () => act("fill", { row: r.i, old: r.text, k: o.k, answer: "" }, "Marked as checked") }, "✓ I checked it: remove the marker"),
            el("button", { class: "ghost", onclick: () => { S.open = { row: r.i, mode: "edit" }; render(); } }, "Change the line instead"),
            el("button", { class: "ghost", onclick: () => { S.open = null; render(); } }, "Cancel")));
      }
    }
    return box;
  }
  function body(r) {
    const d = el("div", { class: "scSay" });
    let k = 0;
    for (const part of r.body.split(MARK)) {
      if (!part) continue;
      if (MARK.test(part) && part.startsWith("[")) {
        const idx = k++, kind = part.startsWith("[FILL") ? "FILL" : "CONFIRM";
        d.append(el("button", { class: `scMark ${kind}`, title: kind === "FILL" ? "Click to answer" : "Click to confirm", onclick: () => { S.open = { row: r.i, mode: "mark", k: idx }; render(); } }, part));
      } else if (part.includes("[")) {
        for (const sub of part.split(/(\[[^\]]*\])/)) if (sub) d.append(sub.startsWith("[") ? el("span", { class: "spNote" }, sub) : sub);
      } else d.append(part);
    }
    return d;
  }
  function lineCard(r) {
    const c = el("div", { class: "scLine", id: `sl_${r.id}` });
    for (const v of r.visuals) c.append(el("div", { class: "scVis" }, v.text));
    c.append(el("div", { class: "scMain" }, el("b", { class: "scId" }, r.id), body(r),
      el("span", { class: "scBtns" },
        el("button", { class: "ghost", title: "Edit this line", onclick: () => { S.open = { row: r.i, mode: "edit" }; render(); } }, "✎"),
        el("button", { class: "ghost", title: "Add a line after this one", onclick: () => { S.open = { row: r.i, mode: "add" }; render(); } }, "＋"),
        el("button", { class: "ghost", title: "Copy this line to paste in the chat with Claude", onclick: () => navigator.clipboard.writeText(`About ${r.id} in the script (“${r.body.replace(/\[[^\]]*\]/g, "").trim()}”): `).then(() => App.toast("Copied: paste it in the chat")) }, "Ask Claude"),
        el("button", { class: "ghost", title: "Remove this line (and the notes attached to it)", onclick: () => {
          if (confirm(`Remove ${r.id}? Its picture and notes lines go with it. You can put it back from Versions.`)) act("delete", { row: r.i, old: r.text }, `${r.id} removed`);
        } }, "✕"))));
    const ed = editor(r); if (ed) c.append(ed);
    for (const n of r.notes) {
      const vo = n.vo && (S.d.voiceovers || []).find(x => x.id === n.vo);
      if (vo) { c.append(voInline(vo)); continue; }
      c.append(el("div", { class: `scNote${n.open ? " open" : ""}` }, n.text,
      n.open && !n.markers.length ? el("button", { class: "ghost", title: "Delete this note once it is dealt with", onclick: () => { if (confirm("Delete this note?")) act("delete", { row: n.i, old: n.text }, "Note removed"); } }, "Resolved") : null));
    }
    return c;
  }
  /* the takes of a voice-over (an audio file in the footage folder and a start and end in it): play one, pick the one to use */
  let voAudio = null;
  function playTake(t) {
    if (!voAudio) voAudio = new Audio();
    voAudio.pause();
    voAudio.src = `/fmedia/${encodeURIComponent(S.key.work)}/${encodeURIComponent(S.key.name)}/${t.file.split("/").map(encodeURIComponent).join("/")}`;
    voAudio.onloadedmetadata = () => { voAudio.currentTime = t.start; voAudio.play(); };
    voAudio.ontimeupdate = () => { if (voAudio.currentTime >= t.end) voAudio.pause(); };
    if (voAudio.readyState >= 1) { voAudio.currentTime = t.start; voAudio.play(); }
  }
  function voTakes(vo) {
    const box = el("div", { class: "scVOtakes" });
    (vo.takes || []).forEach((t, k) => {
      const len = (t.end - t.start).toFixed(0);
      box.append(el("span", { class: `scTake${k === vo.pick ? " use" : ""}` },
        el("button", { class: "ghost", title: t.note || "Play this take", onclick: () => playTake(t) }, `▶ Take ${k + 1} · ${len} s`),
        (vo.takes.length > 1) ? el("button", { class: k === vo.pick ? "" : "ghost", title: "Use this one", onclick: () => act("vo_takes", { id: vo.id, takes: vo.takes, pick: k }, `Take ${k + 1} chosen`) }, k === vo.pick ? "✓ in use" : "Use") : null));
    });
    if (!(vo.takes || []).length) box.append(el("span", { class: "muted small" }, "No recording attached yet."));
    return box;
  }
  /* a voice-over to record, as a card of its own: what to read, where it goes, how long, and a Recorded tick */
  function voInline(vo) {
    const rec = vo.status === "recorded";
    return el("div", { class: `scVO${rec ? " done" : ""}`, id: `vo_${vo.id}` },
      el("div", { class: "row" }, el("b", {}, `🎙 Voice-over ${vo.id}`), el("span", { class: "muted small" }, `plays at ${vo.at || vo.line}${vo.secs ? ` · about ${vo.secs}` : ""}`),
        el("span", { class: "spacer" }),
        el("button", { class: rec ? "" : "ghost", onclick: () => act("vo_mark", { id: vo.id, status: rec ? "todo" : "recorded" }) }, rec ? "✓ Recorded (click to undo)" : "Mark as recorded"),
        el("button", { class: "ghost", onclick: () => navigator.clipboard.writeText(vo.text).then(() => App.toast("Copied")) }, "Copy the words")),
      el("div", { class: "scVOtext" }, vo.text), voTakes(vo),
      el("details", { class: "small" }, el("summary", { class: "muted" }, "Why, the graphic, and when it gets cut"),
        el("div", { class: "muted small" }, vo.term ? `About: ${vo.term}` : ""), el("div", { class: "muted small" }, vo.why ? `Why it matters: ${vo.why}` : ""),
        el("div", { class: "muted small" }, vo.graphic ? `Graphic: ${vo.graphic}` : ""), el("div", { class: "muted small" }, vo.cut_if ? `Cut if: ${vo.cut_if}` : "")));
  }
  function renderVO() {
    const d = S.d, box = $("#scVO"); box.innerHTML = "";
    const list = d.voiceovers || [];
    box.hidden = !list.length;
    if (!list.length) return;
    const left = list.filter(v => v.status !== "recorded").length;
    box.append(el("div", { class: "row" }, el("b", {}, "🎙 Voice-overs to record"), el("span", { class: left ? "chip pend" : "chip restored" }, left ? `${left} to record` : "all recorded"),
      el("span", { class: "muted small" }, "Voice only, any quiet room, your own words are fine. Each one plays over a graphic at its line.")));
    for (const v of list) {
      const rec = v.status === "recorded";
      box.append(el("div", { class: `scVOrow${rec ? " done" : ""}` },
        el("span", { class: "scVOid" }, v.id), el("div", { class: "scVOtxt" }, el("div", { class: "scVOtext" }, v.text),
          el("div", { class: "muted small" }, `plays at ${v.at || v.line}${v.secs ? ` · about ${v.secs}` : ""}${v.cut_if ? ` · cut if: ${v.cut_if.slice(0, 80)}` : ""}`), voTakes(v)),
        el("span", { class: "scBtns", style: { opacity: 1 } },
          el("button", { class: "ghost", onclick: () => { const t = document.getElementById(`vo_${v.id}`) || document.getElementById(`sl_${v.at}`); if (t) t.scrollIntoView({ behavior: "smooth", block: "center" }); } }, `Go to ${v.at || v.line}`),
          el("button", { class: rec ? "" : "ghost", onclick: () => act("vo_mark", { id: v.id, status: rec ? "todo" : "recorded" }) }, rec ? "✓ Recorded" : "Recorded?"),
          el("button", { class: "ghost", onclick: () => navigator.clipboard.writeText(v.text).then(() => App.toast("Copied")) }, "Copy"))));
    }
  }
  function renderList() {
    const d = S.d, box = $("#scList"); box.innerHTML = "";
    if (!d.exists) return;
    for (const s of d.sections) {
      if (!s.has_lines) {                                              // notes sections (not spoken): collapsed, read only
        if (s.rows.length) box.append(el("details", { class: "scOther" }, el("summary", { class: "small muted" }, s.heading), el("div", { class: "finPre" }, s.rows.map(r => r.text).join("\n"))));
        continue;
      }
      box.append(el("div", { class: "spHead" }, s.heading, el("span", { class: "muted small", style: { fontWeight: 400 } }, `  ·  about ${mmss(s.est_s)} (${s.words} words)`)));
      for (const r of s.rows) if (r.kind === "line") box.append(lineCard(r));
    }
  }
  function render() { if (S.d) { renderTop(); renderVO(); renderHist(); renderList(); } }

  /* ---------------------------------------------------------------- wiring */
  $("#scPick").onchange = () => { const [work, name] = JSON.parse($("#scPick").value); S.key = { work, name }; S.d = null; S.open = null; reload(); };
  $("#scRefresh").onclick = () => loadList(S.key);
  $("#scHistoryBtn").onclick = () => { S.showHist = !S.showHist; render(); };
  $("#scVoBtn").onclick = () => { const b = $("#scVO"); if (!b.hidden) b.scrollIntoView({ behavior: "smooth", block: "start" }); };
  window.addEventListener("viewchange", e => { if (e.detail === "script") loadList(S.key); });
  window.addEventListener("focus", () => { if (visible() && !S.open) reload(); });       // the script changes while you are in the chat
  if (visible()) loadList();
})();
