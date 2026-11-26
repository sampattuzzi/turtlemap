import { isTestPath, net } from '../core/data.js';
import { el } from '../core/dom.js';
import { refOf } from './boxes.js';
const LINKS_OPEN_AT_FIRST = 12;
const LINK_FOLDS = new Map();
let linkFoldsFor = null;
export function linkSections(ex, n, actions) {
  if (linkFoldsFor !== n.id) { LINK_FOLDS.clear(); linkFoldsFor = n.id; }
  const { usedBy, uses } = linksAcross(n);
  linkSection(ex, 'Used by', usedBy, actions);
  linkSection(ex, 'Uses', uses, actions);
}
function linksAcross(n) {
  const N = net();
  const inside = (id) => N.chain(id).includes(n);
  const usedBy = new Map(), uses = new Map();
  for (const e of N.edges) {
    const from = inside(e.from), to = inside(e.to);
    if (from && !to) addLink(uses, e.to, e.kinds);
    else if (to && !from) addLink(usedBy, e.from, e.kinds);
  }
  return { usedBy, uses };
}
function addLink(links, id, kinds) {
  if (!links.has(id)) links.set(id, new Set());
  kinds.forEach((k) => links.get(id).add(k));
}
function linkSection(ex, title, links, actions) {
  ex.append(el('div', { class: 'kind' }, title, links.size ? el('span', { class: 'link-count' }, ` ${links.size}`) : null));
  if (!links.size) { ex.append(el('p', { class: 'udim' }, 'Nothing outside it.')); return; }
  const shelves = linkShelves(links);
  const box = el('div', { class: 'links link-list' });
  const fold = { open: openLinkFiles(title, shelves), toggle: (id) => { if (!fold.open.delete(id)) fold.open.add(id); draw(); } };
  const draw = () => box.replaceChildren(...shelves.flatMap((shelf) => shelfEls(shelf, fold, actions)));
  draw();
  ex.append(box);
}
function linkShelves(links) {
  const N = net();
  const shelves = new Map();
  for (const [id, kinds] of links) {
    const home = homeOf(N.chain(id));
    const where = shelfOf(home);
    if (!shelves.has(where.key)) shelves.set(where.key, { ...where, files: new Map() });
    const files = shelves.get(where.key).files;
    if (!files.has(home.id)) files.set(home.id, { home, ends: [] });
    files.get(home.id).ends.push({ node: N.nodes.get(id), kinds, label: endLabel(N.chain(id), home) });
  }
  return [...shelves.values()].sort((a, b) => a.rank - b.rank || a.label.localeCompare(b.label)).map((shelf) => ({
    ...shelf,
    files: [...shelf.files.values()].sort((a, b) => a.home.name.localeCompare(b.home.name)).map((file) => ({ ...file, ends: file.ends.sort((a, b) => a.label.localeCompare(b.label)) })),
  }));
}
function homeOf(chain) {
  return chain.find((x) => x.kind === 'module' || x.kind === 'libmodule') || chain.find((x) => x.kind === 'library') || chain[chain.length - 1];
}
function shelfOf(home) {
  if (home.kind === 'libmodule' || home.kind === 'library') {
    const library = home.kind === 'library' ? home : home.parent;
    return { key: library.id, label: library.name, rank: 2 };
  }
  const path = home.kind === 'module' ? home.path : home.id.slice(home.id.indexOf(':') + 1);
  const folder = path.includes('/') ? path.slice(0, path.lastIndexOf('/') + 1) : '';
  return { key: `dir:${folder}`, label: folder || `${net().root.name}/`, rank: isTestPath(path) ? 1 : 0 };
}
function endLabel(chain, home) {
  const below = chain.slice(chain.indexOf(home) + 1);
  if (!below.length) return home.kind === 'library' ? 'the library itself' : 'the module itself';
  return below.map(stepName).join('.');
}
function openLinkFiles(title, shelves) {
  if (!LINK_FOLDS.has(title)) LINK_FOLDS.set(title, firstOpenFiles(shelves));
  return LINK_FOLDS.get(title);
}
function firstOpenFiles(shelves) {
  const files = shelves.flatMap((shelf) => shelf.files);
  const open = new Set();
  let visible = files.length;
  for (const file of files) {
    if (visible + file.ends.length > LINKS_OPEN_AT_FIRST) break;
    open.add(file.home.id);
    visible += file.ends.length;
  }
  return open;
}
function shelfEls(shelf, fold, actions) {
  return [el('div', { class: 'link-shelf' }, breakable(shelf.label)), ...shelf.files.flatMap((file) => fileEls(file, fold, actions))];
}
function fileEls(file, fold, actions) {
  const { home, ends } = file;
  const isOpen = fold.open.has(home.id);
  const toggle = () => fold.toggle(home.id);
  const row = el('div', { class: 'link-file' },
    el('button', { class: 'link-chev', title: isOpen ? 'Collapse' : 'Expand', onclick: toggle }, isOpen ? '▾' : '▸'),
    el('button', { class: 'link-file-name', title: `Show ${home.name} on the map`, onclick: () => actions.show(home.id) }, breakable(home.name)),
    el('span', { class: 'link-count' }, ends.length));
  return isOpen ? [row, ...ends.map((end) => endEl(end, actions))] : [row];
}
function endEl(end, actions) {
  return el('div', { class: 'link-end-row' },
    el('span', { class: 'link-bullet', 'aria-hidden': 'true' }, '•'),
    el('button', { class: 'link-end', title: [...end.kinds].join(', '), onclick: () => followLink(end.node, actions) }, breakable(end.label)));
}
function breakable(text) {
  return text.split(/(?<=[/._])|(?<=[a-z0-9])(?=[A-Z])/).flatMap((part, i) => (i ? [el('wbr'), part] : [part]));
}
function stepName(step) {
  return step.kind === 'function' || step.kind === 'method' ? `${step.name}()` : step.name;
}
function followLink(node, actions) {
  if (node.sym && node.sym.kind === 'function') actions.go(refOf(node.sym));
  else actions.show(node.id);
}
