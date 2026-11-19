import { DIFF, FILES, lookup } from './data.js';
import { apiPost, el } from './dom.js';
export function fileDiff(path) { return DIFF && DIFF.files[path] ? DIFF.files[path].status : null; }
export function folderDiff(prefix) {
  if (!DIFF) return null;
  const inside = Object.keys(FILES).filter((p) => p.startsWith(`${prefix}/`));
  const states = inside.map(fileDiff).filter(Boolean);
  if (!states.length) return null;
  if (states.length === inside.length && states.every((s) => s === states[0]) && states[0] !== 'modified') return states[0];
  return 'modified';
}
export function symbolDiff(ref) {
  if (!DIFF || !ref) return null;
  const sym = lookup(ref);
  const kind = sym && sym.kind !== 'function' ? 'cls' : sym && sym.owner ? 'm' : 'fn';
  return DIFF.status[`${kind}:${ref.path}:${ref.sym}`] || null;
}
let SEEN = new Set();
let SEEN_REQUEST = 0;
let onSeenChanged = () => {};
export function setSeen(ids) { SEEN = ids; }
export function setSeenListener(listener) { onSeenChanged = listener; }
export function fileUnits(path) { return (DIFF && DIFF.units[path]) || []; }
export function unitsUnder(prefix) { return DIFF ? Object.keys(DIFF.files).filter((p) => p.startsWith(`${prefix}/`)).flatMap(fileUnits) : []; }
export function symbolUnits(ref) {
  const sym = lookup(ref);
  if (!sym) return [];
  if (sym.kind === 'function') return fileUnits(ref.path).filter((u) => u.qual === ref.sym && u.kind !== 'body');
  return fileUnits(ref.path).filter((u) => u.owner === ref.sym || (u.owner || '').startsWith(`${ref.sym}.`));
}
export function seenCount(units) { return units.reduce((n, u) => n + (SEEN.has(u.id) ? 1 : 0), 0); }
export function seenState(units) {
  if (!units.length) return null;
  const n = seenCount(units);
  return n === 0 ? 'none' : n === units.length ? 'all' : 'some';
}
async function markSeen(units, seen) {
  const ids = units.map((u) => u.id);
  const before = new Set(SEEN);
  for (const id of ids) { if (seen) SEEN.add(id); else SEEN.delete(id); }
  onSeenChanged();
  const request = ++SEEN_REQUEST;
  try {
    const result = await apiPost('/api/seen', { ids, seen });
    if (request === SEEN_REQUEST) SEEN = new Set(result.seen);
  } catch (error) {
    if (request === SEEN_REQUEST) SEEN = before;
    console.warn('Could not save what you have seen', error);
  }
  if (request === SEEN_REQUEST) onSeenChanged();
}
export function seenBox(units, what) {
  const state = seenState(units);
  const box = el('input', { type: 'checkbox', class: 'seen-box', title: state === 'all' ? `Mark ${what} as not seen` : `Mark ${what} as seen`, 'aria-label': `${what} seen` });
  box.checked = state === 'all';
  box.indeterminate = state === 'some';
  box.addEventListener('click', (e) => e.stopPropagation());
  box.addEventListener('change', () => markSeen(units, state !== 'all'));
  return box;
}
export function seenMark(units) { return seenState(units) === 'all' ? el('span', { class: 'seen-mark', title: 'Seen' }, '✓') : null; }
