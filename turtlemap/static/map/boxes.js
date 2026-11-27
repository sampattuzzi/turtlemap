import { net } from '../core/data.js';
import { el } from '../core/dom.js';
export const DIFF_SIGN = { added: '+', removed: '−', modified: '~' };
export const DIFF_WORD = { added: 'added', removed: 'removed', modified: 'changed' };
export function combinedDiff(states) {
  const changed = states.filter(Boolean);
  if (!changed.length) return null;
  return changed.length === states.length && changed.every((x) => x === changed[0]) ? changed[0] : 'modified';
}
export function diffBadge(state) { return state ? el('span', { class: `diff-badge diff-${state}`, title: DIFF_WORD[state] }, DIFF_SIGN[state]) : null; }
export const refOf = (sym) => ({ path: sym.file, sym: sym.qual });
export const shortType = (label) => (label.length > 60 ? `${label.slice(0, 59)}…` : label);
export const plural = (n, word) => `${n} ${word}${n === 1 ? '' : (word.endsWith('s') ? 'es' : 's')}`;
export function netLabel(id) {
  const n = net().nodes.get(id);
  if (!n) return id;
  if (n.kind === 'method') return `${n.parent.name}.${n.name}()`;
  if (n.kind === 'function') return `${n.name}()`;
  if (n.kind === 'field' || n.kind === 'member') return `${n.parent.name}.${n.name}`;
  if (n.kind === 'name') return `${n.name} (${n.parent.kind === 'libmodule' ? n.parent.name : n.parent.name})`;
  if (n.kind === 'package') return `${n.name}/`;
  if (n.kind === 'typevar') return `${n.name} (type parameter)`;
  return n.name;
}
export function summaryOf(n) {
  const counts = new Map();
  const word = { package: 'package', module: 'module', class: 'class', function: 'function', method: 'method', field: 'field', member: 'choice', constant: 'constant', typevar: 'type parameter', name: 'name', libmodule: 'module' };
  for (const k of n.children) counts.set(word[k.kind], (counts.get(word[k.kind]) || 0) + 1);
  return [...counts].map(([w, c]) => plural(c, w)).join(' · ');
}
export function moduleNodeOf(id) { return net().chain(id).find((n) => n.kind === 'module') || null; }
export function moduleFileName(module) { return module.name === '__init__.py' && module.parent.kind === 'package' ? `${module.parent.name}/__init__.py` : module.name; }
