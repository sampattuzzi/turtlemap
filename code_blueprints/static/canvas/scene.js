import { el, svg } from '../core/dom.js';
import { settings } from '../core/settings.js';
export function plain(name) {
  if (!settings.plain || !name) return name;
  if (name === '__init__' || name === 'constructor') return 'set up';
  return name.replace(/\bself\./g, '').replace(/(^|[.\s])_+/g, '$1').replace(/_+/g, ' ').replace(/\./g, ' › ');
}
export function routedPath(ax, ay, bx, by, via, minDx = 36, lean = 0) {
  let d = `M${ax},${ay}`, cx = ax, cy = ay;
  const curveTo = (x, y) => { const dx = Math.max(Math.min(minDx, Math.abs(x - cx) * 0.5 + 12), Math.abs(x - cx) * 0.5); d += ` C${cx + dx + lean},${cy} ${x - dx + lean},${y} ${x},${y}`; cx = x; cy = y; };
  for (const p of via) { curveTo(p.x, p.y); d += ` L${p.x + p.w},${p.y}`; cx = p.x + p.w; }
  curveTo(bx, by);
  return d;
}
export function loopBackPath(ax, ay, bx, by, via, turn = LOOP_TURN) {
  const first = via[0], right = first.x + first.w;
  const bend = (y0, y1) => turn * Math.min(1, 0.45 + Math.abs(y1 - y0) / 160);
  let d = `M${ax},${ay} L${right},${ay} C${right + bend(ay, first.y)},${ay} ${right + bend(ay, first.y)},${first.y} ${right},${first.y} L${first.x},${first.y}`;
  let cx = first.x, cy = first.y;
  for (const p of via.slice(1)) {
    const end = p.x + p.w, dx = Math.max(12, (cx - end) * 0.5);
    d += ` C${cx - dx},${cy} ${end + dx},${p.y} ${end},${p.y} L${p.x},${p.y}`;
    cx = p.x; cy = p.y;
  }
  return `${d} C${cx - bend(cy, by)},${cy} ${bx - bend(cy, by)},${by} ${bx},${by}`;
}
export const overlaps = (a, v) => a.x < v.x + v.w && v.x < a.x + a.w && a.y < v.y + v.h && v.y < a.y + a.h;
export function pathBox(path) {
  const numbers = (path.getAttribute('d') || '').match(/-?\d+(?:\.\d+)?(?:e-?\d+)?/g) || [];
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (let i = 0; i + 1 < numbers.length; i += 2) { const x = +numbers[i], y = +numbers[i + 1]; if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
  if (x0 === Infinity) return { x: -1e9, y: -1e9, w: 2e9, h: 2e9 };
  return { x: x0 - 16, y: y0 - 16, w: x1 - x0 + 32, h: y1 - y0 + 32 };
}
export function setCulled(element, state, culled) {
  if (state.culled === culled) return;
  state.culled = culled;
  element.style.display = culled ? 'none' : '';
}
export class Scene {
  constructor(ctx) {
    this.ctx = ctx; this.nodes = []; this.wires = []; this.el = el('div', { class: 'scene' }); this.svg = svg('svg', { class: 'wires' }); this.layer = el('div', { class: 'layer' }); this.el.append(this.svg, this.layer); document.getElementById('measure').append(this.el);
    this.wireCard = null; this.wireKey = '';
    this.el.addEventListener('mousemove', (e) => this.pointAtWires(e));
    this.el.addEventListener('mouseout', (e) => { if (e.target.closest('.wire-hit') && !(e.relatedTarget instanceof Element && e.relatedTarget.closest('.wire-hit'))) this.dropWires(); });
    this.el.addEventListener('mouseleave', () => this.dropWires());
  }
  add(element, data = {}) { const v = { el: element, data, x: 0, y: 0 }; element.classList.add('node'); this.layer.append(element); this.nodes.push(v); return v; }
  wire(a, ak, b, bk, cls, type) { const w = { a, ak, b, bk, cls, type }; this.wires.push(w); return w; }
  measure() {
    for (const n of this.nodes) this.measureNode(n);
  }
  measureNode(n) {
    n.w = n.el.offsetWidth; n.h = n.el.offsetHeight;
    const extra = Object.fromEntries(Object.entries(n.pins || {}).filter(([key]) => key.startsWith('in:cap:')));
    n.pins = extra;
    n.el.querySelectorAll('[data-pin]').forEach((p) => {
      if (p.closest('.node') !== n.el) return;
      const s = p.querySelector('.shape') || p;
      let x = 0, y = 0, cur = s;
      while (cur && cur !== n.el) { x += cur.offsetLeft; y += cur.offsetTop; cur = cur.offsetParent; }
      n.pins[p.dataset.pin] = { dx: x + s.offsetWidth / 2, dy: y + s.offsetHeight / 2 };
    });
  }
  finish(pad = 40) {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    const all = [...this.nodes, ...(this.dummies || [])];
    for (const n of all) { x0 = Math.min(x0, n.x); y0 = Math.min(y0, n.y); x1 = Math.max(x1, n.x + n.w); y1 = Math.max(y1, n.y + n.h); }
    if (!all.length) { x0 = y0 = 0; x1 = y1 = 10; }
    for (const n of all) { n.x += pad - x0; n.y += pad - y0; if (n.el) { n.el.style.left = `${n.x}px`; n.el.style.top = `${n.y}px`; } }
    this.width = x1 - x0 + 2 * pad; this.height = y1 - y0 + 2 * pad;
    Object.assign(this.el.style, { width: `${this.width}px`, height: `${this.height}px` });
    this.svg.setAttribute('width', this.width); this.svg.setAttribute('height', this.height);
    this.svg.innerHTML = '';
    for (const w of this.wires) {
      const pa = w.a.pins[w.ak], pb = w.b.pins[w.bk];
      if (!pa || !pb) continue;
      const path = svg('path', { d: routedPath(w.a.x + pa.dx, w.a.y + pa.dy, w.b.x + pb.dx, w.b.y + pb.dy, (w.via || []).map((d) => ({ x: d.x, y: d.y + d.pins.d.dy, w: d.w }))), class: `wire ${w.cls || ''}${w.diff ? ` wire-${w.diff}` : ''}` });
      if (!w.cls) path.style.stroke = `var(--t-${w.type ? w.type.cat : 'any'})`;
      if (w.cls === 'cell') path.style.stroke = `color-mix(in srgb, var(--t-${w.type ? w.type.cat : 'any'}) 45%, #5f646d)`;
      w.path = path; this.svg.append(path);
    }
    this.wires.forEach((w, i) => { if (w.path) { w.hit = svg('path', { d: w.path.getAttribute('d'), class: 'wire-hit', 'data-wire': i }); this.svg.append(w.hit); } });
  }
  cull(view) {
    for (const n of this.nodes) setCulled(n.el, n, !overlaps(n, view));
    for (const w of this.wires) {
      if (!w.path) continue;
      if (!w.box) w.box = pathBox(w.path);
      setCulled(w.path, w, !overlaps(w.box, view));
      w.hit.style.display = w.culled ? 'none' : '';
    }
  }
  pointAtWires(e) {
    if (!e.target.closest('.wire-hit')) return;
    const under = document.elementsFromPoint(e.clientX, e.clientY).filter((x) => x.classList.contains('wire-hit') && this.svg.contains(x)).map((x) => this.wires[+x.dataset.wire]);
    const key = under.map((w) => this.wires.indexOf(w)).join(' ');
    if (key !== this.wireKey) {
      this.dropWires();
      if (!under.length) return;
      this.wireKey = key;
      this.el.classList.add('has-hot');
      for (const w of under) {
        w.path.classList.add('hot');
        for (const [node, pin] of [[w.a, w.ak], [w.b, w.bk]]) for (const p of pinElsOf(node, pin)) { p.classList.add('pin-hot'); p.style.setProperty('--pin-c', wireColour(w)); }
      }
      this.wireCard = wireCardEl(under);
      document.body.append(this.wireCard);
    }
    if (this.wireCard) placeCard(this.wireCard, e, [...this.el.querySelectorAll('.pin-hot')].map((pin) => pin.getBoundingClientRect()));
  }
  dropWires() {
    if (this.wireCard) { this.wireCard.remove(); this.wireCard = null; }
    if (!this.wireKey) return;
    this.wireKey = '';
    this.el.classList.remove('has-hot');
    for (const w of this.wires) if (w.path) w.path.classList.remove('hot');
    this.el.querySelectorAll('.pin-hot').forEach((p) => p.classList.remove('pin-hot'));
  }
  hover(node, on) {
    this.el.classList.toggle('has-hot', on);
    for (const w of this.wires) if (w.path) w.path.classList.toggle('hot', on && (w.a === node || w.b === node));
    if (this.onHot) this.onHot(on ? this.wires.filter((w) => w.path && w.a !== w.b && (w.a === node || w.b === node)).map((w) => wireEnds(w, node)) : null);
  }
}
function pinElsOf(node, key) {
  return [...node.el.querySelectorAll(`[data-pin="${CSS.escape(key)}"]`)].filter((p) => p.closest('.node') === node.el);
}
function wireColour(w) {
  return w.cls === 'exec' ? 'var(--exec)' : `var(--t-${w.type ? w.type.cat : 'any'})`;
}
function wireCardEl(wires) {
  const shown = wires.slice(0, 6);
  const end = (node, key) => `${plain(node.data.title || node.data.kind || '')} › ${plain(key.replace(/^(out|in):/, ''))}`;
  return el('div', { class: 'edge-card wire-card' },
    shown.map((w, i) => el('div', { class: `edge-card-section${i ? ' divided' : ''}` },
      el('div', { class: 'wire-card-ends' }, el('span', {}, end(w.a, w.ak)), el('span', { class: 'udim' }, '→'), el('span', {}, end(w.b, w.bk))),
      w.cls === 'exec' ? el('div', { class: 'udim' }, 'Runs next, in this order') : el('code', { class: 'wire-card-type', style: `color:${wireColour(w)}` }, `${w.cls === 'cell' ? 'the variable itself · ' : ''}${w.type ? w.type.label : 'Any'}`))),
    wires.length > shown.length ? el('div', { class: 'udim' }, `and ${wires.length - shown.length} more`) : null);
}
export function placeCard(card, e, avoid = []) {
  const box = card.getBoundingClientRect();
  const fit = (x, y) => ({ x: Math.max(12, Math.min(x, window.innerWidth - box.width - 12)), y: Math.max(12, Math.min(y, window.innerHeight - box.height - 12)) });
  const spots = [fit(e.clientX + 16, e.clientY + 16), fit(e.clientX + 16, e.clientY - box.height - 16), fit(e.clientX - box.width - 16, e.clientY + 16), fit(e.clientX - box.width - 16, e.clientY - box.height - 16)];
  const clear = (spot) => avoid.every((r) => spot.x > r.right + 6 || spot.x + box.width < r.left - 6 || spot.y > r.bottom + 6 || spot.y + box.height < r.top - 6);
  const spot = spots.find(clear) || spots[0];
  card.style.left = `${spot.x}px`;
  card.style.top = `${spot.y}px`;
}
function wireEnds(w, node) {
  const outgoing = w.a === node;
  const other = outgoing ? w.b : w.a;
  const end = (n, key) => ({ x: n.x + n.pins[key].dx, y: n.y + n.pins[key].dy });
  const label = plain(other.data.title || other.data.kind || '');
  return {
    key: other.data.id || label,
    from: end(node, outgoing ? w.ak : w.bk),
    to: end(other, outgoing ? w.bk : w.ak),
    label,
    color: wireColour(w),
    title: `${outgoing ? 'Goes to' : 'Comes from'} ${label}`,
  };
}
export const LOOP_TURN = 34;
export function messageScene(text) {
  const box = el('div', { class: 'scene-message' }, text);
  return { el: box, width: 480, height: 80, nodes: [], sizes: [] };
}
