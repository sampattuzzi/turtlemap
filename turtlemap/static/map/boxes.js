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
  if (n.kind === 'typevar') return `${n.name} (type parameter)`;
  return n.name;
}
function opBlock(fnSym) {
  const params = fnSym.params.filter((p) => p[0] !== 'self');
  const hasReturn = fnSym.returns && fnSym.returns.cat !== 'none';
  return [
    el('div', { class: 'sig-head' }, el('span', { class: 'uvis' }, visibility(fnSym.name)), el('span', { class: 'uop' }, plain(fnSym.name)), fnSym.typeParams ? el('span', { class: 'ttag', title: 'Generic over these type parameters' }, `[${fnSym.typeParams.join(', ')}]`) : null, el('span', { class: 'go' }, '▸')),
    params.length ? el('div', { class: 'sig-params' }, params.map((p, i) => el('span', { class: 'sig-param', title: `${p[0]}: ${p[1].label}` }, el('span', { class: 'pdot', style: `background:var(--t-${p[1].cat})` }), plain(p[0]), i < params.length - 1 ? ',' : ''))) : null,
    hasReturn ? el('div', { class: 'sig-ret' }, el('span', { class: 'udim' }, '→ '), typeText(fnSym.returns)) : null,
  ];
}
export function summaryOf(n) {
  const counts = new Map();
  const word = { package: 'package', module: 'module', class: 'class', function: 'function', method: 'method', field: 'field', member: 'choice', constant: 'constant', typevar: 'type parameter', name: 'name', libmodule: 'module' };
  for (const k of n.children) counts.set(word[k.kind], (counts.get(word[k.kind]) || 0) + 1);
  return [...counts].map(([w, c]) => plural(c, w)).join(' · ');
}
export function netBoxEl(n, expanded, ctx, filter = null) {
  if (!n.children.length && !n.pruned) return leafBoxEl(n, ctx);
  const bare = !n.children.length;
  const isOpen = expanded.has(n.id);
  const stereo = boxStereotype(n);
  const title = n.kind === 'package' ? `${n.name}/` : n.name;
  const shownKids = filter ? n.children.filter((k) => filter.visible(k)) : n.children;
  const hiddenKids = n.children.length - shownKids.length;
  const box = el('div', { class: `nb k-${n.kind} ${isOpen ? 'open' : ''}${bare ? ' bare' : ''}${n.faded ? ' faded' : ''} ${n.diff ? `diff-${n.diff}` : ''} ${filter && filter.unit === n.id ? 'focused' : ''}`, 'data-id': n.id, style: `--hc: var(${boxHeadColour(n)})` });
  const head = el('div', { class: 'nhead', title: bare ? null : isOpen ? 'Collapse' : 'Expand' }, bare ? null : el('span', { class: 'chev' }, isOpen ? '▾' : '▸'), diffBadge(n.diff),
    stereo ? el('span', { class: 'stereo' }, `«${stereo}»`) : null, el('span', { class: 'ntitle' }, title),
    isOpen && hiddenKids ? el('span', { class: 'nhidden', title: 'Hidden because they have no dependency on the selected module' }, `${hiddenKids} unrelated hidden`) : null);
  head.addEventListener('click', (e) => { e.stopPropagation(); ctx.select(n.id); ctx.toggle(n.id); });
  box.append(head);
  const corner = templateCorner(n);
  if (corner) box.append(corner);
  if (!isOpen) { if (!bare) box.append(el('div', { class: 'nsum' }, summaryOf(n))); return box; }
  const inner = el('div', { class: 'ninner' });
  for (const k of shownKids) inner.append(netBoxEl(k, expanded, ctx, filter));
  box.append(inner);
  return box;
}
function leafBoxEl(n, ctx) {
  const stripe = { method: '--h-method', function: '--h-call', field: '--h-break', member: '--h-enum', constant: '--h-var', typevar: '--rel-bound', name: '--h-lit' }[n.kind] || '--h-lit';
  const isFn = n.kind === 'method' || n.kind === 'function';
  const leaf = el('div', { class: `nb leaf k-${n.kind}${isFn ? ' fnleaf' : ''}${n.faded ? ' faded' : ''}${n.diff ? ` diff-${n.diff}` : ''}`, 'data-id': n.id, style: `--stripe: var(${stripe})`, title: n.sym ? 'Open its dataflow view' : netLabel(n.id) }, diffBadge(n.diff), leafParts(n, isFn));
  leaf.addEventListener('click', (e) => { e.stopPropagation(); if (n.sym) ctx.go(refOf(n.sym)); else ctx.select(n.id); });
  return leaf;
}
function leafParts(n, isFn) {
  if (isFn) return opBlock(n.sym);
  if (n.kind === 'field') return [el('span', { class: 'uvis' }, visibility(n.name)), el('span', {}, plain(n.name)), el('span', { class: 'udim' }, ':'), typeText(n.type)];
  if (n.kind === 'member') return [el('span', {}, n.name), el('span', { class: 'udim' }, ` = ${n.value}`)];
  if (n.kind === 'constant') return [el('span', {}, plain(n.name)), el('span', { class: 'udim' }, ':'), typeText(n.type), el('span', { class: 'udim' }, ` = ${n.value}`)];
  if (n.kind === 'typevar') return [el('span', { class: 'tbadge', title: 'Type parameter: stands for one type, the same wherever it appears' }, 'T'), el('span', {}, n.name), n.bound ? el('span', { class: 'udim' }, ':') : null, n.bound ? typeText(n.bound) : el('span', { class: 'udim' }, 'any type')];
  return [el('span', { class: 'uicon' }, /^[a-z_]/.test(n.name) ? 'ƒ' : 'C'), el('span', {}, n.name)];
}
function templateCorner(n) {
  const params = n.kind === 'class' && n.sym && n.sym.typeParams;
  if (!params || !params.length) return null;
  return el('div', { class: 'tparams', title: 'Type parameters this class is generic over' }, params.map(([name, bound]) => el('div', {}, el('span', {}, name), bound ? el('span', { class: 'udim' }, ' : ') : null, bound ? typeText(bound) : null)));
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
export function layoutNet(n, boxEl, edges, N = net(), outside = null) {
  const inner = boxEl.querySelector(':scope > .ninner');
  if (!inner) return;
  const box = new MapBoxLayout(n, inner, N, outside);
  box.layoutChildren(edges);
  const { pairs, skips, weights } = box.linkKids(edges);
  box.rank = rankColumns(box.kids, weights, (k) => ['field', 'member', 'constant', 'typevar'].includes(k.node.kind));
  box.addRoutes(pairs);
  box.stackColumns(skips);
  box.relax();
  box.tighten();
  if (ARRANGED_LAYOUTS.has(settings.layout)) arrangeMapColumns(settings.layout, Array.from(box.cols, (col) => col || []), box, { gapY: box.gapY, top: MAP_TOP });
  box.apply();
  box.record(skips);
}
export function outsideOf(rootEl) {
  const anchors = new Map();
  rootEl.querySelectorAll('.nb').forEach((b) => anchors.set(b.dataset.id, offsetWithin(b, rootEl).y + boxAnchor(b)));
  return { anchors, top: (inner) => offsetWithin(inner, rootEl).y };
}
export function offsetWithin(node, root) {
  let x = 0, y = 0, cur = node;
  while (cur && cur !== root) { x += cur.offsetLeft; y += cur.offsetTop; cur = cur.offsetParent; }
  return { x, y };
}
export function boxAnchor(box) {
  const head = box.querySelector(':scope > .nhead');
  return head ? head.offsetHeight / 2 : box.offsetHeight / 2;
}
class MapBoxLayout {
  constructor(n, inner, N, outside) {
    Object.assign(this, { n, inner, N, outside });
    this.kids = [...inner.children].map((elx) => ({ node: N.nodes.get(elx.dataset.id), el: elx, x: 0, y: 0 }));
    this.byId = new Map(this.kids.map((k) => [k.node.id, k]));
    this.items = [...this.kids];
    this.nbrs = new Map();
    this.ports = new Map();
    this.pulls = new Map();
    this.ends = new Map();
    this.inside = new Map();
    this.extent = outside ? inner.offsetHeight : 0;
    this.routes = [];
  }
  port(it, other) {
    const ports = this.ports.get(it);
    return ports && ports.has(other) ? ports.get(other) : mapAnchor(it);
  }
  portIn(k, id) {
    if (id === k.node.id) return mapAnchor(k);
    if (!this.inside.has(k)) this.inside.set(k, new Map([...k.el.querySelectorAll('.nb')].map((box) => [box.dataset.id, offsetWithin(box, k.el).y + boxAnchor(box)])));
    return this.inside.get(k).get(id) ?? mapAnchor(k);
  }
  isOutside(id) { return !this.N.chain(id).includes(this.n); }
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
    for (const k of this.kids) layoutNet(k.node, k.el, touching.get(k), this.N, this.outside);
    for (const k of this.kids) { k.w = k.el.offsetWidth; k.h = k.el.offsetHeight; }
  }
  linkKids(edges) {
    const pairs = new Map(), skips = [], weights = new Map();
    for (const e of edges) {
      const a = this.under(e.from), b = this.under(e.to);
      const count = e.atoms ? e.atoms.length : 1;
      if (a && !b && this.isOutside(e.to)) this.pull(a, e.from, e.to);
      if (b && !a && this.isOutside(e.from)) this.pull(b, e.to, e.from);
      if (!a || !b || a === b) continue;
      if (!weights.has(a)) weights.set(a, new Map());
      weights.get(a).set(b, (weights.get(a).get(b) || 0) + count);
      this.endsOf(a, b).push({ pa: this.portIn(a, e.from), pb: this.portIn(b, e.to), count });
      if (e.shortcut) { skips.push({ a, b }); continue; }
      if (!pairs.has(a)) pairs.set(a, new Set()); pairs.get(a).add(b);
    }
    return { pairs, skips, weights };
  }
  endsOf(a, b) {
    if (!this.ends.has(a)) this.ends.set(a, new Map());
    const from = this.ends.get(a);
    if (!from.has(b)) from.set(b, []);
    return from.get(b);
  }
  pull(k, end, far) {
    if (!this.outside || !this.outside.anchors.has(far)) return;
    const y = this.outside.anchors.get(far) - this.outside.top(this.inner) - this.portIn(k, end);
    if (!this.pulls.has(k)) this.pulls.set(k, []);
    this.pulls.get(k).push({ y: Math.min(Math.max(y, MAP_TOP), Math.max(MAP_TOP, this.extent - MAP_PAD - k.h)) });
  }
  portsBetween(a, b) {
    const ends = this.endsOf(a, b), total = ends.reduce((sum, e) => sum + e.count, 0);
    const mean = (key) => ends.reduce((sum, e) => sum + e[key] * e.count, 0) / total;
    return { pa: mean('pa'), pb: mean('pb') };
  }
  near(a, b, pa = mapAnchor(a), pb = mapAnchor(b)) {
    if (!this.nbrs.has(a)) this.nbrs.set(a, new Set()); this.nbrs.get(a).add(b);
    if (!this.nbrs.has(b)) this.nbrs.set(b, new Set()); this.nbrs.get(b).add(a);
    if (!this.ports.has(a)) this.ports.set(a, new Map()); this.ports.get(a).set(b, pa);
    if (!this.ports.has(b)) this.ports.set(b, new Map()); this.ports.get(b).set(a, pb);
  }
  lane(from, ranks, port) {
    const chain = [];
    for (const r of ranks) { const d = { dummy: true, rank: r, w: 0, h: 6, x: 0, y: 0, origin: from, port }; this.near(chain.length ? chain[chain.length - 1] : from, d, chain.length ? 3 : port, 3); chain.push(d); this.items.push(d); }
    return chain;
  }
  addRoutes(pairs) {
    const rank = this.rank;
    for (const [a, bs] of pairs) {
      const r0 = rank.get(a);
      const ts = [...bs].map((b) => rank.get(b));
      const ports = new Map([...bs].map((b) => [b, this.portsBetween(a, b)]));
      const leaving = (some) => (some.length ? some.reduce((sum, b) => sum + ports.get(b).pa, 0) / some.length : mapAnchor(a));
      const ahead = this.lane(a, rankSpan(r0 + 1, Math.max(r0, ...ts)), leaving([...bs].filter((b) => rank.get(b) > r0)));
      const behind = this.lane(a, rankSpan(Math.min(r0 + 1, ...ts), r0 + 1).reverse(), leaving([...bs].filter((b) => rank.get(b) <= r0)));
      for (const b of bs) {
        const t = rank.get(b), { pa, pb } = ports.get(b);
        const via = t > r0 ? ahead.slice(0, t - r0 - 1) : behind.slice(0, r0 - t + 1);
        if (via.length) this.near(via[via.length - 1], b, 3, pb); else this.near(a, b, pa, pb);
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
    for (const it of this.items) if (it.dummy) it.y = it.origin.y + it.port - 3;
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
    const wanted = [...nb.map((o) => o.y + this.port(o, it) - this.port(it, o)), ...(this.pulls.get(it) || []).map((p) => p.y)];
    return wanted.length ? wanted.reduce((acc, y) => acc + y, 0) / wanted.length : it.y;
  }
  tighten() {
    const connected = (it) => (this.nbrs.get(it) || new Set()).size > 0 || this.pulls.has(it);
    for (const col of this.cols) {
      if (!col) continue;
      col.sort((a, b) => (connected(b) - connected(a)) || a.y - b.y);
      let prev = null;
      for (const it of col) {
        const lo = prev === null ? MAP_TOP : prev + (it.dummy ? 8 : this.gapY);
        it.y = Math.min(Math.max(it.y, lo), this.pulls.has(it) ? Infinity : lo + 36);
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
export function rankSpan(lo, hi) { return Array.from({ length: Math.max(0, hi - lo) }, (_, i) => lo + i); }
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
function arrangeMapColumns(layout, columns, box, { gapY, top }) {
  const layerOf = new Map();
  columns.forEach((col, i) => col.forEach((it) => layerOf.set(it, i)));
  const links = [];
  for (const [a, others] of box.nbrs) for (const b of others) if (layerOf.get(a) < layerOf.get(b)) links.push({ a, b, pa: box.port(a, b), pb: box.port(b, a), weight: 1 });
  const targets = [];
  for (const [k, pulls] of box.pulls) { const target = { target: true, y: pulls.reduce((sum, p) => sum + p.y, 0) / pulls.length, h: 0 }; targets.push(target); links.push({ a: k, b: target, pa: 0, pb: 0, weight: 1 }); }
  const placed = arrangeLayers(layout, targets.length ? [...columns, [], targets.sort((p, q) => p.y - q.y)] : columns, links, {
    height: (it) => it.h,
    gap: (it) => (it.dummy ? 8 : it.target ? 0 : gapY),
    floor: (it) => (it.target ? it.y : top),
    pinned: (it) => Boolean(it.target),
    isDummy: (it) => Boolean(it.dummy),
    candidates: (it, list) => list,
    previous: new Map([...columns.flat(), ...targets].map((it) => [it, it.y])),
  });
  if (placed) for (const [it, y] of placed) it.y = y;
}
export function moduleNodeOf(id) { return net().chain(id).find((n) => n.kind === 'module') || null; }
export function moduleFileName(module) { return module.name === '__init__.py' && module.parent.kind === 'package' ? `${module.parent.name}/__init__.py` : module.name; }
