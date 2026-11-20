import { SETTINGS_KEY, settings } from './settings.js';
export const LINE_KINDS = [
  { key: 'inherits', label: 'inherits', legend: 'builds on (inherits)', dashed: false },
  { key: 'realizes', label: 'implements', legend: 'implements a protocol', dashed: true },
  { key: 'bound', label: 'stands for', legend: 'type parameter stands for any of these', dashed: false },
  { key: 'has', label: 'has a field of', legend: 'has a field of that type', dashed: false },
  { key: 'creates', label: 'creates', legend: 'creates one', dashed: true },
  { key: 'calls', label: 'calls', legend: 'calls it', dashed: true },
  { key: 'writes', label: 'writes a field', legend: 'sets a field (inside a class)', dashed: true },
  { key: 'reads', label: 'reads a field', legend: 'reads a field (inside a class)', dashed: true },
  { key: 'uses', label: 'takes or returns', legend: 'takes or returns it', dashed: true },
];
export const BOX_KINDS = [
  { key: 'data', label: 'Data classes', colour: '--h-struct' },
  { key: 'enum', label: 'Enums', colour: '--h-enum' },
  { key: 'iface', label: 'Interfaces', colour: '--h-iface' },
  { key: 'class', label: 'Other classes', colour: '--h-break' },
  { key: 'function', label: 'Functions', colour: '--h-call' },
  { key: 'method', label: 'Methods', colour: '--h-method' },
  { key: 'field', label: 'Fields', colour: '--h-break' },
  { key: 'constant', label: 'Constants', colour: '--h-var' },
  { key: 'typevar', label: 'Type variables', colour: '--rel-bound' },
  { key: 'library', label: 'Libraries', colour: '--h-lib' },
];
const EVERY_BOX = BOX_KINDS.map((b) => b.key);
const EVERY_LINE = LINE_KINDS.map((l) => l.key);
export const PRESETS = [
  { key: 'all', label: 'Everything', hint: 'all of it', boxes: EVERY_BOX, lines: EVERY_LINE },
  { key: 'data', label: 'Data', hint: 'classes that hold data', boxes: ['data', 'enum', 'field'], lines: ['inherits', 'realizes', 'has'] },
  { key: 'inheritance', label: 'Inheritance', hint: 'what builds on what', boxes: ['data', 'enum', 'iface', 'class', 'typevar'], lines: ['inherits', 'realizes', 'bound'] },
  { key: 'execution', label: 'Execution', hint: 'what calls what', boxes: ['function', 'method', 'library'], lines: ['calls', 'creates'] },
];
const CONTAINERS = new Set(['root', 'package', 'module']);
const LIBRARY_PARTS = new Set(['library', 'libmodule', 'name']);
const MEMBERS = new Set(['field', 'member']);
const SHOWN_ANYWAY = new Set();
let PROJECT = '';
let STATE = null;
export function filterProject(root) { PROJECT = root || ''; STATE = null; SHOWN_ANYWAY.clear(); }
export function currentFilter() {
  if (!STATE) STATE = { ...presetState('all'), ...constantsLeftOff(), fade: false, keep: true, ...savedFilter() };
  return STATE;
}
export function changeFilter(change) {
  Object.assign(currentFilter(), change);
  SHOWN_ANYWAY.clear();
  try { localStorage.setItem(filterKey(), JSON.stringify(STATE)); } catch (e) {}
}
export function choosePreset(key) { changeFilter({ ...presetState(key), base: key }); }
export function toggleKind(group, key, on) {
  const now = new Set(currentFilter()[group]);
  if (on) now.add(key); else now.delete(key);
  changeFilter({ [group]: [...now] });
}
export function onlyLine(key) { changeFilter({ lines: [key] }); }
export function showAnyway(ids) { ids.forEach((id) => SHOWN_ANYWAY.add(id)); }
export function presetKey(f = currentFilter()) {
  const found = PRESETS.find((p) => sameKinds(p.boxes, f.boxes) && sameKinds(p.lines, f.lines));
  return found ? found.key : 'custom';
}
export function filterName(f = currentFilter()) {
  const key = presetKey(f);
  return key === 'custom' ? 'Custom' : PRESETS.find((p) => p.key === key).label;
}
export function customChanges(f = currentFilter()) {
  const base = PRESETS.find((p) => p.key === f.base) || PRESETS[0];
  const words = [...kindChanges(base.boxes, f.boxes, BOX_KINDS, (b) => b.label.toLowerCase()), ...kindChanges(base.lines, f.lines, LINE_KINDS, (l) => l.label)];
  return `${base.label}${words.length > 3 ? ` with ${words.length} changes` : words.join('')}`;
}
export function boxKindOf(n) {
  if (CONTAINERS.has(n.kind)) return 'container';
  if (LIBRARY_PARTS.has(n.kind)) return 'library';
  if (MEMBERS.has(n.kind)) return 'field';
  if (n.kind !== 'class') return n.kind;
  if (n.sym.kind === 'enum') return 'enum';
  return n.sym.cat === 'struct' ? 'data' : n.sym.cat === 'iface' ? 'iface' : 'class';
}
export function kindCounts(nodes, edges) {
  const boxes = new Map(), lines = new Map();
  for (const n of nodes.values()) { const k = boxKindOf(n); boxes.set(k, (boxes.get(k) || 0) + (k === 'library' && n.kind !== 'library' ? 0 : 1)); }
  for (const e of edges) for (const k of e.kinds) lines.set(k, (lines.get(k) || 0) + 1);
  return { boxes, lines };
}
export function filterNet(root, nodes, edges) {
  const f = currentFilter();
  if (presetKey(f) === 'all') return { edges, autoOpen: new Set() };
  const boxes = new Set(f.boxes), lines = new Set(f.lines);
  const chosen = new Set([...nodes.values()].filter((n) => SHOWN_ANYWAY.has(n.id) || isChosen(n, boxes)).map((n) => n.id));
  const shownEdges = edges.flatMap((e) => {
    const kinds = new Set([...e.kinds].filter((k) => lines.has(k)));
    const ends = Number(chosen.has(e.from)) + Number(chosen.has(e.to));
    return kinds.size && (ends === 2 || (f.keep && ends === 1 && rescuable(nodes.get(chosen.has(e.from) ? e.to : e.from)))) ? [{ ...e, kinds, kind: EVERY_LINE.find((k) => kinds.has(k)) }] : [];
  });
  const shown = withAncestors(nodes, [...chosen, ...shownEdges.flatMap((e) => [e.from, e.to])]);
  for (const n of nodes.values()) n.faded = !CONTAINERS.has(n.kind) && !chosen.has(n.id) && (f.fade || shown.has(n.id));
  if (!f.fade) prune(root, nodes, shown);
  const autoOpen = new Set([...nodes.values()].filter((n) => n.kind === 'class' && n.children.length && n.children.every((k) => MEMBERS.has(k.kind))).map((n) => n.id));
  return { edges: shownEdges, autoOpen };
}
function isChosen(n, boxes) {
  const kind = boxKindOf(n);
  if (kind === 'container') return false;
  if (kind === 'field') return boxes.has('field') && boxes.has(boxKindOf(n.parent));
  if (n.kind === 'class') return boxes.has(kind) || (boxes.has('method') && n.children.some((k) => k.kind === 'method'));
  return boxes.has(kind);
}
function rescuable(n) { return n.kind !== 'constant'; }
function withAncestors(nodes, ids) {
  const shown = new Set(['root']);
  for (const id of ids) for (let n = nodes.get(id); n && !shown.has(n.id); n = n.parent) shown.add(n.id);
  return shown;
}
function prune(n, nodes, shown) {
  const kept = n.children.filter((k) => shown.has(k.id));
  if (kept.length < n.children.length) n.pruned = true;
  for (const k of n.children) if (!shown.has(k.id)) dropSubtree(k, nodes);
  n.children = kept;
  for (const k of kept) prune(k, nodes, shown);
}
function dropSubtree(n, nodes) {
  nodes.delete(n.id);
  for (const k of n.children) dropSubtree(k, nodes);
}
function presetState(key) {
  const p = PRESETS.find((x) => x.key === key) || PRESETS[0];
  return { boxes: [...p.boxes], lines: [...p.lines], base: p.key };
}
function constantsLeftOff() {
  return settings.constants === false ? { boxes: EVERY_BOX.filter((k) => k !== 'constant') } : {};
}
function savedFilter() {
  try {
    const saved = JSON.parse(localStorage.getItem(filterKey()) || '{}');
    const known = (list, all) => (Array.isArray(list) ? list.filter((k) => all.includes(k)) : undefined);
    const out = { boxes: known(saved.boxes, EVERY_BOX), lines: known(saved.lines, EVERY_LINE), base: PRESETS.some((p) => p.key === saved.base) ? saved.base : undefined, fade: typeof saved.fade === 'boolean' ? saved.fade : undefined, keep: typeof saved.keep === 'boolean' ? saved.keep : undefined };
    return Object.fromEntries(Object.entries(out).filter(([, v]) => v !== undefined));
  } catch (e) { return {}; }
}
function filterKey() { return `${SETTINGS_KEY}-filter:${PROJECT}`; }
function sameKinds(a, b) { return a.length === b.length && a.every((k) => b.includes(k)); }
function kindChanges(base, now, all, word) {
  return all.flatMap((k) => (now.includes(k.key) && !base.includes(k.key) ? [` + ${word(k)}`] : !now.includes(k.key) && base.includes(k.key) ? [` − ${word(k)}`] : []));
}
