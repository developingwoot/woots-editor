import { h, api } from './util.js';
import * as review from './review.js';
import * as finalStep from './final.js';
import * as outlineStep from './outline.js';
import * as footageStep from './footage.js';

const STEP_NAMES = { outline: 'Outline', footage: 'Footage', 'rough-cut': 'Rough cut', preview: 'Preview', final: 'Final', shorts: 'Shorts' };
const REVIEW_STAGE = { preview: 'preview', 'rough-cut': 'cut' };

export async function render(root, [key, step], busy) {
  review.leave();
  const v = await api(`/api/v2/video?key=${encodeURIComponent(key)}`);
  const bar = h('nav', { class: 'stepbar' },
    ...v.steps.map(s => h('a', { href: `#/v/${key}/${s.id}`, class: 'step' + (s.id === step ? ' current' : ''), 'data-dot': s.dot },
      h('i', { class: 'dot' }), s.title)));
  const body = h('div', { id: 'stepBody' });
  root.replaceChildren(
    h('div', { class: 'headrow' }, h('a', { class: 'quiet', href: '#/' }, '← Your videos'), h('h1', {}, v.title)),
    bar, body);
  if (REVIEW_STAGE[step]) return review.render(body, key, REVIEW_STAGE[step], busy);
  if (step === 'final') return finalStep.render(body, key, busy);
  if (step === 'outline') return outlineStep.render(body, key, busy);
  if (step === 'footage') return footageStep.render(body, key, busy);
  body.append(h('div', { class: 'card empty' },
    h('p', {}, `${STEP_NAMES[step] || 'This step'} is coming soon.`),
    h('p', { class: 'muted' }, v.sentence)));
}
