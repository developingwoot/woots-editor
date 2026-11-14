import { h, api, say, ask } from './util.js';
import { usageLine } from './extras.js';

// Confirm a delete in the app's own dialog (window.confirm is blocked in some embeds and looks out of place).
function sure(title, detail, okLabel) {
  return new Promise(resolve => {
    const done = v => { dlg.close(); dlg.remove(); resolve(v); };
    const dlg = h('dialog', { id: 'sureDialog' },
      h('p', {}, h('b', {}, title)), h('p', { class: 'muted' }, detail),
      h('div', { class: 'row' }, h('button', { class: 'main', id: 'sureOk', onclick: () => done(true) }, okLabel),
        h('button', { class: 'quiet', id: 'sureCancel', onclick: () => done(false) }, 'Cancel')));
    dlg.addEventListener('cancel', () => done(false));
    document.body.append(dlg);
    dlg.showModal();
  });
}

async function act(path, v, body = {}) {
  try { await api(path, { key: v.key, ...body }); render(document.getElementById('screen')); }
  catch (e) { say(e.message); }
}

async function del(v) {
  const detail = (v.renders ? 'It already has renders (a cut, a preview or a final): Hide keeps it instead. ' : '') +
    'Its outline, notes and plans go to the trash folder in your workspace, where you can get them back. Your footage is not touched.';
  if (await sure(`Delete “${v.title}”?`, detail, 'Delete')) act('/api/v2/video/delete', v, { confirm: true });
}

function menu(v) {
  return h('details', { class: 'vmenu' }, h('summary', { 'aria-label': `More for ${v.title}`, title: 'More' }, '⋯'),
    h('div', { class: 'vmenuList' },
      v.hidden ? h('button', { class: 'quiet', onclick: () => act('/api/v2/video/unhide', v) }, 'Unhide')
        : h('button', { class: 'quiet', onclick: () => act('/api/v2/video/hide', v) }, 'Hide'),
      h('button', { class: 'quiet', onclick: () => del(v) }, 'Delete…')));
}

function card(v) {
  return h('div', { class: 'vcard' },
    v.thumb ? h('img', { class: 'vthumb', src: `/api/v2/thumb?key=${encodeURIComponent(v.key)}`, alt: '' }) : h('div', { class: 'vthumb' }),
    h('div', { class: 'vbody' },
      h('div', { class: 'vtitle' }, v.title),
      h('div', { class: 'muted' }, v.sentence)),
    h('a', { class: 'main', href: `#/v/${v.key}/${v.step}` }, v.button),
    menu(v));
}

async function newVideo() {
  const title = await ask('What is the video called?', { placeholder: 'My next video', okLabel: 'Create' });
  if (!title) return;
  try {
    const r = await api('/api/v2/video/new', { title });
    location.hash = `#/v/${r.key}/outline`;
  } catch (e) { say(e.message); }
}

export async function render(root) {
  const data = await api('/api/v2/home');
  const list = data.videos.length
    ? data.videos.map(card)
    : [h('div', { class: 'card empty' }, h('p', {}, 'No videos yet.'), h('p', { class: 'muted' }, 'Start one to begin the outline.'))];
  root.replaceChildren(
    h('div', { class: 'headrow' }, h('h1', {}, 'Your videos'), h('button', { class: 'main', id: 'newVideo', onclick: newVideo }, '+ New video')),
    ...list,
    ...(data.done.length ? [h('details', { class: 'doneBox' }, h('summary', {}, `Done (${data.done.length})`), ...data.done.map(card))] : []),
    ...(data.hidden && data.hidden.length ? [h('details', { class: 'doneBox', id: 'hiddenBox' }, h('summary', {}, `Hidden (${data.hidden.length})`), ...data.hidden.map(card))] : []));
  const use = await usageLine();
  if (use && root.isConnected) root.append(use);
}
