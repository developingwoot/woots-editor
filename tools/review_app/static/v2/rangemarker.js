import { h } from './util.js';

// One range-marking component for clips and cuts: a player, a strip showing the marked ranges, Mark start / Mark end at the playhead,
// a label, and the list of ranges. Used by tags on footage; the good / don't-touch marks on a cut use the same component.
//   rangeMarker({ src, ranges: [{id, start, end, label}], labelPlaceholder, addLabel, onAdd({start, end, label}), onRemove(range) })
// onAdd / onRemove may return a promise of the new ranges (or nothing); the strip and the list redraw from them.
const clock = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

export function rangeMarker({ src, ranges = [], labelPlaceholder = 'What is on screen?', addLabel = 'Add tag', onAdd, onRemove }) {
  let list = ranges;
  const video = h('video', { class: 'rmVideo', src, controls: true, preload: 'metadata' });
  const strip = h('div', { class: 'rmStrip', title: 'Click to jump' });
  const start = h('input', { type: 'number', class: 'rmNum', id: 'rmStart', min: 0, step: 0.1, value: '' });
  const end = h('input', { type: 'number', class: 'rmNum', id: 'rmEnd', min: 0, step: 0.1, value: '' });
  const label = h('input', { type: 'text', class: 'rmLabel', id: 'rmLabel', placeholder: labelPlaceholder, autocomplete: 'off' });
  const note = h('div', { class: 'muted small', id: 'rmNote' });
  const rows = h('div', { class: 'rmList', id: 'rmList' });
  const at = () => Math.round(video.currentTime * 10) / 10;
  const say = t => { note.textContent = t || ''; };

  const redraw = () => {
    const len = video.duration || Math.max(1, ...list.map(r => r.end));
    strip.replaceChildren(...list.map(r => h('div', { class: 'rmSeg', style: `left:${r.start / len * 100}%;width:${Math.max(0.5, (r.end - r.start) / len * 100)}%`, title: r.label,
      onclick: e => { e.stopPropagation(); video.currentTime = r.start; } })));
    rows.replaceChildren(...list.map(r => h('div', { class: 'rmRow', 'data-id': r.id },
      h('button', { class: 'quiet', onclick: () => { video.currentTime = r.start; video.play(); } }, `${clock(r.start)}–${clock(r.end)}`),
      h('span', { class: 'rmText' }, r.label),
      h('button', { class: 'x', title: 'Remove', onclick: async () => { try { apply(await onRemove(r)); } catch (e) { say(e.message); } } }, '✕'))));
    if (!list.length) rows.replaceChildren(h('div', { class: 'muted small' }, 'Nothing marked yet.'));
  };
  const apply = next => { if (Array.isArray(next)) list = next; redraw(); };
  strip.addEventListener('click', e => { const b = strip.getBoundingClientRect(); if (video.duration) video.currentTime = (e.clientX - b.left) / b.width * video.duration; });
  video.addEventListener('loadedmetadata', redraw);

  const addBtn = h('button', { class: 'main small', id: 'rmAdd', onclick: async () => {
    try {
      const next = await onAdd({ start: parseFloat(start.value), end: parseFloat(end.value), label: label.value });
      label.value = ''; start.value = end.value; end.value = '';
      say('');
      apply(next);
    } catch (e) { say(e.message); }
  } }, addLabel);
  const el = h('div', { class: 'rangeMarker' }, video, strip,
    h('div', { class: 'rmControls' },
      h('button', { class: 'quiet', id: 'rmMarkStart', onclick: () => { start.value = at(); if (!end.value || +end.value <= at()) end.value = ''; } }, 'Mark start'), start,
      h('button', { class: 'quiet', id: 'rmMarkEnd', onclick: () => { end.value = at(); } }, 'Mark end'), end),
    h('div', { class: 'rmControls' }, label, addBtn), note, rows);
  redraw();
  el.video = video;
  return el;
}
