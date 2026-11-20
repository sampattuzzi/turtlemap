import { DIFF, FILES, FUNCTIONS, fnKey, lookup, net, patchProject, setProject } from './data.js';
import { api } from './dom.js';
import { FOCUS_CACHE } from '../map/focus.js';
let CALLERS = null;
const FUNCTION_REQUESTS = new Map();
const OUTLINES = {};
const OUTLINE_REQUESTS = new Map();
function addRemovedSymbols(data) {
  for (const [path, entry] of Object.entries(DIFF ? DIFF.removed : {})) {
    if (entry.module) {
      if (!data.modules.some((m) => m.path === path)) data.modules.push({ ...entry.module, path });
      continue;
    }
    const module = data.modules.find((m) => m.path === path);
    if (module) addRemovedParts(module, entry);
  }
}
function addRemovedParts(module, entry) {
  module.symbols.push(...(entry.symbols || []));
  for (const key of ['methods', 'fields', 'members']) appendToOwners(module, entry[key], key);
  module.constants = [...(module.constants || []), ...(entry.constants || [])];
}
function appendToOwners(module, byOwner, key) {
  for (const [qual, items] of Object.entries(byOwner || {})) {
    const owner = module.symbols.find((s) => s.qual === qual);
    if (owner) owner[key] = [...(owner[key] || []), ...items];
  }
}
export function loadOverview(data) {
  addRemovedSymbols(data);
  setProject(data);
  forgetDerived();
  FUNCTIONS.clear();
  FUNCTION_REQUESTS.clear();
  for (const key of Object.keys(OUTLINES)) delete OUTLINES[key];
  OUTLINE_REQUESTS.clear();
  for (const m of data.modules) addFile(m);
}
export async function loadChanges(since) {
  if (DIFF) return false;
  const changes = await api(`/api/project/changes?since=${since}`);
  if (changes.full) return false;
  const touched = patchProject(changes);
  forgetDerived();
  for (const key of [...FUNCTIONS.keys(), ...FUNCTION_REQUESTS.keys()]) if (touched.has(key.slice(0, key.indexOf('::')))) { FUNCTIONS.delete(key); FUNCTION_REQUESTS.delete(key); }
  for (const path of touched) { delete OUTLINES[path]; OUTLINE_REQUESTS.delete(path); }
  for (const m of changes.modules) addFile(m);
  return true;
}
function forgetDerived() {
  CALLERS = null;
  FOCUS_CACHE.clear();
}
function addFile(m) {
  const f = { ...m, index: {} };
  for (const s of m.symbols) {
    s.file = m.path;
    f.index[s.qual] = s;
    for (const meth of s.methods || []) { meth.file = m.path; meth.owner = s.qual; meth.qual = `${s.qual}.${meth.name}`; f.index[meth.qual] = meth; }
  }
  FILES[m.path] = f;
}
export function ensureFunction(ref) {
  const key = fnKey(ref);
  if (FUNCTIONS.has(key)) return Promise.resolve(FUNCTIONS.get(key));
  if (!FUNCTION_REQUESTS.has(key)) {
    const request = api(`/api/function?path=${encodeURIComponent(ref.path)}&qual=${encodeURIComponent(ref.sym)}`)
      .then((data) => {
        if (FUNCTION_REQUESTS.get(key) !== request) return data;
        FUNCTIONS.set(key, data);
        const sym = lookup(ref);
        if (sym) sym.codeLines = data.code;
        return data;
      })
      .finally(() => { if (FUNCTION_REQUESTS.get(key) === request) FUNCTION_REQUESTS.delete(key); });
    FUNCTION_REQUESTS.set(key, request);
  }
  return FUNCTION_REQUESTS.get(key);
}
export function ensureOutline(path) {
  if (OUTLINES[path]) return Promise.resolve(OUTLINES[path]);
  if (!OUTLINE_REQUESTS.has(path)) {
    const request = api(`/api/outline?path=${encodeURIComponent(path)}`)
      .then((data) => { if (OUTLINE_REQUESTS.get(path) === request) OUTLINES[path] = data; return data; })
      .finally(() => { if (OUTLINE_REQUESTS.get(path) === request) OUTLINE_REQUESTS.delete(path); });
    OUTLINE_REQUESTS.set(path, request);
  }
  return OUTLINE_REQUESTS.get(path);
}
export const shortFile = (p) => p.split('/').slice(-2).join('/');
export function callersOf(ref) {
  if (!CALLERS) {
    CALLERS = new Map();
    for (const e of net().edges) {
      if (!e.kinds.has('calls') || !/^(fn|m):/.test(e.from)) continue;
      if (!CALLERS.has(e.to)) CALLERS.set(e.to, []);
      CALLERS.get(e.to).push(e.from);
    }
  }
  const sym = lookup(ref);
  if (!sym) return [];
  return (CALLERS.get(`${sym.owner ? 'm' : 'fn'}:${ref.path}:${ref.sym}`) || []).map((id) => {
    const match = id.match(/^(?:fn|m):(.*):([^:]*)$/);
    return match ? { path: match[1], sym: match[2] } : null;
  }).filter(Boolean);
}
export function outlineFor(path) { return OUTLINES[path] || null; }
