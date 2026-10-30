import { h, api } from './util.js';
import { pickFolder } from './folder.js';
import { tagClip } from './tagclip.js';

// The Footage step: where the recordings are, what we have for each shot of the outline, the recordings themselves, and one button.
export async function render(root, key, setBusy) {
  const post = (path, body = {}) => api(path, { key, ...body });

  function shotRow(sec, it) {
    const thumbs = (cands, ready) => cands.map((c, idx) => {
      const on = ready && it.chosen && it.chosen.rel === c.rel && it.chosen.t === c.t;
      return h('button', { class: 'pickThumb' + (on ? ' on' : ''), title: c.what, onclick: async () => draw(await post('/api/v2/footage/choose', { shot: it.key, index: idx })) },
        h('img', { src: c.frame, alt: '', loading: 'lazy' }), h('span', {}, c.at));
    });
    const none = h('button', { class: 'quiet', onclick: async () => draw(await post('/api/v2/footage/choose', { shot: it.key, index: null })) }, 'None of these');
    return h('div', { class: 'frow shot ' + it.status, 'data-status': it.status },
      h('div', { class: 'ftext' }, h('span', { class: 'dotmark' }, '▸'), it.text),
      it.status === 'ready'
        ? h('div', { class: 'picks' }, ...thumbs(it.candidates, true), none)
        : h('div', { class: 'picks' }, h('span', { class: 'chip warn' }, 'Nothing yet'),
          it.candidates.length ? h('details', { class: 'closest' }, h('summary', {}, 'Closest clips'), h('div', { class: 'picks' }, ...thumbs(it.candidates, false))) : null));
  }

  function takeRow(it) {
    return h('div', { class: 'frow take ' + it.status, 'data-status': it.status },
      h('div', { class: 'ftext' }, h('span', { class: 'mark ' + it.status }, it.status === 'ready' ? '✓' : '○'), `Says: “${it.text}”`),
      it.status === 'ready' ? h('span', { class: 'muted small' }, `take found, ${it.len}`) : h('span', { class: 'chip warn' }, 'No take yet'));
  }

  async function draw(d) {
    const folderText = d.folder.set ? h('span', { id: 'folderPath', title: d.folder.path }, d.folder.short) : h('span', { class: 'muted' }, 'No footage folder yet. Choose the folder you recorded into.');
    const change = h('button', { class: 'quiet', id: 'changeFolder', onclick: async () => {
      const f = await pickFolder({ start: d.folder.path || '', suggest: d.folder.path ? [d.folder.path] : [] });
      if (f) { try { await draw(await post('/api/v2/footage/folder', { folder: f })); } catch (e) { alert(e.message); } }
    } }, d.folder.set ? 'Change folder' : 'Choose folder');
    const folderCard = h('div', { class: 'card' }, h('div', { class: 'rhead' }, h('b', {}, 'Footage folder'), change),
      folderText, d.folder.guessed ? h('span', { class: 'muted small' }, ' (matched to the video’s title)') : null,
      d.summary ? h('div', { class: 'muted small', id: 'footageSummary' }, d.summary) : null);

    const b = d.button;
    const go = h('button', { class: 'main', id: 'cutBtn', disabled: !b.enabled, onclick: async () => {
      go.disabled = true;
      try { await post('/api/v2/footage/cut'); setBusy(); } catch (e) { alert(e.message); go.disabled = false; }
    } }, b.label);
    const copy = d.missing.length ? h('button', { class: 'quiet', id: 'copyMissing', onclick: async () => {
      try { await navigator.clipboard.writeText(d.missing.join('\n')); copy.textContent = 'Copied'; } catch { copy.textContent = 'Could not copy'; }
    } }, `Copy the list of missing shots (${d.missing.length})`) : null;
    const bar = h('div', { class: 'card makebar' }, go,
      h('div', { class: 'muted small' }, [b.why, b.detail, b.enabled && b.estimate ? `(${b.estimate})` : ''].filter(Boolean).join(' ')), copy);

    const shots = d.sections.length ? h('div', { class: 'card', id: 'shotsCard' }, h('b', {}, 'What we have for each shot'),
      ...d.sections.map(sec => h('div', { class: 'fsec' }, h('h4', {}, sec.section), ...sec.items.map(it => it.type === 'shot' ? shotRow(sec, it) : takeRow(it)))))
      : h('div', { class: 'card empty' }, h('p', {}, d.has_outline ? '' : 'There is no outline yet.'), h('p', { class: 'muted' }, 'Once the outline has talking points and shot ideas, this shows what footage matches each one.'));

    const rec = d.recordings;
    const grid = rec.total ? h('div', { class: 'card', id: 'recordings' }, h('b', {}, 'Recordings'),
      h('div', { class: 'recGrid' }, ...rec.rows.map(r => h('div', { class: 'rec' + (r.ignored ? ' ignored' : ''), 'data-speech': r.ignored ? 'left out' : r.speech },
        h('img', { src: r.frame, alt: '', loading: 'lazy' }),
        h('div', { class: 'recMeta' }, h('span', {}, r.len), h('span', { class: 'chip2 ' + (r.ignored ? '' : r.speech === 'read' ? 'ok' : r.speech === 'not read yet' ? 'todo' : '') }, r.ignored ? 'left out' : r.speech),
          r.looked && !r.ignored ? h('span', { class: 'looked', title: 'Looked at' }, '👁') : null,
          r.thin && !r.ignored ? h('span', { class: 'chip2 todo', title: 'The editor knows little about this clip. Tag what is on screen.' }, 'little data') : null,
          r.tags ? h('span', { class: 'chip2 ok' }, `${r.tags} tag${r.tags === 1 ? '' : 's'}`) : null,
          r.ignored ? null : h('button', { class: 'quiet tiny tagBtn', title: 'Say what is on screen in this clip', onclick: async () => { await tagClip(key, r.ref); draw(await api(`/api/v2/footage?key=${encodeURIComponent(key)}`)); } }, 'Tag'),
          h('button', { class: 'quiet tiny', title: r.ignored ? 'Use this recording' : 'This recording is not part of this video', onclick: async () => draw(await post('/api/v2/footage/ignore', { rel: r.ref, ignore: !r.ignored })) }, r.ignored ? 'Use it' : 'Leave out')))))) : null;

    root.replaceChildren(...[folderCard, bar, shots, grid].filter(Boolean));
  }
  await draw(await api(`/api/v2/footage?key=${encodeURIComponent(key)}`));
}
