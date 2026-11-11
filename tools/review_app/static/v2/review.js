import { h, api, say } from './util.js';
import { marksCard } from './marks.js';
import { factCheckCard, musicCard } from './extras.js';

// The review screen, shared by the rough cut and the preview: player, clips as a strip, notes pinned to the time, versions, one main button.
// In the rough cut a click on a clip also opens Keep / Replace / Trim / Remove / Note for that clip, and teaching moments sit below the strip.
const fmt = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
const PENDING = { replace: 'Another take', remove: 'Out', trim: 'Trimmed' };

let keyHandler = null;
let reopen = null;                                     // a clip whose Replace panel to open again after a background search
document.addEventListener('keydown', e => { if (keyHandler) keyHandler(e); });
export function leave() { keyHandler = null; }

export async function render(root, key, stage, setBusy) {
  let version = null;
  let selected = null;                                   // the clip (ref) whose panel is open
  const state = { range: null, pin: null };
  const post = (path, body) => api(path, { key, stage, ...body });

  async function load() {
    const q = `key=${encodeURIComponent(key)}&stage=${stage}` + (version ? `&v=${version}` : '');
    return api(`/api/v2/review?${q}`);
  }

  function makeButton(b) {
    const make = h('button', { class: 'main', id: 'makeBtn', disabled: !b.enabled, onclick: async () => {
      make.disabled = true;
      try { await api('/api/v2/make', { key, stage }); setBusy(); } catch (e) { say(e.message); make.disabled = false; }
    } }, b.label);
    return make;
  }

  async function draw(data) {
    if (!data.has_video) {
      root.replaceChildren(h('div', { class: 'card empty', id: 'stepBody' },
        h('p', {}, stage === 'preview' ? 'No preview yet.' : 'No rough cut yet.'),
        h('p', { class: 'muted' }, stage === 'cut' ? (data.button.enabled ? 'Claude can cut your clips together from the plan.' : data.button.detail) : 'It shows up here as soon as Claude has made one.'),
        stage === 'cut' ? makeButton(data.button) : null,
        data.button.estimate && data.button.enabled ? h('p', { class: 'muted small' }, data.button.estimate) : null));
      return;
    }
    const v = data.version;
    const video = h('video', { id: 'player', src: v.video, controls: true, preload: 'metadata' });
    const strip = h('div', { class: 'strip', id: 'strip' });
    const panel = h('div', { class: 'clipPanel', id: 'clipPanel', hidden: true });
    const noteBox = h('input', { id: 'noteText', type: 'text', placeholder: 'Type a note, press Enter', autocomplete: 'off' });
    const rangeHint = h('div', { class: 'muted small', id: 'rangeHint' });
    const wholeBox = h('input', { type: 'checkbox', id: 'wholeNote' });

    const pad = () => (state.range ? `${fmt(state.range[0])}–${fmt(state.range[1])}` : fmt(state.pin ?? (video.currentTime || 0)));
    const addNote = async () => {
      const text = noteBox.value.trim();
      if (text.length < 2) return;
      const t = state.range ? state.range[0] : state.pin ?? (video.currentTime || 0);
      const t_end = state.range ? state.range[1] : null;
      noteBox.value = '';
      state.range = state.pin = null;
      const whole = wholeBox.checked;
      wholeBox.checked = false;
      await draw(await post('/api/v2/notes', { op: 'add', text, t, t_end, whole }));
    };
    noteBox.addEventListener('keydown', e => { e.stopPropagation(); if (e.key === 'Enter') addNote(); });
    noteBox.addEventListener('focus', () => { rangeHint.textContent = `Note at ${pad()}`; });

    const choose = async (clip, kind, extra = {}) => {
      selected = clip.ref;
      await draw(await post('/api/v2/clipchoice', { clip: clip.ref, kind, t: clip.start, ...extra }));
    };

    async function openPanel(clip) {
      selected = clip.ref;
      for (const el of strip.children) el.classList.toggle('selected', el.dataset.ref === clip.ref);
      panel.hidden = false;
      const body = h('div', { class: 'cpBody' });
      panel.replaceChildren(h('div', { class: 'cpHead' }, h('b', {}, `Clip at ${clip.at}`),
        clip.pending ? h('span', { class: 'chip' }, PENDING[clip.pending]) : null,
        clip.web ? h('span', { class: 'chip' }, 'Web page') : null,
        h('span', { class: 'spacer' }),
        h('button', { class: 'quiet', onclick: () => choose(clip, 'keep') }, 'Keep'),
        h('button', { class: 'quiet', id: 'actReplace', onclick: () => replaceUI(clip, body) }, 'Replace'),
        h('button', { class: 'quiet', id: 'actTrim', onclick: () => trimUI(clip, body) }, 'Trim'),
        h('button', { class: 'quiet', id: 'actWeb', onclick: () => webUI(clip, body) }, 'Web page'),
        h('button', { class: 'quiet', id: 'actRemove', onclick: () => choose(clip, 'remove') }, 'Remove this clip'),
        h('button', { class: 'quiet', id: 'actNote', onclick: () => { state.pin = clip.start; noteBox.focus(); rangeHint.textContent = `Note at ${fmt(clip.start)}`; } }, 'Note')),
        body);
    }

    // B-roll from a web page: the host pastes the address (and, if they like, the words to highlight); the page is captured as a short clip over this one.
    function webUI(clip, body) {
      const url = h('input', { type: 'url', id: 'webUrl', placeholder: 'https://…', autocomplete: 'off', class: 'fbInput' });
      const find = h('input', { type: 'text', id: 'webFind', placeholder: 'Words on the page to highlight (optional)', autocomplete: 'off', class: 'fbInput' });
      const style = h('select', { id: 'webStyle' }, h('option', { value: 'scroll' }, 'Scroll down to the words'), h('option', { value: 'still' }, 'A still picture with a slow zoom'));
      const secs = h('input', { type: 'number', id: 'webSecs', min: 2, max: 12, step: 0.5, value: 5, style: 'width:70px' });
      const inClip = video.currentTime >= clip.start && video.currentTime < clip.start + clip.dur;
      const at = inClip ? Math.max(0, video.currentTime - clip.start) : 0.5;
      for (const el of [url, find, secs]) el.addEventListener('keydown', e => e.stopPropagation());
      const go = h('button', { class: 'main', id: 'webGo', onclick: async () => {
        go.disabled = true;
        try { await api('/api/v2/webbroll', { key, clip: clip.ref, url: url.value.trim(), find: find.value.trim(), style: style.value, seconds: Number(secs.value) || 5, at }); reopen = null; setBusy(); }
        catch (e) { say(e.message); go.disabled = false; }
      } }, 'Capture the page');
      const now = clip.web ? h('div', { class: 'webNow', id: 'webNow' },
        h('img', { src: clip.web.still, alt: '', style: 'max-width:240px;border:1px solid var(--line);border-radius:6px' }),
        h('div', {}, h('div', {}, `${clip.web.title || clip.web.host} goes over this clip in the next cut.`),
          clip.web.found ? null : h('div', { class: 'muted small' }, 'The words to highlight were not found on the page.'),
          h('button', { class: 'quiet', id: 'webRemove', onclick: () => choose(clip, 'noweb') }, 'Do not use it'))) : null;
      body.replaceChildren(...[now,
        h('p', { class: 'muted small' }, `The page shows over this clip from ${fmt(clip.start + at)}${inClip ? ' (the playhead)' : ''}. Only public pages: nothing is signed in to and cookie banners are hidden. The address is added to the credits.`),
        url, find, h('div', { class: 'row' }, style, h('label', { class: 'muted small' }, secs, ' seconds'), go)].filter(Boolean));
      url.focus();
    }

    async function replaceUI(clip, body) {
      body.replaceChildren(h('p', { class: 'muted small' }, 'Looking for other takes…'));
      const { options, can_search, picture, vision } = await api(`/api/v2/options?key=${encodeURIComponent(key)}&clip=${encodeURIComponent(clip.ref)}`);
      const look = picture && !vision.ready ? h('div', { class: 'searchMore', id: 'visionNote' },
        h('span', { class: 'muted' }, vision.total ? `${vision.missing} of ${vision.total} recordings have not been looked at yet, so some shots may be missing.` : 'The footage has not been looked at yet.'),
        h('button', { class: 'quiet', id: 'lookBtn', onclick: async () => { try { await api('/api/v2/vision', { key }); reopen = clip.ref; setBusy(); } catch (e) { say(e.message); } } }, 'Look at my footage')) : null;
      const search = can_search && !picture ? h('div', { class: 'searchMore' },
        h('button', { class: 'quiet', id: 'findOptions', onclick: async () => { try { await api('/api/v2/options/find', { key, clip: clip.ref }); reopen = clip.ref; setBusy(); } catch (e) { say(e.message); } } }, 'Search all my footage for more takes'),
        h('span', { class: 'muted small' }, 'This takes a little longer.')) : null;
      if (!options.length) { body.replaceChildren(...[h('p', { class: 'muted' }, picture ? 'Nothing in your footage looks like this yet.' : 'There is no other take of this part yet.'), look, search].filter(Boolean)); return; }
      body.replaceChildren(...[h('div', { class: 'options' }, ...options.map(o => {
        const vid = h('video', { src: o.video + `#t=${o.start}`, controls: true, preload: 'none', hidden: true });
        return h('div', { class: 'option' },
          h('img', { src: o.frame, alt: '' }),
          h('div', { class: 'small' }, o.why),
          o.said ? h('div', { class: 'small muted' }, `“${o.said}”`) : null,
          h('div', { class: 'optActs' },
            h('button', { class: 'quiet', onclick: () => { vid.hidden = false; vid.currentTime = o.start; vid.play(); } }, 'Play'),
            h('button', { class: 'main small', onclick: () => choose(clip, 'replace', { span: o.span }) }, 'Use this one')), vid);
      })), look, search].filter(Boolean));
    }

    function trimUI(clip, body) {
      const max = Math.max(1, Math.floor(clip.dur) - 1);
      const a = h('input', { type: 'range', min: 0, max, value: 0, id: 'trimStart' });
      const z = h('input', { type: 'range', min: 0, max, value: 0, id: 'trimEnd' });
      const txt = h('div', { class: 'small muted' });
      const upd = () => { txt.textContent = `Cut ${a.value} s from the start and ${z.value} s from the end`; };
      a.addEventListener('input', upd); z.addEventListener('input', upd); upd();
      body.replaceChildren(h('label', {}, 'Start ', a), h('label', {}, 'End ', z), txt,
        h('button', { class: 'main small', id: 'trimGo', onclick: () => choose(clip, 'trim', { cut_start: +a.value, cut_end: +z.value }) }, 'Trim this clip'));
    }

    for (const c of data.clips) {
      const cell = h('div', { class: 'clip' + (c.pending ? ' pending' : '') + (c.ref === selected ? ' selected' : ''), style: `flex: ${Math.max(c.share, 0.04)} 1 0`,
        'data-start': c.start, 'data-dur': c.dur, 'data-ref': c.ref || '', title: c.at },
        h('img', { src: c.frame, alt: '', draggable: 'false' }), c.pending ? h('span', { class: 'badge' }, PENDING[c.pending]) : null);
      cell.addEventListener('click', e => { if (e.shiftKey) return; video.currentTime = c.start; if (stage === 'cut' && c.ref) openPanel(c); });
      strip.append(cell);
    }
    const total = data.clips.reduce((m, c) => Math.max(m, c.start + c.dur), 0);
    const at = e => { const r = strip.getBoundingClientRect(); return Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * total; };
    strip.addEventListener('mousedown', e => {
      if (!e.shiftKey) return;
      const a = at(e);
      e.preventDefault();
      addEventListener('mouseup', up => {
        const b = at(up);
        if (Math.abs(b - a) > 0.5) { state.range = [Math.min(a, b), Math.max(a, b)]; noteBox.focus(); rangeHint.textContent = `Note for ${pad()}`; }
      }, { once: true });
    });

    video.addEventListener('timeupdate', () => {
      const t = video.currentTime;
      for (const el of strip.children) el.classList.toggle('playing', t >= +el.dataset.start && t < +el.dataset.start + +el.dataset.dur);
    });

    const verMenu = h('select', { id: 'versionMenu', onchange: async e => { version = +e.target.value; await draw(await load()); } },
      ...data.versions.map(x => h('option', { value: x.n, selected: x.current }, x.label + (x.latest ? ' (latest)' : ''))));

    const notesList = h('ul', { class: 'notes', id: 'notes' }, ...data.notes.map(n => h('li', { class: n.done ? 'done' : '' },
      h('a', { class: 'when', href: '#', onclick: e => { e.preventDefault(); if (!n.whole) video.currentTime = n.t; } }, n.when),
      n.clip_change ? h('span', { class: 'ntext' }, n.text) : h('span', { class: 'ntext', contenteditable: 'true', spellcheck: 'false', onblur: async e => {
        const text = e.target.textContent.trim();
        if (text && text !== n.text) await post('/api/v2/notes', { op: 'edit', id: n.id, text });
      }, onkeydown: e => { e.stopPropagation(); if (e.key === 'Enter') { e.preventDefault(); e.target.blur(); } } }, n.text),
      n.done_in ? h('span', { class: 'muted small' }, `done in ${n.done_in}`) : null,
      h('button', { class: 'quiet', title: 'Delete this note', onclick: async () => draw(await post('/api/v2/notes', { op: 'delete', id: n.id })) }, '✕'))));

    const copy = h('button', { class: 'quiet', onclick: async () => {
      const text = data.notes.filter(n => !n.done).map(n => `${n.when} ${n.text}`).join('\n');
      try { await navigator.clipboard.writeText(text); copy.textContent = 'Copied'; } catch { copy.textContent = 'Could not copy'; }
    } }, 'Copy my notes');

    const teach = stage === 'cut' ? h('div', { class: 'card teach', id: 'teaching' },
      h('div', { class: 'rhead' }, h('b', {}, 'Teaching moments'),
        h('button', { class: 'quiet', id: 'findTeach', onclick: async () => { try { await api('/api/v2/teaching/find', { key }); setBusy(); } catch (e) { say(e.message); } } }, 'Ask Claude for more')),
      data.teaching.length ? h('ul', { class: 'moments' }, ...data.teaching.map(m => h('li', { class: m.status },
        h('span', { class: 'when' }, m.when), h('span', { class: 'ntext' }, h('b', {}, m.term), ' ', h('span', { class: 'muted' }, m.why)),
        h('button', { class: 'tick' + (m.status === 'yes' ? ' on' : ''), title: 'Explain this in the video', onclick: async () => draw(await post('/api/v2/teaching', { id: m.id, status: m.status === 'yes' ? 'suggested' : 'yes' })) }, '✓'),
        h('button', { class: 'tick' + (m.status === 'no' ? ' on' : ''), title: 'No explanation needed', onclick: async () => draw(await post('/api/v2/teaching', { id: m.id, status: m.status === 'no' ? 'suggested' : 'no' })) }, '✕'))))
        : h('p', { class: 'muted small' }, 'None yet.')) : null;
    const fun = stage === 'cut' ? h('div', { class: 'card teach', id: 'moments' },
      h('div', { class: 'rhead' }, h('b', {}, 'Fun moments'),
        h('button', { class: 'quiet', id: 'findFun', onclick: async () => { try { await api('/api/v2/moments/find', { key }); setBusy(); } catch (e) { say(e.message); } } }, 'Ask Claude for some')),
      data.moments.length ? h('ul', { class: 'moments' }, ...data.moments.map(m => h('li', { class: m.status },
        h('span', { class: 'when' }, m.when), h('span', { class: 'ntext' }, h('b', {}, m.text), ' ', h('span', { class: 'muted' }, `${m.kind} · ${m.why}`)),
        h('button', { class: 'tick' + (m.status === 'yes' ? ' on' : ''), title: 'Show this pop-up', onclick: async () => draw(await post('/api/v2/moments', { id: m.id, status: m.status === 'yes' ? 'suggested' : 'yes' })) }, '✓'),
        h('button', { class: 'tick' + (m.status === 'no' ? ' on' : ''), title: 'No pop-up here', onclick: async () => draw(await post('/api/v2/moments', { id: m.id, status: m.status === 'no' ? 'suggested' : 'no' })) }, '✕'))))
        : h('p', { class: 'muted small' }, 'None yet. A fun moment is a short sticker or number on a good line.')) : null;

    const marks = stage === 'cut' && v.latest && total ? marksCard(key, video, total) : null;
    const b = data.button;
    root.replaceChildren(h('div', { class: 'review' },
      h('div', { class: 'left' }, video, strip, marks && marks.overlay, panel,
        h('div', { class: 'muted small' }, stage === 'cut'
          ? 'Click a clip to keep, replace, trim or remove it. Space plays, arrows jump 5 seconds, N adds a note.'
          : 'Space plays, arrows jump 5 seconds, N adds a note. Shift and drag over the clips to note a range.'), marks && marks.card, teach, fun, stage === 'preview' ? musicCard(key) : null, stage === 'preview' ? factCheckCard(key) : null),
      h('aside', { class: 'right card' },
        h('div', { class: 'rhead' }, h('b', {}, 'Notes'), verMenu),
        v.changes.length ? h('details', { class: 'changes' }, h('summary', {}, `What changed in ${v.label}`), ...(v.suggestions.length ? [h('div', { class: 'suggest', id: 'suggestions' }, h('b', {}, 'Claude suggests'),
          ...v.suggestions.map(s => h('div', { class: 'row' }, h('span', { class: 'small' }, s.text),
            h('button', { class: 'quiet', disabled: data.notes.some(n => n.text === s.text.replace(/\s+/g, ' ')), onclick: async () => draw(await post('/api/v2/notes', { op: 'add', text: s.text, t: s.t })) }, 'Add as a note'))))] : []), h('ul', {}, ...v.changes.map(c => h('li', { class: c.startsWith('Not done') ? 'warn' : '' }, c))),
          v.lesson ? h('div', { class: 'suggest', id: 'lesson' }, h('b', {}, 'Claude learned something'),
            h('div', { class: 'row' }, h('span', { class: 'small' }, v.lesson),
              h('button', { class: 'quiet', onclick: async () => { await post('/api/v2/lesson', { key, stage, n: v.n }); draw(await load()); } }, 'Add to my editing rules'))) : null) : null,
        stage === 'preview' && data.graphics.length ? h('details', { class: 'card gfxlist', id: 'graphicsList' }, h('summary', {}, `Graphics in this preview (${data.graphics.filter(g => !g.skipped).length})`),
          h('ul', { class: 'moments' }, ...data.graphics.map(g => h('li', { class: g.skipped ? 'no' : '' },
            h('span', { class: 'when' }, g.when), h('span', { class: 'ntext' }, h('b', {}, g.what), ' ', h('span', { class: 'muted' }, [g.kind, g.words && `over “${g.words.slice(0, 60)}”`].filter(Boolean).join(' · '))),
            h('button', { class: 'tick' + (g.skipped ? ' on' : ''), 'aria-label': g.skipped ? 'Build this graphic again' : 'Skip this graphic', title: g.skipped ? 'Skipped: click to build it' : 'Skip this graphic',
              onclick: async () => draw(await post('/api/v2/graphics/skip', { beat: g.beat, skip: !g.skipped })) }, '✕'))))) : null,
        notesList, noteBox, h('label', { class: 'muted small wholeLabel' }, wholeBox, ' This note is about the whole video (too long, be pickier, more energy)'), rangeHint,
        h('div', { class: 'makebox' }, makeButton(b), h('div', { class: 'muted small' }, [b.detail, b.estimate].filter(Boolean).join(' · ')), copy))));
    if (reopen) { selected = reopen; reopen = null; const c = data.clips.find(x => x.ref === selected); if (c) { await openPanel(c); document.getElementById('actReplace').click(); } }
    else if (selected) { const c = data.clips.find(x => x.ref === selected); if (c) openPanel(c); }
    keyHandler = (e) => {
      if (e.target.matches('input, textarea, [contenteditable]')) return;
      if (e.key === ' ') { e.preventDefault(); video.paused ? video.play() : video.pause(); }
      else if (e.key === 'ArrowRight') video.currentTime += 5;
      else if (e.key === 'ArrowLeft') video.currentTime -= 5;
      else if (e.key.toLowerCase() === 'n') { e.preventDefault(); video.pause(); noteBox.focus(); }
    };
  }
  await draw(await load());
}
