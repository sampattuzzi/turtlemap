export class Graph {
  constructor(name) {
    this.root = { id: 'root', kind: 'root', name, depth: 0, children: [], parent: null };
    this.nodes = new Map([['root', this.root]]);
    this.steps = new Map();
    this.edges = [];
    this.chains = new Map();
  }
  add(id, kind, name, parent, extra = {}) {
    if (this.nodes.has(id)) return this.nodes.get(id);
    const n = { id, kind, name, parent, depth: parent.depth + 1, children: [], ...extra };
    parent.children.push(n);
    this.nodes.set(id, n);
    return n;
  }
  node(id) { return this.nodes.get(id) || this.steps.get(id) || null; }
  chain(id) {
    if (this.chains.has(id)) return this.chains.get(id);
    const out = [];
    for (let n = this.node(id); n; n = n.parent) out.unshift(n);
    this.chains.set(id, out);
    return out;
  }
  contains(outer, inner) { return this.chain(inner).some((n) => n.id === outer); }
  liftTo(id, isOpen) {
    const chain = this.chain(id);
    for (let i = 1; i < chain.length; i++) if (!chain[i].children.length || !isOpen(chain[i])) return chain[i];
    return null;
  }
  lift(isOpen, edges = this.edges) {
    const links = new Map();
    for (const e of edges) {
      const a = this.liftTo(e.from, isOpen), b = this.liftTo(e.to, isOpen);
      if (!a || !b || a === b) continue;
      const key = `${a.id}|${b.id}`;
      if (!links.has(key)) links.set(key, { key, a, b, atoms: [], kinds: new Set() });
      const link = links.get(key);
      link.atoms.push(e);
      e.kinds.forEach((k) => link.kinds.add(k));
    }
    return [...links.values()];
  }
  attachBody(id, data, targetId) {
    const fn = this.nodes.get(id);
    if (!fn || fn.body || !data || !data.graph) return null;
    const stepId = (local) => `${id}#${local}`;
    const steps = data.graph.nodes.map((n) => {
      const step = { id: stepId(n.id), kind: 'step', name: n.title || n.kind, parent: fn, depth: fn.depth + 1, children: [], step: n };
      this.steps.set(step.id, step);
      return step;
    });
    const wire = (e, kind, label) => ({ from: stepId(e.from), to: stepId(e.to), kinds: new Set([kind]), labels: new Set(label ? [label] : []), kind, diff: e.diff || null });
    const edges = [...(data.graph.edges || []).map((e) => wire(e, 'data', e.fp)), ...(data.graph.exec || []).map((e) => wire(e, 'exec', e.fp))];
    for (const s of steps) {
      const target = s.step.target ? targetId(s.step.target) : null;
      if (target && this.nodes.has(target)) edges.push({ from: s.id, to: target, kinds: new Set(['calls']), labels: new Set(), kind: 'calls', diff: null });
    }
    fn.body = { data, steps, edges };
    return fn.body;
  }
}
