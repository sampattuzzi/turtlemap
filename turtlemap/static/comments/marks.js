import { FUNCTIONS, fnKey, lookup, net } from '../core/data.js';
import { el } from '../core/dom.js';
import { CARD, PICK, codeRange, openThreads, setCommentPick } from './store.js';

export function decorateMap(sceneEl, open) {
  const pins = new Map();
  for (const thread of openThreads()) {
    const boxes = new Set(mapTargets(thread.anchor).map((id) => shownBox(sceneEl, id)).filter(Boolean));
    markThread(thread, [...boxes], pins);
  }
  for (const [box, threads] of pins) addPin(box.classList.contains('leaf') ? box : box.querySelector(':scope > .nhead') || box, threads, open);
  if (PICK && PICK.kind === 'map') for (const id of PICK.ids) markPicked(sceneEl.querySelector(`.nb[data-id="${CSS.escape(id)}"]`));
}

export function decorateBlueprint(layer, fnRef, open) {
  const elements = new Map([...layer.querySelectorAll(':scope > .node[data-node]')].map((e) => [e.dataset.node, e]));
  const data = FUNCTIONS.get(fnKey(fnRef));
  const nodes = data ? data.graph.nodes : [];
  const pins = new Map();
  for (const thread of openThreads()) {
    const hit = blueprintHits(thread, fnRef, nodes).map((n) => elements.get(n.id)).filter(Boolean);
    markThread(thread, thread.anchor.view === 'code' ? hit.slice(0, 1) : hit, pins);
  }
  for (const [node, threads] of pins) addPin(node, threads, open);
  if (PICK && PICK.kind === 'blueprint' && PICK.fn.path === fnRef.path && PICK.fn.sym === fnRef.sym) {
    for (const id of PICK.ids) markPicked(elements.get(id));
  }
}

export function clearDecorations(root) {
  root.querySelectorAll('.comment-pin').forEach((p) => p.remove());
  root.querySelectorAll('.picked, .in-thread').forEach((p) => p.classList.remove('picked', 'in-thread'));
}

export function paintCodeViews(container, open, onPick) {
  for (const view of container.querySelectorAll('.code-view')) {
    view.querySelectorAll('.cmark').forEach((m) => m.remove());
    const rows = [...view.querySelectorAll('.ln[data-line]')];
    rows.forEach(markPickedLine);
    const marks = new Map();
    for (const thread of openThreads()) {
      const row = threadRow(thread, rows);
      if (row) pinTo(marks, row, thread);
    }
    for (const [row, threads] of marks) row.append(threadButton('cmark', threads, open, '💬'));
    if (!view.dataset.selectable) { view.dataset.selectable = '1'; enableLineSelection(view, onPick); }
  }
}

function mapTargets(anchor) {
  if (anchor.view === 'map') return anchor.ids || [];
  if (anchor.view === 'blueprint' || (anchor.view === 'code' && anchor.qual)) {
    const sym = lookup({ path: anchor.path, sym: anchor.qual });
    const id = sym ? `${sym.kind !== 'function' ? 'cls' : sym.owner ? 'm' : 'fn'}:${anchor.path}:${anchor.qual}` : null;
    if (id && net().nodes.has(id)) return [id];
  }
  return [`mod:${anchor.path}`];
}

function shownBox(sceneEl, id) {
  const N = net();
  const chain = N.nodes.has(id) ? N.chain(id) : [];
  return [...chain].reverse().map((n) => sceneEl.querySelector(`.nb[data-id="${CSS.escape(n.id)}"]`)).find(Boolean);
}

function blueprintHits(thread, fnRef, nodes) {
  const a = thread.anchor;
  if (a.view === 'blueprint' && a.path === fnRef.path && a.qual === fnRef.sym) {
    const wanted = a.nodes || [];
    return nodes.filter((n) => wanted.some((w) => sameNode(w, n)));
  }
  if (a.view === 'code' && a.path === fnRef.path) {
    const r = codeRange(thread);
    return nodes.filter((n) => n.kind !== 'entry' && n.line >= r.start && n.line <= r.end);
  }
  return [];
}

function sameNode(wanted, node) {
  if (wanted.id === node.id && (!wanted.title || wanted.title === node.title || node.kind === 'entry')) return true;
  return Boolean(wanted.title && wanted.title === node.title && wanted.line === node.line);
}

function markThread(thread, targets, pins) {
  if (CARD && CARD.id === thread.id) targets.forEach((e) => e.classList.add('in-thread'));
  if (targets.length) pinTo(pins, targets[0], thread);
}

function markPicked(element) {
  if (element) element.classList.add('picked');
}

function pinTo(pins, holder, thread) {
  if (!pins.has(holder)) pins.set(holder, []);
  pins.get(holder).push(thread);
}

function addPin(holder, threads, open) {
  holder.append(threadButton('comment-pin', threads, open, '💬', threads.length > 1 ? String(threads.length) : null));
}

function threadButton(kind, threads, open, ...content) {
  return el('button', { class: kind, 'data-threads': threads.map((t) => t.id).join(' '), title: threads.map((t) => `${t.id}: ${t.messages[0].body.slice(0, 80)}`).join('\n'), onclick: (e) => { e.stopPropagation(); open(threads[0].id); } }, ...content);
}

function threadRow(thread, rows) {
  const at = codeRange(thread);
  if (!at) return null;
  const same = rows.filter((row) => row.dataset.path === at.path);
  return same.find((r) => lineOf(r) >= at.start && lineOf(r) <= at.end) || foldedAbove(same, at.start);
}

function foldedAbove(rows, start) {
  const coveredBelow = (r) => rows.some((n) => lineOf(n) > lineOf(r) && lineOf(n) <= start);
  return [...rows].reverse().find((r) => lineOf(r) < start && r.querySelector('.fold-chip') && !coveredBelow(r));
}

function lineOf(row) {
  return Number(row.dataset.line);
}

function markPickedLine(row) {
  const line = lineOf(row);
  row.classList.toggle('line-picked', Boolean(PICK && PICK.kind === 'code' && PICK.path === row.dataset.path && line >= PICK.start && line <= PICK.end));
}

function enableLineSelection(view, onPick) {
  view.addEventListener('click', (e) => { if (e.target.closest('.no')) e.stopPropagation(); }, true);
  view.addEventListener('mousedown', (e) => {
    const row = rowIn(view, e.target);
    if (!row || !e.target.closest('.no') || e.button !== 0) return;
    e.preventDefault();
    pickLines(view, row, e.shiftKey, onPick);
  });
}

function rowIn(view, target) {
  const row = target && target.closest && target.closest('.ln[data-line]');
  return row && view.contains(row) ? row : null;
}

function pickLines(view, row, extend, onPick) {
  const path = row.dataset.path, qual = row.dataset.qual || null, line = lineOf(row);
  const from = extend && PICK && PICK.kind === 'code' && PICK.path === path ? PICK.start : line;
  setCommentPick({ kind: 'code', path, qual, start: Math.min(from, line), end: Math.max(from, line) });
  view.querySelectorAll('.ln[data-line]').forEach(markPickedLine);
  const move = (ev) => {
    const over = rowIn(view, document.elementFromPoint(ev.clientX, ev.clientY));
    if (!over || over.dataset.path !== path) return;
    const to = lineOf(over);
    setCommentPick({ ...PICK, start: Math.min(from, to), end: Math.max(from, to) });
    view.querySelectorAll('.ln[data-line]').forEach(markPickedLine);
  };
  const up = () => {
    document.removeEventListener('mousemove', move);
    document.removeEventListener('mouseup', up);
    capturePickedText(view, path);
    onPick();
  };
  document.addEventListener('mousemove', move);
  document.addEventListener('mouseup', up);
}

function capturePickedText(view, path) {
  const picked = [...view.querySelectorAll('.ln[data-line]')].filter((r) => r.dataset.path === path && lineOf(r) >= PICK.start && lineOf(r) <= PICK.end);
  const numbers = picked.map(lineOf);
  const contiguous = numbers.length === PICK.end - PICK.start + 1 && numbers.every((n, i) => n === PICK.start + i);
  if (contiguous) PICK.text = picked.map((r) => (r.querySelector('.tx') || r).textContent).join('\n');
}
