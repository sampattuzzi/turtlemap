import { codePanel } from '../blueprint/codepanel.js';
import { BlueprintControls } from '../blueprint/controls.js';
import { buildFunctionScene } from '../blueprint/nodes.js';
import { messageScene } from '../canvas/scene.js';
import { Viewport } from '../canvas/viewport.js';
import { setCommentPick } from '../comments/store.js';
import { CommentControls } from '../comments/controls.js';
import { FUNCTIONS, fnKey, lookup, net } from '../core/data.js';
import { api, baseName, el } from '../core/dom.js';
import { PlaceMemory, loadPlace } from '../core/place.js';
import { ensureFunction } from '../core/project.js';
import { fileUnits, seenBox, setSeenListener, symbolUnits } from '../core/review.js';
import { saveSettings, settings } from '../core/settings.js';
import { crumbsFor, renderSide } from './sidebar.js';
import { shell } from './toolbar.js';
import { startingTrail } from './trail.js';
import { netLabel, plural } from '../map/boxes.js';
import { dataScopeChip, showToggles } from '../map/chips.js';
import { dataScopeFor } from '../map/datamodel.js';
import { buildDataScene } from '../map/datascene.js';
import { focusUnitOf, netDefaultExpanded, relatedTo, resetNet } from '../map/focus.js';
import { netPanel } from '../map/panel.js';
import { buildNetScene } from '../map/scene.js';
const DATA_TITLE = 'Show the data model: data classes, their fields and how they hold each other';
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
    this.ui = shell(root, { extraButtons: [b.openOther, b.reload, b.back, b.forward, b.foldAll, b.data], onPick: this.goTo, onSettings: () => this.render(true), onCompared: () => session.waitForProject() });
    this.vp = new Viewport(this.ui.vpHost);
    this.vp.onMoved = () => this.rememberPlace();
    this.vp.onBackground = () => this.clearSelection();
    this.blueprints = new BlueprintControls(this);
    this.netCtx = this.mapContext();
    this.dataCtx = { ...this.netCtx, toggle: () => {}, select: (id) => { this.trail.selected = id; this.panel(); showOnPhone(this.ui.right); } };
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
    const sym = ref.sym ? lookup(ref) : null;
    if (sym && sym.kind === 'function') { this.open({ view: 'fn', path: ref.path, sym: ref.sym, open: new Set() }); return; }
    if (ref.sym) { this.showOnMap(`cls:${ref.path}:${ref.sym}`); return; }
    const target = `mod:${ref.path}`;
    this.open({ view: 'net', expanded: netDefaultExpanded(ref.path), focus: target, related: focusUnitOf(target), open: new Set() }, target);
  }
  showOnMap(id) {
    setCommentPick(null);
    const expanded = new Set(this.trail.lastMap().expanded);
    net().chain(id).slice(1).forEach((x) => expanded.add(x.id));
    this.open({ view: 'net', expanded, focus: id, related: focusUnitOf(id), open: new Set() }, id);
  }
  toggleData() {
    const leaving = this.trail.current.view === 'data';
    const last = this.trail.lastMap();
    const from = typeof this.trail.selected === 'string' ? this.trail.selected : last.focus || last.related;
    const entry = leaving ? { ...last, expanded: new Set(last.expanded), open: new Set() } : { view: 'data', scope: dataScopeFor(net(), from), open: new Set() };
    setCommentPick(null);
    this.open(entry);
  }
  toggleNet(id) {
    const target = net().nodes.get(id);
    if (target && target.children.length) {
      const ex = this.trail.current.expanded;
      if (ex.has(id)) ex.delete(id); else ex.add(id);
    }
    this.keepInPlace(id, () => this.render(true));
  }
  keepInPlace(id, change) {
    const vp = this.vp;
    const before = this.scene && this.scene.netRects && this.scene.netRects.get(id);
    const x0 = before ? vp.x + before.x * vp.s : null, y0 = before ? vp.y + before.y * vp.s : null;
    change();
    const after = this.scene && this.scene.netRects && this.scene.netRects.get(id);
    if (before && after) { vp.x = x0 - after.x * vp.s; vp.y = y0 - after.y * vp.s; vp.apply(); }
  }
  showEverything() {
    const c = this.trail.current;
    const keep = c.related;
    c.related = null;
    this.keepInPlace(keep, () => this.render(true));
  }
  clearSelection() {
    this.trail.selected = null;
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
  mapContext() {
    return {
      refresh: () => { if (this.trail.current.view !== 'fn') this.panel(); },
      go: this.goTo,
      show: (id) => this.showOnMap(id),
      toggle: (id) => this.toggleNet(id),
      select: (id) => {
        this.trail.selected = id;
        const unit = focusUnitOf(id);
        const c = this.trail.current;
        if (unit && unit !== c.related) {
          c.related = unit;
          c.refocused = true;
          queueMicrotask(() => { if (this.trail.current.refocused) this.keepInPlace(id, () => this.render(true)); });
        }
        this.panel();
        showOnPhone(this.ui.right);
      },
    };
  }
  panel() {
    const { ui, trail } = this;
    if (trail.current.view !== 'fn') {
      netPanel(ui.right, trail.selectedId(), this.netCtx, this.scene && this.scene.effective);
      this.comments.decorate();
      return;
    }
    const ctx = { ...this.blueprints.context('root'), activate: this.goTo };
    if (trail.selected && trail.selected.n) codePanel(ui.right, trail.selected.sym, trail.selected.n, ctx);
    else codePanel(ui.right, lookup(trail.current), null, ctx);
    this.comments.decorate();
  }
  chrome() { paintFrame(this.ui, this.trail.current, this.goTo); }
  rememberPlace() { this.place.remember(this.trail, this.vp); }
  render(keepView) {
    const c = this.trail.current;
    updateButtons(this.buttons, this.trail);
    this.chrome();
    if (c.view === 'data') this.renderData(c, keepView);
    else if (c.view !== 'net' && !FUNCTIONS.has(fnKey(c))) this.renderLoading(c, keepView);
    else this.renderScene(c, keepView);
  }
  renderData(c, keepView) {
    const { vp, ui } = this;
    const keep = { x: vp.x, y: vp.y, s: vp.s };
    this.scene = buildDataScene(this.dataCtx, c.scope);
    ui.vpHost.querySelectorAll('.focus-chip, .show-chip').forEach((chip) => chip.remove());
    ui.vpHost.append(dataScopeChip(c.scope, (scope) => { c.scope = scope; this.trail.selected = null; this.render(false); }));
    vp.setScene(this.scene, keepView ? 'none' : 'fit');
    if (keepView) { Object.assign(vp, keep); vp.apply(); }
    this.place.restore(vp);
    this.panel();
    this.rememberPlace();
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
    c.refocused = false;
    const filter = isNet ? relatedTo(c.related) : null;
    this.scene = isNet ? buildNetScene(c.expanded, this.netCtx, filter) : buildFunctionScene(lookup(c), this.blueprints.context('root'));
    const onToggle = (key, on) => { settings[key] = on; saveSettings(); resetNet(); this.render(true); };
    placeMapChips(this.ui.vpHost, isNet ? showToggles(onToggle) : null, filter, () => this.showEverything());
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
function explorerButtons(explorer) {
  const button = (title, label, onclick) => el('button', { class: 'btn', title, onclick }, label);
  return {
    back: button('Back (Alt+←)', '←', () => explorer.step(explorer.trail.back())),
    forward: button('Forward (Alt+→)', '→', () => explorer.step(explorer.trail.forward())),
    foldAll: button('Fold every open node back up', '⊟ Fold all', () => { explorer.trail.current.open.clear(); explorer.render(true); }),
    openOther: button('Open another project folder', 'Open…', () => explorer.session.showWelcome()),
    reload: button('Read the project again after editing code', '↻ Reload', () => { api('/api/reload').then(() => explorer.session.waitForProject(), (err) => explorer.session.showWelcome(err.message)); }),
    data: button(DATA_TITLE, '▦ Data', () => explorer.toggleData()),
  };
}
function updateButtons(buttons, trail) {
  const view = trail.current.view;
  buttons.back.disabled = !trail.canGoBack;
  buttons.forward.disabled = !trail.canGoForward;
  buttons.foldAll.hidden = view !== 'fn';
  buttons.data.textContent = view === 'data' ? '◱ Map' : '▦ Data';
  buttons.data.title = view === 'data' ? 'Back to the dependency map' : DATA_TITLE;
}
function paintFrame(ui, c, onPick) {
  if (c.view === 'data') {
    renderSide(ui.left, null, null, onPick);
    crumbsFor(ui.crumbs, null, null, onPick, el('span', { class: 'crumb-extra' }, '· data model'));
    return;
  }
  const isNet = c.view === 'net';
  const focusPath = isNet ? (net().nodes.get(c.focus) && net().chain(c.focus).find((n) => n.kind === 'module') || {}).path || null : c.path;
  renderSide(ui.left, focusPath, isNet ? null : c.sym, onPick);
  crumbsFor(ui.crumbs, focusPath, isNet ? null : c.sym, onPick, crumbExtra(c, focusPath));
}
function crumbExtra(c, focusPath) {
  const isNet = c.view === 'net';
  const note = isNet ? `· ${c.expanded.size} open` : c.open.size ? `· ${c.open.size} unfolded` : null;
  const units = isNet ? (focusPath ? fileUnits(focusPath) : []) : symbolUnits(c);
  const seen = units.length ? el('label', { class: 'seen-toggle', title: 'Tick once you have reviewed these changes' }, seenBox(units, isNet ? baseName(focusPath) : c.sym), isNet ? 'File seen' : 'Seen') : null;
  return note || seen ? el('span', { class: 'crumb-extra' }, note, seen) : null;
}
function placeMapChips(host, toggles, filter, onShowAll) {
  host.querySelectorAll('.focus-chip').forEach((chip) => chip.remove());
  host.querySelectorAll('.show-chip').forEach((chip) => chip.remove());
  if (toggles) host.append(toggles);
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
