const PY_KEYWORDS = new Set('and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield'.split(' '));
const PY_BUILTINS = new Set('abs all any bool bytes callable chr dict dir divmod enumerate filter float format frozenset getattr hasattr hash id input int isinstance issubclass iter len list map max min next object open ord pow print property range repr reversed round set setattr slice sorted staticmethod classmethod str sum super tuple type vars zip'.split(' '));
const PY_TYPES = new Set('bool bytes complex dict float frozenset int list object set str tuple type'.split(' '));
const PY_TOKEN = /(#.*)|([rRbBuUfF]{0,2})("""|'''|"|')|(@[A-Za-z_][\w.]*)|(\b0[xXoObB][\da-fA-F_]+\b|\b\d[\d_]*(?:\.[\d_]*)?(?:[eE][+-]?\d+)?j?\b|\.\d[\d_]*(?:[eE][+-]?\d+)?j?\b)|([A-Za-z_]\w*)/g;

function pythonPainter(special = null) {
  let open = null;
  let last = null;
  return (text, no) => {
    if (no == null || last == null || no !== last + 1) open = null;
    last = no == null ? null : no;
    const { parts, close } = paintPython(text, open, special);
    open = close;
    return parts;
  };
}

function paintPython(text, open, special = null) {
  const parts = [];
  const plainUpTo = (end) => { if (end > at) parts.push(text.slice(at, end)); };
  const token = (cls, end) => { const piece = text.slice(at, end); parts.push(cls === 'plain' ? piece : el('span', { class: `s-${cls}` }, piece)); at = end; };
  let at = 0;
  if (open) {
    const end = text.indexOf(open, 0);
    if (end < 0) return { parts: [el('span', { class: 's-str' }, text)], close: open };
    token('str', end + 3);
  }
  let previousWord = null;
  PY_TOKEN.lastIndex = at;
  for (let m = PY_TOKEN.exec(text); m; m = PY_TOKEN.exec(text)) {
    plainUpTo(m.index);
    at = m.index;
    const end = m.index + m[0].length;
    if (m[1]) { token('comment', end); break; }
    if (m[3]) {
      const quote = m[3];
      const close = closingQuote(text, end, quote);
      if (close < 0) {
        token('str', text.length);
        return { parts, close: quote.length === 3 ? quote : null };
      }
      token('str', close);
      PY_TOKEN.lastIndex = close;
      previousWord = null;
      continue;
    }
    if (m[4]) { token(text.slice(0, m.index).trim() ? 'plain' : 'deco', end); continue; }
    if (m[5]) { token('num', end); continue; }
    const hit = special && special(text, m.index);
    if (hit) {
      parts.push(hit.node);
      at = hit.end;
      PY_TOKEN.lastIndex = hit.end;
      previousWord = null;
      continue;
    }
    const word = m[6];
    token(wordClass(word, previousWord, text, end), end);
    previousWord = word;
  }
  plainUpTo(text.length);
  return { parts: parts.length ? parts : [text], close: null };
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
