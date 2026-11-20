import { DIFF, OVERVIEW, isTestPath, net } from '../core/data.js';
import { el, speak } from '../core/dom.js';
import { codePainter } from '../core/highlight.js';
import { ensureOutline, outlineFor } from '../core/project.js';
import { fileDiff } from '../core/review.js';
import { DIFF_SIGN, DIFF_WORD, diffBadge, moduleNodeOf, netLabel, plural, refOf, summaryOf } from './boxes.js';
function moduleOf(id) { const c = net().chain(id); const m = c.find((n) => n.kind === 'module' || n.kind === 'libmodule'); return m ? m.name : null; }
const PANEL_MODULES = 30;
const LINKS_OPEN_AT_FIRST = 12;
const LINK_FOLDS = new Map();
let linkFoldsFor = null;
let refreshTimer = null;
function refreshSoon(refresh) {
  if (!refresh || refreshTimer) return;
  refreshTimer = setTimeout(() => { refreshTimer = null; refresh(); }, 60);
}
function foldedRows(effective, refresh) {
  const N = net();
  const outline = new OutlineRows(N, effective);
  const open = [...N.nodes.values()].filter((n) => n.kind === 'module' && effective.has(n.id));
  for (const m of open.slice(0, PANEL_MODULES)) {
    outline.rows.push({ banner: true, text: m.path, id: m.id, diff: fileDiff(m.path) });
    const ol = outlineFor(m.path);
    if (!ol) { outline.rows.push({ text: '    reading…', dim: true }); ensureOutline(m.path).then(() => refreshSoon(refresh), () => {}); continue; }
    for (const it of ol) outline.add(it, m.path, null);
  }
  if (open.length > PANEL_MODULES) outline.rows.push({ text: `    … and ${open.length - PANEL_MODULES} more open modules. Fold some boxes on the map to read their code here.`, dim: true });
  return outline.rows;
}
const ITEM_FOLDS = new Map([
  ['imports', (it) => (it.count > 1 ? `+${it.count - 1} more imports` : null)],
  ['doc', (it) => (it.multi ? 'docstring' : null)],
  ['stmt', (it) => (it.multi ? '⋯' : null)],
]);
class OutlineRows {
  constructor(N, effective) {
    this.N = N;
    this.effective = effective;
    this.rows = [];
  }
  add(it, path, cls) {
    const qual = cls ? `${cls}.${it.name}` : it.name;
    const diff = it.diff || null;
    for (const [no, text] of it.decorators || []) this.rows.push({ no, text, diff, path });
    const fold = ITEM_FOLDS.get(it.kind);
    if (fold) this.rows.push({ no: it.no, text: it.text, fold: fold(it), diff, path });
    else if (it.kind === 'def') this.def(it, path, cls ? `m:${path}:${qual}` : `fn:${path}:${qual}`, diff);
    else if (it.kind === 'class') this.cls(it, path, qual, diff);
  }
  def(it, path, id, diff) {
    this.rows.push({ no: it.no, text: it.text, fold: 'body', id: this.known(id), def: true, diff, path });
  }
  cls(it, path, qual, diff) {
    const id = `cls:${path}:${qual}`;
    const open = this.effective.has(id);
    this.rows.push({ no: it.no, text: it.text, fold: open ? null : 'body', id: this.known(id), cls: true, open, diff, path });
    if (open) for (const b of it.body) this.add(b, path, qual);
  }
  known(id) {
    return this.N.nodes.has(id) ? id : null;
  }
}
export function netPanel(container, selId, ctx, effective) {
  container.querySelectorAll(':scope > :not(.resize-bar)').forEach((c) => c.remove());
  const ex = el('div', { class: 'explain' });
  const panel = el('div', { class: 'code-panel' }, ex);
  container.append(panel);
  const n = selId ? net().nodes.get(selId) : null;
  if (n) explainMapNode(ex, n, selId, ctx);
  else if (DIFF) explainComparison(ex, ctx);
  else explainFoldedCode(ex);
  const cv = el('div', { class: 'code-view folded' });
  const paint = codePainter();
  for (const r of foldedRows(effective || new Set(), ctx.refresh)) cv.append(foldedRowEl(r, selId, ctx, effective, paint));
  panel.append(cv);
  const hl = cv.querySelector('.hl'); if (hl) requestAnimationFrame(() => hl.scrollIntoView({ block: 'nearest' }));
}
function explainMapNode(ex, n, selId, ctx) {
  const what = n.children.length ? summaryOf(n) : n.sym && n.sym.params ? `${n.sym.params.filter((p) => p[0] !== 'self').length} parameters` : n.type ? n.type.label : '';
  const text = `${netLabel(selId)}. ${n.kind}${moduleOf(selId) ? ` in ${moduleOf(selId)}` : ''}. ${what}.`;
  ex.append(el('div', { class: 'kind' }, n.kind), el('h2', {}, netLabel(selId)), el('p', {}, what));
  ex.append(el('div', { class: 'actions' }, el('button', { class: 'btn small', onclick: () => speak(text) }, '🔊 Read aloud')));
  if (linkFoldsFor !== selId) { LINK_FOLDS.clear(); linkFoldsFor = selId; }
  const { usedBy, uses } = linksAcross(n);
  linkSection(ex, 'Used by', usedBy, ctx);
  linkSection(ex, 'Uses', uses, ctx);
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
function linkSection(ex, title, links, ctx) {
  const tree = linkTree(links);
  ex.append(el('div', { class: 'kind' }, title, links.size ? el('span', { class: 'link-count' }, ` ${links.size}`) : null));
  if (!links.size) { ex.append(el('p', { class: 'udim' }, 'Nothing outside it.')); return; }
  const box = el('div', { class: 'links link-tree' });
  const fold = { open: openLinkGroups(title, tree), toggle: (id) => { if (!fold.open.delete(id)) fold.open.add(id); draw(); } };
  const draw = () => box.replaceChildren(...linkRowEls(tree, 0, fold, ctx));
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
function linkRowEls(tree, depth, fold, ctx) {
  return linkRows(tree).flatMap((row) => {
    const isOpen = fold.open.has(row.tree.node.id);
    const rowEl = linkRowEl(row, depth, isOpen, fold, ctx);
    return isOpen ? [rowEl, ...linkRowEls(row.tree, depth + 1, fold, ctx)] : [rowEl];
  });
}
function linkRowEl(row, depth, isOpen, fold, ctx) {
  const { steps, tree } = row;
  const group = tree.children.size > 0;
  const toggle = () => fold.toggle(tree.node.id);
  const label = steps.flatMap((step, i) => [i ? el('span', { class: 'link-sep' }, ' › ') : null, el('span', {}, stepName(step))]);
  const name = tree.kinds
    ? el('button', { class: 'link-end', title: [...tree.kinds].join(', '), onclick: () => followLink(tree.node, ctx) }, label)
    : el('button', { class: 'link-group', onclick: toggle }, label);
  return el('div', { class: 'link-row', style: `padding-left:${depth * 14}px` },
    group ? el('button', { class: 'link-chev', title: isOpen ? 'Collapse' : 'Expand', onclick: toggle }, isOpen ? '▾' : '▸') : el('span', { class: 'link-chev' }),
    name,
    group ? el('span', { class: 'link-count' }, tree.count) : null);
}
function stepName(step) {
  return step.kind === 'function' || step.kind === 'method' ? `${step.name}()` : step.name;
}
function followLink(node, ctx) {
  if (node.sym && node.sym.kind === 'function') ctx.go(refOf(node.sym));
  else ctx.show(node.id);
}
function explainComparison(ex, ctx) {
  const c = DIFF.counts;
  const files = Object.entries(DIFF.files);
  ex.append(el('div', { class: 'kind' }, 'Comparing'), el('h2', {}, DIFF.spec),
    el('p', {}, `${DIFF.headLabel} against ${DIFF.baseLabel}: ${plural(files.length, 'source file')} changed (${c.added} added, ${c.removed} removed, ${c.modified} changed).`));
  const list = el('div', { class: 'diff-files' }, files.slice(0, 60).map(([path, info]) => el('button', { class: `diff-file diff-${info.status}`, title: info.oldPath ? `renamed from ${info.oldPath}` : DIFF_WORD[info.status], onclick: () => ctx.go({ path, sym: null }) }, diffBadge(info.status), el('span', {}, path))));
  if (files.length > 60) list.append(el('span', { class: 'udim' }, `and ${files.length - 60} more`));
  ex.append(list);
}
function explainFoldedCode(ex) {
  ex.append(el('div', { class: 'kind' }, 'Code'), el('h2', {}, 'Folded to match the map'));
  ex.append(el('p', {}, 'This is the real code of every open module, folded to the level you have expanded. Click a class line to expand or fold it here and in the map. Click a def line to open its dataflow view.'));
  if (OVERVIEW) ex.append(el('p', { style: 'color:var(--fg-dim);font-size:0.9em' }, `${OVERVIEW.root} · ${plural(OVERVIEW.modules.length, 'module')}${OVERVIEW.failures && OVERVIEW.failures.length ? ` · ${OVERVIEW.failures.length} could not be read` : ''}`));
}
function foldedRowEl(r, selId, ctx, effective, paint) {
  const located = r.path && r.no && r.diff !== 'removed';
  const row = el('div', { class: foldedRowClass(r, selId), 'data-id': r.id || null, 'data-path': located ? r.path : null, 'data-line': located ? r.no : null, title: r.diff ? DIFF_WORD[r.diff] : null },
    el('span', { class: 'no' }, foldedRowNumber(r, effective)),
    DIFF ? el('span', { class: 'sign' }, r.diff ? DIFF_SIGN[r.diff] : '') : null,
    el('span', { class: 'tx' }, foldedRowText(r, paint)),
    r.fold ? foldChip(r.fold) : null);
  if (r.id) followFoldedRow(row, r, ctx);
  return row;
}
function foldedRowClass(r, selId) {
  return `ln ${r.banner ? 'banner' : ''} ${r.id ? 'clickable' : ''} ${r.dim ? 'dimrow' : ''} ${r.id && r.id === selId ? 'hl' : ''} ${r.diff ? `diff-${r.diff}` : ''}`;
}
function foldedRowNumber(r, effective) {
  if (r.banner) return effective.has(r.id) ? '▾' : '▸';
  return r.no || '';
}
function foldedRowText(r, paint) {
  if (r.banner || r.dim || r.diff === 'removed' || !r.text) return r.text || ' ';
  return paint(r.text, r.no, r.path);
}
function foldChip(fold) {
  const body = fold === 'body';
  return el('span', { class: 'fold-chip', title: body ? 'Folded' : fold }, body ? '⋯' : fold);
}
function followFoldedRow(row, r, ctx) {
  row.addEventListener('click', () => {
    const node = net().nodes.get(r.id);
    if (r.def && node && node.sym) ctx.go(refOf(node.sym));
    else { ctx.select(r.id); if (node && node.children.length) ctx.toggle(r.id); }
  });
  row.addEventListener('mouseenter', () => { const b = document.querySelector(`.viewport .nb[data-id="${CSS.escape(r.id)}"]`); if (b) b.classList.add('code-hover'); });
  row.addEventListener('mouseleave', () => document.querySelectorAll('.viewport .code-hover').forEach((b) => b.classList.remove('code-hover')));
}
