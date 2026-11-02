import { h, api } from './util.js';

function card(v) {
  return h('div', { class: 'vcard' },
    v.thumb ? h('img', { class: 'vthumb', src: `/api/v2/thumb?key=${encodeURIComponent(v.key)}`, alt: '' }) : h('div', { class: 'vthumb' }),
    h('div', { class: 'vbody' },
      h('div', { class: 'vtitle' }, v.title),
      h('div', { class: 'muted' }, v.sentence)),
    h('a', { class: 'main', href: `#/v/${v.key}/${v.step}` }, v.button));
}

async function newVideo() {
  const title = prompt('What is the video called?');
  if (!title) return;
  try {
    const r = await api('/api/v2/video/new', { title });
    location.hash = `#/v/${r.key}/outline`;
  } catch (e) { alert(e.message); }
}

export async function render(root) {
  const data = await api('/api/v2/home');
  const list = data.videos.length
    ? data.videos.map(card)
    : [h('div', { class: 'card empty' }, h('p', {}, 'No videos yet.'), h('p', { class: 'muted' }, 'Start one to begin the outline.'))];
  root.replaceChildren(
    h('div', { class: 'headrow' }, h('h1', {}, 'Your videos'), h('button', { class: 'main', id: 'newVideo', onclick: newVideo }, '+ New video')),
    ...list,
    ...(data.done.length ? [h('details', { class: 'doneBox' }, h('summary', {}, `Done (${data.done.length})`), ...data.done.map(card))] : []));
}
