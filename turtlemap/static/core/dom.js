const QUERY = new URLSearchParams(location.search);
const TOKEN = QUERY.get('t') || '';
export async function api(path) {
  return answer(await fetch(path, { headers: { 'X-Blueprints-Token': TOKEN } }));
}
export async function answer(response) {
  let body = null;
  try { body = await response.json(); } catch (e) { body = null; }
  if (!response.ok) throw new Error((body && body.error) || `${response.status} ${response.statusText}`);
  return body;
}
export const baseName = (p) => p.split('/').pop();
export function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') e.className = v; else if (k === 'html') e.innerHTML = v; else if (k === 'style') e.style.cssText = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v); else e.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat(Infinity)) { if (kid == null || kid === false) continue; e.append(kid.nodeType ? kid : document.createTextNode(String(kid))); }
  return e;
}
const SVGNS = 'http://www.w3.org/2000/svg';
export function svg(tag, attrs = {}) { const e = document.createElementNS(SVGNS, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); return e; }
export async function apiPost(path, payload) {
  return answer(await fetch(path, { method: 'POST', headers: { 'X-Blueprints-Token': TOKEN, 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }));
}
export function speak(text) { try { speechSynthesis.cancel(); const u = new SpeechSynthesisUtterance(text.replace(/_/g, ' ').replace(/\./g, ' ')); u.rate = 0.95; speechSynthesis.speak(u); } catch (e) {} }
