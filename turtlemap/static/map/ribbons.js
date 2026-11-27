import { anneal } from '../core/anneal.js';
import { countBelow, inversions } from '../core/crossings.js';
export const FOLDER_HEAD = 24;
const FOLDER_PAD = 10;
const FOLDER_SIDE = 9;
const BOX_GAP = 12;
const COLUMN_GAP = 76;
const LANE_GAP = 3;
const AREA = 500;
const STEPS_PER_BOX = 40;
const TIME_LIMIT = 2500;
export function layOutRibbons(G, previous) {
  if (!G.leaves.length) return { ribbons: [], backs: [], width: 0, height: 0 };
  const layout = new RibbonLayout(G);
  if (previous && G.leaves.every((n) => previous.has(n.id))) layout.restore(previous);
  else layout.optimise();
  return layout.draw();
}
export function placesOf(G) { return new Map([...G.leaves, ...G.folders].map((n) => [n.id, { wish: n.wish, rank: n.rank, lanes: n.laneWishes && new Map(n.laneWishes) }])); }
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
  return { root, leaves, folders, edges, maxDepth: Math.max(0, ...leaves.map((l) => l.depth)) };
}
class RibbonLayout {
  constructor(G) {
    this.G = G;
    const { rank, back } = rankLeaves(G.leaves, G.edges);
    this.rank = rank;
    this.post = [];
    const walkPost = (n) => { for (const k of n.kids) if (k.kids) walkPost(k); if (n !== G.root) this.post.push(n); };
    walkPost(G.root);
    for (const f of this.post) f.level = 1 + Math.max(0, ...f.kids.filter((k) => k.kids).map((k) => k.level));
    for (const n of [...G.leaves, ...G.folders]) n.wish = 0;
    for (const n of G.leaves) n.laneWishes = new Map();
    G.root.y = 0;
    this.ancestors = new Map(G.leaves.map((n) => { const chain = []; for (let f = n.up; f; f = f.up) chain.push(f); return [n, chain]; }));
    this.placeColumns();
    this.forward = G.edges.filter((e) => !back.has(e) && rank.get(e.t) > rank.get(e.s));
    this.backward = G.edges.filter((e) => !this.forward.includes(e));
    this.byTarget = groupBy(this.forward, (e) => e.t);
    this.into = groupBy(this.forward, (e) => e.t);
    this.outOf = groupBy(this.forward, (e) => e.s);
    this.neighbours = new Map(G.leaves.map((l) => [l, []]));
    for (const e of G.edges) { this.neighbours.get(e.s).push(e.t); this.neighbours.get(e.t).push(e.s); }
    this.score();
    this.commit();
  }
  placeColumns() {
    const { G, rank } = this;
    const used = [...new Set(G.leaves.map((n) => rank.get(n)))].sort((a, b) => a - b);
    const compact = new Map(used.map((r, i) => [r, i]));
    for (const n of G.leaves) rank.set(n, compact.get(rank.get(n)));
    this.colW = used.map(() => 0);
    for (const n of G.leaves) this.colW[rank.get(n)] = Math.max(this.colW[rank.get(n)], n.w);
    for (const f of this.post) f.span = [Math.min(...f.kids.map((k) => (k.kids ? k.span[0] : rank.get(k)))), Math.max(...f.kids.map((k) => (k.kids ? k.span[1] : rank.get(k))))];
    const ending = used.map(() => 0), starting = used.map(() => 0);
    for (const f of G.folders) { ending[f.span[1]] = Math.max(ending[f.span[1]], this.padOf(f)); starting[f.span[0]] = Math.max(starting[f.span[0]], this.padOf(f)); }
    this.colX = [starting[0]];
    for (let L = 1; L < used.length; L++) this.colX.push(this.colX[L - 1] + this.colW[L - 1] + ending[L - 1] + COLUMN_GAP + starting[L]);
    for (const n of G.leaves) { n.x = this.colX[rank.get(n)]; n.rank = rank.get(n); }
    this.lanesByHome = null;
    for (const f of G.folders) {
      const p = this.padOf(f);
      f.x = this.colX[f.span[0]] - p;
      f.w = Math.max(this.colX[f.span[1]] + this.colW[f.span[1]] + p - f.x, f.minW || 0);
    }
    this.width = this.colX[used.length - 1] + this.colW[used.length - 1] + ending[used.length - 1];
  }
  padOf(f) { return FOLDER_SIDE * f.level; }
  restore(previous) {
    for (const n of [...this.G.leaves, ...this.G.folders]) { const p = previous.get(n.id); if (!p) continue; n.wish = p.wish; if (p.lanes) n.laneWishes = new Map(p.lanes); if (!n.kids) this.rank.set(n, p.rank); }
    this.placeColumns();
  }
  columnRange(n) {
    const { rank } = this;
    const lo = Math.max(0, ...(this.into.get(n) || []).map((e) => rank.get(e.s) + 1));
    const hi = Math.min(this.colX.length - 1, ...(this.outOf.get(n) || []).map((e) => rank.get(e.t) - 1));
    return [lo, hi];
  }
  columnsOf() {
    const { rank, G } = this, cols = this.colX.map(() => ({ leaves: [], folders: [] }));
    for (const n of G.leaves) cols[rank.get(n)].leaves.push(n);
    for (const f of G.folders) for (let L = f.span[0]; L <= f.span[1]; L++) cols[L].folders.push(f);
    return cols;
  }
  spanOf(n) { return n.kids ? n.span : [this.rank.get(n), this.rank.get(n)]; }
  trunks() {
    const { rank } = this, trunks = [], lanes = new Map();
    for (const [t, es] of this.byTarget) {
      const rt = rank.get(t);
      const groups = groupBy(es, (e) => (rank.get(e.s) < rt - 1 ? this.homeOf([e.s, t]) : null));
      for (const [home, list] of groups) {
        const bySource = groupBy(list, (e) => rank.get(e.s));
        const trunk = { t, home, key: home === this.G.root ? '' : home?.id, bySource, first: Math.min(...bySource.keys()), w: list.reduce((sum, e) => sum + ribbonWidth(e.w), 0) };
        trunk.a = trunk.first + 1; trunk.b = rt - 1;
        if (home) pushTo(lanes, home, trunk);
        trunks.push(trunk);
      }
    }
    for (const list of lanes.values()) list.sort((p, q) => rank.get(p.t) - rank.get(q.t) || q.a - p.a || p.t.wish - q.t.wish);
    return { trunks, lanes };
  }
  homeOf(nodes) {
    let common = this.ancestors.get(nodes[0]);
    for (const n of nodes.slice(1)) { const mine = new Set(this.ancestors.get(n)); common = common.filter((f) => mine.has(f)); }
    return common[0];
  }
  pack(f, lanes) {
    const top = f === this.G.root ? 0 : FOLDER_HEAD + FOLDER_PAD, sky = new Map();
    const skyOver = ([a, b]) => { let y = top; for (let L = a; L <= b; L++) y = Math.max(y, sky.get(L) ?? top); return y; };
    const items = [...f.kids.map((k) => ({ k, wish: k.wish })), ...(lanes.get(f) || []).map((trunk) => ({ trunk, wish: trunk.t.laneWishes?.get(trunk.key) ?? Infinity }))];
    items.sort((p, q) => p.wish - q.wish);
    let bottom = top;
    for (const { k, trunk } of items) {
      if (trunk) {
        trunk.relTop = Math.max(trunk.t.laneWishes?.get(trunk.key) ?? -Infinity, skyOver([trunk.a, trunk.b]));
        for (let L = trunk.a; L <= trunk.b; L++) sky.set(L, trunk.relTop + trunk.w + LANE_GAP);
        bottom = Math.max(bottom, trunk.relTop + trunk.w);
        continue;
      }
      if (k.kids) this.pack(k, lanes);
      const span = this.spanOf(k);
      k.relY = Math.max(k.wish, skyOver(span));
      for (let L = span[0]; L <= span[1]; L++) sky.set(L, k.relY + k.h + BOX_GAP);
      bottom = Math.max(bottom, k.relY + k.h);
    }
    f.h = bottom + (f === this.G.root ? 0 : FOLDER_PAD);
  }
  settle(f, lanes) {
    for (const k of f.kids) { k.y = f.y + k.relY; if (k.kids) this.settle(k, lanes); }
    for (const trunk of lanes.get(f) || []) trunk.laneTop = f.y + trunk.relTop;
  }
  commit() {
    for (const n of [...this.G.leaves, ...this.G.folders]) n.wish = n.relY;
    for (const n of this.G.leaves) n.laneWishes = new Map();
    for (const trunk of this.lanes) trunk.t.laneWishes.set(trunk.key, trunk.relTop);
  }
  route() {
    if (!this.lanesByHome) Object.assign(this, (({ trunks, lanes }) => ({ allTrunks: trunks, lanesByHome: lanes }))(this.trunks()));
    const trunks = this.allTrunks, lanes = this.lanesByHome;
    this.lanes = [...lanes.values()].flat();
    this.pack(this.G.root, lanes);
    this.settle(this.G.root, lanes);
    const cols = this.columnsOf(), { rank } = this;
    for (const trunk of trunks) {
      trunk.stack = []; trunk.joins = new Map();
      for (let g = trunk.first; g < rank.get(trunk.t); g++) {
        const joiners = (trunk.bySource.get(g) || []).sort((a, b) => a.s.y - b.s.y);
        trunk.stack.unshift(...joiners);
        for (const e of joiners) trunk.joins.set(e, g);
      }
    }
    const ribbons = [];
    for (const trunk of trunks) ribbons.push(...this.trunkRibbons(trunk));
    this.arrive(ribbons);
    for (const [src, list] of groupBy(ribbons, (r) => r.e.s)) {
      list.sort((p, q) => p.ys[0] - q.ys[0]);
      const total = list.reduce((t, r) => t + r.w, 0), k = Math.min(1, (src.h - 2) / total);
      let y = src.y + src.h / 2 - (total * k) / 2;
      for (const r of list) { r.y0 = y + (r.w * k) / 2; r.w0 = r.w * k; y += r.w * k; }
    }
    return { ribbons, trunks, cols };
  }
  trunkRibbons(trunk) {
    const rt = this.rank.get(trunk.t), widths = new Map(trunk.stack.map((e) => [e, ribbonWidth(e.w)]));
    const after = new Map();
    let below = 0;
    for (let i = trunk.stack.length - 1; i >= 0; i--) { after.set(trunk.stack[i], below); below += widths.get(trunk.stack[i]); }
    return trunk.stack.map((e) => {
      const g0 = trunk.joins.get(e), ys = [];
      const lane = trunk.laneTop + trunk.w - after.get(e) - widths.get(e) / 2;
      for (let g = g0; g < rt - 1; g++) ys.push(lane);
      return { e, g0, ys, w: widths.get(e), w0: widths.get(e), tree: trunk.t };
    });
  }
  arrive(ribbons) {
    for (const [t, list] of groupBy(ribbons, (r) => r.e.t)) {
      const approach = (r) => (r.ys.length ? r.ys[r.ys.length - 1] : r.e.s.y + r.e.s.h / 2);
      list.sort((p, q) => approach(p) - approach(q));
      const total = list.reduce((sum, r) => sum + r.w, 0), k = Math.min(1, (t.h - 2) / total);
      let y = t.y + t.h / 2 - (total * k) / 2;
      for (const r of list) { r.ys.push(y + (r.w * k) / 2); r.w1 = r.w * k; y += r.w * k; }
    }
  }
  pointsOf(r) {
    const { colX, colW } = this;
    const pts = [[r.e.s.x + r.e.s.w, r.y0]];
    r.ys.forEach((y, k) => {
      const g = r.g0 + k;
      if (k === r.ys.length - 1) pts.push([r.e.t.x, y]);
      else pts.push([(colX[g] + colW[g] + colX[g + 1]) / 2, y], [colX[g + 1] - 4, y], [colX[g + 1] + colW[g + 1] + 4, y]);
    });
    return pts;
  }
  score() {
    const routed = this.route(), { G } = this;
    this.routed = routed;
    let ink = 0, crossings = 0, headers = 0, area = 0;
    const flat = this.colX.map(() => []), sloped = this.colX.map(() => []);
    for (const r of routed.ribbons) {
      ink += r.w * (r.e.t.x - r.e.s.x - r.e.s.w);
      let prev = r.y0;
      for (let k = 0; k < r.ys.length; k++) {
        const y = r.ys[k];
        ink += r.w * Math.abs(y - prev);
        if (Math.abs(y - prev) < 0.5) flat[r.g0 + k].push(y); else sloped[r.g0 + k].push({ a: prev, b: y, w: r.w });
        prev = y;
      }
    }
    const heads = this.colX.map(() => []);
    for (const f of G.folders) for (let g = f.span[0]; g < f.span[1]; g++) heads[g].push(f.y);
    flat.forEach((ys, g) => {
      const level = Float64Array.from(ys).sort();
      for (const top of heads[g]) headers += FOLDER_HEAD * (countBelow(level, top + FOLDER_HEAD) - countBelow(level, top + 1e-6));
      for (const S of sloped[g]) {
        const lo = Math.min(S.a, S.b), hi = Math.max(S.a, S.b);
        crossings += countBelow(level, hi) - countBelow(level, lo + 1e-6);
        for (const top of heads[g]) if (top + FOLDER_HEAD > lo && top < hi) headers += S.w * FOLDER_HEAD;
      }
      crossings += inversions(sloped[g]);
    });
    for (const f of G.folders) area += f.w * f.h;
    return ink / 100 + crossings * 3 + headers / 4 + area / AREA + (this.width * G.root.h) / AREA;
  }
  optimise() {
    const { G, rank } = this, leaves = G.leaves;
    const shift = (changes) => {
      const before = changes.map(([n]) => [n, n.wish]);
      for (const [n, dy] of changes) n.wish += dy;
      return () => { for (const [n, wish] of before) n.wish = wish; };
    };
    const sigma = (cooling) => 3 + 40 * cooling;
    this.score();
    this.settled = this.routed;
    anneal({
      score: () => this.score(),
      accepted: () => { this.commit(); this.settled = this.routed; },
      steps: STEPS_PER_BOX * leaves.length,
      limit: TIME_LIMIT,
      moves: [
        { weight: 0.2, apply: (random) => {
          const long = this.settled.trunks.filter((trunk) => trunk.laneTop !== undefined);
          if (!long.length) return null;
          const trunk = random.pick(long), t = trunk.t;
          return shift([[t, trunk.laneTop + trunk.w / 2 - (t.y + t.h / 2)]]);
        } },
        { weight: 0.2, apply: (random, cooling) => shift([[random.pick(leaves), random.gauss() * sigma(cooling)]]) },
        { weight: 0.15, apply: (random, cooling) => {
          if (!this.lanes.length) return null;
          const trunk = random.pick(this.lanes), t = trunk.t;
          const dy = random.next() < 0.5 ? t.y + t.h / 2 - trunk.laneTop - trunk.w / 2 : random.gauss() * sigma(cooling);
          const before = t.laneWishes.get(trunk.key);
          t.laneWishes.set(trunk.key, (before ?? trunk.relTop) + dy);
          return () => { if (before === undefined) t.laneWishes.delete(trunk.key); else t.laneWishes.set(trunk.key, before); };
        } },
        { weight: 0.2, apply: (random, cooling) => {
          const n = random.pick(leaves), o = this.neighbours.get(n);
          if (!o.length) return null;
          return shift([[n, o.reduce((t, m) => t + m.y + m.h / 2, 0) / o.length - n.y - n.h / 2 + random.gauss() * sigma(cooling) * 0.3]]);
        } },
        { weight: 0.15, apply: (random, cooling) => (G.folders.length ? shift([[random.pick(G.folders), random.gauss() * sigma(cooling)]]) : null) },
        { weight: 0.1, apply: (random) => {
          const n = random.pick([...leaves, ...G.folders]), peers = n.up.kids.filter((k) => k !== n && this.spanOf(k)[0] <= this.spanOf(n)[1] && this.spanOf(n)[0] <= this.spanOf(k)[1]);
          if (!peers.length) return null;
          const o = random.pick(peers), dy = o.wish - n.wish;
          return shift([[n, dy], [o, -dy]]);
        } },
        { weight: 0.15, apply: (random) => {
          const n = random.pick(leaves), [lo, hi] = this.columnRange(n), options = [];
          for (let r = lo - 0.5; r <= hi + 0.5; r += 0.5) if (r !== rank.get(n)) options.push(r);
          if (!options.length) return null;
          const before = new Map(rank);
          rank.set(n, random.pick(options));
          this.placeColumns();
          return () => { for (const [k, v] of before) rank.set(k, v); this.placeColumns(); };
        } },
      ],
    });
    this.score();
  }
  draw() {
    const g = this.route(), { rank, colX, colW, G } = this;
    const obs = g.cols.map((c) => [...c.leaves.map((n) => [n.y, n.y + n.h]), ...c.folders.map((f) => [f.y, f.y + FOLDER_HEAD])]);
    const ribbons = g.ribbons.map((rb) => {
      const pts = this.pointsOf(rb);
      const widthAt = (i) => (i === 0 ? rb.w0 : i === pts.length - 1 ? rb.w1 : rb.w);
      const top = pts.map(([x, y], i) => [x, y - widthAt(i) / 2]), bottom = pts.map(([x, y], i) => [x, y + widthAt(i) / 2]).reverse();
      return { d: `${smoothPath(top)} ${smoothPath(bottom).replace(/^M/, 'L')} Z`, centre: smoothPath(pts), w: rb.w, edge: rb.e, group: rb.tree };
    });
    const backs = this.backward.map((e) => {
      const a = rank.get(e.s), b = rank.get(e.t), low = Math.max(e.s.y + e.s.h, e.t.y + e.t.h) + 18;
      const pts = [[e.s.x + e.s.w, e.s.y + e.s.h / 2], [colX[a] + colW[a] + 18, (e.s.y + e.s.h / 2 + low) / 2]];
      for (let L = a; L >= b; L--) { const y = freeY(obs[L], low, 6); pts.push([colX[L] + colW[L] + 4, y], [colX[L] - 4, y]); }
      pts.push([colX[b] - 18, (e.t.y + e.t.h / 2 + low) / 2], [e.t.x, e.t.y + e.t.h / 2]);
      return { d: catmull(pts), edge: e };
    });
    const boxes = [...G.leaves, ...G.folders];
    const x0 = Math.min(...boxes.map((b) => b.x)), y0 = Math.min(...boxes.map((b) => b.y), ...g.trunks.map((t) => t.laneTop ?? Infinity));
    return { ribbons, backs, x0, y0, width: Math.max(...boxes.map((b) => b.x + b.w)) - x0, height: Math.max(...boxes.map((b) => b.y + b.h), ...g.trunks.filter((t) => t.laneTop !== undefined).map((t) => t.laneTop + t.w)) - y0 };
  }
}
function ribbonWidth(w) { return 0.9 + 1.1 * Math.log2(1 + w); }
function rankLeaves(leaves, edges) {
  const out = new Map(leaves.map((n) => [n, []]));
  for (const e of edges) out.get(e.s).push(e);
  const state = new Map(), back = new Set();
  const visit = (n) => { state.set(n, 1); for (const e of out.get(n)) { const s = state.get(e.t); if (s === 1) back.add(e); else if (!s) visit(e.t); } state.set(n, 2); };
  for (const n of leaves) if (!state.get(n)) visit(n);
  const fwd = edges.filter((e) => !back.has(e) && e.s !== e.t);
  const rank = new Map(leaves.map((n) => [n, 0]));
  for (let pass = 0; pass < leaves.length; pass++) {
    let changed = false;
    for (const e of fwd) if (rank.get(e.t) < rank.get(e.s) + 1) { rank.set(e.t, rank.get(e.s) + 1); changed = true; }
    if (!changed) break;
  }
  const preds = new Map(leaves.map((n) => [n, 0])), succ = new Map(leaves.map((n) => [n, []]));
  for (const e of fwd) { preds.set(e.t, preds.get(e.t) + 1); succ.get(e.s).push(e.t); }
  for (let pass = 0; pass < 3; pass++) for (const n of [...leaves].sort((a, b) => rank.get(b) - rank.get(a))) {
    if (!preds.get(n) && succ.get(n).length) rank.set(n, Math.min(...succ.get(n).map((t) => rank.get(t))) - 1);
  }
  const lo = Math.min(...rank.values());
  for (const n of leaves) rank.set(n, rank.get(n) - lo);
  return { rank, back };
}
function freeY(obstacles, ideal, margin) {
  const ivs = obstacles.map(([a, b]) => [a - margin, b + margin]).sort((p, q) => p[0] - q[0]);
  const merged = [];
  for (const iv of ivs) { if (merged.length && iv[0] <= merged[merged.length - 1][1]) merged[merged.length - 1][1] = Math.max(merged[merged.length - 1][1], iv[1]); else merged.push([...iv]); }
  for (const [a, b] of merged) if (ideal > a && ideal < b) return ideal - a < b - ideal ? a : b;
  return ideal;
}
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
function pushTo(map, key, value) { if (!map.has(key)) map.set(key, []); map.get(key).push(value); }
function groupBy(items, keyOf) {
  const out = new Map();
  for (const it of items) { const k = keyOf(it); if (!out.has(k)) out.set(k, []); out.get(k).push(it); }
  return out;
}
