export const SETTINGS_KEY = 'code-blueprints-settings';
export const settings = Object.assign({ pinFont: 'mono', size: 12.5, theme: 'dark', plain: false, types: false, tests: true, constants: true, layout: 'balanced' }, (() => { try { return JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}'); } catch (e) { return {}; } })());
export function saveSettings() { try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings)); } catch (e) {} }
export function applySettings() {
  const root = document.documentElement;
  const fonts = { mono: '"JetBrains Mono", ui-monospace, monospace', lexend: '"Lexend", system-ui, sans-serif', atkinson: '"Atkinson Hyperlegible", system-ui, sans-serif', comic: '"Comic Neue", system-ui, sans-serif' };
  root.style.setProperty('--font-pin', fonts[settings.pinFont] || fonts.mono);
  root.style.setProperty('--font-head', settings.pinFont === 'mono' ? '"Inter", system-ui, sans-serif' : fonts[settings.pinFont]);
  root.style.setProperty('--node-size', `${settings.size}px`);
  root.style.setProperty('--tracking', settings.pinFont === 'mono' ? '0em' : '0.02em');
  if (settings.theme === 'system') root.removeAttribute('data-theme'); else root.setAttribute('data-theme', settings.theme);
}
