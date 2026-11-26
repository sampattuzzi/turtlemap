import { renderCommentList } from '../comments/list.js';
import { openThreads } from '../comments/store.js';
import { DIFF, FILES, OVERVIEW, lookup } from '../core/data.js';
import { baseName, el } from '../core/dom.js';
import { fileDiff, fileUnits, folderDiff, seenBox, seenCount, seenMark, seenState, symbolDiff, symbolUnits, unitsUnder } from '../core/review.js';
import { SETTINGS_KEY } from '../core/settings.js';
import { DIFF_WORD, diffBadge, plural, refOf } from '../map/boxes.js';
const SIDE_TAB_KEY = `${SETTINGS_KEY}-side-tab`;
let SIDE_TAB = (() => { try { return localStorage.getItem(SIDE_TAB_KEY) || 'changes'; } catch (e) { return 'changes'; } })();
let SIDE_SHOWN = null;
export function renderSide(left, place) {
  const { currentPath, currentSym, currentFolder } = place;
  const scroll = left.scrollTop;
  left.innerHTML = '';
  const redraw = () => renderSide(left, place);
  const tab = SIDE_TAB === 'changes' && !DIFF ? 'files' : SIDE_TAB;
  const pick = (name) => { SIDE_TAB = name; try { localStorage.setItem(SIDE_TAB_KEY, name); } catch (e) {} left.scrollTop = 0; redraw(); };
  const tabButton = (name, label, title, count) => el('button', { class: `side-tab ${tab === name ? 'on' : ''}`, role: 'tab', 'aria-selected': String(tab === name), title, onclick: () => pick(name) }, label, count != null ? el('small', {}, count) : null);
  const all = DIFF ? Object.keys(DIFF.files).flatMap(fileUnits) : [];
  const openCount = openThreads().length;
  left.append(el('div', { class: 'side-tabs', role: 'tablist' },
    tabButton('files', 'Files', 'Every file in the project'),
    DIFF ? tabButton('changes', 'Changes', `${seenCount(all)} of ${all.length} changes seen`, `${seenCount(all)}/${all.length}`) : null,
    tabButton('comments', 'Comments', `${plural(openCount, 'open comment')}`, openCount || null)));
  if (tab === 'changes') renderChanges(left, place);
  else if (tab === 'comments') renderCommentList(left);
  else renderFiles(left, place);
  left.scrollTop = scroll;
  const shown = `${tab}|${currentPath}|${currentSym}|${currentFolder}`;
  if (shown !== SIDE_SHOWN) { SIDE_SHOWN = shown; const active = left.querySelector('.active'); if (active) active.scrollIntoView({ block: 'nearest' }); }
}
function renderFiles(left, here) {
  const { currentPath, currentSym, currentFolder, onPick } = here;
  left.append(el('h3', {}, OVERVIEW ? OVERVIEW.name : 'Files'));
  const box = el('div', { class: 'tree' });
  drawFileTree(box, pathTree(Object.keys(FILES)), '', 0, here);
  left.append(box);
  const f = currentPath ? FILES[currentPath] : null;
  if (!f) return;
  left.append(el('h3', {}, `In ${baseName(currentPath)}`));
  for (const s of f.symbols) {
    left.append(symbolButton(s, s.kind === 'function' ? '--h-call' : s.kind === 'enum' ? '--h-enum' : '--h-make', null, currentSym, onPick));
    for (const m of s.methods || []) left.append(symbolButton(m, '--h-method', 'padding-left:32px', currentSym, onPick));
  }
}
function drawFileTree(box, node, prefix, depth, view) {
  for (const name of Object.keys(node.dirs).sort()) {
    const full = prefix ? `${prefix}/${name}` : name;
    box.append(folderRow(name, full, depth, view));
    if (view.folds.isOpen(`pkg:${full}`)) drawFileTree(box, node.dirs[name], full, depth + 1, view);
  }
  for (const path of node.files.sort()) box.append(fileButton(path, depth, view));
}
function folderRow(name, full, depth, { currentFolder, onPick, folds }) {
  const isOpen = folds.isOpen(`pkg:${full}`);
  const active = full === currentFolder;
  const state = folderDiff(full);
  const toggle = () => folds.toggle(`pkg:${full}`);
  return el('div', { class: `tree-row${active ? ' active' : ''}`, style: `padding-left:${10 + depth * 14}px` },
    el('button', { class: 'chev', title: isOpen ? 'Collapse' : 'Expand', onclick: toggle }, isOpen ? '▾' : '▸'),
    el('button', { class: `tree-item folder${active ? ' active' : ''}${state ? ` diff-${state}` : ''}`, title: `Show ${full}/ on the map`, onclick: () => onPick({ folder: full }) }, `${name}/`, diffBadge(state)));
}
function fileButton(path, depth, { currentPath, onPick }) {
  const state = fileDiff(path);
  return el('button', { class: `tree-item ${path === currentPath ? 'active' : ''}${state ? ` diff-${state}` : ''}`, style: `padding-left:${33 + depth * 14}px`, title: state ? `${path} (${DIFF_WORD[state]})` : path, onclick: () => onPick({ path, sym: null }) }, baseName(path), seenMark(fileUnits(path)), diffBadge(state));
}
function symbolButton(sym, colour, style, currentSym, onPick) {
  const ref = refOf(sym);
  const state = symbolDiff(ref);
  return el('button', { class: `tree-item ${currentSym === sym.qual ? 'active' : ''}${state ? ` diff-${state}` : ''}`, style, onclick: () => onPick(refOf(sym)) }, el('span', { class: 'dot', style: `background:var(${colour})` }), sym.name, seenMark(symbolUnits(refOf(sym))), diffBadge(state));
}
function pathTree(paths) {
  const root = { dirs: {}, files: [] };
  for (const path of paths) {
    let node = root;
    for (const part of path.split('/').slice(0, -1)) node = node.dirs[part] = node.dirs[part] || { dirs: {}, files: [] };
    node.files.push(path);
  }
  return root;
}
function reviewRow({ depth, units, what, chevron, onChevron, label, onClick, active, state, title }) {
  const seen = seenState(units) === 'all';
  return el('div', { class: `tree-row${active ? ' active' : ''}${seen ? ' seen' : ''}`, style: `padding-left:${8 + depth * 14}px` },
    chevron ? el('button', { class: 'chev', title: chevron === '▾' ? 'Collapse' : 'Expand', onclick: onChevron }, chevron) : el('span', { class: 'chev' }),
    seenBox(units, what),
    el('button', { class: `tree-item${active ? ' active' : ''}${state ? ` diff-${state}` : ''}`, title: title || what, onclick: onClick }, ...label, units.length > 1 ? el('span', { class: 'count' }, `${seenCount(units)}/${units.length}`) : null, diffBadge(state)));
}
function renderChanges(left, here) {
  const paths = Object.keys(DIFF.files).sort();
  const all = paths.flatMap(fileUnits);
  const done = seenCount(all);
  left.append(el('div', { class: 'review-progress' },
    el('div', { class: 'review-bar' }, el('span', { style: `width:${all.length ? (100 * done) / all.length : 0}%` })),
    el('span', {}, all.length ? `${done} of ${all.length} changes seen` : 'Nothing changed')));
  const tree = new ChangeTree(here);
  tree.draw(pathTree(paths), '', 0);
  left.append(tree.box);
}
class ChangeTree {
  constructor({ currentPath, currentSym, currentFolder, onPick, folds }) {
    Object.assign(this, { currentPath, currentSym, currentFolder, onPick, folds });
    this.box = el('div', { class: 'tree' });
  }
  draw(node, prefix, depth) {
    for (const first of Object.keys(node.dirs).sort()) this.folder(node, first, prefix, depth);
    for (const path of node.files) this.file(path, depth);
  }
  folder(node, first, prefix, depth) {
    let name = first, full = prefix ? `${prefix}/${first}` : first, inner = node.dirs[first];
    while (!inner.files.length && Object.keys(inner.dirs).length === 1) { const only = Object.keys(inner.dirs)[0]; name += `/${only}`; full += `/${only}`; inner = inner.dirs[only]; }
    const isOpen = this.folds.isOpen(`pkg:${full}`);
    const toggle = () => this.folds.toggle(`pkg:${full}`);
    this.box.append(reviewRow({ depth, units: unitsUnder(full), what: `everything in ${full}/`, chevron: isOpen ? '▾' : '▸', onChevron: toggle, label: [el('span', { class: 'label folder-name' }, `${name}/`)], onClick: () => this.onPick({ folder: full }), active: full === this.currentFolder, title: `Show ${full}/ on the map` }));
    if (isOpen) this.draw(inner, full, depth + 1);
  }
  file(path, depth) {
    const units = fileUnits(path);
    const isOpen = this.folds.isOpen(`mod:${path}`);
    const info = DIFF.files[path];
    this.box.append(reviewRow({ depth, units, what: baseName(path), chevron: isOpen ? '▾' : '▸', onChevron: () => this.folds.toggle(`mod:${path}`), label: [el('span', { class: 'label' }, baseName(path))], onClick: () => this.onPick({ path, sym: null }), active: path === this.currentPath && !this.currentSym, state: info.status, title: info.oldPath ? `${path} (renamed from ${info.oldPath})` : path }));
    if (isOpen) this.units(path, units, depth + 1);
  }
  units(path, units, depth) {
    const emitted = new Set();
    for (const unit of units) {
      if (!unit.owner) { this.box.append(this.unitRow(path, unit, depth)); continue; }
      if (emitted.has(unit.owner)) continue;
      emitted.add(unit.owner);
      const members = units.filter((u) => u.owner === unit.owner);
      const owner = { path, sym: unit.owner };
      const id = `cls:${path}:${unit.owner}`, isOpen = this.folds.isOpen(id);
      this.box.append(reviewRow({ depth, units: members, what: `class ${unit.owner}`, chevron: isOpen ? '▾' : '▸', onChevron: () => this.folds.toggle(id), label: [el('span', { class: 'dot', style: 'background:var(--h-make)' }), el('span', { class: 'label' }, unit.owner)], onClick: () => this.onPick(owner), active: path === this.currentPath && this.currentSym === unit.owner, state: symbolDiff(owner) || unit.diff }));
      if (isOpen) for (const member of members) this.box.append(this.unitRow(path, member, depth + 1));
    }
  }
  unitRow(path, unit, depth) {
    const plainText = unit.kind === 'top' || unit.kind === 'body';
    const name = unit.kind === 'top' ? 'Module-level code' : unit.kind === 'body' ? 'Class body' : unit.owner ? unit.qual.slice(unit.owner.length + 1) : unit.qual;
    const target = { path, sym: unit.kind === 'top' ? null : unit.kind === 'body' ? unit.owner : unit.qual };
    const dot = plainText ? null : el('span', { class: 'dot', style: `background:var(${unit.owner ? '--h-method' : '--h-call'})` });
    return reviewRow({ depth, units: [unit], what: plainText ? `${name.toLowerCase()} of ${unit.owner || baseName(path)}` : name, label: [dot, el('span', { class: `label${plainText ? ' unit-note' : ''}` }, name)], onClick: () => this.onPick(target), active: !plainText && path === this.currentPath && this.currentSym === unit.qual, state: unit.diff });
  }
}
export function crumbsFor(crumbs, path, sym, onPick, extra) {
  crumbs.innerHTML = '';
  if (!path) { crumbs.append(el('span', { class: 'here' }, OVERVIEW ? OVERVIEW.name : '')); if (extra) crumbs.append(extra); return; }
  if (path.includes('/')) crumbs.append(el('span', {}, path.split('/').slice(-3, -1).join('/') + '/'));
  crumbs.append(el('button', { onclick: () => onPick({ path, sym: null }) }, baseName(path)));
  if (sym) { const s = lookup({ path, sym }); if (s && s.owner) crumbs.append(el('span', {}, '›'), el('button', { onclick: () => onPick({ path, sym: s.owner }) }, s.owner)); crumbs.append(el('span', {}, '›'), el('span', { class: 'here' }, s ? s.name : sym)); }
  if (extra) crumbs.append(extra);
}
