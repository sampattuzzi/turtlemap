import { codePanel } from '../blueprint/codepanel.js';
import { BlueprintControls, nodesOnLine } from '../blueprint/controls.js';
import { buildFunctionScene } from '../blueprint/nodes.js';
import { boundsOf, flash, messageScene } from '../canvas/scene.js';
import { Viewport } from '../canvas/viewport.js';
import { setCommentPick } from '../comments/store.js';
import { CommentControls } from '../comments/controls.js';
import { FUNCTIONS, fnKey, lookup, net } from '../core/data.js';
import { baseName, el } from '../core/dom.js';
import { PlaceMemory, loadPlace } from '../core/place.js';
import { ensureFunction } from '../core/project.js';
import { fileUnits, seenBox, setSeenListener, symbolUnits } from '../core/review.js';
import { crumbsFor, renderSide } from './sidebar.js';
import { filterButton, filterChip, labelFilterButton, lineFilter } from './filtermenu.js';
import { shell } from './toolbar.js';
import { startingTrail } from './trail.js';
import { netLabel, plural, refOf } from '../map/boxes.js';
import { focusUnitOf, relatedTo, resetNet, revealHidden } from '../map/focus.js';
import { LIBRARIES, buildPackageScene } from '../map/packages.js';
import { netPanel } from '../map/panel.js';
export class Explorer {
  constructor(root, session) {
    this.session = session;
    const saved = loadPlace();
    const { trail, restored } = startingTrail(saved);
    this.trail = trail;
    this.place = new PlaceMemory(restored && saved.view && Number.isFinite(saved.view.s) ? saved.view : null);
    this.scene = null;
    this.relayouts = 0;
    this.goTo = (ref) => this.go(ref);
    this.buttons = explorerButtons(this);
    const b = this.buttons;
    this.ui = shell(root, { extraButtons: [b.openOther, b.reload, b.back, b.forward, b.foldAll, b.filter], onPick: this.goTo, onSettings: () => this.render(true), onCompared: () => session.waitForProject(), lineFilter: lineFilter(() => this.filterChanged()) });
    this.vp = new Viewport(this.ui.vpHost);
    this.vp.onMoved = () => this.rememberPlace();
    this.vp.onBackground = () => this.clearSelection();
    this.blueprints = new BlueprintControls(this);
    this.netCtx = this.mapContext();
    setSeenListener(() => this.chrome());
    this.ui.crumbs.after(el('span', { id: 'agent-chip', class: 'agent-chip', hidden: true }));
    this.comments = new CommentControls(this);
    this.render(false);
  }
  keys(e) {
    if (e.altKey && e.key === 'ArrowLeft') this.buttons.back.click();
    if (e.altKey && e.key === 'ArrowRight') this.buttons.forward.click();
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    this.comments.keys(e);
  }
  step(moved) {
    if (!moved) return;
    setCommentPick(null);
    this.render(false);
  }
  open(entry, selected = null) {
    this.trail.push(entry, selected);
    this.render(false);
  }
  go(ref) {
    setCommentPick(null);
    if (ref.folder) { this.goToFolder(ref.folder); return; }
    const sym = ref.sym ? lookup(ref) : null;
    if (sym && sym.kind === 'function') { this.open({ view: 'fn', path: ref.path, sym: ref.sym, open: new Set() }); return; }
    if (ref.sym) { this.showOnMap(`cls:${ref.path}:${ref.sym}`); return; }
    this.showOnMap(`mod:${ref.path}`);
  }
  showOnMap(id) {
    setCommentPick(null);
    revealHidden([id]);
    this.open(this.mapShowing([id], id, focusUnitOf(id)), id);
  }
  goToFolder(folder) {
    const target = `pkg:${folder}`;
    revealHidden([target]);
    const entry = this.mapShowing([target], target, focusUnitOf(target));
    entry.folded.delete(target);
    this.open(entry, target);
  }
  mapShowing(ids, focus, related) {
    const last = this.trail.lastMap(), folded = new Set(last.folded), open = new Set(last.open || []);
    for (const id of ids) for (const n of net().chain(id).slice(1, -1)) { folded.delete(n.id); if (n.kind === 'module' || n.kind === 'class') open.add(n.id); }
    return { view: 'net', folded, focus, related, open };
  }
  filterChanged() {
    resetNet();
    this.render(true);
  }
  async projectChanged() {
    const c = this.trail.current;
    if (c.view === 'fn') {
      c.error = null;
      try { await ensureFunction(c); } catch (error) { c.error = error.message; }
    }
    if (this.trail.current !== c) return;
    this.trail.selected = refreshedPick(this.trail.selected);
    resetNet();
    this.render(true);
  }
  toggleNet(id) {
    const target = id === LIBRARIES ? { kind: 'package' } : net().nodes.get(id);
    if (!target) return;
    const c = this.trail.current;
    if (target.kind === 'package') {
      if (!c.folded.delete(id)) c.folded.add(id);
      this.keepInPlace(id, () => this.render(true));
    } else if (target.kind === 'module' || target.kind === 'class') {
      if (!c.open.delete(id)) c.open.add(id);
      this.keepInPlace(id, () => this.render(true));
    }
  }
  keepInPlace(id, change) {
    const vp = this.vp;
    const before = this.scene && this.scene.netRects && this.scene.netRects.get(id);
    const x0 = before ? vp.x + before.x * vp.s : null, y0 = before ? vp.y + before.y * vp.s : null;
    change();
    const after = this.scene && this.scene.netRects && this.scene.netRects.get(id);
    if (before && after) { vp.x = x0 - after.x * vp.s; vp.y = y0 - after.y * vp.s; vp.apply(); }
  }
  followArrow(ends) {
    const boxes = ends.map((id) => this.scene.netRects.get(id)).filter(Boolean);
    if (!boxes.length) return;
    this.vp.frame(this.scene, boundsOf(boxes));
    boxes.forEach((box) => flash(box.el));
  }
  showEverything() {
    const c = this.trail.current;
    const keep = c.related;
    c.related = null;
    this.keepInPlace(keep, () => this.render(true));
  }
  clearSelection() {
    this.trail.selected = null;
    if (this.scene && this.scene.pin) this.scene.pin(null);
    setCommentPick(null);
    document.querySelectorAll('.node.selected').forEach((n) => n.classList.remove('selected'));
    this.panel();
  }
  selectNode(n, v, sym) {
    document.querySelectorAll('.node.selected').forEach((q) => q.classList.remove('selected'));
    if (v) v.el.classList.add('selected');
    this.trail.selected = { n, sym };
    this.panel();
    showOnPhone(this.ui.right);
  }
  revealLine(sym, line) {
    const found = nodesOnLine(this.scene, sym, line);
    if (!found.length) return;
    const at = found.findIndex((f) => f.v.el.classList.contains('selected'));
    const next = found[(at + 1) % found.length];
    this.selectNode(next.n, next.v, sym);
    this.vp.frame(next.scene, next.v.headH ? { x: next.v.x, y: next.v.y, w: next.v.headW, h: next.v.headH } : next.v);
    flash(next.v.el);
  }
  mapContext() {
    return {
      refresh: () => { if (this.trail.current.view !== 'fn') this.panel(); },
      go: this.goTo,
      show: (id) => this.showOnMap(id),
      toggle: (id) => this.toggleNet(id),
      followArrow: (ends) => this.followArrow(ends),
      selectedId: () => this.trail.selectedId(),
      select: (id) => {
        this.trail.selected = id;
        if (this.scene && this.scene.pin) this.scene.pin(id);
        this.panel();
        showOnPhone(this.ui.right);
      },
    };
  }
  panel() {
    const { ui, trail } = this;
    if (trail.current.view !== 'fn') {
      netPanel(ui.right, trail.selectedId(), this.netCtx, codeShown(trail.current, trail.selectedId()));
      this.comments.decorate();
      return;
    }
    const ctx = { ...this.blueprints.context('root'), activate: this.goTo, show: (id) => this.showOnMap(id), reveal: (sym, line) => this.revealLine(sym, line) };
    if (trail.selected && trail.selected.n) codePanel(ui.right, trail.selected.sym, trail.selected.n, ctx);
    else codePanel(ui.right, lookup(trail.current), null, ctx);
    this.comments.decorate();
  }
  chrome() { paintFrame(this.ui, this.trail.current, this.goTo, this.folds()); }
  folds() {
    const map = this.trail.lastMap();
    const shut = (n) => map.folded.has(n.id) || ((n.kind === 'module' || n.kind === 'class') && !map.open.has(n.id));
    const isOpen = (id) => net().nodes.has(id) && !net().chain(id).slice(1).some(shut);
    return { isOpen, toggle: (id) => this.foldFromTree(map, isOpen, id) };
  }
  foldFromTree(map, isOpen, id) {
    const node = net().nodes.get(id);
    if (!node) return;
    if (isOpen(id)) { if (node.kind === 'package') map.folded.add(id); else map.open.delete(id); }
    else for (const n of net().chain(id).slice(1)) { map.folded.delete(n.id); if (n.kind === 'module' || n.kind === 'class') map.open.add(n.id); }
    if (this.trail.current === map) this.keepInPlace(id, () => this.render(true));
    else this.chrome();
  }
  rememberPlace() { this.place.remember(this.trail, this.vp); }
  render(keepView) {
    const c = this.trail.current;
    updateButtons(this.buttons, this.trail);
    this.chrome();
    if (c.view !== 'net' && !FUNCTIONS.has(fnKey(c))) this.renderLoading(c, keepView);
    else this.renderScene(c, keepView);
  }
  renderLoading(c, keepView) {
    const vp = this.vp;
    const still = () => this.trail.current === c;
    if (!c.error) ensureFunction(c).then(() => { if (still()) this.render(keepView === 'relayout' ? true : keepView); }, (err) => { c.error = err.message; if (still()) this.render(keepView); });
    if (c.error) this.place.forget();
    this.scene = messageScene(c.error ? `Could not draw ${c.sym}: ${c.error}` : `Reading ${c.sym}…`);
    vp.setScene(this.scene, 'none'); vp.s = 1; vp.x = 40; vp.y = 40; vp.apply();
    this.panel();
  }
  renderScene(c, keepView) {
    const vp = this.vp;
    const isNet = c.view === 'net';
    const keep = { x: vp.x, y: vp.y, s: vp.s };
    const filter = isNet ? relatedTo(c.related) : null;
    this.scene = isNet ? buildPackageScene(c, this.netCtx, filter) : buildFunctionScene(lookup(c), this.blueprints.context('root'));
    placeMapChips(this.ui.vpHost, isNet ? filterChip(() => this.filterChanged()) : null, filter, () => this.showEverything());
    vp.setScene(this.scene, keepView ? 'none' : 'start');
    if (keepView) { Object.assign(vp, keep); vp.apply(); }
    else if (isNet && c.focus) zoomToFocus(vp, this.scene, c.focus);
    this.place.restore(vp);
    this.panel();
    this.rememberPlace();
    this.watchRelayout(c, keepView);
  }
  watchRelayout(c, keepView) {
    this.relayouts = keepView === 'relayout' ? this.relayouts + 1 : 0;
    const sizes = this.scene.sizes || this.scene.nodes.map((n) => ({ el: n.el, w: n.w, h: n.h }));
    if (this.relayouts < 3) watchSizes(sizes, () => { if (this.trail.current === c) this.render('relayout'); });
  }
}
function codeShown(c, selectedId) {
  const shown = new Set(c.open || []);
  if (!selectedId) return shown;
  const chain = net().chain(selectedId);
  const module = chain.find((n) => n.kind === 'module');
  if (module) shown.add(module.id);
  for (const n of chain) if (n.kind === 'class') shown.add(n.id);
  return shown;
}
function refreshedPick(selected) {
  if (!selected || !selected.n || !selected.sym) return selected;
  const ref = refOf(selected.sym);
  const sym = lookup(ref), data = FUNCTIONS.get(fnKey(ref));
  const node = sym && data && data.graph.nodes.find((n) => n.id === selected.n.id);
  return node ? { n: { ...node, ins: node.ins || [], outs: node.outs || [] }, sym } : null;
}
function explorerButtons(explorer) {
  const button = (title, label, onclick) => el('button', { class: 'btn', title, onclick }, label);
  return {
    back: button('Back (Alt+←)', '←', () => explorer.step(explorer.trail.back())),
    forward: button('Forward (Alt+→)', '→', () => explorer.step(explorer.trail.forward())),
    foldAll: button('Fold every open node back up', '⊟ Fold all', () => { explorer.trail.current.open.clear(); explorer.render(true); }),
    openOther: button('Open another project folder', 'Open…', () => explorer.session.showWelcome()),
    reload: button('Read the project again after editing code', '↻ Reload', () => explorer.session.reload()),
    filter: filterButton(() => explorer.filterChanged()),
  };
}
function updateButtons(buttons, trail) {
  const view = trail.current.view;
  buttons.back.disabled = !trail.canGoBack;
  buttons.forward.disabled = !trail.canGoForward;
  buttons.foldAll.hidden = view !== 'fn';
  buttons.filter.hidden = view === 'fn';
  labelFilterButton(buttons.filter);
}
function paintFrame(ui, c, onPick, folds) {
  const isNet = c.view === 'net';
  const focusPath = isNet ? (net().nodes.get(c.focus) && net().chain(c.focus).find((n) => n.kind === 'module') || {}).path || null : c.path;
  const focusFolder = isNet && !focusPath && c.focus && c.focus.startsWith('pkg:') ? c.focus.slice(4) : null;
  renderSide(ui.left, { currentPath: focusPath, currentSym: isNet ? null : c.sym, currentFolder: focusFolder, onPick, folds });
  crumbsFor(ui.crumbs, focusPath, isNet ? null : c.sym, onPick, crumbExtra(c, focusPath));
}
function crumbExtra(c, focusPath) {
  const isNet = c.view === 'net';
  const note = isNet ? [c.folded.size ? `· ${c.folded.size} folded` : '', c.open.size ? `· ${c.open.size} open` : ''].filter(Boolean).join(' ') || null : c.open.size ? `· ${c.open.size} unfolded` : null;
  const units = isNet ? (focusPath ? fileUnits(focusPath) : []) : symbolUnits(c);
  const seen = units.length ? el('label', { class: 'seen-toggle', title: 'Tick once you have reviewed these changes' }, seenBox(units, isNet ? baseName(focusPath) : c.sym), isNet ? 'File seen' : 'Seen') : null;
  return note || seen ? el('span', { class: 'crumb-extra' }, note, seen) : null;
}
function placeMapChips(host, kindChip, filter, onShowAll) {
  host.querySelectorAll('.focus-chip').forEach((chip) => chip.remove());
  host.querySelectorAll('.show-chip').forEach((chip) => chip.remove());
  if (kindChip) host.append(kindChip);
  if (filter) host.append(el('div', { class: 'focus-chip' }, el('span', {}, 'Showing what ', el('strong', {}, netLabel(filter.unit)), ` depends on or is used by · ${plural(filter.related.size, 'related module')}`), el('button', { class: 'btn small', title: 'Show every module again', onclick: onShowAll }, '✕ Show all')));
}
function zoomToFocus(vp, scene, focus) {
  const box = scene.el.querySelector(`.nb[data-id="${CSS.escape(focus)}"]`);
  const r = scene.netRects && scene.netRects.get(focus);
  vp.fit();
  if (r && vp.s < 0.6) { vp.s = 0.85; vp.x = 40 - r.x * vp.s; vp.y = 60 - r.y * vp.s; vp.apply(); }
  if (box) box.classList.add('flash');
}
function showOnPhone(panel) { if (window.innerWidth <= 760) panel.hidden = false; }
let sizeWatcher = null;
function watchSizes(entries, relayout) {
  if (sizeWatcher) sizeWatcher.disconnect();
  if (typeof ResizeObserver === 'undefined') return;
  let pending = false;
  sizeWatcher = new ResizeObserver(() => {
    if (pending) return;
    if (!entries.some((s) => s.el.offsetParent && (Math.abs(s.el.offsetWidth - s.w) > 1 || Math.abs(s.el.offsetHeight - s.h) > 1))) return;
    pending = true; sizeWatcher.disconnect(); requestAnimationFrame(relayout);
  });
  entries.forEach((s) => sizeWatcher.observe(s.el));
}
