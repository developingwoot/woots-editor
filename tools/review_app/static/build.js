"use strict";
/* Build tab (stage 5): the video is built section by section, never more than 3 at a time, as HALF-SIZE previews.
   tools/builder.py does the work: a section with only takes, punch-ins, B-roll and finished graphics is built locally
   (no tokens); a section with a graphic to design starts ONE background Claude run in its own folder. The board shows
   the three slots, live progress, cost, a check that nothing outside the section's folder changed, and the preview.
   The final render (Final tab) starts from the stitched preview this tab makes. */
(() => {
  const B = { key: null, d: null, loading: false, timer: null };
  const vid = $("#bdVideo");
  const q = () => `work=${encodeURIComponent(B.key.work)}&name=${encodeURIComponent(B.key.name)}`;
  const visible = () => document.body.dataset.view === "build";
  const money = x => (x == null ? "–" : `$${x < 1 ? x.toFixed(3) : x.toFixed(2)}`);
  const mmss = s => (s == null ? "–" : App.fmtT(s, 0));
  const STATUS = { todo: "not built", queued: "waiting for a slot", running: "building", done: "built", failed: "failed",
                   cancelled: "cancelled", interrupted: "interrupted", outdated: "plan changed: rebuild" };
  const busy = () => B.d && (B.d.running + B.d.queued) > 0;

  /* ---------------------------------------------------------------- load + polling */
  async function loadList(pick) {
    const list = await App.api("/api/wf/videos");
    const vids = list.flatMap(w => w.names.map(n => ({ work: w.work, name: n })));
    const sel = $("#bdPick"); sel.innerHTML = "";
    for (const v of vids) sel.append(el("option", { value: JSON.stringify([v.work, v.name]) }, v.work === v.name ? v.name : `${v.work} · ${v.name}`));
    $("#bdEmpty").hidden = vids.length > 0; $("#bdBody").hidden = !vids.length; sel.hidden = !vids.length;
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
      B.d = await App.api(`/api/build?${q()}`);
      render();
    } catch (e) { App.toast(e.message, true, 8000); }
    B.loading = false;
    clearTimeout(B.timer);
    if (visible() && busy()) B.timer = setTimeout(reload, 2000);          // live progress while anything runs
  }
  App.buildReload = () => (visible() ? reload() : Promise.resolve());
  const post = async (op, body = {}) => {
    try { B.d = await App.api(`/api/build/${op}`, { ...B.key, ...body }); render(); clearTimeout(B.timer); if (busy()) B.timer = setTimeout(reload, 1500); return true; }
    catch (e) { App.toast(e.message, true, 9000); return false; }
  };

  /* ---------------------------------------------------------------- setup strip + slots */
  function renderSetup() {
    const d = B.d, box = $("#bdSetup"); box.innerHTML = "";
    if (!d.beatmap_ready) { box.append(el("b", {}, "No beat map yet."), el("span", { class: "muted small" }, "Building starts from the beat map.")); return; }
    if (!d.can_build) box.append(el("div", { class: "bdGate" }, d.why_not));
    const s = d.settings, t = d.totals;
    box.append(el("div", { class: "muted small" },
      `Graphics model: ${s.build_model}, effort ${s.build_effort}${s.critic_model && s.critic_model !== "off" ? `, then a ${s.critic_model} critic` : ""}, up to ${money(s.build_budget_usd)} per run (a soft cap: it is checked between steps and can overshoot) · at most ${Math.min(d.max_global, s.max_parallel)} at once · preview ${s.preview_size[0]}×${s.preview_size[1]}. Change these in the Dashboard tab.`));
    const chips = [`${t.done} of ${t.sections} sections built`, `${mmss(t.dur)} of video`, `${money(t.cost_usd)} spent so far`];
    box.append(el("div", { class: "bmTotals" }, ...chips.map(c => el("span", {}, c))));
    if (t.agent_sections_left) box.append(el("div", { class: "small" },
      t.estimate_usd != null ? `${t.agent_sections_left} section${t.agent_sections_left !== 1 ? "s" : ""} still need Claude: about ${money(t.estimate_usd)} (the average of your ${money(t.avg_agent_cost)} finished runs).`
                             : `${t.agent_sections_left} section${t.agent_sections_left !== 1 ? "s" : ""} need Claude to design graphics. No cost estimate yet: build ONE first and the board will show what it cost.`));
    const todo = d.sections.filter(x => ["todo", "outdated", "failed", "cancelled", "interrupted"].includes(x.status));
    const firstAgent = todo.find(x => x.needs_agent);
    const row = el("div", { class: "row" });
    const dis = !d.can_build;
    if (firstAgent && t.avg_agent_cost == null)
      row.append(el("button", { class: "accent", disabled: dis || busy(), onclick: () => start([firstAgent.id]) }, `Build ${firstAgent.id} first (needs Claude: measure the cost)`));
    row.append(el("button", { class: firstAgent && t.avg_agent_cost == null ? "ghost" : "accent", disabled: dis || !todo.length, onclick: () => start(null, todo) },
      busy() ? "Building…" : todo.length ? `Build ${todo.length === d.sections.length ? "all" : "the remaining"} ${todo.length} section${todo.length !== 1 ? "s" : ""}` : "Everything is built"));
    row.append(el("button", { class: "ghost", disabled: busy(), onclick: () => confirm("Re-plan the sections from the current beat map? Built sections whose beats did not change stay built.") && post("replan") }, "Re-plan sections"));
    const allDone = d.sections.length && d.sections.every(x => x.status === "done");
    row.append(el("button", { class: allDone ? "accent" : "ghost", disabled: !allDone || busy(), onclick: stitch }, "Stitch the half-size preview"));
    box.append(row);
    if (d.plan_stale) box.append(el("div", { class: "bdGate" }, "The beat map changed after the sections were planned: press “Re-plan sections”."));
    if (d.stitch) box.append(el("div", { class: "row" }, el("span", { class: "tag2 good" }, `stitched preview ${mmss(d.stitch.dur)} · ${new Date(d.stitch.stitched).toLocaleString()}`),
      el("button", { onclick: () => playFile(`/media/${encodeURIComponent(B.key.work)}/${encodeURIComponent(d.stitch.file)}?t=${encodeURIComponent(d.stitch.stitched)}`, "Stitched half-size preview") }, "▶ Play it"),
      el("span", { class: "muted small" }, "Watch it whole in “Watch and note” below, then render the final in the Final tab.")));
  }
  function renderSlots() {
    const box = $("#bdSlots"); box.innerHTML = "";
    const run = B.d.sections.filter(x => x.status === "running");
    for (let i = 0; i < Math.min(B.d.max_global, B.d.settings.max_parallel); i++) {
      const r = run[i];
      box.append(el("div", { class: `bdSlot ${r ? "on" : ""}` }, r
        ? [el("b", {}, `Slot ${i + 1}: ${r.id} ${r.title}`), el("div", { class: "muted" }, `${r.mode === "agent" ? "Claude is designing" : "rendering"} · ${elapsed(r)}`),
           el("div", { class: "muted" }, (r.progress || []).slice(-1)[0] || "starting…")]
        : [el("b", {}, `Slot ${i + 1}`), el("div", { class: "muted" }, B.d.queued ? "taking the next waiting section…" : "free")]));
    }
  }
  const elapsed = r => { const s = Math.max(0, Math.round((Date.now() - new Date(r.started).getTime()) / 1000)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };

  /* music audition list: hear another track in place of a bed, in the picture (tools/musicaudition.py) */
  async function renderMusic() {
    const box = $("#bdMusic");
    if (!B.d || !B.d.stitch) { box.innerHTML = ""; return; }
    const key = B.d.stitch.stitched;
    if (B.musicKey === key && B.musicBox) return;                     // the list only changes with a new stitch (or a "Use it")
    let M; try { M = await App.api(`/api/music?${new URLSearchParams(B.key)}`); } catch { return; }
    B.musicKey = key; B.musicBox = true;
    box.innerHTML = "";
    const d = el("details", { class: "card" }, el("summary", {}, el("b", {}, "Music: hear other tracks"), el("span", { class: "muted small" }, `  ${M.beds.length} stretch${M.beds.length !== 1 ? "es" : ""} of music in the preview`)));
    if (M.note) d.append(el("div", { class: "bdGate" }, M.note));
    const clip = el("div", { class: "muted small" });
    for (const b of M.beds) {
      const sel = el("select", {}, ...M.tracks.map(t => el("option", { value: t.name, selected: t.name === b.name }, `${t.name}${t.bpm ? ` · ${t.bpm} bpm` : ""}${t.note ? " · " + t.note : ""}`)));
      const status = el("span", { class: "muted small" });
      const hear = el("button", { disabled: !M.ready, onclick: async () => {
        hear.disabled = true; status.textContent = "making a clip… (about 15 seconds)";
        try {
          const r = await App.api("/api/music/audition", { ...B.key, bed: b.i, track: sel.value });
          status.textContent = `clip ${mmss(r.from)}–${mmss(r.to)} of the preview, with "${r.track}"; the first ${r.lead_in} s lead the music in`;
          playFile(`/media/${encodeURIComponent(B.key.work)}/${encodeURIComponent(r.file)}?t=${Date.now()}`, `Music audition: bed ${b.i + 1}, ${r.track}`);
        } catch (e) { status.textContent = ""; App.toast(e.message, true, 8000); }
        hear.disabled = !M.ready;
      } }, "▶ Hear it");
      const use = el("button", { class: "accent", disabled: !M.ready, onclick: async () => {
        if (sel.value === b.name) return App.toast("That track is already the one in the preview");
        try { await App.api("/api/music/use", { ...B.key, bed: b.i, track: sel.value }); B.musicKey = null; App.toast(`Saved in the beat map. Stitch again to hear "${sel.value}" in the whole video.`, false, 8000); renderMusic(); }
        catch (e) { App.toast(e.message, true, 8000); }
      } }, "Use it");
      d.append(el("div", { class: "row", style: { margin: "6px 0", gap: "8px" } },
        el("b", {}, `${mmss(b.start)}–${mmss(b.end)}`), el("span", { class: "muted small" }, `now: ${b.name}`), sel, hear, use, status));
    }
    d.append(clip);
    d.append(el("div", { class: "muted small" }, "“Hear it” plays about 35 seconds of that stretch of the stitched preview with the track you picked, at the same level and ducking as the final. “Use it” changes the whole stretch in the beat map; stitch again to hear it everywhere."));
    box.append(d);
  }

  /* ---------------------------------------------------------------- actions */
  async function start(ids, todo) {
    const t = B.d.totals;
    if (!ids) {
      const agent = todo.filter(x => x.needs_agent).length;
      const est = t.estimate_usd != null && agent ? `\n\nClaude runs are expected to cost about ${money(t.estimate_usd)} in total.` : agent ? `\n\n${agent} section(s) will start a Claude run each; the cost is not known yet.` : "\n\nNo Claude runs: these are built locally.";
      if (!confirm(`Build ${todo.length} section${todo.length !== 1 ? "s" : ""}, three at a time?${est}`)) return;
      ids = todo.map(x => x.id);
    }
    await post("start", { ids });
  }
  async function stitch() {
    if (!(await post("stitch"))) return;
    const r = B.d || {};
    App.toast(r.selfreview_started ? "Stitched. The self-review is running on it now (Self-review tab)." : "Stitched" + (r.selfreview_note ? ` (self-review not started: ${r.selfreview_note})` : ""), false, 8000);
  }
  const cancel = sid => post("cancel", { sid });
  function playFile(url, title) {
    $("#bdPlayerBox").hidden = false; $("#bdPlayTitle").textContent = title;
    vid.src = url; vid.play().catch(() => {});
  }
  const play = s => {
    B.playSid = s.id;
    playFile(`/bmedia/${encodeURIComponent(B.key.work)}/${encodeURIComponent(B.key.name)}/${s.id}?t=${encodeURIComponent(s.finished || "")}`, `${s.id} ${s.title}: half-size preview`);
    $("#bdNoteRow").hidden = false;
  };
  const sendNote = async (sid, text, kind, t) => {
    if (!text.trim()) { App.toast("Write what should change first", true); return false; }
    if (await post("note", { sid, text, kind, t })) { App.toast(kind === "graphic" ? "Saved: it will be used the next time this section is built" : "Saved for Claude: tell Claude in chat to apply it"); return true; }
    return false;
  };
  const noteHere = kind => async () => {
    const t = vid.currentTime; vid.pause();
    if (await sendNote(B.playSid, $("#bdNoteText").value, kind, t)) $("#bdNoteText").value = "";
  };
  $("#bdNoteG").onclick = noteHere("graphic"); $("#bdNoteP").onclick = noteHere("plan");
  vid.addEventListener("timeupdate", () => { $("#bdNoteAt").textContent = `${B.playSid || ""} at ${mmss(vid.currentTime)}`; });
  $("#bdPlayClose").onclick = () => { vid.pause(); $("#bdPlayerBox").hidden = true; };

  /* ---------------------------------------------------------------- section cards */
  function card(s) {
    const live = s.status === "running" || s.status === "queued";
    const box = el("div", { class: `bdCard ${s.status}` });
    box.append(el("div", { class: "bdHead" }, el("b", {}, `${s.id} ${s.title}`),
      el("span", { class: "muted small" }, `${mmss(s.dur)} · ${s.beats.length} beat${s.beats.length !== 1 ? "s" : ""} (${s.beats[0]}–${s.beats[s.beats.length - 1]})`),
      el("span", { class: `tag2 ${s.needs_agent ? "warn" : "good"}` }, s.needs_agent ? `needs Claude: ${s.unbuilt_graphics} graphic${s.unbuilt_graphics !== 1 ? "s" : ""}` : "local, no Claude"),
      el("span", { class: `wfStatus ${s.status === "done" ? "approved" : s.status === "failed" || s.status === "interrupted" ? "changed" : ""}` }, STATUS[s.status] || s.status),
      s.cost_usd != null ? el("span", { class: "muted small" }, `${money(s.cost_usd)} · ${s.turns || "?"} steps${s.elapsed ? ` · ${Math.round(s.elapsed)} s` : ""}`) : (s.elapsed ? el("span", { class: "muted small" }, `${Math.round(s.elapsed)} s`) : null),
      el("span", { class: "spacer" }),
      s.has_preview ? el("button", { class: s.status === "outdated" ? "ghost" : "", title: s.status === "outdated" ? "This preview was built from an older plan: Rebuild to see the current one" : "", onclick: () => play(s) },
        s.status === "outdated" ? "▶ Old preview (plan changed)" : "▶ Preview") : null,
      live ? el("button", { class: "ghost", onclick: () => cancel(s.id) }, "Cancel")
           : el("button", { class: s.status === "done" ? "ghost" : "accent", disabled: !B.d.can_build, onclick: () => start([s.id]) }, s.status === "done" ? "Rebuild" : "Build")));
    if (!live && s.status === "todo") box.append(el("div", { class: "muted small" }, s.why));
    if (s.status === "running" && (s.progress || []).length) box.append(el("div", { class: "bdProg" }, s.progress.join("\n")));
    if (s.error) box.append(el("div", { class: "bdBad" }, s.error));
    const sus = (s.audit && s.audit.suspicious) || [], other = (s.audit && (s.audit.other || (s.audit.suspicious ? [] : s.audit.changed))) || [];
    if (sus.length)
      box.append(el("div", { class: "bdBad" }, "⚠ Claude's own commands mention files outside this section's folder that changed while it ran. Look before you trust the result:",
        el("ul", {}, ...sus.slice(0, 5).map(c => el("li", {}, c)))));
    if (other.length)
      box.append(el("details", {}, el("summary", { class: "muted small" }, `${other.length} other file${other.length !== 1 ? "s" : ""} changed while this ran, but nothing Claude did mentions them (most likely your own edits)`),
        el("ul", { class: "small muted" }, ...other.slice(0, 8).map(c => el("li", {}, c)))));
    if (s.left_out && s.left_out.length) box.append(el("div", { class: "bdWarn" }, `Claude did not build: ${s.left_out.join(", ")} (see its report). The section is shown without ${s.left_out.length === 1 ? "it" : "them"}.`));
    if (s.denials && s.denials.length) box.append(el("div", { class: "bdWarn" }, `${s.denials.length} action${s.denials.length !== 1 ? "s were" : " was"} refused by the permission rules: `, s.denials.slice(0, 3).map(d => `${d.tool} ${d.input}`).join(" · ")));
    if ((s.notes || []).length) box.append(el("div", { class: "bdWarn" }, s.notes.join(" · ")));
    if (s.critic) {
      const c = s.critic, ids = Object.keys(c.verdicts || {});
      const nfix = ids.reduce((n, k) => n + (c.verdicts[k].issues || []).filter(i => i.severity === "fix").length, 0);
      const nlook = ids.reduce((n, k) => n + (c.verdicts[k].issues || []).filter(i => i.severity !== "fix").length, 0);
      box.append(el("details", { class: "bdCrit" }, el("summary", { class: "small" },
        `Critic (${c.model}): ${ids.length} graphic${ids.length !== 1 ? "s" : ""} looked at, ${nfix} fix${nfix !== 1 ? "es" : ""}${c.fixed ? " (the builder applied them)" : ""}, ${nlook} to look at · ${money(c.cost_usd)}${c.fix_cost_usd ? ` + ${money(c.fix_cost_usd)} for the fixes` : ""}`),
        ...ids.map(k => el("div", { class: "small" }, el("b", {}, `${k} ${c.verdicts[k].verdict}`),
          ...(c.verdicts[k].issues || []).map(i => el("div", { class: "muted small" }, `${i.severity === "fix" ? "FIX" : "look"}: ${i.what}  →  ${i.fix}`))))));
    }
    if (s.report) box.append(el("details", {}, el("summary", { class: "muted small" }, "Claude's report"), el("div", { class: "bdRep" }, s.report)));
    if (s.status === "done" || s.status === "outdated" || (B.d.notes || []).some(n => n.sid === s.id)) box.append(changeBox(s));
    return box;
  }
  /* ask for a change on a built section: a graphic change is redone by Claude on the next build; a cut/clip/timing change is saved for Claude in chat */
  function changeBox(s) {
    const mine = (B.d.notes || []).filter(n => n.sid === s.id);
    const d = el("details", { class: "bdNotes", open: mine.some(n => n.status !== "done") },
      el("summary", {}, mine.length ? `Your change requests (${mine.filter(n => n.status !== "done").length} open)` : "Ask for a change"));
    const STAT = { open: "waiting", applied: "rebuilt with this: look again", done: "done" };
    for (const n of mine) {
      d.append(el("div", { class: `bdNote ${n.status}` },
        el("span", { class: `tag2 ${n.kind === "graphic" ? "good" : "warn"}` }, n.kind === "graphic" ? "graphic" : "cut / clip / timing"),
        el("span", { class: "muted small" }, `${n.t != null ? mmss(n.t) + " " : ""}${n.beat ? "(" + n.beat + ") " : ""}${n.kind === "plan" && n.status === "open" ? "waiting for Claude in chat" : STAT[n.status]}`),
        el("span", {}, n.text), el("span", { class: "spacer" }),
        n.status !== "done" ? el("button", { class: "ghost", onclick: () => post("note_status", { id: n.id, status: "done" }) }, "Mark done") : null,
        el("button", { class: "ghost", onclick: () => post("note_status", { id: n.id, status: "delete" }) }, "Remove")));
    }
    const ta = el("input", { placeholder: "e.g. the counter covers the shark, make it smaller", style: { flex: "1", minWidth: "16em" } });
    d.append(el("div", { class: "row" }, ta,
      el("button", { onclick: async () => { if (await sendNote(s.id, ta.value, "graphic")) ta.value = ""; } }, "Change the graphic"),
      el("button", { class: "ghost", onclick: async () => { if (await sendNote(s.id, ta.value, "plan")) ta.value = ""; } }, "Change the cut or clip")),
      el("div", { class: "muted small" }, "Or press ▶ Preview and use the box under the player to pin a note to the exact moment. “Change the graphic” is built by Claude next time you press Rebuild; “cut or clip” notes wait for you to tell Claude in chat."));
    return d;
  }
  function render() {
    if (!B.d) return;
    renderSetup(); renderSlots(); renderMusic();
    const list = $("#bdList"); list.innerHTML = "";
    for (const s of B.d.sections) list.append(card(s));
  }

  /* ---------------------------------------------------------------- wiring */
  $("#bdPick").onchange = () => {
    const [work, name] = JSON.parse($("#bdPick").value); B.key = { work, name }; B.d = null; reload();
    App.setVideoKey(JSON.stringify([work, name]));
    window.dispatchEvent(new CustomEvent("videopick", { detail: { work, name } }));        // self-review and watch follow this one picker
  };
  for (const b of document.querySelectorAll("#buildCol [data-jump]")) b.onclick = () => document.getElementById(b.dataset.jump).scrollIntoView({ behavior: "smooth", block: "start" });
  $("#bdRefresh").onclick = () => loadList(B.key);
  window.addEventListener("viewchange", e => { if (e.detail === "build") loadList(B.key); else { vid.pause(); clearTimeout(B.timer); } });
  window.addEventListener("focus", () => { if (visible()) reload(); });
  if (visible()) loadList();
})();
