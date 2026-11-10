import { h, api } from './util.js';

// "Undo": for 10 seconds after a change to a plan file, a quiet button puts the file back as it was (the server keeps every version: /api/history).
// "History": the list of versions of this video's plan files, each with "Put this back".
const enc = encodeURIComponent;
const LABELS = { script: 'Script', clips: 'Clips', beatmap: 'Plan', graphicsplan: 'Graphics', graphicsreview: 'Graphics', notes: 'Notes', sectionnotes: 'Notes', watchnotes: 'Notes',
  teaching: 'Teaching moments', publish: 'Publishing details', shots: 'Shots', takes: 'Takes', tags: 'Tags', locks: 'Locks', trims: 'Trims', footage: 'Footage', workflow: 'Settings', shorts: 'Shorts' };
const labelOf = (file, name) => { const rest = file.startsWith(name + '.') ? file.slice(name.length + 1) : file; const k = rest.split('.')[0]; return LABELS[k] || k; };
const keyOf = () => { const m = /^#\/v\/([^/]+)\//.exec(location.hash); return m ? decodeURIComponent(m[1]) : null; };

let bar = null;
let timer = null;
function toast() {
  if (!bar) { bar = h('div', { id: 'undoBar', hidden: true }); document.body.append(bar); }
  return bar;
}
function hide() { clearTimeout(timer); toast().hidden = true; }

export function watch() {
  document.addEventListener('wr-saved', async e => {
    const { path, t0 } = e.detail;
    const key = keyOf();
    if (!key || path.startsWith('/api/history') || path.startsWith('/api/v2/job')) return;
    const work = key.split('~')[0];
    let entries;
    try { entries = (await api(`/api/history?work=${enc(work)}&limit=30`)).entries; } catch { return; }
    const last = entries[0];
    if (!last || last.ts * 1000 < t0 - 2000) return;                        // nothing was saved by this call
    const before = entries.slice(1).find(x => x.file === last.file);
    if (!before) return;                                                    // the first version of a file has nothing to go back to
    const b = toast();
    b.replaceChildren(h('span', {}, 'Saved.'), h('button', { class: 'quiet onDark', id: 'undoBtn', title: last.summary || '', onclick: async () => {
      hide();
      try { await api('/api/history/restore', { work, id: before.id }); } catch (err) { b.replaceChildren(h('span', {}, err.message)); b.hidden = false; return; }
      dispatchEvent(new Event('hashchange'));                               // draw the step again from the file
    } }, 'Undo'));
    b.hidden = false;
    clearTimeout(timer);
    timer = setTimeout(hide, 10000);
  });
}

export async function historyPanel(key) {
  const [work, name] = key.split('~');
  const { entries } = await api(`/api/history?work=${enc(work)}&limit=200`);
  const mine = entries.filter(x => x.file.startsWith(name + '.'));
  const when = t => t.replace('T', ' ').slice(0, 16);
  const rows = mine.map((x, i) => h('li', {},
    h('span', { class: 'when' }, when(x.t)), h('b', {}, labelOf(x.file, name)), ' ', h('span', { class: 'muted' }, [x.summary, x.who].filter(Boolean).join(' · ')),
    i === 0 ? h('span', { class: 'muted small' }, 'now') : h('button', { class: 'quiet', onclick: async () => {
      await api('/api/history/restore', { work, id: x.id });
      dispatchEvent(new Event('hashchange'));
    } }, 'Put this back')));
  return h('div', { class: 'card', id: 'historyPanel' }, h('b', {}, 'History'),
    rows.length ? h('p', { class: 'muted small' }, 'Every change to the plan is kept. Putting a version back is saved too, so it can be undone.') : h('p', { class: 'muted' }, 'No changes yet.'),
    h('ul', { class: 'history' }, ...rows));
}
