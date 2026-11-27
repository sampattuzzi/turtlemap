import { shapeSVG } from '../blueprint/nodes.js';
import { DIFF, OVERVIEW } from '../core/data.js';
import { LINE_KINDS } from '../core/filters.js';
import { api, el } from '../core/dom.js';
import { SETTINGS_KEY, applySettings, saveSettings, settings } from '../core/settings.js';
import { openPalette } from './palette.js';
import { diffBadge } from '../map/boxes.js';
export function lineSample(kind) {
  const dashed = LINE_KINDS.find((l) => l.key === kind).dashed;
  return el('span', { class: 'line-sample', html: `<svg viewBox="0 0 46 12"><path d="M2,6 H38" style="stroke:var(--rel-${kind === 'realizes' ? 'inherits' : kind})" stroke-width="2" ${dashed ? 'stroke-dasharray="6 4"' : ''}/>${kind === 'inherits' || kind === 'realizes' || kind === 'bound' ? `<path d="M36,1 L45,6 L36,11 z" style="fill:var(--canvas);stroke:var(--rel-${kind === 'bound' ? 'bound' : 'inherits'})" stroke-width="1.4"/>` : `<path d="M37,1 L45,6 L37,11" style="fill:none;stroke:var(--rel-${kind})" stroke-width="1.6"/>`}${kind === 'has' ? '<path d="M1,6 L6,2.5 L11,6 L6,9.5 z" style="fill:var(--rel-has)"/>' : ''}</svg>` });
}
function legendInto(container, lineFilter) {
  container.append(el('div', { class: 'kind', style: 'font-size:0.72em;letter-spacing:0.08em;text-transform:uppercase;color:var(--fg-dim)' }, 'Map lines', el('span', { style: 'text-transform:none;letter-spacing:0' }, ' · click one to show or hide it')));
  for (const { key, legend } of LINE_KINDS) {
    const box = el('input', { type: 'checkbox', onchange: (e) => lineFilter.toggle(key, e.target.checked) });
    box.checked = lineFilter.shown(key);
    container.append(el('label', { class: 'legend-row legend-line legend-toggle', title: 'Show or hide these lines on the map' }, box, lineSample(key), el('span', {}, legend)));
  }
  if (DIFF) {
    container.append(el('div', { class: 'kind', style: 'font-size:0.72em;letter-spacing:0.08em;text-transform:uppercase;color:var(--fg-dim)' }, `Changes in ${DIFF.spec}`));
    for (const [state, text] of [['added', 'added'], ['removed', 'removed'], ['modified', 'changed, or something inside it changed']]) container.append(el('div', { class: 'legend-row' }, diffBadge(state), el('span', {}, text)));
  }
  container.append(el('div', { class: 'kind', style: 'font-size:0.72em;letter-spacing:0.08em;text-transform:uppercase;color:var(--fg-dim);margin-top:6px' }, 'Function view'));
  const rows = [['bool', 'bool'], ['int', 'int'], ['float', 'float'], ['str', 'str, Path'], ['enum', 'Enum'], ['struct', 'dataclass / model'], ['object', 'object'], ['map', 'dict, Mapping'], ['list', 'list, tuple'], ['callable', 'callable'], ['time', 'datetime'], ['none', 'None / unknown']];
  container.append(el('div', { class: 'legend-row' }, el('span', { class: 'shape', html: shapeSVG(null) }), el('span', {}, 'execution order ', el('small', {}, 'white wire'))));
  for (const [cat, code] of rows) container.append(el('div', { class: 'legend-row' }, el('span', { class: 'shape', html: shapeSVG({ cat }) }), el('small', {}, code)));
  container.append(el('div', { class: 'legend-row' }, el('span', { class: 'shape', html: shapeSVG({ cat: 'int' }, true, true) }), el('span', {}, 'the variable itself ', el('small', {}, 'dotted wire, to a variable that is set in one place and read or changed in another'))));
}
export function popoverButton(label, cls, fill) {
  const btn = el('button', { class: 'btn' }, label);
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    const existing = document.querySelector(`.popover.${cls}`); document.querySelectorAll('.popover').forEach((p) => p.remove()); if (existing) return;
    const r = btn.getBoundingClientRect();
    const pop = el('div', { class: `popover ${cls}`, style: `top:${r.bottom + 6}px; right:max(12px, ${window.innerWidth - r.right}px)`, onclick: (ev) => ev.stopPropagation() });
    fill(pop); document.body.append(pop);
    if (pop.getBoundingClientRect().left < 12) { pop.style.right = 'auto'; pop.style.left = `${Math.max(12, Math.min(r.left, window.innerWidth - pop.offsetWidth - 12))}px`; }
  });
  return btn;
}
const COG_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill-rule="evenodd" d="M19.62,10.33 L22.42,10.68 L22.42,13.32 L19.62,13.67 L18.57,16.21 L20.30,18.44 L18.44,20.30 L16.21,18.57 L13.67,19.62 L13.32,22.42 L10.68,22.42 L10.33,19.62 L7.79,18.57 L5.56,20.30 L3.70,18.44 L5.43,16.21 L4.38,13.67 L1.58,13.32 L1.58,10.68 L4.38,10.33 L5.43,7.79 L3.70,5.56 L5.56,3.70 L7.79,5.43 L10.33,4.38 L10.68,1.58 L13.32,1.58 L13.67,4.38 L16.21,5.43 L18.44,3.70 L20.30,5.56 L18.57,7.79 Z M15,12 A3,3 0 1,0 9,12 A3,3 0 1,0 15,12 Z"/></svg>';
function settingsButton(onChange) {
  const btn = popoverButton(el('span', { class: 'cog', html: COG_ICON }), 'layout-menu', (pop) => {
    const done = () => { saveSettings(); applySettings(); onChange(); };
    const sel = (id, value, opts, fn2) => el('select', { id, onchange: (ev) => fn2(ev.target.value) }, opts.map(([v, l]) => { const o = el('option', { value: v }, l); if (String(v) === String(value)) o.selected = true; return o; }));
    const chk = (id, value, fn2) => { const c = el('input', { type: 'checkbox', id, onchange: (ev) => fn2(ev.target.checked) }); c.checked = value; return c; };
    pop.append(el('div', { class: 'popover-title' }, 'Reading'), el('div', { class: 'popover-rows' },
      el('label', { for: 'set-font' }, 'Label font', sel('set-font', settings.pinFont, [['mono', 'Monospace'], ['lexend', 'Lexend'], ['atkinson', 'Atkinson Hyperlegible'], ['comic', 'Comic Neue']], (v) => { settings.pinFont = v; done(); })),
      el('label', { for: 'set-size' }, 'Node text', sel('set-size', settings.size, [[11, 'Small'], [12.5, 'Normal'], [14, 'Large'], [16, 'Extra large']], (v) => { settings.size = +v; done(); })),
      el('label', { for: 'set-theme' }, 'Background', sel('set-theme', settings.theme, [['dark', 'Dark'], ['light', 'Soft paper'], ['system', 'Match device']], (v) => { settings.theme = v; done(); })),
      el('label', { for: 'set-plain' }, 'Spaced-out names', chk('set-plain', settings.plain, (v) => { settings.plain = v; done(); })),
      el('label', { for: 'set-types' }, 'Type names on pins', chk('set-types', settings.types, (v) => { settings.types = v; done(); }))));
  });
  btn.title = 'Settings';
  btn.setAttribute('aria-label', 'Settings');
  return btn;
}
document.addEventListener('click', () => document.querySelectorAll('.popover').forEach((p) => p.remove()));
function compareButton(onCompared) {
  const button = popoverButton(DIFF ? `± ${shortSpec(DIFF.spec)}` : '± Compare', 'compare', (pop) => {
    const input = el('input', { id: 'diff-spec', class: 'path-input', placeholder: 'develop..my-branch', value: DIFF ? DIFF.spec : '', list: 'diff-branches', autocomplete: 'off', spellcheck: 'false' });
    const branches = el('datalist', { id: 'diff-branches' });
    const message = el('p', { class: 'error-text', hidden: true });
    const run = async (spec) => {
      message.hidden = true;
      try { await api(`/api/diff?spec=${encodeURIComponent(spec)}`); } catch (error) { message.textContent = error.message; message.hidden = false; return; }
      pop.remove();
      onCompared();
    };
    pop.append(el('form', { class: 'compare-form', onsubmit: (e) => { e.preventDefault(); if (input.value.trim()) run(input.value.trim()); } },
      el('label', { for: 'diff-spec' }, 'Show the changes in a git range'), input, branches,
      el('p', { class: 'muted small' }, 'A..B compares the tips of A and B. A...B compares B with the point where it branched off A, like a pull request. A on its own compares A with your working copy.'),
      message,
      el('div', { class: 'actions' }, el('button', { class: 'btn primary', type: 'submit' }, 'Compare'), DIFF ? el('button', { class: 'btn', type: 'button', onclick: () => run('') }, 'Stop comparing') : null)));
    setTimeout(() => input.focus(), 0);
    let names = [];
    const refill = () => {
      const typed = input.value.match(/^(.*?)(\.\.\.?)/);
      branches.innerHTML = '';
      for (const name of names.slice(0, 200)) branches.append(el('option', { value: typed ? `${typed[1]}${typed[2]}${name}` : name }));
    };
    input.addEventListener('input', refill);
    api('/api/branches').then((data) => { names = data.branches; refill(); }, () => {});
  });
  button.title = DIFF ? `Comparing ${DIFF.spec}` : 'Compare with a git branch';
  if (DIFF) button.classList.add('comparing');
  return button;
}
function shortSpec(spec) {
  const short = spec.replace(/\b[0-9a-f]{12,40}\b/g, (sha) => sha.slice(0, 8));
  return short.length > 32 ? `${short.slice(0, 31)}…` : short;
}
export function shell(root, { extraButtons, onPick, onSettings, onCompared, lineFilter }) {
  const crumbs = el('div', { class: 'crumbs' });
  const left = el('div', { class: 'panel left' });
  const right = el('div', { class: 'panel right' });
  root.append(el('div', { class: 'topbar' },
    el('div', { class: 'brand' }, el('img', { class: 'brand-mark', src: 'logo.svg', alt: 'Turtlemap' }), el('small', {}, OVERVIEW ? OVERVIEW.name : '')),
    el('button', { class: 'btn phone-only', onclick: () => { left.hidden = !left.hidden; } }, 'Files'),
    ...extraButtons,
    el('button', { class: 'btn', title: 'Find a file or symbol (/)', 'data-find': true, onclick: () => openPalette(onPick) }, '⌕ Find'),
    compareButton(onCompared),
    crumbs, popoverButton('● Key', 'legend', (pop) => legendInto(pop, lineFilter)), settingsButton(onSettings)));
  const row = el('div', { class: 'body-row' });
  const vpHost = el('div', { class: 'viewport' });
  const bar = el('div', { class: 'resize-bar', title: 'Drag to resize the code panel' });
  right.append(bar);
  const tab = el('button', { class: 'code-tab', title: 'Click to show or hide the code, drag to resize it' }, el('span', { class: 'chev' }, '⌄'), 'Code');
  const mainCol = el('div', { class: 'main-col' }, vpHost, el('div', { class: 'code-dock' }, tab), right);
  const sideBar = el('div', { class: 'side-bar', title: 'Drag to resize the side panel' });
  const sideTab = el('button', { class: 'side-tab-handle', title: 'Click to show or hide the side panel, drag to resize it' }, el('span', { class: 'chev' }, '⌄'), el('span', { class: 'label' }, 'Files'));
  row.append(left, el('div', { class: 'side-dock' }, sideBar, sideTab), mainCol);
  root.append(row);
  const phone = window.innerWidth <= 760;
  try {
    const savedBottom = localStorage.getItem(`${SETTINGS_KEY}-bottom`); if (savedBottom) right.style.setProperty('--bottom-h', savedBottom);
    right.hidden = localStorage.getItem(`${SETTINGS_KEY}-code-hidden`) === '1';
    const savedSide = localStorage.getItem(`${SETTINGS_KEY}-side`); if (savedSide) left.style.setProperty('--side-w', savedSide);
    left.hidden = localStorage.getItem(`${SETTINGS_KEY}-side-hidden`) === '1';
  } catch (e) {}
  if (phone) left.hidden = true;
  const remember = () => { try { localStorage.setItem(`${SETTINGS_KEY}-bottom`, right.style.getPropertyValue('--bottom-h')); localStorage.setItem(`${SETTINGS_KEY}-code-hidden`, right.hidden ? '1' : '0'); } catch (err) {} };
  const rememberSide = () => { if (phone) return; try { localStorage.setItem(`${SETTINGS_KEY}-side`, left.style.getPropertyValue('--side-w')); localStorage.setItem(`${SETTINGS_KEY}-side-hidden`, left.hidden ? '1' : '0'); } catch (err) {} };
  const resizeBottom = (y) => {
    const colRect = mainCol.getBoundingClientRect();
    right.hidden = false;
    right.style.setProperty('--bottom-h', `${Math.round(Math.min(colRect.height * 0.75, Math.max(90, colRect.bottom - y)))}px`);
  };
  const resizeSide = (x) => {
    const rowRect = row.getBoundingClientRect();
    left.hidden = false;
    left.style.setProperty('--side-w', `${Math.round(Math.min(rowRect.width * 0.6, Math.max(160, x - rowRect.left)))}px`);
  };
  const toggleCode = () => { right.hidden = !right.hidden; };
  const toggleSide = () => { left.hidden = !left.hidden; };
  dragToResize(bar, 'y', resizeBottom, null, remember);
  dragToResize(tab, 'y', resizeBottom, toggleCode, remember);
  dragToResize(sideBar, 'x', resizeSide, null, rememberSide);
  dragToResize(sideTab, 'x', resizeSide, toggleSide, rememberSide);
  return { crumbs, left, right, vpHost };
}
function dragToResize(handle, axis, resize, toggle, remember) {
  const along = (e) => (axis === 'x' ? e.clientX : e.clientY);
  handle.addEventListener('pointerdown', (e) => {
    e.preventDefault();
    handle.setPointerCapture(e.pointerId);
    let dragged = false;
    const move = (ev) => {
      if (!dragged && Math.abs(along(ev) - along(e)) < 4) return;
      dragged = true;
      resize(along(ev));
    };
    const up = () => { handle.removeEventListener('pointermove', move); handle.removeEventListener('pointerup', up); if (!dragged && toggle) toggle(); remember(); };
    handle.addEventListener('pointermove', move);
    handle.addEventListener('pointerup', up);
  });
  if (toggle) handle.addEventListener('click', (e) => { if (e.detail === 0) { toggle(); remember(); } });
}
