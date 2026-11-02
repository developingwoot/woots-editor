import { h, api } from './util.js';

// The brand pickers in Settings: a font list that shows the channel's name in every installed font, and a palette of up to five colours.
// Both keep the profile's plain-text format (a font name; "primary #142C44, accent #E2703A"), so the files Claude reads do not change.

let fontsLoaded = null;
const loadFonts = () => fontsLoaded ??= api('/api/v2/fonts').then(r => r.fonts).catch(() => []);

const fontCss = f => `font-family: "${f.family}", sans-serif; font-weight: ${f.weight}; font-style: ${f.italic ? 'italic' : 'normal'}`;

export function fontPicker({ value, sample, onChange }) {
  const word = () => (sample() || '').trim() || 'Your channel';
  let fonts = null, open = false, filter = '';
  const shown = h('button', { type: 'button', class: 'fontShown', onclick: () => toggle() });
  const list = h('div', { class: 'fontList', hidden: true });
  const search = h('input', { type: 'search', class: 'setPath', placeholder: 'Find a font…', oninput: e => { filter = e.target.value.toLowerCase(); fill(); } });
  const rows = h('div', { class: 'fontRows' });
  list.append(search, rows);
  const root = h('div', { class: 'fontPicker' }, shown, list);

  const paintShown = () => {
    const f = (fonts || []).find(x => x.name.toLowerCase() === value.toLowerCase());
    shown.replaceChildren(value
      ? h('span', { class: 'fontSample', style: f ? fontCss(f) : '' }, word())
      : h('span', { class: 'muted' }, 'Default (no font chosen)'),
      value ? h('span', { class: 'muted small' }, value + (fonts && !f ? ' (not found on this computer)' : '')) : null);
  };
  const choose = name => { value = name; onChange(name); paintShown(); toggle(false); };
  const fill = () => {
    const found = (fonts || []).filter(f => !filter || f.name.toLowerCase().includes(filter));
    rows.replaceChildren(
      filter ? null : h('button', { type: 'button', class: 'fontRow', onclick: () => choose('') }, h('span', { class: 'muted' }, 'Default (no font chosen)')),
      ...found.map(f => h('button', { type: 'button', class: 'fontRow' + (f.name.toLowerCase() === value.toLowerCase() ? ' on' : ''), 'data-font': f.name, onclick: () => choose(f.name) },
        h('span', { class: 'fontSample', style: fontCss(f) }, word()), h('span', { class: 'muted small' }, f.name))),
      found.length ? null : h('div', { class: 'muted small' }, fonts && fonts.length ? 'No font matches.' : 'Could not list the fonts on this computer; type the font name in the notes file instead.'));
  };
  const toggle = async (to = !open) => {
    open = to;
    list.hidden = !open;
    if (open) { search.value = ''; filter = ''; fill(); search.focus(); }
  };
  document.addEventListener('click', e => { if (open && !root.contains(e.target)) toggle(false); });
  paintShown();
  loadFonts().then(f => { fonts = f; paintShown(); if (open) fill(); });
  return root;
}

const ROLES = ['primary', 'accent'];
const roleName = i => ROLES[i] || `colour ${i + 1}`;
const MAX = 5;
const PRESETS = [
  ['Deep sea', ['#142C44', '#E2703A', '#F4EFE6', '#2E8B57', '#1B2430']],
  ['Sunset', ['#2D1B3D', '#FF6B35', '#FFD166', '#F7F0E8', '#EF476F']],
  ['Forest', ['#1F3D2B', '#E9B44C', '#F5F1E3', '#6B8F71', '#2B2D2F']],
  ['Mono pop', ['#111111', '#00C2A8', '#F5F5F5', '#8A8A8A', '#FF4D6D']],
];

// "navy #142C44, orange #E2703A" -> [{name, hex}]
export function parsePalette(text) {
  return (text || '').split(/[\n,;]+/).map(s => s.trim()).map(s => {
    const m = s.match(/^(.*?)\s*(#[0-9a-f]{6}|#[0-9a-f]{3})\b/i);
    if (!m) return null;
    const hex = m[2].length === 4 ? '#' + [...m[2].slice(1)].map(c => c + c).join('') : m[2];
    return { name: m[1].replace(/[:\-–]+$/, '').trim(), hex: hex.toUpperCase() };
  }).filter(Boolean).slice(0, MAX);
}
export const writePalette = colors => colors.map((c, i) => `${c.name || roleName(i)} ${c.hex}`).join(', ');

export function palettePicker({ value, onChange }) {
  let colors = parsePalette(value);
  const hasOther = !!(value || '').trim() && !colors.length;          // text with no hex codes in it: leave it alone until a colour is picked
  const root = h('div', { class: 'palette' });
  const changed = () => { onChange(writePalette(colors)); draw(); };
  const draw = () => {
    root.replaceChildren(...[
      hasOther && !colors.length ? h('p', { class: 'muted small' }, `Saved as text: ${value}. Pick a colour below to replace it.`) : null,
      h('div', { class: 'swatches' },
        ...colors.map((c, i) => h('div', { class: 'swatch', 'data-i': i },
          h('label', { class: 'swatchColor', style: `background:${c.hex}`, title: 'Change colour' },
            h('input', { type: 'color', value: c.hex, 'aria-label': `${c.name || roleName(i)} colour`,
              oninput: e => { c.hex = e.target.value.toUpperCase(); e.target.parentElement.style.background = c.hex; e.target.parentElement.nextSibling.nextSibling.textContent = c.hex; onChange(writePalette(colors)); },
              onchange: () => changed() })),
          h('input', { type: 'text', class: 'swatchName', value: c.name, placeholder: roleName(i), 'aria-label': 'Colour name',
            oninput: e => { c.name = e.target.value; onChange(writePalette(colors)); } }),
          h('code', { class: 'swatchHex' }, c.hex),
          h('button', { type: 'button', class: 'quiet swatchX', title: 'Remove', onclick: () => { colors.splice(i, 1); changed(); } }, '×'))),
        colors.length < MAX ? h('button', { type: 'button', class: 'quiet swatchAdd', onclick: () => { colors.push({ name: '', hex: '#888888' }); changed(); } }, '+ Add a colour') : null),
      h('div', { class: 'presets' }, h('span', { class: 'muted small' }, 'Or start from a palette:'),
        ...PRESETS.map(([name, hexes]) => h('button', { type: 'button', class: 'preset', title: name, onclick: () => { colors = hexes.map(hex => ({ name: '', hex })); changed(); } },
          h('span', { class: 'presetBar' }, ...hexes.map(hex => h('i', { style: `background:${hex}` }))), h('span', { class: 'small' }, name))))].filter(Boolean));
  };
  draw();
  return root;
}
