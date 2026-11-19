export function rankColumns(items, counts, keepRight) {
  const weights = new Map([...counts].map(([a, targets]) => [a, new Map([...targets].map(([b, n]) => [b, 1 + Math.log2(n)]))]));
  const order = siftOrder(feedbackOrder(items, weights), weights);
  const at = new Map(order.map((k, i) => [k, i]));
  const forward = (a, b) => at.get(b) > at.get(a);
  const rank = new Map(order.map((k) => [k, 0]));
  const linked = new Set();
  for (const a of order) for (const b of (weights.get(a) || new Map()).keys()) if (forward(a, b)) { rank.set(b, Math.max(rank.get(b), rank.get(a) + 1)); linked.add(a); linked.add(b); }
  const last = Math.max(0, ...rank.values());
  for (const k of items) if (keepRight(k) && !linked.has(k)) rank.set(k, last);
  return rank;
}

function feedbackOrder(items, weights) {
  const graph = new FeedbackGraph(items, weights);
  const front = [], back = [];
  while (graph.alive.size) {
    graph.peel(front, back);
    const best = graph.mostOutgoing();
    if (best !== null) { front.push(best); graph.drop(best); }
  }
  return [...front, ...back.reverse()];
}

class FeedbackGraph {
  constructor(items, weights) {
    this.outs = new Map(items.map((k) => [k, new Map()]));
    this.ins = new Map(items.map((k) => [k, new Map()]));
    for (const [a, targets] of weights) for (const [b, w] of targets) if (a !== b) { this.outs.get(a).set(b, w); this.ins.get(b).set(a, w); }
    this.alive = new Set(items);
  }
  drop(v) {
    this.alive.delete(v);
    for (const b of this.outs.get(v).keys()) this.ins.get(b).delete(v);
    for (const a of this.ins.get(v).keys()) this.outs.get(a).delete(v);
  }
  peel(front, back) {
    let moved = true;
    while (moved) {
      moved = false;
      for (const v of this.alive) {
        if (!this.outs.get(v).size && this.ins.get(v).size) { back.push(v); this.drop(v); moved = true; }
        else if (!this.ins.get(v).size) { front.push(v); this.drop(v); moved = true; }
      }
    }
  }
  mostOutgoing() {
    let best = null, score = -Infinity;
    for (const v of this.alive) { const s = total(this.outs.get(v)) - total(this.ins.get(v)); if (s > score) { score = s; best = v; } }
    return best;
  }
}

function total(weights) {
  let sum = 0;
  for (const w of weights.values()) sum += w;
  return sum;
}

function siftOrder(order, weights, passes = 4) {
  const weight = (a, b) => (a === b ? 0 : (weights.get(a) && weights.get(a).get(b)) || 0);
  const touches = touchMap(order, weights);
  let list = [...order];
  for (let pass = 0; pass < passes; pass++) {
    let improved = false;
    for (const v of order) {
      if (!touches.get(v).size) continue;
      const moved = siftOne(list, v, touches.get(v), weight);
      if (moved) { list = moved; improved = true; }
    }
    if (!improved) break;
  }
  return list;
}

function touchMap(order, weights) {
  const touches = new Map(order.map((k) => [k, new Set()]));
  for (const [a, targets] of weights) for (const b of targets.keys()) if (a !== b && touches.has(a) && touches.has(b)) { touches.get(a).add(b); touches.get(b).add(a); }
  return touches;
}

function siftOne(list, v, near, weight) {
  const rest = list.filter((k) => k !== v);
  const here = list.indexOf(v);
  let cost = 0;
  for (const u of near) cost += weight(u, v);
  let best = cost, bestAt = 0, current = here === 0 ? cost : null;
  rest.forEach((u, i) => {
    if (near.has(u)) cost += weight(v, u) - weight(u, v);
    if (i + 1 === here) current = cost;
    if (cost < best) { best = cost; bestAt = i + 1; }
  });
  if (!(best < current)) return null;
  rest.splice(bestAt, 0, v);
  return rest;
}
