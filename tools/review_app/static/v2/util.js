// Small helpers for the v2 screens (copied in, not shared with the old core.js).
export const $ = (sel, root = document) => root.querySelector(sel);

export function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid);
  return el;
}

export async function api(path, body) {
  const t0 = Date.now();
  const r = await fetch(path, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || 'Something went wrong.');
  if (body !== undefined) document.dispatchEvent(new CustomEvent('wr-saved', { detail: { path, t0 } }));   // undo.js looks for a plan file this call changed
  return data;
}

// Every video player remembers the volume (and mute) last set: saved when it changes, put back when a player loads (same keys as the old app's core.js).
{
  const get = k => { try { return JSON.parse(localStorage.getItem('wr.' + k)); } catch { return null; } };
  const set = (k, v) => { try { localStorage.setItem('wr.' + k, JSON.stringify(v)); } catch { /* private mode */ } };
  let applying = false;
  const apply = v => {
    const vol = get('volume'), muted = get('muted');
    applying = true;
    if (typeof vol === 'number' && v.volume !== vol) v.volume = vol;
    if (typeof muted === 'boolean' && v.muted !== muted) v.muted = muted;
    applying = false;
  };
  document.addEventListener('volumechange', e => {
    if (applying || !(e.target instanceof HTMLVideoElement)) return;
    set('volume', e.target.volume); set('muted', e.target.muted);
  }, true);
  for (const ev of ['loadstart', 'loadedmetadata', 'play'])
    document.addEventListener(ev, e => { if (e.target instanceof HTMLVideoElement) apply(e.target); }, true);
}
