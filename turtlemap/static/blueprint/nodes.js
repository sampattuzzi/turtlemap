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
  if (cell) return `<svg viewBox="0 0 12 12"><rect x="1.6" y="1.6" width="8.8" height="8.8" rx="1.6" style="fill:none;stroke:color-mix(in srgb, ${c} 55%, #5f646d)" stroke-width="1.8"/></svg>`;
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
  loop: ['--h-loop', 'Loop'], entry: ['--h-entry', 'Start of the function'], break: ['--h-break', 'Read fields'], make: ['--h-make', 'Build a value'], call: ['--h-call', 'Call a function in this project'],
  method: ['--h-method', 'Call a method'], ext: ['--h-ext', 'Library call'], op: ['--h-op', 'Operator'], lit: ['--h-lit', 'Fixed value'], var: ['--h-var', 'Module variable'],
  select: ['--h-select', 'Pick one value'], branch: ['--h-branch', 'Branch'], return: ['--h-return', 'Give back'], raise: ['--h-raise', 'Raise an error'], set: ['--h-set', 'Store a value'],
  get: ['--h-var', 'Read a variable now'], closure: ['--h-closure', 'A function made here'],
  lane: ['--h-lane', 'One way through the branch'], jump: ['--h-raise', 'Leave this pass of the loop'],
  comprehension: ['--h-loop', 'Builds a collection, one element at a time'], collect: ['--h-loop', 'What each element gives back'],
};
const FRAME_KINDS = new Set(['closure', 'loop', 'branch', 'lane', 'comprehension']);
export const isFrame = (n) => FRAME_KINDS.has(n.kind);
function targetChanged(n) {
  if (!DIFF || !n.target || n.kind === 'entry') return false;
  const sym = lookup(n.target);
  if (!sym || sym.kind === 'function') return Boolean(symbolDiff(n.target));
  const pins = n.kind === 'break' ? n.outs : n.ins;
  return pins.some((pin) => DIFF.status[`f:${n.target.path}:${n.target.sym}.${pin.name.split('.')[0]}`]);
}
function codeBlockEl(lines, ins, path, pins = null) {
  const names = ins.map((pin) => pin.name).sort((a, b) => b.length - a.length);
  const colours = new Map(ins.map((pin) => [pin.name, `var(--t-${pin.type ? pin.type.cat : 'any'})`]));
  const pattern = names.length ? new RegExp(`(?<![\\w.])(${names.map((name) => name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})(?![\\w(])`, 'y') : null;
  const input = (text, at) => {
    if (!pattern) return null;
    pattern.lastIndex = at;
    const match = pattern.exec(text);
    if (!match) return null;
    const name = match[1], word = el('span', { class: 'expr-input', style: `color:${colours.get(name)}` }, name);
    if (!pins || pins.used.has(name)) return { end: at + name.length, node: word };
    pins.used.add(name);
    const pin = ins.find((p) => p.name === name);
    const shape = el('span', { class: 'shape', html: shapeSVG(pin.type, pins.connected.has(name), pin.cell) });
    return { end: at + name.length, node: el('span', { class: 'expr-pin', 'data-pin': `in:${name}`, title: `${name}: ${pin.type.label}` }, shape, word) };
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
function comprehensionEl(n, connectedIns, connectedOuts, state) {
  const [result, ...elements] = n.outs;
  const wrap = el('div', { class: `k-frame k-comprehension${state ? ` diff-${state}` : ''}`, 'data-node': n.id });
  const head = el('div', { class: 'head', style: '--hc: var(--h-loop)' }, diffBadge(state),
    n.execIn ? pinEl('in', 'exec-in', '', null) : null,
    n.ins.map((p) => pinEl('in', `in:${p.name}`, p.name, p.type, { lit: p.lit, connected: connectedIns.has(p.name) || p.lit != null, diff: p.diff })),
    n.badge ? el('span', { class: 'badge' }, n.badge) : null,
    el('span', { class: 'title' }, plain(n.title)),
    el('span', { class: 'grow' }));
  const resultPins = [el('span', { class: 'tag' }, result.type.label), pinEl('out', `out:${result.name}`, result.name, result.type, { connected: connectedOuts.has(result.name), diff: result.diff })];
  const strip = el('div', { class: 'strip' });
  if ((n.execOuts || []).includes('start')) strip.append(pinEl('out', 'start', '', null));
  strip.append(...elements.map((o) => pinEl('out', `out:${o.name}`, o.name, o.type, { connected: connectedOuts.has(o.name), diff: o.diff })));
  if (n.execOut) {
    head.append(el('span', { class: 'then' }, 'then'), pinEl('out', 'then', '', null));
    strip.append(el('span', { class: 'grow' }), ...resultPins);
  } else head.append(...resultPins);
  wrap.append(el('div', { class: 'box frame-box' }, head, strip));
  return wrap;
}
function collectEl(n, connectedIns, state) {
  const pins = el('div', { class: 'col in' }, n.ins.map((p) => pinEl('in', `in:${p.name}`, p.name, p.type, { lit: p.lit, connected: connectedIns.has(p.name) || p.lit != null, diff: p.diff })));
  return el('div', { class: `k-collect${state ? ` diff-${state}` : ''}`, 'data-node': n.id, title: KIND.collect[1] }, el('div', { class: 'box band' }, pins));
}
function frameEl(n, connectedIns, connectedOuts, state, path) {
  const wrap = el('div', { class: `k-frame k-${n.kind}${state ? ` diff-${state}` : ''}`, 'data-node': n.id });
  const head = el('div', { class: 'head', style: `--hc: var(${KIND[n.kind][0]})` }, diffBadge(state));
  if (n.kind === 'lane') head.append(pinEl('out', 'start', '', null));
  else if (n.execIn) head.append(pinEl('in', 'exec-in', '', null));
  const pins = { used: new Set(), connected: connectedIns };
  const condition = n.expr ? codeBlockEl(n.expr, n.ins, path, pins) : null;
  for (const p of n.ins) if (!pins.used.has(p.name)) head.append(pinEl('in', `in:${p.name}`, p.name, p.type, { lit: p.lit, connected: connectedIns.has(p.name) || p.lit != null, diff: p.diff, cell: p.cell }));
  head.append(el('span', { class: 'title' }, plain(n.title)));
  if (condition) head.append(condition);
  if (n.kind !== 'lane') head.append(el('span', { class: 'grow' }), n.execOut ? el('span', { class: 'then' }, 'then') : null, n.execOut ? pinEl('out', 'then', '', null) : null);
  const box = el('div', { class: 'box frame-box' }, head);
  const starts = n.kind === 'loop' && (n.execOuts || []).includes('start');
  if (starts || (n.kind !== 'branch' && n.outs.length)) {
    const strip = el('div', { class: 'strip' });
    if (starts) strip.append(pinEl('out', 'start', '', null));
    for (const o of n.outs) strip.append(pinEl('out', `out:${o.name}`, o.name, o.type, { connected: connectedOuts.has(o.name), diff: o.diff }));
    box.append(strip);
  }
  wrap.append(box);
  return wrap;
}
function nodeEl(n, ctx, sources, connectedOuts, path) {
  const state = n.diff || (targetChanged(n) ? 'modified' : null);
  const connectedIns = new Set(sources.keys());
  if (n.kind === 'closure') return closureEl(n, connectedOuts, state);
  if (n.kind === 'comprehension') return comprehensionEl(n, connectedIns, connectedOuts, state);
  if (n.kind === 'collect') return collectEl(n, connectedIns, state);
  if (isFrame(n)) return frameEl(n, connectedIns, connectedOuts, state, path);
  const [hc, about] = KIND[n.kind] || KIND.ext;
  const runs = n.execIn || n.execOut || (n.execOuts || []).length > 0;
  const wrap = el('div', { class: `k-${n.kind}${state ? ` diff-${state}` : ''}`, 'data-node': n.id, title: `${about}: ${n.title}` });
  const box = el('div', { class: `box syn${runs ? '' : ' pure'}`, style: `--hc: var(${hc})` });
  wrap.append(box);
  if (runs) box.append(execBar(n));
  if (n.code) box.append(codeBlockEl([n.code], n.ins, path));
  const paint = codePainter(null, path);
  const rows = el('div', { class: 'syn-rows' }, syntaxOf(n).map((row) => syntaxRow(row, n, sources, connectedOuts, paint)));
  const extras = [diffBadge(state), openButton(n, ctx)].filter(Boolean);
  if (extras.length) rows.firstChild.querySelector(':scope > .grow').after(...extras);
  box.append(rows);
  if (n.note) box.append(el('div', { class: 'note' }, n.note));
  box.append(el('div', { class: 'embed-slot' }));
  return wrap;
}
const OPENABLE_KINDS = ['call', 'method', 'ext', 'var'];
function openButton(n, ctx) {
  const target = n.target && lookup(n.target);
  const openable = target && target.kind === 'function' && OPENABLE_KINDS.includes(n.kind);
  return openable && ctx.openButton ? ctx.openButton(n) : null;
}
function execBar(n) {
  const outs = [n.execOut ? pinEl('out', 'then', '', null) : null, ...(n.execOuts || []).map((label) => pinEl('out', label, label, null, { raw: true }))];
  return el('div', { class: 'syn-bar' }, n.execIn ? pinEl('in', 'exec-in', '', null) : null, el('span', { class: 'grow' }), ...outs);
}
function syntaxOf(n) {
  if (n.syntax) return n.syntax;
  return [[['text', n.title]], ...n.ins.map((p) => [['in', p.name]]), ...n.outs.map((o) => (o.name ? [['text', `→ ${o.name}`], ['out', o.name]] : [['out', '']]))];
}
function syntaxRow(row, n, sources, connectedOuts, paint) {
  const gutter = el('span', { class: 'syn-gutter' }), parts = [], outs = [];
  for (const [kind, value] of row) {
    if (kind === 'text') parts.push(el('span', { class: 'syn-text' }, ...paint(value, null)));
    else if (kind === 'out') outs.push(syntaxOutput(n.outs.find((o) => o.name === value), connectedOuts));
    else {
      const pin = n.ins.find((p) => p.name === value);
      if (!pin) continue;
      const [socket, label] = syntaxInput(pin, sources.get(value));
      if (socket) gutter.append(socket);
      parts.push(label);
    }
  }
  return el('div', { class: 'syn-row' }, gutter, ...parts, el('span', { class: 'grow' }), ...outs);
}
function syntaxInput(p, source) {
  const tip = `${p.name}: ${p.cell ? 'the variable itself, ' : ''}${p.type.label}`;
  if (p.lit != null) return [null, el('span', { class: 'lit', title: tip, style: `color:var(--t-${p.type.cat})` }, p.lit)];
  const socket = el('span', { class: `pin syn-socket${p.diff ? ` pin-${p.diff}` : ''}`, 'data-pin': `in:${p.name}`, title: tip },
    el('span', { class: 'shape', html: shapeSVG(p.type, Boolean(source), p.cell) }));
  const label = source ? source.label : p.name;
  return [socket, label ? el('span', { class: `syn-label${source ? '' : ' unset'}`, title: tip }, label) : null];
}
function syntaxOutput(o, connectedOuts) {
  if (!o) return null;
  return pinEl('out', `out:${o.name}`, '', o.type, { connected: connectedOuts.has(o.name), diff: o.diff, cell: o.cell });
}
export function buildFunctionScene(fnSym, ctx) {
  const g = freshGraph(fnSym);
  const scene = new Scene(ctx);
  scene.fnSym = fnSym;
  const byId = new Map();
  const sources = inputSources(g.edges);
  const conOut = connectedPins(g.edges, (e) => e.from, (e) => e.fp);
  for (const n of g.nodes) {
    const v = scene.add(nodeEl(n, ctx, sources.get(n) || new Map(), conOut.get(n) || new Set(), fnSym.file), n);
    listenToNode(scene, v, n, fnSym, ctx);
    byId.set(n, v);
    if (ctx.afterNode) ctx.afterNode(n, v);
  }
  const doc = fnSym.doc ? scene.add(el('div', { class: 'doc-note' }, fnSym.doc)) : null;
  scene.measure();
  for (const v of byId.values()) if (isFrame(v.data)) { v.headW = v.w; v.headH = v.h; }
  const { routes, dummies, routeKey } = framedLayout(g, byId, (v) => scene.measureNode(v));
  scene.dummies = dummies;
  for (const e of g.edges) Object.assign(scene.wire(byId.get(e.from), `out:${e.fp}`, byId.get(e.to), `in:${e.tp}`, e.cell ? 'cell' : null, e.type), { via: routes.get(routeKey(e)), diff: e.diff });
  for (const e of g.exec) Object.assign(scene.wire(byId.get(e.from), e.fp, byId.get(e.to), 'exec-in', 'exec'), { via: routes.get(routeKey(e)), diff: e.diff });
  if (doc) { const entry = byId.get(g.nodes[0]); doc.x = entry.x; doc.y = Math.min(...[...byId.values()].map((v) => v.y)) - doc.h - 20; }
  scene.finish();
  scene.crumbs = (view) => crumbsAt(scene, view);
  return scene;
}
function crumbsAt(scene, view) {
  const x = view.x + view.w / 2, y = view.y + view.h / 2;
  const around = scene.nodes.filter((v) => ['loop', 'lane', 'closure', 'comprehension'].includes(v.data.kind) && x >= v.x && x <= v.x + v.w && y >= v.y && y <= v.y + v.h).sort((a, b) => b.w * b.h - a.w * a.h);
  const inner = around[around.length - 1];
  if (!inner || (inner.y >= view.y && inner.x >= view.x)) return null;
  return around.map((v) => el('div', { class: `crumb-line crumb-${v.data.kind}` }, v.data.kind === 'loop' || v.data.kind === 'comprehension' ? '↻ ' : v.data.kind === 'lane' ? '↳ ' : 'ƒ ', plain(v.data.reach || v.data.title)));
}
function inputSources(edges) {
  const found = new Map();
  for (const e of edges) {
    if (!found.has(e.to)) found.set(e.to, new Map());
    found.get(e.to).set(e.tp, { label: sourceLabel(e) });
  }
  return found;
}
function sourceLabel(e) {
  if (e.fp) return e.fp;
  if (e.from.kind === 'var' || e.from.kind === 'get') return e.from.title;
  return '';
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
