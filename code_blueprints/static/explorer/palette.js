import { FILES } from '../core/data.js';
import { baseName, el } from '../core/dom.js';
import { shortFile } from '../core/project.js';
import { refOf } from '../map/boxes.js';
export function openPalette(onPick) {
  document.querySelectorAll('.palette').forEach((p) => p.remove());
  const items = [];
  for (const f of Object.values(FILES)) {
    items.push({ k: 'file', name: baseName(f.path), where: f.path, ref: { path: f.path, sym: null } });
    for (const s of Object.values(f.index)) items.push({ k: s.kind === 'function' ? (s.owner ? 'method' : 'function') : 'type', name: s.qual, where: shortFile(f.path), ref: refOf(s) });
  }
  const input = el('input', { id: 'palette-input', placeholder: 'file, class or function…', autocomplete: 'off' });
  const results = el('div', { class: 'results' });
  const pal = el('div', { class: 'palette', onclick: (e) => e.stopPropagation() }, input, results);
  let on = 0, shown = [];
  const render = () => {
    const q = input.value.toLowerCase().replace(/[\s_]+/g, '');
    shown = items.filter((i) => (i.name + i.where).toLowerCase().replace(/[\s_]+/g, '').includes(q)).slice(0, 40);
    on = Math.max(0, Math.min(on, shown.length - 1));
    results.innerHTML = '';
    shown.forEach((i, ix) => results.append(el('button', { class: `res ${ix === on ? 'on' : ''}`, onclick: () => { pal.remove(); onPick(i.ref); } }, el('span', { class: 'k' }, i.k), el('span', {}, i.name), el('span', { class: 'where' }, i.where))));
  };
  input.addEventListener('input', () => { on = 0; render(); });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') { on = Math.min(shown.length - 1, on + 1); render(); e.preventDefault(); }
    if (e.key === 'ArrowUp') { on = Math.max(0, on - 1); render(); e.preventDefault(); }
    if (e.key === 'Enter' && shown[on]) { pal.remove(); onPick(shown[on].ref); }
    if (e.key === 'Escape') pal.remove();
  });
  setTimeout(() => document.addEventListener('click', () => pal.remove(), { once: true }), 0);
  render(); document.body.append(pal); input.focus();
}
