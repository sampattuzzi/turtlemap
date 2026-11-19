import { overlaps } from './scene.js';
import { el } from '../core/dom.js';
const POINTER_INSET = 10;
const POINTER_TOP = 46;
const POINTER_BOTTOM = 52;
const POINTER_MAX = 16;
const POINTER_LINGER = 700;
export class EdgePointers {
  constructor(viewport) {
    this.viewport = viewport;
    this.layer = el('div', { class: 'edge-pointers' });
    viewport.host.append(this.layer);
    this.hot = null;
    this.timer = undefined;
  }
  show(hot) {
    clearTimeout(this.timer);
    if (hot && hot.length) { this.hot = hot; this.draw(); return; }
    if (!this.hot) return;
    this.timer = setTimeout(() => { if (this.layer.querySelector('.edge-pointer:hover')) return; this.hot = null; this.draw(); }, hot ? 0 : POINTER_LINGER);
  }
  redraw() {
    if (this.hot) this.draw();
  }
  reset() {
    clearTimeout(this.timer);
    this.clear();
  }
  clear() {
    this.hot = null;
    this.layer.innerHTML = '';
  }
  draw() {
    this.layer.innerHTML = '';
    if (!this.hot) return;
    const W = this.viewport.host.clientWidth, H = this.viewport.host.clientHeight;
    const frame = { l: POINTER_INSET, t: POINTER_TOP, r: W - POINTER_INSET, b: H - POINTER_BOTTOM };
    if (frame.r <= frame.l || frame.b <= frame.t) return;
    const far = this.offScreen(W, H);
    const placed = [];
    for (const h of far.slice(0, POINTER_MAX)) this.addPointer(h, frame, W, H, placed);
    if (far.length > POINTER_MAX) {
      const more = el('div', { class: 'edge-pointer more' }, `+${far.length - POINTER_MAX} more off screen`);
      this.layer.append(more);
      placeChip(more, W / 2, frame.b, false, W, H, placed);
    }
  }
  onScreen(p) {
    const { x, y, s } = this.viewport;
    return { x: x + p.x * s, y: y + p.y * s };
  }
  offScreen(W, H) {
    const away = new Map();
    for (const h of this.hot) {
      const at = this.onScreen(h.to);
      if (at.x >= 0 && at.x <= W && at.y >= 0 && at.y <= H) continue;
      if (!away.has(h.key)) away.set(h.key, { ...h, at, origin: this.onScreen(h.from) });
    }
    return [...away.values()].sort((p, q) => Math.hypot(p.at.x - p.origin.x, p.at.y - p.origin.y) - Math.hypot(q.at.x - q.origin.x, q.at.y - q.origin.y));
  }
  addPointer(h, frame, W, H, placed) {
    const ox = clamp(h.origin.x, frame.l, frame.r), oy = clamp(h.origin.y, frame.t, frame.b);
    const dx = h.at.x - ox, dy = h.at.y - oy;
    const reach = Math.min(edgeReach(dx, ox, frame.l, frame.r), edgeReach(dy, oy, frame.t, frame.b));
    const px = ox + dx * reach, py = oy + dy * reach;
    const chip = this.pointerChip(h, dx, dy);
    this.layer.append(chip);
    placeChip(chip, px, py, Math.abs(px - frame.l) < 1 || Math.abs(px - frame.r) < 1, W, H, placed);
  }
  pointerChip(h, dx, dy) {
    const arrow = el('span', { class: 'arrow', style: `transform:rotate(${(Math.atan2(dy, dx) * 180) / Math.PI}deg)` }, '➜');
    const name = el('span', { class: 'name' }, h.label);
    return el('button', { class: 'edge-pointer', style: `--pc:${h.color}`, title: `${h.title} · click to go there`, onclick: (e) => { e.stopPropagation(); this.viewport.glideTo(h.to); }, onmouseenter: () => clearTimeout(this.timer), onmouseleave: () => this.show(null) }, ...(dx < 0 ? [arrow, name] : [name, arrow]));
  }
}
function edgeReach(d, origin, lo, hi) {
  if (d > 0) return (hi - origin) / d;
  return d < 0 ? (lo - origin) / d : Infinity;
}
function clamp(v, lo, hi) { return Math.min(hi, Math.max(lo, v)); }
function placeChip(chip, px, py, alongY, W, H, placed) {
  const w = chip.offsetWidth, h = chip.offsetHeight;
  const top = POINTER_TOP - h / 2;
  const x0 = clamp(px - w / 2, 4, Math.max(4, W - w - 4)), y0 = clamp(py - h / 2, top, Math.max(top, H - h - 4));
  let box = { x: x0, y: y0, w, h };
  for (let i = 1; i < 40 && placed.some((o) => overlaps(box, { x: o.x - 3, y: o.y - 3, w: o.w + 6, h: o.h + 6 })); i++) {
    const shift = Math.ceil(i / 2) * (i % 2 ? 1 : -1) * ((alongY ? h : w / 2) + 4);
    box = alongY ? { ...box, y: clamp(y0 + shift, top, Math.max(top, H - h - 4)) } : { ...box, x: clamp(x0 + shift, 4, Math.max(4, W - w - 4)) };
  }
  placed.push(box);
  chip.style.left = `${box.x}px`;
  chip.style.top = `${box.y}px`;
}
