import { h, api } from './util.js';

// Cards that sit on the Preview and Final screens: the fact check, the music chooser, the DaVinci Resolve export. A usage line for Home.
const enc = encodeURIComponent;
const fmt = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
const VERDICT = { incorrect: 'Wrong', misleading: 'Misleading', imprecise: 'Not precise', unverifiable: 'Could not confirm' };
const safeLink = u => /^https?:\/\//i.test(u || '');

// --- Check the facts: Claude checks what is said against real sources; this only reports, it never changes the plan.
export function factCheckCard(key) {
  const [work, name] = key.split('~');
  const body = h('div', { id: 'factBody' });
  const run = h('button', { class: 'quiet', id: 'factRun' }, 'Check the facts');
  const card = h('div', { class: 'card', id: 'factCard' }, h('div', { class: 'rhead' }, h('b', {}, 'Check the facts'), run), body);
  let timer = null;

  const draw = d => {
    clearTimeout(timer);
    run.disabled = !!d.running;
    run.textContent = d.running ? 'Checking…' : d.status === 'done' ? 'Check again' : 'Check the facts';
    if (d.running) {
      body.replaceChildren(h('p', { class: 'muted' }, 'Claude is reading what is said and looking things up. This takes a few minutes.'));
      timer = setTimeout(async () => { if (card.isConnected) draw(await api(`/api/accuracy?work=${enc(work)}&name=${enc(name)}`)); }, 3000);
      return;
    }
    if (d.status === 'failed') { body.replaceChildren(h('p', { class: 'muted', id: 'factError' }, `The check did not finish. ${d.error || ''}`)); return; }
    if (d.status !== 'done') {
      body.replaceChildren(h('p', { class: 'muted small' }, 'Claude reads what is said in the video and checks each claim about how things work against real sources on the web. It takes a few minutes and uses some of your plan. It only reports: nothing in your video changes.'));
      return;
    }
    const gone = new Set(d.dismissed || []);
    const open = d.findings.filter(f => !gone.has(f.id));
    const closed = d.findings.filter(f => gone.has(f.id));
    const dismiss = (f, undo) => async () => draw(await api('/api/accuracy/dismiss', { work, name, id: f.id, undo }));
    body.replaceChildren(
      d.summary ? h('p', { id: 'factSummary' }, d.summary) : null,
      open.length ? h('ul', { class: 'facts', id: 'factList' }, ...open.map(f => h('li', {},
        h('span', { class: 'chip warn' }, VERDICT[f.verdict] || f.verdict),
        h('div', { class: 'quote' }, `“${f.quote}”`),
        h('div', {}, f.explanation),
        f.suggestion ? h('div', { class: 'muted small' }, `Suggestion: ${f.suggestion}`) : null,
        f.sources.filter(s => safeLink(s.url)).length ? h('div', { class: 'small' }, ...f.sources.filter(s => safeLink(s.url)).map(s => h('a', { href: s.url, target: '_blank', rel: 'noopener noreferrer' }, s.title || s.url), ' ')) : null,
        h('button', { class: 'quiet', onclick: dismiss(f, false) }, 'Dismiss')))) : h('p', { class: 'muted', id: 'factNone' }, 'No problems found.'),
      closed.length ? h('details', {}, h('summary', {}, `Dismissed (${closed.length})`),
        ...closed.map(f => h('div', { class: 'small' }, `“${f.quote}” `, h('button', { class: 'quiet', onclick: dismiss(f, true) }, 'Bring back')))) : null,
      d.claims.length ? h('p', { class: 'muted small' }, `${d.claims.length} claims checked.`) : null);
  };
  run.addEventListener('click', async () => {
    run.disabled = true;
    try { draw(await api('/api/accuracy/run', { work, name })); } catch (e) { run.disabled = false; body.replaceChildren(h('p', { class: 'muted' }, e.message)); }
  });
  api(`/api/accuracy?work=${enc(work)}&name=${enc(name)}`).then(draw).catch(e => body.replaceChildren(h('p', { class: 'muted' }, e.message)));
  return card;
}

// --- Music: for each stretch of music, hear another track under the speech, then use it from the next preview on.
export function musicCard(key) {
  const [work, name] = key.split('~');
  const card = h('div', { class: 'card', id: 'musicCard', hidden: true });
  api(`/api/music?work=${enc(work)}&name=${enc(name)}`).then(d => {
    if (!d.stitched) return;
    card.hidden = false;
    card.append(h('b', {}, 'Music'));
    if (!d.ready) { card.append(h('p', { class: 'muted small' }, 'Make a new preview first: choosing music needs a preview made with this version of the app.')); return; }
    if (!d.beds.length) { card.append(h('p', { class: 'muted small' }, 'This video has no music yet.')); return; }
    if (!d.tracks.length) { card.append(h('p', { class: 'muted small' }, 'No music tracks were found in your Music folder.')); return; }
    card.append(h('p', { class: 'muted small' }, 'Pick a track and press Hear it: a short clip plays with the speech over it. Use this keeps your choice for the next preview.'));
    for (const bed of d.beds) {
      const pick = h('select', { class: 'trackPick' }, ...d.tracks.map(t => h('option', { value: t.name }, t.name + (t.bpm ? ` · ${Math.round(t.bpm)} bpm` : '') + (t.note ? ` · ${t.note}` : ''))));
      const player = h('video', { controls: true, hidden: true, class: 'auditionPlayer' });
      const say = h('span', { class: 'muted small' });
      const hear = h('button', { class: 'quiet', onclick: async () => {
        hear.disabled = true; say.textContent = 'Making a short clip…';
        try {
          const r = await api('/api/music/audition', { work, name, bed: bed.i, track: pick.value });
          player.src = `/media/${enc(work)}/${enc(r.file)}?v=${Date.now()}`; player.hidden = false; player.play().catch(() => {});
          say.textContent = `Playing ${fmt(r.from)} to ${fmt(r.to)} with ${r.track}.`;
        } catch (e) { say.textContent = e.message; }
        hear.disabled = false;
      } }, 'Hear it');
      const use = h('button', { class: 'main small', onclick: async () => {
        try { const r = await api('/api/music/use', { work, name, bed: bed.i, track: pick.value }); say.textContent = `Saved: ${r.track} plays here from the next preview.`; } catch (e) { say.textContent = e.message; }
      } }, 'Use this');
      card.append(h('div', { class: 'bed' }, h('div', { class: 'rhead' }, h('b', {}, `Music ${bed.i + 1}`), h('span', { class: 'muted small' }, `${fmt(bed.start)} to ${fmt(bed.end)}`)),
        h('div', { class: 'row' }, pick, hear, use), say, player));
    }
  }).catch(() => {});
  return card;
}

// --- DaVinci Resolve: the cut as a timeline file for another editor.
export function resolveCard(key) {
  const [work, name] = key.split('~');
  const card = h('div', { class: 'card', id: 'resolveCard' });
  const draw = d => {
    const go = h('button', { class: 'quiet', id: 'resolveGo', disabled: !d.ready, onclick: async () => {
      go.disabled = true; go.textContent = 'Exporting… this takes a minute';
      try { draw(await api('/api/resolve/export', { work, name })); } catch (e) { go.textContent = 'Export for DaVinci Resolve'; go.disabled = false; card.append(h('p', { class: 'muted' }, e.message)); }
    } }, d.last ? 'Export again' : 'Export for DaVinci Resolve');
    card.replaceChildren(h('div', { class: 'rhead' }, h('b', {}, 'Export for DaVinci Resolve'), go),
      d.ready ? null : h('p', { class: 'muted small' }, d.why),
      d.last ? h('p', { class: 'small', id: 'resolveLast' }, `Exported ${d.last.exported.replace('T', ' ').slice(0, 16)}: ${d.last.contents.join('; ')}.`, d.stale ? h('span', { class: 'muted' }, ` Changed since then: ${d.stale}.`) : null) : null,
      d.last ? h('button', { class: 'quiet', id: 'resolveOpen', onclick: () => api('/api/resolve/reveal', { work, name }) }, 'Open the folder') : null,
      h('details', {}, h('summary', {}, 'What does not carry over'), h('ul', {}, ...d.not_carried.map(t => h('li', { class: 'small' }, t)))));
  };
  api(`/api/resolve?work=${enc(work)}&name=${enc(name)}`).then(draw).catch(e => card.replaceChildren(h('p', { class: 'muted' }, e.message)));
  return card;
}

// --- Home: how much of the plan this app used this week.
export async function usageLine() {
  const line = h('p', { class: 'muted small', id: 'usageLine' });
  try {
    const m = await api('/api/usage/week');
    line.textContent = m.weekly_pct == null ? 'This week’s use of your plan: no reading yet.'
      : `This week your plan is ${Math.round(m.weekly_pct)}% used; this app is about ${m.app_pct_of_plan} points of that.`;
  } catch { return null; }
  return line;
}
