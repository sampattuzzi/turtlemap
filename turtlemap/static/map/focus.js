import { DIFF, clearNetCache, isTestPath, net } from '../core/data.js';
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
export function netDefaultExpanded(path) { const n = net().nodes.get(`mod:${path}`); return new Set(n ? net().chain(n.id).slice(1).map((x) => x.id) : []); }
const SIDE_PACKAGES = /^(tests?|testing|docs?|examples?|scripts?|benchmarks?|tools?|\.?venv|build|dist)$/i;
function moduleCount(n) { return n.kind === 'module' ? 1 : n.children.reduce((sum, k) => sum + (k.kind === 'package' || k.kind === 'module' ? moduleCount(k) : 0), 0); }
export function startExpanded() {
  const changed = DIFF ? changedExpansion(Object.keys(DIFF.files)) : null;
  if (changed && changed.size) return changed;
  const ex = new Set();
  let n = net().root;
  for (let i = 0; i < 8; i++) {
    const pick = dominantChild(n);
    if (!pick || !pick.children.length || (pick.kind === 'module' && ex.size)) break;
    ex.add(pick.id);
    n = pick;
    if (codeChildren(pick).length > 1) break;
  }
  return ex;
}
function changedExpansion(changed) {
  const ex = new Set();
  for (const path of changed) {
    const chain = net().chain(`mod:${path}`);
    for (const n of chain.slice(1, changed.length <= 12 ? undefined : -1)) if (n.children.length) ex.add(n.id);
  }
  return ex;
}
function codeChildren(n) {
  return n.children.filter((k) => k.kind === 'package' || k.kind === 'module');
}
function dominantChild(n) {
  const main = codeChildren(n).filter((k) => !SIDE_PACKAGES.test(k.name)).sort((a, b) => moduleCount(b) - moduleCount(a));
  if (main.length === 1) return main[0];
  return main.length > 1 && moduleCount(main[0]) > 0.6 * main.reduce((s, k) => s + moduleCount(k), 0) ? main[0] : null;
}
