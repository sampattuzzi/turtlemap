const LAYOUT_CHOICES = [
  { key: 'balanced', label: 'Balanced', hint: 'Moves each node toward the middle of its wires. Quick, and the default.' },
  { key: 'classic', label: 'Classic', hint: 'The original layout: each node moves toward the average of its wires, so more of them bend.' },
  { key: 'compact', label: 'Compact', hint: 'The least wire travel and the shortest blueprints, but fewer wires run straight.' },
  { key: 'straighter', label: 'Straighter', hint: 'Locks chains of wires into straight runs, then packs them as tightly as it can.' },
  { key: 'straightest', label: 'Straightest', hint: 'The most straight wires. Blueprints grow taller and the other wires travel further.' },
];
const ARRANGED_LAYOUTS = new Set(['compact', 'straighter', 'straightest']);
const LAYOUT_UNITS = 2;
const LAYOUT_PIN_WEIGHT = 1000;
const LAYOUT_BEND = 400;
const LAYOUT_MAX_ITERATIONS = 4000;

function arrangeLayers(layout, columns, links, { height, gap, floor, pinned, isDummy, candidates, previous }) {
  const layer = new Map(), pos = new Map();
  columns.forEach((col, i) => col.forEach((v, k) => { layer.set(v, i); pos.set(v, k); }));
  const usable = links.filter((l) => layer.has(l.a) && layer.has(l.b) && l.a !== l.b);
  const weightOf = (l) => (l.weight || 1) * (isDummy(l.a) && isDummy(l.b) ? 8 : isDummy(l.a) || isDummy(l.b) ? 2 : 1);
  const travel = (l, y) => Math.abs(y.get(l.a) + l.pa - y.get(l.b) - l.pb);
  const place = (root, off) => placeBlocks(columns, usable, root, off, { height, gap, floor, pinned, weightOf });
  const nodes = [...layer.keys()];
  const alone = () => place(new Map(nodes.map((v) => [v, v])), new Map(nodes.map((v) => [v, 0])));
  if (layout === 'compact') return alone();
  const alignments = blockAlignments(columns, usable, layer, pos, isDummy, candidates);
  if (layout === 'straightest') {
    const packed = alignments.map(({ root, off, topDown }) => compactBlocks(columns, root, off, topDown, usable, { height, gap, floor, pinned }));
    return bestBy(packed, (y) => [-usable.filter((l) => travel(l, y) < 0.5).length, usable.reduce((sum, l) => sum + travel(l, y), 0)]);
  }
  const placed = [previous, alone(), ...alignments.map(({ root, off }) => place(root, off))];
  return bestBy(placed, (y) => [usable.reduce((sum, l) => { const t = travel(l, y); return sum + weightOf(l) * (t + (t >= 0.5 ? LAYOUT_BEND : 0)); }, 0)]);
}

function bestBy(options, keyOf) {
  const scored = options.filter(Boolean).map((option) => ({ option, key: keyOf(option) }));
  scored.sort((p, q) => compareKeys(p.key, q.key));
  return scored.length ? scored[0].option : null;
}

function compareKeys(p, q) {
  for (let i = 0; i < p.length; i++) if (p[i] !== q[i]) return p[i] - q[i];
  return 0;
}

function blockAlignments(columns, links, layer, pos, isDummy, candidates) {
  const adjacent = links.filter((l) => layer.get(l.b) === layer.get(l.a) + 1);
  const ups = new Map(), downs = new Map();
  for (const l of adjacent) { listInto(ups, l.b, l); listInto(downs, l.a, l); }
  const marked = innerConflicts(adjacent, layer, pos, isDummy);
  const alignments = [];
  for (const forward of [true, false]) for (const topDown of [true, false]) alignments.push({ topDown, ...alignBlocks(columns, forward, topDown, forward ? ups : downs, pos, marked, candidates) });
  return alignments;
}

function placeBlocks(columns, links, root, off, { height, gap, floor, pinned, weightOf }) {
  const units = (value) => Math.round(value * LAYOUT_UNITS);
  const index = new Map();
  for (const b of root.values()) if (!index.has(b)) index.set(b, index.size + 1);
  const lowest = new Map(), fixed = new Set();
  for (const [v, b] of root) { lowest.set(b, Math.max(lowest.get(b) ?? -Infinity, floor(v) - off.get(v))); if (pinned(v)) fixed.add(b); }
  const edges = [];
  for (const [b, i] of index) edges.push({ tail: 0, head: i, minlen: units(lowest.get(b)), weight: fixed.has(b) ? LAYOUT_PIN_WEIGHT : 0 });
  for (const col of columns) for (let k = 1; k < (col || []).length; k++) {
    const w = col[k - 1], v = col[k];
    if (root.get(w) === root.get(v)) return null;
    edges.push({ tail: index.get(root.get(w)), head: index.get(root.get(v)), minlen: units(off.get(w) + height(w) + gap(w) - off.get(v)), weight: 0 });
  }
  let count = index.size + 1;
  for (const l of links) {
    const ba = root.get(l.a), bb = root.get(l.b);
    if (ba === bb) continue;
    const middle = count++;
    edges.push({ tail: middle, head: index.get(ba), minlen: -units(off.get(l.a) + l.pa), weight: weightOf(l) });
    edges.push({ tail: middle, head: index.get(bb), minlen: -units(off.get(l.b) + l.pb), weight: weightOf(l) });
  }
  const rank = networkSimplex(count, edges, LAYOUT_MAX_ITERATIONS);
  if (!rank) return null;
  return new Map([...root].map(([v, b]) => [v, (rank[index.get(b)] - rank[0]) / LAYOUT_UNITS + off.get(v)]));
}

function listInto(map, key, value) { if (!map.has(key)) map.set(key, []); map.get(key).push(value); }

function innerConflicts(adjacent, layer, pos, isDummy) {
  const marked = new Set();
  const byLayer = new Map();
  for (const l of adjacent) listInto(byLayer, layer.get(l.a), l);
  for (const list of byLayer.values()) {
    const inner = list.filter((l) => isDummy(l.a) && isDummy(l.b));
    if (!inner.length) continue;
    for (const l of list) {
      if (isDummy(l.a) && isDummy(l.b)) continue;
      const a = pos.get(l.a), b = pos.get(l.b);
      if (inner.some((m) => (a - pos.get(m.a)) * (b - pos.get(m.b)) < 0)) marked.add(l);
    }
  }
  return marked;
}

function alignBlocks(columns, forward, topDown, sideLinks, pos, marked, candidates) {
  const root = new Map(), off = new Map();
  for (const col of columns) for (const v of col || []) { root.set(v, v); off.set(v, 0); }
  const other = (l) => (forward ? l.a : l.b);
  const otherPin = (l) => (forward ? l.pa : l.pb);
  const order = columns.map((_, i) => i);
  if (!forward) order.reverse();
  for (const i of order) {
    const col = columns[i];
    if (!col) continue;
    let reached = topDown ? -Infinity : Infinity;
    for (const v of topDown ? col : [...col].reverse()) {
      const list = candidates(v, sideLinks.get(v) || [], forward).slice().sort((p, q) => pos.get(other(p)) - pos.get(other(q)) || otherPin(p) - otherPin(q));
      if (!list.length) continue;
      const medians = [...new Set([Math.floor((list.length - 1) / 2), Math.ceil((list.length - 1) / 2)])];
      if (!topDown) medians.reverse();
      for (const m of medians) {
        const l = list[m], u = other(l), at = pos.get(u);
        if (marked.has(l) || !(topDown ? reached < at : reached > at)) continue;
        root.set(v, root.get(u));
        off.set(v, off.get(u) + (forward ? l.pa - l.pb : l.pb - l.pa));
        reached = at;
        break;
      }
    }
  }
  return { root, off };
}

function compactBlocks(columns, root, off, topDown, links, { height, gap, floor, pinned }) {
  const blocks = new Set(root.values());
  const after = new Map(), before = new Map(), waiting = new Map(), lowest = new Map(), fixed = new Set();
  for (const b of blocks) { after.set(b, []); before.set(b, []); waiting.set(b, 0); lowest.set(b, -Infinity); }
  for (const [v, b] of root) { lowest.set(b, Math.max(lowest.get(b), floor(v) - off.get(v))); if (pinned(v)) fixed.add(b); }
  for (const col of columns) {
    for (let k = 1; k < (col || []).length; k++) {
      const w = col[k - 1], v = col[k];
      const edge = { from: root.get(w), to: root.get(v), space: off.get(w) + height(w) + gap(w) - off.get(v) };
      if (edge.from === edge.to) return null;
      after.get(edge.from).push(edge); before.get(edge.to).push(edge);
      waiting.set(edge.to, waiting.get(edge.to) + 1);
    }
  }
  const order = [...blocks].filter((b) => waiting.get(b) === 0);
  for (let i = 0; i < order.length; i++) for (const e of after.get(order[i])) { waiting.set(e.to, waiting.get(e.to) - 1); if (waiting.get(e.to) === 0) order.push(e.to); }
  if (order.length !== blocks.size) return null;
  const at = new Map();
  for (const b of order) at.set(b, Math.max(lowest.get(b), ...before.get(b).map((e) => at.get(e.from) + e.space)));
  if (!topDown) {
    let bottom = -Infinity;
    for (const [v, b] of root) bottom = Math.max(bottom, at.get(b) + off.get(v) + height(v));
    const highest = new Map([...blocks].map((b) => [b, Infinity]));
    for (const [v, b] of root) highest.set(b, Math.min(highest.get(b), bottom - off.get(v) - height(v)));
    for (const b of [...order].reverse()) {
      if (fixed.has(b)) continue;
      at.set(b, Math.max(at.get(b), Math.min(highest.get(b), ...after.get(b).map((e) => at.get(e.to) - e.space))));
    }
  }
  settleBlocks(order, at, root, off, links, before, after, lowest, fixed);
  const y = new Map();
  for (const [v, b] of root) { const value = at.get(b) + off.get(v); if (!Number.isFinite(value)) return null; y.set(v, value); }
  return y;
}

function settleBlocks(order, at, root, off, links, before, after, lowest, fixed) {
  const pulls = new Map(order.map((b) => [b, []]));
  for (const l of links) {
    const ba = root.get(l.a), bb = root.get(l.b);
    if (ba === bb) continue;
    const weight = l.weight || 1;
    pulls.get(ba).push({ other: bb, shift: off.get(l.b) + l.pb - off.get(l.a) - l.pa, weight });
    pulls.get(bb).push({ other: ba, shift: off.get(l.a) + l.pa - off.get(l.b) - l.pb, weight });
  }
  for (let round = 0; round < 12; round++) {
    let moved = false;
    for (const b of round % 2 ? [...order].reverse() : order) {
      if (fixed.has(b) || !pulls.get(b).length) continue;
      const lo = Math.max(lowest.get(b), ...before.get(b).map((e) => at.get(e.from) + e.space));
      const hi = Math.min(...after.get(b).map((e) => at.get(e.to) - e.space));
      const wanted = weightedMedian(pulls.get(b).map((p) => ({ value: at.get(p.other) + p.shift, weight: p.weight })));
      const next = Math.min(Math.max(wanted, lo), hi);
      if (Number.isFinite(next) && Math.abs(next - at.get(b)) > 0.25) { at.set(b, next); moved = true; }
    }
    if (!moved) break;
  }
}

function weightedMedian(items) {
  items.sort((p, q) => p.value - q.value);
  const half = items.reduce((sum, i) => sum + i.weight, 0) / 2;
  let running = 0;
  for (const i of items) { running += i.weight; if (running >= half) return i.value; }
  return items.length ? items[items.length - 1].value : NaN;
}

function networkSimplex(count, edges, maxIterations) {
  const tail = edges.map((e) => e.tail), head = edges.map((e) => e.head), minlen = edges.map((e) => e.minlen), weight = edges.map((e) => e.weight);
  const outs = Array.from({ length: count }, () => []), ins = Array.from({ length: count }, () => []);
  edges.forEach((e, i) => { outs[e.tail].push(i); ins[e.head].push(i); });
  const rank = longestPathRanks(count, edges, outs, ins);
  if (!rank) return null;
  const slack = (e) => rank[head[e]] - rank[tail[e]] - minlen[e];
  const inTree = new Uint8Array(count), isTree = new Uint8Array(edges.length);
  const treeEdges = Array.from({ length: count }, () => []);
  const addTree = (e) => { isTree[e] = 1; treeEdges[tail[e]].push(e); treeEdges[head[e]].push(e); };
  const removeTree = (e) => { isTree[e] = 0; for (const v of [tail[e], head[e]]) treeEdges[v].splice(treeEdges[v].indexOf(e), 1); };
  let size = 1;
  inTree[0] = 1;
  const grow = (start) => {
    const stack = [start];
    while (stack.length) {
      const v = stack.pop();
      for (const e of [...outs[v], ...ins[v]]) {
        const w = tail[e] === v ? head[e] : tail[e];
        if (!inTree[w] && slack(e) === 0) { inTree[w] = 1; size++; addTree(e); stack.push(w); }
      }
    }
  };
  grow(0);
  while (size < count) {
    let best = -1, bestSlack = Infinity;
    for (let e = 0; e < edges.length; e++) {
      if (inTree[tail[e]] === inTree[head[e]]) continue;
      const s = slack(e);
      if (s < bestSlack) { best = e; bestSlack = s; }
    }
    if (best < 0) return null;
    const delta = inTree[head[best]] ? -bestSlack : bestSlack;
    for (let v = 0; v < count; v++) if (inTree[v]) rank[v] += delta;
    const fresh = inTree[tail[best]] ? head[best] : tail[best];
    inTree[fresh] = 1; size++; addTree(best);
    grow(fresh);
  }
  const par = new Int32Array(count).fill(-1), low = new Int32Array(count), lim = new Int32Array(count);
  const cut = new Float64Array(edges.length);
  const within = (v, w) => low[v] <= lim[w] && lim[w] <= lim[v];
  const other = (e, v) => (tail[e] === v ? head[e] : tail[e]);
  const range = (root, rootPar, start) => {
    let next = start;
    par[root] = rootPar; low[root] = start;
    const stack = [[root, 0]];
    const visited = [];
    while (stack.length) {
      const frame = stack[stack.length - 1];
      const [v, i] = frame;
      if (i < treeEdges[v].length) {
        frame[1]++;
        const e = treeEdges[v][i];
        if (e === par[v]) continue;
        const w = other(e, v);
        par[w] = e; low[w] = next;
        stack.push([w, 0]);
      } else {
        lim[v] = next++;
        visited.push(v);
        stack.pop();
      }
    }
    return visited;
  };
  const value = (e, v, dir) => {
    const w = other(e, v);
    let result, outside;
    if (!within(v, w)) { outside = true; result = weight[e]; } else { outside = false; result = (isTree[e] ? cut[e] : 0) - weight[e]; }
    let d = dir > 0 ? (head[e] === v ? 1 : -1) : tail[e] === v ? 1 : -1;
    if (outside) d = -d;
    return d < 0 ? -result : result;
  };
  const cutValue = (f) => {
    const v = par[tail[f]] === f ? tail[f] : head[f];
    const dir = v === tail[f] ? 1 : -1;
    let sum = 0;
    for (const e of outs[v]) sum += value(e, v, dir);
    for (const e of ins[v]) sum += value(e, v, dir);
    cut[f] = sum;
  };
  for (const v of range(0, -1, 1)) if (par[v] >= 0) cutValue(par[v]);
  const enter = (e) => {
    const outward = lim[tail[e]] >= lim[head[e]];
    const start = outward ? head[e] : tail[e];
    const lo = low[start], hi = lim[start];
    let best = -1, bestSlack = Infinity;
    const stack = [start];
    while (stack.length) {
      const v = stack.pop();
      for (const f of outward ? outs[v] : ins[v]) {
        const w = outward ? head[f] : tail[f];
        if (!isTree[f]) { if (!(lo <= lim[w] && lim[w] <= hi)) { const s = slack(f); if (s < bestSlack) { best = f; bestSlack = s; } } } else if (lim[w] < lim[v]) stack.push(w);
      }
      for (const f of treeEdges[v]) {
        if (outward ? head[f] !== v : tail[f] !== v) continue;
        const w = other(f, v);
        if (lim[w] < lim[v]) stack.push(w);
      }
    }
    return best;
  };
  const rerank = (start, delta) => {
    const stack = [start];
    while (stack.length) {
      const v = stack.pop();
      rank[v] -= delta;
      for (const e of treeEdges[v]) if (e !== par[v]) stack.push(other(e, v));
    }
  };
  const climb = (v, w, cutvalue, dir) => {
    while (!within(v, w)) {
      const e = par[v];
      const d = v === tail[e] ? dir : !dir;
      cut[e] += d ? cutvalue : -cutvalue;
      v = lim[tail[e]] > lim[head[e]] ? tail[e] : head[e];
    }
    return v;
  };
  let cursor = 0;
  for (let iteration = 0; iteration < maxIterations; iteration++) {
    let leaving = -1;
    for (let k = 0; k < edges.length; k++) {
      const e = (cursor + k) % edges.length;
      if (isTree[e] && cut[e] < 0) { leaving = e; cursor = e + 1; break; }
    }
    if (leaving < 0) break;
    const entering = enter(leaving);
    if (entering < 0) return null;
    const delta = slack(entering);
    if (delta > 0) { if (lim[tail[leaving]] < lim[head[leaving]]) rerank(tail[leaving], delta); else rerank(head[leaving], -delta); }
    const cutvalue = cut[leaving];
    const lca = climb(tail[entering], head[entering], cutvalue, true);
    if (climb(head[entering], tail[entering], cutvalue, false) !== lca) return null;
    cut[entering] = -cutvalue;
    cut[leaving] = 0;
    removeTree(leaving);
    addTree(entering);
    range(lca, par[lca], low[lca]);
  }
  return rank;
}

function longestPathRanks(count, edges, outs, ins) {
  const rank = new Array(count).fill(-Infinity);
  const waiting = ins.map((list) => list.length);
  const ready = [];
  for (let v = 0; v < count; v++) if (!waiting[v]) { ready.push(v); rank[v] = 0; }
  let seen = 0;
  while (ready.length) {
    const v = ready.pop();
    seen++;
    for (const e of outs[v]) {
      const w = edges[e].head;
      rank[w] = Math.max(rank[w], rank[v] + edges[e].minlen);
      if (--waiting[w] === 0) ready.push(w);
    }
  }
  return seen === count ? rank : null;
}

function rankColumns(items, counts, keepRight) {
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
  const outs = new Map(items.map((k) => [k, new Map()]));
  const ins = new Map(items.map((k) => [k, new Map()]));
  for (const [a, targets] of weights) for (const [b, w] of targets) if (a !== b) { outs.get(a).set(b, w); ins.get(b).set(a, w); }
  const alive = new Set(items);
  const front = [], back = [];
  const drop = (v) => { alive.delete(v); for (const b of outs.get(v).keys()) ins.get(b).delete(v); for (const a of ins.get(v).keys()) outs.get(a).delete(v); };
  const total = (m) => { let s = 0; for (const w of m.values()) s += w; return s; };
  while (alive.size) {
    let moved = true;
    while (moved) {
      moved = false;
      for (const v of alive) {
        if (!outs.get(v).size && ins.get(v).size) { back.push(v); drop(v); moved = true; }
        else if (!ins.get(v).size) { front.push(v); drop(v); moved = true; }
      }
    }
    let best = null, score = -Infinity;
    for (const v of alive) { const s = total(outs.get(v)) - total(ins.get(v)); if (s > score) { score = s; best = v; } }
    if (best !== null) { front.push(best); drop(best); }
  }
  return [...front, ...back.reverse()];
}

function siftOrder(order, weights, passes = 4) {
  const weight = (a, b) => (a === b ? 0 : (weights.get(a) && weights.get(a).get(b)) || 0);
  const touches = new Map(order.map((k) => [k, new Set()]));
  for (const [a, targets] of weights) for (const b of targets.keys()) if (a !== b && touches.has(a) && touches.has(b)) { touches.get(a).add(b); touches.get(b).add(a); }
  let list = [...order];
  for (let pass = 0; pass < passes; pass++) {
    let improved = false;
    for (const v of order) {
      if (!touches.get(v).size) continue;
      const rest = list.filter((k) => k !== v);
      const here = list.indexOf(v);
      let cost = 0;
      for (const u of touches.get(v)) cost += weight(u, v);
      let best = cost, bestAt = 0, current = here === 0 ? cost : null;
      rest.forEach((u, i) => {
        if (touches.get(v).has(u)) cost += weight(v, u) - weight(u, v);
        if (i + 1 === here) current = cost;
        if (cost < best) { best = cost; bestAt = i + 1; }
      });
      if (best < current) { rest.splice(bestAt, 0, v); list = rest; improved = true; }
    }
    if (!improved) break;
  }
  return list;
}
