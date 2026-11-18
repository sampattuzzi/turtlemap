import { OPEN_ICON, buildFunctionScene } from './nodes.js';
import { FUNCTIONS, fnKey, lookup } from '../core/data.js';
import { el } from '../core/dom.js';
import { ensureFunction, shortFile } from '../core/project.js';
export class BlueprintControls {
  constructor(explorer) {
    this.explorer = explorer;
    this.unfolding = [];
  }
  context(owner) {
    const explorer = this.explorer;
    return {
      openButton: (n) => this.openButton(unfoldKey(owner, n)),
      activate: (ref, n, v) => { const btn = v && v.el.querySelector(':scope > .box > .head [data-unfold]'); if (btn) btn.click(); else explorer.go(ref); },
      select: (n, v, sym) => explorer.selectNode(n, v, sym),
      afterNode: (n, v) => {
        if (!n.target || n.kind === 'entry') return;
        const embed = this.embed(unfoldKey(owner, n), n.target);
        if (embed) v.el.querySelector('.embed-slot').append(embed);
      },
    };
  }
  openButton(key) {
    const isOpen = this.explorer.trail.current.open.has(key);
    return el('button', { class: `open ${isOpen ? 'on' : ''}`, 'data-unfold': key, title: isOpen ? 'Fold away' : 'Unfold here', html: OPEN_ICON, onclick: (e) => { e.stopPropagation(); this.toggle(key, e.currentTarget); } });
  }
  toggle(key, button) {
    const { vp } = this.explorer;
    const open = this.explorer.trail.current.open;
    const before = button.closest('.node').getBoundingClientRect();
    const opening = !open.has(key);
    if (opening) open.add(key); else [...open].forEach((k) => { if (k.startsWith(key)) open.delete(k); });
    this.explorer.render(true);
    const after = document.querySelector(`[data-unfold="${CSS.escape(key)}"]`);
    if (!after) return;
    const moved = after.closest('.node').getBoundingClientRect();
    vp.x += before.left - moved.left; vp.y += before.top - moved.top; vp.apply();
    const embed = opening ? after.closest('.node').querySelector('.embed') : null;
    if (embed) this.bringIntoView(embed);
  }
  bringIntoView(embed) {
    const { vp, ui } = this.explorer;
    const er = embed.getBoundingClientRect(), hr = ui.vpHost.getBoundingClientRect();
    if (er.right > hr.right - 20) vp.x -= Math.max(0, Math.min(er.right - hr.right + 40, er.left - hr.left - 20));
    if (er.bottom > hr.bottom - 70) vp.y -= Math.max(0, Math.min(er.bottom - hr.bottom + 90, er.top - hr.top - 60));
    vp.apply();
  }
  embed(key, ref) {
    const explorer = this.explorer;
    if (!explorer.trail.current.open.has(key)) return null;
    const sym = lookup(ref);
    if (!sym || sym.kind !== 'function') return null;
    const wrap = el('div', { class: 'embed' });
    wrap.append(el('div', { class: 'embed-label' },
      el('span', {}, ref.path !== explorer.trail.current.path ? `↗ ${shortFile(ref.path)} · ${sym.qual}` : sym.qual),
      el('button', { class: 'btn small go-into', title: 'Make this the whole view', onclick: (e) => { e.stopPropagation(); explorer.go(ref); } }, 'Go into ↘')));
    wrap.append(this.embedBody(key, ref, sym));
    return wrap;
  }
  embedBody(key, ref, sym) {
    if (!FUNCTIONS.has(fnKey(ref))) {
      const note = embedNote('Reading…');
      ensureFunction(ref).then(() => this.explorer.render(true), (err) => { note.textContent = err.message; });
      return note;
    }
    const id = ref.path + ref.sym;
    if (this.unfolding.includes(id) || this.unfolding.length > 5) return embedNote('Already unfolded further out.');
    this.unfolding.push(id);
    const inner = buildFunctionScene(sym, this.context(key));
    this.unfolding.pop();
    return inner.el;
  }
}
function unfoldKey(owner, n) { return `${owner}>${n.target.path}::${n.target.sym}@${n.line || ''}:${n.title}`; }
function embedNote(text) { return el('div', { class: 'note', style: 'padding:30px 10px 6px' }, text); }
