import { h, api, say } from './util.js';
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
    try { await api('/api/v2/shorts/fromfile', { path }); setBusy(); } catch (e) { say(e.message); }
  };
  const fromFolder = async () => {
    let start = '';
    try { start = localStorage.getItem('wr.rawDir') || ''; } catch { /* private mode */ }
    const path = await pickFolder({ start, title: 'Choose the folder with the raw footage' });
    if (!path) return;
    try { localStorage.setItem('wr.rawDir', path.replace(/[\\/][^\\/]*$/, '')); } catch { /* private mode */ }
    try { await api('/api/v2/shorts/fromfolder', { path }); setBusy(); } catch (e) { say(e.message); }
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

  const run = async (op, body) => { try { await post(op, body); setBusy(); } catch (e) { say(e.message); } };

  async function wordsPanel(box, id) {
    const w = await api(`/api/v2/shorts/words?key=${encodeURIComponent(key)}&id=${encodeURIComponent(id)}`);
    const toggle = async (word, cut) => { try { drawWords(await post('cut', { id, start: word.s, end: word.e, cut })); } catch (e) { say(e.message); } };
    const drawWords = data => box.replaceChildren(
      h('div', { class: 'glabel' }, 'Words (click a word to cut it out, click it again to bring it back)'),
      ...data.ranges.map(r => h('p', { class: 'wordRange' }, ...r.words.map(x =>
        h('button', { class: 'w' + (x.cut ? ' cut' : ''), title: x.why === 'backchannel' ? 'Left out: a little “yeah” from someone else' : '', onclick: () => toggle(x, !x.cut) }, x.w)))));
    drawWords(w);
  }

  async function soundPanel(box, d, s) {
    const o = await api('/api/v2/shorts/sounds');
    const set = (op, body) => async () => { try { draw(await post(op, { id: s.id, ...body })); } catch (e) { say(e.message); } };
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

  function graphicsPanel(d, s) {
    const g = s.gfx;
    if (!g.can) return h('div', { class: 'shortGfx', id: 'shortGfx' }, h('div', { class: 'glabel' }, 'Graphics'), h('div', { class: 'muted small' }, 'Graphics are not planned yet for a short joined from several recordings.'));
    const cut = (x) => async () => { try { draw(await post('gfxcut', { id: s.id, g: x.id, cut: !x.cut })); } catch (e) { say(e.message); } };
    return h('div', { class: 'shortGfx', id: 'shortGfx' },
      h('div', { class: 'glabel' }, 'Graphics'),
      ...[g.graphics.length ? g.graphics.map(x => h('div', { class: 'gfxRow' + (x.cut ? ' cut' : ''), 'data-gid': x.id },
        h('div', { class: 'vbody' }, h('b', {}, x.title), h('div', { class: 'muted small' }, `${x.look} · ${x.place}${x.words ? ' · “' + x.words + '”' : ''}`)),
        h('button', { class: 'quiet gfxCut', onclick: cut(x) }, x.cut ? 'Bring back' : 'Cut'))) : [],
        g.note ? [h('div', { class: 'muted small' }, g.note)] : [],
        g.skipped.length ? [h('div', { class: 'muted small' }, 'Left out: ' + g.skipped.join('; '))] : [],
        [h('div', { class: 'row' }, h('button', { class: 'quiet', id: 'gfxPlanBtn', disabled: d.busy, onclick: () => run('gfxplan', { id: s.id }) }, g.planned ? 'Plan the graphics again' : 'Plan graphics'),
          h('span', { class: 'muted small' }, g.graphics.length ? 'They are built into the preview.' : 'Claude proposes where graphics go; each is built into the preview unless you cut it.'))]].flat());
  }

  function publishPanel(d, s) {
    const p = s.publish;
    const save = (k) => async e => { try { draw(await post('publish', { id: s.id, [k]: e.target.value })); } catch (err) { say(err.message); } };
    const field = (id, label, tag, attrs, k) => { const el = h(tag, { id, ...attrs }); el.value = p[k]; el.addEventListener('change', save(k)); return [h('label', { class: 'glabel', for: id }, label), el]; };
    return h('div', { class: 'shortPublish', id: 'shortPublish' },
      h('div', { class: 'glabel' }, 'YouTube details'),
      ...field('pubTitle', 'Title', 'input', { type: 'text', maxlength: 100, autocomplete: 'off' }, 'title'),
      ...field('pubDesc', 'Description', 'textarea', { rows: 5 }, 'description'),
      ...field('pubTags', 'Tags (separated by commas)', 'input', { type: 'text', autocomplete: 'off' }, 'tags'),
      ...field('pubFile', 'File name', 'input', { type: 'text', autocomplete: 'off' }, 'filename'),
      h('div', { class: 'row' }, h('button', { class: 'quiet', id: 'titlesBtn', disabled: d.busy, onclick: () => run('titles', { id: s.id }) }, p.written ? 'Write them again' : 'Write them for me'),
        h('span', { class: 'muted small' }, p.written ? 'Edit anything above; it is saved when you leave the box.' : 'Claude writes a title, description, tags and file name from what the short says.')));
  }

  // The host's feedback: plain notes. On one short they wait until Claude applies them (cuts, hook, title); the general ones are given to every later run.
  function feedbackList(f, sid, general) {
    const edit = (n, body) => async () => { try { draw(await post('noteedit', { id: sid, note: n.id, ...body })); } catch (e) { say(e.message); } };
    return f.notes.map(n => h('div', { class: 'noteRow' + (n.status === 'done' ? ' done' : ''), 'data-note': n.id },
      h('div', { class: 'vbody' }, n.text),
      general ? null : h('span', { class: 'chip ' + (n.status === 'done' ? 'ok' : '') }, n.status === 'done' ? 'Applied' : 'Waiting'),
      !general && n.status === 'done' ? h('button', { class: 'quiet noteReopen', onclick: edit(n, { status: 'open' }) }, 'Again') : null,
      h('button', { class: 'quiet noteDelete', onclick: edit(n, { delete: true }) }, 'Delete')));
  }
  function feedbackBox(d, f, sid, general) {
    const input = h('textarea', { class: 'fbInput', rows: 2, autocomplete: 'off',
      placeholder: general ? 'e.g. “Hooks are too long” or “Start every short on the answer”' : 'e.g. “Start on the number” or “Cut the story about the failed print”' });
    const add = async () => {
      if (!input.value.trim()) return;
      try { draw(await post('note', { id: sid, text: input.value })); } catch (e) { say(e.message); }
    };
    return [...feedbackList(f, sid, general),
      input,
      h('div', { class: 'row' }, h('button', { class: 'quiet fbAdd', onclick: add }, 'Save the note'),
        general ? null : h('button', { class: 'main small fbApply', disabled: d.busy || !f.open, onclick: () => run('feedback', { id: sid }) }, f.open ? `Apply ${f.open} note${f.open !== 1 ? 's' : ''}` : 'Apply my notes'),
        h('span', { class: 'muted small' }, general ? 'Claude reads these every time it chooses, tightens, plans or titles shorts.' : 'Claude changes the cuts, hook or title to match; sound, captions and crops stay yours.')),
      !general && f.result ? h('div', { class: 'muted small fbResult' }, f.result) : null,
      !general && f.face != null ? h('div', { class: 'small fbFace' }, `${Math.round(f.face * 100)}% of the words are spoken over your face.`) : null,
      !general && f.unmet.length ? h('div', { class: 'small fbUnmet' }, 'Claude could not do: ' + f.unmet.join('; ')) : null].filter(Boolean);
  }

  function openPanel(d, s) {
    const hook = h('input', { id: 'hookInput', type: 'text', value: s.hook, placeholder: 'Words shown over the first seconds', autocomplete: 'off' });
    hook.addEventListener('change', async () => { try { draw(await post('hook', { id: s.id, hook: hook.value })); } catch (e) { say(e.message); } });
    const pace = h('select', { id: 'paceSelect', onchange: async e => { try { draw(await post('pace', { id: s.id, pace: e.target.value })); } catch (err) { say(err.message); } } },
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
          h('div', { class: 'shortFeedback', id: 'shortFeedback' }, h('div', { class: 'glabel' }, 'Your feedback'), ...feedbackBox(d, s.feedback, s.id, false)),
          sound, graphicsPanel(d, s), publishPanel(d, s),
          h('div', { class: 'row' }, h('button', { class: 'quiet', id: 'tightenBtn', disabled: d.busy, onclick: () => run('tighten', { id: s.id }) }, s.tightened ? 'Tighten it again' : 'Tighten it'),
            h('span', { class: 'muted small' }, 'Claude cuts the filler and tangents out of this short.')),
          words)));
  }

  function shortCard(d, s) {
    const act = (op, body) => async () => { try { draw(await post(op, body)); } catch (e) { say(e.message); } };
    return h('div', { class: 'shortBlock', 'data-id': s.id },
      h('div', { class: 'vcard shortCard' + (s.status ? ' ' + s.status : ''), 'data-id': s.id, 'data-status': s.status },
        h('img', { class: 'sthumb', src: s.frame, alt: '', loading: 'lazy' }),
        h('div', { class: 'vbody' },
          h('div', { class: 'vtitle' }, s.title),
          h('div', { class: 'muted' }, [s.length, s.hook].filter(Boolean).join(' · ')),
          s.why ? h('div', { class: 'muted small' }, s.why) : null),
        s.status === 'kept' ? h('span', { class: 'chip ok' }, 'Kept') : null,
        s.delivered.file ? h('span', { class: 'chip ' + (s.delivered.current ? 'ok' : ''), title: s.delivered.file }, s.delivered.current ? 'Saved' : 'Saved, changed since') : null,
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
      h('div', { class: 'row', id: 'deliverRow' },
        h('label', { class: 'glabel', for: 'linkInput' }, 'Full video link'),
        (() => { const i = h('input', { id: 'linkInput', type: 'text', placeholder: 'Put this in each description', autocomplete: 'off' }); i.value = d.full_video_url || '';
          i.addEventListener('change', async () => { try { draw(await post('link', { url: i.value })); } catch (e) { say(e.message); } }); return i; })(),
        h('button', { class: 'quiet', id: 'allTitlesBtn', disabled: d.busy || !d.shorts.length, onclick: () => run('titles') }, 'Write all the titles')),
      h('div', { class: 'muted small', id: 'folderNote' }, `The final shorts are saved in ${d.folder}, each with a text file of its title, description and tags.`),
      h('details', { class: 'doneBox', id: 'rawStory' },
        h('summary', {}, 'A newer story from the raw footage'),
        (() => {
          const text = h('textarea', { class: 'fbInput', id: 'rawText', rows: 3, autocomplete: 'off', placeholder: 'e.g. “Tell the story of the failed first print and what fixed it” or “Redo this one without the part about the slicer”' });
          const base = h('select', { id: 'rawBase' }, h('option', { value: '' }, 'A new story (not based on a short)'),
            ...d.shorts.map(s => h('option', { value: s.id }, `Redo: ${s.title}`)));
          const go = async () => { try { await post('fromraw', { id: base.value, text: text.value }); setBusy(); } catch (e) { say(e.message); } };
          return h('div', {}, text, h('div', { class: 'row' }, base, h('button', { class: 'main small', id: 'rawGo', disabled: d.busy, onclick: go }, 'Make it from the raw footage')),
            h('div', { class: 'muted small' }, 'Claude reads the recordings this video was filmed from and makes a new short, which appears as its own project in the Shorts list. The shorts you have now stay as they are.'));
        })()),
      h('details', { class: 'doneBox', id: 'generalFeedback', open: d.feedback.notes.length > 0 },
        h('summary', {}, `Feedback for all shorts${d.feedback.notes.length ? ` (${d.feedback.notes.length})` : ''}`),
        ...feedbackBox(d, d.feedback, '', true)),
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
