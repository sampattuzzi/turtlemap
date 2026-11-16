const QUERY = new URLSearchParams(location.search);
const TOKEN = QUERY.get('t') || '';
async function api(path) {
  const response = await fetch(path, { headers: { 'X-Blueprints-Token': TOKEN } });
  let body = null;
  try { body = await response.json(); } catch (e) { body = null; }
  if (!response.ok) throw new Error((body && body.error) || `${response.status} ${response.statusText}`);
  return body;
}
let OVERVIEW = null;
let FILES = {};
let CALLERS = null;
const FUNCTIONS = new Map();
const FUNCTION_REQUESTS = new Map();
const OUTLINES = {};
const OUTLINE_REQUESTS = new Map();
const fnKey = (ref) => `${ref.path}::${ref.sym}`;
function loadOverview(data) {
  OVERVIEW = data;
  FILES = {};
  CALLERS = null;
  NET_CACHE = null;
  FUNCTIONS.clear();
  FUNCTION_REQUESTS.clear();
  for (const key of Object.keys(OUTLINES)) delete OUTLINES[key];
  for (const m of data.modules) {
    const f = { ...m, index: {} };
    for (const s of m.symbols) {
      s.file = m.path;
      f.index[s.qual] = s;
      for (const meth of s.methods || []) { meth.file = m.path; meth.owner = s.qual; meth.qual = `${s.qual}.${meth.name}`; f.index[meth.qual] = meth; }
    }
    FILES[m.path] = f;
  }
}
function ensureFunction(ref) {
  const key = fnKey(ref);
  if (FUNCTIONS.has(key)) return Promise.resolve(FUNCTIONS.get(key));
  if (!FUNCTION_REQUESTS.has(key)) {
    FUNCTION_REQUESTS.set(key, api(`/api/function?path=${encodeURIComponent(ref.path)}&qual=${encodeURIComponent(ref.sym)}`)
      .then((data) => { FUNCTIONS.set(key, data); const sym = lookup(ref); if (sym) sym.codeLines = data.code; return data; })
      .finally(() => FUNCTION_REQUESTS.delete(key)));
  }
  return FUNCTION_REQUESTS.get(key);
}
function ensureOutline(path) {
  if (OUTLINES[path]) return Promise.resolve(OUTLINES[path]);
  if (!OUTLINE_REQUESTS.has(path)) {
    OUTLINE_REQUESTS.set(path, api(`/api/outline?path=${encodeURIComponent(path)}`).then((data) => { OUTLINES[path] = data; return data; }).finally(() => OUTLINE_REQUESTS.delete(path)));
  }
  return OUTLINE_REQUESTS.get(path);
}
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
    edges.push({ from, fp: e.fp, to, tp: e.tp, type: pin ? pin.type : { label: 'Any', cat: 'any' } });
  }
  const exec = [];
  for (const e of graph.exec || []) { const from = byId.get(e.from), to = byId.get(e.to); if (from && to) exec.push({ from, fp: e.fp, to }); }
  return { nodes, edges, exec };
}
function lookup(ref) { if (!ref) return null; const f = FILES[ref.path]; return f ? f.index[ref.sym] || null : null; }
const refOf = (sym) => ({ path: sym.file, sym: sym.qual });
const baseName = (p) => p.split('/').pop();
const shortFile = (p) => p.split('/').slice(-2).join('/');
function callersOf(ref) {
  if (!CALLERS) {
    CALLERS = new Map();
    for (const e of net().edges) {
      if (!e.kinds.has('calls') || !/^(fn|m):/.test(e.from)) continue;
      if (!CALLERS.has(e.to)) CALLERS.set(e.to, []);
      CALLERS.get(e.to).push(e.from);
    }
  }
  const sym = lookup(ref);
  if (!sym) return [];
  return (CALLERS.get(`${sym.owner ? 'm' : 'fn'}:${ref.path}:${ref.sym}`) || []).map((id) => {
    const match = id.match(/^(?:fn|m):(.*):([^:]*)$/);
    return match ? { path: match[1], sym: match[2] } : null;
  }).filter(Boolean);
}


const SETTINGS_KEY = 'code-blueprints-settings';
const settings = Object.assign({ pinFont: 'mono', size: 12.5, theme: 'dark', plain: false, types: false }, (() => { try { return JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}'); } catch (e) { return {}; } })());
function saveSettings() { try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings)); } catch (e) {} }
function applySettings() {
  const root = document.documentElement;
  const fonts = { mono: '"JetBrains Mono", ui-monospace, monospace', lexend: '"Lexend", system-ui, sans-serif', atkinson: '"Atkinson Hyperlegible", system-ui, sans-serif', comic: '"Comic Neue", system-ui, sans-serif' };
  root.style.setProperty('--font-pin', fonts[settings.pinFont] || fonts.mono);
  root.style.setProperty('--font-head', settings.pinFont === 'mono' ? '"Inter", system-ui, sans-serif' : fonts[settings.pinFont]);
  root.style.setProperty('--node-size', `${settings.size}px`);
  root.style.setProperty('--tracking', settings.pinFont === 'mono' ? '0em' : '0.02em');
  if (settings.theme === 'system') root.removeAttribute('data-theme'); else root.setAttribute('data-theme', settings.theme);
}

function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') e.className = v; else if (k === 'html') e.innerHTML = v; else if (k === 'style') e.style.cssText = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v); else e.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat(Infinity)) { if (kid == null || kid === false) continue; e.append(kid.nodeType ? kid : document.createTextNode(String(kid))); }
  return e;
}
const SVGNS = 'http://www.w3.org/2000/svg';
function svg(tag, attrs = {}) { const e = document.createElementNS(SVGNS, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); return e; }
function plain(name) {
  if (!settings.plain || !name) return name;
  if (name === '__init__') return 'set up';
  return name.replace(/\bself\./g, '').replace(/(^|[.\s])_+/g, '$1').replace(/_+/g, ' ').replace(/\./g, ' › ');
}

function shapeSVG(tp, connected = true) {
  if (!tp) return `<svg viewBox="0 0 12 12"><path d="M1.5 1.5h5l4 4.5-4 4.5h-5z" style="fill:${connected ? 'var(--exec)' : 'none'};stroke:var(--exec)" stroke-width="1.4" stroke-linejoin="round"/></svg>`;
  const c = `var(--t-${tp.cat})`;
  return `<svg viewBox="0 0 12 12"><circle cx="6" cy="6" r="4.2" style="fill:${connected ? c : 'none'};stroke:${c}" stroke-width="1.8"/></svg>`;
}
function pinEl(side, key, name, tp, opts = {}) {
  const shape = el('span', { class: 'shape', html: shapeSVG(tp, opts.connected !== false) });
  const label = name ? el('span', { class: 'pname' }, opts.raw ? name : plain(name)) : null;
  const typeLabel = tp && (settings.types || opts.showType) ? el('span', { class: 'ptype' }, tp.label) : null;
  const lit = opts.lit != null ? el('span', { class: 'lit', style: `color:var(--t-${tp ? tp.cat : 'any'})` }, opts.lit) : null;
  const tip = tp ? `${name || 'value'}: ${tp.label}` : 'execution order';
  return el('div', { class: 'pin', 'data-pin': key, title: tip }, ...(side === 'in' ? [shape, label, lit, typeLabel] : [typeLabel, label, shape]));
}
const OPEN_ICON = '<svg width="11" height="11" viewBox="0 0 12 12"><rect x="1" y="3.5" width="7.5" height="7.5" rx="1" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M4 1h7v7" fill="none" stroke="currentColor" stroke-width="1.3"/></svg>';

const KIND = {
  loop: ['--h-branch', 'Loop'], entry: ['--h-entry', 'Start of the function'], break: ['--h-break', 'Read fields'], make: ['--h-make', 'Build a value'], call: ['--h-call', 'Call a function in this project'],
  method: ['--h-method', 'Call a method'], ext: ['--h-ext', 'Library call'], op: ['--h-op', 'Operator'], lit: ['--h-lit', 'Fixed value'], var: ['--h-var', 'Module variable'],
  select: ['--h-select', 'Pick one value'], branch: ['--h-branch', 'Branch'], return: ['--h-return', 'Give back'], raise: ['--h-raise', 'Raise an error'], set: ['--h-set', 'Store on the object'],
};

function routedPath(ax, ay, bx, by, via, minDx = 36) {
  let d = `M${ax},${ay}`, cx = ax, cy = ay;
  const curveTo = (x, y) => { const dx = Math.max(Math.min(minDx, Math.abs(x - cx) * 0.5 + 12), Math.abs(x - cx) * 0.5); d += ` C${cx + dx},${cy} ${x - dx},${y} ${x},${y}`; cx = x; cy = y; };
  for (const p of via) { curveTo(p.x, p.y); d += ` L${p.x + p.w},${p.y}`; cx = p.x + p.w; }
  curveTo(bx, by);
  return d;
}
class Scene {
  constructor(ctx) { this.ctx = ctx; this.nodes = []; this.wires = []; this.el = el('div', { class: 'scene' }); this.svg = svg('svg', { class: 'wires' }); this.layer = el('div', { class: 'layer' }); this.el.append(this.svg, this.layer); document.getElementById('measure').append(this.el); }
  add(element, data = {}) { const v = { el: element, data, x: 0, y: 0 }; element.classList.add('node'); this.layer.append(element); this.nodes.push(v); return v; }
  wire(a, ak, b, bk, cls, type) { const w = { a, ak, b, bk, cls, type }; this.wires.push(w); return w; }
  measure() {
    for (const n of this.nodes) {
      n.w = n.el.offsetWidth; n.h = n.el.offsetHeight; n.pins = {};
      n.el.querySelectorAll('[data-pin]').forEach((p) => {
        if (p.closest('.node') !== n.el) return;
        const s = p.querySelector('.shape') || p;
        let x = 0, y = 0, cur = s;
        while (cur && cur !== n.el) { x += cur.offsetLeft; y += cur.offsetTop; cur = cur.offsetParent; }
        n.pins[p.dataset.pin] = { dx: x + s.offsetWidth / 2, dy: y + s.offsetHeight / 2 };
      });
    }
  }
  finish(pad = 40) {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    const all = [...this.nodes, ...(this.dummies || [])];
    for (const n of all) { x0 = Math.min(x0, n.x); y0 = Math.min(y0, n.y); x1 = Math.max(x1, n.x + n.w); y1 = Math.max(y1, n.y + n.h); }
    if (!all.length) { x0 = y0 = 0; x1 = y1 = 10; }
    for (const n of all) { n.x += pad - x0; n.y += pad - y0; if (n.el) { n.el.style.left = `${n.x}px`; n.el.style.top = `${n.y}px`; } }
    this.width = x1 - x0 + 2 * pad; this.height = y1 - y0 + 2 * pad;
    Object.assign(this.el.style, { width: `${this.width}px`, height: `${this.height}px` });
    this.svg.setAttribute('width', this.width); this.svg.setAttribute('height', this.height);
    this.svg.innerHTML = '';
    for (const w of this.wires) {
      const pa = w.a.pins[w.ak], pb = w.b.pins[w.bk];
      if (!pa || !pb) continue;
      const path = svg('path', { d: routedPath(w.a.x + pa.dx, w.a.y + pa.dy, w.b.x + pb.dx, w.b.y + pb.dy, (w.via || []).map((d) => ({ x: d.x, y: d.y + d.pins.d.dy, w: d.w }))), class: `wire ${w.cls || ''}` });
      if (!w.cls) path.style.stroke = `var(--t-${w.type ? w.type.cat : 'any'})`;
      w.path = path; this.svg.append(path);
    }
  }
  hover(node, on) {
    this.el.classList.toggle('has-hot', on);
    for (const w of this.wires) if (w.path) w.path.classList.toggle('hot', on && (w.a === node || w.b === node));
  }
}

function nodeEl(n, ctx, connectedIns, connectedOuts) {
  const [hc] = KIND[n.kind] || KIND.ext;
  const wrap = el('div', { class: `k-${n.kind}` });
  const box = el('div', { class: 'box' });
  wrap.append(box);
  const openable = n.target && lookup(n.target) && lookup(n.target).kind === 'function' && ['call', 'method', 'ext', 'var'].includes(n.kind);
  box.append(el('div', { class: 'head', style: `--hc: var(${hc})` },
    el('span', { class: 'title' }, n.kind === 'break' || n.kind === 'make' ? `${n.title.split(' ')[0]} ${plain(n.title.split(' ').slice(1).join(' '))}` : plain(n.title)),
    openable && ctx.openButton ? ctx.openButton(n) : null));
  const left = el('div', { class: 'col in' }), right = el('div', { class: 'col out' });
  if (n.execIn) left.append(pinEl('in', 'exec-in', '', null));
  if (n.execOut) right.append(pinEl('out', 'then', '', null));
  for (const label of n.execOuts || []) right.append(pinEl('out', label, label, null, { raw: true }));
  for (const p of n.ins) left.append(pinEl('in', `in:${p.name}`, p.name, p.type, { lit: p.lit, connected: connectedIns.has(p.name) || p.lit != null }));
  for (const o of n.outs) right.append(pinEl('out', `out:${o.name}`, o.name, o.type, { connected: connectedOuts.has(o.name) }));
  box.append(el('div', { class: 'rows' }, left, right));
  if (n.note) box.append(el('div', { class: 'note' }, n.note));
  box.append(el('div', { class: 'embed-slot' }));
  return wrap;
}

function buildFunctionScene(fnSym, ctx) {
  const g = freshGraph(fnSym);
  const scene = new Scene(ctx);
  const byId = new Map();
  const conIn = new Map(), conOut = new Map();
  for (const e of g.edges) { if (!conIn.has(e.to)) conIn.set(e.to, new Set()); conIn.get(e.to).add(e.tp); if (!conOut.has(e.from)) conOut.set(e.from, new Set()); conOut.get(e.from).add(e.fp); }
  for (const n of g.nodes) {
    const v = scene.add(nodeEl(n, ctx, conIn.get(n) || new Set(), conOut.get(n) || new Set()), n);
    v.el.addEventListener('click', (ev) => { if (ev.target.closest('button')) return; ev.stopPropagation(); ctx.select(n, v, fnSym); });
    v.el.addEventListener('dblclick', (ev) => { ev.stopPropagation(); if (n.target && lookup(n.target) && n.kind !== 'entry') ctx.activate(n.target, n, v); });
    v.el.addEventListener('mouseenter', () => scene.hover(v, true));
    v.el.addEventListener('mouseleave', () => scene.hover(v, false));
    byId.set(n, v);
    if (ctx.afterNode) ctx.afterNode(n, v);
  }
  let doc = null;
  if (fnSym.doc) doc = scene.add(el('div', { class: 'doc-note' }, fnSym.doc));
  scene.measure();
  const { routes, dummies } = layered(g, byId);
  scene.dummies = dummies;
  for (const e of g.edges) scene.wire(byId.get(e.from), `out:${e.fp}`, byId.get(e.to), `in:${e.tp}`, null, e.type).via = routes.get(`${e.from.id}|out:${e.fp}|${e.to.id}|in:${e.tp}`);
  for (const e of g.exec) scene.wire(byId.get(e.from), e.fp, byId.get(e.to), 'exec-in', 'exec').via = routes.get(`${e.from.id}|${e.fp}|${e.to.id}|exec-in`);
  if (doc) { const entry = byId.get(g.nodes[0]); doc.x = entry.x; doc.y = Math.min(...[...byId.values()].map((v) => v.y)) - doc.h - 20; }
  scene.finish();
  return scene;
}

function layered(g, byId) {
  const addTo = (m, k, v) => { if (!m.has(k)) m.set(k, []); m.get(k).push(v); };
  const realPreds = new Map(), realSuccs = new Map();
  for (const e of [...g.edges, ...g.exec]) { addTo(realPreds, e.to, e.from); addTo(realSuccs, e.from, e.to); }
  const rank = new Map();
  const rankOf = (n) => {
    if (rank.has(n)) return rank.get(n);
    rank.set(n, 0);
    const ps = realPreds.get(n) || [];
    const r = n.kind === 'entry' ? 0 : ps.length ? 1 + Math.max(...ps.map((p) => rankOf(p) ?? 0)) : null;
    rank.set(n, r);
    return r;
  };
  g.nodes.forEach(rankOf);
  for (const n of g.nodes) if (rank.get(n) === null) { const ss = realSuccs.get(n) || []; rank.set(n, ss.length ? Math.max(1, Math.min(...ss.map((s) => rank.get(s) ?? 2)) - 1) : 1); }
  const maxR = Math.max(...rank.values());
  for (const n of g.nodes) if (n.kind === 'return' && !(realSuccs.get(n) || []).length) rank.set(n, maxR);
  const V = (n) => (n.dummy ? n : byId.get(n));
  const rk = (n) => (n.dummy ? n.rank : rank.get(n));
  const isExec = (n) => (n.dummy ? n.exec : Boolean(n.execIn || n.execOut || (n.execOuts && n.execOuts.length)));
  const preds = new Map(), succs = new Map();
  const link = (a, b, ak, bk, exec) => { addTo(preds, b, { n: a, ak, bk, exec }); addTo(succs, a, { n: b, ak, bk, exec }); };
  const all = [
    ...g.edges.map((e) => ({ from: e.from, fp: `out:${e.fp}`, to: e.to, tp: `in:${e.tp}`, exec: false })),
    ...g.exec.map((e) => ({ from: e.from, fp: e.fp, to: e.to, tp: 'exec-in', exec: true })),
  ];
  const bundles = new Map();
  for (const e of all) { const k = `${e.from.id}|${e.fp}`; if (!bundles.has(k)) bundles.set(k, []); bundles.get(k).push(e); }
  const dummies = [];
  const routes = new Map();
  for (const list of bundles.values()) {
    const src = list[0].from, r0 = rank.get(src), exec = list[0].exec;
    const far = Math.max(r0, ...list.map((e) => rank.get(e.to)));
    const chain = [];
    for (let r = r0 + 1; r < far; r++) {
      const d = { dummy: true, exec, rank: r, w: 0, h: 8, x: 0, y: 0, pins: { d: { dx: 0, dy: 4 } } };
      link(chain.length ? chain[chain.length - 1] : src, d, chain.length ? 'd' : list[0].fp, 'd', exec);
      chain.push(d); dummies.push(d);
    }
    for (const e of list) {
      const t = rank.get(e.to);
      const via = t > r0 + 1 ? chain.slice(0, t - r0 - 1) : [];
      routes.set(`${e.from.id}|${e.fp}|${e.to.id}|${e.tp}`, via);
      link(via.length ? via[via.length - 1] : src, e.to, via.length ? 'd' : e.fp, e.tp, exec);
    }
  }
  const cols = [];
  for (const n of [...g.nodes, ...dummies]) { const r = rk(n); if (!cols[r]) cols[r] = []; cols[r].push(n); }
  const GAPX = 56, GAPY = 18;
  const colX = [], colW = [];
  let x = 0;
  cols.forEach((col, r) => { if (!col) return; const real = col.filter((n) => !n.dummy); const w = real.length ? Math.max(...real.map((n) => byId.get(n).w)) : 24; colX[r] = x; colW[r] = w; for (const n of real) byId.get(n).x = x; x += w + GAPX; });
  for (const col of cols) { if (!col) continue; let y = 0; for (const n of col) { const v = V(n); v.y = y; y += v.h + GAPY; } }
  const linksFor = (n, map) => { const lst = map.get(n) || []; if (!isExec(n)) return lst; const ex = lst.filter((l) => l.exec); return ex.length ? ex : lst; };
  const targetFrom = (n, list, fromPreds) => {
    const v = V(n);
    const vals = list.map((p) => { const o = V(p.n); const op = o.pins[fromPreds ? p.ak : p.bk], vp = v.pins[fromPreds ? p.bk : p.ak]; return op && vp ? o.y + op.dy - vp.dy : null; }).filter((t0) => t0 !== null);
    return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
  };
  const entryV = byId.get(g.nodes.find((n) => n.kind === 'entry'));
  const lane = g.exec.length && entryV.pins.then ? entryV.pins.then.dy + 26 : -Infinity;
  const place = (col, targets) => {
    const key = (n) => (targets.get(n) ?? V(n).y) + (isExec(n) ? -1e6 : 0);
    col.sort((a, b) => key(a) - key(b));
    let prev = -Infinity;
    for (const n of col) {
      const v = V(n);
      const t0 = isExec(n) && g.exec.length ? Math.max(0, targets.get(n) ?? 0) : targets.get(n) ?? v.y;
      v.y = Math.max(t0, prev, isExec(n) ? -Infinity : lane);
      prev = v.y + v.h + (n.dummy ? 10 : GAPY);
    }
  };
  const forward = () => { for (const col of cols) { if (!col) continue; const t = new Map(); for (const n of col) { const tp = targetFrom(n, linksFor(n, preds), true); if (tp !== null) t.set(n, tp); } place(col, t); } };
  const backward = () => { for (let ci = cols.length - 1; ci >= 0; ci--) { const col = cols[ci]; if (!col) continue; const t = new Map(); for (const n of col) { const ts = isExec(n) && !n.dummy ? null : targetFrom(n, succs.get(n) || [], false); const tp = targetFrom(n, linksFor(n, preds), true); const val = ts !== null && tp !== null ? (ts + tp) / 2 : ts ?? tp; if (val !== null) t.set(n, val); } place(col, t); } };
  for (let it = 0; it < 5; it++) { forward(); backward(); }
  forward();
  for (const d of dummies) { d.x = colX[d.rank]; d.w = colW[d.rank]; }
  return { routes, dummies };
}

const KIND_ORDER = ['inherits', 'realizes', 'has', 'creates', 'calls', 'writes', 'reads', 'uses'];
function stereotypeOf(sym) {
  if (sym.stereo) return sym.stereo;
  if (sym.kind === 'enum') return 'enum';
  if (sym.cat === 'iface') return 'protocol';
  if (sym.cat === 'struct') return 'dataclass';
  return null;
}
const visibility = (name) => (/^_[^_]/.test(name) ? '−' : '+');
const typeText = (t) => el('span', { class: 'utype', style: `color:var(--t-${t.cat})` }, t.label);

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : (word.endsWith('s') ? 'es' : 's')}`;
let NET_CACHE = null;
function net() {
  if (NET_CACHE) return NET_CACHE;
  const nodes = new Map();
  const root = { id: 'root', kind: 'root', name: OVERVIEW ? OVERVIEW.name : 'project', depth: 0, children: [], parent: null };
  nodes.set('root', root);
  const add = (id, kind, name, parent, extra = {}) => {
    if (nodes.has(id)) return nodes.get(id);
    const n = { id, kind, name, parent, depth: parent.depth + 1, children: [], ...extra };
    parent.children.push(n); nodes.set(id, n); return n;
  };
  for (const path of Object.keys(FILES).sort()) {
    const parts = path.split('/');
    let parent = root, acc = '';
    for (const part of parts.slice(0, -1)) { acc += (acc ? '/' : '') + part; parent = add(`pkg:${acc}`, 'package', part, parent); }
    const f = FILES[path];
    const mod = add(`mod:${path}`, 'module', parts[parts.length - 1], parent, { path, mocked: true });
    for (const s of f.symbols) {
      if (s.kind === 'function') { add(`fn:${path}:${s.qual}`, 'function', s.name, mod, { sym: s }); continue; }
      const c = add(`cls:${path}:${s.qual}`, 'class', s.name, mod, { sym: s, path });
      for (const [mname, v] of s.members || []) add(`f:${path}:${s.qual}.${mname}`, 'member', mname, c, { value: v });
      for (const [fname, ftype] of s.fields || []) add(`f:${path}:${s.qual}.${fname}`, 'field', fname, c, { type: ftype });
      for (const m of s.methods || []) add(`m:${path}:${m.qual}`, 'method', m.name, c, { sym: m });
    }
    for (const [cn, ct, cv] of f.constants || []) add(`c:${path}:${cn}`, 'constant', cn, mod, { type: ct, value: cv });
  }
  for (const lib of (OVERVIEW && OVERVIEW.libraries) || []) {
    const libNode = add(lib.id, 'library', lib.title, root);
    for (const m of lib.modules) {
      const modNode = add(`libmod:${m.module}`, 'libmodule', m.module, libNode);
      for (const n of m.names) add(`libn:${m.module}.${n}`, 'name', n, modNode);
    }
  }
  const list = [];
  const ids = OVERVIEW ? OVERVIEW.edges.ids : [];
  for (const row of OVERVIEW ? OVERVIEW.edges.rows : []) {
    const from = ids[row[0]], to = ids[row[1]];
    if (!nodes.has(from) || !nodes.has(to)) continue;
    const kinds = new Set(row[2].split(',').filter(Boolean));
    list.push({ from, to, kinds, labels: new Set(row[3] ? row[3].split(',') : []), kind: KIND_ORDER.find((k) => kinds.has(k)) });
  }
  const chains = new Map();
  const chain = (id) => { if (chains.has(id)) return chains.get(id); const out = []; for (let n = nodes.get(id); n; n = n.parent) out.unshift(n); chains.set(id, out); return out; };
  NET_CACHE = { nodes, root, edges: list, chain };
  return NET_CACHE;
}

function netLabel(id) {
  const n = net().nodes.get(id);
  if (!n) return id;
  if (n.kind === 'method') return `${n.parent.name}.${n.name}()`;
  if (n.kind === 'function') return `${n.name}()`;
  if (n.kind === 'field' || n.kind === 'member') return `${n.parent.name}.${n.name}`;
  if (n.kind === 'name') return `${n.name} (${n.parent.kind === 'libmodule' ? n.parent.name : n.parent.name})`;
  if (n.kind === 'package') return `${n.name}/`;
  return n.name;
}
function moduleOf(id) { const c = net().chain(id); const m = c.find((n) => n.kind === 'module' || n.kind === 'libmodule'); return m ? m.name : null; }
function netDefaultExpanded(path) { const n = net().nodes.get(`mod:${path}`); return new Set(n ? net().chain(n.id).slice(1).map((x) => x.id) : []); }

function opBlock(fnSym) {
  const params = fnSym.params.filter((p) => p[0] !== 'self');
  const hasReturn = fnSym.returns && fnSym.returns.cat !== 'none';
  return [
    el('div', { class: 'sig-head' }, el('span', { class: 'uvis' }, visibility(fnSym.name)), el('span', { class: 'uop' }, plain(fnSym.name)), el('span', { class: 'go' }, '▸')),
    params.length ? el('div', { class: 'sig-params' }, params.map((p, i) => el('span', { class: 'sig-param', title: `${p[0]}: ${p[1].label}` }, el('span', { class: 'pdot', style: `background:var(--t-${p[1].cat})` }), plain(p[0]), i < params.length - 1 ? ',' : ''))) : null,
    hasReturn ? el('div', { class: 'sig-ret' }, el('span', { class: 'udim' }, '→ '), typeText(fnSym.returns)) : null,
  ];
}
function summaryOf(n) {
  const counts = new Map();
  const word = { package: 'package', module: 'module', class: 'class', function: 'function', method: 'method', field: 'field', member: 'choice', constant: 'constant', name: 'name', libmodule: 'module' };
  for (const k of n.children) counts.set(word[k.kind], (counts.get(word[k.kind]) || 0) + 1);
  return [...counts].map(([w, c]) => plural(c, w)).join(' · ');
}
function netBoxEl(n, expanded, ctx) {
  if (!n.children.length) {
    const stripe = { method: '--h-method', function: '--h-call', field: '--h-break', member: '--h-enum', constant: '--h-var', name: '--h-lit' }[n.kind] || '--h-lit';
    const isFn = n.kind === 'method' || n.kind === 'function';
    const kids = isFn ? opBlock(n.sym)
      : n.kind === 'field' ? [el('span', { class: 'uvis' }, visibility(n.name)), el('span', {}, plain(n.name)), el('span', { class: 'udim' }, ':'), typeText(n.type)]
        : n.kind === 'member' ? [el('span', {}, n.name), el('span', { class: 'udim' }, ` = ${n.value}`)]
          : n.kind === 'constant' ? [el('span', {}, plain(n.name)), el('span', { class: 'udim' }, ':'), typeText(n.type), el('span', { class: 'udim' }, ` = ${n.value}`)]
            : [el('span', { class: 'uicon' }, /^[a-z_]/.test(n.name) ? 'ƒ' : 'C'), el('span', {}, n.name)];
    const leaf = el('div', { class: `nb leaf k-${n.kind}${isFn ? ' fnleaf' : ''}`, 'data-id': n.id, style: `--stripe: var(${stripe})`, title: n.sym ? 'Open its dataflow view' : netLabel(n.id) }, kids);
    leaf.addEventListener('click', (e) => { e.stopPropagation(); if (n.sym) ctx.go(refOf(n.sym)); else ctx.select(n.id); });
    return leaf;
  }
  const isOpen = expanded.has(n.id);
  const sym = n.sym;
  const hc = n.kind === 'package' ? '--h-pkg' : n.kind === 'module' ? '--h-mod' : n.kind === 'library' || n.kind === 'libmodule' ? '--h-lib'
    : sym.kind === 'enum' ? '--h-enum' : sym.cat === 'iface' ? '--h-iface' : sym.cat === 'struct' ? '--h-struct' : '--h-break';
  const stereo = n.kind === 'class' ? stereotypeOf(sym) : n.kind === 'module' ? 'module' : n.kind === 'library' ? 'library' : null;
  const title = n.kind === 'package' ? `${n.name}/` : n.name;
  const box = el('div', { class: `nb k-${n.kind} ${isOpen ? 'open' : ''} ${n.kind === 'module' && !n.mocked ? 'missing' : ''}`, 'data-id': n.id, style: `--hc: var(${hc})` });
  const head = el('div', { class: 'nhead', title: isOpen ? 'Collapse' : 'Expand' }, el('span', { class: 'chev' }, isOpen ? '▾' : '▸'),
    stereo ? el('span', { class: 'stereo' }, `«${stereo}»`) : null, el('span', { class: 'ntitle' }, title),
    n.kind === 'module' && !n.mocked ? el('span', { class: 'stereo' }, 'not in prototype') : null);
  head.addEventListener('click', (e) => { e.stopPropagation(); ctx.select(n.id); ctx.toggle(n.id); });
  box.append(head);
  if (!isOpen) { box.append(el('div', { class: 'nsum' }, summaryOf(n))); return box; }
  const inner = el('div', { class: 'ninner' });
  for (const k of n.children) inner.append(netBoxEl(k, expanded, ctx));
  box.append(inner);
  return box;
}
const NET_ROUTES = new Map();
const NET_EXITS = new Map();
const NET_ENTRIES = new Map();
function layoutNet(n, boxEl, edges) {
  const inner = boxEl.querySelector(':scope > .ninner');
  if (!inner) return;
  const N = net();
  const kids = [...inner.children].map((elx) => ({ node: N.nodes.get(elx.dataset.id), el: elx, x: 0, y: 0 }));
  const byId = new Map(kids.map((k) => [k.node.id, k]));
  const under = (id) => { const c = N.chain(id); return c[n.depth] === n && c[n.depth + 1] ? byId.get(c[n.depth + 1].id) : null; };
  const touching = new Map(kids.map((k) => [k, []]));
  for (const e of edges) {
    const a = under(e.from), b = under(e.to);
    if (a) touching.get(a).push(e);
    if (b && b !== a) touching.get(b).push(e);
  }
  for (const k of kids) layoutNet(k.node, k.el, touching.get(k));
  for (const k of kids) { k.w = k.el.offsetWidth; k.h = k.el.offsetHeight; }
  const pairs = new Map();
  for (const e of edges) {
    const a = under(e.from), b = under(e.to);
    if (!a || !b || a === b) continue;
    if (!pairs.has(a)) pairs.set(a, new Set()); pairs.get(a).add(b);
  }
  const preds = new Map();
  for (const [a, bs] of pairs) for (const b of bs) { if (!preds.has(b)) preds.set(b, new Set()); preds.get(b).add(a); }
  const rank = new Map();
  const rankOf = (k, seen = new Set()) => { if (rank.has(k)) return rank.get(k); if (seen.has(k)) return 0; seen.add(k); const r = Math.max(0, ...[...(preds.get(k) || [])].map((p) => rankOf(p, seen) + 1)); rank.set(k, r); return r; };
  kids.forEach((k) => rankOf(k));
  const maxR = Math.max(0, ...rank.values());
  for (const k of kids) if (['field', 'member', 'constant'].includes(k.node.kind) && !preds.has(k) && maxR > 0) rank.set(k, maxR);
  const inside = (id) => N.chain(id)[n.depth] === n;
  const exits = new Set(), entries = new Set();
  for (const e of edges) {
    const a = under(e.from), b = under(e.to);
    if (a && !inside(e.to)) exits.add(a);
    if (b && !inside(e.from)) entries.add(b);
  }
  const items = [...kids];
  const nbrs = new Map();
  const near = (a, b) => { if (!nbrs.has(a)) nbrs.set(a, new Set()); nbrs.get(a).add(b); if (!nbrs.has(b)) nbrs.set(b, new Set()); nbrs.get(b).add(a); };
  const routes = [];
  for (const [a, bs] of pairs) {
    const r0 = rank.get(a);
    const far = Math.max(r0, ...[...bs].map((b) => rank.get(b)));
    const chain = [];
    for (let r = r0 + 1; r < far; r++) { const d = { dummy: true, rank: r, w: 0, h: 6, x: 0, y: 0 }; near(chain.length ? chain[chain.length - 1] : a, d); chain.push(d); items.push(d); }
    for (const b of bs) { const t = rank.get(b); const via = t > r0 + 1 ? chain.slice(0, t - r0 - 1) : []; near(via.length ? via[via.length - 1] : a, b); routes.push({ a, b, via }); }
  }
  const lastRank = Math.max(0, ...kids.map((k) => rank.get(k)));
  const exitRoutes = [], entryRoutes = [];
  for (const k of exits) {
    const chain = [];
    for (let r = rank.get(k) + 1; r <= lastRank; r++) { const d = { dummy: true, rank: r, w: 0, h: 6, x: 0, y: 0 }; near(chain.length ? chain[chain.length - 1] : k, d); chain.push(d); items.push(d); }
    exitRoutes.push({ k, via: chain });
  }
  for (const k of entries) {
    const chain = [];
    for (let r = 0; r < rank.get(k); r++) { const d = { dummy: true, rank: r, w: 0, h: 6, x: 0, y: 0 }; if (chain.length) near(chain[chain.length - 1], d); chain.push(d); items.push(d); }
    if (chain.length) near(chain[chain.length - 1], k);
    entryRoutes.push({ k, via: chain });
  }
  const rk = (it) => (it.dummy ? it.rank : rank.get(it));
  const cols = [];
  for (const it of items) { const r = rk(it); if (!cols[r]) cols[r] = []; cols[r].push(it); }
  const leafy = kids.every((k) => !k.node.children.length);
  const PAD = 14, TOP = 10, GX = leafy ? 70 : 110, GY = leafy ? 12 : 22;
  const colX = [], colW = [];
  let x = PAD;
  cols.forEach((col, r) => { if (!col) return; const real = col.filter((it) => !it.dummy); const w = real.length ? Math.max(...real.map((k) => k.w)) : 30; colX[r] = x; colW[r] = w; let y = TOP; for (const it of col) { it.x = x; it.y = y; y += it.h + GY; } x += w + GX; });
  const mid = (o) => o.y + (o.dummy ? 3 : Math.min(o.h, 40) / 2);
  for (let pass = 0; pass < 4; pass++) for (const col of cols) {
    if (!col) continue;
    const want = new Map(col.map((it) => {
      const nb = [...(nbrs.get(it) || [])].filter((o) => rk(o) !== rk(it));
      return [it, nb.length ? nb.reduce((acc, o) => acc + mid(o), 0) / nb.length - (it.dummy ? 3 : Math.min(it.h, 40) / 2) : it.y];
    }));
    col.sort((a, b) => want.get(a) - want.get(b));
    let prev = TOP; for (const it of col) { it.y = Math.max(want.get(it), prev); prev = it.y + it.h + (it.dummy ? 8 : GY); }
  }
  const connected = (it) => (nbrs.get(it) || new Set()).size > 0;
  for (const col of cols) {
    if (!col) continue;
    col.sort((a, b) => (connected(b) - connected(a)) || a.y - b.y);
    let prev = null;
    for (const it of col) {
      const lo = prev === null ? TOP : prev + (it.dummy ? 8 : GY);
      it.y = Math.min(Math.max(it.y, lo), lo + 36);
      prev = it.y + it.h;
    }
  }
  const minY = Math.min(...items.map((it) => it.y));
  for (const it of items) it.y += TOP - minY;
  for (const k of kids) { k.el.style.left = `${k.x}px`; k.el.style.top = `${k.y}px`; }
  for (const it of items) if (it.dummy) { it.x = colX[it.rank]; it.w = colW[it.rank]; }
  inner.style.width = `${Math.max(...kids.map((k) => k.x + k.w), 100) + PAD}px`;
  inner.style.height = `${Math.max(...items.map((it) => it.y + it.h), 30) + PAD}px`;
  for (const r of routes) NET_ROUTES.set(`${r.a.node.id}|${r.b.node.id}`, { inner, via: r.via });
  for (const r of exitRoutes) NET_EXITS.set(`${n.id}|${r.k.node.id}`, { inner, via: r.via });
  for (const r of entryRoutes) NET_ENTRIES.set(`${n.id}|${r.k.node.id}`, { inner, via: r.via });
}

function buildNetScene(expanded, ctx) {
  const N = net();
  const scene = new Scene(ctx);
  const effective = new Set(['root']);
  for (const id of expanded) { const c = N.chain(id); if (c.length && c[c.length - 1].children.length && c.slice(1).every((x) => expanded.has(x.id))) effective.add(id); }
  const rootEl = el('div', { class: 'nroot', 'data-id': 'root' });
  const inner = el('div', { class: 'ninner' });
  for (const k of N.root.children) inner.append(netBoxEl(k, effective, ctx));
  rootEl.append(inner);
  const rootV = scene.add(rootEl);
  NET_ROUTES.clear(); NET_EXITS.clear(); NET_ENTRIES.clear();
  const visibleOf = (id) => { const c = N.chain(id); for (let i = 1; i < c.length; i++) if (!effective.has(c[i].id)) return c[i].id; return id; };
  const shown = new Map();
  for (const e of N.edges) {
    const a = visibleOf(e.from), b = visibleOf(e.to);
    if (a === b) continue;
    const key = `${a}|${b}`;
    if (!shown.has(key)) shown.set(key, { from: a, to: b, atoms: [] });
    shown.get(key).atoms.push(e);
  }
  layoutNet(N.root, rootEl, [...shown.values()]);
  scene.measure();
  scene.finish(40);
  const rects = new Map();
  const sizes = [];
  rootEl.querySelectorAll('.nb').forEach((b) => {
    let x = 0, y = 0, cur = b;
    while (cur && cur !== rootEl) { x += cur.offsetLeft; y += cur.offsetTop; cur = cur.offsetParent; }
    const head = b.querySelector(':scope > .nhead');
    rects.set(b.dataset.id, { x: rootV.x + x, y: rootV.y + y, w: b.offsetWidth, h: b.offsetHeight, anchorY: head ? head.offsetHeight / 2 : b.offsetHeight / 2, el: b });
    sizes.push({ el: b, w: b.offsetWidth, h: b.offsetHeight });
  });
  const depthMax = Math.max(...[...effective].map((id) => N.nodes.get(id).depth));
  const agg = new Map();
  for (const { from: a, to: b, atoms } of shown.values()) {
    if (!rects.has(a) || !rects.has(b)) continue;
    if (N.chain(b).some((x) => x.id === a) || N.chain(a).some((x) => x.id === b)) continue;
    const g = { a, b, kinds: new Set(), labels: new Set(), count: atoms.length, atoms };
    for (const e of atoms) { e.kinds.forEach((x) => g.kinds.add(x)); e.labels.forEach((x) => g.labels.add(x)); }
    agg.set(`${a}|${b}`, g);
  }
  const defs = svg('defs');
  defs.innerHTML = `
    <marker id="m-tri" viewBox="0 0 14 14" refX="13" refY="7" markerWidth="14" markerHeight="14" markerUnits="userSpaceOnUse" orient="auto"><path d="M1,1 L13,7 L1,13 z" style="fill:var(--canvas);stroke:var(--rel-inherits)" stroke-width="1.6"/></marker>
    <marker id="m-dia" viewBox="0 0 18 10" refX="1" refY="5" markerWidth="18" markerHeight="10" markerUnits="userSpaceOnUse" orient="auto"><path d="M1,5 L9,1 L17,5 L9,9 z" style="fill:var(--rel-has)"/></marker>
    ${['has', 'creates', 'calls', 'writes', 'reads', 'uses'].map((k) => `<marker id="m-arrow-${k}" viewBox="0 0 12 12" refX="11" refY="6" markerWidth="12" markerHeight="12" markerUnits="userSpaceOnUse" orient="auto"><path d="M1,1 L11,6 L1,11" style="fill:none;stroke:var(--rel-${k})" stroke-width="1.7"/></marker>`).join('')}
    <marker id="m-arrow-faint" viewBox="0 0 12 12" refX="11" refY="6" markerWidth="12" markerHeight="12" markerUnits="userSpaceOnUse" orient="auto"><path d="M1,1 L11,6 L1,11" style="fill:none;stroke:var(--rel-uses)" stroke-width="1.7"/></marker>`;
  scene.svg.append(defs);
  const overlay = svg('svg', { class: 'wires overlay', width: scene.width, height: scene.height });
  scene.el.append(overlay);
  const cubic = (t, a, b, c, d) => (1 - t) ** 3 * a + 3 * (1 - t) ** 2 * t * b + 3 * (1 - t) * t ** 2 * c + t ** 3 * d;
  const drawn = [];
  const offsets = new Map();
  const innerOffset = (inner) => { if (offsets.has(inner)) return offsets.get(inner); let ox = 0, oy = 0, cur = inner; while (cur && cur !== rootEl) { ox += cur.offsetLeft; oy += cur.offsetTop; cur = cur.offsetParent; } const o = { x: rootV.x + ox, y: rootV.y + oy }; offsets.set(inner, o); return o; };
  const absVia = (route) => { if (!route) return []; const o = innerOffset(route.inner); return route.via.map((d) => ({ x: o.x + d.x, y: o.y + d.y + 3, w: d.w })); };
  const hierarchicalSpans = (aId, bId, y1, y2) => {
    const ca = N.chain(aId), cb = N.chain(bId);
    let i = 0; while (ca[i + 1] && cb[i + 1] && ca[i + 1] === cb[i + 1]) i++;
    const spans = [];
    let cy = y1;
    for (let j = ca.length - 2; j >= i + 1; j--) {
      const box = rects.get(ca[j].id);
      if (!box) continue;
      const via = absVia(NET_EXITS.get(`${ca[j].id}|${ca[j + 1].id}`));
      spans.push(...via);
      if (via.length) cy = via[via.length - 1].y;
      const from = spans.length ? spans[spans.length - 1].x + spans[spans.length - 1].w : box.x + box.w - 2;
      spans.push({ x: Math.min(from, box.x + box.w - 1), y: cy, w: Math.max(1, box.x + box.w - from) });
    }
    const middle = absVia(NET_ROUTES.get(`${ca[i + 1].id}|${cb[i + 1].id}`));
    spans.push(...middle);
    for (let j = i + 1; j <= cb.length - 2; j++) {
      const box = rects.get(cb[j].id);
      if (!box) continue;
      const via = absVia(NET_ENTRIES.get(`${cb[j].id}|${cb[j + 1].id}`));
      const child = rects.get(cb[j + 1].id);
      const laneY = via.length ? via[0].y : child ? child.y + child.anchorY : y2;
      spans.push({ x: box.x + 1, y: laneY, w: Math.max(1, (via.length ? via[0].x : box.x + 14) - box.x - 1) });
      spans.push(...via);
    }
    return spans;
  };
  for (const g of agg.values()) {
    g.kind = KIND_ORDER.find((k) => g.kinds.has(k));
    const ra = rects.get(g.a), rb = rects.get(g.b);
    g.coloured = N.nodes.get(g.a).depth === depthMax + 1 && N.nodes.get(g.b).depth === depthMax + 1;
    const x1 = ra.x + ra.w, y1 = ra.y + ra.anchorY;
    const backwards = rb.x < x1 - 4;
    const x2 = backwards ? rb.x + rb.w + 2 : rb.x - 2, y2 = rb.y + rb.anchorY;
    let c1, c2;
    if (backwards) { c1 = Math.max(x1, x2) + 50 + Math.abs(y2 - y1) * 0.12; c2 = c1; } else { const dx = Math.max(50, Math.abs(x2 - x1) * 0.45); c1 = x1 + dx; c2 = x2 - dx; }
    const marker = g.kind === 'inherits' || g.kind === 'realizes' ? 'url(#m-tri)' : `url(#m-arrow-${g.kind})`;
    const spans = backwards ? [] : hierarchicalSpans(g.a, g.b, y1, y2);
    const routedD = spans.length ? routedPath(x1, y1, x2, y2, spans, 50) : `M${x1},${y1} C${c1},${y1} ${c2},${y2} ${x2},${y2}`;
    const tail = spans.length ? spans[spans.length - 1] : null;
    const path = svg('path', { d: routedD, class: `rel k-${g.kind}${g.coloured ? '' : ' faint'}`, 'marker-end': g.coloured ? marker : 'url(#m-arrow-faint)', 'data-marker': marker });
    if (g.kind === 'has' && g.coloured) path.setAttribute('marker-start', 'url(#m-dia)');
    const kinds = [...g.kinds].sort((p, q) => KIND_ORDER.indexOf(p) - KIND_ORDER.indexOf(q));
    const label = g.kinds.size === 1 && g.kind === 'has' && N.nodes.get(g.a).kind === 'field' ? [...g.labels].join(', ') : `${kinds.join(' · ')}${g.count > 1 ? ` (${g.count})` : ''}`;
    const text = svg('text', { x: tail ? (tail.x + tail.w + x2) / 2 : cubic(0.65, x1, c1, c2, x2), y: (tail ? (tail.y + y2) / 2 : cubic(0.65, y1, y1, y2, y2)) - 5, class: `rel-label k-${g.kind}${g.coloured ? '' : ' faint'}`, 'text-anchor': 'middle' });
    text.textContent = label;
    (g.coloured ? overlay : scene.svg).append(path, text);
    drawn.push({ g, path, text, box: { x: +text.getAttribute('x') - label.length * 3.3, y: +text.getAttribute('y') - 10, w: label.length * 6.6, h: 13 } });
  }
  const placed = [];
  for (const d of [...drawn].sort((p, q) => Number(q.g.coloured) - Number(p.g.coloured))) {
    const b = d.box;
    if (placed.some((o) => b.x < o.x + o.w && o.x < b.x + b.w && b.y < o.y + o.h && o.y < b.y + b.h)) d.text.classList.add('crowded');
    else placed.push(b);
  }
  const highlight = (id) => {
    overlay.querySelectorAll('.hot-clone').forEach((c) => c.remove());
    scene.el.classList.toggle('has-hot', Boolean(id));
    const inside = (x) => id && N.chain(x).some((n) => n.id === id);
    for (const d of drawn) {
      const hot = Boolean(id) && (inside(d.g.a) || inside(d.g.b));
      d.path.classList.toggle('hot', hot); d.text.classList.toggle('hot', hot);
      if (hot && !d.g.coloured) for (const e2 of [d.path, d.text]) {
        const c = e2.cloneNode(true); c.classList.add('hot-clone'); c.classList.remove('faint');
        if (c.dataset.marker) { c.setAttribute('marker-end', c.dataset.marker); if (c.classList.contains('k-has')) c.setAttribute('marker-start', 'url(#m-dia)'); }
        overlay.append(c);
      }
    }
  };
  let hovered = null;
  scene.el.addEventListener('mouseover', (e) => { const b = e.target.closest('.nb'); const id = b ? b.dataset.id : null; if (id !== hovered) { hovered = id; highlight(id); } });
  scene.el.addEventListener('mouseleave', () => { hovered = null; highlight(null); });
  scene.sizes = sizes;
  scene.netRects = rects;
  scene.depthMax = depthMax;
  scene.effective = effective;
  return scene;
}

function outlineFor(path) { return OUTLINES[path] || null; }
const PANEL_MODULES = 30;
let refreshTimer = null;
function refreshSoon(refresh) {
  if (!refresh || refreshTimer) return;
  refreshTimer = setTimeout(() => { refreshTimer = null; refresh(); }, 60);
}
function foldedRows(effective, refresh) {
  const N = net();
  const rows = [];
  const addItem = (it, path, cls) => {
    const qual = cls ? `${cls}.${it.name}` : it.name;
    for (const [no, text] of it.decorators || []) rows.push({ no, text });
    if (it.kind === 'imports') rows.push({ no: it.no, text: it.text, fold: it.count > 1 ? `+${it.count - 1} more imports` : null });
    else if (it.kind === 'doc') rows.push({ no: it.no, text: it.text, fold: it.multi ? 'docstring' : null });
    else if (it.kind === 'stmt') rows.push({ no: it.no, text: it.text, fold: it.multi ? '⋯' : null });
    else if (it.kind === 'def') { const id = cls ? `m:${path}:${qual}` : `fn:${path}:${qual}`; rows.push({ no: it.no, text: it.text, fold: 'body', id: N.nodes.has(id) ? id : null, def: true }); }
    else if (it.kind === 'class') {
      const id = `cls:${path}:${qual}`;
      const open = effective.has(id);
      rows.push({ no: it.no, text: it.text, fold: open ? null : 'body', id: N.nodes.has(id) ? id : null, cls: true, open });
      if (open) for (const b of it.body) addItem(b, path, qual);
    }
  };
  const open = [...N.nodes.values()].filter((n) => n.kind === 'module' && effective.has(n.id));
  for (const m of open.slice(0, PANEL_MODULES)) {
    rows.push({ banner: true, text: m.path, id: m.id });
    const ol = outlineFor(m.path);
    if (!ol) { rows.push({ text: '    reading…', dim: true }); ensureOutline(m.path).then(() => refreshSoon(refresh), () => {}); continue; }
    for (const it of ol) addItem(it, m.path, null);
  }
  if (open.length > PANEL_MODULES) rows.push({ text: `    … and ${open.length - PANEL_MODULES} more open modules. Fold some boxes on the map to read their code here.`, dim: true });
  return rows;
}
function netPanel(container, selId, ctx, effective) {
  container.querySelectorAll(':scope > :not(.resize-bar)').forEach((c) => c.remove());
  const N = net();
  const ex = el('div', { class: 'explain' });
  const panel = el('div', { class: 'code-panel' }, ex);
  container.append(panel);
  const n = selId ? N.nodes.get(selId) : null;
  if (n) {
    const what = n.children.length ? summaryOf(n) : n.sym ? `${n.sym.params.filter((p) => p[0] !== 'self').length} parameters` : n.type ? n.type.label : '';
    const text = `${netLabel(selId)}. ${n.kind}${moduleOf(selId) ? ` in ${moduleOf(selId)}` : ''}. ${what}.`;
    ex.append(el('div', { class: 'kind' }, n.kind), el('h2', {}, netLabel(selId)), el('p', {}, what));
    ex.append(el('div', { class: 'actions' }, el('button', { class: 'btn small', onclick: () => speak(text) }, '🔊 Read aloud')));
  } else {
    ex.append(el('div', { class: 'kind' }, 'Code'), el('h2', {}, 'Folded to match the map'));
    ex.append(el('p', {}, 'This is the real code of every open module, folded to the level you have expanded. Click a class line to expand or fold it here and in the map. Click a def line to open its dataflow view.'));
    if (OVERVIEW) ex.append(el('p', { style: 'color:var(--fg-dim);font-size:0.9em' }, `${OVERVIEW.root} · ${plural(OVERVIEW.modules.length, 'module')}${OVERVIEW.failures && OVERVIEW.failures.length ? ` · ${OVERVIEW.failures.length} could not be read` : ''}`));
  }
  const cv = el('div', { class: 'code-view folded' });
  for (const r of foldedRows(effective || new Set(), ctx.refresh)) {
    const row = el('div', { class: `ln ${r.banner ? 'banner' : ''} ${r.id ? 'clickable' : ''} ${r.dim ? 'dimrow' : ''} ${r.id && r.id === selId ? 'hl' : ''}`, 'data-id': r.id || null },
      el('span', { class: 'no' }, r.banner ? (effective.has(r.id) ? '▾' : '▸') : r.no || ''),
      el('span', {}, r.text || ' '),
      r.fold ? el('span', { class: 'fold-chip', title: r.fold === 'body' ? 'Folded' : r.fold }, r.fold === 'body' ? '⋯' : r.fold) : null);
    if (r.id) {
      row.addEventListener('click', () => {
        const node = N.nodes.get(r.id);
        if (r.def && node && node.sym) ctx.go(refOf(node.sym));
        else { ctx.select(r.id); if (node && node.children.length) ctx.toggle(r.id); }
      });
      row.addEventListener('mouseenter', () => { const b = document.querySelector(`.viewport .nb[data-id="${CSS.escape(r.id)}"]`); if (b) b.classList.add('code-hover'); });
      row.addEventListener('mouseleave', () => document.querySelectorAll('.viewport .code-hover').forEach((b) => b.classList.remove('code-hover')));
    }
    cv.append(row);
  }
  panel.append(cv);
  const hl = cv.querySelector('.hl'); if (hl) requestAnimationFrame(() => hl.scrollIntoView({ block: 'nearest' }));
}

class Viewport {
  constructor(host) {
    this.host = host; this.s = 1; this.x = 0; this.y = 0;
    this.world = el('div', { class: 'world' }); host.append(this.world);
    this.pct = el('span', { class: 'pct' }, '100%');
    let drag = null;
    host.addEventListener('pointerdown', (e) => { if (e.target.closest('.node, button, .zoom-ctl')) return; drag = { x: e.clientX, y: e.clientY, ox: this.x, oy: this.y, moved: false }; host.setPointerCapture(e.pointerId); host.classList.add('dragging'); });
    host.addEventListener('pointermove', (e) => { if (!drag) return; const dx = e.clientX - drag.x, dy = e.clientY - drag.y; if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true; this.x = drag.ox + dx; this.y = drag.oy + dy; this.apply(); });
    host.addEventListener('pointerup', () => { if (drag && !drag.moved && this.onBackground) this.onBackground(); drag = null; host.classList.remove('dragging'); });
    host.addEventListener('wheel', (e) => { e.preventDefault(); const r = host.getBoundingClientRect(); this.zoomAt(e.clientX - r.left, e.clientY - r.top, Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0015))); }, { passive: false });
    host.append(el('div', { class: 'zoom-ctl' }, this.pct,
      el('button', { class: 'btn small', title: 'Zoom out', onclick: () => this.zoomCentre(1 / 1.2) }, '−'),
      el('button', { class: 'btn small', title: 'Zoom in', onclick: () => this.zoomCentre(1.2) }, '+'),
      el('button', { class: 'btn small', title: 'Back to 100%', onclick: () => this.start() }, '1:1'),
      el('button', { class: 'btn small', title: 'Fit everything on screen', onclick: () => this.fit() }, 'Fit')));
  }
  setScene(scene, how = 'start') { this.world.innerHTML = ''; this.scene = scene; this.world.append(scene.el); if (how === 'start') this.start(); else if (how === 'fit') this.fit(); this.apply(); }
  apply() {
    this.world.style.transform = `translate(${this.x}px, ${this.y}px) scale(${this.s})`;
    const g = 16 * this.s, G2 = g * 8;
    this.host.style.backgroundSize = `${G2}px ${G2}px, ${G2}px ${G2}px, ${g}px ${g}px, ${g}px ${g}px`;
    this.host.style.backgroundPosition = `${this.x}px ${this.y}px`;
    this.pct.textContent = `${Math.round(this.s * 100)}%`;
  }
  zoomAt(px, py, f) { const ns = Math.min(2.5, Math.max(0.15, this.s * f)); f = ns / this.s; this.x = px - (px - this.x) * f; this.y = py - (py - this.y) * f; this.s = ns; this.apply(); }
  zoomCentre(f) { this.zoomAt(this.host.clientWidth / 2, this.host.clientHeight / 2, f); }
  fit() { if (!this.scene) return; const W = this.host.clientWidth, H = this.host.clientHeight; this.s = Math.min(1.2, Math.max(0.15, Math.min(W / this.scene.width, (H - 40) / this.scene.height))); this.x = (W - this.scene.width * this.s) / 2; this.y = Math.max(20, (H - this.scene.height * this.s) / 2); this.apply(); }
  start() { if (!this.scene) return; const W = this.host.clientWidth, H = this.host.clientHeight; const fitS = Math.min(W / this.scene.width, (H - 60) / this.scene.height); this.s = Math.max(0.75, Math.min(1, fitS)); this.x = this.scene.width * this.s <= W ? (W - this.scene.width * this.s) / 2 : 0; this.y = this.scene.height * this.s <= H - 60 ? (H - this.scene.height * this.s) / 2 : 30; this.apply(); }
  centreOn(elm) { const r = elm.getBoundingClientRect(), hr = this.host.getBoundingClientRect(); this.x += hr.left + hr.width / 2 - (r.left + r.width / 2); this.y += hr.top + hr.height / 2 - (r.top + r.height / 2); this.apply(); }
}

function describe(n) {
  const ins = n.ins.map((p) => p.name).filter(Boolean);
  const outs = n.outs.map((o) => o.name).filter(Boolean);
  switch (n.kind) {
    case 'entry': return `The function starts here. It takes ${outs.join(', ') || 'nothing'}.`;
    case 'break': return `Reads ${outs.join(', ')} out of ${ins[0]}.`;
    case 'make': return `Builds a new ${n.title.slice(5)} from ${ins.join(', ')}.`;
    case 'select': return n.ins.length > 3 ? `Picks one value depending on ${ins[0]}: ${ins.slice(1).join(', ')}. ${n.note || ''}` : 'Gives back "if true" when the condition holds, otherwise "if false". This is how an if-and-return shows up as dataflow.';
    case 'branch': return 'Decides which way the white execution line goes next: True or False.';
    case 'return': return `Gives back ${ins.length ? n.ins[0].type.label : 'nothing'} to whoever called this function.`;
    case 'op': return `${n.title}: works out a ${n.outs[0] ? n.outs[0].type.label : 'value'} from its inputs.`;
    case 'lit': return `The fixed value ${n.title}.`;
    case 'var': return `Reads ${n.title}, which is defined at module level.`;
    case 'set': return `Stores a value as ${n.title.slice(4)}, so other methods can use it later.`;
    case 'raise': return `Stops with an error. ${n.note || ''}`;
    default: return `Calls ${n.title}${ins.length ? ` with ${ins.join(', ')}` : ''}${outs.length ? `, giving ${outs.join(', ')}` : ''}.${n.note ? ' ' + n.note + '.' : ''}`;
  }
}
function speak(text) { try { speechSynthesis.cancel(); const u = new SpeechSynthesisUtterance(text.replace(/_/g, ' ').replace(/\./g, ' ')); u.rate = 0.95; speechSynthesis.speak(u); } catch (e) {} }

function codePanel(container, sym, node, ctx) {
  container.querySelectorAll(':scope > :not(.resize-bar)').forEach((c) => c.remove());
  const panel = el('div', { class: 'code-panel' });
  container.append(panel);
  const ex = el('div', { class: 'explain' });
  panel.append(ex);
  if (!sym) { ex.append(el('div', { class: 'kind' }, 'Code'), el('p', {}, 'Click a node to see its line of code. Press ⧉ on a call (or double-click it) to unfold its code right there. Press Go into on an unfolded frame to make it the whole view; ← takes you back with everything still unfolded.')); return; }
  if (node) {
    ex.append(el('div', { class: 'kind' }, KIND[node.kind] ? KIND[node.kind][1] : 'Node'), el('h2', {}, node.kind === 'entry' ? sym.name : node.title));
    const text = describe(node);
    ex.append(el('p', {}, text));
    const acts = el('div', { class: 'actions' }, el('button', { class: 'btn small', onclick: () => speak(text) }, '🔊 Read aloud'));
    if (node.target && lookup(node.target) && node.kind !== 'entry') acts.append(el('button', { class: 'btn small', onclick: () => ctx.activate(node.target, null, null) }, node.target.path === sym.file ? 'Go into it' : `Go into it (${baseName(node.target.path)})`));
    ex.append(acts);
  } else {
    ex.append(el('div', { class: 'kind' }, sym.kind === 'function' ? (sym.owner ? `method of ${sym.owner}` : 'function') : sym.kind === 'enum' ? 'enum' : 'class'), el('h2', {}, sym.qual));
    if (sym.kind === 'function') {
      const callers = callersOf(refOf(sym));
      const isTest = (c) => /(^|\/)(tests?|testing)\/|(^|\/)test_[^/]*$|_test\.py$/.test(c.path);
      callers.sort((a, b) => Number(isTest(a)) - Number(isTest(b)) || a.path.localeCompare(b.path) || a.sym.localeCompare(b.sym));
      const shown = callers.slice(0, 8);
      if (callers.length) ex.append(el('div', { class: 'kind' }, 'Called from'), el('div', { class: 'links' }, shown.map((c) => el('button', { onclick: () => ctx.activate(c, null, null) }, `${c.sym} · ${baseName(c.path)}`)), callers.length > shown.length ? el('span', { class: 'udim' }, `and ${callers.length - shown.length} more`) : null));
    }
  }
  const codeRows = sym.codeLines || (sym.code ? sym.code.split('\n').map((t, i) => [sym.line + i, t]) : null);
  if (codeRows) {
    const line = node ? node.line : null;
    const cv = el('div', { class: 'code-view' });
    codeRows.forEach(([no, ln]) => { cv.append(el('div', { class: `ln ${line && no === line && node.kind !== 'entry' ? 'hl' : ''}` }, el('span', { class: 'no' }, no), el('span', {}, ln || ' '))); });
    panel.append(cv);
    const hl = cv.querySelector('.hl'); if (hl) requestAnimationFrame(() => hl.scrollIntoView({ block: 'nearest' }));
  }
}

function legendInto(container) {
  container.append(el('div', { class: 'kind', style: 'font-size:0.72em;letter-spacing:0.08em;text-transform:uppercase;color:var(--fg-dim)' }, 'File diagram lines'));
  const line = (kind, dashed, label) => container.append(el('div', { class: 'legend-row legend-line' }, el('span', { html: `<svg viewBox="0 0 46 12"><path d="M2,6 H38" style="stroke:var(--rel-${kind === 'realizes' ? 'inherits' : kind})" stroke-width="2" ${dashed ? 'stroke-dasharray="6 4"' : ''}/>${kind === 'inherits' || kind === 'realizes' ? '<path d="M36,1 L45,6 L36,11 z" style="fill:var(--canvas);stroke:var(--rel-inherits)" stroke-width="1.4"/>' : `<path d="M37,1 L45,6 L37,11" style="fill:none;stroke:var(--rel-${kind})" stroke-width="1.6"/>`}${kind === 'has' ? '<path d="M1,6 L6,2.5 L11,6 L6,9.5 z" style="fill:var(--rel-has)"/>' : ''}</svg>` }), el('span', {}, label)));
  line('inherits', false, 'builds on (inherits)'); line('realizes', true, 'implements a protocol'); line('has', false, 'has a field of that type'); line('creates', true, 'creates one'); line('calls', true, 'calls it'); line('uses', true, 'takes or returns it'); line('reads', true, 'reads a field (inside a class)'); line('writes', true, 'sets a field (inside a class)');
  container.append(el('div', { class: 'kind', style: 'font-size:0.72em;letter-spacing:0.08em;text-transform:uppercase;color:var(--fg-dim);margin-top:6px' }, 'Function view'));
  const rows = [['bool', 'bool'], ['int', 'int'], ['float', 'float'], ['str', 'str, Path'], ['enum', 'Enum'], ['struct', 'dataclass / model'], ['object', 'object'], ['map', 'dict, Mapping'], ['list', 'list, tuple'], ['callable', 'callable'], ['time', 'datetime'], ['none', 'None / unknown']];
  container.append(el('div', { class: 'legend-row' }, el('span', { class: 'shape', html: shapeSVG(null) }), el('span', {}, 'execution order ', el('small', {}, 'white wire'))));
  for (const [cat, code] of rows) container.append(el('div', { class: 'legend-row' }, el('span', { class: 'shape', html: shapeSVG({ cat }) }), el('small', {}, code)));
}
function popoverButton(label, cls, fill) {
  const btn = el('button', { class: 'btn' }, label);
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    const existing = document.querySelector(`.popover.${cls}`); document.querySelectorAll('.popover').forEach((p) => p.remove()); if (existing) return;
    const r = btn.getBoundingClientRect();
    const pop = el('div', { class: `popover ${cls}`, style: `top:${r.bottom + 6}px; right:max(12px, ${window.innerWidth - r.right}px)`, onclick: (ev) => ev.stopPropagation() });
    fill(pop); document.body.append(pop);
  });
  return btn;
}
function settingsButton(onChange) {
  return popoverButton('Aa Reading', 'settings', (pop) => {
    const done = () => { saveSettings(); applySettings(); onChange(); };
    const sel = (id, value, opts, fn2) => el('select', { id, onchange: (ev) => fn2(ev.target.value) }, opts.map(([v, l]) => { const o = el('option', { value: v }, l); if (String(v) === String(value)) o.selected = true; return o; }));
    const chk = (id, value, fn2) => { const c = el('input', { type: 'checkbox', id, onchange: (ev) => fn2(ev.target.checked) }); c.checked = value; return c; };
    pop.append(
      el('label', { for: 'set-font' }, 'Label font', sel('set-font', settings.pinFont, [['mono', 'Monospace'], ['lexend', 'Lexend'], ['atkinson', 'Atkinson Hyperlegible'], ['comic', 'Comic Neue']], (v) => { settings.pinFont = v; done(); })),
      el('label', { for: 'set-size' }, 'Node text', sel('set-size', settings.size, [[11, 'Small'], [12.5, 'Normal'], [14, 'Large'], [16, 'Extra large']], (v) => { settings.size = +v; done(); })),
      el('label', { for: 'set-theme' }, 'Background', sel('set-theme', settings.theme, [['dark', 'Dark'], ['light', 'Soft paper'], ['system', 'Match device']], (v) => { settings.theme = v; done(); })),
      el('label', { for: 'set-plain' }, 'Spaced-out names', chk('set-plain', settings.plain, (v) => { settings.plain = v; done(); })),
      el('label', { for: 'set-types' }, 'Type names on pins', chk('set-types', settings.types, (v) => { settings.types = v; done(); })));
  });
}
document.addEventListener('click', () => document.querySelectorAll('.popover').forEach((p) => p.remove()));

function openPalette(onPick) {
  document.querySelectorAll('.palette').forEach((p) => p.remove());
  const items = [];
  for (const f of Object.values(FILES)) {
    items.push({ k: 'file', name: baseName(f.path), where: f.path, ref: { path: f.path, sym: null } });
    for (const s of Object.values(f.index)) items.push({ k: s.kind === 'function' ? (s.owner ? 'method' : 'function') : 'type', name: s.qual, where: shortFile(f.path), ref: refOf(s) });
  }
  const input = el('input', { id: 'palette-input', placeholder: 'file, class or function…', autocomplete: 'off' });
  const results = el('div', { class: 'results' });
  const pal = el('div', { class: 'palette', onclick: (e) => e.stopPropagation() }, input, results);
  let on = 0, shown = [];
  const render = () => {
    const q = input.value.toLowerCase().replace(/[\s_]+/g, '');
    shown = items.filter((i) => (i.name + i.where).toLowerCase().replace(/[\s_]+/g, '').includes(q)).slice(0, 40);
    on = Math.max(0, Math.min(on, shown.length - 1));
    results.innerHTML = '';
    shown.forEach((i, ix) => results.append(el('button', { class: `res ${ix === on ? 'on' : ''}`, onclick: () => { pal.remove(); onPick(i.ref); } }, el('span', { class: 'k' }, i.k), el('span', {}, i.name), el('span', { class: 'where' }, i.where))));
  };
  input.addEventListener('input', () => { on = 0; render(); });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') { on = Math.min(shown.length - 1, on + 1); render(); e.preventDefault(); }
    if (e.key === 'ArrowUp') { on = Math.max(0, on - 1); render(); e.preventDefault(); }
    if (e.key === 'Enter' && shown[on]) { pal.remove(); onPick(shown[on].ref); }
    if (e.key === 'Escape') pal.remove();
  });
  setTimeout(() => document.addEventListener('click', () => pal.remove(), { once: true }), 0);
  render(); document.body.append(pal); input.focus();
}

function shell(root, { extraButtons, onPick, onSettings }) {
  const crumbs = el('div', { class: 'crumbs' });
  const left = el('div', { class: 'panel left' });
  const right = el('div', { class: 'panel right' });
  root.append(el('div', { class: 'topbar' },
    el('div', { class: 'brand' }, 'Code Blueprints', el('small', {}, OVERVIEW ? OVERVIEW.name : '')),
    el('button', { class: 'btn phone-only', onclick: () => { left.hidden = !left.hidden; } }, 'Files'),
    ...extraButtons,
    el('button', { class: 'btn', title: 'Find a file or symbol (/)', 'data-find': true, onclick: () => openPalette(onPick) }, '⌕ Find'),
    crumbs, popoverButton('● Key', 'legend', legendInto), settingsButton(onSettings),
    el('button', { class: 'btn', title: 'Show or hide the code panel', onclick: () => { right.hidden = !right.hidden; } }, '⌄ Code')));
  const row = el('div', { class: 'body-row' });
  const vpHost = el('div', { class: 'viewport' });
  const bar = el('div', { class: 'resize-bar', title: 'Drag to resize the code panel' });
  right.append(bar);
  const mainCol = el('div', { class: 'main-col' }, vpHost, right);
  row.append(left, mainCol);
  root.append(row);
  try { const saved = localStorage.getItem(`${SETTINGS_KEY}-bottom`); if (saved) right.style.setProperty('--bottom-h', saved); } catch (e) {}
  bar.addEventListener('pointerdown', (e) => {
    e.preventDefault();
    bar.setPointerCapture(e.pointerId);
    const colRect = mainCol.getBoundingClientRect();
    const move = (ev) => { const h = Math.min(colRect.height * 0.75, Math.max(90, colRect.bottom - ev.clientY)); right.style.setProperty('--bottom-h', `${Math.round(h)}px`); };
    const up = () => { bar.removeEventListener('pointermove', move); bar.removeEventListener('pointerup', up); try { localStorage.setItem(`${SETTINGS_KEY}-bottom`, right.style.getPropertyValue('--bottom-h')); } catch (err) {} };
    bar.addEventListener('pointermove', move);
    bar.addEventListener('pointerup', up);
  });
  if (window.innerWidth <= 760) { left.hidden = true; }
  return { crumbs, left, right, vpHost };
}
const TREE_OPEN = new Set();
function renderTree(left, currentPath, currentSym, onPick) {
  left.innerHTML = '';
  left.append(el('h3', {}, OVERVIEW ? OVERVIEW.name : 'Files'));
  if (currentPath) { let acc = ''; for (const part of currentPath.split('/').slice(0, -1)) { acc += (acc ? '/' : '') + part; TREE_OPEN.add(acc); } }
  const treeRoot = { dirs: {}, files: [] };
  for (const path of Object.keys(FILES)) {
    let node = treeRoot;
    const parts = path.split('/');
    for (const part of parts.slice(0, -1)) node = node.dirs[part] = node.dirs[part] || { dirs: {}, files: [] };
    node.files.push(path);
  }
  const box = el('div', { class: 'tree' });
  const draw = (node, prefix, depth) => {
    for (const name of Object.keys(node.dirs).sort()) {
      const full = prefix ? `${prefix}/${name}` : name;
      const isOpen = TREE_OPEN.has(full);
      box.append(el('button', { class: 'tree-item folder', style: `padding-left:${12 + depth * 14}px`, onclick: () => { if (isOpen) TREE_OPEN.delete(full); else TREE_OPEN.add(full); renderTree(left, currentPath, currentSym, onPick); } }, `${isOpen ? '▾' : '▸'} ${name}/`));
      if (isOpen) draw(node.dirs[name], full, depth + 1);
    }
    for (const path of node.files.sort()) box.append(el('button', { class: `tree-item ${path === currentPath ? 'active' : ''}`, style: `padding-left:${26 + depth * 14}px`, title: path, onclick: () => onPick({ path, sym: null }) }, baseName(path)));
  };
  draw(treeRoot, '', 0);
  left.append(box);
  const f = currentPath ? FILES[currentPath] : null;
  if (!f) return;
  left.append(el('h3', {}, `In ${baseName(currentPath)}`));
  for (const s of f.symbols) {
    const color = s.kind === 'function' ? '--h-call' : s.kind === 'enum' ? '--h-enum' : '--h-make';
    left.append(el('button', { class: `tree-item ${currentSym === s.qual ? 'active' : ''}`, onclick: () => onPick(refOf(s)) }, el('span', { class: 'dot', style: `background:var(${color})` }), s.name));
    for (const m of s.methods || []) left.append(el('button', { class: `tree-item ${currentSym === m.qual ? 'active' : ''}`, style: 'padding-left:32px', onclick: () => onPick(refOf(m)) }, el('span', { class: 'dot', style: 'background:var(--h-method)' }), m.name));
  }
}

function crumbsFor(crumbs, path, sym, onPick, extra) {
  crumbs.innerHTML = '';
  if (!path) { crumbs.append(el('span', { class: 'here' }, OVERVIEW ? OVERVIEW.name : '')); if (extra) crumbs.append(extra); return; }
  if (path.includes('/')) crumbs.append(el('span', {}, path.split('/').slice(-3, -1).join('/') + '/'));
  crumbs.append(el('button', { onclick: () => onPick({ path, sym: null }) }, baseName(path)));
  if (sym) { const s = lookup({ path, sym }); if (s && s.owner) crumbs.append(el('span', {}, '›'), el('button', { onclick: () => onPick({ path, sym: s.owner }) }, s.owner)); crumbs.append(el('span', {}, '›'), el('span', { class: 'here' }, s ? s.name : sym)); }
  if (extra) crumbs.append(extra);
}

let sizeWatcher = null;
function watchSizes(entries, relayout) {
  if (sizeWatcher) sizeWatcher.disconnect();
  if (typeof ResizeObserver === 'undefined') return;
  let pending = false;
  sizeWatcher = new ResizeObserver(() => {
    if (pending) return;
    if (!entries.some((s) => Math.abs(s.el.offsetWidth - s.w) > 1 || Math.abs(s.el.offsetHeight - s.h) > 1)) return;
    pending = true; sizeWatcher.disconnect(); requestAnimationFrame(relayout);
  });
  entries.forEach((s) => sizeWatcher.observe(s.el));
}
function messageScene(text) {
  const box = el('div', { class: 'scene-message' }, text);
  return { el: box, width: 480, height: 80, nodes: [], sizes: [] };
}
const SIDE_PACKAGES = /^(tests?|testing|docs?|examples?|scripts?|benchmarks?|tools?|\.?venv|build|dist)$/i;
function moduleCount(n) { return n.kind === 'module' ? 1 : n.children.reduce((sum, k) => sum + (k.kind === 'package' || k.kind === 'module' ? moduleCount(k) : 0), 0); }
function startExpanded() {
  const ex = new Set();
  let n = net().root;
  for (let i = 0; i < 8; i++) {
    const kids = n.children.filter((k) => k.kind === 'package' || k.kind === 'module');
    const main = kids.filter((k) => !SIDE_PACKAGES.test(k.name)).sort((a, b) => moduleCount(b) - moduleCount(a));
    const pick = main.length === 1 ? main[0] : main.length > 1 && moduleCount(main[0]) > 0.6 * main.reduce((s, k) => s + moduleCount(k), 0) ? main[0] : null;
    if (!pick || !pick.children.length || (pick.kind === 'module' && ex.size)) break;
    ex.add(pick.id);
    n = pick;
    if (pick.children.filter((k) => k.kind === 'package' || k.kind === 'module').length > 1) break;
  }
  return ex;
}
function Explorer(root) {
  const start = { view: 'net', expanded: startExpanded(), focus: null, open: new Set() };
  const st = { stack: [start], fwd: [], selected: null };
  const cur = () => st.stack[st.stack.length - 1];
  const lastNet = () => [...st.stack].reverse().find((e) => e.view === 'net') || start;
  const back = el('button', { class: 'btn', title: 'Back (Alt+←)', onclick: () => { if (st.stack.length > 1) { st.fwd.push(st.stack.pop()); st.selected = null; render(false); } } }, '←');
  const fwd = el('button', { class: 'btn', title: 'Forward (Alt+→)', onclick: () => { if (st.fwd.length) { st.stack.push(st.fwd.pop()); st.selected = null; render(false); } } }, '→');
  const deeper = el('button', { class: 'btn', title: 'Expand every box at the deepest open level', onclick: () => { const s = currentScene; if (!s.netRects) return; for (const [id] of s.netRects) { const n = net().nodes.get(id); if (n.depth === s.depthMax + 1 && n.children.length) cur().expanded.add(id); } render(true); } }, '⊕ Expand a level');
  const shallower = el('button', { class: 'btn', title: 'Collapse the deepest open level', onclick: () => { const s = currentScene; if (!s.netRects) { cur().open.clear(); render(true); return; } for (const id of [...cur().expanded]) if (net().nodes.get(id).depth === s.depthMax) cur().expanded.delete(id); render(true); } }, '⊖ Collapse a level');
  const openOther = el('button', { class: 'btn', title: 'Open another project folder', onclick: () => showWelcome() }, 'Open…');
  const reload = el('button', { class: 'btn', title: 'Read the project again after editing code', onclick: () => { api('/api/reload').then(() => waitForProject(), (err) => showWelcome(err.message)); } }, '↻ Reload');
  const ui = shell(root, { extraButtons: [openOther, reload, back, fwd, deeper, shallower], onPick: (r) => go(r), onSettings: () => render(true) });
  const vp = new Viewport(ui.vpHost);
  vp.onBackground = () => { st.selected = null; document.querySelectorAll('.node.selected').forEach((n) => n.classList.remove('selected')); panel(); };
  const unfolding = [];
  const keyOf = (owner, n) => `${owner}>${n.target.path}::${n.target.sym}@${n.line || ''}:${n.title}`;
  function go(ref) {
    const sym = ref.sym ? lookup(ref) : null;
    if (sym && sym.kind === 'function') { st.stack.push({ view: 'fn', path: ref.path, sym: ref.sym, open: new Set() }); st.fwd = []; st.selected = null; render(false); return; }
    const target = ref.sym ? `cls:${ref.path}:${ref.sym}` : `mod:${ref.path}`;
    const expanded = new Set(lastNet().expanded);
    if (!ref.sym) { expanded.clear(); netDefaultExpanded(ref.path).forEach((x) => expanded.add(x)); }
    else { net().chain(target).slice(1).forEach((x) => expanded.add(x.id)); }
    st.stack.push({ view: 'net', expanded, focus: target, open: new Set() }); st.fwd = []; st.selected = ref.sym ? target : null; render(false);
  }
  function toggleNet(id) {
    const target = net().nodes.get(id);
    if (!target || !target.children.length) { render(true); return; }
    const before = document.querySelector(`.viewport .nb[data-id="${CSS.escape(id)}"]`);
    const r0 = before ? before.getBoundingClientRect() : null;
    const ex = cur().expanded;
    if (ex.has(id)) ex.delete(id); else ex.add(id);
    render(true);
    const after = document.querySelector(`.viewport .nb[data-id="${CSS.escape(id)}"]`);
    if (r0 && after) { const r1 = after.getBoundingClientRect(); vp.x += r0.left - r1.left; vp.y += r0.top - r1.top; vp.apply(); }
  }
  function toggle(k, button) {
    const open = cur().open;
    const r0 = button.closest('.node').getBoundingClientRect();
    const opening = !open.has(k);
    if (opening) open.add(k); else [...open].forEach((x) => { if (x.startsWith(k)) open.delete(x); });
    render(true);
    const after = document.querySelector(`[data-unfold="${CSS.escape(k)}"]`);
    if (!after) return;
    const r1 = after.closest('.node').getBoundingClientRect(); vp.x += r0.left - r1.left; vp.y += r0.top - r1.top; vp.apply();
    const emb = opening ? after.closest('.node').querySelector('.embed') : null;
    if (emb) {
      const er = emb.getBoundingClientRect(), hr = ui.vpHost.getBoundingClientRect();
      if (er.right > hr.right - 20) vp.x -= Math.max(0, Math.min(er.right - hr.right + 40, er.left - hr.left - 20));
      if (er.bottom > hr.bottom - 70) vp.y -= Math.max(0, Math.min(er.bottom - hr.bottom + 90, er.top - hr.top - 60));
      vp.apply();
    }
  }
  function makeCtx(owner) {
    return {
      openButton: (n) => {
        const k = keyOf(owner, n);
        const isOpen = cur().open.has(k);
        return el('button', { class: `open ${isOpen ? 'on' : ''}`, 'data-unfold': k, title: isOpen ? 'Fold away' : 'Unfold here', html: OPEN_ICON, onclick: (e) => { e.stopPropagation(); toggle(k, e.currentTarget); } });
      },
      activate: (ref, n, v) => { const btn = v && v.el.querySelector(':scope > .box > .head [data-unfold]'); if (btn) btn.click(); else go(ref); },
      select: (n, v, sym) => { document.querySelectorAll('.node.selected').forEach((q) => q.classList.remove('selected')); if (v) v.el.classList.add('selected'); st.selected = { n, sym }; panel(); if (window.innerWidth <= 760) ui.right.hidden = false; },
      afterNode: (n, v) => { if (!n.target || n.kind === 'entry') return; const emb = embedFor(keyOf(owner, n), n.target); if (emb) v.el.querySelector('.embed-slot').append(emb); },
    };
  }
  function embedFor(k, ref) {
    if (!cur().open.has(k)) return null;
    const sym = lookup(ref);
    if (!sym || sym.kind !== 'function') return null;
    const wrap = el('div', { class: 'embed' });
    wrap.append(el('div', { class: 'embed-label' },
      el('span', {}, ref.path !== cur().path ? `↗ ${shortFile(ref.path)} · ${sym.qual}` : sym.qual),
      el('button', { class: 'btn small go-into', title: 'Make this the whole view', onclick: (e) => { e.stopPropagation(); go(ref); } }, 'Go into ↘')));
    if (!FUNCTIONS.has(fnKey(ref))) { const note = el('div', { class: 'note', style: 'padding:30px 10px 6px' }, 'Reading…'); wrap.append(note); ensureFunction(ref).then(() => render(true), (err) => { note.textContent = err.message; }); return wrap; }
    const id = ref.path + ref.sym;
    if (unfolding.includes(id) || unfolding.length > 5) { wrap.append(el('div', { class: 'note', style: 'padding:30px 10px 6px' }, 'Already unfolded further out.')); return wrap; }
    unfolding.push(id);
    const inner = buildFunctionScene(sym, makeCtx(k));
    unfolding.pop();
    wrap.append(inner.el);
    return wrap;
  }
  const netCtx = { refresh: () => { if (cur().view === 'net') panel(); }, go: (ref) => go(ref), toggle: (id) => toggleNet(id), select: (id) => { st.selected = id; panel(); if (window.innerWidth <= 760) ui.right.hidden = false; } };
  let currentScene = null;
  function panel() {
    if (cur().view === 'net') { netPanel(ui.right, typeof st.selected === 'string' ? st.selected : null, netCtx, currentScene && currentScene.effective); return; }
    const ctx = { ...makeCtx('root'), activate: (ref) => go(ref) };
    if (st.selected && st.selected.n) codePanel(ui.right, st.selected.sym, st.selected.n, ctx);
    else codePanel(ui.right, lookup(cur()), null, ctx);
  }
  let relayouts = 0;
  function render(keepView) {
    const c = cur();
    const isNet = c.view === 'net';
    back.disabled = st.stack.length < 2; fwd.disabled = !st.fwd.length;
    deeper.hidden = !isNet;
    shallower.textContent = isNet ? '⊖ Collapse a level' : '⊟ Fold all';
    const focusPath = isNet ? (net().nodes.get(c.focus) && net().chain(c.focus).find((n) => n.kind === 'module') || {}).path || null : c.path;
    renderTree(ui.left, focusPath, isNet ? null : c.sym, go);
    crumbsFor(ui.crumbs, focusPath, isNet ? null : c.sym, go, isNet ? el('span', { style: 'margin-left:8px' }, `· ${c.expanded.size} open`) : c.open.size ? el('span', { style: 'margin-left:8px' }, `· ${c.open.size} unfolded`) : null);
    if (!isNet && !FUNCTIONS.has(fnKey(c))) {
      if (!c.error) ensureFunction(c).then(() => { if (cur() === c) render(keepView === 'relayout' ? true : keepView); }, (err) => { c.error = err.message; if (cur() === c) render(keepView); });
      currentScene = messageScene(c.error ? `Could not draw ${c.sym}: ${c.error}` : `Reading ${c.sym}…`);
      vp.setScene(currentScene, 'none'); vp.s = 1; vp.x = 40; vp.y = 40; vp.apply();
      panel();
      return;
    }
    const keep = { x: vp.x, y: vp.y, s: vp.s };
    currentScene = isNet ? buildNetScene(c.expanded, netCtx) : buildFunctionScene(lookup(c), makeCtx('root'));
    vp.setScene(currentScene, keepView ? 'none' : 'start');
    if (keepView) { Object.assign(vp, keep); vp.apply(); }
    else if (isNet && c.focus) { const f = currentScene.el.querySelector(`.nb[data-id="${CSS.escape(c.focus)}"]`); vp.fit(); if (f && vp.s < 0.6) { vp.s = 0.85; vp.apply(); const r = f.getBoundingClientRect(), hr = ui.vpHost.getBoundingClientRect(); vp.x += hr.left + 40 - r.left; vp.y += hr.top + 60 - r.top; vp.apply(); } if (f) f.classList.add('flash'); }
    panel();
    relayouts = keepView === 'relayout' ? relayouts + 1 : 0;
    const sizes = currentScene.sizes || currentScene.nodes.map((n) => ({ el: n.el, w: n.w, h: n.h }));
    if (relayouts < 3) watchSizes(sizes, () => { if (cur() === c) render('relayout'); });
  }
  render(false);
  return { keys: (e) => { if (e.altKey && e.key === 'ArrowLeft') back.click(); if (e.altKey && e.key === 'ArrowRight') fwd.click(); } };
}
let explorerApi = null;
document.addEventListener('keydown', (e) => {
  if (e.target.closest && e.target.closest('input, textarea, select, [contenteditable]')) return;
  if (explorerApi) explorerApi.keys(e);
  if (e.key === '/') { e.preventDefault(); const f = document.querySelector('[data-find]'); if (f) f.click(); }
});
function screen(...kids) {
  const app = document.getElementById('app');
  app.innerHTML = '';
  document.getElementById('measure').innerHTML = '';
  explorerApi = null;
  app.append(el('div', { class: 'screen' }, el('div', { class: 'screen-card' }, el('div', { class: 'brand big' }, 'Code Blueprints'), ...kids)));
}
async function showWelcome(message) {
  let capabilities = { recent: [] };
  try { capabilities = await api('/api/capabilities'); } catch (e) {}
  const input = el('input', { id: 'folder-input', class: 'path-input', placeholder: '/path/to/your/python/project', autocomplete: 'off' });
  const form = el('form', { class: 'open-row', onsubmit: (e) => { e.preventDefault(); if (input.value.trim()) openProject(input.value.trim()); } }, input, el('button', { class: 'btn primary', type: 'submit' }, 'Open'));
  screen(
    el('p', { class: 'lede' }, 'Open a Python project to see its packages, modules and classes as a dependency map, and every function as a blueprint.'),
    message ? el('p', { class: 'error-text' }, message) : null,
    el('div', { class: 'or' }, 'Folder to open'),
    form,
    capabilities.recent.length ? el('div', { class: 'recent' }, el('div', { class: 'kind' }, 'Recent'), capabilities.recent.map((root) => el('button', { class: 'recent-item', title: root, onclick: () => openProject(root) }, el('span', {}, root.split(/[\\/]/).pop()), el('small', {}, root)))) : null,
  );
  input.focus();
}
async function openProject(root) {
  try {
    await api(`/api/open?root=${encodeURIComponent(root)}`);
  } catch (error) {
    showWelcome(error.message);
    return;
  }
  waitForProject();
}
async function waitForProject() {
  const started = Date.now();
  const tick = async () => {
    let status;
    try { status = await api('/api/status'); } catch (error) { showWelcome(error.message); return; }
    if (!status.open) { showWelcome(); return; }
    if (status.error) { screen(el('p', { class: 'error-text' }, 'Reading the project failed.'), el('pre', { class: 'error-detail' }, status.error), el('button', { class: 'btn', onclick: () => showWelcome() }, 'Open another folder')); return; }
    if (!status.ready) {
      const seconds = Math.round((Date.now() - started) / 1000);
      const text = `Reading ${status.files.toLocaleString()} Python files in ${status.name}…`;
      const hint = seconds > 2 ? `${seconds}s — large projects take a little while the first time; after that they open from a cache.` : ' ';
      const shown = document.getElementById('load-text');
      if (shown) { shown.textContent = text; document.getElementById('load-hint').textContent = hint; }
      else screen(el('div', { class: 'spinner' }), el('p', { class: 'lede', id: 'load-text' }, text), el('p', { class: 'muted', id: 'load-hint' }, hint));
      setTimeout(tick, 400);
      return;
    }
    try {
      loadOverview(await api('/api/project'));
    } catch (error) { showWelcome(error.message); return; }
    mount();
  };
  tick();
}
function mount() {
  const app = document.getElementById('app');
  app.innerHTML = '';
  document.getElementById('measure').innerHTML = '';
  document.querySelectorAll('.popover, .palette').forEach((p) => p.remove());
  explorerApi = Explorer(app);
}
async function boot() {
  applySettings();
  try {
    const status = await api('/api/status');
    if (!status.open) showWelcome(); else waitForProject();
  } catch (error) {
    screen(el('p', { class: 'error-text' }, `Cannot reach the Code Blueprints server: ${error.message}`));
  }
}
let booted = false;
const startOnce = () => { if (booted) return; booted = true; boot(); };
if (document.fonts && document.fonts.ready) document.fonts.ready.then(startOnce, startOnce); else startOnce();
setTimeout(startOnce, 1500);
