export function networkSimplex(count, edges, maxIterations) {
  const ranker = new SimplexRanker(count, edges);
  return ranker.rank ? ranker.solve(maxIterations) : null;
}
class SimplexRanker {
  constructor(count, edges) {
    this.count = count;
    this.edgeCount = edges.length;
    this.tail = edges.map((e) => e.tail); this.head = edges.map((e) => e.head);
    this.minlen = edges.map((e) => e.minlen); this.weight = edges.map((e) => e.weight);
    this.outs = Array.from({ length: count }, () => []); this.ins = Array.from({ length: count }, () => []);
    edges.forEach((e, i) => { this.outs[e.tail].push(i); this.ins[e.head].push(i); });
    this.rank = longestPathRanks(count, edges, this.outs, this.ins);
    this.inTree = new Uint8Array(count); this.isTree = new Uint8Array(edges.length);
    this.treeEdges = Array.from({ length: count }, () => []);
    this.par = new Int32Array(count).fill(-1); this.low = new Int32Array(count); this.lim = new Int32Array(count);
    this.cut = new Float64Array(edges.length);
    this.size = 0;
  }
  solve(maxIterations) {
    if (!this.feasibleTree()) return null;
    for (const v of this.range(0, -1, 1)) if (this.par[v] >= 0) this.cutValue(this.par[v]);
    let cursor = 0;
    for (let iteration = 0; iteration < maxIterations; iteration++) {
      const leaving = this.leavingEdge(cursor);
      if (leaving < 0) break;
      cursor = leaving + 1;
      if (!this.pivot(leaving)) return null;
    }
    return this.rank;
  }
  slack(e) { return this.rank[this.head[e]] - this.rank[this.tail[e]] - this.minlen[e]; }
  other(e, v) { return this.tail[e] === v ? this.head[e] : this.tail[e]; }
  within(v, w) { return this.low[v] <= this.lim[w] && this.lim[w] <= this.lim[v]; }
  addTree(e) { this.isTree[e] = 1; this.treeEdges[this.tail[e]].push(e); this.treeEdges[this.head[e]].push(e); }
  removeTree(e) { this.isTree[e] = 0; for (const v of [this.tail[e], this.head[e]]) this.treeEdges[v].splice(this.treeEdges[v].indexOf(e), 1); }
  grow(start) {
    const stack = [start];
    while (stack.length) {
      const v = stack.pop();
      for (const e of [...this.outs[v], ...this.ins[v]]) {
        const w = this.other(e, v);
        if (!this.inTree[w] && this.slack(e) === 0) { this.inTree[w] = 1; this.size++; this.addTree(e); stack.push(w); }
      }
    }
  }
  feasibleTree() {
    const { tail, head, inTree } = this;
    this.size = 1;
    inTree[0] = 1;
    this.grow(0);
    while (this.size < this.count) {
      let best = -1, bestSlack = Infinity;
      for (let e = 0; e < this.edgeCount; e++) {
        if (inTree[tail[e]] === inTree[head[e]]) continue;
        const s = this.slack(e);
        if (s < bestSlack) { best = e; bestSlack = s; }
      }
      if (best < 0) return false;
      const delta = inTree[head[best]] ? -bestSlack : bestSlack;
      for (let v = 0; v < this.count; v++) if (inTree[v]) this.rank[v] += delta;
      const fresh = inTree[tail[best]] ? head[best] : tail[best];
      inTree[fresh] = 1; this.size++; this.addTree(best);
      this.grow(fresh);
    }
    return true;
  }
  range(root, rootPar, start) {
    const { par, low, lim, treeEdges } = this;
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
        const w = this.other(e, v);
        par[w] = e; low[w] = next;
        stack.push([w, 0]);
      } else {
        lim[v] = next++;
        visited.push(v);
        stack.pop();
      }
    }
    return visited;
  }
  value(e, v, dir) {
    const { tail, head } = this;
    const outside = !this.within(v, this.other(e, v));
    const result = outside ? this.weight[e] : (this.isTree[e] ? this.cut[e] : 0) - this.weight[e];
    let d = dir > 0 ? (head[e] === v ? 1 : -1) : tail[e] === v ? 1 : -1;
    if (outside) d = -d;
    return d < 0 ? -result : result;
  }
  cutValue(f) {
    const { tail, head } = this;
    const v = this.par[tail[f]] === f ? tail[f] : head[f];
    const dir = v === tail[f] ? 1 : -1;
    let sum = 0;
    for (const e of this.outs[v]) sum += this.value(e, v, dir);
    for (const e of this.ins[v]) sum += this.value(e, v, dir);
    this.cut[f] = sum;
  }
  leavingEdge(cursor) {
    for (let k = 0; k < this.edgeCount; k++) {
      const e = (cursor + k) % this.edgeCount;
      if (this.isTree[e] && this.cut[e] < 0) return e;
    }
    return -1;
  }
  pivot(leaving) {
    const { tail, head, lim, cut } = this;
    const entering = this.enter(leaving);
    if (entering < 0) return false;
    const delta = this.slack(entering);
    if (delta > 0) { if (lim[tail[leaving]] < lim[head[leaving]]) this.rerank(tail[leaving], delta); else this.rerank(head[leaving], -delta); }
    const cutvalue = cut[leaving];
    const lca = this.climb(tail[entering], head[entering], cutvalue, true);
    if (this.climb(head[entering], tail[entering], cutvalue, false) !== lca) return false;
    cut[entering] = -cutvalue;
    cut[leaving] = 0;
    this.removeTree(leaving);
    this.addTree(entering);
    this.range(lca, this.par[lca], this.low[lca]);
    return true;
  }
  enter(e) {
    const { tail, head, lim } = this;
    const outward = lim[tail[e]] >= lim[head[e]];
    const start = outward ? head[e] : tail[e];
    const bounds = { lo: this.low[start], hi: lim[start] };
    const best = { edge: -1, slack: Infinity };
    const stack = [start];
    while (stack.length) {
      const v = stack.pop();
      for (const f of outward ? this.outs[v] : this.ins[v]) this.considerEntering(f, v, outward, bounds, best, stack);
      for (const f of this.treeEdges[v]) {
        if (outward ? head[f] !== v : tail[f] !== v) continue;
        const w = this.other(f, v);
        if (lim[w] < lim[v]) stack.push(w);
      }
    }
    return best.edge;
  }
  considerEntering(f, v, outward, { lo, hi }, best, stack) {
    const lim = this.lim;
    const w = outward ? this.head[f] : this.tail[f];
    if (this.isTree[f]) { if (lim[w] < lim[v]) stack.push(w); return; }
    if (lo <= lim[w] && lim[w] <= hi) return;
    const s = this.slack(f);
    if (s < best.slack) { best.edge = f; best.slack = s; }
  }
  rerank(start, delta) {
    const stack = [start];
    while (stack.length) {
      const v = stack.pop();
      this.rank[v] -= delta;
      for (const e of this.treeEdges[v]) if (e !== this.par[v]) stack.push(this.other(e, v));
    }
  }
  climb(v, w, cutvalue, dir) {
    const { tail, head, lim, cut } = this;
    while (!this.within(v, w)) {
      const e = this.par[v];
      const d = v === tail[e] ? dir : !dir;
      cut[e] += d ? cutvalue : -cutvalue;
      v = lim[tail[e]] > lim[head[e]] ? tail[e] : head[e];
    }
    return v;
  }
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
