import { Scene, loopBackPath, messageScene, routedPath } from '../canvas/scene.js';
import { net } from '../core/data.js';
import { el, svg } from '../core/dom.js';
import { NET_COLUMNS, NET_ROUTES, NET_SLACK, layoutNet, moduleFileName, moduleNodeOf, netBoxEl } from './boxes.js';
import { DATA_LIMIT, dataGroups, dataModel } from './datamodel.js';
const DATA_END_WORDS = { one: 'one', optional: 'zero or one', many: 'many' };
const DATA_MARKERS = {
  one: '<path d="M16,1 V15 M11,1 V15"/>',
  optional: '<circle cx="8" cy="8" r="4"/><path d="M16,1 V15"/>',
  many: '<circle cx="6" cy="8" r="4"/><path d="M12,8 L24,1 M12,8 L24,8 M12,8 L24,15"/>',
};
const BASE_MARKER = '<marker id="er-base" viewBox="0 0 14 14" refX="13" refY="7" markerWidth="14" markerHeight="14" markerUnits="userSpaceOnUse" orient="auto"><path d="M1,1 L13,7 L1,13 z" style="fill:var(--canvas);stroke:var(--rel-inherits)" stroke-width="1.6"/></marker>';

export function buildDataScene(ctx, scope = 'root') {
  const model = dataModel(net(), scope);
  if (model.core > DATA_LIMIT) return messageScene(`${model.core} data classes are too many to draw at once. Pick a package or module in the list above the view.`);
  if (!model.classes.length) return messageScene('No dataclasses, models or enums were found here.');
  const scene = new Scene(ctx);
  const rootEl = el('div', { class: 'nroot data-root', 'data-id': 'root' });
  const inner = el('div', { class: 'ninner' });
  const open = new Set(model.classes.map((n) => n.id));
  rootEl.append(inner);
  const rootV = scene.add(rootEl);
  NET_ROUTES.clear(); NET_SLACK.clear(); NET_COLUMNS.clear();
  const boxOf = (n) => dataBox(n, open, ctx);
  packPieces(inner, dataGroups(model).map((group, i) => placeGroup(inner, group, i, model, boxOf)));
  scene.measure();
  scene.finish(40);
  const { rects, sizes } = measureBoxes(rootEl, rootV);
  scene.svg.append(dataMarkers());
  const routeOffset = (route) => offsetSum(route.inner, rootEl, rootV.x, rootV.y);
  const drawn = model.links.map((link) => drawDataLink(scene, link, rects, routeOffset));
  const middles = drawn.map((d) => d.path.getPointAtLength(d.path.getTotalLength() / 2));
  drawn.forEach((d, i) => { d.text.setAttribute('x', middles[i].x); d.text.setAttribute('y', middles[i].y - 6); });
  highlightOnHover(scene, model, drawn);
  scene.sizes = sizes;
  scene.netRects = rects;
  scene.effective = open;
  return scene;
}

function dataBox(n, open, ctx) {
  const box = netBoxEl(n, open, ctx);
  if (n.outside) box.classList.add('outside');
  const module = moduleNodeOf(n.id);
  const head = box.querySelector(':scope > .nhead');
  if (module && head) head.append(el('span', { class: 'nsub' }, moduleFileName(module)));
  return box;
}

function placeGroup(inner, group, i, model, boxOf) {
  if (group.length === 1 && !model.links.some((l) => l.from === group[0].id || l.to === group[0].id)) {
    const box = boxOf(group[0]);
    inner.append(box);
    return box;
  }
  const groupRoot = { id: `group:${i}`, kind: 'root', name: 'group', depth: 0, children: group, parent: null };
  for (const n of group) n.parent = groupRoot;
  const groupInner = el('div', { class: 'ninner' }, group.map(boxOf));
  const groupEl = el('div', { class: 'nroot data-group', 'data-id': groupRoot.id }, groupInner);
  inner.append(groupEl);
  const members = new Set(group.map((n) => n.id));
  layoutNet(groupRoot, groupEl, model.links.filter((l) => l.from !== l.to && members.has(l.from) && members.has(l.to)), model);
  return groupEl;
}

function measureBoxes(rootEl, rootV) {
  const rects = new Map();
  const sizes = [];
  rootEl.querySelectorAll('.nb').forEach((b) => {
    const { x, y } = offsetSum(b, rootEl, 0, 0);
    const head = b.querySelector(':scope > .nhead');
    rects.set(b.dataset.id, { x: rootV.x + x, y: rootV.y + y, w: b.offsetWidth, h: b.offsetHeight, anchorY: head ? head.offsetHeight / 2 : b.offsetHeight / 2, el: b });
    sizes.push({ el: b, w: b.offsetWidth, h: b.offsetHeight });
  });
  return { rects, sizes };
}

function offsetSum(start, stop, x, y) {
  for (let cur = start; cur && cur !== stop; cur = cur.offsetParent) { x += cur.offsetLeft; y += cur.offsetTop; }
  return { x, y };
}

function dataMarkers() {
  const defs = svg('defs');
  defs.innerHTML = Object.entries(DATA_MARKERS).map(([end, shape]) => `<marker id="er-${end}" class="er-marker" viewBox="0 0 24 16" refX="24" refY="8" markerWidth="24" markerHeight="16" markerUnits="userSpaceOnUse" orient="auto-start-reverse">${shape}</marker>`).join('') + BASE_MARKER;
  return defs;
}

function highlightOnHover(scene, model, drawn) {
  const light = (id) => {
    scene.el.classList.toggle('has-hot', Boolean(id));
    for (const d of drawn) {
      const hot = Boolean(id) && (d.link.from === id || d.link.to === id);
      d.path.classList.toggle('hot', hot);
      d.text.classList.toggle('hot', hot);
    }
  };
  scene.el.addEventListener('mouseover', (e) => {
    const box = e.target.closest('.nb');
    light(box ? model.chain(box.dataset.id)[1].id : null);
  });
  scene.el.addEventListener('mouseleave', () => { scene.el.classList.remove('has-hot'); for (const d of drawn) { d.path.classList.remove('hot'); d.text.classList.remove('hot'); } });
}

function packPieces(inner, pieces) {
  const GAP = 48, PAD = 14;
  const sized = pieces.map((el) => ({ el, w: el.offsetWidth + GAP, h: el.offsetHeight + GAP }));
  const area = sized.reduce((sum, p) => sum + p.w * p.h, 0);
  const width = Math.max(1400, Math.sqrt(area * 1.3), ...sized.map((p) => p.w));
  let skyline = [{ x: 0, w: width, y: 0 }];
  for (const piece of [...sized].sort((p, q) => q.h - p.h || q.w - p.w)) {
    const best = lowestFit(skyline, piece.w, width);
    piece.el.style.left = `${PAD + best.x}px`;
    piece.el.style.top = `${PAD + best.y}px`;
    skyline = raiseSkyline(skyline, best.x, piece.w, best.y + piece.h);
  }
  inner.style.width = `${Math.max(...sized.map((p) => p.el.offsetLeft + p.el.offsetWidth)) + PAD}px`;
  inner.style.height = `${Math.max(...sized.map((p) => p.el.offsetTop + p.el.offsetHeight)) + PAD}px`;
}

function lowestFit(skyline, w, width) {
  let best = null;
  for (const start of skyline) {
    if (start.x + w > width) break;
    const y = Math.max(...skyline.filter((s) => s.x < start.x + w && s.x + s.w > start.x).map((s) => s.y));
    if (!best || y < best.y) best = { x: start.x, y };
  }
  return best;
}

function raiseSkyline(skyline, x, w, y) {
  const next = [];
  for (const s of skyline) {
    if (s.x + s.w <= x || s.x >= x + w) { next.push(s); continue; }
    if (s.x < x) next.push({ x: s.x, w: x - s.x, y: s.y });
    if (s.x + s.w > x + w) next.push({ x: x + w, w: s.x + s.w - x - w, y: s.y });
  }
  next.push({ x, w, y });
  next.sort((p, q) => p.x - q.x);
  const merged = [];
  for (const s of next) {
    const last = merged[merged.length - 1];
    if (last && last.y === s.y && last.x + last.w === s.x) last.w += s.w; else merged.push({ ...s });
  }
  return merged;
}

function drawDataLink(scene, link, rects, routeOffset) {
  const path = svg('path', { d: dataLinkPath(link, rects, routeOffset), class: link.base ? 'rel er-base' : 'rel er-link' });
  if (link.base) path.setAttribute('marker-end', 'url(#er-base)');
  else { path.setAttribute('marker-start', `url(#er-${link.fromEnd})`); path.setAttribute('marker-end', `url(#er-${link.toEnd})`); }
  const text = svg('text', { class: `rel-label ${link.base ? 'k-inherits' : 'k-has'}`, 'text-anchor': 'middle' });
  text.textContent = dataLinkLabel(link);
  scene.svg.append(path, text);
  return { link, path, text };
}

function dataLinkLabel(link) {
  if (link.base) return 'inherits';
  const fields = link.toField ? `${link.fromField.name} ⇄ ${link.toField.name}` : link.fromField.name;
  return `${fields} · ${DATA_END_WORDS[link.fromEnd]} to ${DATA_END_WORDS[link.toEnd]}`;
}

function dataLinkPath(link, rects, routeOffset) {
  const ra = rects.get(link.from), rb = rects.get(link.to);
  const ya = fieldY(link.fromField, rects, ra), yb = fieldY(link.toField, rects, rb);
  if (link.from === link.to) {
    const x = ra.x + ra.w + 2;
    return `M${x},${ya} C${x + 70},${ya} ${x + 70},${yb} ${x},${yb}`;
  }
  const spans = routeSpans(NET_ROUTES.get(`${link.from}|${link.to}`), routeOffset);
  const x1 = ra.x + ra.w, out = x1 + (NET_SLACK.get(link.from) || 0);
  if (rb.x >= x1) return forwardPath(x1, out, ya, rb.x - 2, yb, spans);
  const left = Math.min(ra.x, rb.x);
  return loopBackPath(x1, ya, rb.x - 2, yb, spans.length ? spans : [{ x: left, w: out - left, y: Math.min(ra.y, rb.y) - 12 }]);
}

function fieldY(field, rects, box) {
  const at = field ? rects.get(field.id) : null;
  return at ? at.y + at.h / 2 : box.y + box.anchorY;
}

function routeSpans(route, routeOffset) {
  if (!route) return [];
  const at = routeOffset(route);
  return route.via.map((v) => ({ x: at.x + v.x, y: at.y + v.y + 3, w: v.w }));
}

function forwardPath(x1, out, ya, x2, yb, spans) {
  const dx = Math.max(50, (x2 - out) * 0.45);
  const curve = spans.length ? routedPath(out, ya, x2, yb, spans, 50) : `M${out},${ya} C${out + dx},${ya} ${x2 - dx},${yb} ${x2},${yb}`;
  return out > x1 + 1 ? `M${x1},${ya} L${curve.slice(1)}` : curve;
}
