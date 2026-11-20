import { isTestPath, net } from '../core/data.js';
import { el } from '../core/dom.js';
import { moduleNodeOf, refOf } from './boxes.js';
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
  const tree = linkTree(links);
  ex.append(el('div', { class: 'kind' }, title, links.size ? el('span', { class: 'link-count' }, ` ${links.size}`) : null));
  if (!links.size) { ex.append(el('p', { class: 'udim' }, 'Nothing outside it.')); return; }
  const box = el('div', { class: 'links link-tree' });
  const fold = { open: openLinkGroups(title, tree), toggle: (id) => { if (!fold.open.delete(id)) fold.open.add(id); draw(); } };
  const draw = () => box.replaceChildren(...linkRowEls(tree, 0, fold, actions));
  draw();
  ex.append(box);
}
function linkTree(links) {
  const N = net();
  const top = linkBranch(N.root);
  for (const [id, kinds] of links) {
    let at = top;
    at.count += 1;
    for (const step of N.chain(id).slice(1)) {
      if (!at.children.has(step.id)) at.children.set(step.id, linkBranch(step));
      at = at.children.get(step.id);
      at.count += 1;
    }
    at.kinds = kinds;
  }
  return top;
}
function linkBranch(node) {
  return { node, kinds: null, children: new Map(), count: 0 };
}
function openLinkGroups(title, tree) {
  if (!LINK_FOLDS.has(title)) LINK_FOLDS.set(title, firstOpenGroups(tree));
  return LINK_FOLDS.get(title);
}
function firstOpenGroups(tree) {
  const open = new Set();
  const queue = linkRows(tree);
  let visible = queue.length;
  while (queue.length) {
    const row = queue.shift();
    const kids = linkRows(row.tree);
    if (!kids.length) continue;
    if (visible + kids.length > LINKS_OPEN_AT_FIRST) break;
    open.add(row.tree.node.id);
    visible += kids.length;
    queue.push(...kids);
  }
  return open;
}
function linkRows(tree) {
  return [...tree.children.values()].sort(byLinkOrder).map(mergedRow);
}
function byLinkOrder(a, b) {
  return linkRank(a.node) - linkRank(b.node) || stepName(a.node).localeCompare(stepName(b.node));
}
function linkRank(node) {
  if (node.kind === 'library' || node.kind === 'libmodule' || node.kind === 'name') return 2;
  const module = moduleNodeOf(node.id);
  const path = module ? module.path : node.kind === 'package' ? node.id.slice('pkg:'.length) : '';
  return isTestPath(path) ? 1 : 0;
}
function mergedRow(tree) {
  const steps = [tree.node];
  while (!tree.kinds && tree.children.size === 1) {
    tree = tree.children.values().next().value;
    steps.push(tree.node);
  }
  return { steps, tree };
}
function linkRowEls(tree, depth, fold, actions) {
  return linkRows(tree).flatMap((row) => {
    const isOpen = fold.open.has(row.tree.node.id);
    const rowEl = linkRowEl(row, depth, isOpen, fold, actions);
    return isOpen ? [rowEl, ...linkRowEls(row.tree, depth + 1, fold, actions)] : [rowEl];
  });
}
function linkRowEl(row, depth, isOpen, fold, actions) {
  const { steps, tree } = row;
  const group = tree.children.size > 0;
  const toggle = () => fold.toggle(tree.node.id);
  const label = steps.flatMap((step, i) => [i ? el('span', { class: 'link-sep' }, ' › ') : null, el('span', {}, stepName(step))]);
  const name = tree.kinds
    ? el('button', { class: 'link-end', title: [...tree.kinds].join(', '), onclick: () => followLink(tree.node, actions) }, label)
    : el('button', { class: 'link-group', onclick: toggle }, label);
  return el('div', { class: 'link-row', style: `padding-left:${depth * 14}px` },
    group ? el('button', { class: 'link-chev', title: isOpen ? 'Collapse' : 'Expand', onclick: toggle }, isOpen ? '▾' : '▸') : el('span', { class: 'link-chev' }),
    name,
    group ? el('span', { class: 'link-count' }, tree.count) : null);
}
function stepName(step) {
  return step.kind === 'function' || step.kind === 'method' ? `${step.name}()` : step.name;
}
function followLink(node, actions) {
  if (node.sym && node.sym.kind === 'function') actions.go(refOf(node.sym));
  else actions.show(node.id);
}
