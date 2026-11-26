import { layered } from './layout.js';
const FRAME_PAD = 22;
const LANE_PAD = 14;
const BAND_PAD = 6;
const FRAMES = new Set(['closure', 'loop', 'branch', 'lane', 'comprehension']);
const isFrame = (n) => FRAMES.has(n.kind);
export function framedLayout(g, byId, remeasure) {
  if (!g.nodes.some(isFrame)) {
    const { routes, dummies } = layered(g, byId);
    return { routes, dummies, routeKey: plainRouteKey };
  }
  const byNodeId = new Map(g.nodes.map((n) => [n.id, n]));
  const members = new Map();
  for (const n of g.nodes) pushTo(members, frameOf(n, byNodeId), n);
  const routes = new Map(), routeKeys = new Map(), frameDummies = new Map();
  const standIns = new Map();
  const standIn = (n) => {
    if (!isFrame(n)) return n;
    if (!standIns.has(n)) standIns.set(n, n.kind === 'closure' ? { id: n.id, kind: 'closure', title: n.title, ins: [], outs: n.outs } : { id: n.id, kind: n.kind, title: n.title, ins: n.ins, outs: carriesResult(n) ? [n.outs[0]] : [], execIn: n.execIn, execOut: n.execOut });
    return standIns.get(n);
  };
  const contentOf = (frameId) => {
    const out = [];
    for (const n of members.get(frameId) || []) { out.push(n); if (isFrame(n)) out.push(...contentOf(n.id)); }
    return out;
  };
  const framesUnder = (frameId) => [frameId, ...(members.get(frameId) || []).filter(isFrame).flatMap((n) => framesUnder(n.id))];
  const headerPin = (frame, pin) => (frame.kind === 'closure' || carriesResult(frame)) && pin === frame.outs[0].name;
  const shiftContent = (frameId, dx, dy) => {
    for (const n of contentOf(frameId)) { const v = byId.get(n); v.x += dx; v.y += dy; }
    for (const f of framesUnder(frameId)) for (const d of frameDummies.get(f) || []) { d.x += dx; d.y += dy; }
  };
  const stackLanes = (branch) => {
    const lanes = members.get(branch.id) || [];
    for (const lane of lanes) layoutFrame(lane.id);
    const bv = byId.get(branch);
    const width = Math.max(bv.headW, ...lanes.map((lane) => byId.get(lane).w));
    let y = bv.headH;
    for (const lane of lanes) {
      const lv = byId.get(lane);
      lv.el.style.width = `${width}px`;
      remeasure(lv);
      lv.x = 0; lv.y = y;
      shiftContent(lane.id, 0, y);
      y += lv.h;
    }
    bv.el.style.width = `${width}px`; bv.el.style.height = `${y}px`;
    remeasure(bv);
  };
  const layoutFrame = (frameId) => {
    const own = members.get(frameId) || [];
    const frame = frameId ? byNodeId.get(frameId) : null;
    if (frame && frame.kind === 'branch') { stackLanes(frame); return; }
    for (const n of own) if (isFrame(n)) layoutFrame(n.id);
    const views = new Map(byId);
    const sub = { nodes: [], edges: [], exec: [] };
    let head = null;
    if (frame) {
      const fv = byId.get(frame);
      head = { id: `${frame.id}#head`, kind: 'entry', execOut: true, overhead: true, ins: [], outs: [] };
      const pins = { then: fv.pins.start };
      for (const [key, pin] of Object.entries(fv.pins)) if (key.startsWith('out:') && !headerPin(frame, key.slice(4))) pins[key] = pin;
      views.set(head, { w: fv.headW, h: fv.headH, x: 0, y: 0, pins });
      sub.nodes.push(head);
    }
    for (const n of own) { const s = standIn(n); views.set(s, byId.get(n)); sub.nodes.push(s); }
    const memberOf = (n) => { let cur = n; while (cur && frameOf(cur, byNodeId) !== frameId) cur = byNodeId.get(cur.parent); return cur || null; };
    const sourceOf = (n, pin) => (frame && n === frame && !headerPin(frame, pin) ? head : memberOf(n));
    for (const e of g.edges) {
      const a = sourceOf(e.from, e.fp), b = memberOf(e.to);
      if (!a || !b || (a !== head && a !== e.from) || (a === b && b !== e.to)) continue;
      let tp = e.tp;
      if (b !== e.to) {
        tp = `cap:${e.to.id}:${e.tp}`;
        const inner = byId.get(e.to), outer = byId.get(b), pin = inner.pins[`in:${e.tp}`];
        if (pin) outer.pins[`in:${tp}`] = { dx: 0, dy: inner.y - outer.y + pin.dy };
      }
      const from = a === head ? head : standIn(a), to = standIn(b);
      sub.edges.push({ from, fp: e.fp, to, tp });
      routeKeys.set(e, `${from.id}|out:${e.fp}|${to.id}|in:${tp}`);
    }
    for (const e of g.exec) {
      const a = frame && e.from === frame && e.fp === 'start' ? head : memberOf(e.from), b = memberOf(e.to);
      if (!a || !b || b !== e.to || (a !== head && a !== e.from)) continue;
      const fp = a === head ? 'then' : e.fp;
      const from = a === head ? head : standIn(a);
      sub.exec.push({ from, fp, to: standIn(b) });
      routeKeys.set(e, `${from.id}|${fp}|${b.id}|exec-in`);
    }
    if (!frame && !sub.nodes.some((n) => n.kind === 'entry')) return;
    const placed = layered(sub, views);
    for (const [key, via] of placed.routes) routes.set(key, via);
    frameDummies.set(frameId, placed.dummies);
    for (const n of own) if (isFrame(n)) { const v = byId.get(n); shiftContent(n.id, v.x, v.y); }
    if (frame) fitFrame(frame, own, placed.dummies);
  };
  const fitFrame = (frame, own, dummies) => {
    const fv = byId.get(frame);
    const boxes = [...own.map((n) => byId.get(n)), ...dummies];
    if (boxes.length) {
      const x0 = Math.min(...boxes.map((b) => b.x)), y0 = Math.min(...boxes.map((b) => b.y));
      const pad = frame.kind === 'lane' ? LANE_PAD : FRAME_PAD;
      const dx = pad + (frame.kind === 'lane' ? 12 : 0) - x0, dy = fv.headH + pad - y0;
      for (const n of own) { const v = byId.get(n); v.x += dx; v.y += dy; if (isFrame(n)) shiftContent(n.id, dx, dy); }
      for (const d of dummies) { d.x += dx; d.y += dy; }
    }
    const pad = frame.kind === 'lane' ? LANE_PAD : FRAME_PAD;
    const w = Math.max(fv.headW, ...boxes.map((b) => b.x + b.w + pad));
    const h = Math.max(fv.headH + (frame.kind === 'lane' ? 10 : 0), ...boxes.map((b) => b.y + b.h + pad));
    fv.el.style.width = `${w}px`; fv.el.style.height = `${h}px`;
    remeasure(fv);
    const band = frame.kind === 'comprehension' && own.find((n) => n.kind === 'collect');
    if (band) alongRightEdge(byId.get(band), w, h, fv.headH, remeasure);
  };
  layoutFrame('');
  const dummies = [...frameDummies.values()].flat();
  return { routes, dummies, routeKey: (e) => routeKeys.get(e) };
}
function alongRightEdge(view, width, height, top, remeasure) {
  view.el.firstChild.style.paddingTop = `${view.y - top + BAND_PAD}px`;
  view.el.style.height = `${height - top}px`;
  view.x = width - view.w; view.y = top;
  remeasure(view);
}
const carriesResult = (n) => n.kind === 'comprehension';
function plainRouteKey(e) { return e.tp === undefined ? `${e.from.id}|${e.fp}|${e.to.id}|exec-in` : `${e.from.id}|out:${e.fp}|${e.to.id}|in:${e.tp}`; }
function frameOf(n, byNodeId) { return n.parent && byNodeId.has(n.parent) ? n.parent : ''; }
function pushTo(map, key, value) { if (!map.has(key)) map.set(key, []); map.get(key).push(value); }
