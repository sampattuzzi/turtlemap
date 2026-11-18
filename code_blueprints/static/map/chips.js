import { FILES, isTestPath, net } from '../core/data.js';
import { el } from '../core/dom.js';
import { settings } from '../core/settings.js';
import { dataScopes } from './datamodel.js';
export function showToggles(onChange) {
  const tests = Object.keys(FILES).filter(isTestPath).length;
  const constants = Object.values(FILES).reduce((n, f) => n + (f.constants || []).length, 0);
  const toggle = (key, label, count, title) => {
    if (!count) return null;
    const box = el('input', { type: 'checkbox', onchange: (e) => onChange(key, e.target.checked) });
    box.checked = settings[key];
    return el('label', { class: 'show-toggle', title }, box, label, el('span', { class: 'udim' }, count));
  };
  const toggles = [
    toggle('tests', 'Tests', tests, 'Show test files and the libraries only they use'),
    toggle('constants', 'Constants', constants, 'Show module constants and what reads them'),
  ].filter(Boolean);
  return toggles.length ? el('div', { class: 'show-chip' }, el('span', { class: 'udim' }, 'Show'), toggles) : null;
}
export function dataScopeChip(scope, onPick) {
  const pick = el('select', { id: 'data-scope', onchange: (ev) => onPick(ev.target.value) }, dataScopes(net()).map((s) => {
    const option = el('option', { value: s.id }, `${'\u00a0\u00a0'.repeat(Math.max(0, s.depth - 1))}${s.label} · ${s.count}`);
    if (s.id === scope) option.selected = true;
    return option;
  }));
  return el('div', { class: 'focus-chip data-scope' }, el('label', { for: 'data-scope' }, 'Data classes in'), pick, el('span', { class: 'udim' }, 'Faded boxes live elsewhere and link in.'));
}
