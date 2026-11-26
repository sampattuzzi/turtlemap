import { Scene, loopBackPath, overlaps, pathBox, placeCard, routedPath, setCulled } from '../canvas/scene.js';
import { KIND_ORDER, net } from '../core/data.js';
import { el, svg } from '../core/dom.js';
import { DIFF_SIGN, NET_COLUMNS, NET_ROUTES, NET_SLACK, combinedDiff, diffBadge, layoutNet, moduleFileName, moduleNodeOf, netBoxEl, netLabel, offsetWithin, outsideOf, rankSpan } from './boxes.js';
import { settings } from '../core/settings.js';
export function buildNetScene(expanded, ctx, filter = null) {
  const N = net();
  const scene = new Scene(ctx);
  const effective = effectiveOpen(N, expanded);
  const rootEl = el('div', { class: 'nroot', 'data-id': 'root' });
  const inner = el('div', { class: 'ninner' });
  for (const k of N.root.children) if (!filter || filter.visible(k)) inner.append(netBoxEl(k, effective, ctx, filter));
  rootEl.append(inner);
  const rootV = scene.add(rootEl);
  NET_ROUTES.clear(); NET_SLACK.clear(); NET_COLUMNS.clear();
  const direct = settings.ungrouped;
  const shown = visibleLinks(N, effective, direct);
  const shortcuts = shortcutKeys([...shown.values()]);
  for (const l of shown.values()) l.shortcut = shortcuts.has(`${l.from}|${l.to}`);
  layoutNet(N.root, rootEl, [...shown.values()]);
  if (direct) layoutNet(N.root, rootEl, [...shown.values()], N, outsideOf(rootEl));
  scene.measure();
  scene.finish(40);
  const { rects, sizes } = measureBoxes(rootEl, rootV);
  const drawnOpen = new Set([...effective].filter((id) => id === 'root' || rects.has(id)));
  const groups = arrowGroups(N, shown, rects, shortcuts);
  const drawing = new NetDrawing(scene, N, { rootEl, rootV, rects, effective, direct });
  drawing.drawArrows(groups);
  drawing.traceRoutes();
  spreadLabels(drawing.drawn);
  drawing.listen();
  scene.cull = (view) => drawing.cull(view);
  scene.sizes = sizes;
  scene.netRects = rects;
  scene.effective = drawnOpen;
  return scene;
}
class NetDrawing {
  constructor(scene, N, { rootEl, rootV, rects, effective, direct }) {
    Object.assign(this, { scene, N, rootEl, rootV, rects, effective, direct });
    this.drawn = [];
    this.offsets = new Map();
    this.feeders = new Map();
    this.legs = new Map();
    this.hovered = null;
    this.card = null;
    this.hoverKey = '';
    scene.svg.append(arrowMarkers());
    this.overlay = svg('svg', { class: 'wires overlay', width: scene.width, height: scene.height });
    scene.el.append(this.overlay);
    this.feederList = [];
    for (const route of NET_ROUTES.values()) this.innerOffset(route.inner);
  }
  innerOffset(inner) {
    if (!this.offsets.has(inner)) { const o = offsetWithin(inner, this.rootEl); this.offsets.set(inner, { x: this.rootV.x + o.x, y: this.rootV.y + o.y }); }
    return this.offsets.get(inner);
  }
  absVia(route) {
    if (!route) return [];
    const o = this.innerOffset(route.inner);
    return route.via.map((d) => ({ x: o.x + d.x, y: o.y + d.y + 3, w: d.w }));
  }
  drawArrows(groups) { for (const g of groups.values()) this.drawArrow(g, groups); }
  drawArrow(g, groups) {
    g.kind = KIND_ORDER.find((k) => g.kinds.has(k));
    const ra = this.rects.get(g.a), rb = this.rects.get(g.b);
    const shift = groups.has(`${g.b}|${g.a}`) ? (g.a < g.b ? -4 : 4) : 0;
    const ends = { a: { x: ra.x + ra.w, y: ra.y + ra.anchorY + shift }, b: { x: rb.x - 2, y: rb.y + rb.anchorY + shift } };
    const [sa, sb] = siblingEnds(this.N, g.a, g.b);
    const forward = this.direct ? this.rects.get(sb).x >= this.rects.get(sa).x + this.rects.get(sa).w - 4 : rb.x >= ra.x + ra.w - 4;
    const spans = this.direct && forward ? this.directSpans(g, sa, sb, ends) : this.absVia(NET_ROUTES.get(`${sa}|${sb}`));
    const { d, labelAt } = forward ? forwardArrow(g, ends, shift, spans) : loopBackArrow(g, ra, rb, ends, spans);
    const changed = g.diff ? ` diff-${g.diff}` : '';
    const path = svg('path', { d, class: `rel k-${g.kind} weighted${g.count === 1 ? ' light' : ''}${g.shortcut ? ' shortcut' : ''}${changed}`, 'marker-end': g.kind === 'inherits' || g.kind === 'realizes' ? 'url(#m-tri)' : g.kind === 'bound' ? 'url(#m-tri-bound)' : `url(#m-arrow-${g.kind})` });
    path.style.setProperty('--w', `${(1.4 + 1.4 * Math.log2(g.count)).toFixed(2)}px`);
    if (g.kind === 'has') path.setAttribute('marker-start', 'url(#m-dia)');
    const end = g.kinds.size === 1 && g.kind === 'has' ? holdingEnd(this.N, g.atoms) : null;
    if (end) path.setAttribute('marker-end', `url(#m-hold-${end})`);
    const label = arrowLabel(this.N, g);
    const text = svg('text', { x: labelAt.x, y: labelAt.y - 5, class: `rel-label k-${g.kind}${changed}`, 'text-anchor': 'middle' });
    if (g.diff) { const sign = svg('tspan', { class: 'rel-sign' }); sign.textContent = `${DIFF_SIGN[g.diff]} `; text.append(sign); }
    text.append(label);
    if (g.count === 1) text.classList.add('light');
    if (g.shortcut) text.classList.add('shortcut');
    const hit = svg('path', { d, class: 'rel-hit', 'data-drawn': this.drawn.length });
    this.overlay.append(path, text, hit);
    this.drawn.push({ g, path, text, hit, forward, ends, labelBox: labelBoxOf(text, label.length + (g.diff ? 2 : 0)) });
  }
  directSpans(g, sa, sb, ends) {
    const along = (x) => ends.a.y + (ends.b.y - ends.a.y) * Math.min(1, Math.max(0, (x - ends.a.x) / Math.max(1, ends.b.x - ends.a.x)));
    const across = (box, ranks) => {
      const cols = NET_COLUMNS.get(box);
      if (!cols) return [];
      const o = this.innerOffset(cols.inner);
      return ranks.filter((r) => cols.colX[r] !== undefined).map((r) => ({ x: o.x + cols.colX[r], w: cols.colW[r], y: o.y + cols.gapNear(r, along(o.x + cols.colX[r] + cols.colW[r] / 2) - o.y) }));
    };
    const rankIn = (box, kid) => NET_COLUMNS.get(box).rank.get(kid);
    const from = this.N.chain(g.a), to = this.N.chain(g.b);
    const ia = from.findIndex((x) => x.id === sa), ib = to.findIndex((x) => x.id === sb);
    const spans = [];
    for (let j = from.length - 2; j >= ia; j--) { const q = from[j].id, cols = NET_COLUMNS.get(q); if (cols) spans.push(...across(q, rankSpan(rankIn(q, from[j + 1].id) + 1, cols.last + 1))); }
    const parent = from[ia - 1].id;
    if (NET_COLUMNS.has(parent)) spans.push(...across(parent, rankSpan(rankIn(parent, sa) + 1, rankIn(parent, sb))));
    for (let j = ib; j < to.length - 1; j++) { const q = to[j].id; if (NET_COLUMNS.has(q)) spans.push(...across(q, rankSpan(0, rankIn(q, to[j + 1].id)))); }
    return spans;
  }
  traceRoutes() {
    if (this.direct) {
      for (const d of this.drawn) { d.routes = []; d.traced = d.g.atoms.every((e) => e.from === d.g.a && e.to === d.g.b); }
      return;
    }
    for (const d of this.drawn) {
      d.routes = d.g.atoms.map((e) => this.routeOf(e, d));
      for (const route of d.routes) for (const f of route.segs) f.passing.push({ d, route });
      d.traced = d.routes.every((route) => route.whole);
    }
    for (const f of this.feederList) {
      const state = combinedDiff(f.passing.map(({ route }) => route.e.diff));
      if (state) f.el.classList.add(`diff-${state}`);
    }
  }
  routeOf(e, d) {
    const out = this.legOf(d.g.a, visibleEnd(this.N, this.effective, e.from), 'R'), into = this.legOf(d.g.b, visibleEnd(this.N, this.effective, e.to), 'L');
    return { e, segs: [...out, ...into], whole: out.length > 0 && into.length > 0 };
  }
  legOf(end, id, side) {
    const key = `${side}|${end}|${id}`;
    if (!this.legs.has(key)) {
      const chain = this.N.chain(id), segs = [];
      for (let j = chain.findIndex((x) => x.id === end); j >= 0 && j < chain.length - 1; j++) { const f = this.feederOf(side, chain[j].id, chain[j + 1].id); if (f) segs.push(f); }
      this.legs.set(key, segs);
    }
    return this.legs.get(key);
  }
  feederOf(side, q, c) {
    const key = `${side}|${q}|${c}`;
    if (!this.feeders.has(key)) this.feeders.set(key, this.feederPath(side, q, c));
    return this.feeders.get(key);
  }
  feederPath(side, q, c) {
    const cols = NET_COLUMNS.get(q), rq = this.rects.get(q), rc = this.rects.get(c);
    if (!cols || !rq || !rc || !cols.rank.has(c)) return null;
    const o = this.innerOffset(cols.inner);
    const portY = rq.y + rq.anchorY, cy = rc.y + rc.anchorY, r0 = cols.rank.get(c);
    const ranks = side === 'R' ? Array.from({ length: cols.last - r0 }, (_, i) => r0 + 1 + i) : Array.from({ length: r0 }, (_, i) => i);
    const want = (r) => (side === 'R' ? cy + ((portY - cy) * (r - r0)) / (cols.last + 1 - r0) : portY + ((cy - portY) * (r + 1)) / (r0 + 1));
    const via = ranks.filter((r) => cols.colX[r] !== undefined).map((r) => ({ x: o.x + cols.colX[r], w: cols.colW[r], y: o.y + cols.gapNear(r, want(r) - o.y) }));
    let d;
    if (side === 'R') { const start = rc.x + rc.w, out = start + (NET_SLACK.get(c) || 0); d = `M${start},${cy} L${routedPath(out, cy, rq.x + rq.w, portY, via, 30).slice(1)}`; }
    else d = routedPath(rq.x, portY, rc.x, cy, via, 30);
    const into = side === 'L';
    const feeder = { el: svg('path', { d, class: 'feeder', ...(into ? { 'marker-end': FEEDER_HEAD } : {}) }), into, hit: svg('path', { d, class: 'feeder-hit', 'data-feeder': this.feederList.length }), child: c, passing: [] };
    this.feederList.push(feeder);
    this.overlay.prepend(feeder.el, feeder.hit);
    return feeder;
  }
  highlight(id) {
    const N = this.N;
    this.scene.el.classList.toggle('has-hot', Boolean(id));
    const inside = (x) => Boolean(id) && N.chain(x).some((n) => n.id === id);
    for (const f of this.feederList) coolFeeder(f);
    if (id) this.lightRoutes(inside);
    const ends = this.drawn.map((d) => lightRelation(d, inside)).filter(Boolean);
    if (this.scene.onHot) this.scene.onHot(id ? ends : null);
  }
  lightRoutes(inside) {
    for (const d of this.drawn) for (const route of d.routes) if (inside(route.e.from) || inside(route.e.to)) lightRoute(d, route);
  }
  listen() {
    const host = this.scene.el;
    host.addEventListener('mousemove', (e) => this.onMouseMove(e));
    host.addEventListener('mouseout', (e) => { if (e.target.closest('.rel-hit, .feeder-hit') && !(e.relatedTarget instanceof Element && e.relatedTarget.closest('.rel-hit, .feeder-hit'))) { this.dropCard(); this.highlight(null); } });
    host.addEventListener('mouseover', (e) => {
      if (e.target.closest('.rel-hit')) return;
      const feeder = e.target.closest('.feeder-hit');
      if (feeder) { this.hoverFeeder(this.feederList[+feeder.dataset.feeder]); return; }
      const b = e.target.closest('.nb');
      const id = b && (!b.classList.contains('open') || e.target.closest('.nhead')) ? b.dataset.id : null;
      if (id !== this.hovered) { this.hovered = id; this.highlight(id); }
    });
    host.addEventListener('mouseleave', () => { this.hovered = null; this.dropCard(); this.highlight(null); });
    host.addEventListener('click', (e) => this.onClick(e));
  }
  onClick(e) {
    const hit = e.target.closest('.rel-hit, .feeder-hit');
    if (!hit || !this.scene.ctx.followArrow) return;
    e.stopPropagation();
    this.dropCard();
    this.highlight(null);
    if (hit.classList.contains('rel-hit')) { const d = this.drawn[+hit.dataset.drawn]; this.scene.ctx.followArrow(d.g.a, [d.g.a, d.g.b]); return; }
    const f = this.feederList[+hit.dataset.feeder];
    const ends = f.passing.flatMap(({ route }) => [visibleEnd(this.N, this.effective, route.e.from), visibleEnd(this.N, this.effective, route.e.to)]);
    if (ends.length) this.scene.ctx.followArrow(f.child, [...new Set(ends)]);
  }
  hoverFeeder(f) {
    this.dropCard();
    this.hovered = null;
    this.highlight(null);
    this.scene.el.classList.add('has-hot');
    for (const { d, route } of f.passing) { d.path.classList.add('hot'); d.text.classList.add('hot'); lightRoute(d, route); }
  }
  onMouseMove(e) {
    if (!e.target.closest('.rel-hit')) return;
    const under = document.elementsFromPoint(e.clientX, e.clientY).filter((x) => x.classList.contains('rel-hit')).map((x) => this.drawn[+x.dataset.drawn]);
    const key = under.map((d) => `${d.g.a}|${d.g.b}`).join(' ');
    if (key !== this.hoverKey && !this.hoverArrows(under, key)) return;
    if (this.card) placeCard(this.card, e);
  }
  hoverArrows(under, key) {
    this.dropCard();
    this.hovered = null; this.highlight(null);
    if (!under.length) return false;
    this.hoverKey = key;
    this.scene.el.classList.add('has-hot');
    for (const d of under) { d.path.classList.add('hot'); d.text.classList.add('hot'); for (const route of d.routes) lightRoute(d, route); }
    const carded = under.filter((d) => !d.traced);
    if (carded.length) { this.card = edgeCardEl(carded.map((d) => d.g)); document.body.append(this.card); }
    return true;
  }
  dropCard() {
    if (this.card) { this.card.remove(); this.card = null; }
    this.hoverKey = '';
  }
  cull(view) {
    for (const r of this.rects.values()) setCulled(r.el, r, !overlaps(r, view));
    for (const d of this.drawn) {
      if (!d.box) d.box = arrowBox(d);
      const hidden = !overlaps(d.box, view);
      setCulled(d.path, d, hidden);
      d.text.style.display = hidden ? 'none' : '';
      d.hit.style.display = hidden ? 'none' : '';
    }
    for (const f of this.feederList) {
      if (!f.box) f.box = pathBox(f.el);
      setCulled(f.el, f, !overlaps(f.box, view));
      f.hit.style.display = f.culled ? 'none' : '';
    }
  }
}
export function effectiveOpen(N, expanded) {
  const effective = new Set(['root']);
  const open = (x) => expanded.has(x.id) !== N.autoOpen.has(x.id);
  for (const id of new Set([...expanded, ...N.autoOpen])) { const c = N.chain(id); if (c.length && c[c.length - 1].children.length && c.slice(1).every(open)) effective.add(id); }
  return effective;
}
function visibleEnd(N, effective, id) {
  const c = N.chain(id);
  for (let i = 1; i < c.length; i++) if (!effective.has(c[i].id)) return c[i].id;
  return id;
}
function visibleLinks(N, effective, direct) {
  const shown = new Map();
  for (const e of N.edges) {
    const from = visibleEnd(N, effective, e.from), to = visibleEnd(N, effective, e.to);
    const [sa, sb] = siblingEnds(N, from, to);
    if (sa === sb) continue;
    const [a, b] = direct ? [from, to] : [sa, sb];
    const key = `${a}|${b}`;
    if (!shown.has(key)) shown.set(key, { from: a, to: b, atoms: [] });
    shown.get(key).atoms.push(e);
  }
  return shown;
}
function measureBoxes(rootEl, rootV) {
  const rects = new Map();
  const sizes = [];
  rootEl.querySelectorAll('.nb').forEach((b) => {
    const { x, y } = offsetWithin(b, rootEl);
    const head = b.querySelector(':scope > .nhead');
    rects.set(b.dataset.id, { x: rootV.x + x, y: rootV.y + y, w: b.offsetWidth, h: b.offsetHeight, anchorY: head ? head.offsetHeight / 2 : b.offsetHeight / 2, el: b });
    sizes.push({ el: b, w: b.offsetWidth, h: b.offsetHeight });
  });
  return { rects, sizes };
}
function arrowGroups(N, shown, rects, shortcuts) {
  const groups = new Map();
  for (const { from: a, to: b, atoms } of shown.values()) {
    if (!rects.has(a) || !rects.has(b)) continue;
    if (N.chain(b).some((x) => x.id === a) || N.chain(a).some((x) => x.id === b)) continue;
    const g = { a, b, kinds: new Set(), labels: new Set(), count: atoms.length, atoms, shortcut: shortcuts.has(`${a}|${b}`), through: shortcuts.get(`${a}|${b}`) || null };
    for (const e of atoms) { e.kinds.forEach((x) => g.kinds.add(x)); e.labels.forEach((x) => g.labels.add(x)); }
    g.diff = combinedDiff(atoms.map((e) => e.diff));
    groups.set(`${a}|${b}`, g);
  }
  return groups;
}
function arrowMarkers() {
  const defs = svg('defs');
  defs.innerHTML = `
    <marker id="m-tri" viewBox="0 0 14 14" refX="13" refY="7" markerWidth="14" markerHeight="14" markerUnits="userSpaceOnUse" orient="auto"><path d="M1,1 L13,7 L1,13 z" style="fill:var(--canvas);stroke:var(--rel-inherits)" stroke-width="1.6"/></marker>
    <marker id="m-tri-bound" viewBox="0 0 14 14" refX="13" refY="7" markerWidth="14" markerHeight="14" markerUnits="userSpaceOnUse" orient="auto"><path d="M1,1 L13,7 L1,13 z" style="fill:var(--canvas);stroke:var(--rel-bound)" stroke-width="1.6"/></marker>
    <marker id="m-feed" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" markerUnits="userSpaceOnUse" orient="auto"><path d="M1,1 L9,5 L1,9" style="fill:none;stroke:var(--fg-dim)" stroke-width="1.5"/></marker>
    <marker id="m-dia" viewBox="0 0 18 10" refX="1" refY="5" markerWidth="18" markerHeight="10" markerUnits="userSpaceOnUse" orient="auto"><path d="M1,5 L9,1 L17,5 L9,9 z" style="fill:var(--rel-has)"/></marker>
    ${Object.entries(HOLDING_ENDS).map(([end, shape]) => `<marker id="m-hold-${end}" class="hold-marker" viewBox="0 0 24 16" refX="24" refY="8" markerWidth="24" markerHeight="16" markerUnits="userSpaceOnUse" orient="auto">${shape}</marker>`).join('')}
    ${['has', 'creates', 'calls', 'writes', 'reads', 'uses'].map((k) => `<marker id="m-arrow-${k}" viewBox="0 0 12 12" refX="11" refY="6" markerWidth="12" markerHeight="12" markerUnits="userSpaceOnUse" orient="auto"><path d="M1,1 L11,6 L1,11" style="fill:none;stroke:var(--rel-${k})" stroke-width="1.7"/></marker>`).join('')}`;
  return defs;
}
const HOLDING_ENDS = {
  one: '<path d="M16,1 V15 M11,1 V15"/>',
  optional: '<circle cx="8" cy="8" r="4"/><path d="M16,1 V15"/>',
  many: '<circle cx="6" cy="8" r="4"/><path d="M12,8 L24,1 M12,8 L24,8 M12,8 L24,15"/>',
};
function holdingEnd(N, atoms) {
  const ends = new Set(atoms.map((e) => fieldHolds(N.nodes.get(e.from), e.to)));
  return ends.size === 1 ? [...ends][0] : null;
}
function fieldHolds(field, target) {
  const t = field && field.kind === 'field' ? field.type : null;
  const classId = (ref) => (ref ? `cls:${ref.path}:${ref.sym}` : null);
  if (!t) return null;
  if (classId(t.items) === target) return 'many';
  if (classId(t.ref) === target) return t.opt ? 'optional' : 'one';
  return null;
}
function forwardArrow(g, ends, shift, spans) {
  const { x: x1, y: y1 } = ends.a, { x: x2, y: y2 } = ends.b;
  const out = x1 + (NET_SLACK.get(g.a) || 0);
  const dx = Math.max(50, Math.abs(x2 - out) * 0.45);
  const lean = shift * 1.5 * (y2 > y1 ? -1 : 1);
  const curve = spans.length ? routedPath(out, y1, x2, y2, spans, 50, lean) : `M${out},${y1} C${out + dx + lean},${y1} ${x2 - dx + lean},${y2} ${x2},${y2}`;
  const tail = spans.length ? spans[spans.length - 1] : null;
  return {
    d: out > x1 + 1 ? `M${x1},${y1} L${curve.slice(1)}` : curve,
    labelAt: tail ? { x: (tail.x + tail.w + x2) / 2, y: (tail.y + y2) / 2 } : { x: cubicAt(0.65, out, out + dx, x2 - dx, x2), y: cubicAt(0.65, y1, y1, y2, y2) },
  };
}
function loopBackArrow(g, ra, rb, ends, spans) {
  const lane = spans.length ? spans : [{ x: Math.min(ra.x, rb.x), w: ends.a.x + (NET_SLACK.get(g.a) || 0) - Math.min(ra.x, rb.x), y: Math.min(ra.y, rb.y) - 12 }];
  const middle = lane[Math.floor((lane.length - 1) / 2)];
  return { d: loopBackPath(ends.a.x, ends.a.y, ends.b.x, ends.b.y, lane), labelAt: { x: middle.x + middle.w / 2, y: middle.y } };
}
function cubicAt(t, a, b, c, d) { return (1 - t) ** 3 * a + 3 * (1 - t) ** 2 * t * b + 3 * (1 - t) * t ** 2 * c + t ** 3 * d; }
function arrowLabel(N, g) {
  const kinds = [...g.kinds].sort((p, q) => KIND_ORDER.indexOf(p) - KIND_ORDER.indexOf(q));
  return g.kinds.size === 1 && g.kind === 'has' && N.nodes.get(g.a).kind === 'field' ? [...g.labels].join(', ') : `${kinds.join(' · ')}${g.count > 1 ? ` (${g.count})` : ''}`;
}
function labelBoxOf(text, chars) {
  return { x: +text.getAttribute('x') - chars * 3.3, y: +text.getAttribute('y') - 10, w: chars * 6.6, h: 13 };
}
function arrowBox(d) {
  const a = pathBox(d.path), t = d.labelBox;
  const x = Math.min(a.x, t.x), y = Math.min(a.y, t.y);
  return { x, y, w: Math.max(a.x + a.w, t.x + t.w) - x, h: Math.max(a.y + a.h, t.y + t.h) - y };
}
function lightRoute(d, route) {
  for (const f of route.segs) {
    f.el.classList.add('hot');
    f.el.style.setProperty('--feed', `var(--rel-${d.g.kind})`);
    if (f.into) f.el.setAttribute('marker-end', d.path.getAttribute('marker-end'));
  }
}
const FEEDER_HEAD = 'url(#m-feed)';
function coolFeeder(f) {
  f.el.classList.remove('hot');
  if (f.into) f.el.setAttribute('marker-end', FEEDER_HEAD);
}
function spreadLabels(drawn) {
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
    for (let i = 0; i < queue.length; i++) {
      const v = queue[i];
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
    el('div', { class: 'edge-card-rows' }, rows.map((e) => [el('span', {}, atomLabel(e.from, g.a)), el('span', { class: 'udim' }, '→'), el('span', {}, atomLabel(e.to, g.b)), el('span', { class: 'edge-kind', style: `color:var(--rel-${kindsOf(e)[0]})` }, diffBadge(e.diff), kindsOf(e).join(' · '))])),
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
function lightRelation(d, inside) {
  const fromHere = inside(d.g.a) || d.g.atoms.some((e) => inside(e.from));
  const toHere = inside(d.g.b) || d.g.atoms.some((e) => inside(e.to));
  const hot = fromHere || toHere;
  d.path.classList.toggle('hot', hot); d.text.classList.toggle('hot', hot);
  return hot && !(fromHere && toHere) ? relationEnds(d, fromHere) : null;
}
