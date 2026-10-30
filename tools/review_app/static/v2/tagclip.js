import { h, api } from './util.js';
import { rangeMarker } from './rangemarker.js';

// Tag a clip: watch it, mark a range, say what is on screen. Tags beat the model's description when the app looks for footage.
// Resolves with the number of tags the clip has when the dialog closes.
export async function tagClip(key, rel) {
  const q = encodeURIComponent(key);
  const mine = all => all.filter(t => t.rel === rel).map(t => ({ id: t.id, start: t.start, end: t.end, label: t.label }));
  const post = body => api('/api/v2/tags', { key, rel, ...body }).then(r => mine(r.tags));
  const { tags } = await api(`/api/v2/tags?key=${q}`);
  let count = mine(tags).length;
  return new Promise(resolve => {
    const dlg = h('dialog', { class: 'tagDlg', id: 'tagDlg' });
    const done = () => { dlg.close(); dlg.remove(); resolve(count); };
    const marker = rangeMarker({
      src: `/api/v2/source?key=${q}&rel=${encodeURIComponent(rel)}`, ranges: mine(tags),
      onAdd: async r => { const out = await post({ op: 'add', ...r }); count = out.length; return out; },
      onRemove: async r => { const out = await post({ op: 'delete', id: r.id }); count = out.length; return out; },
    });
    dlg.addEventListener('cancel', done);
    dlg.append(h('h3', {}, `Tag ${rel.split('/').pop()}`),
      h('p', { class: 'muted small' }, 'Play the clip, mark where something happens and say what is on screen, for example "Fluidd dashboard, console tab". The editor trusts your tags over its own guess.'),
      marker, h('div', { class: 'row' }, h('button', { class: 'main', id: 'tagDone', onclick: done }, 'Done')));
    document.body.append(dlg);
    dlg.showModal();
  });
}
