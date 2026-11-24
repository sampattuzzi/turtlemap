import { el } from '../core/dom.js';
const DRAG_THRESHOLD = 4;
export class PointerGestures {
  constructor(viewport) {
    this.viewport = viewport;
    this.pointers = new Map();
    this.drag = null;
    this.pinch = null;
    this.marquee = null;
    this.safariScale = null;
    this.swallowClick = false;
    const host = viewport.host;
    host.addEventListener('pointerdown', (e) => this.pointerDown(e));
    host.addEventListener('pointermove', (e) => this.pointerMove(e));
    host.addEventListener('pointerup', (e) => this.pointerUp(e));
    host.addEventListener('pointercancel', (e) => this.pointerUp(e, true));
    host.addEventListener('wheel', (e) => this.wheel(e), { passive: false });
    host.addEventListener('scroll', () => { host.scrollLeft = 0; host.scrollTop = 0; });
    host.addEventListener('gesturestart', (e) => this.safariGesture(e, 'start'));
    host.addEventListener('gesturechange', (e) => this.safariGesture(e, 'change'));
    host.addEventListener('gestureend', (e) => this.safariGesture(e, 'end'));
    host.addEventListener('click', (e) => { if (this.swallowClick) { e.stopPropagation(); e.preventDefault(); this.swallowClick = false; } }, true);
  }
  pointerDown(e) {
    if (e.pointerType === 'mouse' && e.button !== 0) return;
    if (e.target.closest('.zoom-ctl, .show-chip, .edge-pointer, .comment-card, .pick-bar, input, select, textarea')) return;
    if (e.shiftKey && this.viewport.onMarquee && !this.pointers.size) { this.startMarquee(e); return; }
    this.pointers.set(e.pointerId, { ...this.viewport.local(e), startX: e.clientX, startY: e.clientY, target: e.target });
    this.swallowClick = false;
    if (this.pointers.size === 1) this.drag = { moved: false, background: !e.target.closest('.nb, .box, button, .rel-hit, .wire-hit') };
    if (!this.drag) this.drag = { moved: false, background: false };
    if (this.pointers.size === 2) { this.drag.moved = true; this.pinch = this.twoFinger(); }
  }
  pointerMove(e) {
    if (this.marquee && this.marquee.id === e.pointerId) { this.moveMarquee(e); return; }
    const p = this.pointers.get(e.pointerId);
    if (!p) return;
    const now = this.viewport.local(e);
    if (this.pointers.size === 1) { this.dragMove(e, p, now); return; }
    Object.assign(p, now);
    if (this.pointers.size === 2 && this.pinch) this.pinchMove();
  }
  dragMove(e, p, now) {
    if (!this.drag.moved && Math.hypot(e.clientX - p.startX, e.clientY - p.startY) < DRAG_THRESHOLD) return;
    if (!this.drag.moved) { this.drag.moved = true; try { this.viewport.host.setPointerCapture(e.pointerId); } catch (err) {} this.viewport.host.classList.add('dragging'); }
    this.viewport.panBy(now.x - p.x, now.y - p.y);
    Object.assign(p, now);
  }
  pinchMove() {
    const next = this.twoFinger();
    this.viewport.panBy(next.cx - this.pinch.cx, next.cy - this.pinch.cy);
    if (this.pinch.d > 0) this.viewport.zoomAt(next.cx, next.cy, next.d / this.pinch.d);
    this.pinch = next;
  }
  pointerUp(e, cancelled = false) {
    if (this.marquee && this.marquee.id === e.pointerId) { this.endMarquee(e, cancelled); return; }
    if (!this.pointers.has(e.pointerId)) return;
    this.pointers.delete(e.pointerId);
    if (this.pointers.size === 1) { const [rest] = this.pointers.values(); this.pinch = null; this.drag.moved = true; Object.assign(rest, { startX: -1e9 }); return; }
    if (this.pointers.size) return;
    this.pinch = null;
    this.viewport.host.classList.remove('dragging');
    if (this.drag && this.drag.moved) this.swallowClick = true;
    else if (!cancelled && this.drag && this.drag.background && this.viewport.onBackground) this.viewport.onBackground();
    this.drag = null;
  }
  startMarquee(e) {
    const at = this.viewport.local(e);
    const box = el('div', { class: 'marquee' });
    this.viewport.host.append(box);
    this.marquee = { id: e.pointerId, x0: at.x, y0: at.y, x1: at.x, y1: at.y, box, additive: e.metaKey || e.ctrlKey };
    try { this.viewport.host.setPointerCapture(e.pointerId); } catch (err) {}
    this.moveMarquee(e);
  }
  moveMarquee(e) {
    const m = this.marquee;
    const at = this.viewport.local(e);
    m.x1 = at.x; m.y1 = at.y;
    Object.assign(m.box.style, { left: `${Math.min(m.x0, m.x1)}px`, top: `${Math.min(m.y0, m.y1)}px`, width: `${Math.abs(m.x1 - m.x0)}px`, height: `${Math.abs(m.y1 - m.y0)}px` });
  }
  endMarquee(e, cancelled) {
    const m = this.marquee;
    const { x: vx, y: vy, s } = this.viewport;
    this.marquee = null;
    m.box.remove();
    this.swallowClick = true;
    if (cancelled || Math.hypot(m.x1 - m.x0, m.y1 - m.y0) < DRAG_THRESHOLD) return;
    const x = (Math.min(m.x0, m.x1) - vx) / s, y = (Math.min(m.y0, m.y1) - vy) / s;
    this.viewport.onMarquee({ x, y, w: Math.abs(m.x1 - m.x0) / s, h: Math.abs(m.y1 - m.y0) / s }, m.additive);
  }
  twoFinger() {
    const [a, b] = [...this.pointers.values()];
    return { cx: (a.x + b.x) / 2, cy: (a.y + b.y) / 2, d: Math.hypot(a.x - b.x, a.y - b.y) };
  }
  wheel(e) {
    if (e.target.closest('.comment-card')) { if (e.ctrlKey || e.metaKey) e.preventDefault(); return; }
    e.preventDefault();
    const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? this.viewport.host.clientHeight : 1;
    const p = this.viewport.local(e);
    if (e.ctrlKey || e.metaKey) this.viewport.zoomAt(p.x, p.y, Math.exp(-e.deltaY * unit * wheelZoomRate(e, unit)));
    else this.viewport.panBy(-e.deltaX * unit, -e.deltaY * unit);
  }
  safariGesture(e, phase) {
    e.preventDefault();
    if ([...this.pointers.values()].length) return;
    const p = this.viewport.local(e);
    if (phase === 'start') this.safariScale = 1;
    else if (phase === 'change' && this.safariScale) { this.viewport.zoomAt(p.x, p.y, e.scale / this.safariScale); this.safariScale = e.scale; }
    else this.safariScale = null;
  }
}
function wheelZoomRate(e, unit) {
  return e.ctrlKey && !e.metaKey && unit === 1 && Math.abs(e.deltaY) < 50 ? 0.01 : 0.002;
}
