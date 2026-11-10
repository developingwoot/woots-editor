import { h, api } from './util.js';
import { pickFolder } from './folder.js';
import { fontPicker, palettePicker } from './brandpickers.js';

// Settings and first run: where the app keeps its files, and whether Claude is signed in.
// Folders are saved per user (not in the code); the app restarts to use them.
export async function render(root) {
  let s = await api('/api/v2/settings');
  const draft = {};                                    // folder key -> path typed or chosen but not saved yet
  let note = '';
  let watching = null;
  let models = null;                                   // {hardware, jobs}: loaded after the first draw (it asks the graphics card)
  let polling = null;

  const draw = () => {
    const dirty = Object.keys(draft).length > 0;
    root.replaceChildren(...[
      h('h1', {}, s.first_run ? 'Welcome: set up your folders and channel' : 'Settings'),
      h('nav', { class: 'setNav', id: 'setNav' }, ...[['Folders', 'foldersCard'], ['Your channel', 'channelCard'], ['Claude models', 'claudeModelsCard'], ['Models', 'modelsCard'], ['This computer', 'computerCard']]
        .map(([label, id]) => h('button', { class: 'quiet', type: 'button', onclick: () => { const el = document.getElementById(id); if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' }); } }, label))),
      s.first_run ? h('p', { class: 'muted' }, 'Choose where the app keeps your footage and projects, then tell it about your channel. Nothing is uploaded; these folders stay on your computer.') : null,
      h('section', { class: 'card setCard', id: 'foldersCard' },
        h('h2', {}, 'Folders'),
        ...Object.entries(s.folders).map(([key, f]) => {
          const value = draft[key] ?? f.path;
          const input = h('input', { type: 'text', class: 'setPath', 'data-key': key, value, disabled: f.locked, autocomplete: 'off',
            oninput: e => { draft[key] = e.target.value; document.getElementById('saveSettings').disabled = false; } });
          return h('div', { class: 'setRow' },
            h('label', {}, h('b', {}, f.label), h('div', { class: 'muted small' }, f.help)),
            h('div', { class: 'row' }, input,
              f.locked ? null : h('button', { class: 'quiet', onclick: async () => {
                const p = await pickFolder({ start: value, title: `Choose the ${f.label.toLowerCase()}` });
                if (p) { draft[key] = p; draw(); }
              } }, 'Choose…')),
            h('div', { class: 'muted small' },
              f.locked ? `Set by ${f.source}; change it there.` : (draft[key] !== undefined ? 'Not saved yet.' : f.exists ? `In use (${f.source}).` : 'This folder does not exist yet; it is created when you save.')));
        }),
        h('div', { class: 'row' },
          h('button', { class: 'main', id: 'saveSettings', disabled: !dirty && !s.folders_needed, onclick: save }, 'Save'),
          h('span', { class: 'muted small', id: 'settingsNote' }, note))),
      channelCard(),
      claudeModelsCard(),
      modelsCard(),
      computerCard(),
      h('section', { class: 'card setCard', id: 'claudeCard' },
        h('h2', {}, 'Claude'),
        h('p', { id: 'claudeDetail' }, s.claude.detail),
        s.claude.how ? h('p', { class: 'muted small' }, s.claude.how) : null,
        h('div', { class: 'row' },
          s.claude.installed && !s.claude.signed_in ? h('button', { class: 'main', id: 'claudeSignIn', onclick: signIn }, 'Sign in') : null,
          h('button', { class: 'quiet', id: 'claudeCheck', onclick: check }, 'Check again'))),
      h('p', { class: 'muted small' }, `Saved in ${s.settings_file}`),
      h('p', { class: 'muted small', id: 'appVersion' }, `Woots Editor ${s.version} `,
        h('button', { class: 'quiet', id: 'updateCheck', onclick: async e => {
          const r = await api('/api/v2/update-check', {});
          const out = document.getElementById('updateResult');
          out.replaceChildren(r.error ? r.error : r.newer ? h('span', {}, `Version ${r.latest} is out. `, h('a', { href: r.url, target: '_blank', rel: 'noopener noreferrer' }, 'Download it'),
            ', run setup.bat again after unzipping. Your files are kept elsewhere.') : 'You have the newest version.');
        } }, 'Check for updates'), ' ', h('span', { id: 'updateResult' })),
      s.first_run ? null : h('a', { class: 'quiet', href: '#/' }, '← Back to your videos')].filter(Boolean));
  };

  let computer = null;                                 // {rows:[{id,label,ok,detail,fix}], graphics:{ready,state,error,package}}
  const computerCard = () => h('section', { class: 'card setCard', id: 'computerCard' }, h('h2', {}, 'This computer'),
    computer ? h('div', {}, ...computer.rows.map(r => h('div', { class: 'setRow', 'data-check': r.id },
      h('b', {}, `${r.ok ? '✓' : '✗'} ${r.label}`), h('span', { class: 'muted small' }, ` ${r.detail}`), r.fix ? h('div', { class: 'small' }, r.fix) : null)),
      h('div', { class: 'setRow', 'data-check': 'graphics' }, h('b', {}, `${computer.graphics.ready ? '✓' : '✗'} Graphics tool`),
        h('span', { class: 'muted small' }, computer.graphics.ready ? ' Ready.' : computer.graphics.state === 'running' ? ' Getting it…' : ' Not fetched yet: the first graphic would start with a download.'),
        computer.graphics.error ? h('div', { class: 'small' }, computer.graphics.error) : null,
        computer.graphics.ready ? null : h('button', { class: 'quiet', id: 'getGraphics', disabled: computer.graphics.state === 'running', onclick: async () => {
          computer.graphics = await api('/api/v2/computer/graphics', {}); draw();
          const t = setInterval(async () => { computer = await api('/api/v2/computer'); if (!document.getElementById('computerCard') || computer.graphics.state !== 'running') clearInterval(t); draw(); }, 3000);
        } }, 'Get the graphics tool')),
      h('button', { class: 'quiet', id: 'computerCheck', onclick: async () => { computer = await api('/api/v2/computer'); draw(); } }, 'Check again'))
      : h('p', { class: 'muted small' }, 'Looking…'));

  let channel = null;                                  // {fields:[{key, help, value, default}], file}
  const LABELS = { subjects: 'What your footage shows', name: 'Your name', channel: 'Channel name', topic: 'What the channel is about', cohost: 'Second voice', terms: 'Words speech recognition gets wrong', audience: 'Who watches', voice: 'Your voice and habits',
    headline_font: 'Headline font', label_font: 'Label font', colors: 'Brand colours', tone: 'Tone', always: 'Every video', never: 'No video' };
  const LONG = ['audience', 'voice', 'terms', 'colors', 'always', 'never'];
  const STYLE = ['headline_font', 'label_font', 'colors', 'tone', 'always', 'never'];
  const edited = value => { return v => { value.value = v; document.getElementById('saveChannel').disabled = false; }; };
  const channelName = () => (channel.fields.find(x => x.key === 'channel') || {}).value;
  const channelRow = f => h('div', { class: 'setRow' },
    h('label', {}, h('b', {}, LABELS[f.key] || f.key), h('div', { class: 'muted small' }, f.help)),
    f.key.endsWith('_font') ? fontPicker({ value: f.value, sample: channelName, onChange: edited(f) })
      : f.key === 'colors' ? palettePicker({ value: f.value, onChange: edited(f) })
      : LONG.includes(f.key) ? h('textarea', { rows: 2, class: 'setPath', 'data-key': f.key, placeholder: f.default, oninput: e => { f.value = e.target.value; document.getElementById('saveChannel').disabled = false; } }, f.value)
      : h('input', { type: 'text', class: 'setPath', 'data-key': f.key, placeholder: f.default, value: f.value, oninput: e => { f.value = e.target.value; document.getElementById('saveChannel').disabled = false; } }));
  const channelCard = () => {
    if (!channel) return h('section', { class: 'card setCard', id: 'channelCard' }, h('h2', {}, 'Your channel'), h('p', { class: 'muted' }, 'Loading…'));
    return h('section', { class: 'card setCard', id: 'channelCard' }, h('h2', {}, 'Your channel'),
      h('p', { class: 'muted small' }, 'Claude uses this in everything it writes and checks: your name, your channel, who watches and how you sound.'),
      ...channel.fields.filter(f => !STYLE.includes(f.key)).map(channelRow),
      h('h3', {}, 'Brand and style (optional)'),
      h('p', { class: 'muted small' }, 'Graphics, title cards and thumbnails follow these. They are saved as your own copy of the brand and house-style notes, and you can edit those files by hand.'),
      ...channel.fields.filter(f => STYLE.includes(f.key)).map(channelRow),
      h('div', { class: 'row' }, h('button', { class: 'main', id: 'saveChannel', disabled: true, onclick: saveChannel }, 'Save'), h('span', { class: 'muted small', id: 'channelNote' }, '')));
  };
  const saveChannel = async () => {
    const fields = Object.fromEntries(channel.fields.map(f => [f.key, f.value]));
    try {
      channel = await api('/api/v2/channel', { fields });
      s = { ...s, ...(await api('/api/v2/settings')) };
      draw();
      document.getElementById('channelNote').textContent = 'Saved. Restart the app so speaker names in outlines are read the new way.';
    } catch (e) { document.getElementById('channelNote').textContent = e.message; }
  };

  // Which Claude model, and how hard it thinks, for each kind of background run. Saved the moment a choice changes.
  let claudeModels = null;                              // {jobs: [{job, label, help, model, effort, models}], efforts}
  const claudeModelsCard = () => {
    if (!claudeModels) return h('section', { class: 'card setCard', id: 'claudeModelsCard' }, h('h2', {}, 'Claude models'), h('p', { class: 'muted' }, 'Loading…'));
    const choose = (job, field) => async e => {
      try { claudeModels = await api('/api/v2/claude-models', { choices: { [job]: { [field]: e.target.value } } }); note = ''; }
      catch (err) { note = err.message; }
      draw();
    };
    const pick = (job, field, current, options) => h('select', { class: 'cmPick', 'data-job': job, 'data-field': field, onchange: choose(job, field) },
      ...options.map(o => h('option', { value: o, selected: o === current }, (o === 'off' ? 'Off' : o[0].toUpperCase() + o.slice(1)) + (o === defaults[job + field] ? ' (recommended)' : ''))));
    const defaults = Object.fromEntries(claudeModels.jobs.flatMap(j => [[j.job + 'model', j.default_model], [j.job + 'effort', j.default_effort]]));
    const backToDefaults = async () => {
      try { claudeModels = await api('/api/v2/claude-models', { choices: Object.fromEntries(claudeModels.jobs.map(j => [j.job, { model: j.default_model, effort: j.default_effort }])) }); note = ''; }
      catch (err) { note = err.message; }
      draw();
    };
    return h('section', { class: 'card setCard', id: 'claudeModelsCard' }, h('h2', {}, 'Claude models'),
      h('p', { class: 'muted small' }, 'Which Claude does each job, and how hard it thinks. Higher effort is slower and uses more of your plan. Choices apply to the next run.'),
      h('div', { class: 'row' }, h('button', { class: 'quiet', id: 'modelDefaults', type: 'button', onclick: backToDefaults }, 'Back to defaults')),
      ...claudeModels.jobs.map(j => h('div', { class: 'setRow', 'data-job': j.job },
        h('label', {}, h('b', {}, j.label), h('div', { class: 'muted small' }, j.help)),
        h('div', { class: 'row' }, pick(j.job, 'model', j.model, j.models), j.model === 'off' ? null : pick(j.job, 'effort', j.effort, claudeModels.efforts)))));
  };

  const JOBS = { speech: ['Reading your recordings', 'Turns speech into words with times.'], vision: ['Describing your footage', 'Looks at frames so clips can be found by what they show.'],
    embed: ['Finding clips', 'Matches a shot idea to a clip.'] };
  const modelsCard = () => {
    if (!models) return h('section', { class: 'card setCard', id: 'modelsCard' }, h('h2', {}, 'Models'), h('p', { class: 'muted' }, 'Checking your computer…'));
    const hw = models.hardware;
    const gpu = hw.gpus.length ? hw.gpus.map(g => `${g.name} (${g.vram_gb} GB)`).join(', ') : 'no Nvidia graphics card found';
    const missing = ['ffmpeg', 'ffprobe'].filter(k => !hw.tools[k]);
    return h('section', { class: 'card setCard', id: 'modelsCard' }, h('h2', {}, 'Models'),
      h('p', { class: 'muted small', id: 'hwLine' }, `This computer: ${gpu}; ${hw.ram_gb ?? '?'} GB memory; ${hw.free_gb ?? '?'} GB free for the workspace. Models are not part of the app: they download when you press Download.`),
      missing.length ? h('p', { class: 'bad small' }, `Missing: ${missing.join(', ')}. Install ffmpeg and make sure it is on the PATH.`) : null,
      ...Object.entries(models.jobs).map(([job, rows]) => h('div', { class: 'modelJob', 'data-job': job },
        h('b', {}, JOBS[job][0]), h('div', { class: 'muted small' }, JOBS[job][1]),
        ...rows.map(r => h('div', { class: 'modelRow' + (r.fits && r.built ? '' : ' off'), 'data-id': r.id },
          h('div', { class: 'modelName' }, h('b', {}, r.name), r.recommended ? h('span', { class: 'chip2 ok' }, 'recommended') : null, r.chosen ? h('span', { class: 'chip2' }, 'in use') : null,
            h('div', { class: 'muted small' }, [r.note, !r.built ? 'Not available yet.' : '', r.why ? `Does not fit: ${r.why}.` : '', `Download ${r.gb} GB.`].filter(Boolean).join(' '), ' ', h('span', { class: 'small' }, `Licence: ${r.licence}. `, h('a', { href: r.card, target: '_blank', rel: 'noopener noreferrer' }, 'Model card')))),
          h('div', { class: 'modelAct' },
            r.state === 'running' ? h('progress', { max: 1, value: r.progress }) : null,
            r.state === 'installed' ? h('span', { class: 'chip2 ok' }, 'downloaded') : null,
            r.state === 'error' ? h('span', { class: 'bad small', title: r.error }, 'download failed') : null,
            r.state !== 'installed' && r.state !== 'running' && r.built && r.fits ? h('button', { class: 'quiet', onclick: () => modelOp({ op: 'download', id: r.id }) }, r.state === 'partial' || r.state === 'error' ? 'Resume download' : 'Download') : null,
            job !== 'embed' && r.built && r.fits && !r.chosen ? h('button', { class: 'quiet', onclick: () => modelOp({ op: 'choose', job, id: r.id }) }, 'Use this') : null))))));
  };
  const modelOp = async body => {
    try { models = await api('/api/v2/engines', body); } catch (e) { note = e.message; }
    draw();
    watchDownloads();
  };
  const watchDownloads = () => {
    clearInterval(polling);
    if (!models || !Object.values(models.jobs).flat().some(r => r.state === 'running')) return;
    polling = setInterval(async () => {
      if (!document.getElementById('modelsCard')) return clearInterval(polling);
      models = await api('/api/v2/engines').catch(() => models);
      draw();
      if (!Object.values(models.jobs).flat().some(r => r.state === 'running')) clearInterval(polling);
    }, 2000);
  };

  const save = async () => {
    try {
      const r = await api('/api/v2/settings', { folders: draft, restart: true });
      s = r;
      for (const k of Object.keys(draft)) delete draft[k];
      note = r.restarting ? 'Saved. Restarting the app…' : 'Saved. Restart the app to use the new folders.';
      draw();
      if (r.restarting) setTimeout(waitForServer, 2500);
    } catch (e) { note = e.message; draw(); }
  };
  const waitForServer = async () => {
    try { s = await api('/api/v2/settings'); note = 'Saved.'; draw(); if (!s.first_run) location.hash = '#/'; }
    catch { setTimeout(waitForServer, 1000); }
  };
  const check = async () => {
    s = { ...s, claude: await api('/api/v2/claude') };
    draw();
  };
  const signIn = async () => {
    const r = await api('/api/v2/claude/login', {});
    s.claude = { ...s.claude, detail: r.detail };
    draw();
    clearInterval(watching);
    let tries = 0;
    watching = setInterval(async () => {                       // the sign-in finishes in the browser: watch for it
      tries++;
      if (!document.getElementById('claudeCard') || tries > 90) return clearInterval(watching);
      const c = await api('/api/v2/claude').catch(() => null);
      if (c && c.signed_in) { clearInterval(watching); s.claude = c; draw(); }
    }, 2000);
  };
  draw();
  api('/api/v2/computer').then(c => { computer = c; if (document.getElementById('computerCard')) draw(); }).catch(() => {});
  api('/api/v2/channel').then(c => { channel = c; if (document.getElementById('channelCard')) draw(); }).catch(() => {});
  api('/api/v2/claude-models').then(m => { claudeModels = m; if (document.getElementById('claudeModelsCard')) draw(); }).catch(() => {});
  api('/api/v2/engines').then(m => { models = m; if (document.getElementById('modelsCard')) { draw(); watchDownloads(); } }).catch(() => {});
}
