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
  const detail = (v.renders ? 'It already has renders (a cut, a preview or a final): Archive keeps its plans instead. ' : '') +
    'Its outline, notes and plans go to the trash folder in your workspace, where you can get them back. Your footage is not touched.';
  if (await sure(`Delete “${v.title}”?`, detail, 'Delete')) act('/api/v2/video/delete', v, { confirm: true });
}

// Archive: a finished video gets the Final screen's Finish and archive; any other has its renders and caches cleaned up and is put away.
async function archive(v) {
  let p;
  try { p = await api('/api/v2/video/archive-preview', { key: v.key }); } catch (e) { say(e.message); return; }
  const detail = p.kind === 'finish'
    ? `The final (${p.final_size}) moves to the footage folder as “${p.final_name}”, with the project saved next to it. ` +
      (p.delete.length ? `Deleted for good: ${p.delete.map(d => `${d.what} (${d.size})`).join('; ')}. ` : '') + `Frees ${p.frees}.`
    : (p.delete ? `Deletes for good what the app can make again (renders, sound files, caches: ${p.frees}). ` : 'There is nothing to clean up. ') + p.keep;
  if (await sure(`Archive “${v.title}”?`, detail, 'Archive')) act('/api/v2/video/archive', v, { confirm: true });
}

function menu(v) {
  const first = !v.archived ? h('button', { class: 'quiet', onclick: () => archive(v) }, 'Archive…')
    : !v.finished ? h('button', { class: 'quiet', onclick: () => act('/api/v2/video/unarchive', v) }, 'Unarchive') : null;
  return h('details', { class: 'vmenu' }, h('summary', { 'aria-label': `More for ${v.title}`, title: 'More' }, '⋯'),
    h('div', { class: 'vmenuList' }, ...(first ? [first] : []),
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

// The starter skills have rules or numbers the user's own copy of a skill lacks: say so, list them, and add them on request (nothing of theirs is changed).
function skillNote(u, root) {
  const n = u.count;
  const add = async () => {
    try {
      const r = await api('/api/v2/skills/update', {});
      say(`Added ${r.rules} rule${r.rules === 1 ? '' : 's'} and ${r.numbers} number${r.numbers === 1 ? '' : 's'} to your skills.`);
      render(root);
    } catch (e) { say(e.message); }
  };
  return h('div', { class: 'card', id: 'skillUpdates' },
    h('p', {}, h('b', {}, `Your editing skills are missing ${n} newer rule${n === 1 ? '' : 's'} or number${n === 1 ? '' : 's'}.`)),
    h('p', { class: 'muted' }, 'The app already cuts by them, but your own copy of the skills does not say so, and Claude reads your copy. Adding them changes nothing you wrote; the old file is kept next to it as .bak.'),
    h('details', {}, h('summary', {}, 'What would be added'),
      h('ul', {}, ...u.rules.map(r => h('li', {}, `${r.about} (${r.file})`)),
        ...u.numbers.map(x => h('li', {}, `${x.key}: ${x.value}${x.was === undefined ? '' : ` (was ${x.was})`} (${x.file})`)))),
    h('div', { class: 'row' }, h('button', { class: 'main', id: 'skillUpdatesAdd', onclick: add }, 'Add them to my skills')));
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
    ...(data.skill_updates && data.skill_updates.count ? [skillNote(data.skill_updates, root)] : []),
    ...list,
    ...(data.archived.length ? [h('details', { class: 'doneBox', id: 'archivedList' }, h('summary', {}, `Archived (${data.archived.length})`), ...data.archived.map(card))] : []));
  const use = await usageLine();
  if (use && root.isConnected) root.append(use);
}
