import { el } from '../core/dom.js';
import { CARD, agentState, agentStatus, agentText, allThreads, onCommentsChanged, openThread, openThreads, threadLabel } from './store.js';

const AGENT_ACTIVE_SECONDS = 90;
const AGENT_NOTE_SECONDS = 30 * 60;
const EMPTY_HINT = 'Select something and press C, or use 💬 Comment, to leave a comment. ⌘ or Ctrl-click adds boxes and nodes to a selection, Shift-drag draws a box around them, and dragging down the line numbers picks lines of code.';
let SHOW_RESOLVED = false;

export function renderCommentList(left) {
  const open = openThreads();
  const shown = SHOW_RESOLVED ? allThreads() : open;
  left.append(listHead(open.length));
  const agent = agentLine();
  if (agent) left.append(el('div', { class: 'comment-agent' }, agent));
  if (!shown.length) {
    left.append(el('p', { class: 'comment-hint' }, EMPTY_HINT));
    return;
  }
  const ordered = [...shown].sort((a, b) => Number(a.resolved) - Number(b.resolved) || a.created - b.created);
  for (const thread of ordered) left.append(commentRow(thread));
}

export function paintAgentChip() {
  const chip = document.getElementById('agent-chip');
  if (!chip) return;
  chip.innerHTML = '';
  const line = agentLine();
  chip.hidden = !line;
  if (line) chip.append(line);
}
setInterval(paintAgentChip, 30000);

function listHead(openCount) {
  const toggle = () => { SHOW_RESOLVED = !SHOW_RESOLVED; onCommentsChanged(); };
  return el('div', { class: 'comment-head' },
    el('span', {}, `${openCount} open`),
    el('button', { class: 'btn small', onclick: toggle }, SHOW_RESOLVED ? 'Hide resolved' : 'Show resolved'));
}

function commentRow(thread) {
  const active = CARD && CARD.id === thread.id;
  return el('button', { class: `comment-row${thread.resolved ? ' resolved' : ''}${active ? ' active' : ''}`, onclick: () => openThread(thread.id) },
    el('span', { class: `agent-dot agent-${agentState(thread)}`, title: thread.resolved ? 'Resolved' : agentText(thread) }),
    el('span', { class: 'comment-row-main' },
      el('span', { class: 'comment-row-label' }, threadLabel(thread), thread.where && thread.where.outdated ? el('span', { class: 'outdated' }, 'outdated') : null),
      el('span', { class: 'comment-row-body' }, thread.messages[0].body),
      el('span', { class: 'comment-row-meta' }, `${replySummary(thread)}${thread.resolved ? 'resolved' : agentText(thread)}`)));
}

function replySummary(thread) {
  const count = thread.messages.length;
  if (count < 2) return '';
  const last = thread.messages[count - 1];
  return `${count - 1} repl${count > 2 ? 'ies' : 'y'} · last by ${last.author === 'agent' ? 'agent' : 'you'} · `;
}

function agentLine() {
  const agent = agentStatus();
  const now = Date.now() / 1000;
  const active = agent.polled && now - agent.polled < AGENT_ACTIVE_SECONDS;
  const note = agent.note && agent.at && now - agent.at < AGENT_NOTE_SECONDS ? agent.note : null;
  if (!active && !note) return null;
  return el('span', { class: `agent-status${active ? ' active' : ''}`, title: active ? 'An agent is watching for comments' : 'No agent has checked in for a while' }, active ? '● ' : '○ ', note ? `Agent: ${note}` : 'Agent watching');
}
