export function countBelow(sorted, y) {
  let lo = 0, hi = sorted.length;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (sorted[mid] < y) lo = mid + 1; else hi = mid; }
  return lo;
}
export function inversions(list) {
  const n = list.length;
  if (n < 2) return 0;
  if (n <= 48) return directInversions(list);
  list.sort((p, q) => p.a - q.a || p.b - q.b);
  let from = Float64Array.from(list, (A) => A.b), into = new Float64Array(n), count = 0;
  for (let width = 1; width < n; width *= 2) {
    for (let lo = 0; lo < n; lo += 2 * width) {
      const mid = Math.min(lo + width, n), hi = Math.min(lo + 2 * width, n);
      let i = lo, j = mid, k = lo;
      while (i < mid && j < hi) {
        if (from[i] <= from[j]) into[k++] = from[i++];
        else { count += mid - i; into[k++] = from[j++]; }
      }
      while (i < mid) into[k++] = from[i++];
      while (j < hi) into[k++] = from[j++];
    }
    [from, into] = [into, from];
  }
  return count;
}
function directInversions(list) {
  let count = 0;
  for (let i = 0; i < list.length; i++) {
    const p = list[i];
    for (let j = i + 1; j < list.length; j++) { const q = list[j]; if ((p.a - q.a) * (p.b - q.b) < 0) count++; }
  }
  return count;
}
