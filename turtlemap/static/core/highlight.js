import { el } from './dom.js';
const PY_KEYWORDS = new Set('and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield'.split(' '));
const PY_BUILTINS = new Set('abs all any bool bytes callable chr dict dir divmod enumerate filter float format frozenset getattr hasattr hash id input int isinstance issubclass iter len list map max min next object open ord pow print property range repr reversed round set setattr slice sorted staticmethod classmethod str sum super tuple type vars zip'.split(' '));
const PY_TYPES = new Set('bool bytes complex dict float frozenset int list object set str tuple type'.split(' '));
const PY_TOKEN = /(#.*)|([rRbBuUfF]{0,2})("""|'''|"|')|(@[A-Za-z_][\w.]*)|(\b0[xXoObB][\da-fA-F_]+\b|\b\d[\d_]*(?:\.[\d_]*)?(?:[eE][+-]?\d+)?j?\b|\.\d[\d_]*(?:[eE][+-]?\d+)?j?\b)|([A-Za-z_]\w*)/g;

const JS_KEYWORDS = new Set('abstract as async await break case catch class const continue debugger declare default delete do else enum export extends finally for from function get if implements import in instanceof interface keyof let new of private protected public readonly return satisfies set static switch throw try type typeof var void while with yield'.split(' '));
const JS_BUILTINS = new Set('Array Boolean Date Error JSON Map Math Number Object Promise Reflect RegExp Set String Symbol WeakMap console document fetch parseFloat parseInt require setInterval setTimeout window'.split(' '));
const JS_TYPES = new Set('any bigint boolean never number object string symbol unknown void'.split(' '));
const JS_TOKEN = /(\/\/.*)|(\/\*)|(["'`])|(@[A-Za-z_$][\w$.]*)|(\b0[xXoObB][\da-fA-F_]+n?\b|\b\d[\d_]*(?:\.[\d_]*)?(?:[eE][+-]?\d+)?n?\b|\.\d[\d_]*(?:[eE][+-]?\d+)?\b)|([A-Za-z_$][\w$]*)/g;

function languageOf(path) { return /\.[cm]?[jt]sx?$/.test(path || '') ? 'script' : 'python'; }

export function codePainter(special = null, fixedPath = null) {
  let open = null;
  let last = null;
  let language = null;
  return (text, no, path = fixedPath) => {
    const now = languageOf(path);
    if (no == null || last == null || no !== last + 1 || now !== language) open = null;
    last = no == null ? null : no;
    language = now;
    const { parts, close } = now === 'script' ? paintScript(text, open, special) : paintPython(text, open, special);
    open = close;
    return parts;
  };
}

const STOP = Symbol('stop');

class LinePainter {
  constructor(text, pattern, special) {
    this.text = text;
    this.pattern = pattern;
    this.special = special;
    this.parts = [];
    this.at = 0;
    this.previousWord = null;
  }
  plainUpTo(end) {
    if (end > this.at) this.parts.push(this.text.slice(this.at, end));
  }
  token(cls, end) {
    const piece = this.text.slice(this.at, end);
    this.parts.push(cls === 'plain' ? piece : el('span', { class: `s-${cls}` }, piece));
    this.at = end;
  }
  skipTo(end) {
    this.pattern.lastIndex = end;
    this.previousWord = null;
  }
  unclosed(cls, close) {
    this.token(cls, this.text.length);
    return { parts: this.parts, close };
  }
  run(step) {
    this.pattern.lastIndex = this.at;
    for (let m = this.pattern.exec(this.text); m; m = this.pattern.exec(this.text)) {
      this.plainUpTo(m.index);
      this.at = m.index;
      const result = step(m, m.index + m[0].length);
      if (result === STOP) break;
      if (result) return result;
    }
    this.plainUpTo(this.text.length);
    return { parts: this.parts.length ? this.parts : [this.text], close: null };
  }
  word(m, end, classify) {
    const hit = this.special && this.special(this.text, m.index);
    if (hit) {
      this.parts.push(hit.node);
      this.at = hit.end;
      this.skipTo(hit.end);
      return;
    }
    const word = m[6];
    this.token(classify(word, this.previousWord, this.text, end), end);
    this.previousWord = word;
  }
}

function paintPython(text, open, special = null) {
  const p = new LinePainter(text, PY_TOKEN, special);
  if (open) {
    const end = text.indexOf(open, 0);
    if (end < 0) return { parts: [el('span', { class: 's-str' }, text)], close: open };
    p.token('str', end + 3);
  }
  return p.run((m, end) => pythonToken(p, m, end));
}

function pythonToken(p, m, end) {
  if (m[1]) { p.token('comment', end); return STOP; }
  if (m[3]) return closeString(p, m[3], end, m[3].length === 3 ? m[3] : null);
  if (m[4]) p.token(p.text.slice(0, m.index).trim() ? 'plain' : 'deco', end);
  else if (m[5]) p.token('num', end);
  else p.word(m, end, wordClass);
  return null;
}

function paintScript(text, open, special = null) {
  const p = new LinePainter(text, JS_TOKEN, special);
  const resumed = resumeScript(p, open);
  return resumed || p.run((m, end) => scriptToken(p, m, end));
}

function resumeScript(p, open) {
  if (open === '*/') {
    const end = p.text.indexOf('*/');
    if (end < 0) return { parts: [el('span', { class: 's-comment' }, p.text)], close: open };
    p.token('comment', end + 2);
  } else if (open === '`') {
    const end = closingQuote(p.text, 0, '`');
    if (end < 0) return { parts: [el('span', { class: 's-str' }, p.text)], close: open };
    p.token('str', end);
  }
  return null;
}

function scriptToken(p, m, end) {
  if (m[1]) { p.token('comment', p.text.length); return STOP; }
  if (m[2]) return closeBlockComment(p, end);
  if (m[3]) return closeString(p, m[3], end, m[3] === '`' ? '`' : null);
  if (m[4]) p.token('deco', end);
  else if (m[5]) p.token('num', end);
  else p.word(m, end, scriptWordClass);
  return null;
}

function closeBlockComment(p, end) {
  const close = p.text.indexOf('*/', end);
  if (close < 0) return p.unclosed('comment', '*/');
  p.token('comment', close + 2);
  p.skipTo(close + 2);
  return null;
}

function closeString(p, quote, end, carried) {
  const close = closingQuote(p.text, end, quote);
  if (close < 0) return p.unclosed('str', carried);
  p.token('str', close);
  p.skipTo(close);
  return null;
}

function scriptWordClass(word, previousWord, text, end) {
  if (previousWord === 'function') return 'fn';
  if (['class', 'interface', 'type', 'enum', 'extends', 'implements', 'new'].includes(previousWord)) return 'type';
  if (JS_KEYWORDS.has(word)) return 'kw';
  if (word === 'true' || word === 'false') return 'bool';
  if (word === 'null' || word === 'undefined') return 'none';
  if (word === 'this' || word === 'super') return 'self';
  if (JS_TYPES.has(word)) return 'type';
  if (/^_*[A-Z][A-Z0-9_]+$/.test(word)) return 'const';
  if (/^_*[A-Z]\w*[a-z]\w*$/.test(word)) return 'type';
  if (/^\s*\(/.test(text.slice(end))) return JS_BUILTINS.has(word) ? 'builtin' : 'call';
  return 'plain';
}

function closingQuote(text, from, quote) {
  for (let i = from; i < text.length; i++) {
    if (text[i] === '\\') { i++; continue; }
    if (text.startsWith(quote, i)) return i + quote.length;
  }
  return -1;
}

function wordClass(word, previousWord, text, end) {
  if (previousWord === 'def') return 'fn';
  if (previousWord === 'class') return 'type';
  if (PY_KEYWORDS.has(word)) return 'kw';
  if (word === 'True' || word === 'False') return 'bool';
  if (word === 'None') return 'none';
  if (word === 'self' || word === 'cls') return 'self';
  if (PY_TYPES.has(word)) return 'type';
  if (/^_*[A-Z][A-Z0-9_]+$/.test(word)) return 'const';
  if (/^_*[A-Z]\w*[a-z]\w*$/.test(word)) return 'type';
  if (/^\s*\(/.test(text.slice(end))) return PY_BUILTINS.has(word) ? 'builtin' : 'call';
  return 'plain';
}
