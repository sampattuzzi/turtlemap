async function layoutModules() {
  const data = await import('./core/data.js');
  const { ensureFunction } = await import('./core/project.js');
  const { buildFunctionScene } = await import('./blueprint/nodes.js');
  const { refOf } = await import('./map/boxes.js');
  return { data, ensureFunction, buildFunctionScene, refOf };
}

function anchorsOf(d) {
  const points = [];
  for (const [, command, args] of d.matchAll(/([MLC])([^MLC]*)/g)) {
    const numbers = args.match(/-?\d+(?:\.\d+)?(?:e-?\d+)?/g).map(Number);
    points.push({ x: numbers[numbers.length - 2], y: numbers[numbers.length - 1], command });
  }
  return points;
}

function wiresIn(sceneEl) {
  return [...sceneEl.querySelectorAll('svg.wires > path')].filter((p) => !p.classList.contains('hot-clone')).map((p) => anchorsOf(p.getAttribute('d') || ''));
}

function travelOf(points) {
  return points.slice(1).reduce((sum, p, i) => sum + Math.abs(p.y - points[i].y), 0);
}

function crosses(a, b, c, d) {
  const turn = (p, q, r) => Math.sign((q.x - p.x) * (r.y - p.y) - (q.y - p.y) * (r.x - p.x));
  return turn(a, b, c) * turn(a, b, d) < 0 && turn(c, d, a) * turn(c, d, b) < 0;
}

function crossingsOf(wires) {
  const segments = wires.flatMap((points, w) => points.slice(1).map((p, i) => ({ w, a: points[i], b: p })));
  let count = 0;
  for (let i = 0; i < segments.length; i++) for (let j = i + 1; j < segments.length; j++) {
    const s = segments[i], t = segments[j];
    if (s.w !== t.w && crosses(s.a, s.b, t.a, t.b)) count++;
  }
  return count;
}

function summarise(label, scenes) {
  const wires = scenes.flatMap((s) => s.wires);
  const straight = wires.filter((w) => travelOf(w) < 0.5).length;
  const travel = wires.reduce((sum, w) => sum + travelOf(w), 0);
  return {
    label,
    scenes: scenes.length,
    wires: wires.length,
    straight: `${((100 * straight) / Math.max(1, wires.length)).toFixed(1)}%`,
    travelPerWire: +(travel / Math.max(1, wires.length)).toFixed(1),
    crossings: scenes.reduce((sum, s) => sum + crossingsOf(s.wires), 0),
    height: Math.round(scenes.reduce((sum, s) => sum + s.height, 0)),
    msPerScene: +(scenes.reduce((sum, s) => sum + s.ms, 0) / Math.max(1, scenes.length)).toFixed(1),
  };
}

function measureScene(scene, ms) {
  const result = { wires: wiresIn(scene.el), height: scene.height, ms };
  scene.el.remove();
  return result;
}

async function measureBlueprints(modules, ctx, limit) {
  const { data, ensureFunction, buildFunctionScene, refOf } = modules;
  const functions = Object.values(data.FILES).filter((f) => !data.isTestPath(f.path)).flatMap((f) => Object.values(f.index).filter((s) => s.kind === 'function')).sort((a, b) => `${a.file}:${a.qual}`.localeCompare(`${b.file}:${b.qual}`));
  const step = Math.max(1, functions.length / limit);
  const sample = Array.from({ length: Math.min(limit, functions.length) }, (_, i) => functions[Math.floor(i * step)]);
  const blueprints = [];
  for (const fn of sample) {
    try { await ensureFunction(refOf(fn)); } catch (error) { continue; }
    const start = performance.now();
    const scene = buildFunctionScene(fn, ctx);
    blueprints.push(measureScene(scene, performance.now() - start));
  }
  return summarise('blueprints', blueprints);
}

(async (limit = 150) => {
  const modules = await layoutModules();
  const ctx = { openButton: () => null, go() {}, select() {}, toggle() {}, activate() {} };
  const rows = [await measureBlueprints(modules, ctx, limit)];
  console.table(rows);
  return rows;
})();
