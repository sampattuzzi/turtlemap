import { LINE_KINDS, filterNet, filterProject, kindCounts } from './filters.js';
import { Graph } from './graph.js';
import { settings } from './settings.js';
export let OVERVIEW = null;
export let DIFF = null;
export let FILES = {};
export const FUNCTIONS = new Map();
export const fnKey = (ref) => `${ref.path}::${ref.sym}`;
export function lookup(ref) { if (!ref) return null; const f = FILES[ref.path]; return f ? f.index[ref.sym] || null : null; }
export function symbolId(ref) {
  const sym = lookup(ref);
  if (!sym) return null;
  if (sym.kind !== 'function') return `cls:${ref.path}:${ref.sym}`;
  return `${sym.owner ? 'm' : 'fn'}:${ref.path}:${ref.sym}`;
}
export const KIND_ORDER = LINE_KINDS.map((l) => l.key);
let NET_CACHE = null;
let EDGES = new Map();
export function setProject(overview) { OVERVIEW = overview; FILES = {}; EDGES = edgesByFile(overview.edges); NET_CACHE = null; filterProject(overview && overview.root); }
export function patchProject(changes) {
  const touched = new Set([...changes.rebuilt, ...changes.removed]);
  for (const path of touched) { delete FILES[path]; EDGES.delete(path); }
  for (const [path, rows] of edgesByFile(changes.edges)) EDGES.set(path, rows);
  OVERVIEW.modules = [...OVERVIEW.modules.filter((m) => !touched.has(m.path)), ...changes.modules];
  OVERVIEW.failures = [...OVERVIEW.failures.filter((f) => !touched.has(f.path)), ...changes.failures];
  OVERVIEW.libraries = changes.libraries;
  NET_CACHE = null;
  return touched;
}
function link(from, to, kindList, labels) {
  const kinds = new Set(kindList.split(',').filter(Boolean));
  return { from, to, kinds, labels: new Set(labels ? labels.split(',') : []), kind: KIND_ORDER.find((k) => kinds.has(k)) };
}
function edgesByFile(table) {
  const byFile = new Map();
  let at = 0;
  for (const [path, count] of table.files || []) {
    byFile.set(path, table.rows.slice(at, at + count).map((row) => link(table.ids[row[0]], table.ids[row[1]], row[2], row[3])));
    at += count;
  }
  return byFile;
}
export function setDiff(diff) { DIFF = diff; }
export function clearNetCache() { NET_CACHE = null; }
const TEST_PATH = /(^|\/)(tests?|testing|__tests__)\/|(^|\/)test_[^/]*\.py$|_test\.py$|\.(test|spec)\.[cm]?[jt]sx?$/;
export function isTestPath(path) { return TEST_PATH.test(path) || TEST_PATH.test(`${path}/`); }
export function net() {
  if (NET_CACHE) return NET_CACHE;
  const graph = new Graph(OVERVIEW ? OVERVIEW.name : 'project');
  const add = graph.add.bind(graph);
  for (const path of Object.keys(FILES).sort()) if (settings.tests || !isTestPath(path)) addProjectFile(add, graph.root, path);
  addLibraries(add, graph.root);
  if (DIFF) settleDiffs(graph.root);
  const allEdges = netLinks(graph.nodes);
  if (!settings.tests) dropTestOnlyLibraries(graph.root, graph.nodes, allEdges);
  graph.counts = kindCounts(graph.nodes, allEdges);
  graph.allIds = new Set(graph.nodes.keys());
  graph.edges = filterNet(graph.root, graph.nodes, allEdges);
  for (const [key, data] of FUNCTIONS) attachBody(graph, key, data);
  NET_CACHE = graph;
  return NET_CACHE;
}
export function attachLoadedBody(key, data) { if (NET_CACHE) attachBody(NET_CACHE, key, data); }
function attachBody(graph, key, data) {
  const at = key.indexOf('::');
  const id = symbolId({ path: key.slice(0, at), sym: key.slice(at + 2) });
  if (id) graph.attachBody(id, data, symbolId);
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
  const changes = lineChanges();
  const list = [];
  for (const path of [...EDGES.keys()].sort()) for (const e of EDGES.get(path)) if (nodes.has(e.from) && nodes.has(e.to)) { e.diff = changes ? changes.statusOf(e) : null; list.push(e); }
  if (changes) for (const e of changes.removed) if (nodes.has(e.from) && nodes.has(e.to)) list.push(e);
  return list;
}
let LINE_CHANGES = null;
function lineChanges() {
  if (!DIFF || !DIFF.edges) return null;
  if (LINE_CHANGES && LINE_CHANGES.diff === DIFF) return LINE_CHANGES;
  const byFrom = new Map();
  for (const [from, to, change] of DIFF.edges.status) { if (!byFrom.has(from)) byFrom.set(from, new Map()); byFrom.get(from).set(to, change); }
  const table = DIFF.edges.removed;
  const removed = table.rows.map((row) => Object.assign(link(table.ids[row[0]], table.ids[row[1]], row[2], row[3]), { diff: 'removed' }));
  LINE_CHANGES = { diff: DIFF, removed, statusOf: (e) => (byFrom.has(e.from) && byFrom.get(e.from).get(e.to)) || null };
  return LINE_CHANGES;
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
