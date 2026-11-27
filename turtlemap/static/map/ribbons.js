export const FOLDER_HEAD = 24;
const FOLDER_PAD = 10;
const FOLDER_SIDE = 9;
const BOX_GAP = 12;
const COLUMN_GAP = 76;
const CELL = 90;
export function layOutRibbons(G, { budget, previous }) {
  if (!G.leaves.length) return { ribbons: [], backs: [], width: 0, height: 0 };
  const layout = new RibbonLayout(G);
  if (previous && G.leaves.every((n) => previous.has(n.id))) for (const n of G.leaves) n.y = previous.get(n.id);
  else layout.anneal(budget);
  return layout.draw();
}
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
    placeInBands(G, hierarchicalOrder(G), rank, this);
    this.post = [];
    const walkPost = (n) => { for (const k of n.kids) if (k.kids) walkPost(k); if (n !== G.root) this.post.push(n); };
    walkPost(G.root);
    this.forward = G.edges.filter((e) => !back.has(e) && rank.get(e.t) > rank.get(e.s));
    this.backward = G.edges.filter((e) => !this.forward.includes(e));
    this.byTarget = groupBy(this.forward, (e) => e.t);
    this.neighbours = new Map(G.leaves.map((l) => [l, []]));
    for (const e of G.edges) { this.neighbours.get(e.s).push(e.t); this.neighbours.get(e.t).push(e.s); }
  }
  depthPad(d) { return FOLDER_SIDE * (this.G.maxDepth - d + 1); }
  fitFolders() {
    const { colX, colW } = this;
    for (const f of this.post) {
      const top = Math.min(...f.kids.map((k) => k.y)), bottom = Math.max(...f.kids.map((k) => k.y + k.h));
      f.y = top - FOLDER_HEAD - FOLDER_PAD;
      f.h = bottom - top + FOLDER_HEAD + 2 * FOLDER_PAD;
      const p = this.depthPad(f.depth);
      f.x = colX[f.span[0]] - p;
      f.w = Math.max(colX[f.span[1]] + colW[f.span[1]] + p - f.x, f.minW || 0);
    }
  }
  obstacles() {
    const { rank, G } = this;
    return this.colX.map((_, L) => [...G.leaves.filter((n) => rank.get(n) === L).map((n) => [n.y, n.y + n.h]), ...G.folders.filter((f) => f.span[0] <= L && f.span[1] >= L).map((f) => [f.y, f.y + FOLDER_HEAD])]);
  }
  route() {
    this.fitFolders();
    const { rank, colX, colW, G } = this;
    const obs = this.obstacles();
    const trunks = [];
    for (const [t, es] of this.byTarget) {
      const rt = rank.get(t), yt = t.y + t.h / 2;
      const first = Math.min(...es.map((e) => rank.get(e.s)));
      const trunk = { t, runs: new Map(), joins: new Map(), stack: [], w: 0 };
      let y = null;
      for (let g = first; g < rt; g++) {
        const joiners = es.filter((e) => rank.get(e.s) === g).sort((a, b) => a.s.y - b.s.y);
        const width = trunk.w + joiners.reduce((s, e) => s + ribbonWidth(e.w), 0);
        let target = yt;
        if (g + 1 !== rt) {
          const weight = Math.max(1, joiners.reduce((s, e) => s + ribbonWidth(e.w), 0));
          const base = y === null ? joiners.reduce((s, e) => s + (e.s.y + e.s.h / 2) * ribbonWidth(e.w), 0) / weight : y;
          target = freeY(obs[g + 1], base + (yt - base) / (rt - g), width / 2 + 4);
        }
        trunk.stack.unshift(...joiners);
        for (const e of joiners) trunk.joins.set(e, g);
        trunk.w = width;
        trunk.runs.set(g + 1, target);
        y = target;
      }
      trunks.push(trunk);
    }
    this.sinkLanes(trunks);
    const ribbons = [];
    for (const trunk of trunks) ribbons.push(...this.trunkRibbons(trunk));
    for (const [s, list] of groupBy(ribbons, (r) => r.e.s)) {
      list.sort((p, q) => p.pts[1][1] - q.pts[1][1]);
      const total = list.reduce((t, r) => t + r.w, 0), k = Math.min(1, (s.h - 2) / total);
      let y = s.y + s.h / 2 - (total * k) / 2;
      for (const r of list) { r.pts[0] = [r.pts[0][0], y + (r.w * k) / 2]; r.w0 = r.w * k; y += r.w * k; }
    }
    return { ribbons, obs, trunks, colX, colW, G };
  }
  sinkLanes(trunks) {
    const { rank, colX, G } = this;
    const bottomOf = colX.map((_, L) => Math.max(...G.leaves.filter((n) => rank.get(n) === L).map((n) => n.y + n.h), ...G.folders.filter((f) => f.span[0] <= L && f.span[1] >= L).map((f) => f.y + f.h), -1e9) + 16);
    const long = trunks.map((trunk) => ({ trunk, inner: [...trunk.runs.keys()].filter((L) => L !== rank.get(trunk.t)) })).filter((x) => x.inner.length);
    for (const x of long) { x.a = Math.min(...x.inner); x.b = Math.max(...x.inner); }
    long.sort((p, q) => rank.get(p.trunk.t) - rank.get(q.trunk.t) || q.a - p.a || p.trunk.t.y - q.trunk.t.y);
    const placed = [];
    for (const x of long) {
      let top = Math.max(...x.inner.map((L) => bottomOf[L]));
      for (const o of placed) if (x.a <= o.b && o.a <= x.b) top = Math.max(top, o.top + o.trunk.w + 3);
      x.top = top;
      placed.push(x);
      x.trunk.laneTop = top;
      for (const L of x.inner) x.trunk.runs.set(L, top + x.trunk.w / 2);
    }
  }
  trunkRibbons(trunk) {
    const { rank, colX, colW } = this;
    const rt = rank.get(trunk.t), widths = new Map(trunk.stack.map((e) => [e, ribbonWidth(e.w)]));
    const gapMid = (g) => (colX[g] + colW[g] + colX[g + 1]) / 2;
    return trunk.stack.map((e) => {
      const g0 = trunk.joins.get(e), pts = [[e.s.x + e.s.w, e.s.y + e.s.h / 2]];
      let arrive = widths.get(e);
      for (let g = g0; g < rt; g++) {
        const members = trunk.stack.filter((m) => trunk.joins.get(m) <= g), total = members.reduce((s, m) => s + widths.get(m), 0);
        let off = -total / 2;
        for (const m of members) { if (m === e) break; off += widths.get(m); }
        off += widths.get(e) / 2;
        const yRun = trunk.runs.get(g + 1);
        if (g + 1 === rt) { const k = Math.min(1, (trunk.t.h - 2) / total); pts.push([trunk.t.x, yRun + off * k]); arrive = widths.get(e) * k; break; }
        let after = 0, past = false;
        for (const m of trunk.stack) { if (past) after += widths.get(m); if (m === e) past = true; }
        off = trunk.laneTop + trunk.w - after - widths.get(e) / 2 - yRun;
        pts.push([gapMid(g), yRun + off], [colX[g + 1] - 4, yRun + off], [colX[g + 1] + colW[g + 1] + 4, yRun + off]);
      }
      return { e, pts, w: widths.get(e), w0: widths.get(e), w1: arrive, tree: trunk.t };
    });
  }
  score() {
    const g = this.route(), { G } = this;
    let ink = 0, crossings = 0, through = 0, headers = 0, overlap = 0, area = 0;
    const grid = new Map(), parts = [];
    const add = (p, q, r) => {
      const id = parts.length;
      parts.push({ p, q, r });
      for (const k of cellsOf(Math.min(p[0], q[0]), Math.min(p[1], q[1]), Math.max(p[0], q[0]), Math.max(p[1], q[1]))) { if (!grid.has(k)) grid.set(k, []); grid.get(k).push(id); }
    };
    for (const r of g.ribbons) {
      const s = sampleSmooth(r.pts, 3);
      for (let k = 0; k < s.length - 1; k++) { add(s[k], s[k + 1], r); ink += r.w * Math.hypot(s[k + 1][0] - s[k][0], s[k + 1][1] - s[k][1]); }
    }
    for (const [k, ids] of grid) for (let i = 0; i < ids.length; i++) for (let j = i + 1; j < ids.length; j++) {
      const A = parts[ids[i]], B = parts[ids[j]];
      if (A.r.tree === B.r.tree || A.r.e.s === B.r.e.s || !cross(A.p, A.q, B.p, B.q)) continue;
      const at = crossingPoint(A, B);
      if (cellKey(at[0], at[1]) === k) crossings++;
    }
    const probe = (rc, weightOf) => {
      let total = 0;
      const seen = new Set();
      for (const k of cellsOf(rc.x, rc.y, rc.x + rc.w, rc.y + rc.h)) for (const id of grid.get(k) || []) {
        if (seen.has(id)) continue;
        seen.add(id);
        const P = parts[id], w = weightOf(P);
        if (w) total += w * clip(P.p, P.q, rc);
      }
      return total;
    };
    for (const m of G.leaves) through += probe({ x: m.x + 2, y: m.y + 2, w: m.w - 4, h: m.h - 4 }, (P) => (P.r.e.s === m || P.r.e.t === m ? 0 : P.r.w));
    for (const f of G.folders) headers += probe({ x: f.x, y: f.y, w: f.w, h: FOLDER_HEAD }, (P) => P.r.w);
    for (const f of [G.root, ...G.folders]) overlap += siblingOverlap(f.kids);
    for (const f of G.folders) area += f.w * f.h;
    return ink / 100 + crossings * 3 + through / 4 + headers / 4 + overlap / 2 + area / 4000;
  }
  anneal(budget) {
    const { G, rank } = this, leaves = G.leaves;
    let seed = 11;
    const rand = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
    const gauss = () => Math.sqrt(-2 * Math.log(rand() + 1e-9)) * Math.cos(2 * Math.PI * rand());
    const move = (n, dy, undo) => { if (!n.kids) { undo.push([n, n.y]); n.y += dy; } else for (const k of n.kids) move(k, dy, undo); };
    const pick = (list) => list[Math.floor(rand() * list.length)];
    let current = this.score();
    const start = performance.now(), T0 = Math.max(3, current * 0.003);
    while (performance.now() - start < budget) {
      const heat = T0 * (1 - (performance.now() - start) / budget) ** 2, sigma = 3 + 40 * (heat / T0);
      const undo = [], r = rand();
      if (r < 0.2) {
        const long = this.route().trunks.filter((trunk) => trunk.laneTop !== undefined);
        if (!long.length) continue;
        const trunk = pick(long), t = trunk.t, dy = trunk.laneTop + trunk.w / 2 - (t.y + t.h / 2);
        const below = leaves.filter((n) => n !== t && n.up === t.up && rank.get(n) === rank.get(t) && n.y > t.y);
        move(t, dy, undo);
        if (dy > 0) for (const n of below) move(n, dy, undo);
      } else if (r < 0.45) move(pick(leaves), gauss() * sigma, undo);
      else if (r < 0.65) {
        const n = pick(leaves), o = this.neighbours.get(n);
        if (!o.length) continue;
        move(n, o.reduce((t, m) => t + m.y, 0) / o.length - n.y + gauss() * sigma * 0.3, undo);
      } else if (r < 0.85) {
        if (!G.folders.length) continue;
        move(pick(G.folders), gauss() * sigma, undo);
      } else {
        const n = pick(leaves), peers = leaves.filter((k) => k !== n && rank.get(k) === rank.get(n) && k.up === n.up);
        if (!peers.length) continue;
        const o = pick(peers), dy = o.y - n.y;
        move(n, dy, undo);
        move(o, -dy, undo);
      }
      const next = this.score();
      if (next <= current || (heat > 1e-3 && rand() < Math.exp(-(next - current) / heat))) current = next;
      else for (const [n, y] of undo.reverse()) n.y = y;
    }
  }
  draw() {
    const g = this.route(), { rank, colX, colW, G } = this;
    const ribbons = g.ribbons.map((rb) => {
      const widthAt = (i) => (i === 0 ? rb.w0 : i === rb.pts.length - 1 ? rb.w1 : rb.w);
      const top = rb.pts.map(([x, y], i) => [x, y - widthAt(i) / 2]), bottom = rb.pts.map(([x, y], i) => [x, y + widthAt(i) / 2]).reverse();
      return { d: `${smoothPath(top)} ${smoothPath(bottom).replace(/^M/, 'L')} Z`, centre: smoothPath(rb.pts), samples: sampleSmooth(rb.pts), w: rb.w, edge: rb.e, group: rb.tree };
    });
    const backs = this.backward.map((e) => {
      const a = rank.get(e.s), b = rank.get(e.t), low = Math.max(e.s.y + e.s.h, e.t.y + e.t.h) + 18;
      const pts = [[e.s.x + e.s.w, e.s.y + e.s.h / 2], [colX[a] + colW[a] + 18, (e.s.y + e.s.h / 2 + low) / 2]];
      for (let L = a; L >= b; L--) { const y = freeY(g.obs[L], low, 6); pts.push([colX[L] + colW[L] + 4, y], [colX[L] - 4, y]); }
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
function hierarchicalOrder(G, iterations = 10) {
  const pos = new Map();
  const flatten = () => { let i = 0; const walk = (n) => { if (!n.kids) pos.set(n, i++); else for (const k of n.kids) walk(k); }; walk(G.root); };
  flatten();
  const nb = new Map(G.leaves.map((l) => [l, []]));
  for (const e of G.edges) { nb.get(e.s).push([e.t, e.w]); nb.get(e.t).push([e.s, e.w]); }
  for (let it = 0; it < iterations; it++) {
    const bary = new Map();
    for (const l of G.leaves) { const list = nb.get(l), tw = list.reduce((t, [, w]) => t + w, 0); bary.set(l, tw ? list.reduce((t, [o, w]) => t + pos.get(o) * w, 0) / tw : pos.get(l)); }
    const key = new Map();
    const compute = (n) => { if (!n.kids) { key.set(n, bary.get(n)); return [bary.get(n), 1]; } let s = 0, c = 0; for (const k of n.kids) { const [ks, kc] = compute(k); s += ks; c += kc; } key.set(n, c ? s / c : 0); return [s, c]; };
    compute(G.root);
    const sortKids = (n) => { if (!n.kids) return; n.kids.sort((a, b) => key.get(a) - key.get(b)); for (const k of n.kids) sortKids(k); };
    sortKids(G.root);
    flatten();
  }
  return pos;
}
function placeInBands(G, order, rank, into) {
  const layers = Math.max(0, ...G.leaves.map((n) => rank.get(n))) + 1;
  const colW = Array(layers).fill(0);
  for (const n of G.leaves) colW[rank.get(n)] = Math.max(colW[rank.get(n)], n.w);
  const colX = [];
  let x = 0;
  for (let i = 0; i < layers; i++) { colX.push(x); x += (colW[i] || 40) + COLUMN_GAP + 2 * FOLDER_SIDE * G.maxDepth; }
  const minPos = (n) => (!n.kids ? order.get(n) : Math.min(...n.kids.map(minPos)));
  const pack = (f) => {
    f.kids.sort((a, b) => minPos(a) - minPos(b));
    const sky = new Map(), y0 = f === G.root ? 0 : FOLDER_HEAD + FOLDER_PAD;
    let lo = Infinity, hi = -Infinity;
    for (const k of f.kids) {
      let span;
      if (!k.kids) span = [rank.get(k), rank.get(k)]; else { pack(k); span = k.span; }
      let y = y0;
      for (let L = span[0]; L <= span[1]; L++) y = Math.max(y, sky.get(L) ?? y0);
      k.relY = y;
      for (let L = span[0]; L <= span[1]; L++) sky.set(L, y + k.h + BOX_GAP);
      lo = Math.min(lo, span[0]); hi = Math.max(hi, span[1]);
    }
    f.span = [lo, hi];
    f.h = Math.max(y0, ...sky.values()) - BOX_GAP + (f === G.root ? 0 : FOLDER_PAD);
  };
  pack(G.root);
  const place = (f, y) => {
    for (const k of f.kids) {
      k.y = y + k.relY;
      if (!k.kids) k.x = colX[rank.get(k)]; else place(k, k.y);
    }
  };
  place(G.root, 0);
  Object.assign(into, { colX, colW });
}
function freeY(obstacles, ideal, margin) {
  const ivs = obstacles.map(([a, b]) => [a - margin, b + margin]).sort((p, q) => p[0] - q[0]);
  const merged = [];
  for (const iv of ivs) { if (merged.length && iv[0] <= merged[merged.length - 1][1]) merged[merged.length - 1][1] = Math.max(merged[merged.length - 1][1], iv[1]); else merged.push([...iv]); }
  for (const [a, b] of merged) if (ideal > a && ideal < b) return ideal - a < b - ideal ? a : b;
  return ideal;
}
function siblingOverlap(kids) {
  let total = 0;
  for (let i = 0; i < kids.length; i++) for (let j = i + 1; j < kids.length; j++) {
    const a = kids[i], b = kids[j];
    const ox = Math.min(a.x + a.w + BOX_GAP, b.x + b.w + BOX_GAP) - Math.max(a.x, b.x), oy = Math.min(a.y + a.h + BOX_GAP, b.y + b.h + BOX_GAP) - Math.max(a.y, b.y);
    if (ox > 0 && oy > 0) total += ox * oy;
  }
  return total;
}
const round = (v) => Math.round(v * 10) / 10;
function cellKey(x, y) { return Math.floor(x / CELL) * 100003 + Math.floor(y / CELL); }
function cellsOf(x0, y0, x1, y1) {
  const keys = [];
  for (let x = Math.floor(x0 / CELL); x <= Math.floor(x1 / CELL); x++) for (let y = Math.floor(y0 / CELL); y <= Math.floor(y1 / CELL); y++) keys.push(x * 100003 + y);
  return keys;
}
function crossingPoint(A, B) {
  const den = (A.p[0] - A.q[0]) * (B.p[1] - B.q[1]) - (A.p[1] - A.q[1]) * (B.p[0] - B.q[0]);
  const t = ((A.p[0] - B.p[0]) * (B.p[1] - B.q[1]) - (A.p[1] - B.p[1]) * (B.p[0] - B.q[0])) / den;
  return [A.p[0] + t * (A.q[0] - A.p[0]), A.p[1] + t * (A.q[1] - A.p[1])];
}
function cross(p, q, r, s) {
  const d = (a, b, c) => (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
  return d(r, s, p) * d(r, s, q) < 0 && d(p, q, r) * d(p, q, s) < 0;
}
function clip(p, q, r) {
  let t0 = 0, t1 = 1;
  const dx = q[0] - p[0], dy = q[1] - p[1];
  for (const [num, den] of [[p[0] - r.x, -dx], [r.x + r.w - p[0], dx], [p[1] - r.y, -dy], [r.y + r.h - p[1], dy]]) {
    if (den === 0) { if (num < 0) return 0; continue; }
    const t = num / den;
    if (den < 0) t0 = Math.max(t0, t); else t1 = Math.min(t1, t);
  }
  return t1 > t0 ? (t1 - t0) * Math.hypot(dx, dy) : 0;
}
const bezier = (p0, c1, c2, p3, t) => { const u = 1 - t; return [0, 1].map((j) => u * u * u * p0[j] + 3 * u * u * t * c1[j] + 3 * u * t * t * c2[j] + t * t * t * p3[j]); };
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
function sampleSmooth(pts, per = 6) {
  const out = [pts[0]];
  for (let i = 0; i < pts.length - 1; i++) {
    const [a, b] = [pts[i], pts[i + 1]], m = (a[0] + b[0]) / 2;
    if (Math.abs(a[1] - b[1]) < 0.5) { out.push(b); continue; }
    for (let k = 1; k <= per; k++) out.push(bezier(a, [m, a[1]], [m, b[1]], b, k / per));
  }
  return out;
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
function groupBy(items, keyOf) {
  const out = new Map();
  for (const it of items) { const k = keyOf(it); if (!out.has(k)) out.set(k, []); out.get(k).push(it); }
  return out;
}
