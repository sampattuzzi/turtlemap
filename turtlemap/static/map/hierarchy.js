export const FOLDER_HEAD = 24;
const FOLDER_PAD = 10;
const FOLDER_SIDE = 10;
const PORT_ROOM = 24;
const BACK_ROOM = 18;
const BOX_GAP = 12;
const DUMMY_GAP = 4;
const RIBBON_GAP = 2;
const COLUMN_GAP = 64;
const SWEEPS = 4;
const PER_COLUMN = 2;
const IN = { border: 'in' };
const OUT = { border: 'out' };
export function ribbonGraph(root, edges) {
  const leaves = [], folders = [];
  const walk = (n, depth) => {
    n.depth = depth;
    for (const k of n.kids) {
      k.up = n;
      if (k.kids) { folders.push(k); walk(k, depth + 1); } else { k.depth = depth + 1; leaves.push(k); }
    }
  };
  walk(root, 0);
  return { root, leaves, folders, edges };
}
export function layOutRibbons(G) {
  if (!G.leaves.length) return { ribbons: [], backs: [], width: 0, height: 0 };
  return new Hierarchy(G).result();
}
class Hierarchy {
  constructor(G) {
    this.G = G;
    this.levels = new Map([G.root, ...G.folders].map((f) => [f, { local: [], outs: [], ins: [] }]));
    this.wires = G.edges.filter((e) => e.s !== e.t).map((e) => this.wireOf(e));
    for (const f of [G.root, ...G.folders]) this.rank(f);
    for (const wire of this.wires) if (!wire.back) this.thread(wire);
    const post = [];
    const walk = (f) => { for (const k of f.kids) if (k.kids) walk(k); post.push(f); };
    walk(G.root);
    for (const f of post) this.arrange(f);
    G.root.x = 0;
    G.root.y = 0;
    this.settle(G.root);
  }
  wireOf(e) {
    const up = (n) => { const chain = []; for (let f = n.up; f; f = f.up) chain.push(f); return chain; };
    const fromS = up(e.s), fromT = new Set(up(e.t));
    const lca = fromS.find((f) => fromT.has(f));
    const wire = { e, w: ribbonWidth(e.w), lca, outward: fromS.slice(0, fromS.indexOf(lca)), inward: up(e.t).slice(0, up(e.t).indexOf(lca)).reverse(), path: new Map() };
    wire.a = wire.outward.length ? wire.outward[wire.outward.length - 1] : e.s;
    wire.b = wire.inward.length ? wire.inward[0] : e.t;
    this.levels.get(lca).local.push(wire);
    return wire;
  }
  thread(wire) {
    for (const f of wire.outward) this.levels.get(f).outs.push(wire);
    for (const f of wire.inward) this.levels.get(f).ins.push(wire);
  }
  rank(f) {
    const level = this.levels.get(f), units = f.kids;
    const place = new Map(units.map((u, i) => [u, i]));
    const targets = new Map(units.map((u) => [u, new Set()]));
    for (const wire of level.local) targets.get(wire.a).add(wire.b);
    const out = new Map([...targets].map(([u, vs]) => [u, [...vs].sort((p, q) => place.get(p) - place.get(q))]));
    const state = new Map(), back = new Set();
    const visit = (u) => {
      state.set(u, 1);
      for (const v of out.get(u)) { if (state.get(v) === 1) back.add(`${u.id}|${v.id}`); else if (!state.get(v)) visit(v); }
      state.set(u, 2);
    };
    for (const u of units) if (!state.get(u)) visit(u);
    const forward = [];
    for (const [u, vs] of out) for (const v of vs) if (u !== v && !back.has(`${u.id}|${v.id}`)) forward.push([u, v]);
    const rank = new Map(units.map((u) => [u, 1]));
    for (let pass = 0; pass < units.length; pass++) {
      let changed = false;
      for (const [u, v] of forward) if (rank.get(v) < rank.get(u) + 1) { rank.set(v, rank.get(u) + 1); changed = true; }
      if (!changed) break;
    }
    const preds = new Set(forward.map(([, v]) => v));
    for (const u of [...units].sort((p, q) => rank.get(q) - rank.get(p))) {
      const next = forward.filter(([p]) => p === u).map(([, v]) => rank.get(v));
      if (!preds.has(u) && next.length) rank.set(u, Math.min(...next) - 1);
    }
    const leading = new Set(forward.map(([u]) => u));
    const used = [...new Set(units.filter((u) => leading.has(u)).map((u) => rank.get(u)))].sort((p, q) => p - q);
    for (const u of units) if (leading.has(u)) rank.set(u, used.indexOf(rank.get(u)) + 1);
    const lowest = new Map(units.map((u) => [u, 1 + Math.max(0, ...forward.filter(([, v]) => v === u).map(([p]) => rank.get(p)))]));
    level.rank = rank;
    level.columns = this.spread(units.filter((u) => leading.has(u)), units.filter((u) => !leading.has(u)), lowest, rank, used.length);
    for (const wire of level.local) wire.back = rank.get(wire.a) >= rank.get(wire.b);
    level.backs = level.local.filter((wire) => wire.back);
  }
  spread(fixed, free, lowest, rank, columns) {
    const filled = Array.from({ length: columns + 1 }, () => 0);
    for (const u of fixed) filled[rank.get(u)] += 1;
    const tallest = Math.max(Math.ceil(Math.sqrt((fixed.length + free.length) * PER_COLUMN)), ...filled);
    let k = columns;
    for (const u of free) {
      let c = filled.findIndex((count, i) => i >= lowest.get(u) && count < tallest);
      if (c < 0) { k += 1; filled.push(0); c = k; }
      rank.set(u, c);
      filled[c] += 1;
    }
    return k;
  }
  arrange(f) {
    const level = this.levels.get(f), { rank } = level, k = level.columns;
    const rankOf = (n) => (n === IN ? 0 : n === OUT ? k + 1 : n.dummy ? n.rank : rank.get(n));
    const forward = [...level.local.filter((wire) => !wire.back), ...level.outs, ...level.ins];
    const ins = new Set(level.ins), outs = new Set(level.outs);
    const ends = (wire) => [ins.has(wire) ? IN : this.unitIn(f, wire.e.s), outs.has(wire) ? OUT : this.unitIn(f, wire.e.t)];
    const chains = new Map();
    for (const wire of forward) {
      const [a, b] = ends(wire);
      if (!chains.has(wire.e.t)) chains.set(wire.e.t, new Map());
      const chain = chains.get(wire.e.t), path = [a];
      for (let c = rankOf(a) + 1; c < rankOf(b); c++) {
        if (!chain.has(c)) chain.set(c, { dummy: true, rank: c, wires: [], w: 0, h: 0, x: 0, y: 0 });
        const d = chain.get(c);
        d.wires.push(wire);
        d.h += wire.w;
        path.push(d);
      }
      path.push(b);
      wire.path.set(f, path);
    }
    const cols = Array.from({ length: k + 1 }, () => []);
    for (const u of f.kids) cols[rank.get(u)].push(u);
    for (const chain of chains.values()) for (const d of chain.values()) cols[d.rank].push(d);
    const pairs = new Map();
    const link = (p, q, wire) => { if (p.border || q.border) return; pushTo(pairs, p, { n: q, wire, forward: true }); pushTo(pairs, q, { n: p, wire, forward: false }); };
    for (const wire of forward) { const path = wire.path.get(f); for (let i = 0; i + 1 < path.length; i++) link(path[i], path[i + 1], wire); }
    const skeleton = this.skeleton(f, forward, outs, k);
    this.order(skeleton.cols, skeleton.pairs);
    const leafAt = new Map(this.G.leaves.map((leaf, i) => [leaf, i]));
    const slot = new Map(skeleton.cols.flatMap((col) => col.map((n, i) => [n, i])));
    const keyOf = (n) => [slot.get(n.dummy ? skeleton.of.get(n) : n), n.dummy ? leafAt.get(n.wires[0].e.t) : 0];
    for (const col of cols) col.sort((p, q) => { const [a, b] = [keyOf(p), keyOf(q)]; return a[0] - b[0] || a[1] - b[1]; });
    this.place(f, cols, pairs);
    this.stack(f, cols, forward);
    this.size(f, level, cols);
  }
  skeleton(f, forward, outs, k) {
    const place = new Map(f.kids.map((u, i) => [u, i]));
    const keyOf = (wire) => (outs.has(wire) ? OUT : this.unitIn(f, wire.e.t));
    const lanes = new Map(), of = new Map();
    for (const wire of forward) {
      const key = keyOf(wire);
      if (!lanes.has(key)) lanes.set(key, new Map());
      const lane = lanes.get(key);
      for (const d of wire.path.get(f)) {
        if (!d.dummy || of.has(d)) continue;
        if (!lane.has(d.rank)) lane.set(d.rank, { dummy: true, rank: d.rank, key: key === OUT ? f.kids.length : place.get(key) });
        of.set(d, lane.get(d.rank));
      }
    }
    const cols = Array.from({ length: k + 1 }, () => []);
    for (const u of f.kids) cols[this.levels.get(f).rank.get(u)].push(u);
    for (const lane of lanes.values()) for (const d of lane.values()) cols[d.rank].push(d);
    for (const col of cols) col.sort((p, q) => (p.dummy ? p.key + 1e6 : place.get(p)) - (q.dummy ? q.key + 1e6 : place.get(q)));
    const seen = new Map(), pairs = new Map();
    const node = (n) => (n.dummy ? of.get(n) : n);
    for (const wire of forward) {
      const path = wire.path.get(f).map(node);
      for (let i = 0; i + 1 < path.length; i++) {
        const [p, q] = [path[i], path[i + 1]];
        if (p.border || q.border) continue;
        if (!seen.has(p)) seen.set(p, new Set());
        if (seen.get(p).has(q)) continue;
        seen.get(p).add(q);
        pushTo(pairs, p, { n: q, forward: true });
        pushTo(pairs, q, { n: p, forward: false });
      }
    }
    return { cols, pairs, of };
  }
  unitIn(f, n) { let x = n; while (x.up !== f) x = x.up; return x; }
  order(cols, pairs) {
    const index = new Map();
    const reindex = (col) => col.forEach((n, i) => index.set(n, i));
    for (const col of cols) reindex(col);
    const sweep = (col, forward) => {
      const key = new Map(col.map((n) => {
        const near = (pairs.get(n) || []).filter((l) => l.forward !== forward).map((l) => index.get(l.n)).filter((i) => i !== undefined);
        return [n, near.length ? near.reduce((s, i) => s + i, 0) / near.length : index.get(n)];
      }));
      col.sort((p, q) => key.get(p) - key.get(q));
      reindex(col);
    };
    for (let i = 0; i < SWEEPS; i++) {
      for (let c = 2; c < cols.length; c++) sweep(cols[c], true);
      for (let c = cols.length - 2; c >= 1; c--) sweep(cols[c], false);
    }
  }
  place(f, cols, pairs) {
    const pinOut = (n, wire) => (n.kids ? n.outPort.get(wire) : n.h / 2);
    const pinIn = (n, wire) => (n.kids ? n.inPort.get(wire) : n.h / 2);
    const pack = (col, want) => {
      let off = 0;
      const items = col.map((n) => { const it = { n, off, target: (want.get(n) ?? n.y) - off, weight: want.has(n) ? 1 : 0.01 }; off += n.h + (n.dummy ? DUMMY_GAP : BOX_GAP); return it; });
      for (const [block, z] of nearestInOrder(items)) for (const it of block) it.n.y = z + it.off;
    };
    for (const col of cols) { let y = 0; for (const n of col) { n.y = y; y += n.h + (n.dummy ? DUMMY_GAP : BOX_GAP); } }
    const pass = (c, both) => {
      const want = new Map();
      for (const n of cols[c]) {
        const near = (pairs.get(n) || []).filter((l) => both || l.forward === false).map((l) => (l.forward ? l.n.y + pinIn(l.n, l.wire) - pinOut(n, l.wire) : l.n.y + pinOut(l.n, l.wire) - pinIn(n, l.wire)));
        if (near.length) want.set(n, median(near));
      }
      pack(cols[c], want);
    };
    for (let i = 0; i < SWEEPS; i++) {
      for (let c = 1; c < cols.length; c++) pass(c, false);
      for (let c = cols.length - 1; c >= 1; c--) pass(c, true);
    }
    for (let c = 1; c < cols.length; c++) pass(c, false);
    const wired = cols.flat().filter((n) => pairs.has(n));
    const highest = wired.length ? Math.min(...wired.map((n) => n.y)) : 0;
    for (const col of cols) if (col.some((n) => !pairs.has(n))) pack(col, new Map(col.map((n) => [n, pairs.has(n) ? n.y : highest])));
    const top = Math.min(...cols.flat().map((n) => n.y));
    for (const n of cols.flat()) n.y -= top;
  }
  stack(f, cols, forward) {
    const level = this.levels.get(f);
    level.colX = [];
    level.colW = [];
    let x = FOLDER_SIDE + (level.ins.length ? PORT_ROOM : 0);
    for (let c = 1; c < cols.length; c++) {
      level.colX[c] = x;
      level.colW[c] = Math.max(0, ...cols[c].filter((n) => !n.dummy).map((n) => n.w));
      for (const n of cols[c]) { n.x = x; if (n.dummy) n.w = level.colW[c]; }
      x += level.colW[c] + COLUMN_GAP;
    }
    level.right = x - COLUMN_GAP + FOLDER_SIDE + (level.outs.length ? PORT_ROOM : 0);
    const pinAt = (n, wire, side) => {
      if (n.dummy) return n.offset ? n.offset.get(wire) : n.h / 2;
      if (n.kids) return side === 'out' ? n.outPort.get(wire) : n.inPort.get(wire);
      return (side === 'out' ? n.outAt : n.inAt)?.get(wire)?.y ?? n.h / 2;
    };
    const yAt = (n, wire, side) => n.y + pinAt(n, wire, side);
    for (const u of f.kids.filter((n) => !n.kids)) {
      const leaving = forward.filter((wire) => wire.path.get(f)[0] === u), arriving = forward.filter((wire) => { const path = wire.path.get(f); return path[path.length - 1] === u; });
      u.outAt = stackOn(u, leaving, (wire) => { const n = wire.path.get(f)[1]; return n.border ? u.y : n.y + pinAt(n, wire, 'in'); }, RIBBON_GAP);
      u.inAt = stackOn(u, arriving, (wire) => { const path = wire.path.get(f), n = path[path.length - 2]; return n.border ? u.y : n.y + pinAt(n, wire, 'out'); }, 0);
    }
    for (let c = 1; c < cols.length; c++) {
      for (const d of cols[c].filter((n) => n.dummy)) {
        const before = (wire) => { const path = wire.path.get(f), p = path[path.indexOf(d) - 1]; return p.border ? d.y : yAt(p, wire, 'out'); };
        d.wires.sort((p, q) => before(p) - before(q));
        d.offset = new Map();
        let y = 0;
        for (const wire of d.wires) { d.offset.set(wire, y + wire.w / 2); y += wire.w; }
      }
    }
    level.yAt = yAt;
    level.forward = forward;
  }
  size(f, level, cols) {
    const top = f === this.G.root ? 0 : FOLDER_HEAD + FOLDER_PAD;
    const bottom = Math.max(0, ...cols.flat().map((n) => n.y + n.h)) + (level.backs.length ? BACK_ROOM : 0);
    for (const u of f.kids) { u.rx = u.x; u.ry = top + u.y; }
    for (const col of cols) for (const n of col) if (n.dummy) { n.rx = n.x; n.ry = top + n.y; }
    f.w = Math.max(level.right, f.minW || 0);
    f.h = top + bottom + (f === this.G.root ? 0 : FOLDER_PAD);
    if (f === this.G.root) return;
    f.inPort = new Map();
    f.outPort = new Map();
    for (const wire of level.ins) { const path = wire.path.get(f); f.inPort.set(wire, top + level.yAt(path[1], wire, 'in')); }
    for (const wire of level.outs) { const path = wire.path.get(f); f.outPort.set(wire, top + level.yAt(path[path.length - 2], wire, 'out')); }
  }
  settle(f) {
    for (const u of f.kids) { u.x = f.x + u.rx; u.y = f.y + u.ry; if (u.kids) this.settle(u); }
    const level = this.levels.get(f);
    for (const wire of level.forward) for (const n of wire.path.get(f)) if (n.dummy) { n.ax = f.x + n.rx; n.ay = f.y + n.ry; }
  }
  result() {
    const drawn = this.wires.filter((wire) => !wire.back).map((wire) => this.draw(this.ribbon(wire)));
    const backs = this.wires.filter((wire) => wire.back).map((wire) => this.loop(wire));
    const { root } = this.G;
    return { ribbons: drawn, backs, x0: 0, y0: 0, width: root.w, height: root.h };
  }
  ribbon(wire) {
    const points = [];
    const through = (f) => {
      for (const n of wire.path.get(f)) {
        if (!n.dummy) continue;
        const y = n.ay + n.offset.get(wire);
        points.push([n.ax - 4, y], [n.ax + n.w + 4, y]);
      }
    };
    for (const f of wire.outward) { through(f); points.push([f.x + f.w, f.y + f.outPort.get(wire)]); }
    through(wire.lca);
    for (const f of wire.inward) { points.push([f.x, f.y + f.inPort.get(wire)]); through(f); }
    const { s, t } = wire.e, start = s.outAt.get(wire), end = t.inAt.get(wire);
    return { wire, points, start: { y: s.y + start.y, w: start.w }, end: { y: t.y + end.y, w: end.w } };
  }
  draw({ wire, points, start, end }) {
    const { s, t } = wire.e;
    const pts = [[s.x + s.w, start.y], ...points, [t.x, end.y]];
    const widthAt = (i) => (i === 0 ? start.w : i === pts.length - 1 ? end.w : wire.w);
    const top = pts.map(([x, y], i) => [x, y - widthAt(i) / 2]), bottom = pts.map(([x, y], i) => [x, y + widthAt(i) / 2]).reverse();
    return { d: `${smoothPath(top)} ${smoothPath(bottom).replace(/^M/, 'L')} Z`, centre: smoothPath(pts), w: wire.w, edge: wire.e, group: t };
  }
  loop(wire) {
    const { s, t } = wire.e, ys = s.y + s.h / 2, yt = t.y + t.h / 2, drop = Math.max(s.y + s.h, t.y + t.h) + 10;
    const pts = [[s.x + s.w, ys], [s.x + s.w + 16, (ys + drop) / 2], [s.x + s.w, drop], [t.x, drop], [t.x - 16, (yt + drop) / 2], [t.x, yt]];
    return { d: catmull(pts), edge: wire.e };
  }
}
function stackOn(leaf, wires, keyOf, gap) {
  const at = new Map(), sorted = [...wires].sort((p, q) => keyOf(p) - keyOf(q));
  const between = sorted.length > 1 ? gap * (sorted.length - 1) : 0, total = sorted.reduce((sum, wire) => sum + wire.w, 0) + between;
  const k = Math.min(1, (leaf.h - 2) / total);
  let y = leaf.h / 2 - (total * k) / 2;
  for (const wire of sorted) { at.set(wire, { y: y + (wire.w * k) / 2, w: wire.w * k }); y += (wire.w + gap) * k; }
  return at;
}
function nearestInOrder(items) {
  const blocks = [];
  for (const it of items) {
    blocks.push({ items: [it], sum: it.target * it.weight, weight: it.weight });
    while (blocks.length > 1) {
      const last = blocks[blocks.length - 1], prev = blocks[blocks.length - 2];
      if (prev.sum / prev.weight < last.sum / last.weight) break;
      blocks.pop();
      prev.items.push(...last.items);
      prev.sum += last.sum;
      prev.weight += last.weight;
    }
  }
  return blocks.map((b) => [b.items, b.sum / b.weight]);
}
function ribbonWidth(w) { return 0.9 + 1.1 * Math.log2(1 + w); }
function median(values) {
  const sorted = [...values].sort((a, b) => a - b), mid = sorted.length >> 1;
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}
function pushTo(map, key, value) { if (!map.has(key)) map.set(key, []); map.get(key).push(value); }
const round = (v) => Math.round(v * 10) / 10;
function smoothPath(pts) {
  let d = `M${round(pts[0][0])},${round(pts[0][1])}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const [a, b] = [pts[i], pts[i + 1]];
    if (Math.abs(a[1] - b[1]) < 0.5) { d += ` L${round(b[0])},${round(b[1])}`; continue; }
    const m = (a[0] + b[0]) / 2;
    d += ` C${round(m)},${round(a[1])} ${round(m)},${round(b[1])} ${round(b[0])},${round(b[1])}`;
  }
  return d;
}
function catmull(pts) {
  let d = `M${round(pts[0][0])},${round(pts[0][1])}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[Math.max(0, i - 1)], p1 = pts[i], p2 = pts[i + 1], p3 = pts[Math.min(pts.length - 1, i + 2)];
    const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6], c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
    d += ` C${round(c1[0])},${round(c1[1])} ${round(c2[0])},${round(c2[1])} ${round(p2[0])},${round(p2[1])}`;
  }
  return d;
}
