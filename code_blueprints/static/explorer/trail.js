import { DIFF, lookup, net } from '../core/data.js';
import { startExpanded } from '../map/focus.js';
class Trail {
  constructor(start) {
    this.start = start;
    this.entries = [start];
    this.ahead = [];
    this.selected = null;
  }
  get current() { return this.entries[this.entries.length - 1]; }
  get canGoBack() { return this.entries.length > 1; }
  get canGoForward() { return this.ahead.length > 0; }
  lastMap() { return [...this.entries].reverse().find((e) => e.view === 'net') || this.start; }
  selectedId() { return typeof this.selected === 'string' ? this.selected : null; }
  push(entry, selected = null) {
    this.entries.push(entry);
    this.ahead = [];
    this.selected = selected;
  }
  back() {
    if (!this.canGoBack) return false;
    this.ahead.push(this.entries.pop());
    this.selected = null;
    return true;
  }
  forward() {
    if (!this.canGoForward) return false;
    this.entries.push(this.ahead.pop());
    this.selected = null;
    return true;
  }
}
export function startingTrail(saved) {
  const expanded = startExpanded();
  const focus = firstChangeFocus(expanded);
  const trail = new Trail({ view: 'net', expanded, focus: focus ? focus.id : null, open: new Set() });
  const restored = saved && restoredEntry(saved.entry);
  if (restored) {
    trail.entries.push(restored);
    if (typeof saved.selected === 'string' && net().nodes.has(saved.selected)) trail.selected = saved.selected;
  }
  return { trail, restored };
}
function firstChangeFocus(expanded) {
  const firstChange = DIFF && Object.keys(DIFF.files).sort()[0];
  if (!firstChange) return null;
  const id = `mod:${firstChange}`;
  const shown = (n) => (n.id === id ? net().chain(n.id).slice(1, -1).every((a) => expanded.has(a.id)) : expanded.has(n.id));
  return [...net().chain(id)].reverse().find(shown);
}
function restoredEntry(entry) {
  if (!entry || typeof entry !== 'object') return null;
  const open = new Set(Array.isArray(entry.open) ? entry.open : []);
  const restore = RESTORERS.get(entry.view);
  return restore ? restore(entry, open) : null;
}
const RESTORERS = new Map([['fn', restoredFunction], ['data', restoredData], ['net', restoredMap]]);
function restoredFunction(entry, open) {
  const named = typeof entry.path === 'string' && typeof entry.sym === 'string';
  const sym = named ? lookup({ path: entry.path, sym: entry.sym }) : null;
  return sym && sym.kind === 'function' ? { view: 'fn', path: entry.path, sym: entry.sym, open } : null;
}
function restoredData(entry, open) {
  return entry.scope === 'root' || net().nodes.has(entry.scope) ? { view: 'data', scope: entry.scope, open } : null;
}
function restoredMap(entry, open) {
  if (!Array.isArray(entry.expanded)) return null;
  const known = (id) => typeof id === 'string' && net().nodes.has(id);
  return { view: 'net', expanded: new Set(entry.expanded.filter(known)), focus: known(entry.focus) ? entry.focus : null, related: known(entry.related) ? entry.related : null, open };
}
