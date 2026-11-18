import { KIND } from './nodes.js';
import { DIFF, isTestPath, lookup } from '../core/data.js';
import { baseName, el, speak } from '../core/dom.js';
import { codePainter } from '../core/highlight.js';
import { callersOf } from '../core/project.js';
import { DIFF_SIGN, DIFF_WORD, refOf } from '../map/boxes.js';
const DESCRIPTIONS = new Map([
  ['entry', (n, ins, outs) => `The function starts here. It takes ${outs.join(', ') || 'nothing'}.`],
  ['break', (n, ins, outs) => `Reads ${outs.join(', ')} out of ${ins[0]}.`],
  ['make', (n, ins) => `Builds a new ${n.title.slice(5)} from ${ins.join(', ')}.`],
  ['select', (n, ins) => (n.ins.length > 3 ? `Picks one value depending on ${ins[0]}: ${ins.slice(1).join(', ')}. ${n.note || ''}` : 'Gives back "if true" when the condition holds, otherwise "if false". This is how an if-and-return shows up as dataflow.')],
  ['branch', () => 'Decides which way the white execution line goes next: True or False.'],
  ['return', (n, ins) => `Gives back ${ins.length ? n.ins[0].type.label : 'nothing'} to whoever called this function.`],
  ['expr', (n) => `${n.title} works out ${n.expr.join(' ')} from ${n.ins.map((p) => p.name).join(', ') || 'fixed values'}.`],
  ['op', (n) => `${n.title}: works out a ${n.outs[0] ? n.outs[0].type.label : 'value'} from its inputs.`],
  ['lit', (n) => `The fixed value ${n.title}.`],
  ['var', (n) => `Reads ${n.title}, which is defined at module level.`],
  ['set', (n) => `Stores a value as ${n.title.slice(4)}, so other methods can use it later.`],
  ['raise', (n) => `Stops with an error. ${n.note || ''}`],
]);
function describe(n) {
  const ins = n.ins.map((p) => p.name).filter(Boolean);
  const outs = n.outs.map((o) => o.name).filter(Boolean);
  return (DESCRIPTIONS.get(n.kind) || describeCall)(n, ins, outs);
}
function describeCall(n, ins, outs) {
  return `Calls ${n.title}${ins.length ? ` with ${ins.join(', ')}` : ''}${outs.length ? `, giving ${outs.join(', ')}` : ''}.${n.note ? ' ' + n.note + '.' : ''}`;
}
export function codePanel(container, sym, node, ctx) {
  container.querySelectorAll(':scope > :not(.resize-bar)').forEach((c) => c.remove());
  const panel = el('div', { class: 'code-panel' });
  container.append(panel);
  const ex = el('div', { class: 'explain' });
  panel.append(ex);
  if (!sym) { ex.append(el('div', { class: 'kind' }, 'Code'), el('p', {}, 'Click a node to see its line of code. Press ⧉ on a call (or double-click it) to unfold its code right there. Press Go into on an unfolded frame to make it the whole view; ← takes you back with everything still unfolded.')); return; }
  if (node) explainNode(ex, sym, node, ctx); else explainSymbol(ex, sym, ctx);
  const codeRows = sym.codeLines || (sym.code ? sym.code.split('\n').map((t, i) => [sym.line + i, t]) : null);
  if (codeRows) panel.append(codeView(sym, node, codeRows));
}
function explainNode(ex, sym, node, ctx) {
  ex.append(el('div', { class: 'kind' }, KIND[node.kind] ? KIND[node.kind][1] : 'Node'), el('h2', {}, node.kind === 'entry' ? sym.name : node.title));
  const text = describe(node);
  ex.append(el('p', {}, text));
  const acts = el('div', { class: 'actions' }, el('button', { class: 'btn small', onclick: () => speak(text) }, '🔊 Read aloud'));
  if (node.target && lookup(node.target) && node.kind !== 'entry') acts.append(el('button', { class: 'btn small', onclick: () => ctx.activate(node.target, null, null) }, node.target.path === sym.file ? 'Go into it' : `Go into it (${baseName(node.target.path)})`));
  ex.append(acts);
}
function explainSymbol(ex, sym, ctx) {
  ex.append(el('div', { class: 'kind' }, symbolKindLabel(sym)), el('h2', {}, sym.qual));
  if (sym.kind !== 'function') return;
  const callers = callersOf(refOf(sym));
  callers.sort((a, b) => Number(isTestPath(a.path)) - Number(isTestPath(b.path)) || a.path.localeCompare(b.path) || a.sym.localeCompare(b.sym));
  const shown = callers.slice(0, 8);
  if (callers.length) ex.append(el('div', { class: 'kind' }, 'Called from'), el('div', { class: 'links' }, shown.map((c) => el('button', { onclick: () => ctx.activate(c, null, null) }, `${c.sym} · ${baseName(c.path)}`)), callers.length > shown.length ? el('span', { class: 'udim' }, `and ${callers.length - shown.length} more`) : null));
}
function symbolKindLabel(sym) {
  if (sym.kind === 'function') return sym.owner ? `method of ${sym.owner}` : 'function';
  return sym.kind === 'enum' ? 'enum' : 'class';
}
function codeView(sym, node, codeRows) {
  const cv = el('div', { class: 'code-view' });
  const removed = Boolean(node && node.diff === 'removed');
  const target = removed ? node.baseLine : node ? node.line : null;
  const paint = codePainter(null, sym.file);
  codeRows.forEach(([no, ln, change]) => {
    const hit = target && no === target && node.kind !== 'entry' && (change === 'removed') === removed;
    cv.append(codeLineEl(sym, no, ln, change, hit, paint));
  });
  const hl = cv.querySelector('.hl'); if (hl) requestAnimationFrame(() => hl.scrollIntoView({ block: 'nearest' }));
  return cv;
}
function codeLineEl(sym, no, ln, change, hit, paint) {
  return el('div', { class: `ln ${hit ? 'hl' : ''} ${change ? `diff-${change}` : ''}`, title: change ? DIFF_WORD[change] : null, 'data-path': change === 'removed' ? null : sym.file, 'data-line': change === 'removed' ? null : no, 'data-qual': sym.kind === 'function' ? sym.qual : null }, el('span', { class: 'no' }, no), DIFF ? el('span', { class: 'sign' }, change ? DIFF_SIGN[change] : '') : null, el('span', { class: 'tx' }, change === 'removed' || !ln ? ln || ' ' : paint(ln, no)));
}
