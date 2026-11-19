import { framedLayout } from './frames.js';
import { Scene, plain } from '../canvas/scene.js';
import { DIFF, FUNCTIONS, fnKey, lookup } from '../core/data.js';
import { el } from '../core/dom.js';
import { codePainter } from '../core/highlight.js';
import { symbolDiff } from '../core/review.js';
import { settings } from '../core/settings.js';
import { DIFF_WORD, diffBadge, refOf, shortType } from '../map/boxes.js';
function freshGraph(fnSym) {
  const data = FUNCTIONS.get(fnKey(refOf(fnSym)));
  const graph = data ? data.graph : { nodes: [{ id: 'entry', kind: 'entry', title: fnSym.name, line: fnSym.line, ins: [], outs: [] }], edges: [], exec: [] };
  const byId = new Map();
  const nodes = graph.nodes.map((n) => { const node = { ...n, ins: n.ins || [], outs: n.outs || [] }; byId.set(n.id, node); return node; });
  const edges = [];
  for (const e of graph.edges || []) {
    const from = byId.get(e.from), to = byId.get(e.to);
    if (!from || !to) continue;
    const pin = from.outs.find((o) => o.name === e.fp);
    edges.push({ from, fp: e.fp, to, tp: e.tp, type: pin ? pin.type : { label: 'Any', cat: 'any' }, cell: Boolean(pin && pin.cell), diff: e.diff });
  }
  const exec = [];
  for (const e of graph.exec || []) { const from = byId.get(e.from), to = byId.get(e.to); if (from && to) exec.push({ from, fp: e.fp, to, diff: e.diff }); }
  return { nodes, edges, exec };
}
export function shapeSVG(tp, connected = true, cell = false) {
  if (!tp) return `<svg viewBox="0 0 12 12"><path d="M1.5 1.5h5l4 4.5-4 4.5h-5z" style="fill:${connected ? 'var(--exec)' : 'none'};stroke:var(--exec)" stroke-width="1.4" stroke-linejoin="round"/></svg>`;
  const c = `var(--t-${tp.cat})`;
  if (cell) return `<svg viewBox="0 0 12 12"><rect x="1.2" y="1.2" width="9.6" height="9.6" rx="1.5" style="fill:none;stroke:${c}" stroke-width="1.6"/><rect x="4" y="4" width="4" height="4" style="fill:${connected ? c : 'none'};stroke:${c}" stroke-width="1"/></svg>`;
  return `<svg viewBox="0 0 12 12"><circle cx="6" cy="6" r="4.2" style="fill:${connected ? c : 'none'};stroke:${c}" stroke-width="1.8"/></svg>`;
}
function pinEl(side, key, name, tp, opts = {}) {
  const shape = el('span', { class: 'shape', html: shapeSVG(tp, opts.connected !== false, opts.cell) });
  const label = name ? el('span', { class: 'pname' }, opts.raw ? name : plain(name)) : null;
  const typeLabel = tp && (settings.types || opts.showType) ? el('span', { class: 'ptype' }, shortType(tp.label)) : null;
  const lit = opts.lit != null ? el('span', { class: 'lit', style: `color:var(--t-${tp ? tp.cat : 'any'})` }, opts.lit) : null;
  const tip = tp ? `${name || 'value'}: ${opts.cell ? 'the variable itself, ' : ''}${tp.label}` : 'execution order';
  return el('div', { class: `pin${opts.diff ? ` pin-${opts.diff}` : ''}`, 'data-pin': key, title: opts.diff ? `${tip} (${DIFF_WORD[opts.diff]})` : tip }, ...(side === 'in' ? [shape, label, lit, typeLabel] : [typeLabel, label, shape]));
}
export const OPEN_ICON = '<svg width="11" height="11" viewBox="0 0 12 12"><rect x="1" y="3.5" width="7.5" height="7.5" rx="1" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M4 1h7v7" fill="none" stroke="currentColor" stroke-width="1.3"/></svg>';
export const KIND = {
  loop: ['--h-branch', 'Loop'], entry: ['--h-entry', 'Start of the function'], break: ['--h-break', 'Read fields'], make: ['--h-make', 'Build a value'], call: ['--h-call', 'Call a function in this project'],
  method: ['--h-method', 'Call a method'], ext: ['--h-ext', 'Library call'], op: ['--h-op', 'Operator'], expr: ['--h-op', 'Work out a value'], lit: ['--h-lit', 'Fixed value'], var: ['--h-var', 'Module variable'],
  select: ['--h-select', 'Pick one value'], branch: ['--h-branch', 'Branch'], return: ['--h-return', 'Give back'], raise: ['--h-raise', 'Raise an error'], set: ['--h-set', 'Store a value'],
  get: ['--h-var', 'Read a variable now'], closure: ['--h-closure', 'A function made here'],
};
function targetChanged(n) {
  if (!DIFF || !n.target || n.kind === 'entry') return false;
  const sym = lookup(n.target);
  if (!sym || sym.kind === 'function') return Boolean(symbolDiff(n.target));
  const pins = n.kind === 'break' ? n.outs : n.ins;
  return pins.some((pin) => DIFF.status[`f:${n.target.path}:${n.target.sym}.${pin.name.split('.')[0]}`]);
}
function expressionEl(n, path) { return codeBlockEl(n.expr, n.ins, path); }
function codeBlockEl(lines, ins, path) {
  const names = ins.map((pin) => pin.name).sort((a, b) => b.length - a.length);
  const colours = new Map(ins.map((pin) => [pin.name, `var(--t-${pin.type ? pin.type.cat : 'any'})`]));
  const pattern = names.length ? new RegExp(`(?<![\\w.])(${names.map((name) => name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})(?![\\w(])`, 'y') : null;
  const input = (text, at) => {
    if (!pattern) return null;
    pattern.lastIndex = at;
    const match = pattern.exec(text);
    return match ? { end: at + match[1].length, node: el('span', { class: 'expr-input', style: `color:${colours.get(match[1])}` }, match[1]) } : null;
  };
  const paint = codePainter(input, path);
  return el('div', { class: 'expr' }, lines.map((line, i) => el('div', {}, ...paint(line, i))));
}
function closureEl(n, connectedOuts, state) {
  const [fn, ...parameters] = n.outs;
  const wrap = el('div', { class: `k-closure${state ? ` diff-${state}` : ''}`, 'data-node': n.id });
  const head = el('div', { class: 'head', style: '--hc: var(--h-closure)' }, diffBadge(state),
    el('span', { class: 'title' }, plain(n.title)),
    el('span', { class: 'tag' }, fn.type.label),
    pinEl('out', `out:${fn.name}`, fn.name, fn.type, { connected: connectedOuts.has(fn.name), diff: fn.diff }));
  const strip = el('div', { class: 'strip' });
  if ((n.execOuts || []).includes('start')) strip.append(pinEl('out', 'start', '', null));
  for (const p of parameters) strip.append(pinEl('out', `out:${p.name}`, p.name, p.type, { connected: connectedOuts.has(p.name), diff: p.diff }));
  wrap.append(el('div', { class: 'box closure-frame' }, head, strip));
  return wrap;
}
function nodeEl(n, ctx, connectedIns, connectedOuts, path) {
  const state = n.diff || (targetChanged(n) ? 'modified' : null);
  if (n.kind === 'closure') return closureEl(n, connectedOuts, state);
  const wrap = el('div', { class: `k-${n.kind}${state ? ` diff-${state}` : ''}`, 'data-node': n.id });
  const box = el('div', { class: 'box' });
  wrap.append(box);
  box.append(nodeHead(n, ctx, state));
  const [left, right] = nodePins(n, connectedIns, connectedOuts);
  if (n.expr) box.append(expressionEl(n, path));
  box.append(el('div', { class: 'rows' }, left, right));
  if (n.note) box.append(el('div', { class: 'note' }, n.note));
  if (n.code) box.append(codeBlockEl([n.code], n.ins, path));
  box.append(el('div', { class: 'embed-slot' }));
  return wrap;
}
const OPENABLE_KINDS = ['call', 'method', 'ext', 'var'];
function nodeHead(n, ctx, state) {
  const [hc] = KIND[n.kind] || KIND.ext;
  const target = n.target && lookup(n.target);
  const openable = target && target.kind === 'function' && OPENABLE_KINDS.includes(n.kind);
  return el('div', { class: 'head', style: `--hc: var(${hc})` }, diffBadge(state),
    el('span', { class: 'title' }, nodeTitle(n)),
    openable && ctx.openButton ? ctx.openButton(n) : null);
}
function nodeTitle(n) {
  if (n.kind !== 'break' && n.kind !== 'make') return plain(n.title);
  const [verb, ...rest] = n.title.split(' ');
  return `${verb} ${plain(rest.join(' '))}`;
}
function nodePins(n, connectedIns, connectedOuts) {
  const left = el('div', { class: 'col in' }), right = el('div', { class: 'col out' });
  if (n.execIn) left.append(pinEl('in', 'exec-in', '', null));
  if (n.execOut) right.append(pinEl('out', 'then', '', null));
  for (const label of n.execOuts || []) right.append(pinEl('out', label, label, null, { raw: true }));
  for (const p of n.ins) left.append(pinEl('in', `in:${p.name}`, p.name, p.type, { lit: p.lit, connected: connectedIns.has(p.name) || p.lit != null, diff: p.diff, cell: p.cell }));
  for (const o of n.outs) right.append(pinEl('out', `out:${o.name}`, o.name, o.type, { connected: connectedOuts.has(o.name), diff: o.diff, cell: o.cell }));
  return [left, right];
}
export function buildFunctionScene(fnSym, ctx) {
  const g = freshGraph(fnSym);
  const scene = new Scene(ctx);
  const byId = new Map();
  const conIn = connectedPins(g.edges, (e) => e.to, (e) => e.tp);
  const conOut = connectedPins(g.edges, (e) => e.from, (e) => e.fp);
  for (const n of g.nodes) {
    const v = scene.add(nodeEl(n, ctx, conIn.get(n) || new Set(), conOut.get(n) || new Set(), fnSym.file), n);
    listenToNode(scene, v, n, fnSym, ctx);
    byId.set(n, v);
    if (ctx.afterNode) ctx.afterNode(n, v);
  }
  const doc = fnSym.doc ? scene.add(el('div', { class: 'doc-note' }, fnSym.doc)) : null;
  scene.measure();
  for (const v of byId.values()) if (v.data.kind === 'closure') { v.headW = v.w; v.headH = v.h; }
  const { routes, dummies, routeKey } = framedLayout(g, byId, (v) => scene.measureNode(v));
  scene.dummies = dummies;
  for (const e of g.edges) Object.assign(scene.wire(byId.get(e.from), `out:${e.fp}`, byId.get(e.to), `in:${e.tp}`, e.cell ? 'cell' : null, e.type), { via: routes.get(routeKey(e)), diff: e.diff });
  for (const e of g.exec) Object.assign(scene.wire(byId.get(e.from), e.fp, byId.get(e.to), 'exec-in', 'exec'), { via: routes.get(routeKey(e)), diff: e.diff });
  if (doc) { const entry = byId.get(g.nodes[0]); doc.x = entry.x; doc.y = Math.min(...[...byId.values()].map((v) => v.y)) - doc.h - 20; }
  scene.finish();
  return scene;
}
function connectedPins(edges, nodeOf, pinOf) {
  const connected = new Map();
  for (const e of edges) {
    if (!connected.has(nodeOf(e))) connected.set(nodeOf(e), new Set());
    connected.get(nodeOf(e)).add(pinOf(e));
  }
  return connected;
}
function listenToNode(scene, v, n, fnSym, ctx) {
  v.el.addEventListener('click', (ev) => { if (ev.target.closest('button')) return; ev.stopPropagation(); ctx.select(n, v, fnSym); });
  v.el.addEventListener('dblclick', (ev) => { ev.stopPropagation(); if (n.target && lookup(n.target) && n.kind !== 'entry') ctx.activate(n.target, n, v); });
  v.el.addEventListener('mouseenter', () => scene.hover(v, true));
  v.el.addEventListener('mouseleave', () => scene.hover(v, false));
}
