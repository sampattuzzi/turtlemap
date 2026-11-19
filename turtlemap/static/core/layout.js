import { networkSimplex } from './simplex.js';
export const LAYOUT_CHOICES = [
  { key: 'balanced', label: 'Balanced', hint: 'Moves each node toward the middle of its wires. Quick, and the default.' },
  { key: 'classic', label: 'Classic', hint: 'The original layout: each node moves toward the average of its wires, so more of them bend.' },
  { key: 'compact', label: 'Compact', hint: 'The least wire travel and the shortest blueprints, but fewer wires run straight.' },
  { key: 'straighter', label: 'Straighter', hint: 'Locks chains of wires into straight runs, then packs them as tightly as it can.' },
  { key: 'straightest', label: 'Straightest', hint: 'The most straight wires. Blueprints grow taller and the other wires travel further.' },
];
export const ARRANGED_LAYOUTS = new Set(['compact', 'straighter', 'straightest']);
const LAYOUT_UNITS = 2;
const LAYOUT_PIN_WEIGHT = 1000;
const LAYOUT_BEND = 400;
const LAYOUT_MAX_ITERATIONS = 4000;

export function arrangeLayers(layout, columns, links, { height, gap, floor, pinned, isDummy, candidates, previous }) {
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
  const aligner = new BlockAligner(forward, topDown, sideLinks, pos, marked, candidates);
  for (const col of columns) for (const v of col || []) { aligner.root.set(v, v); aligner.off.set(v, 0); }
  const order = columns.map((_, i) => i);
  if (!forward) order.reverse();
  for (const i of order) if (columns[i]) aligner.alignColumn(columns[i]);
  return { root: aligner.root, off: aligner.off };
}

class BlockAligner {
  constructor(forward, topDown, sideLinks, pos, marked, candidates) {
    Object.assign(this, { forward, topDown, sideLinks, pos, marked, candidates });
    this.root = new Map();
    this.off = new Map();
  }
  other(l) { return this.forward ? l.a : l.b; }
  otherPin(l) { return this.forward ? l.pa : l.pb; }
  alignColumn(col) {
    let reached = this.topDown ? -Infinity : Infinity;
    for (const v of this.topDown ? col : [...col].reverse()) reached = this.alignVertex(v, reached);
  }
  alignVertex(v, reached) {
    const { candidates, pos } = this;
    const list = candidates(v, this.sideLinks.get(v) || [], this.forward).slice().sort((p, q) => pos.get(this.other(p)) - pos.get(this.other(q)) || this.otherPin(p) - this.otherPin(q));
    for (const m of this.medians(list.length)) {
      const l = list[m], u = this.other(l), at = pos.get(u);
      if (this.marked.has(l) || !(this.topDown ? reached < at : reached > at)) continue;
      this.root.set(v, this.root.get(u));
      this.off.set(v, this.off.get(u) + (this.forward ? l.pa - l.pb : l.pb - l.pa));
      return at;
    }
    return reached;
  }
  medians(length) {
    if (!length) return [];
    const medians = [...new Set([Math.floor((length - 1) / 2), Math.ceil((length - 1) / 2)])];
    return this.topDown ? medians : medians.reverse();
  }
}

function compactBlocks(columns, root, off, topDown, links, { height, gap, floor, pinned }) {
  const blocks = new Set(root.values());
  const lowest = new Map([...blocks].map((b) => [b, -Infinity])), fixed = new Set();
  for (const [v, b] of root) { lowest.set(b, Math.max(lowest.get(b), floor(v) - off.get(v))); if (pinned(v)) fixed.add(b); }
  const stacking = stackingEdges(columns, root, off, height, gap, blocks);
  if (!stacking) return null;
  const { before, after } = stacking;
  const order = stackingOrder(blocks, after, stacking.waiting);
  if (!order) return null;
  const at = new Map();
  for (const b of order) at.set(b, Math.max(lowest.get(b), ...before.get(b).map((e) => at.get(e.from) + e.space)));
  if (!topDown) sinkBlocks({ order, at, root, off, height, after, fixed, blocks });
  settleBlocks(order, at, root, off, links, before, after, lowest, fixed);
  return blockYs(root, at, off);
}

function stackingEdges(columns, root, off, height, gap, blocks) {
  const after = new Map(), before = new Map(), waiting = new Map();
  for (const b of blocks) { after.set(b, []); before.set(b, []); waiting.set(b, 0); }
  for (const col of columns) {
    for (let k = 1; k < (col || []).length; k++) {
      const w = col[k - 1], v = col[k];
      const edge = { from: root.get(w), to: root.get(v), space: off.get(w) + height(w) + gap(w) - off.get(v) };
      if (edge.from === edge.to) return null;
      after.get(edge.from).push(edge); before.get(edge.to).push(edge);
      waiting.set(edge.to, waiting.get(edge.to) + 1);
    }
  }
  return { after, before, waiting };
}

function stackingOrder(blocks, after, waiting) {
  const order = [...blocks].filter((b) => waiting.get(b) === 0);
  for (let i = 0; i < order.length; i++) for (const e of after.get(order[i])) { waiting.set(e.to, waiting.get(e.to) - 1); if (waiting.get(e.to) === 0) order.push(e.to); }
  return order.length === blocks.size ? order : null;
}

function sinkBlocks({ order, at, root, off, height, after, fixed, blocks }) {
  let bottom = -Infinity;
  for (const [v, b] of root) bottom = Math.max(bottom, at.get(b) + off.get(v) + height(v));
  const highest = new Map([...blocks].map((b) => [b, Infinity]));
  for (const [v, b] of root) highest.set(b, Math.min(highest.get(b), bottom - off.get(v) - height(v)));
  for (const b of [...order].reverse()) {
    if (fixed.has(b)) continue;
    at.set(b, Math.max(at.get(b), Math.min(highest.get(b), ...after.get(b).map((e) => at.get(e.to) - e.space))));
  }
}

function blockYs(root, at, off) {
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
