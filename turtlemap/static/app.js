import { loadComments, startCommentWatch } from './comments/store.js';
import { DIFF, setDiff } from './core/data.js';
import { api, el } from './core/dom.js';
import { reloadProject, stopWatching, watchProject } from './core/live.js';
import { loadOverview } from './core/project.js';
import { setSeen } from './core/review.js';
import { applySettings } from './core/settings.js';
import { Explorer } from './explorer/explorer.js';
let explorerApi = null;
document.addEventListener('keydown', (e) => {
  if (e.target.closest && e.target.closest('input, textarea, select, [contenteditable]')) return;
  if (explorerApi) explorerApi.keys(e);
  if (e.key === '/') { e.preventDefault(); const f = document.querySelector('[data-find]'); if (f) f.click(); }
});
function screen(...kids) {
  const app = document.getElementById('app');
  app.innerHTML = '';
  document.getElementById('measure').innerHTML = '';
  explorerApi = null;
  app.append(el('div', { class: 'screen' }, el('div', { class: 'screen-card' }, el('h1', { class: 'wordmark' },
    el('img', { class: 'on-dark', src: 'wordmark-dark.svg', alt: 'Turtlemap: dependencies all the way down' }),
    el('img', { class: 'on-light', src: 'wordmark-light.svg', alt: 'Turtlemap: dependencies all the way down' })), ...kids)));
}
async function showWelcome(message) {
  let capabilities = { recent: [] };
  try { capabilities = await api('/api/capabilities'); } catch (e) {}
  const input = el('input', { id: 'folder-input', class: 'path-input', placeholder: '/path/to/your/project', autocomplete: 'off' });
  const form = el('form', { class: 'open-row', onsubmit: (e) => { e.preventDefault(); if (input.value.trim()) openProject(input.value.trim()); } }, input, el('button', { class: 'btn primary', type: 'submit' }, 'Open'));
  screen(
    el('p', { class: 'lede' }, 'Open a Python, JavaScript or TypeScript project to see its packages, modules and classes as a dependency map, and every function as a blueprint.'),
    message ? el('p', { class: 'error-text' }, message) : null,
    el('div', { class: 'or' }, 'Folder to open'),
    form,
    capabilities.recent.length ? el('div', { class: 'recent' }, el('div', { class: 'kind' }, 'Recent'), capabilities.recent.map((root) => el('button', { class: 'recent-item', title: root, onclick: () => openProject(root) }, el('span', {}, root.split(/[\\/]/).pop()), el('small', {}, root)))) : null,
  );
  input.focus();
}
async function openProject(root) {
  try {
    await api(`/api/open?root=${encodeURIComponent(root)}`);
  } catch (error) {
    showWelcome(error.message);
    return;
  }
  waitForProject();
}
let WAITING = 0;
async function waitForProject() {
  stopWatching();
  const generation = ++WAITING;
  const started = Date.now();
  const tick = async () => {
    let status;
    try { status = await api('/api/status'); } catch (error) { showWelcome(error.message); return; }
    if (generation !== WAITING) return;
    if (!status.open) { showWelcome(); return; }
    if (status.error) { showLoadError(status); return; }
    if (!status.ready) { showProgress(status, started); setTimeout(tick, 400); return; }
    try {
      await loadProject(status);
    } catch (error) { showWelcome(error.message); return; }
    if (generation !== WAITING) return;
    mount(status);
  };
  tick();
}
function showLoadError(status) {
  const stop = status.diff ? el('button', { class: 'btn', onclick: () => api('/api/diff?spec=').then(() => waitForProject(), (err) => showWelcome(err.message)) }, 'Stop comparing') : null;
  screen(el('p', { class: 'error-text' }, status.diff ? `Comparing ${status.diff.spec} failed.` : 'Reading the project failed.'), el('pre', { class: 'error-detail' }, status.error), stop, el('button', { class: 'btn', onclick: () => showWelcome() }, 'Open another folder'));
}
function showProgress(status, started) {
  const seconds = Math.round((Date.now() - started) / 1000);
  const text = progressText(status);
  const hint = seconds > 2 ? `${seconds}s — large projects take a little while the first time; after that they open from a cache.` : ' ';
  const shown = document.getElementById('load-text');
  if (shown) { shown.textContent = text; document.getElementById('load-hint').textContent = hint; }
  else screen(el('div', { class: 'spinner' }), el('p', { class: 'lede', id: 'load-text' }, text), el('p', { class: 'muted', id: 'load-hint' }, hint));
}
function progressText(status) {
  if (status.diff && status.files && !status.loading) return `Comparing ${status.diff.spec}…`;
  if (status.diff) return `Reading ${status.diff.spec}: ${status.files.toLocaleString()} source files…`;
  return `Reading ${status.files.toLocaleString()} source files in ${status.name}…`;
}
async function loadProject(status) {
  setDiff(status.diff ? await api('/api/diff/data') : null);
  setSeen(new Set(DIFF ? (await api('/api/seen')).seen : []));
  loadOverview(await api('/api/project'));
  await loadComments();
}
const LIVE = {
  changed: async (status) => { await loadProject(status); if (explorerApi) await explorerApi.projectChanged(); },
  elsewhere: () => waitForProject(),
};
function mount(status) {
  const app = document.getElementById('app');
  app.innerHTML = '';
  document.getElementById('measure').innerHTML = '';
  document.querySelectorAll('.popover, .palette').forEach((p) => p.remove());
  explorerApi = new Explorer(app, { showWelcome, waitForProject, reload: () => reloadProject(LIVE).catch((error) => showWelcome(error.message)) });
  startCommentWatch();
  watchProject(status, LIVE);
}
async function boot() {
  applySettings();
  try {
    const status = await api('/api/status');
    if (!status.open) showWelcome(); else waitForProject();
  } catch (error) {
    screen(el('p', { class: 'error-text' }, `Cannot reach the Turtlemap server: ${error.message}`));
  }
}
let booted = false;
const startOnce = () => { if (booted) return; booted = true; boot(); };
if (document.fonts && document.fonts.ready) document.fonts.ready.then(startOnce, startOnce); else startOnce();
setTimeout(startOnce, 1500);
