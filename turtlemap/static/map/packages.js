import { boundsOf, overlaps, pathBox, placeCard, setCulled } from '../canvas/scene.js';
import { DIFF, KIND_ORDER, net } from '../core/data.js';
import { el, svg } from '../core/dom.js';
import { combinedDiff, diffBadge, moduleFileName, moduleNodeOf, netLabel, plural } from './boxes.js';
import { FOLDER_HEAD, layOutRibbons, placesOf, ribbonGraph } from './ribbons.js';
export const LIBRARIES = 'libraries';
const SCENE_PAD = 40;
const LAYOUTS = new Map();
const LAYOUTS_KEPT = 24;
export function buildPackageScene(entry, ctx, filter = null) {
  const N = net();
  const tree = visibleTree(N, entry.folded, filter);
  const scene = new PackageScene(N, ctx, tree);
  scene.measureLeaves();
  const G = ribbonGraph(tree.root, shownEdges(N, tree));
  const key = layoutKey(G);
  const result = layOutRibbons(G, LAYOUTS.get(key));
  rememberLayout(key, G);
  scene.draw(G, result);
  return scene;
}
export function moduleCount(n) { return n.kind === 'module' ? 1 : n.children.reduce((sum, k) => sum + (k.kind === 'package' || k.kind === 'module' ? moduleCount(k) : 0), 0); }
class PackageScene {
  constructor(N, ctx, tree) {
    Object.assign(this, { N, ctx, tree });
    this.folderLayer = el('div', { class: 'pd-folders' });
    this.svg = svg('svg', { class: `wires pd-wires${DIFF ? ' comparing' : ''}` });
    this.leafLayer = el('div', { class: 'pd-leaves' });
    this.el = el('div', { class: 'scene package-scene' }, this.folderLayer, this.svg, this.leafLayer);
    document.getElementById('measure').append(this.el);
    this.netRects = new Map();
    this.effective = new Set(tree.open);
    this.drawn = [];
    this.pinned = null;
    this.hovered = null;
    this.card = null;
    this.cardKey = '';
    this.hotCache = new Map();
  }
  measureLeaves() {
    for (const v of this.tree.leaves) {
      v.el = leafEl(v.node, this.ctx);
      this.leafLayer.append(v.el);
    }
    for (const f of [...this.tree.folders].sort((p, q) => p.node.depth - q.node.depth)) {
      f.el = folderEl(f.node, this.ctx);
      this.folderLayer.append(f.el);
    }
    for (const v of this.tree.leaves) { v.w = v.el.offsetWidth; v.h = v.el.offsetHeight; }
    for (const f of this.tree.folders) f.minW = f.el.querySelector(':scope > .nhead').scrollWidth + 4;
  }
  draw(G, result) {
    const dx = SCENE_PAD - (result.x0 || 0), dy = SCENE_PAD - (result.y0 || 0);
    this.width = result.width + 2 * SCENE_PAD;
    this.height = result.height + 2 * SCENE_PAD + 30;
    Object.assign(this.el.style, { width: `${this.width}px`, height: `${this.height}px` });
    this.svg.setAttribute('width', this.width);
    this.svg.setAttribute('height', this.height);
    this.svg.setAttribute('viewBox', `${-dx} ${-dy} ${this.width} ${this.height}`);
    for (const v of [...G.folders, ...G.leaves]) {
      const x = v.x + dx, y = v.y + dy;
      Object.assign(v.el.style, { left: `${x}px`, top: `${y}px` });
      if (v.kids) Object.assign(v.el.style, { width: `${v.w}px`, height: `${v.h}px` });
      this.netRects.set(v.id, { x, y, w: v.w, h: v.h, anchorY: v.kids ? FOLDER_HEAD / 2 : v.h / 2, el: v.el });
    }
    this.sizes = G.leaves.map((v) => ({ el: v.el, w: v.w, h: v.h }));
    this.shift = { dx, dy };
    this.drawLines(G, result);
    this.listen();
    this.pin(this.ctx.selectedId ? this.ctx.selectedId() : null);
  }
  drawLines(G, result) {
    const hues = packageHues(G, new Set(result.ribbons.map((r) => r.group.id)));
    const backs = svg('g', { class: 'pd-backs' }), groups = new Map(), hits = svg('g', { class: 'pd-hits' });
    for (const back of result.backs) {
      const path = svg('path', { d: back.d, class: `pd-back${diffClass(back.edge.link)}` });
      backs.append(path);
      this.addDrawn(back.edge, [path], back.d, hits, 'var(--fg-dim)');
    }
    for (const r of result.ribbons) {
      if (!groups.has(r.group.id)) groups.set(r.group.id, svg('g', { class: 'pd-group' }));
      const path = svg('path', { d: r.d, class: `pd-ribbon${diffClass(r.edge.link)}` });
      path.style.setProperty('--hue-fill', hues.get(r.group.id));
      groups.get(r.group.id).append(path);
      this.addDrawn(r.edge, [path], r.centre, hits, hues.get(r.group.id));
    }
    this.svg.append(backs, ...groups.values(), hits);
  }
  addDrawn(edge, parts, centre, hits, colour) {
    const hit = svg('path', { d: centre, class: 'rel-hit', 'data-drawn': this.drawn.length });
    hits.append(hit);
    this.drawn.push({ link: edge.link, parts, hit, colour });
  }
  listen() {
    const host = this.el;
    host.addEventListener('mouseover', (e) => {
      const hit = e.target.closest('.rel-hit');
      if (hit) { this.hoverLines(e); return; }
      const box = e.target.closest('.nb');
      const id = box && (box.classList.contains('leaf') || e.target.closest('.nhead')) ? box.dataset.id : null;
      if (id !== this.hovered) { this.hovered = id; this.dropCard(); this.highlight(); }
    });
    host.addEventListener('mousemove', (e) => { if (e.target.closest('.rel-hit')) this.hoverLines(e); });
    host.addEventListener('mouseout', (e) => { if (e.target.closest('.rel-hit') && !(e.relatedTarget instanceof Element && e.relatedTarget.closest('.rel-hit'))) { this.dropCard(); this.highlight(); } });
    host.addEventListener('mouseleave', () => { this.hovered = null; this.dropCard(); this.highlight(); });
    host.addEventListener('click', (e) => {
      const hit = e.target.closest('.rel-hit');
      if (!hit || !this.ctx.followArrow) return;
      e.stopPropagation();
      this.dropCard();
      const d = this.drawn[+hit.dataset.drawn];
      this.ctx.followArrow([d.link.a.id, d.link.b.id]);
    });
  }
  pin(id) {
    this.pinned = id && (this.N.nodes.has(id) || id === LIBRARIES) ? id : null;
    for (const box of this.el.querySelectorAll('.nb.pinned')) box.classList.remove('pinned');
    const shown = this.pinned ? this.shownBoxOf(this.pinned) : null;
    if (shown) this.netRects.get(shown).el.classList.add('pinned');
    this.highlight();
  }
  shownBoxOf(id) {
    if (this.netRects.has(id)) return id;
    const chain = this.N.chain(id);
    return [...chain].reverse().map((n) => n.id).find((x) => this.netRects.has(x)) || (chain[1] && chain[1].kind === 'library' && this.netRects.has(LIBRARIES) ? LIBRARIES : null);
  }
  inside(focus, id) { return focus === LIBRARIES ? isLibraryPart(this.N, id) : this.N.contains(focus, id); }
  highlight() {
    const focus = this.hovered || this.pinned;
    this.el.classList.toggle('has-hot', Boolean(focus));
    const hot = focus ? this.hotFor(focus) : new Set();
    this.drawn.forEach((d, i) => heat(d, hot.has(i)));
    if (this.onHot) this.onHot(focus ? this.endsFor(focus, hot) : null);
  }
  hotFor(focus) {
    if (!this.hotCache.has(focus)) {
      const inside = (id) => this.inside(focus, id);
      const hot = new Set();
      this.drawn.forEach((d, i) => { if (d.link.atoms.some((e) => inside(e.from) !== inside(e.to))) hot.add(i); });
      this.hotCache.set(focus, hot);
    }
    return this.hotCache.get(focus);
  }
  endsFor(focus, hot) {
    const near = this.netRects.get(this.shownBoxOf(focus));
    if (!near) return [];
    return [...hot].map((i) => {
      const d = this.drawn[i], outgoing = this.inside(focus, d.link.atoms[0].from);
      const other = outgoing ? d.link.b : d.link.a, far = this.netRects.get(other.id);
      const label = netLabel(other.id);
      return { key: other.id, from: { x: near.x + near.w / 2, y: near.y + near.anchorY }, to: { x: far.x + far.w / 2, y: far.y + far.anchorY }, label, color: d.colour, title: `${outgoing ? 'Uses' : 'Used by'} ${label}` };
    });
  }
  hoverLines(e) {
    const under = document.elementsFromPoint(e.clientX, e.clientY).filter((x) => x.classList.contains('rel-hit') && this.svg.contains(x)).map((x) => this.drawn[+x.dataset.drawn]);
    const key = under.map((d) => d.link.key).join(' ');
    if (key !== this.cardKey) {
      this.dropCard();
      if (!under.length) return;
      this.cardKey = key;
      this.el.classList.add('has-hot');
      this.drawn.forEach((d) => heat(d, under.includes(d)));
      this.card = edgeCardEl(under.map((d) => d.link));
      document.body.append(this.card);
    }
    if (this.card) placeCard(this.card, e);
  }
  dropCard() {
    if (this.card) { this.card.remove(); this.card = null; }
    this.cardKey = '';
  }
  cull(view) {
    for (const r of this.netRects.values()) setCulled(r.el, r, !overlaps(r, view));
    for (const d of this.drawn) {
      if (!d.box) d.box = shifted(pathBox(d.hit), this.shift);
      const hidden = !overlaps(d.box, view);
      for (const part of d.parts) setCulled(part, d, hidden);
      d.hit.style.display = hidden ? 'none' : '';
    }
  }
  frameOf(ids) { return boundsOf(ids.map((id) => this.netRects.get(id)).filter(Boolean)); }
}
function shownEdges(N, tree) {
  const pairs = new Map();
  for (const link of N.lift((n) => tree.open.has(n.id))) {
    const s = tree.byId.get(link.a.id), t = tree.byId.get(link.b.id);
    if (!s || !t || s === t) continue;
    const key = `${s.id}|${t.id}`;
    if (!pairs.has(key)) pairs.set(key, { s, t, w: 0, link: { key, a: s.node, b: t.node, atoms: [], kinds: new Set() } });
    const pair = pairs.get(key);
    pair.link.atoms.push(...link.atoms);
    link.kinds.forEach((k) => pair.link.kinds.add(k));
    pair.w = pair.link.atoms.length;
  }
  return [...pairs.values()];
}
function isLibraryPart(N, id) { const chain = N.chain(id); return Boolean(chain[1] && chain[1].kind === 'library'); }
function visibleTree(N, folded, filter) {
  const open = new Set(['root']), byId = new Map(), leaves = [], folders = [];
  const shown = (n) => !filter || filter.visible(n);
  const leaf = (n) => { const v = { id: n.id, node: n }; byId.set(n.id, v); leaves.push(v); return v; };
  const build = (n) => {
    const kids = [];
    for (const k of n.children) {
      if (!shown(k)) continue;
      if (k.kind === 'module') { kids.push(leaf(k)); continue; }
      if (k.kind !== 'package' || !moduleCount(k)) continue;
      if (folded.has(k.id)) { kids.push(leaf(k)); continue; }
      const inner = build(k);
      if (!inner.length) continue;
      const f = { id: k.id, node: k, kids: inner };
      open.add(k.id);
      byId.set(k.id, f);
      folders.push(f);
      kids.push(f);
    }
    return kids;
  };
  const root = { id: 'root', node: N.root, kids: build(N.root) };
  const libraries = N.root.children.filter((k) => k.kind === 'library' && shown(k));
  if (libraries.length) {
    const group = { id: LIBRARIES, kind: 'libraries', name: LIBRARIES, depth: 1, children: libraries };
    if (folded.has(LIBRARIES)) {
      const v = leaf(group);
      for (const lib of libraries) byId.set(lib.id, v);
      root.kids.push(v);
    } else {
      const f = { id: LIBRARIES, node: group, kids: libraries.map(leaf) };
      open.add(LIBRARIES);
      byId.set(LIBRARIES, f);
      folders.push(f);
      root.kids.push(f);
    }
  }
  return { root, open, byId, leaves, folders };
}
function leafEl(n, ctx) {
  const folded = n.kind === 'package' || n.kind === 'libraries';
  const { name, count, stripe } = boxText(n);
  const title = folded ? `${name} · ${count} · click to open` : n.kind === 'library' ? `${n.name} · library` : n.path;
  const box = el('div', { class: `nb leaf pd-leaf k-${n.kind}${n.faded ? ' faded' : ''}${n.diff ? ` diff-${n.diff}` : ''}`, 'data-id': n.id, style: `--stripe: var(${stripe})`, title },
    folded ? el('span', { class: 'chev' }, '▸') : null,
    diffBadge(n.diff),
    n.kind === 'library' ? el('span', { class: 'stereo' }, '«library»') : null,
    el('span', { class: 'pd-name' }, name),
    folded ? el('span', { class: 'udim' }, count) : null);
  box.addEventListener('click', (e) => { e.stopPropagation(); ctx.select(n.id); if (folded) ctx.toggle(n.id); });
  return box;
}
function folderEl(n, ctx) {
  const { name, stripe } = boxText(n);
  const box = el('div', { class: `nb open pd-folder k-${n.kind}${n.diff ? ` diff-${n.diff}` : ''}`, 'data-id': n.id, style: `--hc: var(${stripe})` },
    el('div', { class: 'nhead', title: 'Fold this into one box' }, el('span', { class: 'chev' }, '▾'), diffBadge(n.diff), el('span', { class: 'ntitle' }, name)));
  box.firstChild.addEventListener('click', (e) => { e.stopPropagation(); ctx.select(n.id); ctx.toggle(n.id); });
  return box;
}
function boxText(n) {
  if (n.kind === 'package') return { name: `${n.name}/`, count: plural(moduleCount(n), 'module'), stripe: '--h-pkg' };
  if (n.kind === 'libraries') return { name: 'libraries', count: `${n.children.length}`, stripe: '--h-lib' };
  if (n.kind === 'library') return { name: n.name, stripe: '--h-lib' };
  return { name: moduleFileName(n), stripe: '--h-mod' };
}
function diffClass(link) {
  const state = DIFF ? combinedDiff(link.atoms.map((e) => e.diff)) : null;
  return state ? ` diff-${state}` : '';
}
function heat(d, on) { for (const part of d.parts) part.classList.toggle('hot', on); }
function shifted(box, { dx, dy }) { return { ...box, x: box.x + dx, y: box.y + dy }; }
function layoutKey(G) {
  return `${G.leaves.map((v) => v.id).sort().join(' ')}#${G.edges.map((e) => `${e.s.id}>${e.t.id}`).sort().join(' ')}`;
}
function rememberLayout(key, G) {
  LAYOUTS.delete(key);
  LAYOUTS.set(key, placesOf(G));
  while (LAYOUTS.size > LAYOUTS_KEPT) LAYOUTS.delete(LAYOUTS.keys().next().value);
}
function packageHues(G, wanted) {
  const order = [];
  const walk = (n) => { if (!n.kids) { if (wanted.has(n.id)) order.push(n); return; } for (const k of n.kids) walk(k); };
  walk(G.root);
  const out = new Map();
  if (!order.length) return out;
  const ancestors = (n) => { const c = []; for (let x = n.up; x && x !== G.root; x = x.up) c.unshift(x); return c; };
  const step = (a, b) => {
    const ca = ancestors(a), cb = ancestors(b);
    let k = 0;
    while (k < ca.length && k < cb.length && ca[k] === cb[k]) k++;
    return 1 + 1.6 * (ca.length - k + cb.length - k) + (k === 0 && (ca.length || cb.length) ? 2.5 : 0);
  };
  const at = [0];
  for (let i = 1; i < order.length; i++) at.push(at[i - 1] + step(order[i - 1], order[i]));
  const around = at[at.length - 1] + step(order[order.length - 1], order[0]);
  order.forEach((n, i) => {
    const h = ((250 + (360 * at[i]) / around) % 360).toFixed(0), lift = i % 2 ? 0.05 : -0.03;
    out.set(n.id, `light-dark(oklch(${(0.6 + lift).toFixed(3)} 0.14 ${h}), oklch(${(0.74 + lift).toFixed(3)} 0.14 ${h}))`);
  });
  return out;
}
function edgeCardEl(links) {
  const ordered = [...links].sort((p, q) => q.atoms.length - p.atoms.length);
  const shown = ordered.slice(0, 3);
  return el('div', { class: 'edge-card' }, shown.map((link, i) => edgeCardSection(link, shown.length > 1 ? 6 : 12, i > 0)),
    ordered.length > shown.length ? el('div', { class: 'udim' }, `and ${ordered.length - shown.length} more ribbons here`) : null);
}
function edgeCardSection(link, limit, divided) {
  const rows = link.atoms.slice(0, limit);
  const kindsOf = (e) => [...e.kinds].sort((p, q) => KIND_ORDER.indexOf(p) - KIND_ORDER.indexOf(q));
  const atomLabel = (id, end) => { const home = moduleNodeOf(id); return home && home.id !== id && home.id !== end.id ? `${moduleFileName(home)} › ${netLabel(id)}` : netLabel(id); };
  return el('div', { class: `edge-card-section${divided ? ' divided' : ''}` },
    el('div', { class: 'edge-card-head' }, el('b', {}, `${netLabel(link.a.id)} → ${netLabel(link.b.id)}`), el('span', { class: 'udim' }, link.atoms.length === 1 ? '1 dependency' : `${link.atoms.length} dependencies`)),
    el('div', { class: 'edge-card-rows' }, rows.map((e) => [el('span', {}, atomLabel(e.from, link.a)), el('span', { class: 'udim' }, '→'), el('span', {}, atomLabel(e.to, link.b)), el('span', { class: 'edge-kind', style: `color:var(--rel-${kindsOf(e)[0]})` }, diffBadge(e.diff), kindsOf(e).join(' · '))])),
    link.atoms.length > rows.length ? el('div', { class: 'udim' }, `and ${link.atoms.length - rows.length} more`) : null);
}
