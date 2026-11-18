import { el } from '../core/dom.js';
import { CARD, REPLY_DRAFTS, agentState, agentText, openThreads, pickLabel, threadById, threadLabel } from './store.js';

export function renderPickBar(host, pick, actions) {
  host.querySelectorAll('.pick-bar').forEach((bar) => bar.remove());
  if (!pick || (CARD && CARD.mode === 'new')) return;
  host.append(el('div', { class: 'pick-bar' },
    el('span', {}, pickLabel(pick)),
    el('button', { class: 'btn small primary', title: 'Comment on the selection (C)', onclick: () => actions.compose() }, '💬 Comment'),
    pick.implicit ? null : el('button', { class: 'btn small', title: 'Clear the selection (Esc)', onclick: () => actions.clearPick() }, '✕')));
}

export function renderCommentCard(host, actions) {
  const before = host.querySelector('.comment-card textarea');
  const focus = before && document.activeElement === before ? { start: before.selectionStart, end: before.selectionEnd } : null;
  host.querySelectorAll('.comment-card').forEach((card) => card.remove());
  if (!CARD) return;
  const card = CARD.mode === 'new' ? composerCard(actions) : threadCard(actions);
  if (!card) return;
  host.append(card);
  const area = card.querySelector('textarea');
  if (area && (focus || CARD.focus)) { area.focus(); if (focus) area.setSelectionRange(focus.start, focus.end); CARD.focus = false; }
}

function composerCard(actions) {
  const area = el('textarea', { placeholder: 'What should change, or what is unclear?', rows: 4 });
  area.value = CARD.draft || '';
  area.addEventListener('input', () => { CARD.draft = area.value; });
  const save = () => { if (area.value.trim()) actions.create(CARD.anchor, area.value); };
  submitOnKeys(area, save, () => actions.close());
  return el('div', { class: 'comment-card' },
    el('div', { class: 'comment-card-head' }, el('strong', {}, 'New comment'), el('button', { class: 'btn small', title: 'Cancel (Esc)', onclick: () => actions.close() }, '✕')),
    el('div', { class: 'comment-card-where' }, CARD.anchor.label),
    area,
    el('div', { class: 'comment-card-actions' }, el('span', { class: 'udim' }, '⌘/Ctrl + Enter'), el('button', { class: 'btn small primary', onclick: save }, 'Comment')));
}

function threadCard(actions) {
  const thread = threadById(CARD.id);
  if (!thread) return null;
  const area = replyArea(thread);
  const send = () => { if (area.value.trim()) { actions.reply(thread.id, area.value); REPLY_DRAFTS.delete(thread.id); } };
  submitOnKeys(area, send, () => actions.close());
  return el('div', { class: `comment-card${thread.resolved ? ' resolved' : ''}` },
    threadHead(thread, actions),
    el('div', { class: 'comment-card-where' }, threadLabel(thread), thread.where && thread.where.outdated ? el('span', { class: 'outdated', title: 'The code this points at has changed since' }, 'outdated') : null),
    el('div', { class: 'comment-messages' }, thread.messages.map(messageEl)),
    el('div', { class: `comment-agent-state agent-${agentState(thread)}` }, el('span', { class: `agent-dot agent-${agentState(thread)}` }), thread.resolved ? 'Resolved' : agentText(thread)),
    area,
    el('div', { class: 'comment-card-actions' },
      el('button', { class: 'btn small', onclick: () => actions.resolve(thread.id, !thread.resolved) }, thread.resolved ? 'Reopen' : '✓ Resolve'),
      el('button', { class: 'btn small primary', disabled: thread.resolved, onclick: send }, 'Reply')));
}

function replyArea(thread) {
  const area = el('textarea', { placeholder: thread.resolved ? 'Reopen to reply' : 'Reply…', rows: 2 });
  area.disabled = thread.resolved;
  area.value = REPLY_DRAFTS.get(thread.id) || '';
  area.addEventListener('input', () => REPLY_DRAFTS.set(thread.id, area.value));
  return area;
}

function threadHead(thread, actions) {
  const open = openThreads();
  const at = open.findIndex((t) => t.id === thread.id);
  const step = (title, by, label) => el('button', { class: 'btn small', title, disabled: open.length < 2, onclick: () => actions.step(by) }, label);
  return el('div', { class: 'comment-card-head' },
    el('strong', {}, thread.id),
    el('span', { class: 'comment-card-nav' },
      step('Previous open comment ([)', -1, '‹'),
      el('span', { class: 'udim' }, at >= 0 ? `${at + 1} of ${open.length}` : 'resolved'),
      step('Next open comment (])', 1, '›')),
    el('button', { class: 'btn small', title: 'Close (Esc)', onclick: () => actions.close() }, '✕'));
}

function messageEl(message) {
  const when = new Date(message.at * 1000).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' });
  return el('div', { class: `comment-message from-${message.author}` },
    el('div', { class: 'comment-meta' }, message.author === 'agent' ? 'Agent' : 'You', ' · ', when),
    el('div', { class: 'comment-body' }, message.body));
}

function submitOnKeys(area, submit, close) {
  area.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submit();
    if (e.key === 'Escape') close();
  });
}
