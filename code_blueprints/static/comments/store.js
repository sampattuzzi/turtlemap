import { FUNCTIONS, fnKey } from '../core/data.js';
import { api, baseName, el } from '../core/dom.js';
let COMMENTS = { threads: [], cursor: 0, agent: {} };
let COMMENT_WATCH = 0;
let COMMENT_ACTIONS = null;
export let onCommentsChanged = () => {};
export let PICK = null;
export let CARD = null;
export function setCommentActions(actions) { COMMENT_ACTIONS = actions; }
export function setCommentsListener(listener) { onCommentsChanged = listener; }
export function setCommentPick(pick) { PICK = pick; }
export function setCommentCard(card) { CARD = card; }
export const REPLY_DRAFTS = new Map();
const AGENT_WORDS = { seen: 'Agent has seen this', working: 'Agent is working on this', done: 'Agent thinks this is done' };

export async function loadComments() {
  try {
    const data = await api('/api/comments');
    COMMENTS = { threads: data.threads, cursor: data.cursor, agent: data.agent || {} };
  } catch (error) {
    COMMENTS = { threads: [], cursor: 0, agent: {} };
  }
}

export function startCommentWatch() {
  const generation = ++COMMENT_WATCH;
  (async () => {
    while (generation === COMMENT_WATCH) {
      try {
        const since = COMMENTS.cursor;
        const answer = await api(`/api/comments/events?since=${since}&wait=25`);
        if (generation !== COMMENT_WATCH) return;
        if (answer.cursor < since) { await loadComments(); onCommentsChanged(); continue; }
        mergeThreads(answer.threads);
        COMMENTS.cursor = answer.cursor;
        COMMENTS.agent = answer.agent || COMMENTS.agent;
        if (answer.events.length) { announce(answer.events); onCommentsChanged(); }
      } catch (error) {
        await new Promise((resolve) => setTimeout(resolve, 3000));
      }
    }
  })();
}

export function mergeThreads(threads) {
  for (const thread of threads) {
    const at = COMMENTS.threads.findIndex((t) => t.id === thread.id);
    if (at >= 0) COMMENTS.threads[at] = thread; else COMMENTS.threads.push(thread);
  }
}

export function openThreads() { return COMMENTS.threads.filter((t) => !t.resolved); }

export function allThreads() { return COMMENTS.threads; }

export function agentStatus() { return COMMENTS.agent || {}; }

export function openThread(id) { if (COMMENT_ACTIONS) COMMENT_ACTIONS.open(id); }

export function agentState(thread) { return thread.resolved ? 'resolved' : (thread.agent && thread.agent.state) || 'unseen'; }

export function threadById(id) { return COMMENTS.threads.find((t) => t.id === id) || null; }

function announce(events) {
  for (const event of events) {
    if (event.author !== 'agent' || !event.thread) continue;
    const thread = threadById(event.thread);
    if (!thread) continue;
    if (event.type === 'replied') toast(`Agent replied on ${threadLabel(thread)}`, () => openThread(thread.id));
    if (event.type === 'agent' && thread.agent && thread.agent.state === 'done') toast(`Agent thinks “${threadLabel(thread)}” is done`, () => openThread(thread.id));
  }
}

export function toast(text, onClick) {
  document.querySelectorAll('.toast').forEach((t) => t.remove());
  const box = el('button', { class: 'toast', onclick: () => { box.remove(); onClick(); } }, '💬 ', text);
  document.body.append(box);
  setTimeout(() => box.remove(), 7000);
}

export function threadLabel(thread) { return thread.anchor.label || anchorLabel(thread.anchor); }

function anchorLabel(anchor) {
  if (anchor.view === 'map') {
    const ids = anchor.ids || [];
    return ids.length === 1 ? shortId(ids[0]) : `${ids.length} boxes in ${commonPlace(ids)}`;
  }
  if (anchor.view === 'blueprint') {
    const nodes = anchor.nodes || [];
    if (!nodes.length || (nodes.length === 1 && nodes[0].title === anchor.qual)) return anchor.qual;
    return `${anchor.qual} · ${nodes.length === 1 ? nodes[0].title : `${nodes.length} nodes`}`;
  }
  const lines = anchor.start === anchor.end ? `line ${anchor.start}` : `lines ${anchor.start}–${anchor.end}`;
  return `${anchor.qual || baseName(anchor.path)} · ${lines}`;
}

function shortId(id) {
  const [kind, rest] = [id.slice(0, id.indexOf(':')), id.slice(id.indexOf(':') + 1)];
  if (kind === 'pkg') return `${rest}/`;
  if (kind === 'mod') return baseName(rest);
  if (['cls', 'fn', 'm', 'f', 'c'].includes(kind)) { const at = rest.lastIndexOf(':'); return `${baseName(rest.slice(0, at))} › ${rest.slice(at + 1)}`; }
  return rest;
}

function commonPlace(ids) {
  const paths = ids.map((id) => id.slice(id.indexOf(':') + 1).split(':')[0]);
  const first = paths[0] || '';
  return paths.every((p) => p === first) ? baseName(first) : 'several places';
}

export function agentText(thread) {
  const agent = thread.agent || {};
  if (!agent.state) return "Agent hasn't seen this yet";
  return agent.state === 'working' && agent.note ? `Agent is working: ${agent.note}` : AGENT_WORDS[agent.state];
}

export function pickLabel(pick) {
  if (pick.kind === 'code') return `${pick.qual || baseName(pick.path)} · ${pick.start === pick.end ? `line ${pick.start}` : `lines ${pick.start}–${pick.end}`}`;
  if (pick.kind === 'map') return pick.ids.size === 1 ? shortId([...pick.ids][0]) : `${pick.ids.size} boxes`;
  return `${pick.fn.sym} · ${pick.ids.size === 1 ? '1 node' : `${pick.ids.size} nodes`}`;
}

export function anchorFor(pick) {
  const fnRef = pick.fn;
  if (pick.kind === 'map') { const ids = [...pick.ids]; return { view: 'map', ids, label: anchorLabel({ view: 'map', ids }) }; }
  if (pick.kind === 'code') {
    const anchor = { view: 'code', path: pick.path, qual: pick.qual || null, start: pick.start, end: pick.end };
    if (pick.text) anchor.text = pick.text;
    return { ...anchor, label: anchorLabel(anchor) };
  }
  const data = FUNCTIONS.get(fnKey(fnRef));
  const byId = new Map((data ? data.graph.nodes : []).map((n) => [n.id, n]));
  const nodes = [...pick.ids].map((id) => byId.get(id)).filter(Boolean).map((n) => ({ id: n.id, title: n.kind === 'entry' ? fnRef.sym : n.title, line: n.diff === 'removed' ? null : n.line }));
  const anchor = { view: 'blueprint', path: fnRef.path, qual: fnRef.sym, nodes };
  return { ...anchor, label: anchorLabel(anchor) };
}

export function codeRange(thread) {
  const placed = thread.where && thread.where.locations && thread.where.locations[0];
  if (thread.anchor.view !== 'code') return null;
  return placed && placed.start ? { path: placed.path, start: placed.start, end: placed.end } : thread.anchor;
}
