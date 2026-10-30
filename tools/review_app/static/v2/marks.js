import { h, api } from './util.js';

// Good / don't-touch marks on the rough cut: the cut's words in order; tick a run of sentences (shift-click for a range) and mark it good.
// Marked sentences are never dropped, replaced, re-zoomed or given another cutaway when the cut is made again or Claude is asked for changes.
// Returns { card, overlay }: the card goes under the player, the overlay (marked ranges) sits on the clip strip.
export function marksCard(key, video, total) {
  const q = encodeURIComponent(key);
  const overlay = h('div', { class: 'markBand', id: 'markBand' });
  const list = h('div', { class: 'markList', id: 'markList' });
  const note = h('span', { class: 'muted small', id: 'markNote' });
  const mark = h('button', { class: 'main small', id: 'markGood', disabled: true }, 'Mark as good');
  const card = h('div', { class: 'card marks', id: 'marks' },
    h('div', { class: 'rhead' }, h('b', {}, 'Good parts'), h('span', { class: 'muted small' }, 'Marked parts stay exactly as they are when the cut changes.')),
    list, h('div', { class: 'row' }, mark, note));
  let rows = [];
  const picked = new Set();
  let anchor = null;

  const draw = () => {
    overlay.replaceChildren(...rows.filter(r => r.lock).map(r => h('div', { class: 'markSeg', style: `left:${r.start / total * 100}%;width:${Math.max(0.3, (r.end - r.start) / total * 100)}%` })));
    list.replaceChildren(...rows.map((r, i) => h('div', { class: 'markRow' + (r.lock ? ' good' : '') + (picked.has(r.id) ? ' on' : ''), 'data-id': r.id },
      h('input', { type: 'checkbox', checked: picked.has(r.id), onclick: e => {
        const on = e.target.checked;
        if (e.shiftKey && anchor !== null) for (const x of rows.slice(Math.min(anchor, i), Math.max(anchor, i) + 1)) on ? picked.add(x.id) : picked.delete(x.id);
        else on ? picked.add(r.id) : picked.delete(r.id);
        anchor = i;
        draw();
      } }),
      h('a', { class: 'when', href: '#', onclick: e => { e.preventDefault(); video.currentTime = r.start; } }, r.at),
      h('span', { class: 'ntext' }, r.text),
      r.lock ? h('button', { class: 'quiet tiny', title: 'Let the editor change this again', onclick: () => send({ op: 'unlock', id: r.lock, ids: [r.id] }) }, 'Unlock') : null)));
    const free = [...picked].filter(id => !rows.find(r => r.id === id).lock);
    mark.disabled = !free.length;
    mark.textContent = free.length ? `Mark ${free.length} sentence${free.length === 1 ? '' : 's'} as good` : 'Mark as good';
    if (!rows.length) list.replaceChildren(h('div', { class: 'muted small' }, 'The cut has no spoken sentences yet.'));
  };
  const take = r => { rows = r.sentences; for (const id of [...picked]) if (!rows.some(x => x.id === id)) picked.delete(id); draw(); };
  const send = async body => {
    try { note.textContent = ''; take(await api('/api/v2/locks', { key, ...body })); } catch (e) { note.textContent = e.message; }
  };
  mark.addEventListener('click', async () => {
    const ids = [...picked].filter(id => !rows.find(r => r.id === id).lock);
    picked.clear();
    await send({ op: 'lock', ids });
  });
  api(`/api/v2/locks?key=${q}`).then(take).catch(e => { note.textContent = e.message; });
  return { card, overlay };
}
