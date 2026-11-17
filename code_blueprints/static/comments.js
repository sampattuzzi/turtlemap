let COMMENTS = { threads: [], cursor: 0, agent: {} };
let COMMENT_WATCH = 0;
let COMMENT_ACTIONS = null;
let onCommentsChanged = () => {};
let PICK = null;
let CARD = null;
let SHOW_RESOLVED = false;
const REPLY_DRAFTS = new Map();
const AGENT_ACTIVE_SECONDS = 90;
const AGENT_NOTE_SECONDS = 30 * 60;
const AGENT_WORDS = { seen: 'Agent has seen this', working: 'Agent is working on this', done: 'Agent thinks this is done' };

async function loadComments() {
  try {
    const data = await api('/api/comments');
    COMMENTS = { threads: data.threads, cursor: data.cursor, agent: data.agent || {} };
  } catch (error) {
    COMMENTS = { threads: [], cursor: 0, agent: {} };
  }
}

function startCommentWatch() {
  const generation = ++COMMENT_WATCH;
  (async () => {
    while (generation === COMMENT_WATCH) {
      try {
        const since = COMMENTS.cursor;
        const answer = await api(`/api/comments/events?since=${since}&wait=25`);
        if (generation !== COMMENT_WATCH) return;
        if (answer.cursor < since) { await loadComments(); onCommentsChanged(); continue; }
        mergeThreads(answer.threads);
        COMMENTS.cursor = answer.cursor;
        COMMENTS.agent = answer.agent || COMMENTS.agent;
        if (answer.events.length) { announce(answer.events); onCommentsChanged(); }
      } catch (error) {
        await new Promise((resolve) => setTimeout(resolve, 3000));
      }
    }
  })();
}

function mergeThreads(threads) {
  for (const thread of threads) {
    const at = COMMENTS.threads.findIndex((t) => t.id === thread.id);
    if (at >= 0) COMMENTS.threads[at] = thread; else COMMENTS.threads.push(thread);
  }
}

function openThreads() { return COMMENTS.threads.filter((t) => !t.resolved); }

function threadById(id) { return COMMENTS.threads.find((t) => t.id === id) || null; }

function announce(events) {
  for (const event of events) {
    if (event.author !== 'agent' || !event.thread) continue;
    const thread = threadById(event.thread);
    if (!thread) continue;
    if (event.type === 'replied') toast(`Agent replied on ${threadLabel(thread)}`, () => COMMENT_ACTIONS && COMMENT_ACTIONS.open(thread.id));
    if (event.type === 'agent' && thread.agent && thread.agent.state === 'done') toast(`Agent thinks “${threadLabel(thread)}” is done`, () => COMMENT_ACTIONS && COMMENT_ACTIONS.open(thread.id));
  }
}

function toast(text, onClick) {
  document.querySelectorAll('.toast').forEach((t) => t.remove());
  const box = el('button', { class: 'toast', onclick: () => { box.remove(); onClick(); } }, '💬 ', text);
  document.body.append(box);
  setTimeout(() => box.remove(), 7000);
}

function threadLabel(thread) { return thread.anchor.label || anchorLabel(thread.anchor); }

function anchorLabel(anchor) {
  if (anchor.view === 'map') {
    const ids = anchor.ids || [];
    return ids.length === 1 ? shortId(ids[0]) : `${ids.length} boxes in ${commonPlace(ids)}`;
  }
  if (anchor.view === 'blueprint') {
    const nodes = anchor.nodes || [];
    if (!nodes.length || (nodes.length === 1 && nodes[0].title === anchor.qual)) return anchor.qual;
    return `${anchor.qual} · ${nodes.length === 1 ? nodes[0].title : `${nodes.length} nodes`}`;
  }
  const lines = anchor.start === anchor.end ? `line ${anchor.start}` : `lines ${anchor.start}–${anchor.end}`;
  return `${anchor.qual || baseName(anchor.path)} · ${lines}`;
}

function shortId(id) {
  const [kind, rest] = [id.slice(0, id.indexOf(':')), id.slice(id.indexOf(':') + 1)];
  if (kind === 'pkg') return `${rest}/`;
  if (kind === 'mod') return baseName(rest);
  if (['cls', 'fn', 'm', 'f', 'c'].includes(kind)) { const at = rest.lastIndexOf(':'); return `${baseName(rest.slice(0, at))} › ${rest.slice(at + 1)}`; }
  return rest;
}

function commonPlace(ids) {
  const paths = ids.map((id) => id.slice(id.indexOf(':') + 1).split(':')[0]);
  const first = paths[0] || '';
  return paths.every((p) => p === first) ? baseName(first) : 'several places';
}

function agentText(thread) {
  const agent = thread.agent || {};
  if (!agent.state) return "Agent hasn't seen this yet";
  return agent.state === 'working' && agent.note ? `Agent is working: ${agent.note}` : AGENT_WORDS[agent.state];
}

function pickSize(pick) { return !pick ? 0 : pick.kind === 'code' ? pick.end - pick.start + 1 : pick.ids.size; }

function pickLabel(pick) {
  if (pick.kind === 'code') return `${pick.qual || baseName(pick.path)} · ${pick.start === pick.end ? `line ${pick.start}` : `lines ${pick.start}–${pick.end}`}`;
  if (pick.kind === 'map') return pick.ids.size === 1 ? shortId([...pick.ids][0]) : `${pick.ids.size} boxes`;
  return `${pick.fn.sym} · ${pick.ids.size === 1 ? '1 node' : `${pick.ids.size} nodes`}`;
}

function anchorFor(pick) {
  const fnRef = pick.fn;
  if (pick.kind === 'map') { const ids = [...pick.ids]; return { view: 'map', ids, label: anchorLabel({ view: 'map', ids }) }; }
  if (pick.kind === 'code') {
    const anchor = { view: 'code', path: pick.path, qual: pick.qual || null, start: pick.start, end: pick.end };
    if (pick.text) anchor.text = pick.text;
    return { ...anchor, label: anchorLabel(anchor) };
  }
  const data = FUNCTIONS.get(fnKey(fnRef));
  const byId = new Map((data ? data.graph.nodes : []).map((n) => [n.id, n]));
  const nodes = [...pick.ids].map((id) => byId.get(id)).filter(Boolean).map((n) => ({ id: n.id, title: n.kind === 'entry' ? fnRef.sym : n.title, line: n.diff === 'removed' ? null : n.line }));
  const anchor = { view: 'blueprint', path: fnRef.path, qual: fnRef.sym, nodes };
  return { ...anchor, label: anchorLabel(anchor) };
}

function renderCommentList(left) {
  const open = openThreads();
  const shown = SHOW_RESOLVED ? COMMENTS.threads : open;
  left.append(el('div', { class: 'comment-head' },
    el('span', {}, `${open.length} open`),
    el('button', { class: 'btn small', onclick: () => { SHOW_RESOLVED = !SHOW_RESOLVED; onCommentsChanged(); } }, SHOW_RESOLVED ? 'Hide resolved' : 'Show resolved')));
  const agent = agentLine();
  if (agent) left.append(el('div', { class: 'comment-agent' }, agent));
  if (!shown.length) {
    left.append(el('p', { class: 'comment-hint' }, 'Select something and press C, or use 💬 Comment, to leave a comment. ⌘ or Ctrl-click adds boxes and nodes to a selection, Shift-drag draws a box around them, and dragging down the line numbers picks lines of code.'));
    return;
  }
  const ordered = [...shown].sort((a, b) => Number(a.resolved) - Number(b.resolved) || a.created - b.created);
  for (const thread of ordered) {
    const last = thread.messages[thread.messages.length - 1];
    const state = (thread.agent && thread.agent.state) || 'unseen';
    left.append(el('button', { class: `comment-row${thread.resolved ? ' resolved' : ''}${CARD && CARD.id === thread.id ? ' active' : ''}`, onclick: () => COMMENT_ACTIONS && COMMENT_ACTIONS.open(thread.id) },
      el('span', { class: `agent-dot agent-${thread.resolved ? 'resolved' : state}`, title: thread.resolved ? 'Resolved' : agentText(thread) }),
      el('span', { class: 'comment-row-main' },
        el('span', { class: 'comment-row-label' }, threadLabel(thread), thread.where && thread.where.outdated ? el('span', { class: 'outdated' }, 'outdated') : null),
        el('span', { class: 'comment-row-body' }, thread.messages[0].body),
        el('span', { class: 'comment-row-meta' }, `${thread.messages.length > 1 ? `${thread.messages.length - 1} repl${thread.messages.length > 2 ? 'ies' : 'y'} · last by ${last.author === 'agent' ? 'agent' : 'you'} · ` : ''}${thread.resolved ? 'resolved' : agentText(thread)}`))));
  }
}

function agentLine() {
  const agent = COMMENTS.agent || {};
  const now = Date.now() / 1000;
  const active = agent.polled && now - agent.polled < AGENT_ACTIVE_SECONDS;
  const note = agent.note && agent.at && now - agent.at < AGENT_NOTE_SECONDS ? agent.note : null;
  if (!active && !note) return null;
  return el('span', { class: `agent-status${active ? ' active' : ''}`, title: active ? 'An agent is watching for comments' : 'No agent has checked in for a while' }, active ? '● ' : '○ ', note ? `Agent: ${note}` : 'Agent watching');
}

function paintAgentChip() {
  const chip = document.getElementById('agent-chip');
  if (!chip) return;
  chip.innerHTML = '';
  const line = agentLine();
  chip.hidden = !line;
  if (line) chip.append(line);
}
setInterval(paintAgentChip, 30000);

function renderPickBar(host, pick, actions) {
  host.querySelectorAll('.pick-bar').forEach((bar) => bar.remove());
  if (!pick || (CARD && CARD.mode === 'new')) return;
  host.append(el('div', { class: 'pick-bar' },
    el('span', {}, pickLabel(pick)),
    el('button', { class: 'btn small primary', title: 'Comment on the selection (C)', onclick: () => actions.compose() }, '💬 Comment'),
    pick.implicit ? null : el('button', { class: 'btn small', title: 'Clear the selection (Esc)', onclick: () => actions.clearPick() }, '✕')));
}

function renderCommentCard(host, actions) {
  const before = host.querySelector('.comment-card textarea');
  const focus = before && document.activeElement === before ? { start: before.selectionStart, end: before.selectionEnd } : null;
  host.querySelectorAll('.comment-card').forEach((card) => card.remove());
  if (!CARD) return;
  const card = CARD.mode === 'new' ? composerCard(actions) : threadCard(actions);
  if (!card) return;
  host.append(card);
  const area = card.querySelector('textarea');
  if (area && (focus || CARD.focus)) { area.focus(); if (focus) area.setSelectionRange(focus.start, focus.end); CARD.focus = false; }
}

function composerCard(actions) {
  const area = el('textarea', { placeholder: 'What should change, or what is unclear?', rows: 4 });
  area.value = CARD.draft || '';
  area.addEventListener('input', () => { CARD.draft = area.value; });
  const save = () => { if (area.value.trim()) actions.create(CARD.anchor, area.value); };
  area.addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) save(); if (e.key === 'Escape') actions.close(); });
  return el('div', { class: 'comment-card' },
    el('div', { class: 'comment-card-head' }, el('strong', {}, 'New comment'), el('button', { class: 'btn small', title: 'Cancel (Esc)', onclick: () => actions.close() }, '✕')),
    el('div', { class: 'comment-card-where' }, CARD.anchor.label),
    area,
    el('div', { class: 'comment-card-actions' }, el('span', { class: 'udim' }, '⌘/Ctrl + Enter'), el('button', { class: 'btn small primary', onclick: save }, 'Comment')));
}

function threadCard(actions) {
  const thread = threadById(CARD.id);
  if (!thread) return null;
  const open = openThreads();
  const at = open.findIndex((t) => t.id === thread.id);
  const area = el('textarea', { placeholder: thread.resolved ? 'Reopen to reply' : 'Reply…', rows: 2 });
  area.disabled = thread.resolved;
  area.value = REPLY_DRAFTS.get(thread.id) || '';
  area.addEventListener('input', () => REPLY_DRAFTS.set(thread.id, area.value));
  const send = () => { if (area.value.trim()) { actions.reply(thread.id, area.value); REPLY_DRAFTS.delete(thread.id); } };
  area.addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) send(); if (e.key === 'Escape') actions.close(); });
  const state = (thread.agent && thread.agent.state) || 'unseen';
  return el('div', { class: `comment-card${thread.resolved ? ' resolved' : ''}` },
    el('div', { class: 'comment-card-head' },
      el('strong', {}, thread.id),
      el('span', { class: 'comment-card-nav' },
        el('button', { class: 'btn small', title: 'Previous open comment ([)', disabled: open.length < 2, onclick: () => actions.step(-1) }, '‹'),
        el('span', { class: 'udim' }, at >= 0 ? `${at + 1} of ${open.length}` : 'resolved'),
        el('button', { class: 'btn small', title: 'Next open comment (])', disabled: open.length < 2, onclick: () => actions.step(1) }, '›')),
      el('button', { class: 'btn small', title: 'Close (Esc)', onclick: () => actions.close() }, '✕')),
    el('div', { class: 'comment-card-where' }, threadLabel(thread), thread.where && thread.where.outdated ? el('span', { class: 'outdated', title: 'The code this points at has changed since' }, 'outdated') : null),
    el('div', { class: 'comment-messages' }, thread.messages.map((m) => el('div', { class: `comment-message from-${m.author}` },
      el('div', { class: 'comment-meta' }, m.author === 'agent' ? 'Agent' : 'You', ' · ', new Date(m.at * 1000).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' })),
      el('div', { class: 'comment-body' }, m.body)))),
    el('div', { class: `comment-agent-state agent-${thread.resolved ? 'resolved' : state}` }, el('span', { class: `agent-dot agent-${thread.resolved ? 'resolved' : state}` }), thread.resolved ? 'Resolved' : agentText(thread)),
    area,
    el('div', { class: 'comment-card-actions' },
      el('button', { class: 'btn small', onclick: () => actions.resolve(thread.id, !thread.resolved) }, thread.resolved ? 'Reopen' : '✓ Resolve'),
      el('button', { class: 'btn small primary', disabled: thread.resolved, onclick: send }, 'Reply')));
}

function mapTargets(anchor) {
  if (anchor.view === 'map') return anchor.ids || [];
  if (anchor.view === 'blueprint' || (anchor.view === 'code' && anchor.qual)) {
    const sym = lookup({ path: anchor.path, sym: anchor.qual });
    const id = sym ? `${sym.kind !== 'function' ? 'cls' : sym.owner ? 'm' : 'fn'}:${anchor.path}:${anchor.qual}` : null;
    if (id && net().nodes.has(id)) return [id];
  }
  return [`mod:${anchor.path}`];
}

function decorateMap(sceneEl, open) {
  const N = net();
  const pins = new Map();
  for (const thread of openThreads()) {
    const boxes = new Set();
    for (const id of mapTargets(thread.anchor)) {
      const chain = N.nodes.has(id) ? N.chain(id) : [];
      const shown = [...chain].reverse().map((n) => sceneEl.querySelector(`.nb[data-id="${CSS.escape(n.id)}"]`)).find(Boolean);
      if (shown) boxes.add(shown);
    }
    if (CARD && CARD.id === thread.id) boxes.forEach((box) => box.classList.add('in-thread'));
    const [first] = boxes;
    if (first) { if (!pins.has(first)) pins.set(first, []); pins.get(first).push(thread); }
  }
  for (const [box, threads] of pins) addPin(box.classList.contains('leaf') ? box : box.querySelector(':scope > .nhead') || box, threads, open);
  if (PICK && PICK.kind === 'map') for (const id of PICK.ids) { const box = sceneEl.querySelector(`.nb[data-id="${CSS.escape(id)}"]`); if (box) box.classList.add('picked'); }
}

function decorateBlueprint(layer, fnRef, open) {
  const elements = new Map([...layer.querySelectorAll(':scope > .node[data-node]')].map((e) => [e.dataset.node, e]));
  const data = FUNCTIONS.get(fnKey(fnRef));
  const nodes = data ? data.graph.nodes : [];
  const matching = (wanted) => nodes.filter((n) => wanted.some((w) => w.id === n.id && (!w.title || w.title === n.title || n.kind === 'entry')) || wanted.some((w) => w.title && w.title === n.title && w.line === n.line)).map((n) => elements.get(n.id)).filter(Boolean);
  const pins = new Map();
  for (const thread of openThreads()) {
    const a = thread.anchor;
    let hit = [];
    if (a.view === 'blueprint' && a.path === fnRef.path && a.qual === fnRef.sym) hit = matching(a.nodes || []);
    else if (a.view === 'code' && a.path === fnRef.path) { const r = codeRange(thread); hit = nodes.filter((n) => n.kind !== 'entry' && n.line >= r.start && n.line <= r.end).map((n) => elements.get(n.id)).filter(Boolean).slice(0, 1); }
    if (CARD && CARD.id === thread.id) hit.forEach((e) => e.classList.add('in-thread'));
    if (hit.length) { if (!pins.has(hit[0])) pins.set(hit[0], []); pins.get(hit[0]).push(thread); }
  }
  for (const [node, threads] of pins) addPin(node, threads, open);
  if (PICK && PICK.kind === 'blueprint' && PICK.fn.path === fnRef.path && PICK.fn.sym === fnRef.sym) {
    for (const id of PICK.ids) { const e = elements.get(id); if (e) e.classList.add('picked'); }
  }
}

function addPin(holder, threads, open) {
  holder.append(el('button', { class: 'comment-pin', 'data-threads': threads.map((t) => t.id).join(' '), title: threads.map((t) => `${t.id}: ${t.messages[0].body.slice(0, 80)}`).join('\n'), onclick: (e) => { e.stopPropagation(); open(threads[0].id); } }, '💬', threads.length > 1 ? String(threads.length) : null));
}

function clearDecorations(root) {
  root.querySelectorAll('.comment-pin').forEach((p) => p.remove());
  root.querySelectorAll('.picked, .in-thread').forEach((p) => p.classList.remove('picked', 'in-thread'));
}

function paintCodeViews(container, open, onPick) {
  for (const view of container.querySelectorAll('.code-view')) {
    view.querySelectorAll('.cmark').forEach((m) => m.remove());
    const rows = [...view.querySelectorAll('.ln[data-line]')];
    const marks = new Map();
    for (const row of rows) {
      const line = Number(row.dataset.line), path = row.dataset.path;
      row.classList.toggle('line-picked', Boolean(PICK && PICK.kind === 'code' && PICK.path === path && line >= PICK.start && line <= PICK.end));
    }
    for (const t of openThreads()) {
      const at = codeRange(t);
      if (!at) continue;
      const same = rows.filter((row) => row.dataset.path === at.path);
      const row = same.find((r) => Number(r.dataset.line) >= at.start && Number(r.dataset.line) <= at.end) || [...same].reverse().find((r) => Number(r.dataset.line) < at.start && r.querySelector('.fold-chip') && !same.some((n) => Number(n.dataset.line) > Number(r.dataset.line) && Number(n.dataset.line) <= at.start));
      if (row) { if (!marks.has(row)) marks.set(row, []); marks.get(row).push(t); }
    }
    for (const [row, threads] of marks) row.append(el('button', { class: 'cmark', 'data-threads': threads.map((t) => t.id).join(' '), title: threads.map((t) => `${t.id}: ${t.messages[0].body.slice(0, 80)}`).join('\n'), onclick: (e) => { e.stopPropagation(); open(threads[0].id); } }, '💬'));
    if (!view.dataset.selectable) { view.dataset.selectable = '1'; enableLineSelection(view, onPick); }
  }
}

function codeRange(thread) {
  const placed = thread.where && thread.where.locations && thread.where.locations[0];
  if (thread.anchor.view !== 'code') return null;
  return placed && placed.start ? { path: placed.path, start: placed.start, end: placed.end } : thread.anchor;
}

function enableLineSelection(view, onPick) {
  const rowAt = (target) => { const row = target && target.closest && target.closest('.ln[data-line]'); return row && view.contains(row) ? row : null; };
  const refresh = () => view.querySelectorAll('.ln[data-line]').forEach((row) => { const line = Number(row.dataset.line); row.classList.toggle('line-picked', Boolean(PICK && PICK.kind === 'code' && PICK.path === row.dataset.path && line >= PICK.start && line <= PICK.end)); });
  view.addEventListener('click', (e) => { if (e.target.closest('.no')) e.stopPropagation(); }, true);
  view.addEventListener('mousedown', (e) => {
    const row = rowAt(e.target);
    if (!row || !e.target.closest('.no') || e.button !== 0) return;
    e.preventDefault();
    const path = row.dataset.path, qual = row.dataset.qual || null, line = Number(row.dataset.line);
    const from = e.shiftKey && PICK && PICK.kind === 'code' && PICK.path === path ? PICK.start : line;
    PICK = { kind: 'code', path, qual, start: Math.min(from, line), end: Math.max(from, line) };
    refresh();
    const move = (ev) => {
      const over = rowAt(document.elementFromPoint(ev.clientX, ev.clientY));
      if (!over || over.dataset.path !== path) return;
      const to = Number(over.dataset.line);
      PICK = { ...PICK, start: Math.min(from, to), end: Math.max(from, to) };
      refresh();
    };
    const up = () => {
      document.removeEventListener('mousemove', move);
      document.removeEventListener('mouseup', up);
      const picked = [...view.querySelectorAll('.ln[data-line]')].filter((r) => r.dataset.path === path && Number(r.dataset.line) >= PICK.start && Number(r.dataset.line) <= PICK.end);
      const numbers = picked.map((r) => Number(r.dataset.line));
      const contiguous = numbers.length === PICK.end - PICK.start + 1 && numbers.every((n, i) => n === PICK.start + i);
      if (contiguous) PICK.text = picked.map((r) => (r.querySelector('.tx') || r).textContent).join('\n');
      onPick();
    };
    document.addEventListener('mousemove', move);
    document.addEventListener('mouseup', up);
  });
}
