import { renderCommentCard, renderPickBar } from './cards.js';
import { paintAgentChip } from './list.js';
import { clearDecorations, decorateBlueprint, decorateMap, paintCodeViews } from './marks.js';
import { CARD, PICK, REPLY_DRAFTS, anchorFor, mergeThreads, onCommentsChanged, openThreads, setCommentActions, setCommentCard, setCommentPick, setCommentsListener, threadById, toast } from './store.js';
import { FILES, FUNCTIONS, fnKey, lookup, net } from '../core/data.js';
import { apiPost } from '../core/dom.js';
import { refOf } from '../map/boxes.js';
import { revealHidden } from '../map/focus.js';
export class CommentControls {
  constructor(explorer) {
    this.explorer = explorer;
    this.reveal = null;
    this.show = (id) => this.showThread(id);
    this.actions = this.makeActions();
    setCommentActions(this.actions);
    setCommentsListener(() => { explorer.chrome(); this.decorate(); });
    explorer.ui.vpHost.addEventListener('click', (e) => this.pickByClick(e), true);
    explorer.vp.onMarquee = (rect, additive) => this.pickInside(rect, additive);
  }
  makeActions() {
    const saved = (thread) => { mergeThreads([thread]); onCommentsChanged(); };
    return {
      open: this.show,
      compose: () => this.compose(),
      clearPick: () => { setCommentPick(null); this.decorate(); },
      close: () => { setCommentCard(null); this.decorate(); this.explorer.chrome(); },
      create: (anchor, body) => apiPost('/api/comments', { anchor, body }).then((thread) => { mergeThreads([thread]); setCommentPick(null); setCommentCard({ mode: 'thread', id: thread.id }); onCommentsChanged(); }, failure('Could not save the comment')),
      reply: (id, body) => apiPost('/api/comments/reply', { id, body }).then(saved, (err) => { REPLY_DRAFTS.set(id, body); failure('Could not send the reply')(err); }),
      resolve: (id, resolved) => apiPost('/api/comments/resolve', { id, resolved }).then(saved, failure('Could not change the comment')),
      step: (d) => this.step(d),
    };
  }
  keys(e) {
    if (e.key === 'c' || e.key === 'C') { e.preventDefault(); this.compose(); }
    if (e.key === ']') this.actions.step(1);
    if (e.key === '[') this.actions.step(-1);
    if (e.key === 'Escape') { if (CARD) this.actions.close(); else if (PICK) this.actions.clearPick(); }
  }
  step(direction) {
    const open = openThreads();
    if (!open.length) return;
    const at = open.findIndex((t) => CARD && t.id === CARD.id);
    this.showThread(open[at < 0 ? (direction > 0 ? 0 : open.length - 1) : (at + direction + open.length) % open.length].id);
  }
  currentPick() {
    if (PICK) return PICK;
    const { trail } = this.explorer;
    const c = trail.current;
    if (c.view === 'net' && typeof trail.selected === 'string') return { kind: 'map', ids: new Set([trail.selected]), implicit: true };
    if (c.view === 'fn' && trail.selected && trail.selected.n && trail.selected.sym) return { kind: 'blueprint', ids: new Set([trail.selected.n.id]), fn: refOf(trail.selected.sym), implicit: true };
    return null;
  }
  setPick(kind, ids, additive) {
    const c = this.explorer.trail.current;
    const fn = kind === 'blueprint' ? { path: c.path, sym: c.sym } : undefined;
    const before = additive ? this.currentPick() : null;
    const same = before && before.kind === kind && (kind !== 'blueprint' || (before.fn.path === fn.path && before.fn.sym === fn.sym));
    const chosen = same ? new Set(before.ids) : new Set();
    for (const id of ids) { if (additive && ids.length === 1 && chosen.has(id)) chosen.delete(id); else chosen.add(id); }
    setCommentPick(chosen.size ? { kind, ids: chosen, fn } : null);
    this.decorate();
  }
  compose() {
    const pick = this.currentPick() || this.defaultPick();
    if (!pick) { toast('Select something to comment on first: click a box or node, Shift-drag around several, or drag down the line numbers.', () => {}); return; }
    setCommentCard({ mode: 'new', anchor: anchorFor(pick), draft: '', focus: true });
    this.decorate();
  }
  defaultPick() {
    const c = this.explorer.trail.current;
    if (c.view === 'fn') {
      const data = FUNCTIONS.get(fnKey(c));
      const entry = data && data.graph.nodes.find((n) => n.kind === 'entry');
      if (entry) return { kind: 'blueprint', ids: new Set([entry.id]), fn: { path: c.path, sym: c.sym } };
    }
    if (c.view === 'net' && c.focus) return { kind: 'map', ids: new Set([c.focus]) };
    return null;
  }
  showThread(id) {
    const thread = threadById(id);
    if (!thread) return;
    setCommentCard({ mode: 'thread', id });
    this.reveal = id;
    setCommentPick(null);
    const a = thread.anchor;
    const fnSym = a.qual ? lookup({ path: a.path, sym: a.qual }) : null;
    if (a.view === 'map') this.showOnMap(a.ids || []);
    else if (fnSym && fnSym.kind === 'function') this.showInBlueprint(a);
    else if (FILES[a.path]) this.showFile(a.path);
    else this.redecorate();
  }
  showOnMap(anchored) {
    const { trail, scene } = this.explorer;
    revealHidden(anchored);
    const ids = anchored.filter((i) => net().nodes.has(i));
    const onScreen = trail.current.view === 'net' && ids.length && ids.every((i) => scene.netRects && net().chain(i).some((n) => scene.netRects.has(n.id)));
    if (onScreen || !ids.length) { this.redecorate(); return; }
    this.explorer.open(this.explorer.mapShowing(ids, ids[0], null));
  }
  showInBlueprint(anchor) {
    const { trail } = this.explorer;
    const c = trail.current;
    if (c.view === 'fn' && c.path === anchor.path && c.sym === anchor.qual) { trail.selected = null; this.explorer.render(true); return; }
    this.explorer.open({ view: 'fn', path: anchor.path, sym: anchor.qual, open: new Set() });
  }
  showFile(path) {
    revealHidden([`mod:${path}`]);
    this.explorer.open(this.explorer.mapShowing([`mod:${path}`], `mod:${path}`, null));
  }
  redecorate() {
    this.explorer.chrome();
    this.decorate();
  }
  decorate() {
    const { trail, scene, ui } = this.explorer;
    const c = trail.current;
    if (scene) {
      clearDecorations(scene.el);
      if (c.view === 'net' && scene.netRects) decorateMap(scene.el, this.show);
      else if (c.view === 'fn' && scene.layer && FUNCTIONS.has(fnKey(c))) decorateBlueprint(scene.layer, { path: c.path, sym: c.sym }, this.show);
    }
    paintCodeViews(ui.right, this.show, () => this.decorate());
    renderPickBar(ui.vpHost, this.currentPick(), this.actions);
    renderCommentCard(ui.vpHost, this.actions);
    paintAgentChip();
    if (this.reveal) this.revealThread();
  }
  revealThread() {
    const { ui } = this.explorer;
    const id = this.reveal;
    const pin = ui.vpHost.querySelector(`.comment-pin[data-threads~="${CSS.escape(id)}"]`);
    const mark = ui.right.querySelector(`.cmark[data-threads~="${CSS.escape(id)}"]`);
    if (mark) mark.closest('.ln').scrollIntoView({ block: 'center' });
    if (!pin) return;
    this.reveal = null;
    const target = pin.closest('.nb, .node') || pin;
    this.centreOn(target);
    target.classList.remove('flash'); void target.offsetWidth; target.classList.add('flash');
  }
  centreOn(target) {
    const { vp, ui } = this.explorer;
    const host = ui.vpHost.getBoundingClientRect();
    let r = target.getBoundingClientRect();
    if (vp.s < 0.6) { vp.zoomAt(r.left + r.width / 2 - host.left, r.top + r.height / 2 - host.top, 0.85 / vp.s); r = target.getBoundingClientRect(); }
    const room = host.width - (ui.vpHost.querySelector('.comment-card') ? 380 : 0);
    vp.panBy(room / 2 - (r.left - host.left + Math.min(r.width, room - 40) / 2), host.height / 2 - (r.top - host.top + Math.min(r.height, host.height - 80) / 2));
  }
  pickByClick(e) {
    if (!(e.metaKey || e.ctrlKey) || e.target.closest('.comment-card, .pick-bar, .zoom-ctl, .show-chip, .edge-pointer, .comment-pin')) return;
    const id = this.clickedId(e.target);
    if (!id) return;
    e.stopPropagation(); e.preventDefault();
    this.setPick(this.explorer.trail.current.view === 'net' ? 'map' : 'blueprint', [id], true);
  }
  clickedId(target) {
    const { trail, scene } = this.explorer;
    if (trail.current.view === 'net') { const box = target.closest('.nb[data-id]'); return box ? box.dataset.id : null; }
    const node = target.closest('.node[data-node]');
    return node && scene && node.parentElement === scene.layer ? node.dataset.node : null;
  }
  pickInside(rect, additive) {
    const { trail, scene } = this.explorer;
    const inside = (r) => r.x >= rect.x && r.y >= rect.y && r.x + r.w <= rect.x + rect.w && r.y + r.h <= rect.y + rect.h;
    const c = trail.current;
    if (!scene) return;
    if (c.view === 'net' && scene.netRects) {
      const hits = [...scene.netRects].filter(([, r]) => inside(r)).map(([id]) => id);
      const inPick = new Set(hits);
      const outer = hits.filter((id) => !net().chain(id).slice(0, -1).some((n) => inPick.has(n.id)));
      if (outer.length || !additive) this.setPick('map', outer, additive);
    } else if (c.view === 'fn') {
      const hits = scene.nodes.filter((v) => v.data && v.data.id != null && inside(v)).map((v) => v.data.id);
      if (hits.length || !additive) this.setPick('blueprint', hits, additive);
    }
  }
}
function failure(what) { return (err) => toast(`${what}: ${err.message}`, () => {}); }
