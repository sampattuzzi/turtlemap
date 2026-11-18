export const DATA_LIMIT = 250;

export function dataScopes(N) {
  const counts = dataCounts(N);
  const scopes = [];
  const walk = (n) => {
    if (n.kind === 'root' || n.kind === 'package' || n.kind === 'module') {
      if (counts.get(n.id)) scopes.push({ id: n.id, depth: n.depth, label: n.kind === 'root' ? 'Whole project' : n.kind === 'package' ? `${n.name}/` : n.name, count: counts.get(n.id) });
      for (const k of n.children) walk(k);
    }
  };
  walk(N.root);
  return scopes;
}

export function dataScopeFor(N, id) {
  const counts = dataCounts(N);
  const chain = id && N.nodes.has(id) ? N.chain(id) : [N.root];
  const unit = [...chain].reverse().find((n) => (n.kind === 'module' || n.kind === 'package' || n.kind === 'root') && counts.get(n.id));
  return unit ? unit.id : 'root';
}

export function dataModel(N, scope) {
  const root = { id: 'root', kind: 'root', name: 'data', depth: 0, children: [], parent: null };
  const all = dataClassCopies(N, root);
  const inScope = (id) => scope === 'root' || N.chain(id).some((a) => a.id === scope);
  const core = new Set([...all.keys()].filter(inScope));
  const links = [...pairHolds(fieldHolds(all)), ...baseLinks(N, all)].filter((l) => core.has(l.from) || core.has(l.to));
  const shown = new Set([...core, ...links.flatMap((l) => [l.from, l.to])]);
  const nodes = new Map([['root', root]]);
  const classes = [];
  if (core.size <= DATA_LIMIT) for (const [id, copy] of all) {
    if (!shown.has(id)) continue;
    copy.outside = !core.has(id);
    for (const k of copy.children) nodes.set(k.id, k);
    nodes.set(id, copy);
    root.children.push(copy);
    classes.push(copy);
  }
  const chain = (id) => { const out = []; for (let n = nodes.get(id); n; n = n.parent) out.unshift(n); return out; };
  return { root, nodes, chain, classes, links, core: core.size };
}

export function dataGroups(model) {
  const parent = new Map(model.classes.map((c) => [c.id, c.id]));
  const find = (id) => { while (parent.get(id) !== id) { parent.set(id, parent.get(parent.get(id))); id = parent.get(id); } return id; };
  for (const l of model.links) parent.set(find(l.from), find(l.to));
  const groups = new Map();
  for (const c of model.classes) { const r = find(c.id); if (!groups.has(r)) groups.set(r, []); groups.get(r).push(c); }
  return [...groups.values()].sort((p, q) => q.length - p.length);
}

function dataClassCopies(N, root) {
  const all = new Map();
  for (const n of N.nodes.values()) {
    if (!isDataClass(n)) continue;
    const copy = { ...n, parent: root, depth: 1, children: [] };
    copy.children = n.children.filter((k) => k.kind === 'field' || k.kind === 'member').map((k) => ({ ...k, parent: copy, depth: 2, children: [] }));
    all.set(copy.id, copy);
  }
  return all;
}

function fieldHolds(all) {
  const holds = [];
  for (const c of all.values()) for (const field of c.children) {
    if (field.kind !== 'field' || !field.type) continue;
    for (const [ref, end] of [[field.type.ref, field.type.opt ? 'optional' : 'one'], [field.type.items, 'many']]) {
      const target = ref ? `cls:${ref.path}:${ref.sym}` : null;
      if (target && all.has(target)) holds.push({ from: c.id, to: target, field, end });
    }
  }
  return holds;
}

function baseLinks(N, all) {
  return N.edges.filter((e) => (e.kinds.has('inherits') || e.kinds.has('realizes')) && all.has(e.from) && all.has(e.to)).map((e) => ({ from: e.from, to: e.to, base: true }));
}

function dataCounts(N) {
  if (N.dataCounts) return N.dataCounts;
  const counts = new Map();
  for (const n of N.nodes.values()) if (isDataClass(n)) for (const a of N.chain(n.id)) counts.set(a.id, (counts.get(a.id) || 0) + 1);
  N.dataCounts = counts;
  return counts;
}

function isDataClass(n) {
  return n.kind === 'class' && Boolean(n.sym) && (n.sym.kind === 'enum' || n.sym.cat === 'struct');
}

function pairHolds(holds) {
  const pending = [...holds];
  const links = [];
  while (pending.length) {
    const hold = pending.shift();
    const at = hold.from === hold.to ? -1 : pending.findIndex((o) => o.from === hold.to && o.to === hold.from);
    const back = at >= 0 ? pending.splice(at, 1)[0] : null;
    links.push({ from: hold.from, to: hold.to, fromField: hold.field, toField: back ? back.field : null, fromEnd: back ? back.end : 'one', toEnd: hold.end });
  }
  return links;
}
