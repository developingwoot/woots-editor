"use strict";
/* Shoot plan tab: the shot list that comes between the approved script and the filming (what the industry calls a shot list,
   a B-roll list and pickups). Claude writes <name>.shootplan.json from the script; here the creator ticks shots off while filming,
   attaches clips he already has, and adds pickups. His ticks go to <name>.shootplan.marks.json so the plan can be rewritten
   without losing them. Logic: tools/shootplan.py. Every script line needs a recording (an A-roll session) and a picture. */
(() => {
  const P = { key: null, d: null, loading: false };
  const visible = () => document.body.dataset.view === "shootplan";
  const q = () => `work=${encodeURIComponent(P.key.work)}&name=${encodeURIComponent(P.key.name)}`;
  const post = (op, body) => App.api(`/api/shootplan/${op}`, { ...P.key, ...body });
  const KIND = { a_roll: "A-roll: you saying it", b_roll: "B-roll", screen: "Screen recording", reuse: "No new filming" };
  const STATUS = [["todo", "To shoot"], ["shot", "Shot ✓"], ["have", "Have it ✓"], ["skip", "Skip"]];

  async function loadList(pick) {
    const list = await App.api("/api/wf/videos");
    const vids = list.flatMap(w => w.names.map(n => ({ work: w.work, name: n })));
    const sel = $("#spPick"); sel.innerHTML = "";
    for (const v of vids) sel.append(el("option", { value: JSON.stringify([v.work, v.name]) }, v.work === v.name ? v.name : `${v.work} · ${v.name}`));
    $("#spEmpty").hidden = vids.length > 0; $("#spBody").hidden = !vids.length; sel.hidden = !vids.length;
    if (!vids.length) { P.key = null; return; }
    const want = pick ? JSON.stringify([pick.work, pick.name]) : App.videoKey();
    if (want && [...sel.options].some(o => o.value === want)) sel.value = want;
    const [work, name] = JSON.parse(sel.value);
    P.key = { work, name };
    await reload();
  }
  async function reload() {
    if (!P.key || P.loading) return;
    P.loading = true;
    try {
      App.setVideoKey(JSON.stringify([P.key.work, P.key.name]));
      P.d = await App.api(`/api/shootplan?${q()}`);
      render();
    } catch (e) { App.toast(e.message, true, 8000); }
    P.loading = false;
  }
  async function act(op, body, msg) {
    try { P.d = await post(op, body); render(); if (msg) App.toast(msg); }
    catch (e) { App.toast(e.message, true, 8000); }
  }

  /* ---------------------------------------------------------------- top */
  function renderTop() {
    const d = P.d, box = $("#spTop"); box.innerHTML = "";
    if (!d.exists) {
      box.append(el("b", {}, "No shoot plan yet."),
        el("div", { class: "muted small" }, d.lines.length ? "Ask Claude: “write the shoot plan from the script”. It lists every shot you need, tied to the script lines, and checks what you already have in the footage folder."
          : "Write the script first (the plan is made from it)."));
      return;
    }
    const c = d.counts;
    box.append(el("div", { class: "row" }, el("b", {}, `${c.must_done} of ${c.must} must-have shots in hand`),
      el("span", { class: "muted small" }, `${c.done} of ${c.shots} shots · ${c.a_roll_done} of ${c.a_roll} recording sessions${c.pickups_open ? ` · ${c.pickups_open} pickup${c.pickups_open !== 1 ? "s" : ""} open` : ""}`)));
    for (const w of d.warnings) box.append(el("div", { class: "bdWarn" }, "⚠ " + w));
    if (d.notes) box.append(el("div", { class: "muted small" }, d.notes));
    box.append(el("div", { class: "row small" }, el("span", { class: "muted" }, d.folder ? `Footage folder${d.folder_how === "guessed" ? " (guessed from the title)" : ""}: ${d.folder} · ${d.clips.length} clips` : "No footage folder."),
      el("button", { class: "ghost", onclick: chooseFolder }, d.folder ? "Change…" : "Choose the footage folder…"),
      d.folder && d.folder_how === "guessed" ? el("button", { class: "ghost", onclick: () => saveFolder(d.folder) }, "Use this folder") : null));
    const view = App.store.get("spView") === "script" ? "script" : "shot";
    const tog = el("div", { class: "chips" });
    for (const [v, label] of [["shot", "By shot"], ["script", "By script (read it with its shots)"]])
      tog.append(el("button", { class: view === v ? "on" : "", onclick: () => { App.store.set("spView", v); render(); } }, label));
    box.append(tog);
    if (view === "shot") {
      const hide = el("input", { type: "checkbox", checked: !!App.store.get("spHideDone") });
      hide.onchange = () => { App.store.set("spHideDone", hide.checked ? "1" : ""); render(); };
      box.append(el("label", { class: "small row" }, hide, "Hide shots that are done"));
    }
  }
  async function saveFolder(folder) {
    try { await App.api("/api/footage/folder", { ...P.key, folder }); App.toast("Folder saved"); await reload(); }
    catch (e) { App.toast(e.message, true, 8000); }
  }
  function chooseFolder() {
    App.pickFolder({ suggest: P.d.folder ? [P.d.folder] : [], start: P.d.folder, pick: async folder => saveFolder(folder) });
  }

  /* ---------------------------------------------------------------- shots */
  function lineText(id) { const l = P.d.lines.find(x => x.id === id); return l ? l.said : ""; }
  function card(r) {
    const lines = el("div", { class: "spLines" }, r.lines.map(i => `${i}`).join(", ") + (r.on_camera && r.on_camera.length ? `  ·  on camera: ${r.on_camera.join(", ")}` : ""),
      r.lines.length ? el("span", { title: r.lines.map(i => `${i}: ${lineText(i)}`).join("\n") }, "  ⓘ") : null);
    const c = el("div", { class: `spShot ${r.status}`, id: `sp-${r.id}` },
      el("div", { class: "row" }, el("b", {}, r.id), el("span", { class: `spKind ${r.kind}` }, KIND[r.kind] || r.kind),
        r.fps ? el("span", { class: "muted small" }, `${r.fps} fps`) : null,
        r.must === false ? el("span", { class: "muted small" }, "nice to have") : null),
      el("div", { class: "spWhat" }, r.what),
      r.how ? el("div", { class: "spHow" }, r.how) : null, lines,
      r.takes_total ? el("div", { class: r.takes_missing.length ? "spGap" : "small", style: r.takes_missing.length ? {} : { color: "var(--ok)" } },
        r.takes_missing.length ? `Takes: ${r.takes_total - r.takes_missing.length} of ${r.takes_total} in hand. Missing: ${r.takes_missing.join(", ")}`
          : `✓ All ${r.takes_total} ${r.lines.length ? "lines have" : "voice-overs have"} a recording${r.auto ? " (found in the Clips tab)" : ""}`) : null);
    if (r.files.length || r.suggest.length) {
      const f = el("div", { class: "spFiles" });
      for (const x of r.files) f.append(el("span", { class: `chip ${r.missing_files.includes(x) ? "pend" : "restored"}`, title: x }, x.split("/").pop(), " ",
        el("a", { style: { cursor: "pointer" }, title: "Detach", onclick: () => act("detach", { shot: r.id, file: x }) }, "✕")));
      for (const x of r.suggest) f.append(el("button", { class: "ghost", title: `Claude thinks this covers ${r.id}: ${x}`, onclick: () => act("accept", { shot: r.id, file: x }, "Attached") }, `Use ${x.split("/").pop()}`));
      c.append(f);
    }
    const acts = el("div", { class: "spActs" });
    for (const [v, label] of STATUS) {
      if (r.kind === "reuse" && v !== "skip" && v !== "todo") continue;
      acts.append(el("button", { class: r.status === v ? "on" : "", onclick: () => act("mark", { shot: r.id, status: v }) }, label));
    }
    if (d_clips().length) {
      const sel = el("select", {}, el("option", { value: "" }, "Attach a clip…"), ...d_clips().map(x => el("option", { value: x.rel }, `${x.rel} (${x.mb} MB)`)));
      sel.onchange = () => { if (sel.value) act("attach", { shot: r.id, file: sel.value }, "Attached"); };
      acts.append(sel);
    }
    const note = el("input", { placeholder: "Note (what you got, what to redo)", value: r.note || "", style: { flex: "1", minWidth: "10em" } });
    note.onchange = () => act("mark", { shot: r.id, status: r.status, note: note.value });
    acts.append(note);
    c.append(acts);
    return c;
  }
  const d_clips = () => (P.d && P.d.clips) || [];
  /* The A/V script view: the script as written, one row per line, with the shots that cover it beside it. */
  function renderByScript(box) {
    const d = P.d, by = {};
    for (const r of d.shots) for (const i of r.lines || []) (by[i] = by[i] || []).push(r);
    const pic = (id) => (by[id] || []).some(r => r.kind !== "a_roll" || (r.on_camera || []).includes(id));
    const voice = (id) => (by[id] || []).some(r => r.kind === "a_roll");
    box.append(el("div", { class: "muted small" }, "The script with its shots. Orange = still to shoot, green = shot or have it. Click a shot to jump to it. Edit the words in the chat with Claude; this view only reads the script."));
    let last = null;
    for (const l of d.lines) {
      if (l.heading !== last) { box.append(el("div", { class: "spHead" }, l.heading || "Script")); last = l.heading; }
      const words = el("div", { class: "spSay" });
      for (const part of l.text.split(/(\[[^\]]*\])/)) if (part) words.append(part.startsWith("[") ? el("span", { class: "spNote" }, part) : part);
      const chips = el("div", { class: "spChips" });
      for (const r of by[l.id] || []) {
        const on = (r.on_camera || []).includes(l.id);
        chips.append(el("button", { class: `spChip ${r.status} ${r.kind}`, title: `${r.id} · ${KIND[r.kind] || r.kind}${on ? " · you are on camera for this line" : ""}\n${r.what}`,
          onclick: () => { App.store.set("spView", "shot"); App.store.set("spHideDone", ""); render(); const t = document.getElementById(`sp-${r.id}`); if (t) t.scrollIntoView({ block: "center" }); } },
          `${r.kind === "a_roll" ? "A-roll " : ""}${r.id}${on ? " ●" : ""}`));
      }
      const gaps = [];
      if (!voice(l.id)) gaps.push("not in a recording session");
      if (!pic(l.id)) gaps.push("no picture planned");
      if (l.open) gaps.push("has an open [FILL]/[CONFIRM]");
      box.append(el("div", { class: `spLine${gaps.length ? " gap" : ""}` },
        el("b", {}, l.id), el("div", {}, words, gaps.length ? el("div", { class: "spGap" }, "⚠ " + gaps.join(" · ")) : null), chips));
    }
  }
  function renderShots() {
    const d = P.d, box = $("#spList"); box.innerHTML = "";
    if (!d.exists) return;
    if (App.store.get("spView") === "script") return renderByScript(box);
    const hide = !!App.store.get("spHideDone");
    const G = [
      ["shoot", "🎬 Still to shoot", "Nothing in the footage folder covers these yet.", true],
      ["confirm", "👀 Footage found: please confirm", "The app found a clip that looks right. Press its “Use” button if it is, or pick another with “Attach a clip”.", true],
      ["editor", "✂ The editor makes these (no filming)", "Montages, cards and captions built from footage you already have.", true],
      ["done", "✓ Shot or in hand", "Done. Click a shot to change it.", !hide],
      ["skip", "Skipped", "You decided not to shoot these.", !hide],
    ];
    for (const [key, title, sub, show] of G) {
      const items = d.shots.filter(r => r.group === key);
      if (!show || (!items.length && key !== "shoot")) continue;
      const must = items.filter(r => r.must !== false).length;
      const head = el("div", { class: `spGroup ${key}` }, el("b", {}, `${title} (${items.length})`),
        key === "shoot" && items.length ? el("span", { class: "muted small" }, `  ${must} must-have, ${items.length - must} nice to have`) : null, el("div", { class: "muted small" }, sub));
      box.append(head);
      if (!items.length) { box.append(el("div", { class: "spNone" }, key === "shoot" ? "Nothing left to shoot. 🎉" : "None.")); continue; }
      const sorted = key === "shoot" ? [...items.filter(r => r.must !== false), ...items.filter(r => r.must === false)] : items;
      const wrap = key === "skip" ? el("details", {}, el("summary", { class: "small muted" }, `Show the ${items.length} skipped`)) : el("div", {});
      for (const r of sorted) wrap.append(card(r));
      box.append(wrap);
    }
  }

  /* ---------------------------------------------------------------- pickups */
  function renderPickups() {
    const d = P.d, box = $("#spPickups"); box.innerHTML = "";
    if (!d.exists) return;
    box.append(el("b", {}, "Pickups"), el("div", { class: "muted small" }, "Shots you realise you need that are not in the plan: a line you want to add, an unscripted take, a cutaway you missed. Add them here as you think of them."));
    for (const p of d.pickups) {
      const done = el("input", { type: "checkbox", checked: p.status === "shot" });
      done.onchange = () => act("pickup_mark", { id: p.id, status: done.checked ? "shot" : "todo" });
      box.append(el("div", { class: "row small" }, done, el("b", {}, p.id), el("span", {}, p.what), p.lines.length ? el("span", { class: "muted" }, p.lines.join(", ")) : null,
        el("button", { class: "ghost", onclick: () => act("pickup_del", { id: p.id }) }, "✕")));
    }
    const what = el("input", { placeholder: "e.g. A-roll: my frustration that V3 wasn't the last version", style: { flex: "1", minWidth: "14em" } });
    const lines = el("input", { placeholder: "Script lines (optional, e.g. S38)", style: { width: "11em" } });
    box.append(el("div", { class: "row" }, what, lines, el("button", { onclick: () => {
      if (!what.value.trim()) return;
      act("pickup_add", { what: what.value, lines: lines.value.split(/[ ,]+/).filter(x => /^S\d{2,3}$/i.test(x)).map(x => x.toUpperCase()) });
    } }, "Add pickup")));
  }

  function render() { if (P.d) { renderTop(); renderShots(); renderPickups(); } }

  /* ---------------------------------------------------------------- wiring */
  $("#spPick").onchange = () => { const [work, name] = JSON.parse($("#spPick").value); P.key = { work, name }; P.d = null; reload(); };
  $("#spRefresh").onclick = () => loadList(P.key);
  $("#spCopy").onclick = () => {
    if (!P.d) return;
    navigator.clipboard.writeText(P.d.checklist || "").then(() => App.toast("Copied the to-shoot list"), () => App.toast("Could not copy", true));
  };
  window.addEventListener("viewchange", e => { if (e.detail === "shootplan") loadList(P.key); });
  window.addEventListener("focus", () => { if (visible()) reload(); });
  if (visible()) loadList();
})();
