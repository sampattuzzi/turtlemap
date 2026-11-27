import { DIFF, lookup, net } from '../core/data.js';
import { startFolded } from '../map/focus.js';
import { LIBRARIES } from '../map/packages.js';
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
  const folded = startFolded();
  const focus = firstChangeFocus(folded);
  const trail = new Trail({ view: 'net', folded, focus: focus ? focus.id : null, open: new Set() });
  const restored = saved && restoredEntry(saved.entry);
  if (restored) {
    trail.entries.push(restored);
    if (typeof saved.selected === 'string' && net().nodes.has(saved.selected)) trail.selected = saved.selected;
  }
  return { trail, restored };
}
function firstChangeFocus(folded) {
  const firstChange = DIFF && Object.keys(DIFF.files).sort()[0];
  if (!firstChange) return null;
  const chain = net().chain(`mod:${firstChange}`).slice(1);
  const hidden = chain.findIndex((n) => folded.has(n.id));
  return hidden < 0 ? chain[chain.length - 1] : chain[hidden];
}
function restoredEntry(entry) {
  if (!entry || typeof entry !== 'object') return null;
  const open = new Set(Array.isArray(entry.open) ? entry.open : []);
  const restore = RESTORERS.get(entry.view);
  return restore ? restore(entry, open) : null;
}
const RESTORERS = new Map([['fn', restoredFunction], ['net', restoredMap]]);
function restoredFunction(entry, open) {
  const named = typeof entry.path === 'string' && typeof entry.sym === 'string';
  const sym = named ? lookup({ path: entry.path, sym: entry.sym }) : null;
  return sym && sym.kind === 'function' ? { view: 'fn', path: entry.path, sym: entry.sym, open } : null;
}
function restoredMap(entry, open) {
  if (!Array.isArray(entry.folded)) return null;
  const known = (id) => typeof id === 'string' && net().allIds.has(id);
  return { view: 'net', folded: new Set(entry.folded.filter((id) => id === LIBRARIES || known(id))), focus: known(entry.focus) ? entry.focus : null, related: known(entry.related) ? entry.related : null, open };
}
