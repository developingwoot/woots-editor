import { h, api } from './util.js';

// A folder chooser: a dialog that walks the drives and folders (the server lists them), with "Use this folder".
// pickFolder({ start, suggest: [paths] }) resolves to the chosen path, or null if the dialog was closed.
export function pickFolder({ start = '', suggest = [], title = 'Choose the folder you recorded into' } = {}) {
  return new Promise(resolve => {
    const dlg = h('dialog', { class: 'folderDlg', id: 'folderDlg' });
    const path = h('input', { id: 'fdPath', type: 'text', autocomplete: 'off' });
    const list = h('div', { class: 'fdList', id: 'fdList' });
    const info = h('div', { class: 'muted small', id: 'fdInfo' });
    const use = h('button', { class: 'main', id: 'fdUse', disabled: true }, 'Use this folder');
    let current = '';
    let seq = 0;                                       // only the newest listing is shown: a slow earlier one must not overwrite it
    const done = value => { dlg.close(); dlg.remove(); resolve(value); };

    async function browse(p) {
      const mine = ++seq;
      try {
        const r = await api(`/api/fs?path=${encodeURIComponent(p || '')}`);
        if (mine !== seq) return;
        current = r.path;
        path.value = r.path;
        list.replaceChildren(
          ...(r.path ? [h('div', { class: 'fdRow', onclick: () => browse(r.parent) }, '⬑ Up')] : []),
          ...r.dirs.map(d => h('div', { class: 'fdRow', onclick: () => browse(d.path) }, `📁 ${d.name}`)),
          ...(r.dirs.length ? [] : [h('div', { class: 'muted small' }, 'No folders in here.')]));
        info.textContent = r.path ? `${r.videos} video file${r.videos === 1 ? '' : 's'} directly in this folder` : 'Choose a drive';
        use.disabled = !r.path;
      } catch (e) { info.textContent = e.message; }
    }
    path.addEventListener('keydown', e => { if (e.key === 'Enter') browse(path.value.trim()); });
    use.addEventListener('click', () => done(current));
    dlg.addEventListener('cancel', () => done(null));
    dlg.append(h('h3', {}, title),
      suggest.length ? h('div', { class: 'fdSuggest' }, h('span', { class: 'muted small' }, 'Suggestion: '), ...suggest.map(s => h('button', { class: 'quiet', onclick: () => browse(s) }, s))) : null,
      path, list, info, h('div', { class: 'row' }, use, h('button', { class: 'quiet', onclick: () => done(null) }, 'Cancel')));
    document.body.append(dlg);
    dlg.showModal();
    browse(start || suggest[0] || '');
  });
}
