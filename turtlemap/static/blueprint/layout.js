import { anneal } from '../core/anneal.js';
import { inversions } from '../core/crossings.js';
const GAP_X = 56;
const GAP_Y = 18;
const DUMMY_GAP = 10;
const STEPS_PER_ITEM = 50;
const TIME_LIMIT = 600;
const BEND = 40;
const CROSSING = 50;
const DETOUR = 30;
const SIZE = 0.4;
const DUMMY_PINS = { d: { dx: 0, dy: 4 } };
const LAYOUTS = new Map();
const LAYOUTS_KEPT = 60;
export function layered(g, byId) {
  const layout = new BlueprintLayout(g, byId);
  const key = layoutKey(g);
  if (LAYOUTS.has(key)) layout.restore(LAYOUTS.get(key)); else layout.optimise();
  LAYOUTS.delete(key);
  LAYOUTS.set(key, layout.places());
  while (LAYOUTS.size > LAYOUTS_KEPT) LAYOUTS.delete(LAYOUTS.keys().next().value);
  return layout.result();
}
class BlueprintLayout {
  constructor(g, byId) {
    Object.assign(this, { g, byId });
    this.V = (n) => (n.dummy ? n : byId.get(n));
    this.rank = blueprintRanks(g);
    this.into = new Map();
    this.outOf = new Map();
    for (const e of [...g.edges, ...g.exec]) { pushTo(this.into, e.to, e.from); pushTo(this.outOf, e.from, e.to); }
    const entry = g.nodes.find((n) => n.kind === 'entry');
    const then = entry && byId.get(entry).pins.then;
    this.hasExec = g.exec.length > 0;
    this.lane = this.hasExec && then ? then.dy + 26 : -Infinity;
    this.wish = new Map(g.nodes.map((n) => [n, 0]));
    this.bundles = [...groupBy(blueprintLinks(g), (e) => `${e.from.id}|${e.fp}`)].map(([key, list]) => ({ key, list, src: list[0].from, pin: list[0].fp, exec: list[0].exec }));
    this.build();
    this.place();
    this.commit();
  }
  keyOf(n) { return n.dummy ? n.key : n; }
  rankOf(n) { return n.dummy ? n.rank : this.rank.get(n); }
  wishOf(n) { return this.wish.get(this.keyOf(n)); }
  pinY(n, pin) { const p = this.V(n).pins[pin]; return p ? p.dy : null; }
  build() {
    const used = [...new Set(this.rank.values())].sort((a, b) => a - b);
    const compact = new Map(used.map((r, i) => [r, i]));
    for (const [n, r] of this.rank) this.rank.set(n, compact.get(r));
    const { preds, succs, dummies, routes } = dummyRoutes(this.bundles, this.rank);
    Object.assign(this, { preds, succs, dummies, routes });
    for (const d of dummies) if (!this.wish.has(d.key)) this.wish.set(d.key, this.wishOf(d.from) + (this.pinY(d.from, d.fromPin) ?? 0) - 4);
    this.cols = [];
    for (const n of [...this.g.nodes, ...dummies]) { const r = this.rankOf(n); if (!this.cols[r]) this.cols[r] = []; this.cols[r].push(n); }
    this.colX = []; this.colW = [];
    let x = 0;
    this.cols.forEach((col, r) => {
      const real = col.filter((n) => !n.dummy);
      this.colW[r] = real.length ? Math.max(...real.map((n) => this.V(n).w)) : 24;
      this.colX[r] = x;
      for (const n of real) this.V(n).x = x;
      x += this.colW[r] + GAP_X;
    });
    this.width = x;
    this.items = [...this.g.nodes.filter((n) => n.kind !== 'entry'), ...dummies];
    this.stacks = this.cols.map((col) => (col || []).map((n) => ({ n, v: this.V(n), key: this.keyOf(n), exec: isExecNode(n), fixed: n.kind === 'entry', gap: n.dummy ? DUMMY_GAP : GAP_Y, floor: isExecNode(n) ? (this.hasExec ? 0 : -Infinity) : this.lane })));
    this.gaps = this.cols.map(() => []);
    for (const [a, list] of succs) {
      if (a.overhead) continue;
      for (const s of list) {
        const pa = this.pinY(a, s.ak), pb = this.pinY(s.n, s.bk);
        if (pa !== null && pb !== null) this.gaps[this.rankOf(a)].push({ va: this.V(a), vb: this.V(s.n), pa, pb, w: s.exec ? 2 : 1, a: 0, b: 0 });
      }
    }
  }
  place() {
    for (const stack of this.stacks) {
      for (const item of stack) item.wish = this.wish.get(item.key);
      stack.sort((p, q) => Number(q.exec) - Number(p.exec) || p.wish - q.wish);
      let prev = -Infinity;
      for (const item of stack) {
        item.v.y = item.fixed ? 0 : Math.max(item.wish, prev, item.floor);
        prev = item.v.y + item.v.h + item.gap;
      }
    }
  }
  commit() { for (const stack of this.stacks) for (const item of stack) this.wish.set(item.key, item.v.y); }
  score() {
    this.place();
    let travel = 0, bends = 0, crossings = 0, top = Infinity, bottom = -Infinity;
    for (const gap of this.gaps) {
      for (const link of gap) {
        link.a = link.va.y + link.pa;
        link.b = link.vb.y + link.pb;
        const t = Math.abs(link.a - link.b);
        travel += link.w * t;
        if (t >= 0.5) bends += link.w;
      }
      crossings += inversions(gap);
    }
    for (const stack of this.stacks) if (stack.length) { const last = stack[stack.length - 1].v; top = Math.min(top, stack[0].v.y); bottom = Math.max(bottom, last.y + last.h); }
    return travel + BEND * bends + CROSSING * crossings + DETOUR * this.dummies.length + SIZE * (bottom - top + this.width);
  }
  optimise() {
    const setWishes = (changes) => {
      const before = changes.map(([k]) => [k, this.wish.get(k)]);
      for (const [k, y] of changes) this.wish.set(k, y);
      return () => { for (const [k, y] of before) this.wish.set(k, y); };
    };
    const sigma = (cooling) => 4 + 60 * cooling;
    const linksOf = (n) => [...(this.preds.get(n) || []).map((p) => ({ other: p.n, mine: p.bk, theirs: p.ak })), ...(this.succs.get(n) || []).map((s) => ({ other: s.n, mine: s.ak, theirs: s.bk }))];
    anneal({
      score: () => this.score(),
      accepted: () => this.commit(),
      steps: STEPS_PER_ITEM * this.items.length,
      limit: TIME_LIMIT,
      moves: [
        { weight: 0.25, apply: (random, cooling) => {
          if (!this.items.length) return null;
          const n = random.pick(this.items);
          return setWishes([[this.keyOf(n), this.wishOf(n) + random.gauss() * sigma(cooling)]]);
        } },
        { weight: 0.25, apply: (random) => {
          if (!this.items.length) return null;
          const n = random.pick(this.items), links = linksOf(n).filter((l) => !l.other.overhead);
          if (!links.length) return null;
          const l = random.pick(links), theirs = this.pinY(l.other, l.theirs), mine = this.pinY(n, l.mine);
          if (theirs === null || mine === null) return null;
          return setWishes([[this.keyOf(n), this.wishOf(l.other) + theirs - mine]]);
        } },
        { weight: 0.1, apply: (random) => {
          if (!this.items.length) return null;
          const n = random.pick(this.items), peers = this.cols[this.rankOf(n)].filter((m) => m !== n && m.kind !== 'entry' && isExecNode(m) === isExecNode(n));
          if (!peers.length) return null;
          const m = random.pick(peers);
          return setWishes([[this.keyOf(n), this.wishOf(m)], [this.keyOf(m), this.wishOf(n)]]);
        } },
        { weight: 0.1, apply: (random, cooling) => {
          if (!this.items.length) return null;
          const n = random.pick(this.items), from = this.wishOf(n), dy = random.gauss() * sigma(cooling);
          return setWishes(this.cols[this.rankOf(n)].filter((m) => m.kind !== 'entry' && this.wishOf(m) >= from).map((m) => [this.keyOf(m), this.wishOf(m) + dy]));
        } },
        { weight: 0.1, apply: (random) => {
          if (!this.dummies.length) return null;
          const d = random.pick(this.dummies), pin = this.pinY(d.from, d.fromPin);
          if (pin === null) return null;
          return setWishes(this.dummies.filter((o) => o.bundle === d.bundle).map((o) => [o.key, this.wishOf(d.from) + pin - 4]));
        } },
        { weight: 0.05, apply: (random) => {
          const movable = this.g.nodes.filter((n) => n.kind !== 'entry' && !n.overhead);
          if (!movable.length) return null;
          const n = random.pick(movable);
          const lo = Math.max(1, ...(this.into.get(n) || []).map((p) => this.rank.get(p) + 1));
          const hi = Math.min(this.cols.length - 1, ...(this.outOf.get(n) || []).map((s) => this.rank.get(s) - 1));
          const options = [];
          for (let r = lo - 0.5; r <= hi + 0.5; r += 0.5) if (r !== this.rank.get(n) && r > 0) options.push(r);
          if (!options.length) return null;
          const before = new Map(this.rank);
          this.rank.set(n, random.pick(options));
          this.build();
          return () => { for (const [k, r] of before) this.rank.set(k, r); this.build(); };
        } },
      ],
    });
    this.place();
  }
  places() {
    const out = new Map();
    for (const n of this.g.nodes) out.set(n.id, { rank: this.rank.get(n), y: this.wishOf(n) });
    for (const d of this.dummies) out.set(d.key, { y: this.wishOf(d) });
    return out;
  }
  restore(known) {
    for (const n of this.g.nodes) { const p = known.get(n.id); if (p) { this.rank.set(n, p.rank); this.wish.set(n, p.y); } }
    for (const [key, p] of known) if (p.rank === undefined) this.wish.set(key, p.y);
    this.build();
    this.place();
  }
  result() {
    for (const d of this.dummies) { d.x = this.colX[d.rank]; d.w = this.colW[d.rank]; }
    return { routes: this.routes, dummies: this.dummies };
  }
}
function layoutKey(g) {
  const nodes = g.nodes.map((n) => `${n.id}:${n.kind}`).join(' ');
  const edges = g.edges.map((e) => `${e.from.id}.${e.fp}>${e.to.id}.${e.tp}`).join(' ');
  const exec = g.exec.map((e) => `${e.from.id}.${e.fp}>${e.to.id}`).join(' ');
  return `${nodes}#${edges}#${exec}`;
}
function blueprintRanks(g) {
  const realPreds = new Map(), realSuccs = new Map();
  for (const e of [...g.edges, ...g.exec]) { pushTo(realPreds, e.to, e.from); pushTo(realSuccs, e.from, e.to); }
  const rank = new Map();
  const placedByUse = (n) => n.kind === 'closure' && (realSuccs.get(n) || []).length > 0;
  const rankOf = (n) => {
    if (rank.has(n)) return rank.get(n);
    rank.set(n, 0);
    const r = placedByUse(n) ? null : forwardRank(n, realPreds.get(n) || [], rankOf);
    rank.set(n, r);
    return r;
  };
  g.nodes.forEach((n) => rankOf(n));
  for (const n of g.nodes) if (placedByUse(n)) rank.set(n, Math.max(forwardRank(n, realPreds.get(n) || [], (p) => rank.get(p)) ?? 1, backwardRank(realSuccs.get(n) || [], rank)));
  pushPastSources(g.nodes.filter(placedByUse), realSuccs, rank);
  for (const n of g.nodes) if (rank.get(n) === null) rank.set(n, backwardRank(realSuccs.get(n) || [], rank));
  pushPastSources(g.nodes, realSuccs, rank);
  const maxR = Math.max(...rank.values());
  for (const n of g.nodes) if (n.kind === 'return' && !(realSuccs.get(n) || []).length) rank.set(n, maxR);
  return rank;
}
function pushPastSources(sources, succs, rank) {
  const pending = [...sources];
  let guard = 0;
  while (pending.length && guard++ < 100000) {
    const n = pending.pop();
    for (const s of succs.get(n) || []) {
      if ((rank.get(s) ?? 0) > rank.get(n)) continue;
      rank.set(s, rank.get(n) + 1);
      pending.push(s);
    }
  }
}
function forwardRank(n, preds, rankOf) {
  if (n.kind === 'entry') return 0;
  return preds.length ? 1 + Math.max(...preds.map((p) => rankOf(p) ?? 0)) : null;
}
function backwardRank(succs, rank) {
  return succs.length ? Math.max(1, Math.min(...succs.map((s) => rank.get(s) ?? 2)) - 1) : 1;
}
function dummyRoutes(bundles, rank) {
  const preds = new Map(), succs = new Map();
  const link = (a, b, ak, bk, exec) => { pushTo(preds, b, { n: a, ak, bk, exec }); pushTo(succs, a, { n: b, ak, bk, exec }); };
  const dummies = [];
  const routes = new Map();
  for (const { key, list, src, pin, exec } of bundles) {
    if (src.overhead) {
      for (const e of list) { routes.set(`${key}|${e.to.id}|${e.tp}`, []); link(src, e.to, pin, e.tp, exec); }
      continue;
    }
    const r0 = rank.get(src);
    let far = r0;
    for (const e of list) far = Math.max(far, rank.get(e.to));
    const chain = [];
    for (let r = r0 + 1; r < far; r++) {
      const d = { dummy: true, exec, rank: r, w: 0, h: 8, x: 0, y: 0, pins: DUMMY_PINS, key: `${key}#${r}`, bundle: key, from: src, fromPin: pin };
      link(chain.length ? chain[chain.length - 1] : src, d, chain.length ? 'd' : pin, 'd', exec);
      chain.push(d); dummies.push(d);
    }
    for (const e of list) {
      const t = rank.get(e.to);
      const via = t > r0 + 1 ? chain.slice(0, t - r0 - 1) : [];
      routes.set(`${key}|${e.to.id}|${e.tp}`, via);
      link(via.length ? via[via.length - 1] : src, e.to, via.length ? 'd' : pin, e.tp, exec);
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
function isExecNode(n) { return n.dummy ? n.exec : Boolean(n.execIn || n.execOut || (n.execOuts && n.execOuts.length)); }
function groupBy(list, keyOf) {
  const groups = new Map();
  for (const item of list) pushTo(groups, keyOf(item), item);
  return groups;
}
function pushTo(map, key, value) { if (!map.has(key)) map.set(key, []); map.get(key).push(value); }
