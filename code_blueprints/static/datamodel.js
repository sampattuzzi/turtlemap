const DATA_LIMIT = 250;
const DATA_END_WORDS = { one: 'one', optional: 'zero or one', many: 'many' };
const DATA_MARKERS = {
  one: '<path d="M16,1 V15 M11,1 V15"/>',
  optional: '<circle cx="8" cy="8" r="4"/><path d="M16,1 V15"/>',
  many: '<circle cx="6" cy="8" r="4"/><path d="M12,8 L24,1 M12,8 L24,8 M12,8 L24,15"/>',
};

function buildDataScene(ctx, scope = 'root') {
  const model = dataModel(net(), scope);
  if (model.core > DATA_LIMIT) return messageScene(`${model.core} data classes are too many to draw at once. Pick a package or module in the list above the view.`);
  if (!model.classes.length) return messageScene('No dataclasses, models or enums were found here.');
  const scene = new Scene(ctx);
  const rootEl = el('div', { class: 'nroot data-root', 'data-id': 'root' });
  const inner = el('div', { class: 'ninner' });
  const open = new Set(model.classes.map((n) => n.id));
  const boxOf = (n) => {
    const box = netBoxEl(n, open, ctx);
    if (n.outside) box.classList.add('outside');
    const module = moduleNodeOf(n.id);
    const head = box.querySelector(':scope > .nhead');
    if (module && head) head.append(el('span', { class: 'nsub' }, moduleFileName(module)));
    return box;
  };
  rootEl.append(inner);
  const rootV = scene.add(rootEl);
  NET_ROUTES.clear(); NET_SLACK.clear(); NET_COLUMNS.clear();
  const pieces = dataGroups(model).map((group, i) => {
    if (group.length === 1 && !model.links.some((l) => l.from === group[0].id || l.to === group[0].id)) { const box = boxOf(group[0]); inner.append(box); return box; }
    const groupRoot = { id: `group:${i}`, kind: 'root', name: 'group', depth: 0, children: group, parent: null };
    for (const n of group) n.parent = groupRoot;
    const groupInner = el('div', { class: 'ninner' }, group.map(boxOf));
    const groupEl = el('div', { class: 'nroot data-group', 'data-id': groupRoot.id }, groupInner);
    inner.append(groupEl);
    const members = new Set(group.map((n) => n.id));
    layoutNet(groupRoot, groupEl, model.links.filter((l) => l.from !== l.to && members.has(l.from) && members.has(l.to)), model);
    return groupEl;
  });
  packPieces(inner, pieces);
  scene.measure();
  scene.finish(40);
  const rects = new Map();
  const sizes = [];
  rootEl.querySelectorAll('.nb').forEach((b) => {
    let x = 0, y = 0, cur = b;
    while (cur && cur !== rootEl) { x += cur.offsetLeft; y += cur.offsetTop; cur = cur.offsetParent; }
    const head = b.querySelector(':scope > .nhead');
    rects.set(b.dataset.id, { x: rootV.x + x, y: rootV.y + y, w: b.offsetWidth, h: b.offsetHeight, anchorY: head ? head.offsetHeight / 2 : b.offsetHeight / 2, el: b });
    sizes.push({ el: b, w: b.offsetWidth, h: b.offsetHeight });
  });
  const routeOffset = (route) => { let x = rootV.x, y = rootV.y, cur = route.inner; while (cur && cur !== rootEl) { x += cur.offsetLeft; y += cur.offsetTop; cur = cur.offsetParent; } return { x, y }; };
  const defs = svg('defs');
  defs.innerHTML = Object.entries(DATA_MARKERS).map(([end, shape]) => `<marker id="er-${end}" class="er-marker" viewBox="0 0 24 16" refX="24" refY="8" markerWidth="24" markerHeight="16" markerUnits="userSpaceOnUse" orient="auto-start-reverse">${shape}</marker>`).join('')
    + '<marker id="er-base" viewBox="0 0 14 14" refX="13" refY="7" markerWidth="14" markerHeight="14" markerUnits="userSpaceOnUse" orient="auto"><path d="M1,1 L13,7 L1,13 z" style="fill:var(--canvas);stroke:var(--rel-inherits)" stroke-width="1.6"/></marker>';
  scene.svg.append(defs);
  const drawn = model.links.map((link) => drawDataLink(scene, link, rects, routeOffset));
  const middles = drawn.map((d) => d.path.getPointAtLength(d.path.getTotalLength() / 2));
  drawn.forEach((d, i) => { d.text.setAttribute('x', middles[i].x); d.text.setAttribute('y', middles[i].y - 6); });
  scene.el.addEventListener('mouseover', (e) => {
    const box = e.target.closest('.nb');
    const id = box ? model.chain(box.dataset.id)[1].id : null;
    scene.el.classList.toggle('has-hot', Boolean(id));
    for (const d of drawn) {
      const hot = Boolean(id) && (d.link.from === id || d.link.to === id);
      d.path.classList.toggle('hot', hot);
      d.text.classList.toggle('hot', hot);
    }
  });
  scene.el.addEventListener('mouseleave', () => { scene.el.classList.remove('has-hot'); for (const d of drawn) { d.path.classList.remove('hot'); d.text.classList.remove('hot'); } });
  scene.sizes = sizes;
  scene.netRects = rects;
  scene.effective = open;
  return scene;
}

function dataScopes(N) {
  const counts = dataCounts(N);
  const scopes = [];
  const walk = (n) => {
    if (n.kind === 'root' || n.kind === 'package' || n.kind === 'module') {
      if (counts.get(n.id)) scopes.push({ id: n.id, depth: n.depth, label: n.kind === 'root' ? 'Whole project' : n.kind === 'package' ? `${n.name}/` : n.name, count: counts.get(n.id) });
      for (const k of n.children) walk(k);
    }
  };
  walk(N.root);
  return scopes;
}

function dataScopeFor(N, id) {
  const counts = dataCounts(N);
  const chain = id && N.nodes.has(id) ? N.chain(id) : [N.root];
  const unit = [...chain].reverse().find((n) => (n.kind === 'module' || n.kind === 'package' || n.kind === 'root') && counts.get(n.id));
  return unit ? unit.id : 'root';
}

function packPieces(inner, pieces) {
  const GAP = 48, PAD = 14;
  const sized = pieces.map((el) => ({ el, w: el.offsetWidth + GAP, h: el.offsetHeight + GAP }));
  const area = sized.reduce((sum, p) => sum + p.w * p.h, 0);
  const width = Math.max(1400, Math.sqrt(area * 1.3), ...sized.map((p) => p.w));
  let skyline = [{ x: 0, w: width, y: 0 }];
  for (const piece of [...sized].sort((p, q) => q.h - p.h || q.w - p.w)) {
    let best = null;
    for (const start of skyline) {
      if (start.x + piece.w > width) break;
      const y = Math.max(...skyline.filter((s) => s.x < start.x + piece.w && s.x + s.w > start.x).map((s) => s.y));
      if (!best || y < best.y) best = { x: start.x, y };
    }
    piece.el.style.left = `${PAD + best.x}px`;
    piece.el.style.top = `${PAD + best.y}px`;
    skyline = raiseSkyline(skyline, best.x, piece.w, best.y + piece.h);
  }
  inner.style.width = `${Math.max(...sized.map((p) => p.el.offsetLeft + p.el.offsetWidth)) + PAD}px`;
  inner.style.height = `${Math.max(...sized.map((p) => p.el.offsetTop + p.el.offsetHeight)) + PAD}px`;
}

function raiseSkyline(skyline, x, w, y) {
  const next = [];
  for (const s of skyline) {
    if (s.x + s.w <= x || s.x >= x + w) { next.push(s); continue; }
    if (s.x < x) next.push({ x: s.x, w: x - s.x, y: s.y });
    if (s.x + s.w > x + w) next.push({ x: x + w, w: s.x + s.w - x - w, y: s.y });
  }
  next.push({ x, w, y });
  next.sort((p, q) => p.x - q.x);
  const merged = [];
  for (const s of next) {
    const last = merged[merged.length - 1];
    if (last && last.y === s.y && last.x + last.w === s.x) last.w += s.w; else merged.push({ ...s });
  }
  return merged;
}

function dataGroups(model) {
  const parent = new Map(model.classes.map((c) => [c.id, c.id]));
  const find = (id) => { while (parent.get(id) !== id) { parent.set(id, parent.get(parent.get(id))); id = parent.get(id); } return id; };
  for (const l of model.links) parent.set(find(l.from), find(l.to));
  const groups = new Map();
  for (const c of model.classes) { const r = find(c.id); if (!groups.has(r)) groups.set(r, []); groups.get(r).push(c); }
  return [...groups.values()].sort((p, q) => q.length - p.length);
}

function dataCounts(N) {
  if (N.dataCounts) return N.dataCounts;
  const counts = new Map();
  for (const n of N.nodes.values()) if (isDataClass(n)) for (const a of N.chain(n.id)) counts.set(a.id, (counts.get(a.id) || 0) + 1);
  N.dataCounts = counts;
  return counts;
}

function dataModel(N, scope) {
  const root = { id: 'root', kind: 'root', name: 'data', depth: 0, children: [], parent: null };
  const nodes = new Map([['root', root]]);
  const all = new Map();
  for (const n of N.nodes.values()) {
    if (!isDataClass(n)) continue;
    const copy = { ...n, parent: root, depth: 1, children: [] };
    copy.children = n.children.filter((k) => k.kind === 'field' || k.kind === 'member').map((k) => ({ ...k, parent: copy, depth: 2, children: [] }));
    all.set(copy.id, copy);
  }
  const holds = [];
  for (const c of all.values()) for (const field of c.children) {
    if (field.kind !== 'field' || !field.type) continue;
    for (const [ref, end] of [[field.type.ref, field.type.opt ? 'optional' : 'one'], [field.type.items, 'many']]) {
      const target = ref ? `cls:${ref.path}:${ref.sym}` : null;
      if (target && all.has(target)) holds.push({ from: c.id, to: target, field, end });
    }
  }
  const bases = N.edges.filter((e) => (e.kinds.has('inherits') || e.kinds.has('realizes')) && all.has(e.from) && all.has(e.to)).map((e) => ({ from: e.from, to: e.to, base: true }));
  const inScope = (id) => scope === 'root' || N.chain(id).some((a) => a.id === scope);
  const core = new Set([...all.keys()].filter(inScope));
  const links = [...pairHolds(holds), ...bases].filter((l) => core.has(l.from) || core.has(l.to));
  const shown = new Set([...core, ...links.flatMap((l) => [l.from, l.to])]);
  const classes = [];
  if (core.size <= DATA_LIMIT) for (const [id, copy] of all) {
    if (!shown.has(id)) continue;
    copy.outside = !core.has(id);
    for (const k of copy.children) nodes.set(k.id, k);
    nodes.set(id, copy);
    root.children.push(copy);
    classes.push(copy);
  }
  const chain = (id) => { const out = []; for (let n = nodes.get(id); n; n = n.parent) out.unshift(n); return out; };
  return { root, nodes, chain, classes, links, core: core.size };
}

function isDataClass(n) {
  return n.kind === 'class' && Boolean(n.sym) && (n.sym.kind === 'enum' || n.sym.cat === 'struct');
}

function pairHolds(holds) {
  const pending = [...holds];
  const links = [];
  while (pending.length) {
    const hold = pending.shift();
    const at = hold.from === hold.to ? -1 : pending.findIndex((o) => o.from === hold.to && o.to === hold.from);
    const back = at >= 0 ? pending.splice(at, 1)[0] : null;
    links.push({ from: hold.from, to: hold.to, fromField: hold.field, toField: back ? back.field : null, fromEnd: back ? back.end : 'one', toEnd: hold.end });
  }
  return links;
}

function drawDataLink(scene, link, rects, routeOffset) {
  const ra = rects.get(link.from), rb = rects.get(link.to);
  const fa = link.fromField ? rects.get(link.fromField.id) : null;
  const fb = link.toField ? rects.get(link.toField.id) : null;
  const ya = fa ? fa.y + fa.h / 2 : ra.y + ra.anchorY;
  const yb = fb ? fb.y + fb.h / 2 : rb.y + rb.anchorY;
  let d;
  if (link.from === link.to) {
    const x = ra.x + ra.w + 2;
    d = `M${x},${ya} C${x + 70},${ya} ${x + 70},${yb} ${x},${yb}`;
  } else if (rb.x >= ra.x + ra.w) {
    const route = NET_ROUTES.get(`${link.from}|${link.to}`);
    const at = route ? routeOffset(route) : null;
    const spans = route ? route.via.map((v) => ({ x: at.x + v.x, y: at.y + v.y + 3, w: v.w })) : [];
    const x1 = ra.x + ra.w, out = x1 + (NET_SLACK.get(link.from) || 0), x2 = rb.x - 2;
    const dx = Math.max(50, (x2 - out) * 0.45);
    const curve = spans.length ? routedPath(out, ya, x2, yb, spans, 50) : `M${out},${ya} C${out + dx},${ya} ${x2 - dx},${yb} ${x2},${yb}`;
    d = out > x1 + 1 ? `M${x1},${ya} L${curve.slice(1)}` : curve;
  } else {
    const route = NET_ROUTES.get(`${link.from}|${link.to}`);
    const at = route ? routeOffset(route) : null;
    const spans = route ? route.via.map((v) => ({ x: at.x + v.x, y: at.y + v.y + 3, w: v.w })) : [];
    const x1 = ra.x + ra.w, left = Math.min(ra.x, rb.x);
    d = loopBackPath(x1, ya, rb.x - 2, yb, spans.length ? spans : [{ x: left, w: x1 + (NET_SLACK.get(link.from) || 0) - left, y: Math.min(ra.y, rb.y) - 12 }]);
  }
  const path = svg('path', { d, class: link.base ? 'rel er-base' : 'rel er-link' });
  if (link.base) path.setAttribute('marker-end', 'url(#er-base)');
  else { path.setAttribute('marker-start', `url(#er-${link.fromEnd})`); path.setAttribute('marker-end', `url(#er-${link.toEnd})`); }
  const text = svg('text', { class: `rel-label ${link.base ? 'k-inherits' : 'k-has'}`, 'text-anchor': 'middle' });
  text.textContent = link.base ? 'inherits' : `${link.toField ? `${link.fromField.name} ⇄ ${link.toField.name}` : link.fromField.name} · ${DATA_END_WORDS[link.fromEnd]} to ${DATA_END_WORDS[link.toEnd]}`;
  scene.svg.append(path, text);
  return { link, path, text };
}
