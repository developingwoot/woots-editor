import { h, api } from './util.js';

// The Final step: warnings and one render button, the finished video, the publishing details (each with a Copy button),
// the thumbnail layout draft on a frame the creator picks, and "Finish and archive".
const fmt = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

async function copyText(btn, text) {
  const old = btn.textContent;
  try { await navigator.clipboard.writeText(text); btn.textContent = 'Copied'; } catch { btn.textContent = 'Could not copy'; }
  setTimeout(() => { btn.textContent = old; }, 1500);
}

export async function render(root, key, setBusy) {
  const post = (path, body = {}) => api(path, { key, ...body });
  const draw = async data => {
    const { state, button, latest, publish: pub, archive, finals } = data;

    if (data.archived) {
      root.replaceChildren(h('div', { class: 'card empty', id: 'archivedBox' },
        h('p', {}, 'This video is archived.'),
        h('p', { class: 'muted' }, `The final and the saved project are in the footage folder (${archive.done.date}).`),
        h('button', { class: 'quiet', onclick: () => post('/api/v2/final/reveal') }, 'Open the folder')));
      return;
    }

    // --- render
    const video = latest ? h('video', { id: 'finalPlayer', src: latest.video, controls: true, preload: 'metadata' }) : null;
    const render = h('button', { class: 'main', id: 'renderBtn', disabled: !button.enabled, onclick: async () => {
      render.disabled = true;
      try { await post('/api/v2/final/render'); setBusy(); } catch (e) { alert(e.message); render.disabled = false; }
    } }, button.label);
    const top = h('div', { class: 'card finalTop' },
      h('div', { class: 'rhead' }, h('b', {}, 'Final video'),
        latest ? h('button', { class: 'quiet', id: 'openFolder', onclick: () => post('/api/v2/final/reveal') }, 'Open the folder') : null),
      state.why_not ? h('p', { class: 'muted' }, state.why_not) : null,
      state.warnings.length ? h('ul', { class: 'warnings', id: 'warnings' }, ...state.warnings.map(w => h('li', {}, w))) : null,
      video,
      h('div', { class: 'makebox' }, render, h('div', { class: 'muted small' }, [button.detail, button.estimate].filter(Boolean).join(' · ')),
        finals.length ? h('div', { class: 'muted small' }, `${finals[0].label}: ${finals[0].dur} long, made ${finals[0].when}`) : null));

    // --- publishing details
    const titleBox = h('input', { id: 'ownTitle', type: 'text', placeholder: 'Or type your own title', autocomplete: 'off' });
    titleBox.addEventListener('keydown', async e => { if (e.key === 'Enter' && titleBox.value.trim()) await draw(await post('/api/v2/publish/title', { title: titleBox.value })); });
    const titles = h('ul', { class: 'titles', id: 'titles' }, ...pub.titles.map(t => h('li', { class: t === pub.title ? 'chosen' : '' },
      h('button', { class: 'pick', onclick: async () => draw(await post('/api/v2/publish/title', { title: t })) }, t === pub.title ? '●' : '○'), h('span', {}, t),
      h('button', { class: 'quiet', onclick: e => copyText(e.target, t) }, 'Copy'))));

    const field = (id, label, value, rows, onSave, copyValue) => {
      const ta = h('textarea', { id, rows, spellcheck: 'false' }, value);
      ta.addEventListener('blur', async () => { if (ta.value !== value) await onSave(ta.value); });
      const cp = h('button', { class: 'quiet', onclick: () => copyText(cp, ta.value) }, 'Copy');
      return h('div', { class: 'pubfield' }, h('div', { class: 'rhead' }, h('b', {}, label), cp), ta);
    };
    const save = f => async v => draw(await post('/api/v2/publish/field', { field: f, value: v }));

    const prompts = h('div', { class: 'pubfield' }, h('b', {}, 'Thumbnail prompts'),
      pub.thumbnail_prompts.length ? h('ul', { class: 'prompts', id: 'prompts' }, ...pub.thumbnail_prompts.map(p => h('li', {}, h('span', {}, p),
        h('button', { class: 'quiet', onclick: e => copyText(e.target, p) }, 'Copy')))) : h('p', { class: 'muted small' }, 'None yet.'));

    // --- thumbnail layout draft
    const words = h('input', { id: 'thumbWords', type: 'text', value: pub.thumb.text || (pub.thumbnail_text[0] || ''), placeholder: 'The words on the thumbnail', autocomplete: 'off' });
    const chips = h('div', { class: 'chips' }, ...pub.thumbnail_text.map(t => h('button', { class: 'quiet', onclick: () => { words.value = t; } }, t)));
    const make = h('button', { class: 'main small', id: 'makeThumb', disabled: !latest, onclick: async () => {
      make.disabled = true;
      try { await draw(await post('/api/v2/thumb/make', { t: video.currentTime || 0, text: words.value })); } catch (e) { alert(e.message); make.disabled = false; }
    } }, 'Use this frame');
    const thumb = h('div', { class: 'pubfield', id: 'thumbBox' }, h('b', {}, 'Thumbnail layout draft'),
      latest ? h('p', { class: 'muted small' }, 'Play the video above, stop on the frame you like, type the words, then press Use this frame.') : h('p', { class: 'muted small' }, 'Available once the final is rendered.'),
      words, chips, make,
      pub.draft ? h('div', { class: 'draft' }, h('img', { id: 'draftBig', src: pub.draft, alt: '' }),
        h('div', {}, h('img', { id: 'draftSmall', src: pub.draft, alt: '', width: 168, height: 94 }), h('div', { class: 'muted small' }, 'How it looks small'))) : null);

    const note = h('input', { id: 'redoNote', type: 'text', placeholder: 'What should change? (optional)', autocomplete: 'off' });
    const write = h('button', { class: 'main small', id: 'writeBtn', disabled: !pub.enabled, onclick: async () => {
      write.disabled = true;
      try { await post('/api/v2/publish/write', { note: note.value }); setBusy(); } catch (e) { alert(e.message); write.disabled = false; }
    } }, pub.button);
    const publishCard = h('div', { class: 'card', id: 'publishCard' },
      h('div', { class: 'rhead' }, h('b', {}, 'Publishing details'), h('div', { class: 'redo' }, note, write)),
      h('div', { class: 'pubfield' }, h('b', {}, 'Title'), titles.children.length ? titles : h('p', { class: 'muted small' }, 'No title options yet.'), titleBox),
      field('description', 'Description', pub.description, 12, save('description')),
      field('tags', 'Tags', pub.tags.join(', '), 3, save('tags')),
      prompts, thumb);

    // --- finish and archive
    const arch = h('div', { class: 'card', id: 'archiveCard' }, h('b', {}, 'Finish and archive'));
    if (archive.can) {
      arch.append(h('p', { class: 'muted small' }, 'Saves the whole project next to your footage so it can be opened again, moves the final there and clears the files the program can make again.'),
        h('button', { class: 'quiet', id: 'archiveStart', onclick: async () => {
          try { showPlan(await api(`/api/v2/archive/preview?key=${encodeURIComponent(key)}`)); } catch (e) { alert(e.message); }
        } }, 'See what this will do'));
    } else {
      arch.append(h('p', { class: 'muted small' }, archive.why));
    }
    function showPlan(p) {
      arch.replaceChildren(h('b', {}, 'Finish and archive'),
        h('ul', { class: 'plan', id: 'archivePlan' },
          h('li', {}, `The final moves to the footage folder as “${p.final_name}” (${p.final_size}).`),
          h('li', {}, `Kept: ${p.keep}, with a DaVinci Resolve timeline and a README.`),
          ...p.delete.map(d => h('li', {}, `Deleted for good: ${d.what} (${d.size}).`)),
          h('li', {}, `About ${p.frees} is freed.`)),
        h('div', { class: 'row' },
          h('button', { class: 'main', id: 'archiveGo', onclick: async () => {
            try { await post('/api/v2/archive/run', { confirm: true }); setBusy(); } catch (e) { alert(e.message); }
          } }, 'Yes, archive this video'),
          h('button', { class: 'quiet', onclick: async () => draw(await load()) }, 'Cancel')));
    }

    root.replaceChildren(top, publishCard, arch);
  };
  const load = () => api(`/api/v2/final?key=${encodeURIComponent(key)}`);
  await draw(await load());
}
