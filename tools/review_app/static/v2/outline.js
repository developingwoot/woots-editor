import { h, api } from './util.js';

// The Outline step: the header fields, then one card per section with its shot ideas, talking points (the full wording folded underneath),
// voice-over notes and graphic chips. Everything is edited in place; each change is saved as a version by the server.
export async function render(root, key, setBusy) {
  const post = (path, body) => api(path, { key, ...body });
  const edit = async body => draw(await post('/api/v2/outline/edit', body));

  // A piece of text that is edited where it is: Enter or clicking away saves it, Escape puts it back.
  function editable(text, save, cls = '') {
    const el = h('span', { class: 'ed ' + cls, contenteditable: 'plaintext-only', spellcheck: 'false' }, text);
    el.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); el.blur(); }
      else if (e.key === 'Escape') { el.textContent = text; el.blur(); }
    });
    el.addEventListener('blur', () => { const t = el.textContent.trim(); if (t && t !== text) save(t); else el.textContent = text; });
    return el;
  }

  function adder(placeholder, onAdd) {
    const box = h('input', { type: 'text', class: 'adder', placeholder, autocomplete: 'off' });
    box.addEventListener('keydown', e => { if (e.key === 'Enter' && box.value.trim()) { const t = box.value.trim(); box.value = ''; onAdd(t); } });
    return box;
  }

  const remove = row => h('button', { class: 'quiet x', title: 'Remove this', onclick: () => edit({ op: 'delete_item', line: row.line, raw: row.raw }) }, '✕');
  const setItem = row => t => edit({ op: 'set_item', line: row.line, raw: row.raw, text: t });

  function entryBlock(sec, entry) {
    const parts = [];
    if (entry.title) parts.push(h('h4', {}, editable(entry.title, t => edit({ op: 'set_item', line: entry.line, raw: entry.raw, text: t }))));
    if (entry.chips.length) parts.push(h('div', { class: 'chips' }, ...entry.chips.map(c => h('span', { class: 'chip2 ' + c.kind }, editable(c.text, setItem(c), 'chipText'), remove(c)))));
    if (entry.shots.length) parts.push(h('div', { class: 'group' }, h('div', { class: 'glabel' }, 'Shots'),
      ...entry.shots.map(s => h('div', { class: 'shot' }, h('span', { class: 'dotmark' }, '▸'), editable(s.text, setItem(s)), remove(s)))));
    if (entry.talking.length) parts.push(h('div', { class: 'group' }, h('div', { class: 'glabel' }, 'Talking points'),
      ...entry.talking.map(t => h('div', { class: 'talk' },
        h('div', { class: 'talkHead' }, h('b', {}, t.summary), remove(t)),
        h('details', {}, h('summary', {}, 'Suggested wording'), h('div', { class: 'wording' }, editable(t.text, setItem(t))))))));
    if (entry.vo.length) parts.push(h('div', { class: 'group' }, h('div', { class: 'glabel' }, 'Voice-over'),
      ...entry.vo.map(v => h('div', { class: 'vo' }, v.teaching ? h('span', { class: 'chip' }, 'Teaching point') : null, editable(v.text, setItem(v)), remove(v)))));
    return h('div', { class: 'entry' }, ...parts);
  }

  function card(sec) {
    return h('div', { class: 'card osec', 'data-section': sec.key },
      h('div', { class: 'osecHead' },
        sec.icon ? h('span', { class: 'icon' }, sec.icon) : null,
        h('h3', {}, editable(sec.title, t => edit({ op: 'set_section', line: sec.line, text: t }))),
        sec.time ? h('span', { class: 'muted small' }, sec.time) : null,
        sec.needs_shots ? h('span', { class: 'chip warn' }, 'Needs shot ideas') : null),
      ...sec.entries.map(e => entryBlock(sec, e)),
      adder('+ Add a shot idea', t => edit({ op: 'add_visual', section: sec.key, text: t })));
  }

  async function draw(d) {
    const note = h('input', { id: 'outlineNote', type: 'text', placeholder: d.note.placeholder, autocomplete: 'off' });
    const go = h('button', { class: 'main', id: 'outlineBtn', disabled: !d.button.enabled, onclick: async () => {
      go.disabled = true;
      try { await post('/api/v2/outline/write', { note: note.value }); setBusy(); } catch (e) { alert(e.message); go.disabled = false; }
    } }, d.button.label);
    const ask = h('div', { class: 'card askBar' }, note, go, h('span', { class: 'muted small' }, d.button.estimate));

    if (!d.has_outline) {
      root.replaceChildren(h('div', { class: 'card empty', id: 'stepBody' }, h('p', {}, 'No outline yet.'),
        h('p', { class: 'muted' }, 'Tell Claude what the video is about and it drafts the sections, shots and talking points.')), ask);
      return;
    }
    const header = h('div', { class: 'card ohead', id: 'outlineHeader' }, ...d.header.map(f => h('div', { class: 'hfield', 'data-field': f.field },
      h('div', { class: 'glabel' }, f.label),
      editable(f.text || '', t => edit({ op: 'set_header', field: f.field, text: t }), f.text ? '' : 'blank'))));
    const blanks = d.header.filter(f => !f.text).map(f => f.label.toLowerCase());
    if (blanks.length) header.append(h('div', { class: 'row' },
      h('button', { class: 'quiet', id: 'fillBlanks', disabled: !d.button.enabled, onclick: async () => {
        try { await post('/api/v2/outline/write', { note: `Please write the ${blanks.join(', ')} for this video and change nothing else.` }); setBusy(); } catch (e) { go.textContent = e.message; }
      } }, 'Ask Claude to fill these'), h('span', { class: 'muted small' }, `Empty: ${blanks.join(', ')}.`)));
    // A save redraws the page: what is half typed in a box (and which box has the cursor) must survive it.
    const typed = [...root.querySelectorAll('input')].map(i => [i.closest('[data-section]')?.dataset.section || i.id, i.value, i === document.activeElement]).filter(([k, v, f]) => v || f);
    root.replaceChildren(...[ask, d.summary ? h('div', { class: 'muted', id: 'outlineGaps' }, d.summary) : null, header, ...d.sections.map(card)].filter(Boolean));
    for (const [k, v, focused] of typed) {
      const box = root.querySelector(`[data-section="${CSS.escape(k)}"] input`) || root.querySelector(`#${CSS.escape(k)}`);
      if (!box) continue;
      box.value = v;
      if (focused) box.focus();
    }
  }
  await draw(await api(`/api/v2/outline?key=${encodeURIComponent(key)}`));
}
