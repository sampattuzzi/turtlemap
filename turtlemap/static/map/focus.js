import { DIFF, clearNetCache, isTestPath, net } from '../core/data.js';
import { LIBRARIES, moduleCount } from './packages.js';
import { showAnyway } from '../core/filters.js';
import { saveSettings, settings } from '../core/settings.js';
export function resetNet() { clearNetCache(); FOCUS_CACHE.clear(); }
export function revealHidden(ids) {
  const N = net();
  const missing = ids.filter((id) => !N.nodes.has(id));
  if (!missing.length) return;
  if (missing.some((id) => isTestPath(id.slice(id.indexOf(':') + 1).split(':')[0]))) { settings.tests = true; saveSettings(); }
  showAnyway(missing);
  resetNet();
}
const UNIT_KINDS = new Set(['module', 'libmodule']);
export function focusUnitOf(id) {
  const chain = net().chain(id);
  if (!chain.length || id === 'root') return null;
  const unit = [...chain].reverse().find((n) => UNIT_KINDS.has(n.kind));
  return unit ? unit.id : id;
}
export const FOCUS_CACHE = new Map();
export function relatedTo(unitId) {
  const N = net();
  if (!unitId || !N.nodes.has(unitId)) return null;
  if (FOCUS_CACHE.has(unitId)) return FOCUS_CACHE.get(unitId);
  const unit = N.nodes.get(unitId);
  const inside = (id) => N.chain(id).includes(unit);
  const related = new Set();
  for (const e of N.edges) {
    const a = inside(e.from), b = inside(e.to);
    if (a && !b) related.add(focusUnitOf(e.to));
    else if (b && !a) related.add(focusUnitOf(e.from));
  }
  related.delete(null);
  const units = new Set([unitId, ...related]);
  const shown = new Set();
  for (const id of units) for (const n of N.chain(id)) shown.add(n.id);
  const filter = { unit: unitId, related, units, shown, visible: (n) => shown.has(n.id) || N.chain(n.id).some((a) => units.has(a.id)) };
  FOCUS_CACHE.set(unitId, filter);
  return filter;
}
const SIDE_PACKAGES = /^(tests?|testing|docs?|examples?|scripts?|benchmarks?|tools?|\.?venv|build|dist)$/i;
const MODULES_AT_FIRST = 60;
const MODULES_AT_LEAST = 15;
export function startFolded() {
  const N = net();
  const changed = DIFF ? new Set(Object.keys(DIFF.files).map((path) => `mod:${path}`)) : new Set();
  const packages = [...N.nodes.values()].filter((n) => n.kind === 'package');
  const holdsChange = (p) => [...changed].some((id) => N.contains(p.id, id));
  const order = packages.sort((a, b) => Number(holdsChange(a)) - Number(holdsChange(b)) || Number(SIDE_PACKAGES.test(b.name)) - Number(SIDE_PACKAGES.test(a.name)) || b.depth - a.depth || moduleCount(b) - moduleCount(a));
  const folded = new Set([LIBRARIES]);
  let shown = [...N.nodes.values()].filter((n) => n.kind === 'module').length + 1;
  for (const p of order) {
    if (shown <= MODULES_AT_FIRST) break;
    const inside = shownInside(p, folded);
    if (N.chain(p.id).some((a) => folded.has(a.id)) || shown - inside + 1 < MODULES_AT_LEAST) continue;
    shown -= inside - 1;
    for (const q of packages) if (N.contains(p.id, q.id)) folded.delete(q.id);
    folded.add(p.id);
  }
  return folded;
}
function shownInside(p, folded) {
  return p.children.reduce((sum, k) => sum + (k.kind === 'module' ? 1 : k.kind === 'package' ? (folded.has(k.id) ? 1 : shownInside(k, folded)) : 0), 0);
}
