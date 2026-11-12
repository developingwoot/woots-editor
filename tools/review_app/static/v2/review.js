import { h, api, say } from './util.js';
import { marksCard } from './marks.js';
import { factCheckCard, musicCard } from './extras.js';

// The review screen, shared by the rough cut and the preview: player, clips as a strip, notes pinned to the time, versions, one main button.
// In the rough cut a click on a clip also opens Keep / Replace / Trim / Remove / Note for that clip, and teaching moments sit below the strip.
const fmt = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
const PENDING = { replace: 'Another take', remove: 'Out', trim: 'Trimmed' };
const IDEA_KIND = { footage: 'Your footage', web: 'Web page', film: 'Film it', correction: 'Correction', detail: 'Detail' };

let keyHandler = null;
let keyHandlerBox = null;                              // while a blur box is being drawn: Esc stops
const FPS = 30;                                        // the rough cut and the preview are rendered at 30 frames a second (sections.baseline_edit)
let reopen = null;                                     // a clip whose Replace panel to open again after a background search
document.addEventListener('keydown', e => { if (keyHandler) keyHandler(e); });
export function leave() { keyHandler = null; keyHandlerBox = null; }

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
    // A redraw after an answer (a tick, a choice, a note) keeps the same player: same video, same moment, still playing, and the page where it was.
    const prev = root.querySelector('#player');
    const same = prev && prev.getAttribute('src') === v.video;
    const playing = same && !prev.paused;
    const scroller = document.scrollingElement;
    const scrollY = scroller ? scroller.scrollTop : 0;
    const video = same ? prev : h('video', { id: 'player', src: v.video, controls: true, preload: 'metadata' });
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
      const tr = data.transitions || { presets: [], defaults: {} };
      const dflt = tr.presets.find(p => p.id === tr.defaults.web);
      const trans = h('select', { id: 'webTrans', title: 'How the page comes in and goes out' },
        h('option', { value: '' }, `Comes in: ${dflt ? dflt.label : 'the default'} (Settings)`),
        ...tr.presets.filter(p => p.id !== tr.defaults.web).map(p => h('option', { value: p.id }, `Comes in: ${p.label}${p.kind === 'stinger' && !p.ready ? ' (make it in Settings first)' : ''}`)));
      const inClip = video.currentTime >= clip.start && video.currentTime < clip.start + clip.dur;
      const at = inClip ? Math.max(0, video.currentTime - clip.start) : 0.5;
      for (const el of [url, find, secs]) el.addEventListener('keydown', e => e.stopPropagation());
      const go = h('button', { class: 'main', id: 'webGo', onclick: async () => {
        go.disabled = true;
        try { await api('/api/v2/webbroll', { key, clip: clip.ref, url: url.value.trim(), find: find.value.trim(), style: style.value, seconds: Number(secs.value) || 5, at, transition: trans.value }); reopen = null; setBusy(); }
        catch (e) { say(e.message); go.disabled = false; }
      } }, 'Capture the page');
      const now = clip.web ? h('div', { class: 'webNow', id: 'webNow' },
        h('img', { src: clip.web.still, alt: '', style: 'max-width:240px;border:1px solid var(--line);border-radius:6px' }),
        h('div', {}, h('div', {}, `${clip.web.title || clip.web.host} goes over this clip in the next cut.`),
          clip.web.found ? null : h('div', { class: 'muted small' }, 'The words to highlight were not found on the page.'),
          h('button', { class: 'quiet', id: 'webRemove', onclick: () => choose(clip, 'noweb') }, 'Do not use it'))) : null;
      body.replaceChildren(...[now,
        h('p', { class: 'muted small' }, `The page shows over this clip from ${fmt(clip.start + at)}${inClip ? ' (the playhead)' : ''}. Only public pages: nothing is signed in to and cookie banners are hidden. The address is added to the credits.`),
        url, find, h('div', { class: 'row' }, style, h('label', { class: 'muted small' }, secs, ' seconds'), trans, go)].filter(Boolean));
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

    // B-roll and on-screen text ideas (ideas.py): Claude suggests, a tick says yes (applied when the next cut is made), a cross says no.
    // A text idea's words can be changed before the tick; the form at the bottom adds the host's own text at the playhead (a slip of the tongue fixed on screen).
    function ideasCard(list, video) {
      const yesTitle = { footage: 'Use this shot in the next cut', web: 'Capture the page and use it in the next cut', film: 'Add it to the pickups on the shoot plan',
        correction: 'Show this text in the next cut', detail: 'Show this text in the next cut' };
      const answer = async (i, status, text) => {
        try {
          const r = await post('/api/v2/ideas', { id: i.id, status, ...(text !== undefined ? { text } : {}) });
          if (i.kind === 'web' && status === 'yes') setBusy();
          await draw(r);
        } catch (e) { say(e.message); }
      };
      const row = i => {
        const isText = i.kind === 'correction' || i.kind === 'detail';
        const edit = isText ? h('input', { type: 'text', class: 'ideaText', value: i.text, maxlength: 90, 'aria-label': 'The words on screen', onkeydown: e => e.stopPropagation() }) : null;
        const what = isText ? edit : h('b', {}, i.kind === 'web' ? i.host : i.text);
        return h('li', { class: `idea ${i.status}`, 'data-id': i.id, 'data-kind': i.kind },
          h('a', { class: 'when', href: '#', onclick: e => { e.preventDefault(); video.currentTime = i.t; } }, i.when),
          i.frame ? h('img', { class: 'ideaFrame', src: i.frame, alt: '', loading: 'lazy' }) : null,
          h('span', { class: 'ntext' }, h('span', { class: 'chip' }, IDEA_KIND[i.kind]), ' ', what,
            i.kind === 'web' && i.find ? h('span', { class: 'muted small' }, ` at “${i.find}”`) : null,
            i.why ? h('div', { class: 'muted small' }, i.why) : null),
          h('button', { class: 'tick' + (i.status === 'yes' ? ' on' : ''), title: yesTitle[i.kind], onclick: () => answer(i, i.status === 'yes' ? 'suggested' : 'yes', edit && i.status !== 'yes' ? edit.value : undefined) }, '✓'),
          h('button', { class: 'tick' + (i.status === 'no' ? ' on' : ''), title: 'Not this one', onclick: () => answer(i, i.status === 'no' ? 'suggested' : 'no') }, '✕'));
      };
      const own = h('input', { type: 'text', id: 'ownText', placeholder: '*the right words, e.g. *0.4 mm nozzle', maxlength: 90, autocomplete: 'off', class: 'fbInput' });
      const kind = h('select', { id: 'ownKind' }, h('option', { value: 'correction' }, 'Correction'), h('option', { value: 'detail' }, 'Detail'));
      const add = h('button', { class: 'quiet', id: 'ownAdd', onclick: async () => {
        const text = own.value.trim();
        if (!text) { own.focus(); return; }
        try { await draw(await post('/api/v2/ideas/add', { t: video.currentTime || 0, text, kind: kind.value })); } catch (e) { say(e.message); }
      } }, 'Add at the playhead');
      own.addEventListener('keydown', e => { e.stopPropagation(); if (e.key === 'Enter') add.click(); });
      return h('div', { class: 'card teach', id: 'ideas' },
        h('div', { class: 'rhead' }, h('b', {}, 'B-roll and on-screen text'),
          h('button', { class: 'quiet', id: 'findIdeas', onclick: async () => { try { await api('/api/v2/ideas/find', { key }); setBusy(); } catch (e) { say(e.message); } } },
            list.some(i => !i.own) ? 'Ask Claude again' : 'Ask Claude for ideas')),
        list.length ? h('ul', { class: 'moments ideas' }, ...list.map(row))
          : h('p', { class: 'muted small' }, 'None yet. Claude suggests shots from your footage, web pages, shots to film next time, and on-screen corrections where you misspoke.'),
        h('div', { class: 'row ownText' }, own, kind, add),
        h('div', { class: 'muted small' }, 'Misspoke? Pause where it happens and type the right words: they show on screen for a few seconds in the next cut.'));
    }

    // Blur (blur.py): pause on the first frame where a name or a screen shows, draw a box over it; the app follows it through the clip.
    // The boxes show over the player while it plays, so a box that drifts is seen; pause there and draw it again to fix the rest of the path.
    const layer = h('div', { class: 'blurLayer', id: 'blurLayer' });
    const blurs = data.blurs || [];
    const contentRect = () => {                          // where the picture is inside the player (it is letterboxed to keep its shape)
      const W = video.clientWidth, H = video.clientHeight, vw = video.videoWidth || 16, vh = video.videoHeight || 9;
      const s = Math.min(W / vw, H / vh);
      return { x: (W - vw * s) / 2, y: (H - vh * s) / 2, w: vw * s, h: vh * s };
    };
    const boxAt = (tr, t) => {
      if (!tr.length || t < tr[0][0] - 0.05 || t > tr[tr.length - 1][0] + 0.05) return null;
      for (let i = 1; i < tr.length; i++) if (t <= tr[i][0]) {
        const a = tr[i - 1], b = tr[i], f = (t - a[0]) / ((b[0] - a[0]) || 1e-9);
        return [1, 2, 3, 4].map(j => a[j] + (b[j] - a[j]) * f);
      }
      return tr[tr.length - 1].slice(1);
    };
    const showBoxes = () => {
      if (layer.classList.contains('drawing')) return;
      const r = contentRect(), t = video.currentTime;
      layer.replaceChildren(...blurs.filter(b => b.placed && t >= b.start - 0.02 && t <= b.end + 0.02).map(b => {
        const x = boxAt(b.track, t);
        return x ? h('div', { class: 'blurBox ' + b.style, 'data-id': b.id, style: `left:${r.x + x[0] * r.w}px;top:${r.y + x[1] * r.h}px;width:${x[2] * r.w}px;height:${x[3] * r.h}px` }) : null;
      }).filter(Boolean));
    };
    video._showBoxes = showBoxes;                        // the player outlives this redraw: its frame loop always draws on the newest layer
    video.onplay = () => {                               // one frame loop per play: an older one stops at its next frame
      if (!video.requestVideoFrameCallback) return;
      const gen = video._gen = (video._gen || 0) + 1;
      const tick = () => { if (gen !== video._gen || video.paused) return; video._showBoxes(); video.requestVideoFrameCallback(tick); };
      video.requestVideoFrameCallback(tick);
    };
    video.onseeked = showBoxes;
    video.onloadedmetadata = showBoxes;
    const blurSay = h('div', { class: 'muted small', id: 'blurSay' });
    const drawBox = (label, send) => {                    // the player pauses and the next drag on it is the box
      video.pause();
      layer.classList.add('drawing');
      layer.replaceChildren();
      blurSay.textContent = `${label}: drag a box over it on the picture. Esc stops.`;
      let a = null, el = null;
      const pos = e => { const r = layer.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
      const stop = () => { layer.classList.remove('drawing'); layer.onmousedown = layer.onmousemove = layer.onmouseup = null; keyHandlerBox = null; showBoxes(); };
      keyHandlerBox = e => { if (e.key === 'Escape') { stop(); blurSay.textContent = ''; return true; } return false; };
      layer.onmousedown = e => { e.preventDefault(); a = pos(e); el = h('div', { class: 'blurBox new' }); layer.replaceChildren(el); };
      layer.onmousemove = e => {
        if (!a) return;
        const b = pos(e);
        Object.assign(el.style, { left: `${Math.min(a[0], b[0])}px`, top: `${Math.min(a[1], b[1])}px`, width: `${Math.abs(b[0] - a[0])}px`, height: `${Math.abs(b[1] - a[1])}px` });
      };
      layer.onmouseup = async e => {
        if (!a) return;
        const b = pos(e), r = contentRect();
        const box = [(Math.min(a[0], b[0]) - r.x) / r.w, (Math.min(a[1], b[1]) - r.y) / r.h, Math.abs(b[0] - a[0]) / r.w, Math.abs(b[1] - a[1]) / r.h];
        a = null;
        if (box[2] < 0.01 || box[3] < 0.01) { el.remove(); return; }
        stop();
        blurSay.textContent = 'Following the box through the clip…';
        try { await draw(await send(box)); } catch (err) { blurSay.textContent = ''; say(err.message); }
      };
    };
    const blurPost = body => post('/api/v2/blur', body);
    function blurCard() {
      const what = h('input', { type: 'text', id: 'blurWhat', placeholder: 'What it hides (optional), e.g. my username', maxlength: 80, autocomplete: 'off', class: 'fbInput', onkeydown: e => e.stopPropagation() });
      const style = h('select', { id: 'blurStyle' }, h('option', { value: 'blur' }, 'Blur'), h('option', { value: 'block' }, 'Black box'));
      const addBtn = h('button', { class: 'quiet', id: 'blurAdd', onclick: () => drawBox('The blur starts at this frame',
        box => blurPost({ op: 'add', t: video.currentTime, box, style: style.value, what: what.value.trim() })) }, 'Draw a box at the playhead');
      const row = b => h('li', { class: b.placed ? '' : 'todo', 'data-id': b.id },
        h('a', { class: 'when', href: '#', onclick: e => { e.preventDefault(); video.currentTime = b.start + 0.001; } }, `${fmt(b.start)}–${fmt(b.end)}`),
        h('span', { class: 'ntext' }, b.what || (b.style === 'block' ? 'Black box' : 'Blur'), b.placed ? null : h('span', { class: 'muted small' }, ' · not placed yet')),
        h('select', { class: 'blurRowStyle', onchange: async e => { try { await draw(await blurPost({ op: 'style', id: b.id, style: e.target.value })); } catch (err) { say(err.message); } } },
          h('option', { value: 'blur', selected: b.style === 'blur' }, 'Blur'), h('option', { value: 'block', selected: b.style === 'block' }, 'Black box')),
        b.placed
          ? h('button', { class: 'quiet', title: 'The box is off here: draw it again from this frame on', onclick: () => drawBox('Draw the box again from this frame', box => blurPost({ op: 'fix', id: b.id, t: video.currentTime, box })) }, 'Fix from here')
          : h('button', { class: 'quiet', onclick: () => { video.currentTime = b.start + 0.001; drawBox('Place the box', box => blurPost({ op: 'fix', id: b.id, t: video.currentTime, box })); } }, 'Place the box'),
        b.placed ? h('button', { class: 'quiet', title: 'The blur stops at the playhead', onclick: async () => { try { await draw(await blurPost({ op: 'end', id: b.id, t: video.currentTime })); } catch (err) { say(err.message); } } }, 'Ends here') : null,
        h('button', { class: 'quiet', title: 'Delete this blur', onclick: async () => { try { await draw(await blurPost({ op: 'delete', id: b.id })); } catch (err) { say(err.message); } } }, '✕'));
      return h('div', { class: 'card teach', id: 'blurs' },
        h('div', { class: 'rhead' }, h('b', {}, 'Blur')),
        blurs.length ? h('ul', { class: 'moments blurList' }, ...blurs.map(row)) : null,
        h('div', { class: 'row ownText' }, what, style, addBtn), blurSay,
        h('div', { class: 'muted small' }, 'Pause on the first frame where it shows (comma and full stop step one frame), then draw a box over it. The box follows it to the end of the clip; it shows over the player so you can check it.'));
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

    const clock = h('span', { class: 'muted small frameClock', id: 'frameClock' });
    const showClock = () => { const t = video.currentTime || 0; clock.textContent = `${fmt(t)} · frame ${Math.floor((t % 1) * FPS) + 1} of ${FPS}`; };
    video.ontimeupdate = () => {                         // a property, not a listener: the player is reused by the next redraw, with that redraw's strip
      const t = video.currentTime;
      for (const el of strip.children) el.classList.toggle('playing', t >= +el.dataset.start && t < +el.dataset.start + +el.dataset.dur);
      showClock();
      if (video.paused || !video.requestVideoFrameCallback) showBoxes();
    };
    const step = n => {                                  // one frame on or back: lands in the middle of the frame, so the picture shown is that frame
      video.pause();
      const f = Math.max(0, Math.round((video.currentTime || 0) * FPS - 0.5) + n);
      video.currentTime = (f + 0.5) / FPS;
    };
    const frames = h('div', { class: 'row frameStep' },
      h('button', { class: 'quiet', id: 'frameBack', title: 'One frame back (comma)', onclick: () => step(-1) }, '◀ 1 frame'),
      h('button', { class: 'quiet', id: 'frameOn', title: 'One frame on (full stop)', onclick: () => step(1) }, '1 frame ▶'), clock);
    showClock();

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

    const ideas = stage === 'cut' ? ideasCard(data.ideas || [], video) : null;
    const marks = stage === 'cut' && v.latest && total ? marksCard(key, video, total) : null;
    const blurBox = stage === 'cut' && v.latest ? blurCard() : null;
    const b = data.button;
    root.replaceChildren(h('div', { class: 'review' },
      h('div', { class: 'left' }, h('div', { class: 'playerWrap' }, video, stage === 'cut' && v.latest ? layer : null), frames, strip, marks && marks.overlay, panel,
        h('div', { class: 'muted small' }, stage === 'cut'
          ? 'Click a clip to keep, replace, trim or remove it. Space plays, arrows jump 5 seconds, comma and full stop step one frame, N adds a note.'
          : 'Space plays, arrows jump 5 seconds, comma and full stop step one frame, N adds a note. Shift and drag over the clips to note a range.'), marks && marks.card, blurBox, ideas, teach, fun, stage === 'preview' ? musicCard(key) : null, stage === 'preview' ? factCheckCard(key) : null),
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
    if (same) {
      if (scroller) scroller.scrollTop = scrollY;
      if (playing) video.play().catch(() => {});        // moving the player in the page pauses it
    }
    if (reopen) { selected = reopen; reopen = null; const c = data.clips.find(x => x.ref === selected); if (c) { await openPanel(c); document.getElementById('actReplace').click(); } }
    else if (selected) { const c = data.clips.find(x => x.ref === selected); if (c) openPanel(c); }
    showBoxes();
    keyHandler = (e) => {
      if (keyHandlerBox && keyHandlerBox(e)) return;
      if (e.target.matches('input, textarea, select, [contenteditable]')) return;
      if (e.key === ',') { e.preventDefault(); step(-1); }
      else if (e.key === '.') { e.preventDefault(); step(1); }
      else if (e.key === ' ') { e.preventDefault(); video.paused ? video.play() : video.pause(); }
      else if (e.key === 'ArrowRight') video.currentTime += 5;
      else if (e.key === 'ArrowLeft') video.currentTime -= 5;
      else if (e.key.toLowerCase() === 'n') { e.preventDefault(); video.pause(); noteBox.focus(); }
    };
  }
  await draw(await load());
}
