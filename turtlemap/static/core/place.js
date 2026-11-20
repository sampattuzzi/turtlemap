import { DIFF, OVERVIEW } from './data.js';
import { SETTINGS_KEY } from './settings.js';
export class PlaceMemory {
  constructor(view) {
    this.pending = view;
    this.timer = null;
  }
  remember(trail, vp) {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => { if (!this.pending) savePlace(placeOf(trail, vp)); }, 250);
  }
  restore(vp) {
    if (!this.pending) return;
    Object.assign(vp, { x: this.pending.x, y: this.pending.y, s: this.pending.s });
    this.pending = null;
    vp.apply();
  }
  forget() { this.pending = null; }
}
export function loadPlace() { try { return JSON.parse(localStorage.getItem(placeKey()) || 'null'); } catch (e) { return null; } }
function savePlace(place) { try { localStorage.setItem(placeKey(), JSON.stringify(place)); } catch (e) {} }
function placeKey() { return `${SETTINGS_KEY}-place:${OVERVIEW ? OVERVIEW.root : ''}|${DIFF ? DIFF.spec : ''}`; }
function placeOf(trail, vp) {
  const c = trail.current;
  return {
    entry: { view: c.view, path: c.path, sym: c.sym, focus: c.focus, related: c.related, expanded: c.expanded ? [...c.expanded] : undefined, open: [...(c.open || [])] },
    selected: trail.selectedId(),
    view: { x: vp.x, y: vp.y, s: vp.s },
  };
}
