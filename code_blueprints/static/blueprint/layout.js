import { ARRANGED_LAYOUTS, arrangeLayers } from '../core/layout.js';
import { settings } from '../core/settings.js';
const BLUEPRINT_GAP_X = 56;
const BLUEPRINT_GAP_Y = 18;
export function layered(g, byId) {
  const rank = blueprintRanks(g);
  const { preds, succs, dummies, routes } = dummyRoutes(g, rank);
  const V = (n) => (n.dummy ? n : byId.get(n));
  const cols = [];
  for (const n of [...g.nodes, ...dummies]) { const r = n.dummy ? n.rank : rank.get(n); if (!cols[r]) cols[r] = []; cols[r].push(n); }
  const { colX, colW } = stackColumns(cols, byId, V);
  const entryV = byId.get(g.nodes.find((n) => n.kind === 'entry'));
  const lane = g.exec.length && entryV.pins.then ? entryV.pins.then.dy + 26 : -Infinity;
  const sweep = new ColumnSweep({ V, preds, succs, lane, hasExec: g.exec.length > 0 });
  for (let it = 0; it < 5; it++) { sweep.forward(cols); sweep.backward(cols); }
  sweep.forward(cols);
  if (ARRANGED_LAYOUTS.has(settings.layout)) arrangeBlueprintColumns(settings.layout, Array.from(cols, (col) => col || []), succs, { V, isExec: isExecNode, lane, gapY: BLUEPRINT_GAP_Y });
  for (const d of dummies) { d.x = colX[d.rank]; d.w = colW[d.rank]; }
  return { routes, dummies };
}
class ColumnSweep {
  constructor({ V, preds, succs, lane, hasExec }) {
    Object.assign(this, { V, preds, succs, lane, hasExec });
    this.middleOf = settings.layout === 'classic' ? meanOf : medianOf;
  }
  forward(cols) {
    for (const col of cols) {
      if (!col) continue;
      const t = new Map();
      for (const n of col) { const tp = this.targetFrom(n, this.linksInto(n), true); if (tp !== null) t.set(n, tp); }
      this.place(col, t);
    }
  }
  backward(cols) {
    for (let ci = cols.length - 1; ci >= 0; ci--) {
      const col = cols[ci];
      if (!col) continue;
      const t = new Map();
      for (const n of col) {
        const ts = isExecNode(n) && !n.dummy ? null : this.targetFrom(n, this.succs.get(n) || [], false);
        const tp = this.targetFrom(n, this.linksInto(n), true);
        const val = ts !== null && tp !== null ? (ts + tp) / 2 : ts ?? tp;
        if (val !== null) t.set(n, val);
      }
      this.place(col, t);
    }
  }
  linksInto(n) {
    const links = this.preds.get(n) || [];
    if (!isExecNode(n)) return links;
    const exec = links.filter((l) => l.exec);
    return exec.length ? exec : links;
  }
  targetFrom(n, list, fromPreds) {
    const V = this.V;
    const v = V(n);
    const vals = list.map((p) => { const o = V(p.n); const op = o.pins[fromPreds ? p.ak : p.bk], vp = v.pins[fromPreds ? p.bk : p.ak]; return op && vp ? o.y + op.dy - vp.dy : null; }).filter((t0) => t0 !== null);
    return vals.length ? this.middleOf(vals) : null;
  }
  place(col, targets) {
    const V = this.V;
    const key = (n) => (targets.get(n) ?? V(n).y) + (isExecNode(n) ? -1e6 : 0);
    col.sort((a, b) => key(a) - key(b));
    let prev = -Infinity;
    for (const n of col) {
      const v = V(n);
      const t0 = isExecNode(n) && this.hasExec ? Math.max(0, targets.get(n) ?? 0) : targets.get(n) ?? v.y;
      v.y = Math.max(t0, prev, isExecNode(n) ? -Infinity : this.lane);
      prev = v.y + v.h + (n.dummy ? 10 : BLUEPRINT_GAP_Y);
    }
  }
}
function blueprintRanks(g) {
  const realPreds = new Map(), realSuccs = new Map();
  for (const e of [...g.edges, ...g.exec]) { pushTo(realPreds, e.to, e.from); pushTo(realSuccs, e.from, e.to); }
  const rank = new Map();
  const rankOf = (n) => {
    if (rank.has(n)) return rank.get(n);
    rank.set(n, 0);
    const r = forwardRank(n, realPreds.get(n) || [], rankOf);
    rank.set(n, r);
    return r;
  };
  g.nodes.forEach((n) => rankOf(n));
  for (const n of g.nodes) if (rank.get(n) === null) rank.set(n, backwardRank(realSuccs.get(n) || [], rank));
  const maxR = Math.max(...rank.values());
  for (const n of g.nodes) if (n.kind === 'return' && !(realSuccs.get(n) || []).length) rank.set(n, maxR);
  return rank;
}
function forwardRank(n, preds, rankOf) {
  if (n.kind === 'entry') return 0;
  return preds.length ? 1 + Math.max(...preds.map((p) => rankOf(p) ?? 0)) : null;
}
function backwardRank(succs, rank) {
  return succs.length ? Math.max(1, Math.min(...succs.map((s) => rank.get(s) ?? 2)) - 1) : 1;
}
function dummyRoutes(g, rank) {
  const preds = new Map(), succs = new Map();
  const link = (a, b, ak, bk, exec) => { pushTo(preds, b, { n: a, ak, bk, exec }); pushTo(succs, a, { n: b, ak, bk, exec }); };
  const bundles = new Map();
  for (const e of blueprintLinks(g)) pushTo(bundles, `${e.from.id}|${e.fp}`, e);
  const dummies = [];
  const routes = new Map();
  for (const list of bundles.values()) {
    const src = list[0].from, r0 = rank.get(src), exec = list[0].exec;
    const far = Math.max(r0, ...list.map((e) => rank.get(e.to)));
    const chain = [];
    for (let r = r0 + 1; r < far; r++) {
      const d = { dummy: true, exec, rank: r, w: 0, h: 8, x: 0, y: 0, pins: { d: { dx: 0, dy: 4 } } };
      link(chain.length ? chain[chain.length - 1] : src, d, chain.length ? 'd' : list[0].fp, 'd', exec);
      chain.push(d); dummies.push(d);
    }
    for (const e of list) {
      const t = rank.get(e.to);
      const via = t > r0 + 1 ? chain.slice(0, t - r0 - 1) : [];
      routes.set(`${e.from.id}|${e.fp}|${e.to.id}|${e.tp}`, via);
      link(via.length ? via[via.length - 1] : src, e.to, via.length ? 'd' : e.fp, e.tp, exec);
    }
  }
  return { preds, succs, dummies, routes };
}
function blueprintLinks(g) {
  return [
    ...g.edges.map((e) => ({ from: e.from, fp: `out:${e.fp}`, to: e.to, tp: `in:${e.tp}`, exec: false })),
    ...g.exec.map((e) => ({ from: e.from, fp: e.fp, to: e.to, tp: 'exec-in', exec: true })),
  ];
}
function stackColumns(cols, byId, V) {
  const colX = [], colW = [];
  let x = 0;
  cols.forEach((col, r) => {
    if (!col) return;
    const real = col.filter((n) => !n.dummy);
    const w = real.length ? Math.max(...real.map((n) => byId.get(n).w)) : 24;
    colX[r] = x; colW[r] = w;
    for (const n of real) byId.get(n).x = x;
    x += w + BLUEPRINT_GAP_X;
  });
  for (const col of cols) { if (!col) continue; let y = 0; for (const n of col) { const v = V(n); v.y = y; y += v.h + BLUEPRINT_GAP_Y; } }
  return { colX, colW };
}
function isExecNode(n) { return n.dummy ? n.exec : Boolean(n.execIn || n.execOut || (n.execOuts && n.execOuts.length)); }
function pushTo(map, key, value) { if (!map.has(key)) map.set(key, []); map.get(key).push(value); }
function meanOf(vals) { return vals.reduce((a, b) => a + b, 0) / vals.length; }
function medianOf(vals) { return vals.sort((a, b) => a - b)[Math.floor((vals.length - 1) / 2)]; }
function arrangeBlueprintColumns(layout, columns, succs, { V, isExec, lane, gapY }) {
  const pinOf = (n, key) => { const p = V(n).pins[key]; return p ? p.dy : null; };
  const links = [];
  for (const [a, list] of succs) for (const s of list) { const pa = pinOf(a, s.ak), pb = pinOf(s.n, s.bk); if (pa !== null && pb !== null) links.push({ a, b: s.n, pa, pb, weight: s.exec ? 2 : 1, exec: s.exec }); }
  const placed = arrangeLayers(layout, columns, links, {
    height: (n) => V(n).h,
    gap: (n) => (n.dummy ? 10 : gapY),
    floor: (n) => (isExec(n) ? 0 : Math.max(0, lane)),
    pinned: (n) => n.kind === 'entry',
    isDummy: (n) => Boolean(n.dummy),
    candidates: (n, list, forwards) => { if (!isExec(n)) return list; const exec = list.filter((l) => l.exec); return forwards ? (exec.length ? exec : list) : n.dummy ? list : exec; },
    previous: new Map(columns.flat().map((n) => [n, V(n).y])),
  });
  if (placed) for (const [n, y] of placed) V(n).y = y;
}
