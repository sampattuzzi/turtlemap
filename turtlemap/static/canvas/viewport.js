import { el } from '../core/dom.js';
import { PointerGestures } from './gestures.js';
import { EdgePointers } from './pointers.js';
const CULL_MARGIN = 0.75;
export class Viewport {
  constructor(host) {
    this.host = host; this.s = 1; this.x = 0; this.y = 0;
    this.world = el('div', { class: 'world' }); host.append(this.world);
    this.pct = el('span', { class: 'pct' }, '100%');
    this.edges = new EdgePointers(this);
    this.settleTimer = null;
    this.cullFrame = null;
    this.gestures = new PointerGestures(this);
    this.crumb = el('div', { class: 'crumb', hidden: true });
    host.append(this.crumb);
    host.append(el('div', { class: 'zoom-ctl' }, this.pct,
      el('button', { class: 'btn small', title: 'Zoom out (Ctrl or ⌘ + scroll, or pinch)', onclick: () => this.zoomCentre(1 / 1.2) }, '−'),
      el('button', { class: 'btn small', title: 'Zoom in (Ctrl or ⌘ + scroll, or pinch)', onclick: () => this.zoomCentre(1.2) }, '+'),
      el('button', { class: 'btn small', title: 'Back to 100%', onclick: () => this.start() }, '1:1'),
      el('button', { class: 'btn small', title: 'Fit everything on screen', onclick: () => this.fit() }, 'Fit')));
  }
  local(e) { const r = this.host.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; }
  panBy(dx, dy) { this.x += dx; this.y += dy; this.apply(true); }
  setScene(scene, how = 'start') { this.world.innerHTML = ''; this.scene = scene; this.edges.reset(); scene.onHot = (hot) => this.edges.show(hot); this.world.append(scene.el); if (how === 'start') this.start(); else if (how === 'fit') this.fit(); this.apply(); }
  apply(moving = false) {
    this.world.style.transform = `translate(${this.x}px, ${this.y}px) scale(${this.s})`;
    if (this.onMoved) this.onMoved();
    const g = 16 * this.s, G2 = g * 8;
    this.host.style.backgroundSize = `${G2}px ${G2}px, ${G2}px ${G2}px, ${g}px ${g}px, ${g}px ${g}px`;
    this.host.style.backgroundPosition = `${this.x}px ${this.y}px`;
    this.pct.textContent = `${Math.round(this.s * 100)}%`;
    this.world.classList.toggle('far', this.s < 0.4);
    if (moving) {
      this.world.style.willChange = 'transform';
      clearTimeout(this.settleTimer);
      this.settleTimer = setTimeout(() => { this.cull(); this.world.style.willChange = ''; }, 160);
      this.scheduleCull();
    } else {
      clearTimeout(this.cullFrame);
      this.cullFrame = null;
      this.cull();
    }
    this.edges.redraw();
    this.showCrumbs();
  }
  showCrumbs() {
    const lines = this.scene && this.scene.crumbs ? this.scene.crumbs({ x: -this.x / this.s, y: -this.y / this.s, w: this.host.clientWidth / this.s, h: this.host.clientHeight / this.s }) : null;
    this.crumb.hidden = !lines || !lines.length;
    if (lines) this.crumb.replaceChildren(...lines);
  }
  glideTo(p) {
    const W = this.host.clientWidth, H = this.host.clientHeight;
    const x0 = this.x, y0 = this.y, x1 = W / 2 - p.x * this.s, y1 = H / 2 - p.y * this.s;
    const begun = performance.now();
    this.edges.clear();
    const step = (now) => {
      const k = Math.min(1, (now - begun) / 320);
      const eased = 1 - (1 - k) ** 3;
      this.x = x0 + (x1 - x0) * eased; this.y = y0 + (y1 - y0) * eased;
      this.apply(k < 1);
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
  scheduleCull() {
    if (this.cullFrame) return;
    this.cullFrame = setTimeout(() => { this.cullFrame = null; this.cull(); }, 120);
  }
  cull() {
    if (!this.scene || !this.scene.cull) return;
    const w = this.host.clientWidth / this.s, h = this.host.clientHeight / this.s;
    this.scene.cull({ x: -this.x / this.s - w * CULL_MARGIN, y: -this.y / this.s - h * CULL_MARGIN, w: w * (1 + 2 * CULL_MARGIN), h: h * (1 + 2 * CULL_MARGIN) });
  }
  zoomAt(px, py, f) { const ns = Math.min(2.5, Math.max(0.05, this.s * f)); f = ns / this.s; this.x = px - (px - this.x) * f; this.y = py - (py - this.y) * f; this.s = ns; this.apply(true); }
  zoomCentre(f) { this.zoomAt(this.host.clientWidth / 2, this.host.clientHeight / 2, f); }
  fit() { if (!this.scene) return; const W = this.host.clientWidth, H = this.host.clientHeight; this.s = Math.min(1.2, Math.max(0.05, Math.min(W / this.scene.width, (H - 40) / this.scene.height))); this.x = (W - this.scene.width * this.s) / 2; this.y = Math.max(20, (H - this.scene.height * this.s) / 2); this.apply(); }
  start() { if (!this.scene) return; const W = this.host.clientWidth, H = this.host.clientHeight; const fitS = Math.min(W / this.scene.width, (H - 60) / this.scene.height); this.s = Math.max(0.75, Math.min(1, fitS)); this.x = this.scene.width * this.s <= W ? (W - this.scene.width * this.s) / 2 : 0; this.y = this.scene.height * this.s <= H - 60 ? (H - this.scene.height * this.s) / 2 : 30; this.apply(); }
  centreOn(elm) { const r = elm.getBoundingClientRect(), hr = this.host.getBoundingClientRect(); this.x += hr.left + hr.width / 2 - (r.left + r.width / 2); this.y += hr.top + hr.height / 2 - (r.top + r.height / 2); this.apply(); }
}
