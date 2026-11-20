import { LINE_KINDS, filterNet, filterProject, kindCounts } from './filters.js';
import { settings } from './settings.js';
export let OVERVIEW = null;
export let DIFF = null;
export let FILES = {};
export const FUNCTIONS = new Map();
export const fnKey = (ref) => `${ref.path}::${ref.sym}`;
export function lookup(ref) { if (!ref) return null; const f = FILES[ref.path]; return f ? f.index[ref.sym] || null : null; }
export const KIND_ORDER = LINE_KINDS.map((l) => l.key);
let NET_CACHE = null;
export function setProject(overview) { OVERVIEW = overview; FILES = {}; NET_CACHE = null; filterProject(overview && overview.root); }
export function setDiff(diff) { DIFF = diff; }
export function clearNetCache() { NET_CACHE = null; }
const TEST_PATH = /(^|\/)(tests?|testing|__tests__)\/|(^|\/)test_[^/]*\.py$|_test\.py$|\.(test|spec)\.[cm]?[jt]sx?$/;
export function isTestPath(path) { return TEST_PATH.test(path) || TEST_PATH.test(`${path}/`); }
export function net() {
  if (NET_CACHE) return NET_CACHE;
  const { nodes, root, add } = netTree();
  for (const path of Object.keys(FILES).sort()) if (settings.tests || !isTestPath(path)) addProjectFile(add, root, path);
  addLibraries(add, root);
  if (DIFF) settleDiffs(root);
  const allEdges = netLinks(nodes);
  if (!settings.tests) dropTestOnlyLibraries(root, nodes, allEdges);
  const counts = kindCounts(nodes, allEdges);
  const allIds = new Set(nodes.keys());
  const { edges, autoOpen } = filterNet(root, nodes, allEdges);
  NET_CACHE = { nodes, root, edges, chain: chainLookup(nodes), counts, allIds, autoOpen };
  return NET_CACHE;
}
function netTree() {
  const nodes = new Map();
  const root = { id: 'root', kind: 'root', name: OVERVIEW ? OVERVIEW.name : 'project', depth: 0, children: [], parent: null };
  nodes.set('root', root);
  const add = (id, kind, name, parent, extra = {}) => {
    if (nodes.has(id)) return nodes.get(id);
    const n = { id, kind, name, parent, depth: parent.depth + 1, children: [], ...extra };
    parent.children.push(n); nodes.set(id, n); return n;
  };
  return { nodes, root, add };
}
function addProjectFile(add, root, path) {
  const parts = path.split('/');
  let parent = root, acc = '';
  for (const part of parts.slice(0, -1)) { acc += (acc ? '/' : '') + part; parent = add(`pkg:${acc}`, 'package', part, parent); }
  const f = FILES[path];
  const mod = add(`mod:${path}`, 'module', parts[parts.length - 1], parent, { path, mocked: true });
  for (const s of f.symbols) {
    if (s.kind === 'function') { add(`fn:${path}:${s.qual}`, 'function', s.name, mod, { sym: s }); continue; }
    const c = add(`cls:${path}:${s.qual}`, 'class', s.name, mod, { sym: s, path });
    for (const [mname, v] of s.members || []) add(`f:${path}:${s.qual}.${mname}`, 'member', mname, c, { value: v });
    for (const [fname, ftype] of s.fields || []) add(`f:${path}:${s.qual}.${fname}`, 'field', fname, c, { type: ftype });
    for (const m of s.methods || []) add(`m:${path}:${m.qual}`, 'method', m.name, c, { sym: m });
  }
  for (const [cn, ct, cv] of f.constants || []) add(`c:${path}:${cn}`, 'constant', cn, mod, { type: ct, value: cv });
  for (const [tn, line, bound] of f.typeVars || []) add(`tv:${path}:${tn}`, 'typevar', tn, mod, { bound, line });
}
function addLibraries(add, root) {
  for (const lib of (OVERVIEW && OVERVIEW.libraries) || []) {
    const libNode = add(lib.id, 'library', lib.title, root);
    for (const m of lib.modules) {
      const modNode = add(`libmod:${m.module}`, 'libmodule', m.module, libNode);
      for (const n of m.names) add(`libn:${m.module}.${n}`, 'name', n, modNode);
    }
  }
}
function settleDiffs(n) {
  const kids = n.children.map(settleDiffs).filter((k) => k !== undefined);
  const mine = (n.kind === 'module' ? DIFF.status[`mod:${n.path}`] : DIFF.status[n.id]) || null;
  if (mine) { n.diff = mine; return mine; }
  const changed = kids.filter(Boolean);
  if (!changed.length || n.kind === 'library' || n.kind === 'libmodule') { n.diff = null; return null; }
  n.diff = n.kind === 'package' && changed.length === n.children.length && changed.every((k) => k === changed[0]) ? changed[0] : 'modified';
  return n.diff;
}
function netLinks(nodes) {
  const list = [];
  const ids = OVERVIEW ? OVERVIEW.edges.ids : [];
  for (const row of OVERVIEW ? OVERVIEW.edges.rows : []) {
    const from = ids[row[0]], to = ids[row[1]];
    if (!nodes.has(from) || !nodes.has(to)) continue;
    const kinds = new Set(row[2].split(',').filter(Boolean));
    list.push({ from, to, kinds, labels: new Set(row[3] ? row[3].split(',') : []), kind: KIND_ORDER.find((k) => kinds.has(k)) });
  }
  return list;
}
function chainLookup(nodes) {
  const chains = new Map();
  return (id) => { if (chains.has(id)) return chains.get(id); const out = []; for (let n = nodes.get(id); n; n = n.parent) out.unshift(n); chains.set(id, out); return out; };
}
function dropTestOnlyLibraries(root, nodes, edges) {
  const wanted = new Set(edges.flatMap((e) => [e.from, e.to]));
  for (const [path, f] of Object.entries(FILES)) if (!isTestPath(path)) for (const i of f.imports || []) if (i.lib) wanted.add(`lib:${i.lib}`);
  const subtree = (n) => [n, ...n.children.flatMap(subtree)];
  root.children = root.children.filter((n) => {
    if (n.kind !== 'library') return true;
    const all = subtree(n);
    if (all.some((x) => wanted.has(x.id))) return true;
    for (const x of all) nodes.delete(x.id);
    return false;
  });
}
