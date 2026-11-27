export function seededRandom(seed = 11) {
  let state = seed;
  const next = () => (state = (state * 16807) % 2147483647) / 2147483647;
  return {
    next,
    gauss: () => Math.sqrt(-2 * Math.log(next() + 1e-9)) * Math.cos(2 * Math.PI * next()),
    pick: (list) => list[Math.floor(next() * list.length)],
  };
}
export function anneal({ score, moves, steps, limit, accepted = () => {}, seed = 11 }) {
  const random = seededRandom(seed);
  const total = moves.reduce((sum, m) => sum + m.weight, 0);
  const choose = () => { let r = random.next() * total; for (const m of moves) { r -= m.weight; if (r <= 0) return m; } return moves[moves.length - 1]; };
  let current = score();
  const start = performance.now(), T0 = Math.max(3, current * 0.003);
  for (let step = 0; step < steps && performance.now() - start < limit; step++) {
    const cooling = (1 - step / steps) ** 2, heat = T0 * cooling;
    const undo = choose().apply(random, cooling);
    if (!undo) continue;
    const next = score();
    if (next <= current || (heat > 1e-3 && random.next() < Math.exp(-(next - current) / heat))) { current = next; accepted(); } else undo();
  }
  return current;
}
