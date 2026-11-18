import { LOOP_TURN, plain } from '../canvas/scene.js';
import { net } from '../core/data.js';
import { el } from '../core/dom.js';
import { rankColumns } from '../core/columns.js';
import { ARRANGED_LAYOUTS, arrangeLayers } from '../core/layout.js';
import { settings } from '../core/settings.js';
export const DIFF_SIGN = { added: '+', removed: '−', modified: '~' };
export const DIFF_WORD = { added: 'added', removed: 'removed', modified: 'changed' };
export function diffBadge(state) { return state ? el('span', { class: `diff-badge diff-${state}`, title: DIFF_WORD[state] }, DIFF_SIGN[state]) : null; }
export const refOf = (sym) => ({ path: sym.file, sym: sym.qual });
function stereotypeOf(sym) {
  if (sym.stereo) return sym.stereo;
  if (sym.kind === 'enum') return 'enum';
  if (sym.cat === 'iface') return 'protocol';
  if (sym.cat === 'struct') return 'dataclass';
  return null;
}
const visibility = (name) => (/^_[^_]/.test(name) ? '−' : '+');
const typeText = (t) => el('span', { class: 'utype', style: `color:var(--t-${t.cat})`, title: t.label }, shortType(t.label));
export const shortType = (label) => (label.length > 60 ? `${label.slice(0, 59)}…` : label);
export const plural = (n, word) => `${n} ${word}${n === 1 ? '' : (word.endsWith('s') ? 'es' : 's')}`;
export function netLabel(id) {
  const n = net().nodes.get(id);
  if (!n) return id;
  if (n.kind === 'method') return `${n.parent.name}.${n.name}()`;
  if (n.kind === 'function') return `${n.name}()`;
  if (n.kind === 'field' || n.kind === 'member') return `${n.parent.name}.${n.name}`;
  if (n.kind === 'name') return `${n.name} (${n.parent.kind === 'libmodule' ? n.parent.name : n.parent.name})`;
  if (n.kind === 'package') return `${n.name}/`;
  return n.name;
}
function opBlock(fnSym) {
  const params = fnSym.params.filter((p) => p[0] !== 'self');
  const hasReturn = fnSym.returns && fnSym.returns.cat !== 'none';
  return [
    el('div', { class: 'sig-head' }, el('span', { class: 'uvis' }, visibility(fnSym.name)), el('span', { class: 'uop' }, plain(fnSym.name)), el('span', { class: 'go' }, '▸')),
    params.length ? el('div', { class: 'sig-params' }, params.map((p, i) => el('span', { class: 'sig-param', title: `${p[0]}: ${p[1].label}` }, el('span', { class: 'pdot', style: `background:var(--t-${p[1].cat})` }), plain(p[0]), i < params.length - 1 ? ',' : ''))) : null,
    hasReturn ? el('div', { class: 'sig-ret' }, el('span', { class: 'udim' }, '→ '), typeText(fnSym.returns)) : null,
  ];
}
export function summaryOf(n) {
  const counts = new Map();
  const word = { package: 'package', module: 'module', class: 'class', function: 'function', method: 'method', field: 'field', member: 'choice', constant: 'constant', name: 'name', libmodule: 'module' };
  for (const k of n.children) counts.set(word[k.kind], (counts.get(word[k.kind]) || 0) + 1);
  return [...counts].map(([w, c]) => plural(c, w)).join(' · ');
}
export function netBoxEl(n, expanded, ctx, filter = null) {
  if (!n.children.length) return leafBoxEl(n, ctx);
  const isOpen = expanded.has(n.id);
  const stereo = boxStereotype(n);
  const title = n.kind === 'package' ? `${n.name}/` : n.name;
  const shownKids = filter ? n.children.filter((k) => filter.visible(k)) : n.children;
  const hiddenKids = n.children.length - shownKids.length;
  const box = el('div', { class: `nb k-${n.kind} ${isOpen ? 'open' : ''} ${n.diff ? `diff-${n.diff}` : ''} ${filter && filter.unit === n.id ? 'focused' : ''}`, 'data-id': n.id, style: `--hc: var(${boxHeadColour(n)})` });
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
function leafBoxEl(n, ctx) {
  const stripe = { method: '--h-method', function: '--h-call', field: '--h-break', member: '--h-enum', constant: '--h-var', name: '--h-lit' }[n.kind] || '--h-lit';
  const isFn = n.kind === 'method' || n.kind === 'function';
  const leaf = el('div', { class: `nb leaf k-${n.kind}${isFn ? ' fnleaf' : ''}${n.diff ? ` diff-${n.diff}` : ''}`, 'data-id': n.id, style: `--stripe: var(${stripe})`, title: n.sym ? 'Open its dataflow view' : netLabel(n.id) }, diffBadge(n.diff), leafParts(n, isFn));
  leaf.addEventListener('click', (e) => { e.stopPropagation(); if (n.sym) ctx.go(refOf(n.sym)); else ctx.select(n.id); });
  return leaf;
}
function leafParts(n, isFn) {
  if (isFn) return opBlock(n.sym);
  if (n.kind === 'field') return [el('span', { class: 'uvis' }, visibility(n.name)), el('span', {}, plain(n.name)), el('span', { class: 'udim' }, ':'), typeText(n.type)];
  if (n.kind === 'member') return [el('span', {}, n.name), el('span', { class: 'udim' }, ` = ${n.value}`)];
  if (n.kind === 'constant') return [el('span', {}, plain(n.name)), el('span', { class: 'udim' }, ':'), typeText(n.type), el('span', { class: 'udim' }, ` = ${n.value}`)];
  return [el('span', { class: 'uicon' }, /^[a-z_]/.test(n.name) ? 'ƒ' : 'C'), el('span', {}, n.name)];
}
function boxHeadColour(n) {
  if (n.kind === 'package') return '--h-pkg';
  if (n.kind === 'module') return '--h-mod';
  if (n.kind === 'library' || n.kind === 'libmodule') return '--h-lib';
  const sym = n.sym;
  return sym.kind === 'enum' ? '--h-enum' : sym.cat === 'iface' ? '--h-iface' : sym.cat === 'struct' ? '--h-struct' : '--h-break';
}
function boxStereotype(n) {
  if (n.kind === 'class') return stereotypeOf(n.sym);
  return n.kind === 'module' ? 'module' : n.kind === 'library' ? 'library' : null;
}
export const NET_ROUTES = new Map();
export const NET_SLACK = new Map();
export const NET_COLUMNS = new Map();
const MAP_PAD = 14;
const MAP_TOP = 10;
export function layoutNet(n, boxEl, edges, N = net()) {
  const inner = boxEl.querySelector(':scope > .ninner');
  if (!inner) return;
  const box = new MapBoxLayout(n, inner, N);
  box.layoutChildren(edges);
  const { pairs, skips, weights } = box.linkKids(edges);
  box.rank = rankColumns(box.kids, weights, (k) => ['field', 'member', 'constant'].includes(k.node.kind));
  box.addRoutes(pairs);
  box.stackColumns(skips);
  box.relax();
  box.tighten();
  if (ARRANGED_LAYOUTS.has(settings.layout)) arrangeMapColumns(settings.layout, Array.from(box.cols, (col) => col || []), box.nbrs, { anchor: mapAnchor, gapY: box.gapY, top: MAP_TOP });
  box.apply();
  box.record(skips);
}
class MapBoxLayout {
  constructor(n, inner, N) {
    Object.assign(this, { n, inner, N });
    this.kids = [...inner.children].map((elx) => ({ node: N.nodes.get(elx.dataset.id), el: elx, x: 0, y: 0 }));
    this.byId = new Map(this.kids.map((k) => [k.node.id, k]));
    this.items = [...this.kids];
    this.nbrs = new Map();
    this.routes = [];
  }
  under(id) {
    const c = this.N.chain(id), depth = this.n.depth;
    return c[depth] === this.n && c[depth + 1] ? this.byId.get(c[depth + 1].id) : null;
  }
  rk(it) { return it.dummy ? it.rank : this.rank.get(it); }
  layoutChildren(edges) {
    const touching = new Map(this.kids.map((k) => [k, []]));
    for (const e of edges) {
      const a = this.under(e.from), b = this.under(e.to);
      if (a) touching.get(a).push(e);
      if (b && b !== a) touching.get(b).push(e);
    }
    for (const k of this.kids) layoutNet(k.node, k.el, touching.get(k), this.N);
    for (const k of this.kids) { k.w = k.el.offsetWidth; k.h = k.el.offsetHeight; }
  }
  linkKids(edges) {
    const pairs = new Map(), skips = [], weights = new Map();
    for (const e of edges) {
      const a = this.under(e.from), b = this.under(e.to);
      if (!a || !b || a === b) continue;
      if (!weights.has(a)) weights.set(a, new Map());
      weights.get(a).set(b, (weights.get(a).get(b) || 0) + (e.atoms ? e.atoms.length : 1));
      if (e.shortcut) { skips.push({ a, b }); continue; }
      if (!pairs.has(a)) pairs.set(a, new Set()); pairs.get(a).add(b);
    }
    return { pairs, skips, weights };
  }
  near(a, b) {
    if (!this.nbrs.has(a)) this.nbrs.set(a, new Set()); this.nbrs.get(a).add(b);
    if (!this.nbrs.has(b)) this.nbrs.set(b, new Set()); this.nbrs.get(b).add(a);
  }
  lane(from, ranks) {
    const chain = [];
    for (const r of ranks) { const d = { dummy: true, rank: r, w: 0, h: 6, x: 0, y: 0, origin: from }; this.near(chain.length ? chain[chain.length - 1] : from, d); chain.push(d); this.items.push(d); }
    return chain;
  }
  addRoutes(pairs) {
    const rank = this.rank;
    for (const [a, bs] of pairs) {
      const r0 = rank.get(a);
      const ts = [...bs].map((b) => rank.get(b));
      const ahead = this.lane(a, rankSpan(r0 + 1, Math.max(r0, ...ts)));
      const behind = this.lane(a, rankSpan(Math.min(r0 + 1, ...ts), r0 + 1).reverse());
      for (const b of bs) {
        const t = rank.get(b);
        const via = t > r0 ? ahead.slice(0, t - r0 - 1) : behind.slice(0, r0 - t + 1);
        this.near(via.length ? via[via.length - 1] : a, b);
        this.routes.push({ a, b, via });
      }
    }
  }
  stackColumns(skips) {
    const { kids, rank } = this;
    this.lastRank = Math.max(0, ...kids.map((k) => rank.get(k)));
    this.cols = [];
    for (const it of this.items) { const r = this.rk(it); if (!this.cols[r]) this.cols[r] = []; this.cols[r].push(it); }
    const leafy = kids.every((k) => !k.node.children.length);
    const gapX = leafy ? 70 : 110;
    this.gapY = leafy ? 12 : 22;
    const loops = [...this.routes, ...skips].filter((r) => rank.get(r.b) <= rank.get(r.a));
    const padLeft = loops.some((r) => rank.get(r.b) === 0) ? MAP_PAD + LOOP_TURN : MAP_PAD;
    this.padRight = loops.some((r) => rank.get(r.a) === this.lastRank) ? MAP_PAD + LOOP_TURN : MAP_PAD;
    this.colX = []; this.colW = [];
    let x = padLeft;
    this.cols.forEach((col, r) => {
      if (!col) return;
      const real = col.filter((it) => !it.dummy);
      const w = real.length ? Math.max(...real.map((k) => k.w)) : 30;
      this.colX[r] = x; this.colW[r] = w;
      let y = MAP_TOP;
      for (const it of col) { it.x = x; it.y = y; y += it.h + this.gapY; }
      x += w + gapX;
    });
    for (const it of this.items) if (it.dummy) it.y = mapMid(it.origin) - 3;
    for (const col of this.cols) if (col) col.sort((a, b) => a.y - b.y);
  }
  relax() {
    for (let pass = 0; pass < 8; pass++) for (const col of pass % 2 ? [...this.cols].reverse() : this.cols) {
      if (!col) continue;
      const want = new Map(col.map((it) => [it, this.wantedY(it)]));
      col.sort((a, b) => want.get(a) + a.h / 2 - want.get(b) - b.h / 2);
      let prev = MAP_TOP; for (const it of col) { it.y = Math.max(want.get(it), prev); prev = it.y + it.h + (it.dummy ? 8 : this.gapY); }
    }
  }
  wantedY(it) {
    const nb = [...(this.nbrs.get(it) || [])].filter((o) => this.rk(o) !== this.rk(it) || it.dummy);
    return nb.length ? nb.reduce((acc, o) => acc + mapMid(o), 0) / nb.length - mapAnchor(it) : it.y;
  }
  tighten() {
    const connected = (it) => (this.nbrs.get(it) || new Set()).size > 0;
    for (const col of this.cols) {
      if (!col) continue;
      col.sort((a, b) => (connected(b) - connected(a)) || a.y - b.y);
      let prev = null;
      for (const it of col) {
        const lo = prev === null ? MAP_TOP : prev + (it.dummy ? 8 : this.gapY);
        it.y = Math.min(Math.max(it.y, lo), lo + 36);
        prev = it.y + it.h;
      }
    }
  }
  apply() {
    const { items, kids, inner } = this;
    const minY = Math.min(...items.map((it) => it.y));
    for (const it of items) it.y += MAP_TOP - minY;
    for (const k of kids) { k.el.style.left = `${k.x}px`; k.el.style.top = `${k.y}px`; NET_SLACK.set(k.node.id, this.colW[this.rank.get(k)] - k.w); }
    for (const it of items) if (it.dummy) { it.x = this.colX[it.rank]; it.w = this.colW[it.rank]; }
    inner.style.width = `${Math.max(...kids.map((k) => k.x + k.w), 100) + this.padRight}px`;
    inner.style.height = `${Math.max(...items.map((it) => it.y + it.h), 30) + MAP_PAD}px`;
  }
  record(skips) {
    const { inner, colX, colW, rank } = this;
    for (const r of this.routes) NET_ROUTES.set(`${r.a.node.id}|${r.b.node.id}`, { inner, via: r.via });
    const gapNear = columnGaps(this.cols);
    NET_COLUMNS.set(this.n.id, { inner, colX, colW, gapNear, last: this.lastRank, rank: new Map(this.kids.map((k) => [k.node.id, rank.get(k)])) });
    for (const { a, b } of skips) {
      const r0 = rank.get(a), t = rank.get(b), ya = mapMid(a), yb = mapMid(b);
      const ranks = t > r0 ? rankSpan(r0 + 1, t) : rankSpan(t, r0 + 1).reverse();
      const reach = Math.max(1, Math.abs(t - r0));
      const via = ranks.map((r) => ({ x: colX[r], w: colW[r], y: gapNear(r, ya + ((yb - ya) * Math.abs(r - r0)) / reach) - 3 }));
      NET_ROUTES.set(`${a.node.id}|${b.node.id}`, { inner, via });
    }
  }
}
function mapAnchor(it) { return it.dummy ? 3 : Math.min(it.h, 40) / 2; }
function mapMid(o) { return o.y + mapAnchor(o); }
function rankSpan(lo, hi) { return Array.from({ length: Math.max(0, hi - lo) }, (_, i) => lo + i); }
function columnGaps(cols) {
  const gaps = Array.from(cols, (col) => {
    const real = (col || []).filter((it) => !it.dummy).sort((p, q) => p.y - q.y);
    const out = [];
    let top = 0;
    for (const k of real) { out.push([top, k.y]); top = k.y + k.h; }
    out.push([top, Infinity]);
    return out;
  });
  return (r, want) => gaps[r].map(([lo, hi]) => (hi - lo < 8 ? (lo + hi) / 2 : Math.min(Math.max(want, lo + 4), hi - 4))).reduce((best, y) => (Math.abs(y - want) < Math.abs(best - want) ? y : best), Infinity);
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
export function moduleNodeOf(id) { return net().chain(id).find((n) => n.kind === 'module') || null; }
export function moduleFileName(module) { return module.name === '__init__.py' && module.parent.kind === 'package' ? `${module.parent.name}/__init__.py` : module.name; }
