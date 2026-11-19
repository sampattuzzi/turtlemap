import { FILES, isTestPath, net } from '../core/data.js';
import { el } from '../core/dom.js';
import { BOX_KINDS, LINE_KINDS, PRESETS, changeFilter, choosePreset, currentFilter, customChanges, filterName, onlyLine, presetKey, toggleKind } from '../core/filters.js';
import { saveSettings, settings } from '../core/settings.js';
import { lineSample, popoverButton } from './toolbar.js';
export function filterButton(onChange) {
  let menu = null;
  const changed = () => { onChange(); if (menu && menu.isConnected) fillFilterMenu(menu, changed); };
  const button = popoverButton('', 'filter-menu', (pop) => { menu = pop; fillFilterMenu(pop, changed); });
  button.title = 'Choose which kinds of box and line the map shows';
  labelFilterButton(button);
  return button;
}
export function labelFilterButton(button) {
  const key = presetKey();
  button.replaceChildren(...['⚲ Filter', key === 'all' ? null : el('span', { class: 'filter-name' }, ` · ${filterName()}`), ' ▾'].filter(Boolean));
  button.classList.toggle('filtering', key !== 'all');
}
export function filterChip(onChange) {
  const f = currentFilter();
  const key = presetKey(f);
  if (key === 'all') return null;
  const base = PRESETS.find((p) => p.key === f.base) || PRESETS[0];
  const act = (fn) => () => { fn(); onChange(); };
  return el('div', { class: 'show-chip filter-chip' },
    el('span', { class: 'udim' }, '⚲'), el('strong', {}, filterName(f)),
    el('span', { class: 'udim' }, key === 'custom' ? `· ${customChanges(f)}` : `· ${f.lines.length} of ${LINE_KINDS.length} connections`),
    key === 'custom' && base.key !== 'all' ? el('button', { class: 'btn small', title: `Back to ${base.label}`, onclick: act(() => choosePreset(base.key)) }, '↺') : null,
    el('button', { class: 'btn small', title: 'Show everything again', onclick: act(() => choosePreset('all')) }, '✕'));
}
export function lineFilter(onChange) {
  return { shown: (key) => currentFilter().lines.includes(key), toggle: (key, on) => { toggleKind('lines', key, on); onChange(); } };
}
function fillFilterMenu(pop, changed) {
  const f = currentFilter();
  const act = (fn) => () => { fn(); changed(); };
  pop.replaceChildren(
    el('div', { class: 'popover-title' }, 'Preset'), presetPills(f, act),
    el('div', { class: 'filter-cols' }, boxColumn(f, act), lineColumn(f, act)),
    menuFoot(f, act));
}
function presetPills(f, act) {
  const key = presetKey(f);
  const pill = (on, title, hint, onclick, tip) => el('button', { class: `filter-preset${on ? ' on' : ''}`, onclick, title: tip }, el('b', {}, title), el('small', {}, hint));
  return el('div', { class: 'filter-presets' },
    PRESETS.map((p) => pill(p.key === key, p.label, p.hint, act(() => choosePreset(p.key)), null)),
    key === 'custom' ? pill(true, 'Custom ↺', customChanges(f), act(() => choosePreset(f.base)), 'Go back to the preset you started from') : null);
}
function boxColumn(f, act) {
  const counts = net().counts.boxes;
  const tests = Object.keys(FILES).filter(isTestPath).length;
  return el('div', { class: 'filter-col' }, el('div', { class: 'popover-title' }, 'Boxes'),
    kindRow({ on: true, fixed: true, sample: swatch('--h-pkg'), label: 'Packages and modules', count: 'containers', title: 'Always shown, shrunk to what is inside them' }),
    BOX_KINDS.map((b) => kindRow({ on: f.boxes.includes(b.key), sample: swatch(b.colour), label: b.label, count: counts.get(b.key) || 0, onToggle: act(() => toggleKind('boxes', b.key, !f.boxes.includes(b.key))) })),
    tests ? kindRow({ on: settings.tests, sample: swatch('--h-entry'), label: 'Tests', count: tests, title: 'Test files and the libraries only they use', onToggle: act(() => { settings.tests = !settings.tests; saveSettings(); }) }) : null);
}
function lineColumn(f, act) {
  const counts = net().counts.lines;
  return el('div', { class: 'filter-col' }, el('div', { class: 'popover-title' }, 'Connections'),
    LINE_KINDS.map((l) => kindRow({ on: f.lines.includes(l.key), sample: lineSample(l.key), label: l.label, count: counts.get(l.key) || 0, onToggle: act(() => toggleKind('lines', l.key, !f.lines.includes(l.key))), onOnly: act(() => onlyLine(l.key)) })));
}
function kindRow({ on, fixed = false, sample, label, count, title = null, onToggle = null, onOnly = null }) {
  const box = el('input', { type: 'checkbox', disabled: fixed, onchange: onToggle });
  box.checked = on;
  const only = onOnly ? el('button', { class: 'filter-only', title: 'Show only this kind', onclick: (e) => { e.preventDefault(); onOnly(); } }, 'only') : null;
  return el('label', { class: `filter-row${count === 0 ? ' empty' : ''}${fixed ? ' fixed' : ''}`, title }, box, sample, el('span', { class: 'filter-label' }, label), only, el('span', { class: 'udim filter-count' }, count));
}
function swatch(colour) { return el('span', { class: 'filter-swatch', style: `background:var(${colour})` }); }
function menuFoot(f, act) {
  const mode = (fade, text) => el('button', { class: `filter-mode${f.fade === fade ? ' on' : ''}`, onclick: act(() => changeFilter({ fade })) }, text);
  const keep = el('input', { type: 'checkbox', onchange: act(() => changeFilter({ keep: !f.keep })) });
  keep.checked = f.keep;
  return el('div', { class: 'filter-foot' },
    el('span', { class: 'filter-modes', title: 'Remove the boxes you have hidden, or keep them in place, faded' }, el('span', { class: 'udim' }, 'Hidden boxes'), mode(false, 'remove'), mode(true, 'fade')),
    el('label', { class: 'filter-keep', title: 'Keep a hidden box, faded, when a line you show starts or ends there' }, keep, 'keep boxes a shown line touches'),
    el('button', { class: 'filter-reset', onclick: act(() => choosePreset('all')) }, 'Reset to Everything'));
}
