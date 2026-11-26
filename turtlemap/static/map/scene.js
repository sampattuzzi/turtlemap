import { Scene, loopBackPath, overlaps, pathBox, placeCard, routedPath, setCulled } from '../canvas/scene.js';
import { KIND_ORDER, net } from '../core/data.js';
import { el, svg } from '../core/dom.js';
import { DIFF_SIGN, NET_COLUMNS, NET_ROUTES, NET_SLACK, combinedDiff, diffBadge, layoutNet, moduleFileName, moduleNodeOf, netBoxEl, netLabel, offsetWithin, rankSpan, ribbonWidth } from './boxes.js';
const EDGE_GAP = 10;
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
  const shown = visibleLinks(N, effective);
  const shortcuts = shortcutKeys([...shown.values()]);
  for (const l of shown.values()) l.shortcut = shortcuts.has(`${l.from}|${l.to}`);
  layoutNet(N.root, rootEl, [...shown.values()]);
  scene.measure();
  scene.finish(40);
  const { rects, sizes } = measureBoxes(rootEl, rootV);
  const drawnOpen = new Set([...effective].filter((id) => id === 'root' || rects.has(id)));
  const groups = arrowGroups(N, shown, rects, shortcuts);
  const drawing = new NetDrawing(scene, N, { rootEl, rootV, rects, effective });
  drawing.drawArrows(groups);
  drawing.traceRoutes();
  spreadLabels(drawing.drawn);
  drawing.listen();
  scene.pin = (id) => drawing.pin(id);
  scene.pin(ctx.selectedId ? ctx.selectedId() : null);
  scene.cull = (view) => drawing.cull(view);
  scene.sizes = sizes;
  scene.netRects = rects;
  scene.effective = drawnOpen;
  return scene;
}
class NetDrawing {
  constructor(scene, N, { rootEl, rootV, rects, effective }) {
    Object.assign(this, { scene, N, rootEl, rootV, rects, effective });
    this.pinned = null;
    this.focusEls = [];
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
    return route.via.map((d) => ({ x: o.x + d.x, y: o.y + d.y + (d.h || 6) / 2, w: d.w }));
  }
  drawArrows(groups) {
    const items = [...groups.values()].map((g) => this.arrowItem(g));
    stackEnds(items, this.rects);
    const offsets = this.sharedOffsets(items);
    for (const it of items) this.drawArrow(it, offsets);
  }
  arrowItem(g) {
    g.kind = KIND_ORDER.find((k) => g.kinds.has(k));
    const ra = this.rects.get(g.a), rb = this.rects.get(g.b), route = NET_ROUTES.get(`${g.a}|${g.b}`);
    const spans = this.absVia(route);
    return { g, a: g.a, b: g.b, ra, rb, route, forward: rb.x >= ra.x + ra.w - 4, raw: ribbonWidth(g.count), outKey: spans.length ? spans[0].y : rb.y + rb.anchorY, inKey: spans.length ? spans[spans.length - 1].y : ra.y + ra.anchorY };
  }
  sharedOffsets(items) {
    const through = new Map();
    for (const it of items) for (const d of (it.route && it.route.via) || []) { if (!through.has(d)) through.set(d, []); through.get(d).push(it); }
    const offsets = new Map();
    for (const [d, list] of through) {
      list.sort((p, q) => p.ys - q.ys);
      const at = new Map();
      let y = -list.reduce((t, it) => t + it.w, 0) / 2;
      for (const it of list) { at.set(it, y + it.w / 2); y += it.w; }
      offsets.set(d, at);
    }
    return offsets;
  }
  ribbonGroup(key) {
    if (!this.groupsBy) this.groupsBy = new Map();
    if (!this.groupsBy.has(key)) { const g = svg('g', { class: 'ribbons' }); this.overlay.append(g); this.groupsBy.set(key, g); }
    return this.groupsBy.get(key);
  }
  drawArrow(it, offsets) {
    const { g, ra, rb, route, forward } = it;
    const ends = { a: { x: ra.x + ra.w, y: it.ys }, b: { x: rb.x - 2, y: it.yt } };
    const o = route ? this.innerOffset(route.inner) : null;
    const spans = route ? route.via.map((d) => ({ x: o.x + d.x, y: o.y + d.y + (d.h || 6) / 2 + offsets.get(d).get(it), w: d.w })) : [];
    const { d, labelAt } = forward ? forwardArrow(g, ends, spans) : loopBackArrow(g, ra, rb, ends, spans);
    const changed = g.diff ? ` diff-${g.diff}` : '';
    const path = ribbonPath(d, it.w, g.kind, forward, `rel ribbon k-${g.kind} weighted${g.count === 1 ? ' light' : ''}${g.shortcut ? ' shortcut' : ''}${changed}`);
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
    this.ribbonGroup(g.a).append(path);
    this.overlay.append(text, hit);
    this.drawn.push({ g, path, text, hit, forward, ends, labelBox: labelBoxOf(text, label.length + (g.diff ? 2 : 0)) });
  }
  traceRoutes() {
    for (const d of this.drawn) {
      d.routes = d.g.atoms.map((e) => this.routeOf(e, d));
      for (const route of d.routes) for (const f of route.segs) f.passing.push({ d, route });
      d.traced = d.routes.every((route) => route.whole);
    }
    for (const f of this.feederList) {
      const state = combinedDiff(f.passing.map(({ route }) => route.e.diff));
      if (state) f.el.classList.add(`diff-${state}`);
    }
    for (const list of groupBy(this.feederList, (f) => f.port).values()) {
      for (const f of list) f.w = ribbonWidth(Math.max(1, f.passing.length));
      list.sort((p, q) => p.cy - q.cy);
      let y = list[0].portY - list.reduce((t, f) => t + f.w, 0) / 2;
      for (const f of list) {
        const d = f.shape(y + f.w / 2);
        y += f.w;
        f.el.setAttribute('d', ribbonArea(d, f.w));
        f.hit.setAttribute('d', d);
      }
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
    const shape = (port) => (side === 'R'
      ? `M${rc.x + rc.w},${cy} L${routedPath(rc.x + rc.w + (NET_SLACK.get(c) || 0), cy, rq.x + rq.w, port, via, 0).slice(1)}`
      : routedPath(rq.x, port, rc.x, cy, via, 0));
    const d = shape(portY);
    const feeder = { el: svg('path', { d, class: 'feeder ribbon-feeder' }), hit: svg('path', { d, class: 'feeder-hit', 'data-feeder': this.feederList.length }), child: c, passing: [], side, port: `${side}|${q}`, portY, cy, shape };
    this.feederList.push(feeder);
    this.overlay.prepend(feeder.el, feeder.hit);
    return feeder;
  }
  pin(id) {
    this.pinned = id && this.rects.has(id) && !this.effective.has(id) ? id : null;
    if (!this.hovered) this.highlight(null);
  }
  highlight(id) {
    const focus = id || this.pinned;
    this.scene.el.classList.toggle('has-hot', Boolean(focus));
    for (const f of this.feederList) coolFeeder(f);
    for (const d of this.drawn) { d.path.classList.remove('hot'); d.text.classList.remove('hot'); }
    const ends = this.drawFocus(focus);
    if (this.scene.onHot) this.scene.onHot(focus ? ends : null);
  }
  drawFocus(id) {
    for (const x of this.focusEls) x.remove();
    this.focusEls = [];
    if (!id) return [];
    const found = focusLines(this.N, this.effective, this.rects, id);
    const band = found.reduce((t, line) => t + ribbonWidth(line.atoms.length), 0);
    const lines = found.map((line) => this.focusItem(line, band));
    stackEnds(lines, this.rects);
    stackShared(lines);
    const group = svg('g', { class: 'ribbons focus-ribbons' });
    this.overlay.append(group);
    this.focusEls.push(group);
    for (const line of lines) this.drawFocusLine(line, group);
    return lines.map((line) => relationEnds({ g: line, ends: line.ends }, line.outgoing));
  }
  levelSpans(id, top, want, leaving, margin, own) {
    const chain = this.N.chain(id), at = chain.findIndex((x) => x.id === top);
    want = Math.max(want, this.headerFloor(chain.slice(at, -1), margin));
    const levels = [];
    for (let j = at; j < chain.length - 1; j++) {
      const cols = NET_COLUMNS.get(chain[j].id), box = this.rects.get(chain[j].id);
      if (!box) continue;
      const spans = [];
      if (cols) {
        const rank = cols.rank.get(chain[j + 1].id), o = this.innerOffset(cols.inner);
        const ranks = leaving ? rankSpan(rank + 1, cols.last + 1) : rankSpan(0, rank);
        for (const r of ranks) if (cols.colX[r] !== undefined) spans.push({ x: o.x + cols.colX[r], w: cols.colW[r], y: o.y + cols.gapNear(r, want - o.y, margin) });
      }
      levels.push({ box, spans });
    }
    const near = leaving ? levels.findIndex((l) => l.spans.length) : levels.length - 1 - [...levels].reverse().findIndex((l) => l.spans.length);
    const shared = (k) => (leaving ? k >= near && near >= 0 : k <= near && near < levels.length);
    const points = levels.map(({ box, spans }, k) => {
      const y = Math.min(shared(k) ? want : own, box.y + box.h - margin);
      const edge = { x: leaving ? box.x + box.w + EDGE_GAP : box.x - EDGE_GAP, y, w: 0 };
      return leaving ? [...spans, edge] : [edge, ...spans];
    });
    return (leaving ? points.reverse() : points).flat();
  }
  headerFloor(containers, margin) {
    return Math.max(-Infinity, ...containers.map((c) => this.rects.get(c.id)).filter(Boolean).map((box) => box.y + 2 * box.anchorY + margin));
  }
  focusSpans(sa, sb, want, margin) {
    const parent = this.N.nodes.get(sa).parent, cols = parent && NET_COLUMNS.get(parent.id);
    if (!cols) return [];
    const ra = cols.rank.get(sa), rb = cols.rank.get(sb), o = this.innerOffset(cols.inner);
    const ranks = rb > ra ? rankSpan(ra + 1, rb) : rankSpan(rb, ra + 1).reverse();
    return ranks.filter((r) => cols.colX[r] !== undefined).map((r) => ({ x: o.x + cols.colX[r], w: cols.colW[r], y: o.y + cols.gapNear(r, want - o.y, margin) }));
  }
  focusItem(line, band) {
    const ra = this.rects.get(line.a), rb = this.rects.get(line.b);
    const ay = ra.y + ra.anchorY, by = rb.y + rb.anchorY;
    const [sa, sb] = siblingEnds(this.N, line.a, line.b);
    const outer = this.rects.get(sa), inner = this.rects.get(sb);
    const forward = inner.x >= outer.x + outer.w - 4;
    const raw = ribbonWidth(line.atoms.length), margin = band / 2 + 6;
    const out = this.N.chain(line.a), into = this.N.chain(line.b);
    const floor = Math.max(this.headerFloor(out.slice(out.findIndex((x) => x.id === sa), -1), margin), this.headerFloor(into.slice(into.findIndex((x) => x.id === sb), -1), margin));
    const home = line.outgoing ? ra : rb;
    const shared = Math.max((home.el && home.el.classList.contains('open') ? home.y + home.anchorY * 2 : home.y + home.h) + margin, floor);
    const spans = this.focusSpans(sa, sb, shared, margin);
    const via = forward ? [...this.levelSpans(line.a, sa, shared, true, margin, ay), ...spans, ...this.levelSpans(line.b, sb, shared, false, margin, by)] : spans;
    return Object.assign(line, { ra, rb, outer, inner, forward, via, raw, outKey: by, inKey: ay });
  }
  drawFocusLine(line, group) {
    const { ra, rb, outer, inner, via } = line;
    const a = { x: ra.x + ra.w, y: line.ys }, b = { x: rb.x - 2, y: line.yt };
    line.ends = { a, b };
    let d;
    if (line.forward) d = routedPath(a.x, a.y, b.x, b.y, via, 0);
    else {
      const lane = via.length ? via : [{ x: Math.min(outer.x, inner.x), w: outer.x + outer.w - Math.min(outer.x, inner.x), y: Math.min(outer.y, inner.y) - 12 }];
      d = loopBackPath(a.x, a.y, b.x, b.y, lane);
    }
    group.append(ribbonPath(d, line.w, line.kind, line.forward, `rel ribbon focus-line weighted hot k-${line.kind}${line.diff ? ` diff-${line.diff}` : ''}`));
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
function focusLines(N, effective, rects, id) {
  const inside = (x) => N.chain(x).some((n) => n.id === id);
  const encloses = (outer, inner) => N.chain(inner).some((n) => n.id === outer);
  const lines = new Map();
  for (const e of N.edges) {
    const outgoing = inside(e.from);
    if (outgoing === inside(e.to)) continue;
    const a = visibleEnd(N, effective, e.from), b = visibleEnd(N, effective, e.to);
    if (!rects.has(a) || !rects.has(b) || encloses(a, b) || encloses(b, a)) continue;
    const key = `${a}|${b}`;
    if (!lines.has(key)) lines.set(key, { a, b, outgoing, atoms: [], kinds: new Set() });
    const line = lines.get(key);
    line.atoms.push(e);
    e.kinds.forEach((k) => line.kinds.add(k));
  }
  for (const line of lines.values()) { line.kind = KIND_ORDER.find((k) => line.kinds.has(k)); line.diff = combinedDiff(line.atoms.map((e) => e.diff)); }
  return [...lines.values()];
}
function visibleLinks(N, effective) {
  const shown = new Map();
  for (const e of N.edges) {
    const from = visibleEnd(N, effective, e.from), to = visibleEnd(N, effective, e.to);
    const [sa, sb] = siblingEnds(N, from, to);
    if (sa === sb) continue;
    const [a, b] = [sa, sb];
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
function forwardArrow(g, ends, spans) {
  const { x: x1, y: y1 } = ends.a, { x: x2, y: y2 } = ends.b;
  const out = x1 + (NET_SLACK.get(g.a) || 0);
  const dx = Math.abs(x2 - out) * 0.5;
  const curve = spans.length ? routedPath(out, y1, x2, y2, spans, 0) : `M${out},${y1} C${out + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`;
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
const RIBBON_STACK = 140;
function ribbonMarker(kind, width) {
  if (kind === 'inherits' || kind === 'realizes') return 'url(#m-tri)';
  if (kind === 'bound') return 'url(#m-tri-bound)';
  return width < 5 ? `url(#m-arrow-${kind})` : null;
}
function ribbonPath(d, width, kind, forward, cls) {
  const marker = ribbonMarker(kind, width);
  if (!forward) {
    const path = svg('path', { d, class: cls });
    path.style.setProperty('--w', `${width.toFixed(2)}px`);
    if (marker) path.setAttribute('marker-end', marker);
    return path;
  }
  const group = svg('g', { class: cls });
  const area = svg('path', { d: ribbonArea(d, width), class: 'ribbon-area' });
  area.style.fill = `var(--rel-${kind}, var(--rel-uses))`;
  area.style.stroke = area.style.fill;
  group.append(area);
  if (marker) group.append(svg('path', { d, class: 'ribbon-tip', 'marker-end': marker }));
  return group;
}
function ribbonArea(d, width) {
  const segments = [];
  let at = null;
  for (const [, cmd, args] of d.matchAll(/([MLC])([^MLC]*)/g)) {
    const n = (args.match(/-?\d+(?:\.\d+)?(?:e-?\d+)?/g) || []).map(Number);
    const points = [];
    for (let i = 0; i + 1 < n.length; i += 2) points.push([n[i], n[i + 1]]);
    if (cmd === 'M') { at = points[0]; continue; }
    const step = cmd === 'C' ? 3 : 1;
    for (let i = 0; i + step <= points.length; i += step) { const pts = points.slice(i, i + step); segments.push({ from: at, pts }); at = pts[pts.length - 1]; }
  }
  if (!segments.length) return d;
  const half = width / 2, shift = (p, dy) => `${(+p[0].toFixed(2))},${(+(p[1] + dy).toFixed(2))}`;
  let top = `M${shift(segments[0].from, -half)}`;
  for (const sgm of segments) top += ` ${sgm.pts.length === 3 ? 'C' : 'L'}${sgm.pts.map((p) => shift(p, -half)).join(' ')}`;
  let bottom = ` L${shift(segments[segments.length - 1].pts[segments[segments.length - 1].pts.length - 1], half)}`;
  for (let i = segments.length - 1; i >= 0; i--) {
    const sgm = segments[i];
    bottom += sgm.pts.length === 3 ? ` C${shift(sgm.pts[1], half)} ${shift(sgm.pts[0], half)} ${shift(sgm.from, half)}` : ` L${shift(sgm.from, half)}`;
  }
  return `${top}${bottom} Z`;
}
function stackEnds(items, rects) {
  const outs = groupBy(items, (it) => it.a), ins = groupBy(items, (it) => it.b);
  const room = (r) => Math.max(6, (r.el && r.el.classList.contains('open') ? RIBBON_STACK : r.h) - 4);
  const fit = new Map();
  for (const [id, list] of outs) fit.set(`out|${id}`, Math.min(1, room(rects.get(id)) / list.reduce((t, it) => t + it.raw, 0)));
  for (const [id, list] of ins) fit.set(`in|${id}`, Math.min(1, room(rects.get(id)) / list.reduce((t, it) => t + it.raw, 0)));
  for (const it of items) it.w = Math.max(1.2, it.raw * Math.min(fit.get(`out|${it.a}`), fit.get(`in|${it.b}`)));
  placeSlots(outs, rects, 'outKey', 'ys');
  placeSlots(ins, rects, 'inKey', 'yt');
}
function stackShared(lines) {
  const at = new Map();
  for (const line of lines) for (const p of line.via) { const k = `${Math.round(p.x)},${Math.round(p.y)}`; if (!at.has(k)) at.set(k, []); at.get(k).push({ line, p }); }
  for (const list of at.values()) {
    if (list.length < 2) continue;
    list.sort((u, v) => (u.line.outgoing ? u.line.rb.y - v.line.rb.y : u.line.ra.y - v.line.ra.y));
    let y = -list.reduce((t, { line }) => t + line.w, 0) / 2;
    for (const { line, p } of list) { p.y += y + line.w / 2; y += line.w; }
  }
}
function placeSlots(byBox, rects, key, field) {
  for (const [id, list] of byBox) {
    const r = rects.get(id), total = list.reduce((t, it) => t + it.w, 0);
    list.sort((p, q) => p[key] - q[key]);
    const open = r.el && r.el.classList.contains('open');
    let y = open ? r.y + 3 : Math.max(r.y + 1, r.y + r.h / 2 - total / 2);
    for (const it of list) { it[field] = y + it.w / 2; y += it.w; }
  }
}
function groupBy(items, keyOf) {
  const out = new Map();
  for (const it of items) { const k = keyOf(it); if (!out.has(k)) out.set(k, []); out.get(k).push(it); }
  return out;
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
  }
}
function coolFeeder(f) {
  f.el.classList.remove('hot');
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
