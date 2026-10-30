"use strict";
/* Dashboard (the old Workflow tab): a strip with the plan and how much of it this application uses, a list of every video as a card (thumbnail, stage dots, next step,
   warnings, share of this app's use), and on the right the selected video's stages (done / waiting), its own usage, settings and history.
   State lives in tools/workflow.py; usage in tools/usage.py. There are no approvals (docs/adr/0003): a stage is done when its file exists.
   Claude makes the files; the creator works in the tabs.
   The selected video is also the one every other tab opens on. See docs/workflow.md. */
(() => {
  const W = { dash: null, key: null, S: null, U: null, loading: false };
  const q = () => `work=${encodeURIComponent(W.key.work)}&name=${encodeURIComponent(W.key.name)}`;
  const post = (op, body) => App.api(`/api/wf/${op}`, body);
  const visible = () => document.body.dataset.view === "workflow";
  const STATUS = { waiting: "not started", done: "done", ready: "ready" };
  const SETTINGS = [
    ["preview_size", "Preview size (width × height)", "size"],
    ["max_parallel", "Background builds at once (max 3)", 1],
    ["graphics_per_minute", "Graphics per minute of talking", 0.1],
    ["graphics_extra", "Extra graphics (title + end cards)", 1],
    ["min_visible_s", "Nothing on screen shorter than (s)", 0.1],
    ["read_s_per_word", "Reading time per word (s)", 0.05],
    ["read_pad_s", "Reading time added to every text (s)", 0.1],
    ["lip_tolerance_frames", "Lips vs voice tolerance (frames)", 1],
    ["build_model", "Graphics model", ["sonnet", "opus", "haiku", "fable"]],
    ["build_effort", "Graphics effort", ["low", "medium", "high", "xhigh", "max"]],
    ["build_budget_usd", "Graphics cost cap per run ($)", 0.5],
    ["critic_model", "Graphics critic model (looks at each built explainer, then the graphics model fixes what it finds)", ["off", "opus", "sonnet", "fable"]],
    ["critic_effort", "Graphics critic effort", ["low", "medium", "high", "xhigh", "max"]],
    ["critic_budget_usd", "Graphics critic cost cap ($)", 0.25],
    ["voice_chain", "Final: voice processing (warmer, less bright)", "bool"],
    ["music_below_speech_db", "Final: music below the speech (LU)", 1],
    ["duck_db", "Final: music dips while you talk (dB)", 1],
    ["manual_hours_before", "Time: hours a video like this used to take by hand", 0.5],
    ["hours_actual", "Time: hours it took you this time", 0.5],
    ["hourly_rate_usd", "Time: what an hour of your time is worth ($)", 1],
  ];
  const money = x => x == null ? "—" : `$${(+x).toFixed(x < 10 ? 2 : 0)}`;
  const pct = x => `${(x * 100).toFixed(x >= 0.1 ? 0 : 1)}%`;
  const big = n => n >= 1e9 ? `${(n / 1e9).toFixed(1)}B` : n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}K` : `${Math.round(n)}`;
  const dur = s => s == null ? "" : s >= 60 ? `${Math.floor(s / 60)} min ${Math.round(s % 60)} s` : `${Math.round(s)} s`;
  const DOT = { done: "ok", ready: "ask" };

  /* ---------------------------------------------------------------- load */
  async function loadList(pick) {
    W.dash = await App.api("/api/dash");
    const vids = W.dash.videos;
    $("#wfEmpty").hidden = vids.length > 0;
    $("#wfBody").hidden = vids.length === 0;
    if (!vids.length) { W.key = null; renderCards(); renderStrip(); return; }
    const want = pick ? JSON.stringify([pick.work, pick.name]) : App.videoKey();
    const hit = vids.find(v => JSON.stringify([v.work, v.name]) === want) || vids[0];
    W.key = { work: hit.work, name: hit.name };
    renderCards(); renderStrip();
    await refresh();
  }
  async function refresh() {
    if (!W.key || W.loading) return;
    W.loading = true;
    try {
      W.S = await App.api(`/api/wf/state?${q()}`);
      App.setVideoKey(JSON.stringify([W.key.work, W.key.name]));
      render();
      loadChanges();
      loadResolve();
      W.U = (await App.api(`/api/usage?${q()}`)).video;
      renderVideoUsage();
    } catch (e) { App.toast(e.message, true, 8000); }
    W.loading = false;
  }
  function pickVideo(v) {
    W.key = { work: v.work, name: v.name }; W.S = null; W.U = null;
    App.setVideoKey(JSON.stringify([v.work, v.name]));
    window.dispatchEvent(new CustomEvent("videopick", { detail: { work: v.work, name: v.name } }));       // the Build & review tab follows
    renderCards(); refresh();
  }

  /* ---------------------------------------------------------------- the strip: your Claude plan and how much of it this application uses */
  function renderStrip() {
    const box = $("#wfUsage"); box.innerHTML = "";
    const D = W.dash; if (!D) return;
    const w = D.week, snap = w.snapshot;
    box.append(el("div", { class: "row" }, el("b", {}, snap ? `Your Claude plan (${snap.plan || "plan"})` : "Your Claude plan"),
      el("span", { class: "muted small" }, snap ? `limits read ${snap.age_minutes == null ? "" : snap.age_minutes < 2 ? "just now" : snap.age_minutes < 90 ? `${snap.age_minutes} min ago` : `${Math.round(snap.age_minutes / 60)} h ago`}; every Claude run the app starts refreshes them`
        : "plan limits not read yet"), el("span", { class: "spacer" }),
      el("button", { class: "ghost", title: "Asks Claude (haiku, no tools, about 4,000 tokens) to report your plan's limits", onclick: async e => {
        e.target.disabled = true; e.target.textContent = "Reading…";
        try { W.dash.week = await App.api("/api/dash/plan/refresh", {}); renderStrip(); renderCards(); refresh(); } catch (err) { App.toast(err.message, true, 9000); e.target.disabled = false; e.target.textContent = "↻ Update now"; }
      } }, "↻ Update now")));
    const tiles = el("div", { class: "wfTiles" });
    if (w.window.source === "expired") box.append(el("div", { class: "bdWarn" }, "The plan's weekly window has reset since the last reading, so those percentages are out of date: press Update now."));
    if (snap && snap.windows && w.window.source !== "expired") {
      const bars = el("div", { class: "dashShares" });
      for (const x of snap.windows)
        bars.append(el("div", { class: `dashShare${x.percentUsed >= 90 ? " warn" : ""}` }, el("span", { class: "small" }, x.label),
          el("span", { class: "dashBar" }, el("i", { style: { width: `${Math.min(100, x.percentUsed)}%` } })), el("span", { class: "small" }, `${x.percentUsed}% · resets in ${x.resetsIn || ""}`)));
      tiles.append(el("div", { class: "wfTile wide" }, el("div", { class: "muted small" }, "Used so far (all of your Claude use: this application, other chats, claude.ai)"), bars));
    }
    const mine = w.app_pct_of_plan;
    tiles.append(el("div", { class: "wfTile wide" }, el("div", { class: "muted small" }, "This application"),
      el("div", { class: "wfBig" }, mine != null ? `≈ ${mine}% of your weekly limit` : `${pct(w.app_share)} of Claude Code use on this PC`),
      el("div", { class: "small muted" }, `${big(w.app)} of ${big(w.machine)} weighted tokens used by Claude Code on this PC in this window (${pct(w.app_share)}). ` +
        (mine != null ? `With the plan at ${w.weekly_pct}% for the week, that is roughly ${mine}% of the limit.` : "Add the plan limits to turn that into a share of the weekly limit.")),
      el("details", {}, el("summary", { class: "small" }, "How this is worked out, and what it cannot see"),
        el("div", { class: "small muted" }, "Every Claude Code chat on this PC is saved with its token counts; this application is the chat workspace it is built and used in plus the Build board's background runs. " +
          "Tokens are weighted by how they are priced (input 1, cache writes 1.25, cache reads 0.1, output 5), so this is an estimate of how heavy the use was. " +
          "Your plan's own percentage also counts Claude on the web or phone, which this PC cannot see, so the share of the limit is a rough figure, not a measurement."))));
    box.append(tiles);
    if (D.saved) box.append(el("div", { class: "small muted" }, D.saved));
  }

  /* ---------------------------------------------------------------- the video cards on the left */
  function renderCards() {
    const box = $("#dashCards"); box.innerHTML = "";
    const D = W.dash; if (!D) return;
    for (const v of D.videos) {
      const on = W.key && W.key.work === v.work && W.key.name === v.name;
      const thumb = v.has_thumb ? el("img", { class: "dThumb", src: `/api/dash/thumb?work=${encodeURIComponent(v.work)}&name=${encodeURIComponent(v.name)}`, alt: "" })
        : el("div", { class: "dThumb ph" }, (v.title || "?").trim().charAt(0).toUpperCase());
      const dots = el("div", { class: "dDots" }, ...v.dots.map(d => el("i", { class: `dDot ${DOT[d.status] || "off"}${d.id === v.current ? " now" : ""}`, title: `${d.label}: ${STATUS[d.status] || d.status}` })));
      box.append(el("div", { class: `dCard${on ? " on" : ""}`, onclick: () => pickVideo(v) },
        thumb,
        el("div", { class: "dBody" }, el("b", { class: "dTitle" }, v.title), dots,
          v.error ? el("div", { class: "small bdWarn" }, v.error) :
            el("div", { class: "small muted" }, `Now: ${v.next.title}${v.next.status === "ready" ? " (waiting for you)" : ""}`),
          el("div", { class: "small muted" }, `${v.warnings ? `⚠ ${v.warnings} open · ` : ""}${pct(v.share)} of this application's use`))));
    }
  }

  /* ---------------------------------------------------------------- the selected video's usage */
  function renderVideoUsage() {
    const U = W.U, box = $("#wfVideoUsage"); if (!U) return; box.innerHTML = "";
    const c = U.claude, wk = U.week, sv = U.savings, D = W.dash.week;
    box.append(el("div", { class: "row" }, el("b", {}, "This video's usage"), el("span", { class: "muted small" }, "this week · measured where the app can see it; the rest is labelled")));
    const tiles = el("div", { class: "wfTiles" });
    tiles.append(el("div", { class: "wfTile" }, el("div", { class: "muted small" }, "Share of this application's use"),
      el("div", { class: "wfBig" }, pct(wk.share || 0)),
      el("div", { class: "small muted" }, wk.pct_of_plan != null ? `≈ ${wk.pct_of_plan}% of your weekly limit (estimate)` : "plan limits not read yet"),
      el("div", { class: "small muted" }, wk.chat ? `${big(wk.chat)} weighted tokens from chats assigned to it` : "No chat is assigned to this video yet: use the list below.")));
    tiles.append(el("div", { class: "wfTile" }, el("div", { class: "muted small" }, "Claude runs the app started"), el("div", { class: "wfBig" }, c.runs.length ? money(c.cost_usd) : "none yet"),
      el("div", { class: "small muted" }, c.runs.length ? `${c.runs.length} run${c.runs.length !== 1 ? "s" : ""} designing graphics (API-equivalent, not billed)` : "No graphic has been designed by Claude yet."),
      c.local_sections ? el("div", { class: "small muted" }, `${c.local_sections} section${c.local_sections !== 1 ? "s" : ""} built locally for free`) : null));
    tiles.append(el("div", { class: "wfTile" }, el("div", { class: "muted small" }, "Your time"), el("div", { class: "wfBig" }, sv ? `${sv.saved} h saved` : "not set"),
      el("div", { class: "small muted" }, sv ? `${sv.before} h by hand vs ${sv.actual} h this time${sv.value_usd != null ? ` ≈ ${money(sv.value_usd)}` : ""}` : "Enter the hours in Settings below.")));
    box.append(tiles);
    // which chats were about this video (the app cannot tell, so the creator says)
    const sess = D.sessions;
    const det = el("details", {}, el("summary", { class: "small" }, `Chats this week (${sess.length}): say which video each was about`));
    det.append(el("div", { class: "muted small" }, "Assigning a chat decides which video its use counts toward. A chat that mixed several things is better split by starting a new chat per video. “Building the app” covers tool and skill work."));
    for (const s of sess) {
      const sel = el("select", {}, el("option", { value: "" }, "Not assigned"), el("option", { value: "tools", selected: s.assigned === "tools" }, "Building the app and the skills"),
        ...W.dash.videos.map(v => el("option", { value: v.work, selected: s.assigned === v.work }, v.title)));
      sel.onchange = async () => { try { W.dash.week = await App.api("/api/dash/assign", { session: s.id, target: sel.value }); renderStrip(); renderCards(); refresh(); } catch (e) { App.toast(e.message, true, 8000); } };
      det.append(el("div", { class: "row small" }, el("span", { class: "muted" }, `${new Date(s.first).toLocaleDateString()} to ${new Date(s.last).toLocaleDateString()}`),
        el("span", {}, `${s.messages} replies · ${big(s.weighted)} weighted tokens`), el("span", { class: "spacer" }), sel));
    }
    if (!sess.length) det.append(el("div", { class: "muted small" }, "No chats found for this week."));
    box.append(det);
    if (U.local.length) box.append(el("details", {}, el("summary", { class: "small" }, `Free local work on this video (${U.local.length})`),
      ...U.local.map(x => el("div", { class: "small" }, `${x.what}${x.seconds ? ` · ${dur(x.seconds)}` : ""}`))));
    if (c.runs.length) box.append(el("details", {}, el("summary", { class: "small" }, `Claude runs on this video (${c.runs.length})`),
      ...c.runs.map(r => el("div", { class: "small" }, `${r.id} ${r.title || ""} · ${r.status} · ${money(r.cost_usd)}${r.turns ? ` · ${r.turns} turns` : ""}${r.duration_s ? ` · ${dur(r.duration_s)}` : ""}${r.model ? ` · ${r.model}` : ""}`))));
  }

  /* ---------------------------------------------------------------- the rough cut for DaVinci Resolve (tools/resolve_export.py) */
  async function loadResolve() {
    if (!W.key) return;
    try { W.R = await App.api(`/api/resolve?${q()}`); renderResolve(); } catch (e) { /* the card stays as it was */ }
  }
  function renderResolve() {
    const R = W.R, box = $("#wfResolve"); if (!R) return; box.innerHTML = "";
    const L = R.last;
    const go = el("button", { class: L ? "ghost" : "accent", disabled: !R.ready || W.exporting }, W.exporting ? "Exporting… (about 20 s)" : L ? "Export again" : "Export for DaVinci Resolve");
    go.onclick = exportResolve;
    box.append(el("div", { class: "row" }, el("b", {}, "Open this video in DaVinci Resolve"), el("span", { class: "spacer" }), go,
      L ? el("button", { class: "ghost", onclick: () => App.api("/api/resolve/reveal", { ...W.key }).catch(e => App.toast(e.message, true, 8000)) }, "Open the folder") : null));
    box.append(el("div", { class: "muted small" }, "A rough-cut timeline of the stitched video for Resolve: every cut, the B-roll, the graphics (transparent), sound effects, music and a marker for each section. "
      + "It points at your original recordings, so nothing is copied or re-rendered."));
    if (!R.ready) { box.append(el("div", { class: "wfWarn" }, "⚠ " + R.why)); return; }
    if (!L) return;
    const when = new Date(L.exported).toLocaleString();
    box.append(el("div", { class: "small", style: { marginTop: "6px" } }, `Last export ${when}: ${L.dur.toFixed(0)} s · ${L.contents.join(" · ")}`));
    if (R.stale) box.append(el("div", { class: "wfWarn" }, "⚠ The video has " + R.stale + ". Stitch again, then export again."));
    box.append(el("div", { class: "small", style: { marginTop: "6px" } },
      el("b", {}, "To open it: "), "in Resolve use File → Import → Timeline… and pick the first file below (set the project to 1920×1080, 30 fps first). If that one opens badly, try the second."));
    for (const f of L.files) box.append(el("div", { class: "rsFile" }, f));
    box.append(el("div", { class: "rsFile muted" }, L.folder));
    if (L.warnings.length) box.append(el("details", { class: "small" }, el("summary", { class: "wfWarn" }, `⚠ ${L.warnings.length} thing${L.warnings.length !== 1 ? "s" : ""} left out or to check`),
      el("ul", {}, ...L.warnings.map(w => el("li", { class: "wfWarn" }, w)))));
    box.append(el("details", { class: "small" }, el("summary", { class: "muted" }, "What is not carried over"), el("ul", {}, ...R.not_carried.map(x => el("li", {}, x)))));
  }
  async function exportResolve() {
    if (W.exporting) return;
    W.exporting = true; renderResolve();
    try { W.R = await App.api("/api/resolve/export", { ...W.key }); App.toast("Exported for DaVinci Resolve"); }
    catch (e) { App.toast(e.message, true, 9000); }
    W.exporting = false; renderResolve();
  }

  /* ---------------------------------------------------------------- the right pane: stages, settings, history */
  function render() {
    const S = W.S; if (!S) return;
    const card = W.dash && W.dash.videos.find(v => v.work === W.key.work && v.name === W.key.name);
    const head = $("#wfHead"); head.innerHTML = "";
    head.append(el("b", {}, (card && card.title) || W.key.name), el("div", { class: "wfFile" }, S.dir));
    const nx = $("#wfNext"); nx.innerHTML = "";
    nx.append(el("b", {}, `Next: ${S.next.title}`), el("div", { class: "muted small" }, S.next.hint));

    const box = $("#wfStages"); box.innerHTML = "";
    for (const st of S.stages) {
      const warn = st.warnings.map(w => el("div", { class: "wfWarn" }, "⚠ " + w));
      box.append(el("div", { class: `wfStage ${st.status}` },
        el("div", { class: "wfGate nogate" }, "•"),
        el("div", {},
          el("div", { class: "wfTitle" }, el("b", {}, st.title), el("span", { class: "wfStatus" }, STATUS[st.status] || st.status)),
          el("div", { class: "muted small" }, st.what),
          ...st.summary.map(s => el("div", { class: "small" }, s)),
          ...warn,
          st.status === "waiting" ? el("div", { class: "small muted" }, st.make) : null,
          st.file ? el("div", { class: "wfFile" }, st.file) : null)));
    }

    const set = $("#wfSettings"); set.innerHTML = "";
    const box2 = el("div", { class: "wfSet" });
    for (const [k, label, step] of SETTINGS) {
      let inp;
      if (step === "size") {
        const w = el("input", { type: "number", min: 160, step: 16, value: S.settings[k][0] });
        const h = el("input", { type: "number", min: 90, step: 9, value: S.settings[k][1] });
        const save = () => saveSetting(k, [+w.value, +h.value]);
        w.onchange = save; h.onchange = save;
        inp = el("span", { class: "row" }, w, "×", h);
      } else if (step === "bool") {
        inp = el("input", { type: "checkbox", checked: !!S.settings[k] });
        inp.onchange = () => saveSetting(k, inp.checked);
      } else if (Array.isArray(step)) {
        inp = el("select", {}, ...step.map(o => el("option", { value: o, selected: o === S.settings[k] }, o)));
        inp.onchange = () => saveSetting(k, inp.value);
      } else {
        inp = el("input", { type: "number", step, min: 0, value: S.settings[k] });
        if (k === "max_parallel") { inp.max = 3; inp.min = 1; }
        inp.onchange = () => saveSetting(k, +inp.value);
      }
      box2.append(el("span", {}, label), inp);
    }
    set.append(box2, el("p", { class: "muted small help" },
      "These are starting points. When something feels wrong in a video, change the number here and tell Claude why, so it learns your taste."));

    const h = $("#wfHistory"); h.innerHTML = ""; h.className = "small wfHist";
    for (const e of [...S.history].reverse()) h.append(el("div", {}, el("span", { class: "muted" }, new Date(e.t).toLocaleString() + "  "), e.what));
    if (!S.history.length) h.append(el("span", { class: "muted" }, "Nothing yet."));
  }

  /* ---------------------------------------------------------------- changes: what moved since the last stitch / final, and undo */
  const FILE_LABEL = [[".script.md", "Script"], [".clips.json", "Clips"], [".beatmap.json", "Beat map"], [".graphicsplan.json", "Graphics plan"],
    [".graphicsreview.json", "Graphics review"], [".storyboard.marks.json", "Storyboard marks"], [".sectionnotes.json", "Section notes"],
    [".watchnotes.json", "Watch notes"], [".shootplan.marks.json", "Shoot plan ticks"], [".shootplan.json", "Shoot plan"], [".footage.json", "Footage"],
    [".trims.json", "Trims"], [".voiceovers.json", "Voice-overs"], [".selfreview.marks.json", "Self-review marks"], [".workflow.json", "Settings"]];
  const fileLabel = f => (FILE_LABEL.find(([suf]) => f.endsWith(suf)) || [0, f])[1];
  const WHO = { user: "You", tool: "A tool", "outside the app": "Claude or an editor", "before history": "Before history" };
  const ago = iso => {
    const s = (Date.now() - new Date(iso).getTime()) / 1000;
    return s < 90 ? "just now" : s < 3600 ? `${Math.round(s / 60)} min ago` : s < 86400 ? `${Math.round(s / 3600)} h ago` : new Date(iso).toLocaleDateString();
  };
  async function loadChanges() {
    const box = $("#wfChanges"); if (!box || !W.key) return;
    let entries = [];
    try { entries = (await App.api(`/api/history?${q()}&limit=80`)).entries; } catch { /* the list is a convenience */ }
    box.innerHTML = "";
    box.append(el("h3", {}, "Changes ", el("span", { class: "muted small" }, "(plan files only: script, clips, beat map, graphics, notes)")));
    const since = (W.S && W.S.since) || {};
    for (const [m, label] of [["stitch", "the preview was stitched"], ["final", "the last final render started"]]) {
      const c = since[m]; if (!c) continue;
      const files = [...c.changed, ...c.added, ...c.removed].map(fileLabel);
      box.append(el("div", { class: "chSince" }, files.length ? `Since ${label} (${ago(c.since)}): ${[...new Set(files)].join(", ")} changed.` : `Nothing has changed since ${label} (${ago(c.since)}).`));
    }
    // one row per burst of edits to the same file by the same person
    entries = entries.filter(e => e.who !== "auto");
    const groups = [];
    entries.forEach((e, i) => {
      const g = groups[groups.length - 1];
      if (g && g.file === e.file && g.who === e.who && g.oldest.ts - e.ts < 30) { g.oldest = e; g.count++; g.idx = i; }
      else groups.push({ file: e.file, who: e.who, newest: e, oldest: e, count: 1, idx: i });
    });
    if (!groups.length) box.append(el("div", { class: "muted small" }, "No changes recorded yet."));
    for (const g of groups.slice(0, 25)) {
      const prev = entries.slice(g.idx + 1).find(x => x.file === g.file);          // the version just before this burst
      const row = el("div", { class: "chRow" },
        el("span", { class: "when", title: g.newest.t }, ago(g.newest.t)),
        el("span", {}, el("b", {}, fileLabel(g.file)), ` · ${WHO[g.who] || g.who}${g.count > 1 ? ` · ${g.count} edits` : ""} · `,
          el("span", { class: "muted" }, g.newest.why && g.newest.who === "user" ? g.newest.why : g.newest.summary)),
        el("span", { class: "row" },
          prev ? el("button", { class: "ghost", onclick: () => showDiff(row, prev.id, g.newest.id) }, "What changed") : null,
          prev ? el("button", { class: "ghost", title: "Put this file back as it was before these edits", onclick: () => undo(g, prev) }, "Undo") : null));
      box.append(row);
    }
  }
  async function showDiff(row, fromId, toId) {
    const old = row.querySelector(".chDiff"); if (old) { old.remove(); return; }
    try {
      const d = await App.api(`/api/history/diff?${q()}&id=${fromId}&other=${toId}`);
      const lines = d.text != null ? [d.text || "(no visible difference)"] : [
        ...d.changed.map(i => `changed  ${i}`), ...d.added.map(i => `added    ${i}`), ...d.removed.map(i => `removed  ${i}`),
        ...d.fields.map(k => `setting  ${k}`)];
      row.append(el("div", { class: "chDiff" }, lines.join("\n") || "(no visible difference)"));
    } catch (e) { App.toast(e.message, true, 8000); }
  }
  async function undo(g, prev) {
    if (!confirm(`Put ${fileLabel(g.file)} back as it was ${ago(prev.t)}?\n\nThis undoes ${g.count > 1 ? `these ${g.count} edits` : "this edit"}. The version you have now is kept in the list, so you can undo the undo.`)) return;
    try { await App.api("/api/history/restore", { ...W.key, id: prev.id }); App.toast(`${fileLabel(g.file)} restored`); await refresh(); loadCardsQuiet(); }
    catch (e) { App.toast(e.message, true, 8000); }
  }
  async function saveSetting(k, v) {
    try { W.S = await post("settings", { ...W.key, settings: { [k]: v } }); render(); App.toast("Saved"); if (k.startsWith("hours") || k.startsWith("manual") || k.startsWith("hourly")) refresh(); }
    catch (e) { App.toast(e.message, true, 8000); await refresh(); }
  }
  async function loadCardsQuiet() { try { W.dash = await App.api("/api/dash"); renderCards(); renderStrip(); } catch (e) { /* the list updates next time */ } }
  async function newVideo() {
    const title = prompt("Name of the new video (this becomes its folder name):");
    if (!title) return;
    try { const r = await post("create", { title }); await loadList(r); App.toast("Created"); }
    catch (e) { App.toast(e.message, true, 8000); }
  }

  App.dashRefresh = loadCardsQuiet;                     // other tabs call this after a change that moves a stage dot
  $("#wfNew").onclick = newVideo;
  $("#wfRefresh").onclick = () => loadList(W.key);
  window.addEventListener("viewchange", e => { if (e.detail === "workflow") loadList(W.key); });
  window.addEventListener("focus", () => { if (visible()) { refresh(); loadCardsQuiet(); } });   // files change while you are in Claude
  if (visible()) loadList();
})();
