import { h, api, say } from './util.js';

// Audience retention on the Final screen: import the export from YouTube Studio, then the graph with where viewers left or watched again
// and what the video was saying and showing there.
const fmt = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
const NS = 'http://www.w3.org/2000/svg';
const svg = (tag, attrs = {}, ...kids) => {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  el.append(...kids);
  return el;
};

function chart(r, seek) {
  const W = 720, H = 180, L = 34, B = 20, T = 8;
  const top = Math.max(1, ...r.curve.map(p => p[1]));
  const x = t => L + (W - L - 4) * t / r.dur, y = v => T + (H - T - B) * (1 - v / top);
  const kids = [];
  for (const v of [0, 0.5, 1].filter(g => g <= top)) {
    kids.push(svg('line', { x1: L, x2: W - 4, y1: y(v), y2: y(v), stroke: 'currentColor', 'stroke-opacity': 0.15 }));
    const label = svg('text', { x: L - 6, y: y(v) + 4, 'text-anchor': 'end', 'font-size': 11, fill: 'currentColor', 'fill-opacity': 0.6 });
    label.textContent = `${Math.round(v * 100)}%`;
    kids.push(label);
  }
  for (const m of r.moments) {
    const band = svg('rect', { x: x(m.t) - 3, y: T, width: 6, height: H - T - B, fill: m.kind === 'drop' ? '#d9534f' : '#3a9d5d', 'fill-opacity': 0.35, style: 'cursor:pointer' });
    const tip = svg('title'); tip.textContent = `${m.when}: ${m.size}`; band.append(tip);
    band.addEventListener('click', () => seek(m.t));
    kids.push(band);
  }
  kids.push(svg('polyline', { points: r.curve.map(p => `${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join(' '), fill: 'none', stroke: 'currentColor', 'stroke-width': 2 }));
  for (const t of [0, r.dur / 2, r.dur]) {
    const label = svg('text', { x: x(t), y: H - 4, 'text-anchor': t === 0 ? 'start' : t === r.dur ? 'end' : 'middle', 'font-size': 11, fill: 'currentColor', 'fill-opacity': 0.6 });
    label.textContent = fmt(t);
    kids.push(label);
  }
  return svg('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'Share of viewers still watching through the video', style: 'width:100%;height:auto;margin:8px 0' }, ...kids);
}

export function retentionCard(key, r, redraw) {
  if (!r) return null;
  const file = h('input', { type: 'file', id: 'retentionFile', accept: '.csv,.zip,.tsv,.txt,.json', style: 'display:none' });
  file.addEventListener('change', async () => {
    const f = file.files[0];
    if (!f) return;
    try {
      const bytes = new Uint8Array(await f.arrayBuffer());
      let bin = '';
      for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
      redraw(await api('/api/v2/retention/import', { key, data: btoa(bin), file: f.name }));
    } catch (e) { say(e.message); }
    file.value = '';
  });
  const pick = h('button', { class: r.has ? 'quiet' : 'main', id: 'retentionImport', disabled: !r.can, onclick: () => file.click() }, r.has ? 'Import a newer export' : 'Import the retention export');
  const how = h('p', { class: 'muted small' }, 'In YouTube Studio open the video, then Analytics › Engagement › Audience retention › See more, and use the download button (top right). Choose the file it saves here: the .zip as it is, or the .csv inside.',
    r.can ? '' : ' Render the final first, so the graph can be lined up with it.');
  if (!r.has) return h('div', { class: 'card', id: 'retentionCard' }, h('b', {}, 'Audience retention'), h('p', { class: 'muted' }, 'Once the video has been public for a while, see where viewers left and what was on screen then.'), how, h('div', { class: 'row' }, pick, file));

  const seek = t => { const v = document.getElementById('finalPlayer'); if (v) { v.currentTime = t; v.scrollIntoView({ block: 'center' }); } };
  const rows = r.moments.map(m => h('div', { class: 'frow', 'data-kind': m.kind },
    h('a', { class: 'when', href: '#', onclick: e => { e.preventDefault(); seek(m.t); } }, m.when),
    h('div', { class: 'ftext' }, h('b', {}, m.kind === 'drop' ? 'Viewers left. ' : 'Watched again. '), m.size + '.',
      h('div', { class: 'muted small' }, [m.chapter && `Chapter: ${m.chapter}.`, m.picture && `Picture: ${m.picture}.`].filter(Boolean).join(' ')),
      m.said ? h('div', { class: 'small' }, `“${m.said}”`) : null)));
  const others = r.others.length ? h('details', {}, h('summary', {}, `Your other videos (${r.others.length})`),
    h('table', { class: 'small' }, h('tr', {}, ...['Video', 'After the hook', 'Average', 'At the end', 'Length'].map(t => h('th', { style: 'text-align:left;padding-right:14px' }, t))),
      ...r.others.map(o => h('tr', {}, ...[o.title, o.hook, o.average, o.end, o.length].map(t => h('td', { style: 'padding-right:14px' }, t)))))) : null;
  return h('div', { class: 'card', id: 'retentionCard' },
    h('div', { class: 'rhead' }, h('b', {}, 'Audience retention'), h('span', { class: 'muted small' }, `imported ${r.imported}${r.source ? ` from ${r.source}` : ''}`)),
    h('p', { id: 'retentionNumbers' }, `${r.hook.share} still watching after ${r.hook.at}. ${r.average} watching on average, ${r.end} at the end.`),
    chart(r, seek),
    r.moments.length ? h('div', { id: 'retentionMoments' }, ...rows) : h('p', { class: 'muted' }, 'No moment stands out: viewers leave at an even rate through the video.'),
    h('p', { class: 'muted small' }, r.note), others, h('div', { class: 'row' }, pick, file), how);
}
