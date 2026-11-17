const QUERY = new URLSearchParams(location.search);
const TOKEN = QUERY.get('t') || '';
async function api(path) {
  return answer(await fetch(path, { headers: { 'X-Blueprints-Token': TOKEN } }));
}
async function apiPost(path, payload) {
  return answer(await fetch(path, { method: 'POST', headers: { 'X-Blueprints-Token': TOKEN, 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }));
}
async function answer(response) {
  let body = null;
  try { body = await response.json(); } catch (e) { body = null; }
  if (!response.ok) throw new Error((body && body.error) || `${response.status} ${response.statusText}`);
  return body;
}
let OVERVIEW = null;
let DIFF = null;
const DIFF_SIGN = { added: '+', removed: '−', modified: '~' };
const DIFF_WORD = { added: 'added', removed: 'removed', modified: 'changed' };
let FILES = {};
let CALLERS = null;
const FUNCTIONS = new Map();
const FUNCTION_REQUESTS = new Map();
const OUTLINES = {};
const OUTLINE_REQUESTS = new Map();
const fnKey = (ref) => `${ref.path}::${ref.sym}`;
function addRemovedSymbols(data) {
  for (const [path, entry] of Object.entries(DIFF ? DIFF.removed : {})) {
    if (entry.module) { if (!data.modules.some((m) => m.path === path)) data.modules.push({ ...entry.module, path }); continue; }
    const module = data.modules.find((m) => m.path === path);
    if (!module) continue;
    const owner = (qual) => module.symbols.find((s) => s.qual === qual);
    module.symbols.push(...(entry.symbols || []));
    for (const [qual, methods] of Object.entries(entry.methods || {})) { const c = owner(qual); if (c) c.methods = [...(c.methods || []), ...methods]; }
    for (const [qual, fields] of Object.entries(entry.fields || {})) { const c = owner(qual); if (c) c.fields = [...(c.fields || []), ...fields]; }
    for (const [qual, members] of Object.entries(entry.members || {})) { const c = owner(qual); if (c) c.members = [...(c.members || []), ...members]; }
    module.constants = [...(module.constants || []), ...(entry.constants || [])];
  }
}
function fileDiff(path) { return DIFF && DIFF.files[path] ? DIFF.files[path].status : null; }
function folderDiff(prefix) {
  if (!DIFF) return null;
  const inside = Object.keys(FILES).filter((p) => p.startsWith(`${prefix}/`));
  const states = inside.map(fileDiff).filter(Boolean);
  if (!states.length) return null;
  if (states.length === inside.length && states.every((s) => s === states[0]) && states[0] !== 'modified') return states[0];
  return 'modified';
}
function symbolDiff(ref) {
  if (!DIFF || !ref) return null;
  const sym = lookup(ref);
  const kind = sym && sym.kind !== 'function' ? 'cls' : sym && sym.owner ? 'm' : 'fn';
  return DIFF.status[`${kind}:${ref.path}:${ref.sym}`] || null;
}
let SEEN = new Set();
let SEEN_REQUEST = 0;
let onSeenChanged = () => {};
function fileUnits(path) { return (DIFF && DIFF.units[path]) || []; }
function unitsUnder(prefix) { return DIFF ? Object.keys(DIFF.files).filter((p) => p.startsWith(`${prefix}/`)).flatMap(fileUnits) : []; }
function symbolUnits(ref) {
  const sym = lookup(ref);
  if (!sym) return [];
  if (sym.kind === 'function') return fileUnits(ref.path).filter((u) => u.qual === ref.sym && u.kind !== 'body');
  return fileUnits(ref.path).filter((u) => u.owner === ref.sym || (u.owner || '').startsWith(`${ref.sym}.`));
}
function seenCount(units) { return units.reduce((n, u) => n + (SEEN.has(u.id) ? 1 : 0), 0); }
function seenState(units) {
  if (!units.length) return null;
  const n = seenCount(units);
  return n === 0 ? 'none' : n === units.length ? 'all' : 'some';
}
async function markSeen(units, seen) {
  const ids = units.map((u) => u.id);
  const before = new Set(SEEN);
  for (const id of ids) { if (seen) SEEN.add(id); else SEEN.delete(id); }
  onSeenChanged();
  const request = ++SEEN_REQUEST;
  try {
    const result = await apiPost('/api/seen', { ids, seen });
    if (request === SEEN_REQUEST) SEEN = new Set(result.seen);
  } catch (error) {
    if (request === SEEN_REQUEST) SEEN = before;
    console.warn('Could not save what you have seen', error);
  }
  if (request === SEEN_REQUEST) onSeenChanged();
}
function seenBox(units, what) {
  const state = seenState(units);
  const box = el('input', { type: 'checkbox', class: 'seen-box', title: state === 'all' ? `Mark ${what} as not seen` : `Mark ${what} as seen`, 'aria-label': `${what} seen` });
  box.checked = state === 'all';
  box.indeterminate = state === 'some';
  box.addEventListener('click', (e) => e.stopPropagation());
  box.addEventListener('change', () => markSeen(units, state !== 'all'));
  return box;
}
function seenMark(units) { return seenState(units) === 'all' ? el('span', { class: 'seen-mark', title: 'Seen' }, '✓') : null; }
function diffBadge(state) { return state ? el('span', { class: `diff-badge diff-${state}`, title: DIFF_WORD[state] }, DIFF_SIGN[state]) : null; }
function loadOverview(data) {
  addRemovedSymbols(data);
  OVERVIEW = data;
  FILES = {};
  CALLERS = null;
  NET_CACHE = null;
  FOCUS_CACHE.clear();
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
    edges.push({ from, fp: e.fp, to, tp: e.tp, type: pin ? pin.type : { label: 'Any', cat: 'any' }, diff: e.diff });
  }
  const exec = [];
  for (const e of graph.exec || []) { const from = byId.get(e.from), to = byId.get(e.to); if (from && to) exec.push({ from, fp: e.fp, to, diff: e.diff }); }
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
const settings = Object.assign({ pinFont: 'mono', size: 12.5, theme: 'dark', plain: false, types: false, tests: true, constants: true, layout: 'balanced' }, (() => { try { return JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}'); } catch (e) { return {}; } })());
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
  const typeLabel = tp && (settings.types || opts.showType) ? el('span', { class: 'ptype' }, shortType(tp.label)) : null;
  const lit = opts.lit != null ? el('span', { class: 'lit', style: `color:var(--t-${tp ? tp.cat : 'any'})` }, opts.lit) : null;
  const tip = tp ? `${name || 'value'}: ${tp.label}` : 'execution order';
  return el('div', { class: `pin${opts.diff ? ` pin-${opts.diff}` : ''}`, 'data-pin': key, title: opts.diff ? `${tip} (${DIFF_WORD[opts.diff]})` : tip }, ...(side === 'in' ? [shape, label, lit, typeLabel] : [typeLabel, label, shape]));
}
const OPEN_ICON = '<svg width="11" height="11" viewBox="0 0 12 12"><rect x="1" y="3.5" width="7.5" height="7.5" rx="1" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M4 1h7v7" fill="none" stroke="currentColor" stroke-width="1.3"/></svg>';

const KIND = {
  loop: ['--h-branch', 'Loop'], entry: ['--h-entry', 'Start of the function'], break: ['--h-break', 'Read fields'], make: ['--h-make', 'Build a value'], call: ['--h-call', 'Call a function in this project'],
  method: ['--h-method', 'Call a method'], ext: ['--h-ext', 'Library call'], op: ['--h-op', 'Operator'], expr: ['--h-op', 'Work out a value'], lit: ['--h-lit', 'Fixed value'], var: ['--h-var', 'Module variable'],
  select: ['--h-select', 'Pick one value'], branch: ['--h-branch', 'Branch'], return: ['--h-return', 'Give back'], raise: ['--h-raise', 'Raise an error'], set: ['--h-set', 'Store on the object'],
};

function routedPath(ax, ay, bx, by, via, minDx = 36, lean = 0) {
  let d = `M${ax},${ay}`, cx = ax, cy = ay;
  const curveTo = (x, y) => { const dx = Math.max(Math.min(minDx, Math.abs(x - cx) * 0.5 + 12), Math.abs(x - cx) * 0.5); d += ` C${cx + dx + lean},${cy} ${x - dx + lean},${y} ${x},${y}`; cx = x; cy = y; };
  for (const p of via) { curveTo(p.x, p.y); d += ` L${p.x + p.w},${p.y}`; cx = p.x + p.w; }
  curveTo(bx, by);
  return d;
}
function loopBackPath(ax, ay, bx, by, via, turn = LOOP_TURN) {
  const first = via[0], right = first.x + first.w;
  const bend = (y0, y1) => turn * Math.min(1, 0.45 + Math.abs(y1 - y0) / 160);
  let d = `M${ax},${ay} L${right},${ay} C${right + bend(ay, first.y)},${ay} ${right + bend(ay, first.y)},${first.y} ${right},${first.y} L${first.x},${first.y}`;
  let cx = first.x, cy = first.y;
  for (const p of via.slice(1)) {
    const end = p.x + p.w, dx = Math.max(12, (cx - end) * 0.5);
    d += ` C${cx - dx},${cy} ${end + dx},${p.y} ${end},${p.y} L${p.x},${p.y}`;
    cx = p.x; cy = p.y;
  }
  return `${d} C${cx - bend(cy, by)},${cy} ${bx - bend(cy, by)},${by} ${bx},${by}`;
}
const overlaps = (a, v) => a.x < v.x + v.w && v.x < a.x + a.w && a.y < v.y + v.h && v.y < a.y + a.h;
function pathBox(path) {
  const numbers = (path.getAttribute('d') || '').match(/-?\d+(?:\.\d+)?(?:e-?\d+)?/g) || [];
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (let i = 0; i + 1 < numbers.length; i += 2) { const x = +numbers[i], y = +numbers[i + 1]; if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
  if (x0 === Infinity) return { x: -1e9, y: -1e9, w: 2e9, h: 2e9 };
  return { x: x0 - 16, y: y0 - 16, w: x1 - x0 + 32, h: y1 - y0 + 32 };
}
function setCulled(element, state, culled) {
  if (state.culled === culled) return;
  state.culled = culled;
  element.style.display = culled ? 'none' : '';
}
class Scene {
  constructor(ctx) {
    this.ctx = ctx; this.nodes = []; this.wires = []; this.el = el('div', { class: 'scene' }); this.svg = svg('svg', { class: 'wires' }); this.layer = el('div', { class: 'layer' }); this.el.append(this.svg, this.layer); document.getElementById('measure').append(this.el);
    this.wireCard = null; this.wireKey = '';
    this.el.addEventListener('mousemove', (e) => this.pointAtWires(e));
    this.el.addEventListener('mouseout', (e) => { if (e.target.closest('.wire-hit') && !(e.relatedTarget instanceof Element && e.relatedTarget.closest('.wire-hit'))) this.dropWires(); });
    this.el.addEventListener('mouseleave', () => this.dropWires());
  }
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
      const path = svg('path', { d: routedPath(w.a.x + pa.dx, w.a.y + pa.dy, w.b.x + pb.dx, w.b.y + pb.dy, (w.via || []).map((d) => ({ x: d.x, y: d.y + d.pins.d.dy, w: d.w }))), class: `wire ${w.cls || ''}${w.diff ? ` wire-${w.diff}` : ''}` });
      if (!w.cls) path.style.stroke = `var(--t-${w.type ? w.type.cat : 'any'})`;
      w.path = path; this.svg.append(path);
    }
    this.wires.forEach((w, i) => { if (w.path) { w.hit = svg('path', { d: w.path.getAttribute('d'), class: 'wire-hit', 'data-wire': i }); this.svg.append(w.hit); } });
  }
  cull(view) {
    for (const n of this.nodes) setCulled(n.el, n, !overlaps(n, view));
    for (const w of this.wires) {
      if (!w.path) continue;
      if (!w.box) w.box = pathBox(w.path);
      setCulled(w.path, w, !overlaps(w.box, view));
      w.hit.style.display = w.culled ? 'none' : '';
    }
  }
  pointAtWires(e) {
    if (!e.target.closest('.wire-hit')) return;
    const under = document.elementsFromPoint(e.clientX, e.clientY).filter((x) => x.classList.contains('wire-hit') && this.svg.contains(x)).map((x) => this.wires[+x.dataset.wire]);
    const key = under.map((w) => this.wires.indexOf(w)).join(' ');
    if (key !== this.wireKey) {
      this.dropWires();
      if (!under.length) return;
      this.wireKey = key;
      this.el.classList.add('has-hot');
      for (const w of under) {
        w.path.classList.add('hot');
        for (const [node, pin] of [[w.a, w.ak], [w.b, w.bk]]) for (const p of pinElsOf(node, pin)) { p.classList.add('pin-hot'); p.style.setProperty('--pin-c', wireColour(w)); }
      }
      this.wireCard = wireCardEl(under);
      document.body.append(this.wireCard);
    }
    if (this.wireCard) placeCard(this.wireCard, e, [...this.el.querySelectorAll('.pin-hot')].map((pin) => pin.getBoundingClientRect()));
  }
  dropWires() {
    if (this.wireCard) { this.wireCard.remove(); this.wireCard = null; }
    if (!this.wireKey) return;
    this.wireKey = '';
    this.el.classList.remove('has-hot');
    for (const w of this.wires) if (w.path) w.path.classList.remove('hot');
    this.el.querySelectorAll('.pin-hot').forEach((p) => p.classList.remove('pin-hot'));
  }
  hover(node, on) {
    this.el.classList.toggle('has-hot', on);
    for (const w of this.wires) if (w.path) w.path.classList.toggle('hot', on && (w.a === node || w.b === node));
    if (this.onHot) this.onHot(on ? this.wires.filter((w) => w.path && w.a !== w.b && (w.a === node || w.b === node)).map((w) => wireEnds(w, node)) : null);
  }
}
function pinElsOf(node, key) {
  return [...node.el.querySelectorAll(`[data-pin="${CSS.escape(key)}"]`)].filter((p) => p.closest('.node') === node.el);
}
function wireColour(w) {
  return w.cls === 'exec' ? 'var(--exec)' : `var(--t-${w.type ? w.type.cat : 'any'})`;
}
function wireCardEl(wires) {
  const shown = wires.slice(0, 6);
  const end = (node, key) => `${plain(node.data.title || node.data.kind || '')} › ${plain(key.replace(/^(out|in):/, ''))}`;
  return el('div', { class: 'edge-card wire-card' },
    shown.map((w, i) => el('div', { class: `edge-card-section${i ? ' divided' : ''}` },
      el('div', { class: 'wire-card-ends' }, el('span', {}, end(w.a, w.ak)), el('span', { class: 'udim' }, '→'), el('span', {}, end(w.b, w.bk))),
      w.cls === 'exec' ? el('div', { class: 'udim' }, 'Runs next, in this order') : el('code', { class: 'wire-card-type', style: `color:${wireColour(w)}` }, w.type ? w.type.label : 'Any'))),
    wires.length > shown.length ? el('div', { class: 'udim' }, `and ${wires.length - shown.length} more`) : null);
}
function placeCard(card, e, avoid = []) {
  const box = card.getBoundingClientRect();
  const fit = (x, y) => ({ x: Math.max(12, Math.min(x, window.innerWidth - box.width - 12)), y: Math.max(12, Math.min(y, window.innerHeight - box.height - 12)) });
  const spots = [fit(e.clientX + 16, e.clientY + 16), fit(e.clientX + 16, e.clientY - box.height - 16), fit(e.clientX - box.width - 16, e.clientY + 16), fit(e.clientX - box.width - 16, e.clientY - box.height - 16)];
  const clear = (spot) => avoid.every((r) => spot.x > r.right + 6 || spot.x + box.width < r.left - 6 || spot.y > r.bottom + 6 || spot.y + box.height < r.top - 6);
  const spot = spots.find(clear) || spots[0];
  card.style.left = `${spot.x}px`;
  card.style.top = `${spot.y}px`;
}
function wireEnds(w, node) {
  const outgoing = w.a === node;
  const other = outgoing ? w.b : w.a;
  const end = (n, key) => ({ x: n.x + n.pins[key].dx, y: n.y + n.pins[key].dy });
  const label = plain(other.data.title || other.data.kind || '');
  return {
    key: other.data.id || label,
    from: end(node, outgoing ? w.ak : w.bk),
    to: end(other, outgoing ? w.bk : w.ak),
    label,
    color: wireColour(w),
    title: `${outgoing ? 'Goes to' : 'Comes from'} ${label}`,
  };
}

function targetChanged(n) {
  if (!DIFF || !n.target || n.kind === 'entry') return false;
  const sym = lookup(n.target);
  if (!sym || sym.kind === 'function') return Boolean(symbolDiff(n.target));
  const pins = n.kind === 'break' ? n.outs : n.ins;
  return pins.some((pin) => DIFF.status[`f:${n.target.path}:${n.target.sym}.${pin.name.split('.')[0]}`]);
}
function expressionEl(n) { return codeBlockEl(n.expr, n.ins); }
function codeBlockEl(lines, ins) {
  const names = ins.map((pin) => pin.name).sort((a, b) => b.length - a.length);
  const colours = new Map(ins.map((pin) => [pin.name, `var(--t-${pin.type ? pin.type.cat : 'any'})`]));
  const pattern = names.length ? new RegExp(`(?<![\\w.])(${names.map((name) => name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})(?![\\w(])`, 'y') : null;
  const input = (text, at) => {
    if (!pattern) return null;
    pattern.lastIndex = at;
    const match = pattern.exec(text);
    return match ? { end: at + match[1].length, node: el('span', { class: 'expr-input', style: `color:${colours.get(match[1])}` }, match[1]) } : null;
  };
  const paint = pythonPainter(input);
  return el('div', { class: 'expr' }, lines.map((line, i) => el('div', {}, ...paint(line, i))));
}
function nodeEl(n, ctx, connectedIns, connectedOuts) {
  const [hc] = KIND[n.kind] || KIND.ext;
  const state = n.diff || (targetChanged(n) ? 'modified' : null);
  const wrap = el('div', { class: `k-${n.kind}${state ? ` diff-${state}` : ''}`, 'data-node': n.id });
  const box = el('div', { class: 'box' });
  wrap.append(box);
  const openable = n.target && lookup(n.target) && lookup(n.target).kind === 'function' && ['call', 'method', 'ext', 'var'].includes(n.kind);
  box.append(el('div', { class: 'head', style: `--hc: var(${hc})` }, diffBadge(state),
    el('span', { class: 'title' }, n.kind === 'break' || n.kind === 'make' ? `${n.title.split(' ')[0]} ${plain(n.title.split(' ').slice(1).join(' '))}` : plain(n.title)),
    openable && ctx.openButton ? ctx.openButton(n) : null));
  const left = el('div', { class: 'col in' }), right = el('div', { class: 'col out' });
  if (n.execIn) left.append(pinEl('in', 'exec-in', '', null));
  if (n.execOut) right.append(pinEl('out', 'then', '', null));
  for (const label of n.execOuts || []) right.append(pinEl('out', label, label, null, { raw: true }));
  for (const p of n.ins) left.append(pinEl('in', `in:${p.name}`, p.name, p.type, { lit: p.lit, connected: connectedIns.has(p.name) || p.lit != null, diff: p.diff }));
  for (const o of n.outs) right.append(pinEl('out', `out:${o.name}`, o.name, o.type, { connected: connectedOuts.has(o.name), diff: o.diff }));
  if (n.expr) box.append(expressionEl(n));
  box.append(el('div', { class: 'rows' }, left, right));
  if (n.note) box.append(el('div', { class: 'note' }, n.note));
  if (n.code) box.append(codeBlockEl([n.code], n.ins));
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
  for (const e of g.edges) Object.assign(scene.wire(byId.get(e.from), `out:${e.fp}`, byId.get(e.to), `in:${e.tp}`, null, e.type), { via: routes.get(`${e.from.id}|out:${e.fp}|${e.to.id}|in:${e.tp}`), diff: e.diff });
  for (const e of g.exec) Object.assign(scene.wire(byId.get(e.from), e.fp, byId.get(e.to), 'exec-in', 'exec'), { via: routes.get(`${e.from.id}|${e.fp}|${e.to.id}|exec-in`), diff: e.diff });
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
  const middleOf = settings.layout === 'classic' ? (vals) => vals.reduce((a, b) => a + b, 0) / vals.length : (vals) => vals.sort((a, b) => a - b)[Math.floor((vals.length - 1) / 2)];
  const targetFrom = (n, list, fromPreds) => {
    const v = V(n);
    const vals = list.map((p) => { const o = V(p.n); const op = o.pins[fromPreds ? p.ak : p.bk], vp = v.pins[fromPreds ? p.bk : p.ak]; return op && vp ? o.y + op.dy - vp.dy : null; }).filter((t0) => t0 !== null);
    return vals.length ? middleOf(vals) : null;
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
  if (ARRANGED_LAYOUTS.has(settings.layout)) arrangeBlueprintColumns(settings.layout, Array.from(cols, (col) => col || []), succs, { V, isExec, lane, gapY: GAPY });
  for (const d of dummies) { d.x = colX[d.rank]; d.w = colW[d.rank]; }
  return { routes, dummies };
}

function arrangeBlueprintColumns(layout, columns, succs, { V, isExec, lane, gapY }) {
  const pinOf = (n, key) => { const p = V(n).pins[key]; return p ? p.dy : null; };
  const links = [];
  for (const [a, list] of succs) for (const s of list) { const pa = pinOf(a, s.ak), pb = pinOf(s.n, s.bk); if (pa !== null && pb !== null) links.push({ a, b: s.n, pa, pb, weight: s.exec ? 2 : 1, exec: s.exec }); }
  const placed = arrangeLayers(layout, columns, links, {
    height: (n) => V(n).h,
    gap: (n) => (n.dummy ? 10 : gapY),
    floor: (n) => (isExec(n) ? 0 : Math.max(0, lane)),
    pinned: (n) => n.kind === 'entry',
    isDummy: (n) => Boolean(n.dummy),
    candidates: (n, list, forwards) => { if (!isExec(n)) return list; const exec = list.filter((l) => l.exec); return forwards ? (exec.length ? exec : list) : n.dummy ? list : exec; },
    previous: new Map(columns.flat().map((n) => [n, V(n).y])),
  });
  if (placed) for (const [n, y] of placed) V(n).y = y;
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
const typeText = (t) => el('span', { class: 'utype', style: `color:var(--t-${t.cat})`, title: t.label }, shortType(t.label));
const shortType = (label) => (label.length > 60 ? `${label.slice(0, 59)}…` : label);

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : (word.endsWith('s') ? 'es' : 's')}`;
let NET_CACHE = null;
const TEST_PATH = /(^|\/)(tests?|testing)\/|(^|\/)test_[^/]*\.py$|_test\.py$/;
function isTestPath(path) { return TEST_PATH.test(path) || TEST_PATH.test(`${path}/`); }
function resetNet() { NET_CACHE = null; FOCUS_CACHE.clear(); }
function revealHidden(ids) {
  const N = net();
  const missing = ids.filter((id) => !N.nodes.has(id));
  if (!missing.length) return;
  if (missing.some((id) => id.startsWith('c:'))) settings.constants = true;
  if (missing.some((id) => isTestPath(id.slice(id.indexOf(':') + 1).split(':')[0]))) settings.tests = true;
  saveSettings(); resetNet();
}
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
    if (!settings.tests && isTestPath(path)) continue;
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
    if (settings.constants) for (const [cn, ct, cv] of f.constants || []) add(`c:${path}:${cn}`, 'constant', cn, mod, { type: ct, value: cv });
  }
  for (const lib of (OVERVIEW && OVERVIEW.libraries) || []) {
    const libNode = add(lib.id, 'library', lib.title, root);
    for (const m of lib.modules) {
      const modNode = add(`libmod:${m.module}`, 'libmodule', m.module, libNode);
      for (const n of m.names) add(`libn:${m.module}.${n}`, 'name', n, modNode);
    }
  }
  if (DIFF) {
    const own = (n) => (n.kind === 'module' ? DIFF.status[`mod:${n.path}`] : DIFF.status[n.id]) || null;
    const settle = (n) => {
      const kids = n.children.map(settle).filter((k) => k !== undefined);
      const mine = own(n);
      if (mine) { n.diff = mine; return mine; }
      const changed = kids.filter(Boolean);
      if (!changed.length || n.kind === 'library' || n.kind === 'libmodule') { n.diff = null; return null; }
      n.diff = n.kind === 'package' && changed.length === n.children.length && changed.every((k) => k === changed[0]) ? changed[0] : 'modified';
      return n.diff;
    };
    settle(root);
  }
  const list = [];
  const ids = OVERVIEW ? OVERVIEW.edges.ids : [];
  for (const row of OVERVIEW ? OVERVIEW.edges.rows : []) {
    const from = ids[row[0]], to = ids[row[1]];
    if (!nodes.has(from) || !nodes.has(to)) continue;
    const kinds = new Set(row[2].split(',').filter(Boolean));
    list.push({ from, to, kinds, labels: new Set(row[3] ? row[3].split(',') : []), kind: KIND_ORDER.find((k) => kinds.has(k)) });
  }
  if (!settings.tests) dropTestOnlyLibraries(root, nodes, list);
  const chains = new Map();
  const chain = (id) => { if (chains.has(id)) return chains.get(id); const out = []; for (let n = nodes.get(id); n; n = n.parent) out.unshift(n); chains.set(id, out); return out; };
  NET_CACHE = { nodes, root, edges: list, chain };
  return NET_CACHE;
}

function dropTestOnlyLibraries(root, nodes, edges) {
  const wanted = new Set(edges.flatMap((e) => [e.from, e.to]));
  for (const [path, f] of Object.entries(FILES)) if (!isTestPath(path)) for (const i of f.imports || []) if (i.lib) wanted.add(`lib:${i.lib}`);
  const subtree = (n) => [n, ...n.children.flatMap(subtree)];
  root.children = root.children.filter((n) => {
    if (n.kind !== 'library') return true;
    const all = subtree(n);
    if (all.some((x) => wanted.has(x.id))) return true;
    for (const x of all) nodes.delete(x.id);
    return false;
  });
}

function showToggles(onChange) {
  const tests = Object.keys(FILES).filter(isTestPath).length;
  const constants = Object.values(FILES).reduce((n, f) => n + (f.constants || []).length, 0);
  const toggle = (key, label, count, title) => {
    if (!count) return null;
    const box = el('input', { type: 'checkbox', onchange: (e) => onChange(key, e.target.checked) });
    box.checked = settings[key];
    return el('label', { class: 'show-toggle', title }, box, label, el('span', { class: 'udim' }, count));
  };
  const toggles = [
    toggle('tests', 'Tests', tests, 'Show test files and the libraries only they use'),
    toggle('constants', 'Constants', constants, 'Show module constants and what reads them'),
  ].filter(Boolean);
  return toggles.length ? el('div', { class: 'show-chip' }, el('span', { class: 'udim' }, 'Show'), toggles) : null;
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
const UNIT_KINDS = new Set(['module', 'libmodule']);
function focusUnitOf(id) {
  const chain = net().chain(id);
  if (!chain.length || id === 'root') return null;
  const unit = [...chain].reverse().find((n) => UNIT_KINDS.has(n.kind));
  return unit ? unit.id : id;
}
const FOCUS_CACHE = new Map();
function relatedTo(unitId) {
  const N = net();
  if (!unitId || !N.nodes.has(unitId)) return null;
  if (FOCUS_CACHE.has(unitId)) return FOCUS_CACHE.get(unitId);
  const unit = N.nodes.get(unitId);
  const inside = (id) => N.chain(id).includes(unit);
  const related = new Set();
  for (const e of N.edges) {
    const a = inside(e.from), b = inside(e.to);
    if (a && !b) related.add(focusUnitOf(e.to));
    else if (b && !a) related.add(focusUnitOf(e.from));
  }
  related.delete(null);
  const units = new Set([unitId, ...related]);
  const shown = new Set();
  for (const id of units) for (const n of N.chain(id)) shown.add(n.id);
  const filter = { unit: unitId, related, units, shown, visible: (n) => shown.has(n.id) || N.chain(n.id).some((a) => units.has(a.id)) };
  FOCUS_CACHE.set(unitId, filter);
  return filter;
}
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
function netBoxEl(n, expanded, ctx, filter = null) {
  if (!n.children.length) {
    const stripe = { method: '--h-method', function: '--h-call', field: '--h-break', member: '--h-enum', constant: '--h-var', name: '--h-lit' }[n.kind] || '--h-lit';
    const isFn = n.kind === 'method' || n.kind === 'function';
    const kids = isFn ? opBlock(n.sym)
      : n.kind === 'field' ? [el('span', { class: 'uvis' }, visibility(n.name)), el('span', {}, plain(n.name)), el('span', { class: 'udim' }, ':'), typeText(n.type)]
        : n.kind === 'member' ? [el('span', {}, n.name), el('span', { class: 'udim' }, ` = ${n.value}`)]
          : n.kind === 'constant' ? [el('span', {}, plain(n.name)), el('span', { class: 'udim' }, ':'), typeText(n.type), el('span', { class: 'udim' }, ` = ${n.value}`)]
            : [el('span', { class: 'uicon' }, /^[a-z_]/.test(n.name) ? 'ƒ' : 'C'), el('span', {}, n.name)];
    const leaf = el('div', { class: `nb leaf k-${n.kind}${isFn ? ' fnleaf' : ''}${n.diff ? ` diff-${n.diff}` : ''}`, 'data-id': n.id, style: `--stripe: var(${stripe})`, title: n.sym ? 'Open its dataflow view' : netLabel(n.id) }, diffBadge(n.diff), kids);
    leaf.addEventListener('click', (e) => { e.stopPropagation(); if (n.sym) ctx.go(refOf(n.sym)); else ctx.select(n.id); });
    return leaf;
  }
  const isOpen = expanded.has(n.id);
  const sym = n.sym;
  const hc = n.kind === 'package' ? '--h-pkg' : n.kind === 'module' ? '--h-mod' : n.kind === 'library' || n.kind === 'libmodule' ? '--h-lib'
    : sym.kind === 'enum' ? '--h-enum' : sym.cat === 'iface' ? '--h-iface' : sym.cat === 'struct' ? '--h-struct' : '--h-break';
  const stereo = n.kind === 'class' ? stereotypeOf(sym) : n.kind === 'module' ? 'module' : n.kind === 'library' ? 'library' : null;
  const title = n.kind === 'package' ? `${n.name}/` : n.name;
  const shownKids = filter ? n.children.filter((k) => filter.visible(k)) : n.children;
  const hiddenKids = n.children.length - shownKids.length;
  const box = el('div', { class: `nb k-${n.kind} ${isOpen ? 'open' : ''} ${n.diff ? `diff-${n.diff}` : ''} ${filter && filter.unit === n.id ? 'focused' : ''}`, 'data-id': n.id, style: `--hc: var(${hc})` });
  const head = el('div', { class: 'nhead', title: isOpen ? 'Collapse' : 'Expand' }, el('span', { class: 'chev' }, isOpen ? '▾' : '▸'), diffBadge(n.diff),
    stereo ? el('span', { class: 'stereo' }, `«${stereo}»`) : null, el('span', { class: 'ntitle' }, title),
    isOpen && hiddenKids ? el('span', { class: 'nhidden', title: 'Hidden because they have no dependency on the selected module' }, `${hiddenKids} unrelated hidden`) : null);
  head.addEventListener('click', (e) => { e.stopPropagation(); ctx.select(n.id); ctx.toggle(n.id); });
  box.append(head);
  if (!isOpen) { box.append(el('div', { class: 'nsum' }, summaryOf(n))); return box; }
  const inner = el('div', { class: 'ninner' });
  for (const k of shownKids) inner.append(netBoxEl(k, expanded, ctx, filter));
  box.append(inner);
  return box;
}
const NET_ROUTES = new Map();
const LOOP_TURN = 34;
const NET_SLACK = new Map();
const NET_COLUMNS = new Map();
function layoutNet(n, boxEl, edges, N = net()) {
  const inner = boxEl.querySelector(':scope > .ninner');
  if (!inner) return;
  const kids = [...inner.children].map((elx) => ({ node: N.nodes.get(elx.dataset.id), el: elx, x: 0, y: 0 }));
  const byId = new Map(kids.map((k) => [k.node.id, k]));
  const under = (id) => { const c = N.chain(id); return c[n.depth] === n && c[n.depth + 1] ? byId.get(c[n.depth + 1].id) : null; };
  const touching = new Map(kids.map((k) => [k, []]));
  for (const e of edges) {
    const a = under(e.from), b = under(e.to);
    if (a) touching.get(a).push(e);
    if (b && b !== a) touching.get(b).push(e);
  }
  for (const k of kids) layoutNet(k.node, k.el, touching.get(k), N);
  for (const k of kids) { k.w = k.el.offsetWidth; k.h = k.el.offsetHeight; }
  const pairs = new Map(), skips = [], weights = new Map();
  for (const e of edges) {
    const a = under(e.from), b = under(e.to);
    if (!a || !b || a === b) continue;
    if (!weights.has(a)) weights.set(a, new Map());
    weights.get(a).set(b, (weights.get(a).get(b) || 0) + (e.atoms ? e.atoms.length : 1));
    if (e.shortcut) { skips.push({ a, b }); continue; }
    if (!pairs.has(a)) pairs.set(a, new Set()); pairs.get(a).add(b);
  }
  const rank = rankColumns(kids, weights, (k) => ['field', 'member', 'constant'].includes(k.node.kind));
  const items = [...kids];
  const nbrs = new Map();
  const near = (a, b) => { if (!nbrs.has(a)) nbrs.set(a, new Set()); nbrs.get(a).add(b); if (!nbrs.has(b)) nbrs.set(b, new Set()); nbrs.get(b).add(a); };
  const routes = [];
  const lane = (from, ranks) => { const chain = []; for (const r of ranks) { const d = { dummy: true, rank: r, w: 0, h: 6, x: 0, y: 0, origin: from }; near(chain.length ? chain[chain.length - 1] : from, d); chain.push(d); items.push(d); } return chain; };
  const span = (lo, hi) => Array.from({ length: Math.max(0, hi - lo) }, (_, i) => lo + i);
  for (const [a, bs] of pairs) {
    const r0 = rank.get(a);
    const ts = [...bs].map((b) => rank.get(b));
    const ahead = lane(a, span(r0 + 1, Math.max(r0, ...ts)));
    const behind = lane(a, span(Math.min(r0 + 1, ...ts), r0 + 1).reverse());
    for (const b of bs) {
      const t = rank.get(b);
      const via = t > r0 ? ahead.slice(0, t - r0 - 1) : behind.slice(0, r0 - t + 1);
      near(via.length ? via[via.length - 1] : a, b);
      routes.push({ a, b, via });
    }
  }
  const lastRank = Math.max(0, ...kids.map((k) => rank.get(k)));
  const rk = (it) => (it.dummy ? it.rank : rank.get(it));
  const cols = [];
  for (const it of items) { const r = rk(it); if (!cols[r]) cols[r] = []; cols[r].push(it); }
  const leafy = kids.every((k) => !k.node.children.length);
  const PAD = 14, TOP = 10, GX = leafy ? 70 : 110, GY = leafy ? 12 : 22;
  const loops = [...routes, ...skips].filter((r) => rank.get(r.b) <= rank.get(r.a));
  const padLeft = loops.some((r) => rank.get(r.b) === 0) ? PAD + LOOP_TURN : PAD;
  const padRight = loops.some((r) => rank.get(r.a) === lastRank) ? PAD + LOOP_TURN : PAD;
  const colX = [], colW = [];
  let x = padLeft;
  cols.forEach((col, r) => { if (!col) return; const real = col.filter((it) => !it.dummy); const w = real.length ? Math.max(...real.map((k) => k.w)) : 30; colX[r] = x; colW[r] = w; let y = TOP; for (const it of col) { it.x = x; it.y = y; y += it.h + GY; } x += w + GX; });
  const mid = (o) => o.y + (o.dummy ? 3 : Math.min(o.h, 40) / 2);
  for (const it of items) if (it.dummy) it.y = mid(it.origin) - 3;
  for (const col of cols) if (col) col.sort((a, b) => a.y - b.y);
  for (let pass = 0; pass < 8; pass++) for (const col of pass % 2 ? [...cols].reverse() : cols) {
    if (!col) continue;
    const want = new Map(col.map((it) => {
      const nb = [...(nbrs.get(it) || [])].filter((o) => rk(o) !== rk(it) || it.dummy);
      return [it, nb.length ? nb.reduce((acc, o) => acc + mid(o), 0) / nb.length - (it.dummy ? 3 : Math.min(it.h, 40) / 2) : it.y];
    }));
    col.sort((a, b) => want.get(a) + a.h / 2 - want.get(b) - b.h / 2);
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
  if (ARRANGED_LAYOUTS.has(settings.layout)) arrangeMapColumns(settings.layout, Array.from(cols, (col) => col || []), nbrs, { anchor: (it) => (it.dummy ? 3 : Math.min(it.h, 40) / 2), gapY: GY, top: TOP });
  const minY = Math.min(...items.map((it) => it.y));
  for (const it of items) it.y += TOP - minY;
  for (const k of kids) { k.el.style.left = `${k.x}px`; k.el.style.top = `${k.y}px`; NET_SLACK.set(k.node.id, colW[rank.get(k)] - k.w); }
  for (const it of items) if (it.dummy) { it.x = colX[it.rank]; it.w = colW[it.rank]; }
  inner.style.width = `${Math.max(...kids.map((k) => k.x + k.w), 100) + padRight}px`;
  inner.style.height = `${Math.max(...items.map((it) => it.y + it.h), 30) + PAD}px`;
  for (const r of routes) NET_ROUTES.set(`${r.a.node.id}|${r.b.node.id}`, { inner, via: r.via });
  const gaps = Array.from(cols, (col) => { const real = (col || []).filter((it) => !it.dummy).sort((p, q) => p.y - q.y); const out = []; let top = 0; for (const k of real) { out.push([top, k.y]); top = k.y + k.h; } out.push([top, Infinity]); return out; });
  const gapNear = (r, want) => gaps[r].map(([lo, hi]) => (hi - lo < 8 ? (lo + hi) / 2 : Math.min(Math.max(want, lo + 4), hi - 4))).reduce((best, y) => (Math.abs(y - want) < Math.abs(best - want) ? y : best), Infinity);
  NET_COLUMNS.set(n.id, { inner, colX, colW, gapNear, last: lastRank, rank: new Map(kids.map((k) => [k.node.id, rank.get(k)])) });
  for (const { a, b } of skips) {
    const r0 = rank.get(a), t = rank.get(b), ya = mid(a), yb = mid(b);
    const ranks = t > r0 ? span(r0 + 1, t) : span(t, r0 + 1).reverse();
    const reach = Math.max(1, Math.abs(t - r0));
    const via = ranks.map((r) => ({ x: colX[r], w: colW[r], y: gapNear(r, ya + ((yb - ya) * Math.abs(r - r0)) / reach) - 3 }));
    NET_ROUTES.set(`${a.node.id}|${b.node.id}`, { inner, via });
  }
}

function arrangeMapColumns(layout, columns, nbrs, { anchor, gapY, top }) {
  const layerOf = new Map();
  columns.forEach((col, i) => col.forEach((it) => layerOf.set(it, i)));
  const links = [];
  for (const [a, others] of nbrs) for (const b of others) if (layerOf.get(a) < layerOf.get(b)) links.push({ a, b, pa: anchor(a), pb: anchor(b), weight: 1 });
  const placed = arrangeLayers(layout, columns, links, {
    height: (it) => it.h,
    gap: (it) => (it.dummy ? 8 : gapY),
    floor: () => top,
    pinned: () => false,
    isDummy: (it) => Boolean(it.dummy),
    candidates: (it, list) => list,
    previous: new Map(columns.flat().map((it) => [it, it.y])),
  });
  if (placed) for (const [it, y] of placed) it.y = y;
}

function buildNetScene(expanded, ctx, filter = null) {
  const N = net();
  const scene = new Scene(ctx);
  const effective = new Set(['root']);
  for (const id of expanded) { const c = N.chain(id); if (c.length && c[c.length - 1].children.length && c.slice(1).every((x) => expanded.has(x.id))) effective.add(id); }
  const rootEl = el('div', { class: 'nroot', 'data-id': 'root' });
  const inner = el('div', { class: 'ninner' });
  for (const k of N.root.children) if (!filter || filter.visible(k)) inner.append(netBoxEl(k, effective, ctx, filter));
  rootEl.append(inner);
  const rootV = scene.add(rootEl);
  NET_ROUTES.clear(); NET_SLACK.clear(); NET_COLUMNS.clear();
  const visibleOf = (id) => { const c = N.chain(id); for (let i = 1; i < c.length; i++) if (!effective.has(c[i].id)) return c[i].id; return id; };
  const shown = new Map();
  for (const e of N.edges) {
    const [a, b] = siblingEnds(N, visibleOf(e.from), visibleOf(e.to));
    if (a === b) continue;
    const key = `${a}|${b}`;
    if (!shown.has(key)) shown.set(key, { from: a, to: b, atoms: [] });
    shown.get(key).atoms.push(e);
  }
  const shortcuts = shortcutKeys([...shown.values()]);
  for (const l of shown.values()) l.shortcut = shortcuts.has(`${l.from}|${l.to}`);
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
  const drawnOpen = new Set([...effective].filter((id) => id === 'root' || rects.has(id)));
  const agg = new Map();
  for (const { from: a, to: b, atoms } of shown.values()) {
    if (!rects.has(a) || !rects.has(b)) continue;
    if (N.chain(b).some((x) => x.id === a) || N.chain(a).some((x) => x.id === b)) continue;
    const g = { a, b, kinds: new Set(), labels: new Set(), count: atoms.length, atoms, shortcut: shortcuts.has(`${a}|${b}`), through: shortcuts.get(`${a}|${b}`) || null };
    for (const e of atoms) { e.kinds.forEach((x) => g.kinds.add(x)); e.labels.forEach((x) => g.labels.add(x)); }
    agg.set(`${a}|${b}`, g);
  }
  const defs = svg('defs');
  defs.innerHTML = `
    <marker id="m-tri" viewBox="0 0 14 14" refX="13" refY="7" markerWidth="14" markerHeight="14" markerUnits="userSpaceOnUse" orient="auto"><path d="M1,1 L13,7 L1,13 z" style="fill:var(--canvas);stroke:var(--rel-inherits)" stroke-width="1.6"/></marker>
    <marker id="m-dia" viewBox="0 0 18 10" refX="1" refY="5" markerWidth="18" markerHeight="10" markerUnits="userSpaceOnUse" orient="auto"><path d="M1,5 L9,1 L17,5 L9,9 z" style="fill:var(--rel-has)"/></marker>
    ${['has', 'creates', 'calls', 'writes', 'reads', 'uses'].map((k) => `<marker id="m-arrow-${k}" viewBox="0 0 12 12" refX="11" refY="6" markerWidth="12" markerHeight="12" markerUnits="userSpaceOnUse" orient="auto"><path d="M1,1 L11,6 L1,11" style="fill:none;stroke:var(--rel-${k})" stroke-width="1.7"/></marker>`).join('')}`;
  scene.svg.append(defs);
  const overlay = svg('svg', { class: 'wires overlay', width: scene.width, height: scene.height });
  scene.el.append(overlay);
  const cubic = (t, a, b, c, d) => (1 - t) ** 3 * a + 3 * (1 - t) ** 2 * t * b + 3 * (1 - t) * t ** 2 * c + t ** 3 * d;
  const drawn = [];
  const offsets = new Map();
  const innerOffset = (inner) => { if (offsets.has(inner)) return offsets.get(inner); let ox = 0, oy = 0, cur = inner; while (cur && cur !== rootEl) { ox += cur.offsetLeft; oy += cur.offsetTop; cur = cur.offsetParent; } const o = { x: rootV.x + ox, y: rootV.y + oy }; offsets.set(inner, o); return o; };
  for (const route of NET_ROUTES.values()) innerOffset(route.inner);
  const absVia = (route) => { if (!route) return []; const o = innerOffset(route.inner); return route.via.map((d) => ({ x: o.x + d.x, y: o.y + d.y + 3, w: d.w })); };
  for (const g of agg.values()) {
    g.kind = KIND_ORDER.find((k) => g.kinds.has(k));
    const ra = rects.get(g.a), rb = rects.get(g.b);
    const shift = agg.has(`${g.b}|${g.a}`) ? (g.a < g.b ? -4 : 4) : 0;
    const y1 = ra.y + ra.anchorY + shift, y2 = rb.y + rb.anchorY + shift;
    const forward = rb.x >= ra.x + ra.w - 4;
    const x1 = ra.x + ra.w, x2 = rb.x - 2;
    const marker = g.kind === 'inherits' || g.kind === 'realizes' ? 'url(#m-tri)' : `url(#m-arrow-${g.kind})`;
    const spans = absVia(NET_ROUTES.get(`${g.a}|${g.b}`));
    let routedD, labelAt;
    if (forward) {
      const out = x1 + (NET_SLACK.get(g.a) || 0);
      const dx = Math.max(50, Math.abs(x2 - out) * 0.45);
      const lean = shift * 1.5 * (y2 > y1 ? -1 : 1);
      const curve = spans.length ? routedPath(out, y1, x2, y2, spans, 50, lean) : `M${out},${y1} C${out + dx + lean},${y1} ${x2 - dx + lean},${y2} ${x2},${y2}`;
      routedD = out > x1 + 1 ? `M${x1},${y1} L${curve.slice(1)}` : curve;
      const tail = spans.length ? spans[spans.length - 1] : null;
      labelAt = tail ? { x: (tail.x + tail.w + x2) / 2, y: (tail.y + y2) / 2 } : { x: cubic(0.65, out, out + dx, x2 - dx, x2), y: cubic(0.65, y1, y1, y2, y2) };
    } else {
      const lane = spans.length ? spans : [{ x: Math.min(ra.x, rb.x), w: x1 + (NET_SLACK.get(g.a) || 0) - Math.min(ra.x, rb.x), y: Math.min(ra.y, rb.y) - 12 }];
      routedD = loopBackPath(x1, y1, x2, y2, lane);
      const middle = lane[Math.floor((lane.length - 1) / 2)];
      labelAt = { x: middle.x + middle.w / 2, y: middle.y };
    }
    const path = svg('path', { d: routedD, class: `rel k-${g.kind} weighted${g.count === 1 ? ' light' : ''}${g.shortcut ? ' shortcut' : ''}`, 'marker-end': marker });
    path.style.setProperty('--w', `${(1.4 + 1.4 * Math.log2(g.count)).toFixed(2)}px`);
    if (g.kind === 'has') path.setAttribute('marker-start', 'url(#m-dia)');
    const kinds = [...g.kinds].sort((p, q) => KIND_ORDER.indexOf(p) - KIND_ORDER.indexOf(q));
    const label = g.kinds.size === 1 && g.kind === 'has' && N.nodes.get(g.a).kind === 'field' ? [...g.labels].join(', ') : `${kinds.join(' · ')}${g.count > 1 ? ` (${g.count})` : ''}`;
    const text = svg('text', { x: labelAt.x, y: labelAt.y - 5, class: `rel-label k-${g.kind}`, 'text-anchor': 'middle' });
    text.textContent = label;
    if (g.count === 1) text.classList.add('light');
    if (g.shortcut) text.classList.add('shortcut');
    const hit = svg('path', { d: routedD, class: 'rel-hit', 'data-drawn': drawn.length });
    overlay.append(path, text, hit);
    drawn.push({ g, path, text, hit, forward, ends: { a: { x: x1, y: y1 }, b: { x: x2, y: y2 } }, labelBox: { x: +text.getAttribute('x') - label.length * 3.3, y: +text.getAttribute('y') - 10, w: label.length * 6.6, h: 13 } });
  }
  const feeders = new Map();
  const feederOf = (side, q, c) => {
    const key = `${side}|${q}|${c}`;
    if (!feeders.has(key)) feeders.set(key, feederPath(side, q, c));
    return feeders.get(key);
  };
  const feederPath = (side, q, c) => {
    const cols = NET_COLUMNS.get(q), rq = rects.get(q), rc = rects.get(c);
    if (!cols || !rq || !rc || !cols.rank.has(c)) return null;
    const o = innerOffset(cols.inner);
    const portY = rq.y + rq.anchorY, cy = rc.y + rc.anchorY, r0 = cols.rank.get(c);
    const ranks = side === 'R' ? Array.from({ length: cols.last - r0 }, (_, i) => r0 + 1 + i) : Array.from({ length: r0 }, (_, i) => i);
    const want = (r) => (side === 'R' ? cy + ((portY - cy) * (r - r0)) / (cols.last + 1 - r0) : portY + ((cy - portY) * (r + 1)) / (r0 + 1));
    const via = ranks.filter((r) => cols.colX[r] !== undefined).map((r) => ({ x: o.x + cols.colX[r], w: cols.colW[r], y: o.y + cols.gapNear(r, want(r) - o.y) }));
    let d;
    if (side === 'R') { const start = rc.x + rc.w, out = start + (NET_SLACK.get(c) || 0); d = `M${start},${cy} L${routedPath(out, cy, rq.x + rq.w, portY, via, 30).slice(1)}`; }
    else d = routedPath(rq.x, portY, rc.x, cy, via, 30);
    const feeder = { el: svg('path', { d, class: 'feeder' }) };
    overlay.prepend(feeder.el);
    return feeder;
  };
  const legs = new Map();
  const legOf = (end, id, side) => {
    const key = `${side}|${end}|${id}`;
    if (!legs.has(key)) {
      const chain = N.chain(id), segs = [];
      for (let j = chain.findIndex((x) => x.id === end); j >= 0 && j < chain.length - 1; j++) { const f = feederOf(side, chain[j].id, chain[j + 1].id); if (f) segs.push(f); }
      legs.set(key, segs);
    }
    return legs.get(key);
  };
  const routeOf = (e, d) => {
    const out = legOf(d.g.a, visibleOf(e.from), 'R'), into = legOf(d.g.b, visibleOf(e.to), 'L');
    return { e, segs: [...out, ...into], whole: out.length > 0 && into.length > 0 };
  };
  for (const d of drawn) {
    d.routes = d.g.atoms.map((e) => routeOf(e, d));
    d.traced = d.routes.every((route) => route.whole);
  }
  const lightRoute = (d, route) => { for (const f of route.segs) { f.el.classList.add('hot'); f.el.style.setProperty('--feed', `var(--rel-${d.g.kind})`); } };
  const CELL = 200;
  const placed = new Map();
  const cellsOf = (b) => { const keys = []; for (let cx = Math.floor(b.x / CELL); cx <= Math.floor((b.x + b.w) / CELL); cx++) for (let cy = Math.floor(b.y / CELL); cy <= Math.floor((b.y + b.h) / CELL); cy++) keys.push(`${cx},${cy}`); return keys; };
  for (const d of drawn) {
    if (d.g.shortcut) continue;
    const b = d.labelBox;
    const keys = cellsOf(b);
    if (keys.some((k) => (placed.get(k) || []).some((o) => overlaps(b, o)))) { d.text.classList.add('crowded'); continue; }
    for (const k of keys) { if (!placed.has(k)) placed.set(k, []); placed.get(k).push(b); }
  }
  const highlight = (id) => {
    scene.el.classList.toggle('has-hot', Boolean(id));
    const inside = (x) => id && N.chain(x).some((n) => n.id === id);
    for (const f of feeders.values()) if (f) f.el.classList.remove('hot');
    if (id) for (const d of drawn) for (const route of d.routes) if (inside(route.e.from) || inside(route.e.to)) lightRoute(d, route);
    const ends = [];
    for (const d of drawn) {
      const fromHere = Boolean(id) && (inside(d.g.a) || d.g.atoms.some((e) => inside(e.from)));
      const toHere = Boolean(id) && (inside(d.g.b) || d.g.atoms.some((e) => inside(e.to)));
      const hot = fromHere || toHere;
      if (hot && !(fromHere && toHere)) ends.push(relationEnds(d, fromHere));
      d.path.classList.toggle('hot', hot); d.text.classList.toggle('hot', hot);
    }
    if (scene.onHot) scene.onHot(id ? ends : null);
  };
  let hovered = null;
  let card = null, hoverKey = '';
  const dropCard = () => { if (card) { card.remove(); card = null; } hoverKey = ''; };
  const onArrows = (e) => document.elementsFromPoint(e.clientX, e.clientY).filter((x) => x.classList.contains('rel-hit')).map((x) => drawn[+x.dataset.drawn]);
  scene.el.addEventListener('mousemove', (e) => {
    if (!e.target.closest('.rel-hit')) return;
    const under = onArrows(e);
    const key = under.map((d) => `${d.g.a}|${d.g.b}`).join(' ');
    if (key !== hoverKey) {
      dropCard();
      hovered = null; highlight(null);
      if (!under.length) return;
      hoverKey = key;
      scene.el.classList.add('has-hot');
      for (const d of under) { d.path.classList.add('hot'); d.text.classList.add('hot'); for (const route of d.routes) lightRoute(d, route); }
      const carded = under.filter((d) => !d.traced);
      if (carded.length) { card = edgeCardEl(carded.map((d) => d.g)); document.body.append(card); }
    }
    if (card) placeCard(card, e);
  });
  scene.el.addEventListener('mouseout', (e) => { if (e.target.closest('.rel-hit') && !(e.relatedTarget instanceof Element && e.relatedTarget.closest('.rel-hit'))) { dropCard(); highlight(null); } });
  scene.el.addEventListener('mouseover', (e) => { if (e.target.closest('.rel-hit')) return; const b = e.target.closest('.nb'); const id = b && (!b.classList.contains('open') || e.target.closest('.nhead')) ? b.dataset.id : null; if (id !== hovered) { hovered = id; highlight(id); } });
  scene.el.addEventListener('mouseleave', () => { hovered = null; dropCard(); highlight(null); });
  scene.cull = (view) => {
    for (const r of rects.values()) setCulled(r.el, r, !overlaps(r, view));
    for (const d of drawn) {
      if (!d.box) { const a = pathBox(d.path), t = d.labelBox; const x = Math.min(a.x, t.x), y = Math.min(a.y, t.y); d.box = { x, y, w: Math.max(a.x + a.w, t.x + t.w) - x, h: Math.max(a.y + a.h, t.y + t.h) - y }; }
      const hidden = !overlaps(d.box, view);
      setCulled(d.path, d, hidden);
      d.text.style.display = hidden ? 'none' : '';
      d.hit.style.display = hidden ? 'none' : '';
    }
    for (const f of feeders.values()) if (f) { if (!f.box) f.box = pathBox(f.el); setCulled(f.el, f, !overlaps(f.box, view)); }
  };
  scene.sizes = sizes;
  scene.netRects = rects;
  scene.effective = drawnOpen;
  return scene;
}

function siblingEnds(N, a, b) {
  const ca = N.chain(a), cb = N.chain(b);
  let i = 0;
  while (ca[i + 1] && cb[i + 1] && ca[i + 1] === cb[i + 1]) i++;
  return ca[i + 1] && cb[i + 1] ? [ca[i + 1].id, cb[i + 1].id] : [a, a];
}

function shortcutKeys(links) {
  const next = new Map();
  for (const l of links) { if (!next.has(l.from)) next.set(l.from, new Set()); next.get(l.from).add(l.to); }
  const anotherWay = (from, to) => {
    const cameFrom = new Map([[from, null]]);
    const queue = [...next.get(from)].filter((x) => x !== to);
    for (const x of queue) cameFrom.set(x, from);
    while (queue.length) {
      const v = queue.shift();
      if (v === to) { const path = []; for (let at = to; at !== null; at = cameFrom.get(at)) path.unshift(at); return path; }
      for (const w of next.get(v) || []) if (!cameFrom.has(w)) { cameFrom.set(w, v); queue.push(w); }
    }
    return null;
  };
  const found = new Map();
  for (const l of links) { const path = anotherWay(l.from, l.to); if (path) { next.get(l.from).delete(l.to); found.set(`${l.from}|${l.to}`, path); } }
  return found;
}

function edgeCardEl(gs) {
  const ordered = [...gs].sort((p, q) => Number(p.shortcut) - Number(q.shortcut) || q.count - p.count);
  if (ordered.length <= 3) return el('div', { class: 'edge-card' }, ordered.map((g, i) => edgeCardSection(g, ordered.length > 1 ? 6 : 12, i > 0)));
  const shown = ordered.slice(0, 12);
  return el('div', { class: 'edge-card' },
    el('div', { class: 'edge-card-head' }, el('b', {}, `${ordered.length} arrows meet here`), el('span', { class: 'udim' }, 'follow one further along to see what it stands for')),
    el('div', { class: 'edge-card-rows' }, shown.map((g) => [el('span', {}, netLabel(g.a)), el('span', { class: 'udim' }, '→'), el('span', {}, netLabel(g.b)), el('span', { class: 'udim' }, `${g.count === 1 ? '1 dependency' : `${g.count} dependencies`}${g.shortcut ? ' · shortcut' : ''}`)])),
    ordered.length > shown.length ? el('div', { class: 'udim' }, `and ${ordered.length - shown.length} more`) : null);
}

function edgeCardSection(g, limit, divided) {
  const rows = g.atoms.slice(0, limit);
  const atomLabel = (id, end) => { const home = moduleNodeOf(id); return home && home.id !== id && !net().chain(end).includes(home) ? `${moduleFileName(home)} › ${netLabel(id)}` : netLabel(id); };
  const kindsOf = (e) => [...e.kinds].sort((p, q) => KIND_ORDER.indexOf(p) - KIND_ORDER.indexOf(q));
  return el('div', { class: `edge-card-section${divided ? ' divided' : ''}` },
    el('div', { class: 'edge-card-head' }, el('b', {}, `${netLabel(g.a)} → ${netLabel(g.b)}`), el('span', { class: 'udim' }, g.count === 1 ? '1 dependency' : `${g.count} dependencies`)),
    g.through ? el('div', { class: 'edge-card-through' }, `Shortcut: also reached through ${g.through.slice(1, -1).map(netLabel).join(' → ')}`) : null,
    el('div', { class: 'edge-card-rows' }, rows.map((e) => [el('span', {}, atomLabel(e.from, g.a)), el('span', { class: 'udim' }, '→'), el('span', {}, atomLabel(e.to, g.b)), el('span', { class: 'edge-kind', style: `color:var(--rel-${kindsOf(e)[0]})` }, kindsOf(e).join(' · '))])),
    g.count > rows.length ? el('div', { class: 'udim' }, `and ${g.count - rows.length} more`) : null);
}

function relationEnds(d, outgoing) {
  const other = outgoing ? d.g.b : d.g.a;
  const near = outgoing ? d.g.a : d.g.b;
  const home = moduleNodeOf(other);
  const elsewhere = home && home.id !== other && home !== moduleNodeOf(near);
  const label = elsewhere ? `${moduleFileName(home)} › ${netLabel(other)}` : netLabel(other);
  const kinds = [...d.g.kinds].sort((p, q) => KIND_ORDER.indexOf(p) - KIND_ORDER.indexOf(q)).join(' · ');
  return {
    key: other,
    from: outgoing ? d.ends.a : d.ends.b,
    to: outgoing ? d.ends.b : d.ends.a,
    label,
    color: `var(--rel-${d.g.kind}, var(--rel-uses))`,
    title: `${outgoing ? `${kinds} →` : `← ${kinds} from`} ${elsewhere ? `${home.path} › ${netLabel(other)}` : label}`,
  };
}
function moduleNodeOf(id) { return net().chain(id).find((n) => n.kind === 'module') || null; }
function moduleFileName(module) { return module.name === '__init__.py' && module.parent.kind === 'package' ? `${module.parent.name}/__init__.py` : module.name; }

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
    const diff = it.diff || null;
    for (const [no, text] of it.decorators || []) rows.push({ no, text, diff, path });
    if (it.kind === 'imports') rows.push({ no: it.no, text: it.text, fold: it.count > 1 ? `+${it.count - 1} more imports` : null, diff, path });
    else if (it.kind === 'doc') rows.push({ no: it.no, text: it.text, fold: it.multi ? 'docstring' : null, diff, path });
    else if (it.kind === 'stmt') rows.push({ no: it.no, text: it.text, fold: it.multi ? '⋯' : null, diff, path });
    else if (it.kind === 'def') { const id = cls ? `m:${path}:${qual}` : `fn:${path}:${qual}`; rows.push({ no: it.no, text: it.text, fold: 'body', id: N.nodes.has(id) ? id : null, def: true, diff, path }); }
    else if (it.kind === 'class') {
      const id = `cls:${path}:${qual}`;
      const open = effective.has(id);
      rows.push({ no: it.no, text: it.text, fold: open ? null : 'body', id: N.nodes.has(id) ? id : null, cls: true, open, diff, path });
      if (open) for (const b of it.body) addItem(b, path, qual);
    }
  };
  const open = [...N.nodes.values()].filter((n) => n.kind === 'module' && effective.has(n.id));
  for (const m of open.slice(0, PANEL_MODULES)) {
    rows.push({ banner: true, text: m.path, id: m.id, diff: fileDiff(m.path) });
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
  } else if (DIFF) {
    const c = DIFF.counts;
    const files = Object.entries(DIFF.files);
    ex.append(el('div', { class: 'kind' }, 'Comparing'), el('h2', {}, DIFF.spec),
      el('p', {}, `${DIFF.headLabel} against ${DIFF.baseLabel}: ${plural(files.length, 'Python file')} changed (${c.added} added, ${c.removed} removed, ${c.modified} changed).`));
    const list = el('div', { class: 'diff-files' }, files.slice(0, 60).map(([path, info]) => el('button', { class: `diff-file diff-${info.status}`, title: info.oldPath ? `renamed from ${info.oldPath}` : DIFF_WORD[info.status], onclick: () => ctx.go({ path, sym: null }) }, diffBadge(info.status), el('span', {}, path))));
    if (files.length > 60) list.append(el('span', { class: 'udim' }, `and ${files.length - 60} more`));
    ex.append(list);
  } else {
    ex.append(el('div', { class: 'kind' }, 'Code'), el('h2', {}, 'Folded to match the map'));
    ex.append(el('p', {}, 'This is the real code of every open module, folded to the level you have expanded. Click a class line to expand or fold it here and in the map. Click a def line to open its dataflow view.'));
    if (OVERVIEW) ex.append(el('p', { style: 'color:var(--fg-dim);font-size:0.9em' }, `${OVERVIEW.root} · ${plural(OVERVIEW.modules.length, 'module')}${OVERVIEW.failures && OVERVIEW.failures.length ? ` · ${OVERVIEW.failures.length} could not be read` : ''}`));
  }
  const cv = el('div', { class: 'code-view folded' });
  const paint = pythonPainter();
  for (const r of foldedRows(effective || new Set(), ctx.refresh)) {
    const row = el('div', { class: `ln ${r.banner ? 'banner' : ''} ${r.id ? 'clickable' : ''} ${r.dim ? 'dimrow' : ''} ${r.id && r.id === selId ? 'hl' : ''} ${r.diff ? `diff-${r.diff}` : ''}`, 'data-id': r.id || null, 'data-path': r.path && r.no && r.diff !== 'removed' ? r.path : null, 'data-line': r.path && r.no && r.diff !== 'removed' ? r.no : null, title: r.diff ? DIFF_WORD[r.diff] : null },
      el('span', { class: 'no' }, r.banner ? (effective.has(r.id) ? '▾' : '▸') : r.no || ''),
      DIFF ? el('span', { class: 'sign' }, r.diff ? DIFF_SIGN[r.diff] : '') : null,
      el('span', { class: 'tx' }, r.banner || r.dim || r.diff === 'removed' || !r.text ? r.text || ' ' : paint(r.text, r.no)),
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

const DRAG_THRESHOLD = 4;
const CULL_MARGIN = 0.75;
const POINTER_INSET = 10;
const POINTER_TOP = 46;
const POINTER_BOTTOM = 52;
const POINTER_MAX = 16;
const POINTER_LINGER = 700;
class Viewport {
  constructor(host) {
    this.host = host; this.s = 1; this.x = 0; this.y = 0;
    this.world = el('div', { class: 'world' }); host.append(this.world);
    this.pct = el('span', { class: 'pct' }, '100%');
    this.pointers = new Map();
    this.pointerLayer = el('div', { class: 'edge-pointers' });
    host.append(this.pointerLayer);
    this.hot = null;
    this.gesture = null;
    this.settleTimer = null;
    this.cullFrame = null;
    host.addEventListener('pointerdown', (e) => this.pointerDown(e));
    host.addEventListener('pointermove', (e) => this.pointerMove(e));
    host.addEventListener('pointerup', (e) => this.pointerUp(e));
    host.addEventListener('pointercancel', (e) => this.pointerUp(e, true));
    host.addEventListener('wheel', (e) => this.wheel(e), { passive: false });
    host.addEventListener('scroll', () => { host.scrollLeft = 0; host.scrollTop = 0; });
    host.addEventListener('gesturestart', (e) => this.safariGesture(e, 'start'));
    host.addEventListener('gesturechange', (e) => this.safariGesture(e, 'change'));
    host.addEventListener('gestureend', (e) => this.safariGesture(e, 'end'));
    host.addEventListener('click', (e) => { if (this.swallowClick) { e.stopPropagation(); e.preventDefault(); this.swallowClick = false; } }, true);
    host.append(el('div', { class: 'zoom-ctl' }, this.pct,
      el('button', { class: 'btn small', title: 'Zoom out (Ctrl or ⌘ + scroll, or pinch)', onclick: () => this.zoomCentre(1 / 1.2) }, '−'),
      el('button', { class: 'btn small', title: 'Zoom in (Ctrl or ⌘ + scroll, or pinch)', onclick: () => this.zoomCentre(1.2) }, '+'),
      el('button', { class: 'btn small', title: 'Back to 100%', onclick: () => this.start() }, '1:1'),
      el('button', { class: 'btn small', title: 'Fit everything on screen', onclick: () => this.fit() }, 'Fit')));
  }
  local(e) { const r = this.host.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; }
  pointerDown(e) {
    if (e.pointerType === 'mouse' && e.button !== 0) return;
    if (e.target.closest('.zoom-ctl, .show-chip, .edge-pointer, .comment-card, .pick-bar, input, select, textarea')) return;
    if (e.shiftKey && this.onMarquee && !this.pointers.size) { this.startMarquee(e); return; }
    this.pointers.set(e.pointerId, { ...this.local(e), startX: e.clientX, startY: e.clientY, target: e.target });
    this.swallowClick = false;
    if (this.pointers.size === 1) this.drag = { moved: false, background: !e.target.closest('.nb, .box, button') };
    if (!this.drag) this.drag = { moved: false, background: false };
    if (this.pointers.size === 2) { this.drag.moved = true; this.pinch = this.twoFinger(); }
  }
  pointerMove(e) {
    if (this.marquee && this.marquee.id === e.pointerId) { this.moveMarquee(e); return; }
    const p = this.pointers.get(e.pointerId);
    if (!p) return;
    const now = this.local(e);
    if (this.pointers.size === 1) {
      if (!this.drag.moved && Math.hypot(e.clientX - p.startX, e.clientY - p.startY) < DRAG_THRESHOLD) return;
      if (!this.drag.moved) { this.drag.moved = true; try { this.host.setPointerCapture(e.pointerId); } catch (err) {} this.host.classList.add('dragging'); }
      this.panBy(now.x - p.x, now.y - p.y);
      Object.assign(p, now);
      return;
    }
    Object.assign(p, now);
    if (this.pointers.size === 2 && this.pinch) {
      const next = this.twoFinger();
      this.panBy(next.cx - this.pinch.cx, next.cy - this.pinch.cy);
      if (this.pinch.d > 0) this.zoomAt(next.cx, next.cy, next.d / this.pinch.d);
      this.pinch = next;
    }
  }
  pointerUp(e, cancelled = false) {
    if (this.marquee && this.marquee.id === e.pointerId) { this.endMarquee(e, cancelled); return; }
    if (!this.pointers.has(e.pointerId)) return;
    this.pointers.delete(e.pointerId);
    if (this.pointers.size === 1) { const [rest] = this.pointers.values(); this.pinch = null; this.drag.moved = true; Object.assign(rest, { startX: -1e9 }); return; }
    if (this.pointers.size) return;
    this.pinch = null;
    this.host.classList.remove('dragging');
    if (this.drag && this.drag.moved) this.swallowClick = true;
    else if (!cancelled && this.drag && this.drag.background && this.onBackground) this.onBackground();
    this.drag = null;
  }
  startMarquee(e) {
    const at = this.local(e);
    const box = el('div', { class: 'marquee' });
    this.host.append(box);
    this.marquee = { id: e.pointerId, x0: at.x, y0: at.y, x1: at.x, y1: at.y, box, additive: e.metaKey || e.ctrlKey };
    try { this.host.setPointerCapture(e.pointerId); } catch (err) {}
    this.moveMarquee(e);
  }
  moveMarquee(e) {
    const m = this.marquee;
    const at = this.local(e);
    m.x1 = at.x; m.y1 = at.y;
    Object.assign(m.box.style, { left: `${Math.min(m.x0, m.x1)}px`, top: `${Math.min(m.y0, m.y1)}px`, width: `${Math.abs(m.x1 - m.x0)}px`, height: `${Math.abs(m.y1 - m.y0)}px` });
  }
  endMarquee(e, cancelled) {
    const m = this.marquee;
    this.marquee = null;
    m.box.remove();
    this.swallowClick = true;
    if (cancelled || Math.hypot(m.x1 - m.x0, m.y1 - m.y0) < DRAG_THRESHOLD) return;
    const x = (Math.min(m.x0, m.x1) - this.x) / this.s, y = (Math.min(m.y0, m.y1) - this.y) / this.s;
    this.onMarquee({ x, y, w: Math.abs(m.x1 - m.x0) / this.s, h: Math.abs(m.y1 - m.y0) / this.s }, m.additive);
  }
  twoFinger() {
    const [a, b] = [...this.pointers.values()];
    return { cx: (a.x + b.x) / 2, cy: (a.y + b.y) / 2, d: Math.hypot(a.x - b.x, a.y - b.y) };
  }
  wheel(e) {
    if (e.target.closest('.comment-card')) { if (e.ctrlKey || e.metaKey) e.preventDefault(); return; }
    e.preventDefault();
    const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? this.host.clientHeight : 1;
    const p = this.local(e);
    if (e.ctrlKey || e.metaKey) this.zoomAt(p.x, p.y, Math.exp(-e.deltaY * unit * (e.ctrlKey && !e.metaKey && unit === 1 && Math.abs(e.deltaY) < 50 ? 0.01 : 0.002)));
    else this.panBy(-e.deltaX * unit, -e.deltaY * unit);
  }
  safariGesture(e, phase) {
    e.preventDefault();
    if ([...this.pointers.values()].length) return;
    const p = this.local(e);
    if (phase === 'start') this.safariScale = 1;
    else if (phase === 'change' && this.safariScale) { this.zoomAt(p.x, p.y, e.scale / this.safariScale); this.safariScale = e.scale; }
    else this.safariScale = null;
  }
  panBy(dx, dy) { this.x += dx; this.y += dy; this.apply(true); }
  setScene(scene, how = 'start') { this.world.innerHTML = ''; this.scene = scene; clearTimeout(this.pointerTimer); this.hot = null; this.pointerLayer.innerHTML = ''; scene.onHot = (hot) => this.showPointers(hot); this.world.append(scene.el); if (how === 'start') this.start(); else if (how === 'fit') this.fit(); this.apply(); }
  apply(moving = false) {
    this.world.style.transform = `translate(${this.x}px, ${this.y}px) scale(${this.s})`;
    const g = 16 * this.s, G2 = g * 8;
    this.host.style.backgroundSize = `${G2}px ${G2}px, ${G2}px ${G2}px, ${g}px ${g}px, ${g}px ${g}px`;
    this.host.style.backgroundPosition = `${this.x}px ${this.y}px`;
    this.pct.textContent = `${Math.round(this.s * 100)}%`;
    this.world.classList.toggle('far', this.s < 0.4);
    if (moving) {
      this.world.style.willChange = 'transform';
      clearTimeout(this.settleTimer);
      this.settleTimer = setTimeout(() => { this.cull(); this.world.style.willChange = ''; }, 160);
      this.scheduleCull();
    } else {
      clearTimeout(this.cullFrame);
      this.cullFrame = null;
      this.cull();
    }
    if (this.hot) this.drawPointers();
  }
  showPointers(hot) {
    clearTimeout(this.pointerTimer);
    if (hot && hot.length) { this.hot = hot; this.drawPointers(); return; }
    if (!this.hot) return;
    this.pointerTimer = setTimeout(() => { if (this.pointerLayer.querySelector('.edge-pointer:hover')) return; this.hot = null; this.drawPointers(); }, hot ? 0 : POINTER_LINGER);
  }
  drawPointers() {
    const layer = this.pointerLayer;
    layer.innerHTML = '';
    if (!this.hot) return;
    const W = this.host.clientWidth, H = this.host.clientHeight;
    const frame = { l: POINTER_INSET, t: POINTER_TOP, r: W - POINTER_INSET, b: H - POINTER_BOTTOM };
    if (frame.r <= frame.l || frame.b <= frame.t) return;
    const onScreen = (p) => ({ x: this.x + p.x * this.s, y: this.y + p.y * this.s });
    const away = new Map();
    for (const h of this.hot) {
      const at = onScreen(h.to);
      if (at.x >= 0 && at.x <= W && at.y >= 0 && at.y <= H) continue;
      if (!away.has(h.key)) away.set(h.key, { ...h, at, origin: onScreen(h.from) });
    }
    const far = [...away.values()].sort((p, q) => Math.hypot(p.at.x - p.origin.x, p.at.y - p.origin.y) - Math.hypot(q.at.x - q.origin.x, q.at.y - q.origin.y));
    const placed = [];
    for (const h of far.slice(0, POINTER_MAX)) {
      const ox = clamp(h.origin.x, frame.l, frame.r), oy = clamp(h.origin.y, frame.t, frame.b);
      const dx = h.at.x - ox, dy = h.at.y - oy;
      const reach = Math.min(dx > 0 ? (frame.r - ox) / dx : dx < 0 ? (frame.l - ox) / dx : Infinity, dy > 0 ? (frame.b - oy) / dy : dy < 0 ? (frame.t - oy) / dy : Infinity);
      const px = ox + dx * reach, py = oy + dy * reach;
      const arrow = el('span', { class: 'arrow', style: `transform:rotate(${(Math.atan2(dy, dx) * 180) / Math.PI}deg)` }, '➜');
      const name = el('span', { class: 'name' }, h.label);
      const chip = el('button', { class: 'edge-pointer', style: `--pc:${h.color}`, title: `${h.title} · click to go there`, onclick: (e) => { e.stopPropagation(); this.glideTo(h.to); }, onmouseenter: () => clearTimeout(this.pointerTimer), onmouseleave: () => this.showPointers(null) }, ...(dx < 0 ? [arrow, name] : [name, arrow]));
      layer.append(chip);
      placeChip(chip, px, py, Math.abs(px - frame.l) < 1 || Math.abs(px - frame.r) < 1, W, H, placed);
    }
    if (far.length > POINTER_MAX) {
      const more = el('div', { class: 'edge-pointer more' }, `+${far.length - POINTER_MAX} more off screen`);
      layer.append(more);
      placeChip(more, W / 2, frame.b, false, W, H, placed);
    }
  }
  glideTo(p) {
    const W = this.host.clientWidth, H = this.host.clientHeight;
    const x0 = this.x, y0 = this.y, x1 = W / 2 - p.x * this.s, y1 = H / 2 - p.y * this.s;
    const begun = performance.now();
    this.hot = null;
    this.pointerLayer.innerHTML = '';
    const step = (now) => {
      const k = Math.min(1, (now - begun) / 320);
      const eased = 1 - (1 - k) ** 3;
      this.x = x0 + (x1 - x0) * eased; this.y = y0 + (y1 - y0) * eased;
      this.apply(k < 1);
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
  scheduleCull() {
    if (this.cullFrame) return;
    this.cullFrame = setTimeout(() => { this.cullFrame = null; this.cull(); }, 120);
  }
  cull() {
    if (!this.scene || !this.scene.cull) return;
    const w = this.host.clientWidth / this.s, h = this.host.clientHeight / this.s;
    this.scene.cull({ x: -this.x / this.s - w * CULL_MARGIN, y: -this.y / this.s - h * CULL_MARGIN, w: w * (1 + 2 * CULL_MARGIN), h: h * (1 + 2 * CULL_MARGIN) });
  }
  zoomAt(px, py, f) { const ns = Math.min(2.5, Math.max(0.05, this.s * f)); f = ns / this.s; this.x = px - (px - this.x) * f; this.y = py - (py - this.y) * f; this.s = ns; this.apply(true); }
  zoomCentre(f) { this.zoomAt(this.host.clientWidth / 2, this.host.clientHeight / 2, f); }
  fit() { if (!this.scene) return; const W = this.host.clientWidth, H = this.host.clientHeight; this.s = Math.min(1.2, Math.max(0.05, Math.min(W / this.scene.width, (H - 40) / this.scene.height))); this.x = (W - this.scene.width * this.s) / 2; this.y = Math.max(20, (H - this.scene.height * this.s) / 2); this.apply(); }
  start() { if (!this.scene) return; const W = this.host.clientWidth, H = this.host.clientHeight; const fitS = Math.min(W / this.scene.width, (H - 60) / this.scene.height); this.s = Math.max(0.75, Math.min(1, fitS)); this.x = this.scene.width * this.s <= W ? (W - this.scene.width * this.s) / 2 : 0; this.y = this.scene.height * this.s <= H - 60 ? (H - this.scene.height * this.s) / 2 : 30; this.apply(); }
  centreOn(elm) { const r = elm.getBoundingClientRect(), hr = this.host.getBoundingClientRect(); this.x += hr.left + hr.width / 2 - (r.left + r.width / 2); this.y += hr.top + hr.height / 2 - (r.top + r.height / 2); this.apply(); }
}

function clamp(v, lo, hi) { return Math.min(hi, Math.max(lo, v)); }
function placeChip(chip, px, py, alongY, W, H, placed) {
  const w = chip.offsetWidth, h = chip.offsetHeight;
  const top = POINTER_TOP - h / 2;
  const x0 = clamp(px - w / 2, 4, Math.max(4, W - w - 4)), y0 = clamp(py - h / 2, top, Math.max(top, H - h - 4));
  let box = { x: x0, y: y0, w, h };
  for (let i = 1; i < 40 && placed.some((o) => overlaps(box, { x: o.x - 3, y: o.y - 3, w: o.w + 6, h: o.h + 6 })); i++) {
    const shift = Math.ceil(i / 2) * (i % 2 ? 1 : -1) * ((alongY ? h : w / 2) + 4);
    box = alongY ? { ...box, y: clamp(y0 + shift, top, Math.max(top, H - h - 4)) } : { ...box, x: clamp(x0 + shift, 4, Math.max(4, W - w - 4)) };
  }
  placed.push(box);
  chip.style.left = `${box.x}px`;
  chip.style.top = `${box.y}px`;
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
    case 'expr': return `${n.title} works out ${n.expr.join(' ')} from ${n.ins.map((p) => p.name).join(', ') || 'fixed values'}.`;
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
      callers.sort((a, b) => Number(isTestPath(a.path)) - Number(isTestPath(b.path)) || a.path.localeCompare(b.path) || a.sym.localeCompare(b.sym));
      const shown = callers.slice(0, 8);
      if (callers.length) ex.append(el('div', { class: 'kind' }, 'Called from'), el('div', { class: 'links' }, shown.map((c) => el('button', { onclick: () => ctx.activate(c, null, null) }, `${c.sym} · ${baseName(c.path)}`)), callers.length > shown.length ? el('span', { class: 'udim' }, `and ${callers.length - shown.length} more`) : null));
    }
  }
  const codeRows = sym.codeLines || (sym.code ? sym.code.split('\n').map((t, i) => [sym.line + i, t]) : null);
  if (codeRows) {
    const line = node ? node.line : null;
    const cv = el('div', { class: 'code-view' });
    const wanted = node && node.diff === 'removed' ? 'removed' : null;
    const target = node && node.diff === 'removed' ? node.baseLine : line;
    const paint = pythonPainter();
    codeRows.forEach(([no, ln, change]) => {
      const hit = target && no === target && node.kind !== 'entry' && (change === 'removed') === (wanted === 'removed');
      cv.append(el('div', { class: `ln ${hit ? 'hl' : ''} ${change ? `diff-${change}` : ''}`, title: change ? DIFF_WORD[change] : null, 'data-path': change === 'removed' ? null : sym.file, 'data-line': change === 'removed' ? null : no, 'data-qual': sym.kind === 'function' ? sym.qual : null }, el('span', { class: 'no' }, no), DIFF ? el('span', { class: 'sign' }, change ? DIFF_SIGN[change] : '') : null, el('span', { class: 'tx' }, change === 'removed' || !ln ? ln || ' ' : paint(ln, no))));
    });
    panel.append(cv);
    const hl = cv.querySelector('.hl'); if (hl) requestAnimationFrame(() => hl.scrollIntoView({ block: 'nearest' }));
  }
}

function legendInto(container) {
  container.append(el('div', { class: 'kind', style: 'font-size:0.72em;letter-spacing:0.08em;text-transform:uppercase;color:var(--fg-dim)' }, 'File diagram lines'));
  const line = (kind, dashed, label) => container.append(el('div', { class: 'legend-row legend-line' }, el('span', { html: `<svg viewBox="0 0 46 12"><path d="M2,6 H38" style="stroke:var(--rel-${kind === 'realizes' ? 'inherits' : kind})" stroke-width="2" ${dashed ? 'stroke-dasharray="6 4"' : ''}/>${kind === 'inherits' || kind === 'realizes' ? '<path d="M36,1 L45,6 L36,11 z" style="fill:var(--canvas);stroke:var(--rel-inherits)" stroke-width="1.4"/>' : `<path d="M37,1 L45,6 L37,11" style="fill:none;stroke:var(--rel-${kind})" stroke-width="1.6"/>`}${kind === 'has' ? '<path d="M1,6 L6,2.5 L11,6 L6,9.5 z" style="fill:var(--rel-has)"/>' : ''}</svg>` }), el('span', {}, label)));
  if (DIFF) {
    container.append(el('div', { class: 'kind', style: 'font-size:0.72em;letter-spacing:0.08em;text-transform:uppercase;color:var(--fg-dim)' }, `Changes in ${DIFF.spec}`));
    for (const [state, text] of [['added', 'added'], ['removed', 'removed'], ['modified', 'changed, or something inside it changed']]) container.append(el('div', { class: 'legend-row' }, diffBadge(state), el('span', {}, text)));
  }
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
    if (pop.getBoundingClientRect().left < 12) { pop.style.right = 'auto'; pop.style.left = `${Math.max(12, r.left)}px`; }
  });
  return btn;
}
const COG_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill-rule="evenodd" d="M19.62,10.33 L22.42,10.68 L22.42,13.32 L19.62,13.67 L18.57,16.21 L20.30,18.44 L18.44,20.30 L16.21,18.57 L13.67,19.62 L13.32,22.42 L10.68,22.42 L10.33,19.62 L7.79,18.57 L5.56,20.30 L3.70,18.44 L5.43,16.21 L4.38,13.67 L1.58,13.32 L1.58,10.68 L4.38,10.33 L5.43,7.79 L3.70,5.56 L5.56,3.70 L7.79,5.43 L10.33,4.38 L10.68,1.58 L13.32,1.58 L13.67,4.38 L16.21,5.43 L18.44,3.70 L20.30,5.56 L18.57,7.79 Z M15,12 A3,3 0 1,0 9,12 A3,3 0 1,0 15,12 Z"/></svg>';
function dataScopeChip(scope, onPick) {
  const pick = el('select', { id: 'data-scope', onchange: (ev) => onPick(ev.target.value) }, dataScopes(net()).map((s) => {
    const option = el('option', { value: s.id }, `${'\u00a0\u00a0'.repeat(Math.max(0, s.depth - 1))}${s.label} · ${s.count}`);
    if (s.id === scope) option.selected = true;
    return option;
  }));
  return el('div', { class: 'focus-chip data-scope' }, el('label', { for: 'data-scope' }, 'Data classes in'), pick, el('span', { class: 'udim' }, 'Faded boxes live elsewhere and link in.'));
}
function settingsButton(onChange) {
  const btn = popoverButton(el('span', { class: 'cog', html: COG_ICON }), 'layout-menu', (pop) => {
    const done = () => { saveSettings(); applySettings(); onChange(); };
    const sel = (id, value, opts, fn2) => el('select', { id, onchange: (ev) => fn2(ev.target.value) }, opts.map(([v, l]) => { const o = el('option', { value: v }, l); if (String(v) === String(value)) o.selected = true; return o; }));
    const chk = (id, value, fn2) => { const c = el('input', { type: 'checkbox', id, onchange: (ev) => fn2(ev.target.checked) }); c.checked = value; return c; };
    pop.append(el('div', { class: 'popover-title' }, 'Reading'), el('div', { class: 'popover-rows' },
      el('label', { for: 'set-font' }, 'Label font', sel('set-font', settings.pinFont, [['mono', 'Monospace'], ['lexend', 'Lexend'], ['atkinson', 'Atkinson Hyperlegible'], ['comic', 'Comic Neue']], (v) => { settings.pinFont = v; done(); })),
      el('label', { for: 'set-size' }, 'Node text', sel('set-size', settings.size, [[11, 'Small'], [12.5, 'Normal'], [14, 'Large'], [16, 'Extra large']], (v) => { settings.size = +v; done(); })),
      el('label', { for: 'set-theme' }, 'Background', sel('set-theme', settings.theme, [['dark', 'Dark'], ['light', 'Soft paper'], ['system', 'Match device']], (v) => { settings.theme = v; done(); })),
      el('label', { for: 'set-plain' }, 'Spaced-out names', chk('set-plain', settings.plain, (v) => { settings.plain = v; done(); })),
      el('label', { for: 'set-types' }, 'Type names on pins', chk('set-types', settings.types, (v) => { settings.types = v; done(); }))));
    pop.append(el('div', { class: 'popover-title popover-section' }, 'Layout'));
    for (const option of LAYOUT_CHOICES) {
      const radio = el('input', { type: 'radio', name: 'set-layout', id: `set-layout-${option.key}`, value: option.key, onchange: () => { settings.layout = option.key; saveSettings(); onChange(); } });
      radio.checked = settings.layout === option.key;
      pop.append(el('label', { class: 'layout-option', for: radio.id }, radio, el('span', {}, el('b', {}, option.label), el('small', {}, option.hint))));
    }
    pop.append(el('small', { class: 'popover-foot' }, 'Applies to function blueprints and the map. On the map, Balanced and Classic are the same.'));
  });
  btn.title = 'Settings';
  btn.setAttribute('aria-label', 'Settings');
  return btn;
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

function compareButton() {
  const button = popoverButton(DIFF ? `± ${shortSpec(DIFF.spec)}` : '± Compare', 'compare', (pop) => {
    const input = el('input', { id: 'diff-spec', class: 'path-input', placeholder: 'develop..my-branch', value: DIFF ? DIFF.spec : '', list: 'diff-branches', autocomplete: 'off', spellcheck: 'false' });
    const branches = el('datalist', { id: 'diff-branches' });
    const message = el('p', { class: 'error-text', hidden: true });
    const run = async (spec) => {
      message.hidden = true;
      try { await api(`/api/diff?spec=${encodeURIComponent(spec)}`); } catch (error) { message.textContent = error.message; message.hidden = false; return; }
      pop.remove();
      waitForProject();
    };
    pop.append(el('form', { class: 'compare-form', onsubmit: (e) => { e.preventDefault(); if (input.value.trim()) run(input.value.trim()); } },
      el('label', { for: 'diff-spec' }, 'Show the changes in a git range'), input, branches,
      el('p', { class: 'muted small' }, 'A..B compares the tips of A and B. A...B compares B with the point where it branched off A, like a pull request. A on its own compares A with your working copy.'),
      message,
      el('div', { class: 'actions' }, el('button', { class: 'btn primary', type: 'submit' }, 'Compare'), DIFF ? el('button', { class: 'btn', type: 'button', onclick: () => run('') }, 'Stop comparing') : null)));
    setTimeout(() => input.focus(), 0);
    let names = [];
    const refill = () => {
      const typed = input.value.match(/^(.*?)(\.\.\.?)/);
      branches.innerHTML = '';
      for (const name of names.slice(0, 200)) branches.append(el('option', { value: typed ? `${typed[1]}${typed[2]}${name}` : name }));
    };
    input.addEventListener('input', refill);
    api('/api/branches').then((data) => { names = data.branches; refill(); }, () => {});
  });
  button.title = DIFF ? `Comparing ${DIFF.spec}` : 'Compare with a git branch';
  if (DIFF) button.classList.add('comparing');
  return button;
}
function shortSpec(spec) {
  const short = spec.replace(/\b[0-9a-f]{12,40}\b/g, (sha) => sha.slice(0, 8));
  return short.length > 32 ? `${short.slice(0, 31)}…` : short;
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
    compareButton(),
    crumbs, popoverButton('● Key', 'legend', legendInto), settingsButton(onSettings)));
  const row = el('div', { class: 'body-row' });
  const vpHost = el('div', { class: 'viewport' });
  const bar = el('div', { class: 'resize-bar', title: 'Drag to resize the code panel' });
  right.append(bar);
  const tab = el('button', { class: 'code-tab', title: 'Click to show or hide the code, drag to resize it' }, el('span', { class: 'chev' }, '⌄'), 'Code');
  const mainCol = el('div', { class: 'main-col' }, vpHost, el('div', { class: 'code-dock' }, tab), right);
  row.append(left, mainCol);
  root.append(row);
  try { const saved = localStorage.getItem(`${SETTINGS_KEY}-bottom`); if (saved) right.style.setProperty('--bottom-h', saved); right.hidden = localStorage.getItem(`${SETTINGS_KEY}-code-hidden`) === '1'; } catch (e) {}
  const remember = () => { try { localStorage.setItem(`${SETTINGS_KEY}-bottom`, right.style.getPropertyValue('--bottom-h')); localStorage.setItem(`${SETTINGS_KEY}-code-hidden`, right.hidden ? '1' : '0'); } catch (err) {} };
  const resizeFrom = (handle, onClick) => handle.addEventListener('pointerdown', (e) => {
    e.preventDefault();
    handle.setPointerCapture(e.pointerId);
    const colRect = mainCol.getBoundingClientRect();
    let dragged = false;
    const move = (ev) => {
      if (!dragged && Math.abs(ev.clientY - e.clientY) < 4) return;
      dragged = true;
      right.hidden = false;
      const h = Math.min(colRect.height * 0.75, Math.max(90, colRect.bottom - ev.clientY));
      right.style.setProperty('--bottom-h', `${Math.round(h)}px`);
    };
    const up = () => { handle.removeEventListener('pointermove', move); handle.removeEventListener('pointerup', up); if (!dragged && onClick) onClick(); remember(); };
    handle.addEventListener('pointermove', move);
    handle.addEventListener('pointerup', up);
  });
  resizeFrom(bar, null);
  resizeFrom(tab, () => { right.hidden = !right.hidden; });
  tab.addEventListener('click', (e) => { if (e.detail === 0) { right.hidden = !right.hidden; remember(); } });
  if (window.innerWidth <= 760) { left.hidden = true; }
  return { crumbs, left, right, vpHost };
}
const TREE_OPEN = new Set();
const CHANGES_CLOSED = new Set();
const FILE_UNITS_OPEN = new Map();
const SIDE_TAB_KEY = `${SETTINGS_KEY}-side-tab`;
let SIDE_TAB = (() => { try { return localStorage.getItem(SIDE_TAB_KEY) || 'changes'; } catch (e) { return 'changes'; } })();
let SIDE_SHOWN = null;
function renderSide(left, currentPath, currentSym, onPick) {
  const scroll = left.scrollTop;
  left.innerHTML = '';
  const redraw = () => renderSide(left, currentPath, currentSym, onPick);
  const tab = SIDE_TAB === 'changes' && !DIFF ? 'files' : SIDE_TAB;
  const pick = (name) => { SIDE_TAB = name; try { localStorage.setItem(SIDE_TAB_KEY, name); } catch (e) {} left.scrollTop = 0; redraw(); };
  const tabButton = (name, label, title, count) => el('button', { class: `side-tab ${tab === name ? 'on' : ''}`, role: 'tab', 'aria-selected': String(tab === name), title, onclick: () => pick(name) }, label, count != null ? el('small', {}, count) : null);
  const all = DIFF ? Object.keys(DIFF.files).flatMap(fileUnits) : [];
  const openCount = openThreads().length;
  left.append(el('div', { class: 'side-tabs', role: 'tablist' },
    tabButton('files', 'Files', 'Every file in the project'),
    DIFF ? tabButton('changes', 'Changes', `${seenCount(all)} of ${all.length} changes seen`, `${seenCount(all)}/${all.length}`) : null,
    tabButton('comments', 'Comments', `${plural(openCount, 'open comment')}`, openCount || null)));
  if (tab === 'changes') renderChanges(left, currentPath, currentSym, onPick, redraw);
  else if (tab === 'comments') renderCommentList(left);
  else renderFiles(left, currentPath, currentSym, onPick, redraw);
  left.scrollTop = scroll;
  const shown = `${tab}|${currentPath}|${currentSym}`;
  if (shown !== SIDE_SHOWN) { SIDE_SHOWN = shown; const active = left.querySelector('.active'); if (active) active.scrollIntoView({ block: 'nearest' }); }
}
function renderFiles(left, currentPath, currentSym, onPick, redraw) {
  left.append(el('h3', {}, OVERVIEW ? OVERVIEW.name : 'Files'));
  if (currentPath) { let acc = ''; for (const part of currentPath.split('/').slice(0, -1)) { acc += (acc ? '/' : '') + part; TREE_OPEN.add(acc); } }
  const box = el('div', { class: 'tree' });
  const draw = (node, prefix, depth) => {
    for (const name of Object.keys(node.dirs).sort()) {
      const full = prefix ? `${prefix}/${name}` : name;
      const isOpen = TREE_OPEN.has(full);
      const folderState = folderDiff(full);
      box.append(el('button', { class: `tree-item folder${folderState ? ` diff-${folderState}` : ''}`, style: `padding-left:${12 + depth * 14}px`, onclick: () => { if (isOpen) TREE_OPEN.delete(full); else TREE_OPEN.add(full); redraw(); } }, `${isOpen ? '▾' : '▸'} ${name}/`, diffBadge(folderState)));
      if (isOpen) draw(node.dirs[name], full, depth + 1);
    }
    for (const path of node.files.sort()) { const state = fileDiff(path); box.append(el('button', { class: `tree-item ${path === currentPath ? 'active' : ''}${state ? ` diff-${state}` : ''}`, style: `padding-left:${26 + depth * 14}px`, title: state ? `${path} (${DIFF_WORD[state]})` : path, onclick: () => onPick({ path, sym: null }) }, baseName(path), seenMark(fileUnits(path)), diffBadge(state))); }
  };
  draw(pathTree(Object.keys(FILES)), '', 0);
  left.append(box);
  const f = currentPath ? FILES[currentPath] : null;
  if (!f) return;
  left.append(el('h3', {}, `In ${baseName(currentPath)}`));
  for (const s of f.symbols) {
    const color = s.kind === 'function' ? '--h-call' : s.kind === 'enum' ? '--h-enum' : '--h-make';
    const state = symbolDiff(refOf(s));
    left.append(el('button', { class: `tree-item ${currentSym === s.qual ? 'active' : ''}${state ? ` diff-${state}` : ''}`, onclick: () => onPick(refOf(s)) }, el('span', { class: 'dot', style: `background:var(${color})` }), s.name, seenMark(symbolUnits(refOf(s))), diffBadge(state)));
    for (const m of s.methods || []) { const mState = symbolDiff(refOf(m)); left.append(el('button', { class: `tree-item ${currentSym === m.qual ? 'active' : ''}${mState ? ` diff-${mState}` : ''}`, style: 'padding-left:32px', onclick: () => onPick(refOf(m)) }, el('span', { class: 'dot', style: 'background:var(--h-method)' }), m.name, seenMark(symbolUnits(refOf(m))), diffBadge(mState))); }
  }
}
function pathTree(paths) {
  const root = { dirs: {}, files: [] };
  for (const path of paths) {
    let node = root;
    for (const part of path.split('/').slice(0, -1)) node = node.dirs[part] = node.dirs[part] || { dirs: {}, files: [] };
    node.files.push(path);
  }
  return root;
}
function reviewRow({ depth, units, what, chevron, onChevron, label, onClick, active, state, title }) {
  const seen = seenState(units) === 'all';
  return el('div', { class: `tree-row${active ? ' active' : ''}${seen ? ' seen' : ''}`, style: `padding-left:${8 + depth * 14}px` },
    chevron ? el('button', { class: 'chev', title: chevron === '▾' ? 'Collapse' : 'Expand', onclick: onChevron }, chevron) : el('span', { class: 'chev' }),
    seenBox(units, what),
    el('button', { class: `tree-item${active ? ' active' : ''}${state ? ` diff-${state}` : ''}`, title: title || what, onclick: onClick }, ...label, units.length > 1 ? el('span', { class: 'count' }, `${seenCount(units)}/${units.length}`) : null, diffBadge(state)));
}
function renderChanges(left, currentPath, currentSym, onPick, redraw) {
  const paths = Object.keys(DIFF.files).sort();
  const all = paths.flatMap(fileUnits);
  const done = seenCount(all);
  left.append(el('div', { class: 'review-progress' },
    el('div', { class: 'review-bar' }, el('span', { style: `width:${all.length ? (100 * done) / all.length : 0}%` })),
    el('span', {}, all.length ? `${done} of ${all.length} changes seen` : 'Nothing changed')));
  const box = el('div', { class: 'tree' });
  const draw = (node, prefix, depth) => {
    for (const first of Object.keys(node.dirs).sort()) {
      let name = first, full = prefix ? `${prefix}/${first}` : first, inner = node.dirs[first];
      while (!inner.files.length && Object.keys(inner.dirs).length === 1) { const only = Object.keys(inner.dirs)[0]; name += `/${only}`; full += `/${only}`; inner = inner.dirs[only]; }
      const isOpen = !CHANGES_CLOSED.has(full);
      const toggle = () => { if (isOpen) CHANGES_CLOSED.add(full); else CHANGES_CLOSED.delete(full); redraw(); };
      box.append(reviewRow({ depth, units: unitsUnder(full), what: `everything in ${full}/`, chevron: isOpen ? '▾' : '▸', onChevron: toggle, label: [el('span', { class: 'label folder-name' }, `${name}/`)], onClick: toggle, title: full }));
      if (isOpen) draw(inner, full, depth + 1);
    }
    for (const path of node.files) {
      const units = fileUnits(path);
      const isOpen = FILE_UNITS_OPEN.has(path) ? FILE_UNITS_OPEN.get(path) : path === currentPath;
      const info = DIFF.files[path];
      box.append(reviewRow({ depth, units, what: baseName(path), chevron: isOpen ? '▾' : '▸', onChevron: () => { FILE_UNITS_OPEN.set(path, !isOpen); redraw(); }, label: [el('span', { class: 'label' }, baseName(path))], onClick: () => onPick({ path, sym: null }), active: path === currentPath && !currentSym, state: info.status, title: info.oldPath ? `${path} (renamed from ${info.oldPath})` : path }));
      if (isOpen) drawUnits(path, units, depth + 1);
    }
  };
  const drawUnits = (path, units, depth) => {
    const emitted = new Set();
    for (const unit of units) {
      if (!unit.owner) { box.append(unitRow(path, unit, depth)); continue; }
      if (emitted.has(unit.owner)) continue;
      emitted.add(unit.owner);
      const members = units.filter((u) => u.owner === unit.owner);
      const owner = { path, sym: unit.owner };
      box.append(reviewRow({ depth, units: members, what: `class ${unit.owner}`, label: [el('span', { class: 'dot', style: 'background:var(--h-make)' }), el('span', { class: 'label' }, unit.owner)], onClick: () => onPick(owner), active: path === currentPath && currentSym === unit.owner, state: symbolDiff(owner) || unit.diff }));
      for (const member of members) box.append(unitRow(path, member, depth + 1));
    }
  };
  const unitRow = (path, unit, depth) => {
    const name = unit.kind === 'top' ? 'Module-level code' : unit.kind === 'body' ? 'Class body' : unit.owner ? unit.qual.slice(unit.owner.length + 1) : unit.qual;
    const plainText = unit.kind === 'top' || unit.kind === 'body';
    const target = { path, sym: unit.kind === 'top' ? null : unit.kind === 'body' ? unit.owner : unit.qual };
    const dot = plainText ? null : el('span', { class: 'dot', style: `background:var(${unit.owner ? '--h-method' : '--h-call'})` });
    return reviewRow({ depth, units: [unit], what: plainText ? `${name.toLowerCase()} of ${unit.owner || baseName(path)}` : name, label: [dot, el('span', { class: `label${plainText ? ' unit-note' : ''}` }, name)], onClick: () => onPick(target), active: !plainText && path === currentPath && currentSym === unit.qual, state: unit.diff });
  };
  draw(pathTree(paths), '', 0);
  left.append(box);
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
    if (!entries.some((s) => s.el.offsetParent && (Math.abs(s.el.offsetWidth - s.w) > 1 || Math.abs(s.el.offsetHeight - s.h) > 1))) return;
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
  if (DIFF) {
    const changed = Object.keys(DIFF.files);
    for (const path of changed) {
      const chain = net().chain(`mod:${path}`);
      for (const n of chain.slice(1, changed.length <= 12 ? undefined : -1)) if (n.children.length) ex.add(n.id);
    }
    if (ex.size) return ex;
  }
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
  const expandedAtStart = startExpanded();
  const firstChange = DIFF && Object.keys(DIFF.files).sort()[0];
  const startFocus = firstChange ? [...net().chain(`mod:${firstChange}`)].reverse().find((n) => n.id === `mod:${firstChange}` ? net().chain(n.id).slice(1, -1).every((a) => expandedAtStart.has(a.id)) : expandedAtStart.has(n.id)) : null;
  const start = { view: 'net', expanded: expandedAtStart, focus: startFocus ? startFocus.id : null, open: new Set() };
  const st = { stack: [start], fwd: [], selected: null };
  const cur = () => st.stack[st.stack.length - 1];
  const lastNet = () => [...st.stack].reverse().find((e) => e.view === 'net') || start;
  const back = el('button', { class: 'btn', title: 'Back (Alt+←)', onclick: () => { if (st.stack.length > 1) { st.fwd.push(st.stack.pop()); st.selected = null; PICK = null; render(false); } } }, '←');
  const fwd = el('button', { class: 'btn', title: 'Forward (Alt+→)', onclick: () => { if (st.fwd.length) { st.stack.push(st.fwd.pop()); st.selected = null; PICK = null; render(false); } } }, '→');
  const foldAll = el('button', { class: 'btn', title: 'Fold every open node back up', onclick: () => { cur().open.clear(); render(true); } }, '⊟ Fold all');
  const openOther = el('button', { class: 'btn', title: 'Open another project folder', onclick: () => showWelcome() }, 'Open…');
  const reload = el('button', { class: 'btn', title: 'Read the project again after editing code', onclick: () => { api('/api/reload').then(() => waitForProject(), (err) => showWelcome(err.message)); } }, '↻ Reload');
  const dataButton = el('button', { class: 'btn', title: 'Show the data model: data classes, their fields and how they hold each other', onclick: () => toggleData() }, '▦ Data');
  const ui = shell(root, { extraButtons: [openOther, reload, back, fwd, foldAll, dataButton], onPick: (r) => go(r), onSettings: () => render(true) });
  const vp = new Viewport(ui.vpHost);
  vp.onBackground = () => { st.selected = null; PICK = null; document.querySelectorAll('.node.selected').forEach((n) => n.classList.remove('selected')); panel(); };
  const unfolding = [];
  const keyOf = (owner, n) => `${owner}>${n.target.path}::${n.target.sym}@${n.line || ''}:${n.title}`;
  function go(ref) {
    PICK = null;
    const sym = ref.sym ? lookup(ref) : null;
    if (sym && sym.kind === 'function') { st.stack.push({ view: 'fn', path: ref.path, sym: ref.sym, open: new Set() }); st.fwd = []; st.selected = null; render(false); return; }
    const target = ref.sym ? `cls:${ref.path}:${ref.sym}` : `mod:${ref.path}`;
    const expanded = new Set(lastNet().expanded);
    if (!ref.sym) { expanded.clear(); netDefaultExpanded(ref.path).forEach((x) => expanded.add(x)); }
    else { net().chain(target).slice(1).forEach((x) => expanded.add(x.id)); }
    st.stack.push({ view: 'net', expanded, focus: target, related: focusUnitOf(target), open: new Set() }); st.fwd = []; st.selected = ref.sym ? target : null; render(false);
  }
  function toggleData() {
    const leaving = cur().view === 'data';
    const last = lastNet();
    const from = typeof st.selected === 'string' ? st.selected : last.focus || last.related;
    st.stack.push(leaving ? { ...last, expanded: new Set(last.expanded), open: new Set() } : { view: 'data', scope: dataScopeFor(net(), from), open: new Set() });
    st.fwd = []; st.selected = null; PICK = null;
    render(false);
  }
  function toggleNet(id) {
    const target = net().nodes.get(id);
    if (!target || !target.children.length) { keepInPlace(id, () => render(true)); return; }
    const ex = cur().expanded;
    if (ex.has(id)) ex.delete(id); else ex.add(id);
    keepInPlace(id, () => render(true));
  }
  function keepInPlace(id, change) {
    const before = currentScene && currentScene.netRects && currentScene.netRects.get(id);
    const x0 = before ? vp.x + before.x * vp.s : null, y0 = before ? vp.y + before.y * vp.s : null;
    change();
    const after = currentScene && currentScene.netRects && currentScene.netRects.get(id);
    if (before && after) { vp.x = x0 - after.x * vp.s; vp.y = y0 - after.y * vp.s; vp.apply(); }
  }
  function showEverything() {
    const c = cur();
    const keep = c.related;
    c.related = null;
    keepInPlace(keep, () => render(true));
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
  const netCtx = {
    refresh: () => { if (cur().view !== 'fn') panel(); },
    go: (ref) => go(ref),
    toggle: (id) => toggleNet(id),
    select: (id) => {
      st.selected = id;
      const unit = focusUnitOf(id);
      if (unit && unit !== cur().related) { cur().related = unit; cur().refocused = true; queueMicrotask(() => { if (cur().refocused) keepInPlace(id, () => render(true)); }); }
      panel();
      if (window.innerWidth <= 760) ui.right.hidden = false;
    },
  };
  const dataCtx = {
    ...netCtx,
    toggle: () => {},
    select: (id) => { st.selected = id; panel(); if (window.innerWidth <= 760) ui.right.hidden = false; },
  };
  let currentScene = null;
  function panel() {
    if (cur().view !== 'fn') { netPanel(ui.right, typeof st.selected === 'string' ? st.selected : null, netCtx, currentScene && currentScene.effective); decorate(); return; }
    const ctx = { ...makeCtx('root'), activate: (ref) => go(ref) };
    if (st.selected && st.selected.n) codePanel(ui.right, st.selected.sym, st.selected.n, ctx);
    else codePanel(ui.right, lookup(cur()), null, ctx);
    decorate();
  }
  function chrome() {
    const c = cur();
    if (c.view === 'data') {
      renderSide(ui.left, null, null, go);
      crumbsFor(ui.crumbs, null, null, go, el('span', { class: 'crumb-extra' }, '· data model'));
      return;
    }
    const isNet = c.view === 'net';
    const focusPath = isNet ? (net().nodes.get(c.focus) && net().chain(c.focus).find((n) => n.kind === 'module') || {}).path || null : c.path;
    renderSide(ui.left, focusPath, isNet ? null : c.sym, go);
    const note = isNet ? `· ${c.expanded.size} open` : c.open.size ? `· ${c.open.size} unfolded` : null;
    const units = isNet ? (focusPath ? fileUnits(focusPath) : []) : symbolUnits(c);
    const seen = units.length ? el('label', { class: 'seen-toggle', title: 'Tick once you have reviewed these changes' }, seenBox(units, isNet ? baseName(focusPath) : c.sym), isNet ? 'File seen' : 'Seen') : null;
    crumbsFor(ui.crumbs, focusPath, isNet ? null : c.sym, go, note || seen ? el('span', { class: 'crumb-extra' }, note, seen) : null);
  }
  onSeenChanged = chrome;
  let relayouts = 0;
  function render(keepView) {
    const c = cur();
    const isNet = c.view === 'net';
    back.disabled = st.stack.length < 2; fwd.disabled = !st.fwd.length;
    foldAll.hidden = c.view !== 'fn';
    dataButton.textContent = c.view === 'data' ? '◱ Map' : '▦ Data';
    dataButton.title = c.view === 'data' ? 'Back to the dependency map' : 'Show the data model: data classes, their fields and how they hold each other';
    chrome();
    if (c.view === 'data') {
      const keep = { x: vp.x, y: vp.y, s: vp.s };
      currentScene = buildDataScene(dataCtx, c.scope);
      ui.vpHost.querySelectorAll('.focus-chip, .show-chip').forEach((chip) => chip.remove());
      ui.vpHost.append(dataScopeChip(c.scope, (scope) => { c.scope = scope; st.selected = null; render(false); }));
      vp.setScene(currentScene, keepView ? 'none' : 'fit');
      if (keepView) { Object.assign(vp, keep); vp.apply(); }
      panel();
      return;
    }
    if (!isNet && !FUNCTIONS.has(fnKey(c))) {
      if (!c.error) ensureFunction(c).then(() => { if (cur() === c) render(keepView === 'relayout' ? true : keepView); }, (err) => { c.error = err.message; if (cur() === c) render(keepView); });
      currentScene = messageScene(c.error ? `Could not draw ${c.sym}: ${c.error}` : `Reading ${c.sym}…`);
      vp.setScene(currentScene, 'none'); vp.s = 1; vp.x = 40; vp.y = 40; vp.apply();
      panel();
      return;
    }
    const keep = { x: vp.x, y: vp.y, s: vp.s };
    c.refocused = false;
    const filter = isNet ? relatedTo(c.related) : null;
    currentScene = isNet ? buildNetScene(c.expanded, netCtx, filter) : buildFunctionScene(lookup(c), makeCtx('root'));
    ui.vpHost.querySelectorAll('.focus-chip').forEach((chip) => chip.remove());
    ui.vpHost.querySelectorAll('.show-chip').forEach((chip) => chip.remove());
    const toggles = isNet ? showToggles((key, on) => { settings[key] = on; saveSettings(); resetNet(); render(true); }) : null;
    if (toggles) ui.vpHost.append(toggles);
    if (filter) ui.vpHost.append(el('div', { class: 'focus-chip' }, el('span', {}, 'Showing what ', el('strong', {}, netLabel(filter.unit)), ` depends on or is used by · ${plural(filter.related.size, 'related module')}`), el('button', { class: 'btn small', title: 'Show every module again', onclick: () => showEverything() }, '✕ Show all')));
    vp.setScene(currentScene, keepView ? 'none' : 'start');
    if (keepView) { Object.assign(vp, keep); vp.apply(); }
    else if (isNet && c.focus) { const f = currentScene.el.querySelector(`.nb[data-id="${CSS.escape(c.focus)}"]`); const r = currentScene.netRects && currentScene.netRects.get(c.focus); vp.fit(); if (r && vp.s < 0.6) { vp.s = 0.85; vp.x = 40 - r.x * vp.s; vp.y = 60 - r.y * vp.s; vp.apply(); } if (f) f.classList.add('flash'); }
    panel();
    relayouts = keepView === 'relayout' ? relayouts + 1 : 0;
    const sizes = currentScene.sizes || currentScene.nodes.map((n) => ({ el: n.el, w: n.w, h: n.h }));
    if (relayouts < 3) watchSizes(sizes, () => { if (cur() === c) render('relayout'); });
  }
  const chip = el('span', { id: 'agent-chip', class: 'agent-chip', hidden: true });
  ui.crumbs.after(chip);
  let reveal = null;
  const fail = (what) => (err) => toast(`${what}: ${err.message}`, () => {});
  const commentActions = {
    open: (id) => showThread(id),
    compose: () => compose(),
    clearPick: () => { PICK = null; decorate(); },
    close: () => { CARD = null; decorate(); chrome(); },
    create: (anchor, body) => apiPost('/api/comments', { anchor, body }).then((thread) => { mergeThreads([thread]); PICK = null; CARD = { mode: 'thread', id: thread.id }; onCommentsChanged(); }, fail('Could not save the comment')),
    reply: (id, body) => apiPost('/api/comments/reply', { id, body }).then((thread) => { mergeThreads([thread]); onCommentsChanged(); }, (err) => { REPLY_DRAFTS.set(id, body); fail('Could not send the reply')(err); }),
    resolve: (id, resolved) => apiPost('/api/comments/resolve', { id, resolved }).then((thread) => { mergeThreads([thread]); onCommentsChanged(); }, fail('Could not change the comment')),
    step: (d) => {
      const open = openThreads();
      if (!open.length) return;
      const at = open.findIndex((t) => CARD && t.id === CARD.id);
      showThread(open[at < 0 ? (d > 0 ? 0 : open.length - 1) : (at + d + open.length) % open.length].id);
    },
  };
  COMMENT_ACTIONS = commentActions;
  onCommentsChanged = () => { chrome(); decorate(); };
  function currentPick() {
    if (PICK) return PICK;
    const c = cur();
    if (c.view === 'net' && typeof st.selected === 'string') return { kind: 'map', ids: new Set([st.selected]), implicit: true };
    if (c.view === 'fn' && st.selected && st.selected.n && st.selected.sym) return { kind: 'blueprint', ids: new Set([st.selected.n.id]), fn: refOf(st.selected.sym), implicit: true };
    return null;
  }
  function setPick(kind, ids, additive) {
    const c = cur();
    const fn = kind === 'blueprint' ? { path: c.path, sym: c.sym } : undefined;
    const before = additive ? currentPick() : null;
    const same = before && before.kind === kind && (kind !== 'blueprint' || (before.fn.path === fn.path && before.fn.sym === fn.sym));
    const chosen = same ? new Set(before.ids) : new Set();
    for (const id of ids) { if (additive && ids.length === 1 && chosen.has(id)) chosen.delete(id); else chosen.add(id); }
    PICK = chosen.size ? { kind, ids: chosen, fn } : null;
    decorate();
  }
  function compose() {
    const c = cur();
    let pick = currentPick();
    if (!pick && c.view === 'fn') {
      const data = FUNCTIONS.get(fnKey(c));
      const entry = data && data.graph.nodes.find((n) => n.kind === 'entry');
      if (entry) pick = { kind: 'blueprint', ids: new Set([entry.id]), fn: { path: c.path, sym: c.sym } };
    }
    if (!pick && c.view === 'net' && c.focus) pick = { kind: 'map', ids: new Set([c.focus]) };
    if (!pick) { toast('Select something to comment on first: click a box or node, Shift-drag around several, or drag down the line numbers.', () => {}); return; }
    CARD = { mode: 'new', anchor: anchorFor(pick), draft: '', focus: true };
    decorate();
  }
  function showThread(id) {
    const thread = threadById(id);
    if (!thread) return;
    CARD = { mode: 'thread', id };
    reveal = id;
    PICK = null;
    const a = thread.anchor;
    const c = cur();
    const fnSym = a.qual ? lookup({ path: a.path, sym: a.qual }) : null;
    if (a.view === 'map') {
      revealHidden(a.ids || []);
      const ids = (a.ids || []).filter((i) => net().nodes.has(i));
      if (c.view === 'net' && ids.length && ids.every((i) => currentScene.netRects && currentScene.netRects.has(i))) { chrome(); decorate(); return; }
      if (!ids.length) { chrome(); decorate(); return; }
      const expanded = new Set(lastNet().expanded);
      for (const i of ids) net().chain(i).slice(1, -1).forEach((x) => expanded.add(x.id));
      st.stack.push({ view: 'net', expanded, focus: ids[0], related: null, open: new Set() });
    } else if (fnSym && fnSym.kind === 'function') {
      if (c.view === 'fn' && c.path === a.path && c.sym === a.qual) { st.selected = null; render(true); return; }
      st.stack.push({ view: 'fn', path: a.path, sym: a.qual, open: new Set() });
    } else if (FILES[a.path]) {
      revealHidden([`mod:${a.path}`]);
      const expanded = new Set(lastNet().expanded);
      net().chain(`mod:${a.path}`).slice(1).forEach((x) => expanded.add(x.id));
      st.stack.push({ view: 'net', expanded, focus: `mod:${a.path}`, related: null, open: new Set() });
    } else { chrome(); decorate(); return; }
    st.fwd = []; st.selected = null;
    render(false);
  }
  function decorate() {
    const c = cur();
    if (currentScene) {
      clearDecorations(currentScene.el);
      if (c.view === 'net' && currentScene.netRects) decorateMap(currentScene.el, showThread);
      else if (c.view === 'fn' && currentScene.layer && FUNCTIONS.has(fnKey(c))) decorateBlueprint(currentScene.layer, { path: c.path, sym: c.sym }, showThread);
    }
    paintCodeViews(ui.right, showThread, () => decorate());
    renderPickBar(ui.vpHost, currentPick(), commentActions);
    renderCommentCard(ui.vpHost, commentActions);
    paintAgentChip();
    if (reveal) revealThread();
  }
  function revealThread() {
    const id = reveal;
    const pin = ui.vpHost.querySelector(`.comment-pin[data-threads~="${CSS.escape(id)}"]`);
    const mark = ui.right.querySelector(`.cmark[data-threads~="${CSS.escape(id)}"]`);
    if (mark) mark.closest('.ln').scrollIntoView({ block: 'center' });
    if (!pin) return;
    reveal = null;
    const target = pin.closest('.nb, .node') || pin;
    const host = ui.vpHost.getBoundingClientRect();
    let r = target.getBoundingClientRect();
    if (vp.s < 0.6) { vp.zoomAt(r.left + r.width / 2 - host.left, r.top + r.height / 2 - host.top, 0.85 / vp.s); r = target.getBoundingClientRect(); }
    const room = host.width - (ui.vpHost.querySelector('.comment-card') ? 380 : 0);
    vp.panBy(room / 2 - (r.left - host.left + Math.min(r.width, room - 40) / 2), host.height / 2 - (r.top - host.top + Math.min(r.height, host.height - 80) / 2));
    target.classList.remove('flash'); void target.offsetWidth; target.classList.add('flash');
  }
  ui.vpHost.addEventListener('click', (e) => {
    if (!(e.metaKey || e.ctrlKey) || e.target.closest('.comment-card, .pick-bar, .zoom-ctl, .show-chip, .edge-pointer, .comment-pin')) return;
    const c = cur();
    let id = null;
    if (c.view === 'net') { const box = e.target.closest('.nb[data-id]'); if (box) id = box.dataset.id; }
    else { const node = e.target.closest('.node[data-node]'); if (node && currentScene && node.parentElement === currentScene.layer) id = node.dataset.node; }
    if (!id) return;
    e.stopPropagation(); e.preventDefault();
    setPick(c.view === 'net' ? 'map' : 'blueprint', [id], true);
  }, true);
  vp.onMarquee = (rect, additive) => {
    const inside = (r) => r.x >= rect.x && r.y >= rect.y && r.x + r.w <= rect.x + rect.w && r.y + r.h <= rect.y + rect.h;
    const c = cur();
    if (!currentScene) return;
    if (c.view === 'net' && currentScene.netRects) {
      const hits = [...currentScene.netRects].filter(([, r]) => inside(r)).map(([id]) => id);
      const inPick = new Set(hits);
      const outer = hits.filter((id) => !net().chain(id).slice(0, -1).some((n) => inPick.has(n.id)));
      if (outer.length || !additive) setPick('map', outer, additive);
    } else if (c.view === 'fn') {
      const hits = currentScene.nodes.filter((v) => v.data && v.data.id != null && inside(v)).map((v) => v.data.id);
      if (hits.length || !additive) setPick('blueprint', hits, additive);
    }
  };
  render(false);
  const keys = (e) => {
    if (e.altKey && e.key === 'ArrowLeft') back.click();
    if (e.altKey && e.key === 'ArrowRight') fwd.click();
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === 'c' || e.key === 'C') { e.preventDefault(); compose(); }
    if (e.key === ']') commentActions.step(1);
    if (e.key === '[') commentActions.step(-1);
    if (e.key === 'Escape') { if (CARD) commentActions.close(); else if (PICK) commentActions.clearPick(); }
  };
  return { keys };
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
    if (status.error) {
      const stop = status.diff ? el('button', { class: 'btn', onclick: () => api('/api/diff?spec=').then(() => waitForProject(), (err) => showWelcome(err.message)) }, 'Stop comparing') : null;
      screen(el('p', { class: 'error-text' }, status.diff ? `Comparing ${status.diff.spec} failed.` : 'Reading the project failed.'), el('pre', { class: 'error-detail' }, status.error), stop, el('button', { class: 'btn', onclick: () => showWelcome() }, 'Open another folder'));
      return;
    }
    if (!status.ready) {
      const seconds = Math.round((Date.now() - started) / 1000);
      const text = status.diff && status.files && !status.loading ? `Comparing ${status.diff.spec}…` : status.diff ? `Reading ${status.diff.spec}: ${status.files.toLocaleString()} Python files…` : `Reading ${status.files.toLocaleString()} Python files in ${status.name}…`;
      const hint = seconds > 2 ? `${seconds}s — large projects take a little while the first time; after that they open from a cache.` : ' ';
      const shown = document.getElementById('load-text');
      if (shown) { shown.textContent = text; document.getElementById('load-hint').textContent = hint; }
      else screen(el('div', { class: 'spinner' }), el('p', { class: 'lede', id: 'load-text' }, text), el('p', { class: 'muted', id: 'load-hint' }, hint));
      setTimeout(tick, 400);
      return;
    }
    try {
      DIFF = status.diff ? await api('/api/diff/data') : null;
      SEEN = new Set(DIFF ? (await api('/api/seen')).seen : []);
      loadOverview(await api('/api/project'));
      await loadComments();
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
  startCommentWatch();
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
