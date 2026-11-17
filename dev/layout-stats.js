(async (limit = 150) => {
  const ctx = { openButton: () => null, go() {}, select() {}, toggle() {}, activate() {} };
  const anchorsOf = (d) => {
    const points = [];
    for (const [, command, args] of d.matchAll(/([MLC])([^MLC]*)/g)) {
      const numbers = args.match(/-?\d+(?:\.\d+)?(?:e-?\d+)?/g).map(Number);
      points.push({ x: numbers[numbers.length - 2], y: numbers[numbers.length - 1], command });
    }
    return points;
  };
  const wiresIn = (sceneEl) => [...sceneEl.querySelectorAll('svg.wires > path')].filter((p) => !p.classList.contains('hot-clone')).map((p) => anchorsOf(p.getAttribute('d') || ''));
  const travelOf = (points) => points.slice(1).reduce((sum, p, i) => sum + Math.abs(p.y - points[i].y), 0);
  const crosses = (a, b, c, d) => {
    const turn = (p, q, r) => Math.sign((q.x - p.x) * (r.y - p.y) - (q.y - p.y) * (r.x - p.x));
    return turn(a, b, c) * turn(a, b, d) < 0 && turn(c, d, a) * turn(c, d, b) < 0;
  };
  const crossingsOf = (wires) => {
    const segments = wires.flatMap((points, w) => points.slice(1).map((p, i) => ({ w, a: points[i], b: p })));
    let count = 0;
    for (let i = 0; i < segments.length; i++) for (let j = i + 1; j < segments.length; j++) {
      const s = segments[i], t = segments[j];
      if (s.w !== t.w && crosses(s.a, s.b, t.a, t.b)) count++;
    }
    return count;
  };
  const summarise = (label, scenes, withCrossings) => {
    const wires = scenes.flatMap((s) => s.wires);
    const straight = wires.filter((w) => travelOf(w) < 0.5).length;
    const travel = wires.reduce((sum, w) => sum + travelOf(w), 0);
    return {
      label,
      scenes: scenes.length,
      wires: wires.length,
      straight: `${((100 * straight) / Math.max(1, wires.length)).toFixed(1)}%`,
      travelPerWire: +(travel / Math.max(1, wires.length)).toFixed(1),
      crossings: withCrossings ? scenes.reduce((sum, s) => sum + crossingsOf(s.wires), 0) : null,
      height: Math.round(scenes.reduce((sum, s) => sum + s.height, 0)),
    };
  };
  const measure = (scene) => { const result = { wires: wiresIn(scene.el), height: scene.height }; scene.el.remove(); return result; };
  const functions = Object.values(FILES).filter((f) => !isTestPath(f.path)).flatMap((f) => Object.values(f.index).filter((s) => s.kind === 'function')).sort((a, b) => `${a.file}:${a.qual}`.localeCompare(`${b.file}:${b.qual}`));
  const step = Math.max(1, functions.length / limit);
  const sample = Array.from({ length: Math.min(limit, functions.length) }, (_, i) => functions[Math.floor(i * step)]);
  const blueprints = [];
  for (const fn of sample) {
    try { await ensureFunction(refOf(fn)); } catch (error) { continue; }
    blueprints.push(measure(buildFunctionScene(fn, ctx)));
  }
  const maps = [2, 3].map((depth) => {
    const expanded = new Set([...net().nodes.values()].filter((n) => n.depth > 0 && n.depth < depth && ['package', 'module', 'class'].includes(n.kind)).map((n) => n.id));
    return summarise(`map, ${depth} levels`, [measure(buildNetScene(expanded, ctx))], false);
  });
  const rows = [summarise('blueprints', blueprints, true), ...maps];
  console.table(rows);
  return rows;
})();
