import { api, el } from './dom.js';
export function watchForUpdates() {
  (async () => {
    let known = null;
    while (true) {
      try {
        const answer = await api(`/api/update${known ? updateQuery(known) : ''}`);
        if (known && answer.version !== known.version) { showUpdated(); return; }
        if (answer.waiting && waitingCommit(answer) !== waitingCommit(known)) showWaiting(answer.waiting);
        known = answer;
      } catch (error) {
        await new Promise((resolve) => setTimeout(resolve, 3000));
      }
    }
  })();
}
function updateQuery(known) {
  return `?version=${encodeURIComponent(known.version)}&waiting=${encodeURIComponent(waitingCommit(known))}&wait=25`;
}
function waitingCommit(state) { return state && state.waiting ? state.waiting.commit : ''; }
function showUpdated() {
  updateNote(
    el('span', {}, 'Turtlemap has been updated. Refresh to use the new version.'),
    el('button', { class: 'btn primary', onclick: () => location.reload() }, 'Refresh'),
  );
}
function showWaiting(waiting) {
  updateNote(el('span', {}, 'A Turtlemap update needs new libraries. In ', el('code', {}, waiting.folder), ' run ', el('code', {}, 'git pull'), ' and ', el('code', {}, 'poetry install'), ', then start Turtlemap again.'));
}
function updateNote(...kids) {
  document.querySelectorAll('.update-note').forEach((n) => n.remove());
  const note = el('div', { class: 'update-note', role: 'status' }, el('span', { class: 'update-icon', 'aria-hidden': 'true' }, '⬆'), ...kids);
  note.append(el('button', { class: 'btn small', title: 'Dismiss', 'aria-label': 'Dismiss', onclick: () => note.remove() }, '✕'));
  document.body.append(note);
}
