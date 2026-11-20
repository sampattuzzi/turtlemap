import { api, baseName, el } from './dom.js';
let WATCH = 0;
let SHOWN = { root: null, revision: 0, diff: null };
export function watchProject(status, handlers) {
  const generation = ++WATCH;
  SHOWN = { root: status.root, revision: status.revision, diff: diffSpec(status) };
  (async () => {
    let since = status.revision;
    while (generation === WATCH) {
      try {
        const answer = await api(`/api/project/events?since=${since}&wait=25`);
        if (generation !== WATCH) return;
        since = answer.revision;
        if (!sameProject(answer)) { stopWatching(); handlers.elsewhere(); return; }
        if (answer.ready && answer.revision > SHOWN.revision) await show(answer, handlers.changed);
      } catch (error) {
        await new Promise((resolve) => setTimeout(resolve, 3000));
      }
    }
  })();
}
export function stopWatching() { WATCH += 1; }
export async function reloadProject(handlers) {
  const answer = await api('/api/reload');
  if (!answer.ready || !sameProject(answer)) { stopWatching(); handlers.elsewhere(); return; }
  if (answer.revision > SHOWN.revision) await show(answer, handlers.changed);
  else liveNote('The map already matches the code');
}
async function show(status, changed) {
  await changed(status, SHOWN.revision);
  SHOWN.revision = Math.max(SHOWN.revision, status.revision);
  liveNote(updateText(status));
}
function sameProject(status) {
  return status.open && status.root === SHOWN.root && diffSpec(status) === SHOWN.diff;
}
function diffSpec(status) { return status.diff ? status.diff.spec : null; }
function updateText(status) {
  const edited = status.edited || [];
  const what = status.editedCount === 1 ? baseName(edited[0]) : `${status.editedCount} files`;
  return status.editedCount ? `Redrawn after changes to ${what}` : 'Redrawn';
}
function liveNote(text) {
  document.querySelectorAll('.live-note').forEach((n) => n.remove());
  const note = el('div', { class: 'live-note', role: 'status' }, '↻ ', text);
  document.body.append(note);
  setTimeout(() => note.classList.add('leaving'), 2200);
  setTimeout(() => note.remove(), 2800);
}
