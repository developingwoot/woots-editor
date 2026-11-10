import { $, h, api } from './util.js';
import * as home from './home.js';
import * as video from './video.js';
import * as settings from './settings.js';
import * as shorts from './shorts.js';

// Hash router: #/ is home, #/v/<key>/<step> is a video page.
const routes = [[/^#?\/?$/, home], [/^#\/settings$/, settings], [/^#\/shorts$/, shorts], [/^#\/shorts\/([^/]+)$/, { render: shorts.renderStandalone }], [/^#\/v\/([^/]+)\/([\w-]+)$/, video]];

async function show() {
  for (const [re, screen] of routes) {
    const m = re.exec(location.hash);
    if (m) {
      try { await screen.render($('#screen'), m.slice(1).map(decodeURIComponent), pollSoon); }
      catch (e) { $('#screen').replaceChildren(h('div', { class: 'card empty' }, e.message)); }
      return;
    }
  }
  location.hash = '#/';
}

// Job bar: one sentence, a progress bar, an estimate and Stop for whatever is running; a plain error with "Show details" if the last job failed.
let handled;                                           // id of the last finished job the page already knows about (undefined until the first poll)
let dismissed = null;
let shownFailure = null;                               // id of the failed job whose message is on screen
let timer = null;
const pollSoon = () => { clearTimeout(timer); pollJob(); };

async function pollJob() {
  const bar = $('#jobBar');
  try {
    const { job, last } = await api('/api/v2/job');
    if (handled === undefined) handled = last && last.state !== 'running' ? last.id : null;
    if (job) {
      bar.hidden = false;
      bar.replaceChildren(h('span', {}, job.sentence + (job.estimate ? ` (${job.estimate})` : '')),
        h('progress', { max: 1, value: job.progress ?? undefined }),
        h('button', { class: 'quiet onDark', id: 'stopJob', onclick: async () => { await api('/api/v2/job/stop', { id: job.id }); pollSoon(); } }, 'Stop'));
    } else {
      if (last && last.id !== handled) { handled = last.id; show(); }       // a job finished (even one too quick to be seen running): redraw
      const failed = last && last.state === 'failed' && last.id !== dismissed;
      bar.hidden = !failed;
      if (failed && shownFailure !== last.id) {              // drawn once per failure: redrawing every poll would close the details box while it is being read
        shownFailure = last.id;
        const copy = h('button', { class: 'quiet onDark', id: 'copyDetails', onclick: async () => {
          try { await navigator.clipboard.writeText(last.details || ''); copy.textContent = 'Copied'; } catch { copy.textContent = 'Select the text and copy it'; }
        } }, 'Copy the details');
        bar.replaceChildren(h('span', {}, last.error),
          h('details', { class: 'jobDetails' }, h('summary', {}, 'Show details'), h('pre', {}, last.details || 'No details.')),
          copy,
          h('button', { class: 'quiet onDark', onclick: () => { dismissed = last.id; pollSoon(); } }, 'Dismiss'));
      }
      if (!failed) shownFailure = null;
    }
  } catch { bar.hidden = true; }
  timer = setTimeout(pollJob, 2000);
}

addEventListener('hashchange', show);
api('/api/v2/settings').then(r => { if (r.first_run && location.hash !== '#/settings') location.hash = '#/settings'; }).catch(() => {});   // a fresh install starts at setup
show();
pollJob();
