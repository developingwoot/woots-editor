"use strict";
/* Beat map tab: the plan for the whole video, one card per beat: what is said (the real words), which
   take plays, what is on screen (shot, B-roll, a proposed graphic), audio, and why. Claude writes the plan
   (tools/beatmap.py makes the starter from the script + the takes picked in the Clips tab); the creator reads it,
   strikes graphics he doesn't want and edits anything; there is no approval (docs/adr/0003). Each build saves the plan it starts from,
   and this tab shows what changed since. */
(() => {
  const B = { key: null, S: null, loading: false, playing: null, openTrim: new Set() };
  const vid = $("#bmVideo");
  const q = () => `work=${encodeURIComponent(B.key.work)}&name=${encodeURIComponent(B.key.name)}`;
  const visible = () => document.body.dataset.view === "beatmap";
  const enc = rel => rel.split("/").map(encodeURIComponent).join("/");
  const mediaUrl = rel => `/fmedia/${encodeURIComponent(B.key.work)}/${encodeURIComponent(B.key.name)}/${enc(rel)}`;
  const tc = t => App.fmtT(t, 0);
  const KINDS = ["explainer", "ui", "stamp", "counter", "burst", "3d", "kinetic", "title", "end"];
  const SHOTS = [["a-roll", "A-roll (wide)"], ["punch-in", "Punch-in on the speaker"], ["b-roll", "B-roll"], ["screenshot", "Screenshot"], ["graphic", "Full-frame graphic"], ["text", "Text card"]];
  const isCard = g => g && (g.kind === "title" || g.kind === "end");
  const live = b => (b.graphic && !b.graphic.struck && !b.skip ? b.graphic : null);

  /* ---------------------------------------------------------------- load */
  async function loadList(pick) {
    const list = await App.api("/api/wf/videos");
    const vids = list.flatMap(w => w.names.map(n => ({ work: w.work, name: n })));
    const sel = $("#bmPick"); sel.innerHTML = "";
    for (const v of vids) sel.append(el("option", { value: JSON.stringify([v.work, v.name]) }, v.work === v.name ? v.name : `${v.work} · ${v.name}`));
    $("#bmEmpty").hidden = vids.length > 0; $("#bmBody").hidden = !vids.length; sel.hidden = !vids.length;
    if (!vids.length) { B.key = null; return; }
    const want = pick ? JSON.stringify([pick.work, pick.name]) : App.videoKey();
    if (want && [...sel.options].some(o => o.value === want)) sel.value = want;
    const [work, name] = JSON.parse(sel.value);
    B.key = { work, name };
    await reload();
  }
  async function reload() {
    if (!B.key || B.loading) return;
    B.loading = true;
    try {
      App.setVideoKey(JSON.stringify([B.key.work, B.key.name]));
      B.S = await App.api(`/api/beatmap?${q()}`);
      render();
    } catch (e) { App.toast(e.message, true, 8000); }
    B.loading = false;
  }
  App.beatmapReload = () => (visible() ? reload() : Promise.resolve());

  /* ---------------------------------------------------------------- saving */
  async function send(op, body) {
    const why = ($("#bmWhy") || {}).value || "";
    const payload = { ...B.key, ...body, ...(why.trim() ? { why: why.trim() } : {}) };
    try {
      B.S = await App.api(`/api/beatmap/${op}`, payload);
      if (why.trim() && $("#bmWhy")) $("#bmWhy").value = "";
      render();
      return true;
    } catch (e) {
      App.toast(e.message, true, 8000);
      render();                                   // put the field back to what is saved
      return false;
    }
  }
  const setBeat = (id, sets) => send("edit", { beat: id, set: sets });
  async function build() { await send("build", {}); }
  async function resync() {
    if (!confirm("Take the latest takes from the Clips tab? Your plan (graphics, B-roll, audio, notes) is kept on every beat that still covers the same script lines.")) return;
    await send("resync", {});
  }

  /* ---------------------------------------------------------------- player */
  function play(b) {
    const a = b.aroll || (b.vo && { rel: b.vo.file, in: b.vo.start, out: b.vo.end });
    if (!a) return;
    $("#bmPlayerBox").hidden = false;
    const ranges = a.keep && a.keep.length ? a.keep : [[a.in, a.out]];
    B.playing = { ranges, k: 0 };
    if (b.vo) { vid.removeAttribute("poster"); }
    $("#bmPlayTitle").textContent = `${b.id}  ${base(a.rel)}  ${ranges.length > 1 ? `${ranges.length} pieces` : `${App.fmtT(a.in, 1)}–${App.fmtT(a.out, 1)}`}  (only the kept words)`;
    const url = mediaUrl(a.rel);
    const go = () => { vid.currentTime = ranges[0][0]; vid.play().catch(() => {}); };
    if (!vid.src.endsWith(url)) { vid.src = url; vid.addEventListener("loadedmetadata", go, { once: true }); } else go();
  }
  vid.addEventListener("timeupdate", () => {
    const p = B.playing; if (!p) return;
    if (vid.currentTime < p.ranges[p.k][1]) return;
    if (p.k + 1 < p.ranges.length) { p.k++; vid.currentTime = p.ranges[p.k][0]; } else vid.pause();
  });
  $("#bmPlayClose").onclick = () => { vid.pause(); B.playing = null; $("#bmPlayerBox").hidden = true; };

  /* ---------------------------------------------------------------- setup strip, risks, graphics list */
  function renderSetup() {
    const S = B.S, box = $("#bmSetup"); box.innerHTML = "";
    if (!S) return;
    const row = el("div", { class: "row" });
    if (!S.exists) {
      const can = S.script_ready && S.clips_ready;
      row.append(el("button", { class: "accent", disabled: !can, onclick: build }, "Build starter beat map"),
        el("span", { class: "muted small" }, can ? "One beat per script line (or group of lines read in one take), with the takes you picked. Then ask Claude to add the plan: B-roll, graphic ideas, audio and the reasons."
          : !S.script_ready ? "Needs the script first." : "Needs the takes matched to the script (Clips tab) first."));
      box.append(row);
      return;
    }
    const d = S.data;
    row.append(el("b", {}, `Beat map v${d.version || 1}`),
      el("button", { class: "ghost", onclick: resync, title: "Use the latest takes from the Clips tab; your plan is kept" }, "Update from clips"));
    if (S.diff) row.append(el("span", { class: "tag2 warn" }, `since the last build (v${S.diff.from}): ${S.diff.changed.length} changed, ${S.diff.added.length} added, ${S.diff.removed.length} removed`));
    box.append(row);
    const s = S.stats, over = s.graphics > s.budget;
    const pl = (n, one, many) => `${n} ${n === 1 ? one : many}`;
    box.append(el("div", { class: "bmTotals" },
      el("span", {}, `${App.fmtT(s.runtime_s, 0)} (talking only, before the cut-first list)`), el("span", {}, pl(s.beats, "beat", "beats")),
      el("span", {}, `${s.trimmed} trimmed to the words used`),
      el("span", { class: over ? "over" : "" }, `${pl(s.graphics, "motion explainer", "motion explainers")} of ${s.budget} budget`), el("span", {}, pl(s.popups, "pop-up", "pop-ups")), el("span", {}, pl(s.cards, "title/end card", "title/end cards")),
      s.struck ? el("span", {}, `${s.struck} cut by you`) : null,
      el("span", {}, `${s.broll} B-roll`), el("span", {}, pl(s.punch_ins, "punch-in", "punch-ins")), el("span", {}, pl(s.music, "music bed", "music beds")), el("span", {}, `${s.sfx} SFX`),
      s.missing ? el("span", { class: "over" }, `${pl(s.missing, "beat", "beats")} without footage`) : null));
    box.append(el("div", { class: "row" }, el("label", { class: "small muted" }, "Why (optional): saved with your next change"),
      el("input", { id: "bmWhy", placeholder: "e.g. too much for a short beat", style: { minWidth: "20em" } })));
  }

  /* teaching accuracy: Opus reads what is actually said and lists wrong numbers, missing steps, contradictions and mis-heard words (tools/accuracy.py) */
  async function renderAccuracy() {
    const box = $("#bmAccuracy"); box.innerHTML = "";
    if (!B.S || !B.S.exists) return;
    let A; try { A = await App.api(`/api/accuracy?${q()}`); } catch { return; }
    B.acc = A;
    const open = (A.findings || []).filter(f => !(A.dismissed || []).includes(f.id));
    const WRONG = { incorrect: "fix", misleading: "fix" };
    const fix = open.filter(f => WRONG[f.verdict]), look = open.filter(f => !WRONG[f.verdict]);
    const okc = (A.claims || []).filter(c => c.verdict === "correct");
    const d = el("details", { class: "bmPanel", open: fix.length > 0 || A.running },
      el("summary", {}, A.running ? "Fact check: checking…" : A.status ? `Fact check: ${okc.length} claims correct, ${fix.length} wrong or misleading, ${look.length} to look at${A.cost_usd ? ` · $${A.cost_usd.toFixed(2)}` : ""}` : "Fact check: not run yet"));
    d.append(el("div", { class: "row", style: { margin: "6px 0" } },
      el("button", { class: A.status ? "ghost" : "", disabled: !!A.running, onclick: async () => {
        if (!confirm("Ask Opus to fact-check what you say against the real world (it can search the web)? It takes a few minutes and costs about a dollar.")) return;
        try { await App.api("/api/accuracy/run", { ...B.key }); App.toast("Checking… this takes a couple of minutes"); renderAccuracy(); } catch (e) { App.toast(e.message, true, 8000); }
      } }, A.status ? "Check again" : "Fact-check what I say"),
      el("span", { class: "muted small" }, A.running ? "Opus is checking every claim about how things work, and searching the web where it is unsure…" : A.finished ? `last checked ${new Date(A.finished).toLocaleString()} · ${A.model}` : "Opus checks the claims you make about how things work against real-world facts (it can search the web and gives links). It does not compare with the script. It only reports: you decide.")));
    if (A.summary) d.append(el("div", { class: "small", style: { margin: "4px 0 8px" } }, A.summary));
    if (A.error && A.status === "failed") d.append(el("div", { class: "bmRisk fix" }, el("b", {}, "failed"), A.error));
    const srcs = f => (f.sources || []).filter(s => s && s.url).map(s => el("a", { href: s.url, target: "_blank", rel: "noopener", class: "small", style: { marginRight: "10px" } }, s.title || s.url));
    for (const f of [...fix, ...look])
      d.append(el("div", { class: `bmRisk ${WRONG[f.verdict] ? "fix" : "look"}` }, el("a", { onclick: () => jump(f.beat) }, f.beat), el("span", { class: "tag2" }, f.verdict),
        el("div", {}, el("div", { class: "muted small" }, `“${f.quote}”`), el("div", {}, f.explanation), f.suggestion ? el("div", { class: "small" }, el("b", {}, "Suggestion: "), f.suggestion) : null,
          (f.sources || []).length ? el("div", {}, ...srcs(f)) : null),
        el("button", { class: "ghost", onclick: async () => { await App.api("/api/accuracy/dismiss", { ...B.key, id: f.id }); renderAccuracy(); } }, "Dismiss")));
    if (okc.length) d.append(el("details", { class: "bmPanel" }, el("summary", { class: "small muted" }, `${okc.length} claims checked and correct`),
      ...okc.map(c => el("div", { class: "small", style: { margin: "4px 0" } }, el("a", { onclick: () => jump(c.beat) }, c.beat), `  “${c.quote.slice(0, 90)}”: `, el("span", { class: "muted" }, c.claim)))));
    box.append(d);
    clearTimeout(B.accT); if (A.running) B.accT = setTimeout(renderAccuracy, 4000);
  }

  function jump(id) {
    const n = document.getElementById("bm-" + id); if (!n) return;
    n.scrollIntoView({ block: "start", behavior: "smooth" });
    n.classList.add("flash"); setTimeout(() => n.classList.remove("flash"), 1600);
  }
  function renderRisks() {
    const S = B.S, box = $("#bmRisks"); box.innerHTML = "";
    if (!S || !S.exists) return;
    const fix = S.risks.filter(r => r.level === "fix"), look = S.risks.filter(r => r.level === "look");
    const d = el("details", { class: "bmPanel", open: fix.length > 0 },
      el("summary", {}, S.risks.length ? `Risks: ${fix.length} to fix, ${look.length} to look at` : "Risks: none found"));
    for (const r of [...fix, ...look])
      d.append(el("div", { class: `bmRisk ${r.level}` }, r.beat ? el("a", { onclick: () => jump(r.beat) }, r.beat) : el("b", {}, "all"), r.text));
    if (!S.risks.length) d.append(el("div", { class: "muted small" }, "Nothing needs fixing. (These checks cover the plan; the self-review checks the rendered video.)"));
    box.append(d);
  }
  function renderGfxList() {
    const S = B.S, box = $("#bmGfx"); box.innerHTML = "";
    if (!S || !S.exists) return;
    const gs = S.data.beats.filter(b => b.graphic);
    const d = el("details", { class: "bmPanel", open: gs.length > 0 }, el("summary", {}, `Graphics (${gs.length}): keep or cut`));
    if (S.weakest.length && S.stats.graphics > 0)
      d.append(el("div", { class: "row", style: { margin: "6px 0" } }, el("button", { class: "ghost", onclick: () => cutWeakest() },
        `Cut the ${S.weakest.length} weakest (${S.weakest.join(", ")})`), el("span", { class: "muted small" }, S.stats.graphics > S.stats.budget ? "to get back to your budget" : "offered as the first to cut")));
    for (const b of gs) {
      const g = b.graphic;
      d.append(el("div", { class: `bmG ${g.struck ? "struck" : ""}` },
        el("a", { onclick: () => jump(b.id) }, b.id), el("span", { class: "tag2 " + (isCard(g) ? "" : "good") }, g.kind),
        el("span", {}, `${g.idea || "(no idea written)"}  `, el("span", { class: "muted" }, g.words ? `· on “${g.words}” ` : ""), el("span", { class: "muted" }, g.why ? `· ${g.why}` : "")),
        el("span", { class: "muted small" }, `${g.dur || "?"} s · strength ${g.strength || "?"}`),
        el("button", { class: g.struck ? "ghost" : "", onclick: () => send("strike", { beats: [b.id], struck: !g.struck }) }, g.struck ? "Restore" : "Cut")));
    }
    box.append(d);
  }
  function cutWeakest() {
    if (!confirm(`Cut ${B.S.weakest.join(", ")}? You can restore them any time.`)) return;
    send("strike", { beats: B.S.weakest, struck: true });
  }

  /* ---------------------------------------------------------------- beats */
  const field = (label, value, onchange, type = "text", ph = "") => {
    const i = el("input", { type, value: value ?? "", placeholder: ph });
    i.onchange = () => onchange(type === "number" ? +i.value : i.value);
    return el("div", {}, el("label", {}, label), i);
  };
  const area = (label, value, onchange, ph = "") => {
    const t = el("textarea", { placeholder: ph }, value ?? "");
    t.onchange = () => onchange(t.value);
    return el("div", {}, el("label", {}, label), t);
  };
  const select = (label, value, options, onchange) => {
    const s = el("select", {}, ...options.map(o => el("option", { value: o[0] ?? o, selected: (o[0] ?? o) === value }, o[1] ?? o)));
    s.onchange = () => onchange(s.value);
    return el("div", {}, el("label", {}, label), s);
  };

  /* the words of the take around this beat: kept ones play, cut ones are struck, dashed ones lie outside the clip the Clips tab matched.
     Click a word to cut or restore it (shift-click a second word to do a whole stretch); "Save trim" keeps the choice for good. */
  function trimStrip(b) {
    const a = b.aroll; if (!a || !(a.words || []).length) return null;
    const inSpan = w => w[1] >= a.span_in - 0.001 && w[2] <= a.span_out + 0.001;
    const mid = w => (w[1] + w[2]) / 2;
    const keptNow = a.keep ? a.words.map(w => a.keep.some(([x, y]) => mid(w) >= x - 0.001 && mid(w) <= y + 0.001)) : a.words.map(inSpan);
    const st = keptNow.slice();
    const box = el("div", { class: "bmTrim" }), line = el("div", { class: "bmWords" }), info = el("span", { class: "muted small" });
    const chips = []; let last = null;
    const count = () => {
      const n = st.filter(Boolean).length, dirty = st.some((v, i) => v !== keptNow[i]);
      info.textContent = `${n} of ${a.words.length} words kept${a.keep ? ` · ${a.dur.toFixed(1)} s` : " (the whole matched clip)"}${dirty ? " · not saved yet" : ""}`;
      save.disabled = !dirty || !n;
      chips.forEach((c, i) => c.className = `bmW ${st[i] ? "on" : "off"} ${inSpan(a.words[i]) ? "" : "out"}`);
    };
    a.words.forEach((w, i) => {
      if (i && w[1] - a.words[i - 1][2] > 0.6) line.append(el("span", { class: "bmGap" }, `${(w[1] - a.words[i - 1][2]).toFixed(1)} s`));
      const c = el("span", { title: `${App.fmtT(w[1], 1)}`, onclick: e => {
        if (e.shiftKey && last !== null) { const to = !st[i]; for (let k = Math.min(i, last); k <= Math.max(i, last); k++) st[k] = to; } else st[i] = !st[i];
        last = i; count();
      } }, w[0]);
      chips.push(c); line.append(c, " ");
    });
    const save = el("button", { onclick: () => send("trim", { beat: b.id, kept: st.map((v, i) => v ? i : -1).filter(i => i >= 0) }) }, "Save trim");
    box.append(el("div", { class: "row" }, info, el("span", { class: "spacer" }),
      a.keep ? el("span", { class: "tag2" }, a.trim_by === "claude" ? "trimmed by Claude" : "trimmed by you") : null,
      b.aroll ? el("button", { class: "ghost", onclick: () => play(b) }, "▶ Play what is kept") : null,
      el("button", { class: "ghost", onclick: () => send("trim", { beat: b.id, reset: true }), disabled: !a.keep, title: "Go back to the whole clip the Clips tab matched" }, "Whole clip"), save), line,
      el("div", { class: "muted small" }, "Click a word to cut or restore it. Shift-click a second word for a whole stretch. Dashed words are outside the clip the Clips tab matched (extra takes of the same sentence, or the end of a sentence that stopped short). A silence over 1.5 s inside what you keep is cut."));
    count();
    const d = el("details", { class: "bmPanel bmTrimBox", open: B.openTrim.has(b.id) || !!a.keep }, el("summary", {}, a.keep ? "Words kept and cut" : "Trim the words"), box);
    d.addEventListener("toggle", () => d.open ? B.openTrim.add(b.id) : B.openTrim.delete(b.id));
    return d;
  }

  function beatCard(b) {
    const g = b.graphic, shot = b.on_screen.shot;
    const card = el("div", { class: `bmBeat ${live(b) ? "hasg" : ""} ${b.missing ? "missing" : ""} ${b.skip ? "skip" : ""}`, id: "bm-" + b.id });
    card.append(el("div", { class: "bmHead" }, el("b", {}, b.id),
      el("span", { class: "tag2" }, b.script_lines.join(", ")), el("span", { class: "muted small" }, `${tc(b.start)}–${tc(b.end)} · ${b.dur.toFixed(1)} s`),
      b.aroll || b.vo ? el("button", { onclick: () => play(b) }, "▶") : null,
      b.vo ? el("span", { class: "tag2 good" }, `🎙 voice-over ${b.vo.id}`) : null,
      b.vo ? el("span", { class: "muted small" }, `plays after ${b.vo.after} · ${base(b.vo.file)} ${App.fmtT(b.vo.start, 1)}–${App.fmtT(b.vo.end, 1)}`) : null,
      b.aroll ? el("span", { class: "muted small" }, `${base(b.aroll.rel)} ${App.fmtT(b.aroll.in, 1)}–${App.fmtT(b.aroll.out, 1)}`) : (b.vo ? null : el("span", { class: "tag2 warn" }, "no footage")),
      ...(b.flags || []).map(f => el("span", { class: "tag2 warn" }, f)),
      el("span", { class: "spacer" }),
      el("label", { class: "small" }, el("input", { type: "checkbox", checked: b.skip, onchange: e => setBeat(b.id, { skip: e.target.checked }) }), " leave this beat out")));
    card.append(el("div", { class: "bmSaid" }, b.said));
    const strip = trimStrip(b); if (strip) card.append(strip);

    // left: picture
    const pic = el("div", { class: "bmCol" },
      select("On screen", shot, SHOTS, v => setBeat(b.id, { "on_screen.shot": v })),
      field("Picture note (what exactly is shown)", b.on_screen.note, v => setBeat(b.id, { "on_screen.note": v })));
    for (const br of b.on_screen.broll || []) pic.append(el("div", { class: "bmBroll" }, `B-roll: ${br.file || "?"} ${br.in != null ? App.fmtT(br.in, 1) : ""} · ${br.dur || "?"} s · ${br.why || "no reason"}`));
    if (g) {
      pic.append(el("div", { class: `bmGfx ${g.struck ? "struck" : ""}` },
        el("div", { class: "row" }, el("b", {}, "Graphic"), el("span", { class: "spacer" }),
          el("button", { class: g.struck ? "ghost" : "", onclick: () => send("strike", { beats: [b.id], struck: !g.struck }) }, g.struck ? "Restore this graphic" : "Cut this graphic")),
        select("Kind", g.kind, KINDS, v => setBeat(b.id, { "graphic.kind": v })),
        select("Where on screen", g.place || "auto", [["auto", "Automatic (least over your face)"], ["full", "Full screen"], ["left35", "Left column, 35% width"], ["right35", "Right column, 35% width"], ["bl33", "Bottom-left corner, 33% width"]], v => setBeat(b.id, { "graphic.place": v })),
        field("Idea", g.idea, v => setBeat(b.id, { "graphic.idea": v })),
        field("Timed to the words", g.words, v => setBeat(b.id, { "graphic.words": v })),
        field("On-screen text", g.text, v => setBeat(b.id, { "graphic.text": v })),
        el("div", { class: "row" }, field("Seconds", g.dur, v => setBeat(b.id, { "graphic.dur": v }), "number"),
          field("Strength 1-5", g.strength, v => setBeat(b.id, { "graphic.strength": v }), "number")),
        field("Why this graphic", g.why, v => setBeat(b.id, { "graphic.why": v }))));
    } else {
      pic.append(el("div", { class: "row", style: { marginTop: "6px" } }, el("button", { class: "ghost", onclick: () => setBeat(b.id, { "graphic.kind": "explainer" }) }, "+ Add a graphic here")));
    }
    // right: sound + why
    const snd = el("div", { class: "bmCol" },
      field("Music (exact track name; beats with the same name share one bed)", b.audio.music, v => setBeat(b.id, { "audio.music": v }), "text", "TrackTribe - Boardwalk"),
      area("Sound effects (one per line: file name @ seconds, or @graphic)", (b.audio.sfx || []).join("\n"), v => setBeat(b.id, { "audio.sfx": v }), "ding-idea @graphic"),
      field("Why this beat looks like this", b.why, v => setBeat(b.id, { why: v })),
      field("Cut it if…", b.cut_if, v => setBeat(b.id, { cut_if: v })),
      field("Your note", b.user_note, v => setBeat(b.id, { user_note: v })));
    card.append(el("div", { class: "bmCols" }, pic, snd));
    return card;
  }

  function render() {
    renderSetup(); renderRisks(); renderAccuracy(); renderGfxList();
    const box = $("#bmBeats"), extra = $("#bmExtra"); box.innerHTML = ""; extra.innerHTML = "";
    const S = B.S;
    if (!S || !S.exists) return;
    let sec = null;
    for (const b of S.data.beats) {
      if (b.section !== sec) { sec = b.section; if (sec) box.append(el("div", { class: "bmSec" }, sec)); }
      box.append(beatCard(b));
    }
    const orphans = S.data.orphans || [];
    if (orphans.length) {
      const d = el("details", { class: "bmPanel" }, el("summary", {}, `Plans that lost their beat (${orphans.length})`),
        el("p", { class: "muted small" }, "These graphics or notes were on beats whose script lines changed when the takes were updated. Re-add them where they still fit."));
      for (const o of orphans) d.append(el("div", { class: "bmRisk look" }, `${o.script_lines.join(", ")}: ${o.graphic ? `${o.graphic.kind} “${o.graphic.idea || ""}”` : ""} ${o.user_note || ""}`));
      extra.append(d);
    }
    const ch = (S.data.changes || []).slice(-15).reverse();
    if (ch.length) {
      const d = el("details", { class: "bmPanel" }, el("summary", {}, `History (${S.data.changes.length})`));
      for (const c of ch) d.append(el("div", { class: "small" }, el("span", { class: "muted" }, new Date(c.t).toLocaleString() + "  "),
        `${c.who}: ${c.what || (c.beat ? c.beat + " " + Object.keys(c.set || {}).join(", ") : (c.beats || []).join(", "))}`, c.why ? el("span", { class: "muted" }, `  (why: ${c.why})`) : ""));
      extra.append(d);
    }
  }

  /* ---------------------------------------------------------------- wiring */
  $("#bmPick").onchange = () => { const [work, name] = JSON.parse($("#bmPick").value); B.key = { work, name }; B.S = null; reload(); };
  $("#bmRefresh").onclick = () => loadList(B.key);
  window.addEventListener("viewchange", e => { if (e.detail === "beatmap") loadList(B.key); else vid.pause(); });
  window.addEventListener("focus", () => { if (visible()) reload(); });
  if (visible()) loadList();
})();
