import { h, api } from './util.js';
import { pickFolder } from './folder.js';

// Shorts. One screen, used two ways: the Shorts area (#/shorts: every video that has shorts or a final to make them from)
// and the Shorts step of a video (#/v/<key>/shorts: that video's shorts, one card each, open one to preview it and cut its words).

export async function render(root, args, setBusy) {
  const d = await api('/api/v2/shorts/list');
  const fromFile = async () => {
    let start = '';
    try { start = localStorage.getItem('wr.videoDir') || ''; } catch { /* private mode */ }
    const path = await pickFolder({ files: true, start, title: 'Choose the finished video' });
    if (!path) return;
    try { localStorage.setItem('wr.videoDir', path.replace(/[\\/][^\\/]*$/, '')); } catch { /* private mode */ }
    try { await api('/api/v2/shorts/fromfile', { path }); setBusy(); } catch (e) { alert(e.message); }
  };
  const fromFolder = async () => {
    let start = '';
    try { start = localStorage.getItem('wr.rawDir') || ''; } catch { /* private mode */ }
    const path = await pickFolder({ start, title: 'Choose the folder with the raw footage' });
    if (!path) return;
    try { localStorage.setItem('wr.rawDir', path.replace(/[\\/][^\\/]*$/, '')); } catch { /* private mode */ }
    try { await api('/api/v2/shorts/fromfolder', { path }); setBusy(); } catch (e) { alert(e.message); }
  };
  root.replaceChildren(
    h('div', { class: 'headrow' }, h('h1', {}, 'Shorts'),
      h('button', { class: 'quiet', id: 'fromFolder', onclick: fromFolder }, 'A short from raw footage'),
      h('button', { class: 'main', id: 'fromFile', onclick: fromFile }, 'Shorts from a video file')),
    ...(d.items.length
      ? d.items.map(v => h('div', { class: 'vcard shortsItem' },
        h('div', { class: 'vbody' }, h('div', { class: 'vtitle' }, v.title), h('div', { class: 'muted' }, v.sentence)),
        h('a', { class: 'main', href: v.standalone ? `#/shorts/${v.key}` : `#/v/${v.key}/shorts` }, v.button)))
      : [h('div', { class: 'card empty', id: 'noShorts' }, h('p', {}, 'No shorts yet.'), h('p', { class: 'muted' }, 'Render the final of a video and its shorts will be made from it, or start from a video file or a folder of raw footage.'))]));
}

// Shorts made from a video file that is not one of the app's videos: the same project screen under its own heading.
export async function renderStandalone(root, [key], setBusy) {
  const d = await api(`/api/v2/shorts?key=${encodeURIComponent(key)}`);
  const body = h('div', { id: 'stepBody' });
  root.replaceChildren(h('div', { class: 'headrow' }, h('a', { class: 'quiet', href: '#/shorts' }, '← Shorts'), h('h1', {}, d.title || 'Your shorts')), body);
  await renderStep(body, key, setBusy);
}

let remembered = { key: '', id: null };                  // the short that is open: a finished job redraws the page, and it should still be open

export async function renderStep(root, key, setBusy) {
  const post = (op, body = {}) => api(`/api/v2/shorts/${op}`, { key, ...body });
  let openId = remembered.key === key ? remembered.id : null;

  const run = async (op, body) => { try { await post(op, body); setBusy(); } catch (e) { alert(e.message); } };

  async function wordsPanel(box, id) {
    const w = await api(`/api/v2/shorts/words?key=${encodeURIComponent(key)}&id=${encodeURIComponent(id)}`);
    const toggle = async (word, cut) => { try { drawWords(await post('cut', { id, start: word.s, end: word.e, cut })); } catch (e) { alert(e.message); } };
    const drawWords = data => box.replaceChildren(
      h('div', { class: 'glabel' }, 'Words (click a word to cut it out, click it again to bring it back)'),
      ...data.ranges.map(r => h('p', { class: 'wordRange' }, ...r.words.map(x =>
        h('button', { class: 'w' + (x.cut ? ' cut' : ''), title: x.why === 'backchannel' ? 'Left out: a little “yeah” from someone else' : '', onclick: () => toggle(x, !x.cut) }, x.w)))));
    drawWords(w);
  }

  async function soundPanel(box, d, s) {
    const o = await api('/api/v2/shorts/sounds');
    const set = (op, body) => async () => { try { draw(await post(op, { id: s.id, ...body })); } catch (e) { alert(e.message); } };
    const pick = (id, label, cur, opts, op, key) => h('div', { class: 'soundRow' }, h('label', { class: 'glabel', for: id }, label),
      h('select', { id, onchange: e => set(op, { [key]: e.target.value })() }, ...opts.map(([v, t]) => h('option', { value: v, selected: v === cur }, t))));
    const made = s.sound.made || {};
    const notes = [made.track ? `Music: ${made.track}.` : '', made.sfx ? `${made.sfx} sound effects.` : '', ...(made.missing || [])].filter(Boolean);
    box.replaceChildren(...[
      h('div', { class: 'glabel' }, 'Sound'),
      pick('styleSelect', 'Captions', s.sound.style || o.default_style, o.styles.map(x => [x.id, x.label]), 'style', 'style'),
      pick('musicSelect', 'Music', s.sound.music, [['', 'Picked for you'], ['none', 'No music'], ...o.tracks.map(t => [t, t])], 'music', 'music'),
      pick('sfxSelect', 'Sound effects', s.sound.sfx, [['on', 'On'], ['off', 'Off']], 'sfx', 'sfx'),
      notes.length ? h('div', { class: 'muted small', id: 'soundNotes' }, notes.join(' ')) : null].filter(Boolean));
  }

  function openPanel(d, s) {
    const hook = h('input', { id: 'hookInput', type: 'text', value: s.hook, placeholder: 'Words shown over the first seconds', autocomplete: 'off' });
    hook.addEventListener('change', async () => { try { draw(await post('hook', { id: s.id, hook: hook.value })); } catch (e) { alert(e.message); } });
    const pace = h('select', { id: 'paceSelect', onchange: async e => { try { draw(await post('pace', { id: s.id, pace: e.target.value })); } catch (err) { alert(err.message); } } },
      ...Object.entries(d.paces).map(([k, label]) => h('option', { value: k, selected: k === s.pace }, label)));
    const preview = s.preview.url
      ? h('video', { id: 'shortPlayer', src: s.preview.url, controls: true, preload: 'metadata' })
      : h('div', { class: 'noPreview muted' }, 'No preview yet.');
    const make = h('button', { class: 'main small', id: 'previewBtn', disabled: d.busy, onclick: () => run('preview', { id: s.id }) },
      s.preview.url ? (s.preview.old ? 'Update the preview' : 'Make the preview again') : 'Make a preview');
    const words = h('div', { class: 'shortWords', id: 'shortWords' });
    wordsPanel(words, s.id);
    const sound = h('div', { class: 'shortSound', id: 'shortSound' });
    soundPanel(sound, d, s);
    return h('div', { class: 'card shortOpen', 'data-id': s.id },
      h('div', { class: 'openCols' },
        h('div', { class: 'openPreview' }, preview, s.preview.old ? h('div', { class: 'muted small' }, 'This preview is from before your last change.') : null, make),
        h('div', { class: 'openEdit' },
          h('label', { class: 'glabel' }, 'Hook'), hook,
          h('label', { class: 'glabel' }, 'Pace'), pace,
          sound,
          h('div', { class: 'row' }, h('button', { class: 'quiet', id: 'tightenBtn', disabled: d.busy, onclick: () => run('tighten', { id: s.id }) }, s.tightened ? 'Tighten it again' : 'Tighten it'),
            h('span', { class: 'muted small' }, 'Claude cuts the filler and tangents out of this short.')),
          words)));
  }

  function shortCard(d, s) {
    const act = (op, body) => async () => { try { draw(await post(op, body)); } catch (e) { alert(e.message); } };
    return h('div', { class: 'shortBlock', 'data-id': s.id },
      h('div', { class: 'vcard shortCard' + (s.status ? ' ' + s.status : ''), 'data-id': s.id, 'data-status': s.status },
        h('img', { class: 'sthumb', src: s.frame, alt: '', loading: 'lazy' }),
        h('div', { class: 'vbody' },
          h('div', { class: 'vtitle' }, s.title),
          h('div', { class: 'muted' }, [s.length, s.hook].filter(Boolean).join(' · ')),
          s.why ? h('div', { class: 'muted small' }, s.why) : null),
        s.status === 'kept' ? h('span', { class: 'chip ok' }, 'Kept') : null,
        h('button', { class: 'quiet keepBtn', onclick: act('keep', { id: s.id, keep: s.status !== 'kept' }) }, s.status === 'kept' ? 'Un-keep' : 'Keep'),
        h('button', { class: 'quiet dropBtn', onclick: act('drop', { id: s.id }) }, 'Drop'),
        h('button', { class: 'main small openBtn', onclick: () => { openId = openId === s.id ? null : s.id; remembered = { key, id: openId }; draw(d); } }, openId === s.id ? 'Close' : 'Open')),
      openId === s.id ? openPanel(d, s) : null);
  }

  let last = null;
  async function draw(d) {
    last = d;
    if (d.needs) {
      root.replaceChildren(h('div', { class: 'card empty', id: 'needFinal' }, h('p', {}, d.needs), h('a', { class: 'main', href: `#/v/${key}/final` }, 'Go to the Final step')));
      return;
    }
    if (!d.has_project) {
      root.replaceChildren(h('div', { class: 'card empty', id: 'noProject' },
        h('p', {}, d.recommendation.sentence || 'The final is ready.'),
        h('p', { class: 'muted' }, 'The final is read word by word first, then Claude chooses where the shorts are. It takes a few minutes.'),
        h('button', { class: 'main', id: 'makeBtn', disabled: d.busy, onclick: () => run('make') }, 'Make the shorts')));
      return;
    }
    const head = h('div', { class: 'card shortsHead' },
      d.note ? h('div', { class: 'muted small', id: 'softNote' }, d.note) : null,
      h('div', { class: 'rhead' },
        h('div', {}, h('b', {}, d.recommendation.sentence || 'Your shorts'), d.last_find ? h('div', { class: 'muted small' }, d.last_find) : null),
        h('div', { class: 'row' },
          h('button', { class: 'quiet', id: 'findBtn', disabled: d.busy, onclick: () => run('find') }, 'Find more shorts'),
          h('button', { class: 'main', id: 'finishBtn', disabled: d.busy || !d.shorts.length, onclick: () => run('finish') }, 'Make the final shorts'))),
      d.unlooked ? h('div', { class: 'muted small', id: 'unlooked' },
        `${d.unlooked} short${d.unlooked !== 1 ? 's' : ''} you have not kept or dropped will be made too.`) : null);
    const list = d.shorts.length
      ? d.shorts.map(s => shortCard(d, s))
      : [h('div', { class: 'card empty', id: 'noneLeft' }, h('p', {}, 'No shorts left.'), h('p', { class: 'muted' }, 'Press Find more shorts and Claude will choose some.'))];
    const dropped = d.dropped.length
      ? h('details', { class: 'doneBox', id: 'droppedBox' }, h('summary', {}, `Dropped (${d.dropped.length})`),
        ...d.dropped.map(x => h('div', { class: 'droppedRow' }, h('span', {}, x.title),
          h('button', { class: 'quiet', onclick: async () => draw(await post('drop', { id: x.id, drop: false })) }, 'Bring back'))))
      : null;
    root.replaceChildren(...[head, ...list, dropped].filter(Boolean));
  }

  await draw(await api(`/api/v2/shorts?key=${encodeURIComponent(key)}`));
}
