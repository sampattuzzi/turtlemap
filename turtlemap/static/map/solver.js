import { offsetWithin } from './boxes.js';
const PAD_LEFT = 14;
const PAD_TOP = 10;
const PAD_RIGHT = 14;
const PAD_BOTTOM = 14;
const GAP = 12;
const STEPS = 6;
const BUDGET_MS = 1200;
const START_HEAT = 6;
const WEIGHTS = { length: 1 / 100, crossings: 4, through: 4 / 25, overlap: 10 / 300, area: 2 / 12000, headers: 4 / 25 };
const SOLVED = new Map();

export function solveMap(rootEl, links) {
  const map = readMap(rootEl, links);
  if (!map.leaves.length) return { bends: new Map(), links: map.links };
  const key = solveKey(map);
  const cached = SOLVED.get(key);
  if (cached) map.restore(cached);
  else {
    anneal(map);
    SOLVED.set(key, map.snapshot());
  }
  writeMap(map);
  return { bends: map.bends, links: map.links };
}

export function linkCurve(ra, rb, bend) {
  const ca = [ra.x + ra.w / 2, ra.y + ra.h / 2], cb = [rb.x + rb.w / 2, rb.y + rb.h / 2];
  const len = Math.hypot(cb[0] - ca[0], cb[1] - ca[1]) || 1, n = [-(cb[1] - ca[1]) / len, (cb[0] - ca[0]) / len];
  const [o1, o2] = bend || [0, 0];
  const along = (t, o) => [ca[0] + (cb[0] - ca[0]) * t + n[0] * o, ca[1] + (cb[1] - ca[1]) * t + n[1] * o];
  const c1 = along(1 / 3, o1 * 1.5), c2 = along(2 / 3, o2 * 1.5);
  const p0 = rim(ra, o1 ? c1 : cb), p3 = rim(rb, o2 ? c2 : ca);
  return { p0, c1, c2, p3, d: `M${p0} C${c1} ${c2} ${p3}` };
}

function readMap(rootEl, links) {
  const rectOf = (el) => { const o = offsetWithin(el, rootEl); return { x: o.x, y: o.y, w: el.offsetWidth, h: el.offsetHeight }; };
  const nodes = new Map();
  const visit = (el, parent) => {
    const id = el === rootEl ? 'root' : el.dataset.id;
    const inner = el.querySelector(':scope > .ninner');
    const open = Boolean(inner) && (el === rootEl || el.classList.contains('open'));
    const node = { id, el, parent, open, kids: [], ...rectOf(el) };
    if (open && el !== rootEl) {
      const head = el.querySelector(':scope > .nhead');
      const box = rectOf(el), innerBox = rectOf(inner);
      node.inner = inner;
      node.head = head ? head.offsetHeight : 0;
      node.headWidth = head ? head.scrollWidth : 0;
      node.offsetLeft = innerBox.x - box.x;
      node.offsetTop = innerBox.y - box.y;
      node.extraRight = box.x + box.w - (innerBox.x + innerBox.w);
      node.extraBottom = box.y + box.h - (innerBox.y + innerBox.h);
    }
    if (el === rootEl) Object.assign(node, { inner, head: 0, headWidth: 0, offsetLeft: 0, offsetTop: 0, extraRight: 0, extraBottom: 0 });
    nodes.set(id, node);
    if (parent) parent.kids.push(node);
    if (open) for (const kid of inner.children) if (kid.classList.contains('nb')) visit(kid, node);
  };
  visit(rootEl, null);
  const leaves = [...nodes.values()].filter((n) => !n.open);
  const folders = [...nodes.values()].filter((n) => n.open);
  const order = [];
  const post = (n) => { for (const k of n.kids) if (k.open) post(k); order.push(n); };
  post(nodes.get('root'));
  const pairs = new Map();
  for (const l of links) {
    if (!nodes.has(l.from) || !nodes.has(l.to) || l.from === l.to) continue;
    const a = nodes.get(l.from), b = nodes.get(l.to);
    if (encloses(a, b) || encloses(b, a)) continue;
    const key = `${l.from}|${l.to}`;
    if (!pairs.has(key)) pairs.set(key, { key, a, b, count: 0, kinds: new Set(), atoms: [] });
    const pair = pairs.get(key);
    pair.count += l.atoms ? l.atoms.length : 1;
    for (const e of l.atoms || []) { e.kinds.forEach((k) => pair.kinds.add(k)); pair.atoms.push(e); }
  }
  const bends = new Map();
  const map = {
    nodes, leaves, folders, order, links: [...pairs.values()], bends,
    snapshot: () => ({ at: leaves.map((n) => [n.id, n.x, n.y]), bends: [...bends] }),
    restore: (saved) => { for (const [id, x, y] of saved.at) { const n = nodes.get(id); if (n) { n.x = x; n.y = y; } } for (const [k, v] of saved.bends) bends.set(k, v); },
  };
  for (const n of leaves) n.pinnedX = n.el.classList.contains('leaf');
  return map;
}

function solveKey(map) {
  return `${map.leaves.map((n) => `${n.id}:${Math.round(n.w)}x${Math.round(n.h)}`).join(',')}#${map.links.map((l) => `${l.key}:${l.count}`).join(',')}`;
}

function fitFolders(map) {
  for (const n of map.order) {
    if (!n.kids.length) continue;
    const x0 = Math.min(...n.kids.map((k) => k.x)), y0 = Math.min(...n.kids.map((k) => k.y));
    const x1 = Math.max(...n.kids.map((k) => k.x + k.w)), y1 = Math.max(...n.kids.map((k) => k.y + k.h));
    n.contentW = x1 - x0 + PAD_LEFT + PAD_RIGHT;
    n.contentH = y1 - y0 + PAD_TOP + PAD_BOTTOM;
    n.x = x0 - PAD_LEFT - n.offsetLeft;
    n.y = y0 - PAD_TOP - n.offsetTop;
    n.w = Math.max(n.offsetLeft + n.contentW + n.extraRight, n.headWidth);
    n.h = n.offsetTop + n.contentH + n.extraBottom;
  }
}

function measure(map) {
  fitFolders(map);
  const m = { length: 0, crossings: 0, through: 0, overlap: 0, area: 0, headers: 0 };
  const curves = map.links.map((l) => sample(linkCurve(l.a, l.b, map.bends.get(l.key))));
  map.links.forEach((l, i) => { const P = curves[i].pts; for (let k = 0; k < STEPS; k++) m.length += l.weight * Math.hypot(P[k + 1][0] - P[k][0], P[k + 1][1] - P[k][1]); });
  for (let i = 0; i < map.links.length; i++) for (let j = i + 1; j < map.links.length; j++) {
    const p = map.links[i], q = map.links[j];
    if (p.a === q.a || p.a === q.b || p.b === q.a || p.b === q.b || !meet(curves[i].box, curves[j].box)) continue;
    const P = curves[i].pts, Q = curves[j].pts;
    for (let u = 0; u < STEPS; u++) for (let v = 0; v < STEPS; v++) if (crosses(P[u], P[u + 1], Q[v], Q[v + 1])) m.crossings++;
  }
  map.links.forEach((l, i) => {
    for (const n of map.leaves) {
      if (n === l.a || n === l.b) continue;
      const r = { x: n.x - 3, y: n.y - 3, w: n.w + 6, h: n.h + 6 };
      if (meet(curves[i].box, r)) m.through += alongInside(curves[i].pts, r);
    }
    for (const f of map.folders) {
      if (f.id === 'root' || encloses(f, l.a) || encloses(f, l.b)) continue;
      const strip = { x: f.x, y: f.y, w: f.w, h: f.head };
      if (meet(curves[i].box, strip)) m.headers += alongInside(curves[i].pts, strip);
    }
  });
  for (const f of map.folders) {
    for (let i = 0; i < f.kids.length; i++) for (let j = i + 1; j < f.kids.length; j++) m.overlap += overlapArea(f.kids[i], f.kids[j]);
    if (f.id !== 'root') m.area += f.w * f.h;
  }
  return m;
}

function cost(map) {
  const m = measure(map);
  return Object.keys(WEIGHTS).reduce((t, k) => t + WEIGHTS[k] * m[k], 0);
}

function anneal(map) {
  let seed = 1;
  for (const ch of map.leaves.map((n) => n.id).join('')) seed = (seed * 31 + ch.charCodeAt(0)) % 2147483647;
  const rand = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  const gauss = () => Math.sqrt(-2 * Math.log(rand() + 1e-9)) * Math.cos(2 * Math.PI * rand());
  for (const l of map.links) l.weight = Math.sqrt(l.count);
  const linked = new Map(map.leaves.map((n) => [n, []]));
  for (const l of map.links) { if (linked.has(l.a)) linked.get(l.a).push(l.b); if (linked.has(l.b)) linked.get(l.b).push(l.a); }
  const under = (f) => map.leaves.filter((n) => encloses(f, n));
  let current = cost(map);
  const start = performance.now();
  while (performance.now() - start < BUDGET_MS) {
    const heat = START_HEAT * (1 - (performance.now() - start) / BUDGET_MS) ** 2;
    const sigma = 4 + 60 * (heat / START_HEAT);
    const undo = [];
    const keep = (n) => undo.push([n, n.x, n.y]);
    const r = rand();
    if (r < 0.2 && map.links.length) {
      const l = map.links[Math.floor(rand() * map.links.length)], was = map.bends.get(l.key), [o1, o2] = was || [0, 0], pick = rand();
      map.bends.set(l.key, pick < 0.1 ? [0, 0] : pick < 0.4 ? [o1 + gauss() * sigma, o2] : pick < 0.7 ? [o1, o2 + gauss() * sigma] : [o1 + gauss() * sigma, o2 + gauss() * sigma]);
      undo.push(() => { if (was) map.bends.set(l.key, was); else map.bends.delete(l.key); });
    } else if (r < 0.32) {
      const n = map.leaves[Math.floor(rand() * map.leaves.length)], near = linked.get(n).filter((o) => o.parent === n.parent);
      if (!near.length) continue;
      keep(n);
      n.y = near.reduce((t, o) => t + o.y + o.h / 2, 0) / near.length - n.h / 2 + gauss() * sigma * 0.5;
    } else if (r < 0.82) {
      const n = map.leaves[Math.floor(rand() * map.leaves.length)];
      keep(n);
      if (!n.pinnedX) n.x += gauss() * sigma * 0.5;
      n.y += gauss() * sigma;
    } else if (r < 0.92) {
      const f = map.folders[Math.floor(rand() * map.folders.length)];
      if (f.id === 'root') continue;
      const dx = gauss() * sigma * 0.5, dy = gauss() * sigma;
      for (const n of under(f)) { keep(n); n.x += dx; n.y += dy; }
    } else {
      const n = map.leaves[Math.floor(rand() * map.leaves.length)], peers = map.leaves.filter((o) => o.parent === n.parent && o !== n);
      if (!peers.length) continue;
      const o = peers[Math.floor(rand() * peers.length)];
      keep(n); keep(o);
      const [ny, oy] = [n.y + n.h / 2, o.y + o.h / 2];
      n.y = oy - n.h / 2; o.y = ny - o.h / 2;
    }
    const next = cost(map), delta = next - current;
    if (delta <= 0 || (heat > 1e-3 && rand() < Math.exp(-delta / heat))) current = next;
    else for (const u of undo.reverse()) { if (typeof u === 'function') u(); else { const [n, x, y] = u; n.x = x; n.y = y; } }
  }
  fitFolders(map);
}

function writeMap(map) {
  fitFolders(map);
  const root = map.nodes.get('root');
  const place = (f, originX, originY) => {
    for (const k of f.kids) {
      k.el.style.left = `${k.x - originX}px`;
      k.el.style.top = `${k.y - originY}px`;
      if (k.open) place(k, k.x + k.offsetLeft, k.y + k.offsetTop);
    }
    if (f.inner) { f.inner.style.width = `${f.contentW}px`; f.inner.style.height = `${f.contentH}px`; }
  };
  const x0 = Math.min(...root.kids.map((k) => k.x)) - PAD_LEFT, y0 = Math.min(...root.kids.map((k) => k.y)) - PAD_TOP;
  place(root, x0, y0);
}

function sample({ p0, c1, c2, p3 }) {
  const pts = [];
  for (let k = 0; k <= STEPS; k++) { const t = k / STEPS, u = 1 - t; pts.push([0, 1].map((j) => u * u * u * p0[j] + 3 * u * u * t * c1[j] + 3 * u * t * t * c2[j] + t * t * t * p3[j])); }
  const xs = pts.map((q) => q[0]), ys = pts.map((q) => q[1]);
  return { pts, box: { x: Math.min(...xs), y: Math.min(...ys), w: Math.max(...xs) - Math.min(...xs), h: Math.max(...ys) - Math.min(...ys) } };
}

function rim(b, toward) {
  const cx = b.x + b.w / 2, cy = b.y + b.h / 2, dx = toward[0] - cx, dy = toward[1] - cy;
  const k = Math.min(Math.abs((b.w / 2 + 2) / (dx || 1e-9)), Math.abs((b.h / 2 + 2) / (dy || 1e-9)), 1);
  return [cx + dx * k, cy + dy * k];
}

function encloses(outer, inner) {
  for (let n = inner; n; n = n.parent) if (n === outer) return true;
  return false;
}

function meet(a, b) { return a.x <= b.x + b.w && b.x <= a.x + a.w && a.y <= b.y + b.h && b.y <= a.y + a.h; }

function overlapArea(a, b) {
  const w = Math.min(a.x + a.w + GAP, b.x + b.w + GAP) - Math.max(a.x, b.x), h = Math.min(a.y + a.h + GAP, b.y + b.h + GAP) - Math.max(a.y, b.y);
  return w > 0 && h > 0 ? w * h : 0;
}

function crosses(p, q, r, s) {
  const d = (a, b, c) => (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
  return d(r, s, p) * d(r, s, q) < 0 && d(p, q, r) * d(p, q, s) < 0;
}

function alongInside(pts, r) {
  let total = 0;
  for (let k = 0; k < pts.length - 1; k++) total += clipLength(pts[k], pts[k + 1], r);
  return total;
}

function clipLength(p, q, r) {
  let t0 = 0, t1 = 1;
  const dx = q[0] - p[0], dy = q[1] - p[1];
  for (const [pp, qq] of [[-dx, p[0] - r.x], [dx, r.x + r.w - p[0]], [-dy, p[1] - r.y], [dy, r.y + r.h - p[1]]]) {
    if (pp === 0) { if (qq < 0) return 0; continue; }
    const t = qq / pp;
    if (pp < 0) t0 = Math.max(t0, t); else t1 = Math.min(t1, t);
    if (t0 > t1) return 0;
  }
  return (t1 - t0) * Math.hypot(dx, dy);
}
