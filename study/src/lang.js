// Limen SFD query language — lexer, parser and canonical printer (prototype core).
// Pure module: used unchanged by the browser app and by the Node verification.
//
// question  = "on" id duration { binding } "find" expr
//             { "where" expr } [ "group" "by" expr ]
//             { "measure" call } EOF ;
// binding   = "let" id "=" expr ;
// expr      = and_expr { "or" and_expr } ;
// and_expr  = unary { "and" unary } ;
// unary     = "not" unary | compare ;
// compare   = atom [ ( "=" | "!=" | "<" | "<=" | ">" | ">=" ) atom ] ;
// atom      = duration | number [ "%" ] | string | call | id
//           | "(" expr ")" | vector | choices ;
// call      = id "(" [ arg { "," arg } ] ")" ;
// arg       = id ":" expr | expr ;
// vector    = "[" expr { "," expr } "]" ;
// choices   = "{" expr "|" expr { "|" expr } "}" ;

export const GRAMMAR_EBNF = `question  = "on" id duration { binding } "find" expr
            { "where" expr } [ "group" "by" expr ]
            { "measure" call } EOF ;
binding   = "let" id "=" expr ;
expr      = and_expr { "or" and_expr } ;
and_expr  = unary { "and" unary } ;
unary     = "not" unary | compare ;
compare   = atom [ ( "=" | "!=" | "<" | "<=" | ">" | ">=" ) atom ] ;
atom      = duration | number [ "%" ] | string | call | id
          | "(" expr ")" | vector | choices ;
call      = id "(" [ arg { "," arg } ] ")" ;
arg       = id ":" expr | expr ;
vector    = "[" expr { "," expr } "]" ;
choices   = "{" expr "|" expr { "|" expr } "}" ;`;

export const LEXICAL_RULES = [
  'The lexer consumes the whole input; any character outside the token set is an error with its offset.',
  'Whitespace (space, tab, CR, LF) separates tokens. "--" starts a comment that runs to the end of the line.',
  'Reserved keywords (case-sensitive, lower-case): on let find where group by measure and or not.',
  'Identifiers begin with Unicode ID_Start or "_" and continue with ID_Continue or "_". Bindings and registered calls are case-sensitive. Composer pattern labels accept Unicode NFKC normalization, trimmed whitespace and lowercase matching.',
  'String: JSON double-quoted string (escapes \\" \\\\ \\/ \\b \\f \\n \\r \\t \\uXXXX; no raw control characters).',
  'Number: nonnegative decimal, digits with an optional ".digits" fraction; no sign, exponent or leading zeros.',
  'Duration: positive whole number immediately followed by m, h or d (elapsed UTC units: 1d = 24h).',
  'Percentage: a number followed by "%" (35% is the ratio 35/100). A plain number in a ratio slot is a ratio (0.35).',
  'Comparison operators: = != < <= > >=. Comparisons are non-associative (a = b = c is a syntax error).',
  'Punctuation: ( ) [ ] { } , : | %',
];

export const KEYWORDS = Object.freeze(['on', 'let', 'find', 'where', 'group', 'by', 'measure', 'and', 'or', 'not']);
const KW = new Set(KEYWORDS);
export const UNIT_MS = Object.freeze({ m: 60_000, h: 3_600_000, d: 86_400_000 });
const CLAUSE_KW = new Set(['on', 'let', 'find', 'where', 'group', 'measure']);
const PLANNED_CLAUSES = new Set(['simulate', 'holdout']);

export function diag(kind, message, start, end, hint, extra) {
  return Object.assign({ kind, message, start, end, hint: hint || null }, extra || {});
}

class Fail extends Error {
  constructor(d) { super(d.message); this.diag = d; }
}

const isIdStart = (c) => c === '_' || /^\p{ID_Start}$/u.test(c);
const isIdChar = (c) => c === '_' || /^\p{ID_Continue}$/u.test(c);
const isDigit = (c) => c >= '0' && c <= '9';

/** Tokenize the whole input. Throws Fail on the first lexical error. */
function lexAll(src) {
  const out = [];
  const n = src.length;
  let i = 0;
  const fail = (msg, s, e, hint) => { throw new Fail(diag('syntax', msg, s, e, hint)); };
  while (i < n) {
    const c = String.fromCodePoint(src.codePointAt(i));
    if (c === ' ' || c === '\n' || c === '\t' || c === '\r') { i++; continue; }
    if (c === '-' && src[i + 1] === '-') { while (i < n && src[i] !== '\n') i++; continue; }
    const start = i;
    if (isIdStart(c)) {
      i += c.length;
      while (i < n) {
        const next = String.fromCodePoint(src.codePointAt(i));
        if (!isIdChar(next)) break;
        i += next.length;
      }
      const v = src.slice(start, i);
      out.push({ t: KW.has(v) ? 'kw' : 'id', v, start, end: i });
      continue;
    }
    if (isDigit(c)) {
      while (i < n && isDigit(src[i])) i++;
      const intPart = src.slice(start, i);
      let frac = null;
      if (src[i] === '.') {
        if (!isDigit(src[i + 1] || '')) fail('a number needs digits after the decimal point (e.g. 0.35)', start, i + 1);
        i++;
        const fs = i;
        while (i < n && isDigit(src[i])) i++;
        frac = src.slice(fs, i);
      }
      let tokEnd = i;
      while (tokEnd < n && isIdChar(src[tokEnd])) tokEnd++;
      if (intPart.length > 1 && intPart[0] === '0') fail(`leading zeros are not allowed in "${src.slice(start, tokEnd)}"`, start, tokEnd);
      if (i < n && isIdStart(src[i])) {
        const us = i;
        while (i < n && isIdChar(src[i])) i++;
        const unit = src.slice(us, i);
        if (unit === 'm' || unit === 'h' || unit === 'd') {
          if (frac !== null) fail(`durations are whole numbers of m, h or d; "${src.slice(start, i)}" has a fraction`, start, i, 'write 90m instead of 1.5h');
          const amount = Number(intPart);
          if (amount === 0) fail('durations must be positive', start, i);
          const ms = amount * UNIT_MS[unit];
          if (!Number.isSafeInteger(ms)) fail('duration is too large', start, i);
          out.push({ t: 'dur', v: src.slice(start, i), amount, unit, ms, start, end: i });
          continue;
        }
        fail(`unknown duration unit "${unit}" in "${src.slice(start, i)}"; units are m, h, d (lower-case)`, start, i, 'e.g. 30m, 4h, 2d');
      }
      out.push({ t: 'num', v: src.slice(start, i), start, end: i });
      continue;
    }
    if (c === '"') {
      i++;
      for (;;) {
        if (i >= n) fail('unterminated string: add the closing "', start, n);
        const ch = src[i];
        if (ch === '"') { i++; break; }
        if (ch === '\n' || ch === '\r') fail('unterminated string: strings cannot span lines', start, i);
        if (ch < ' ') fail('raw control character in string; use a JSON escape', i, i + 1);
        if (ch === '\\') { i += 2; continue; }
        i++;
      }
      const raw = src.slice(start, i);
      let value;
      try { value = JSON.parse(raw); } catch {
        fail('invalid escape in string; allowed JSON escapes: \\" \\\\ \\/ \\b \\f \\n \\r \\t \\uXXXX', start, i);
      }
      out.push({ t: 'str', v: value, raw, start, end: i });
      continue;
    }
    if (c === '!') {
      if (src[i + 1] === '=') { out.push({ t: 'op', v: '!=', start, end: i + 2 }); i += 2; continue; }
      fail('unexpected "!"; use != for "not equal" or the keyword not', start, i + 1);
    }
    if (c === '<' || c === '>') {
      if (src[i + 1] === '=') { out.push({ t: 'op', v: c + '=', start, end: i + 2 }); i += 2; continue; }
      out.push({ t: 'op', v: c, start, end: i + 1 }); i++; continue;
    }
    if (c === '=') {
      if (src[i + 1] === '=') fail('use a single = for equality', start, i + 2);
      out.push({ t: 'op', v: '=', start, end: i + 1 }); i++; continue;
    }
    if ('()[]{},:|%'.includes(c)) { out.push({ t: 'p', v: c, start, end: i + 1 }); i++; continue; }
    if (c === '-') fail('unexpected "-": numbers are nonnegative and comments start with --', start, i + 1);
    if (c === '\'') fail('strings use double quotes ("…")', start, i + 1);
    const cp = src.codePointAt(i);
    fail(`unexpected character ${JSON.stringify(String.fromCodePoint(cp))} (U+${cp.toString(16).toUpperCase().padStart(4, '0')})`, start, i + (cp > 0xffff ? 2 : 1));
  }
  out.push({ t: 'eof', v: '', start: n, end: n });
  return out;
}

export function tokenize(src) {
  try { return { tokens: lexAll(src), error: null }; } catch (e) { if (e instanceof Fail) return { tokens: null, error: e.diag }; throw e; }
}

/** Tolerant lexing for editor assistance: tokens up to the first error. */
export function tokenizePrefix(src) {
  const r = tokenize(src);
  if (!r.error) return r.tokens;
  const ok = tokenize(src.slice(0, r.error.start));
  return ok.tokens || [];
}

export function describeToken(t) {
  switch (t.t) {
    case 'eof': return 'end of input';
    case 'kw': return `keyword '${t.v}'`;
    case 'id': return `name ${t.v}`;
    case 'str': return `string ${t.raw}`;
    case 'num': return `number ${t.v}`;
    case 'dur': return `duration ${t.v}`;
    default: return `'${t.v}'`;
  }
}

class Parser {
  constructor(src, toks) { this.src = src; this.toks = toks; this.k = 0; }
  get tok() { return this.toks[this.k]; }
  peek(o = 1) { return this.toks[Math.min(this.k + o, this.toks.length - 1)]; }
  next() { const t = this.toks[this.k]; if (t.t !== 'eof') this.k++; return t; }
  isKw(v) { return this.tok.t === 'kw' && this.tok.v === v; }
  isP(v) { return this.tok.t === 'p' && this.tok.v === v; }
  fail(msg, tok = this.tok, hint) { throw new Fail(diag('syntax', msg, tok.start, tok.end, hint)); }
  expectP(v, context) {
    if (!this.isP(v)) this.fail(`expected '${v}'${context ? ' ' + context : ''} but found ${describeToken(this.tok)}`);
    return this.next();
  }

  clauseFail(expected, expectedText) {
    const t = this.tok;
    const order = 'clauses go in order: on, let, find, where, group by, measure';
    const want = expectedText || `'${expected}'`;
    if (t.t === 'id' && PLANNED_CLAUSES.has(t.v)) {
      this.fail(`'${t.v}' is not a clause in this prototype`, t,
        `${t.v} is a planned design example (simulation ledger / chronological holdout); this prototype is an observed-return study`);
    }
    if (expected === null) {
      if (t.t === 'kw' && CLAUSE_KW.has(t.v)) this.fail(`'${t.v}' cannot follow the measure clauses; ${order}`, t);
      this.fail(`unexpected ${describeToken(t)} after the last measure clause; only further 'measure' clauses may follow`, t);
    }
    if (t.t === 'kw' && CLAUSE_KW.has(t.v)) this.fail(`expected ${want} but found '${t.v}'; ${order}`, t);
    this.fail(`expected ${want} but found ${describeToken(t)}`, t);
  }

  question() {
    const start = this.tok.start;
    if (!this.isKw('on')) this.fail(`a question starts with "on <instrument> <bar size>", e.g. on BTCUSDT 15m; found ${describeToken(this.tok)}`);
    this.next();
    const inst = this.tok;
    if (inst.t !== 'id') this.fail(`expected an instrument name after 'on' (e.g. BTCUSDT) but found ${describeToken(inst)}`);
    this.next();
    const bar = this.tok;
    if (bar.t !== 'dur') this.fail(`expected a bar size after ${inst.v} (e.g. 15m) but found ${describeToken(bar)}`);
    this.next();
    const lets = [];
    while (this.isKw('let')) lets.push(this.binding());
    if (!this.isKw('find')) this.clauseFail('find', "'let' or 'find'");
    this.next();
    const find = this.expr();
    const wheres = [];
    while (this.isKw('where')) { this.next(); wheres.push(this.expr()); }
    let group = null;
    if (this.isKw('group')) {
      this.next();
      if (!this.isKw('by')) this.fail(`expected 'by' after 'group' but found ${describeToken(this.tok)}`);
      this.next();
      group = this.expr();
    }
    if (this.tok.t !== 'eof' && !this.isKw('measure')) this.clauseFail('measure', group ? "'measure'" : "'where', 'group by' or 'measure'");
    const measures = [];
    while (this.isKw('measure')) {
      this.next();
      if (!(this.tok.t === 'id' && this.peek().t === 'p' && this.peek().v === '(')) {
        this.fail(`expected a call after 'measure', e.g. close_return(after: [1h, 4h]); found ${describeToken(this.tok)}`);
      }
      measures.push(this.call());
    }
    if (this.tok.t !== 'eof') this.clauseFail(null);
    const end = (measures.at(-1) || group || wheres.at(-1) || find).end;
    return {
      k: 'question',
      on: {
        instrument: { name: inst.v, start: inst.start, end: inst.end },
        bar: { k: 'dur', text: bar.v, amount: bar.amount, unit: bar.unit, ms: bar.ms, start: bar.start, end: bar.end },
      },
      lets, find, wheres, group, measures, start, end,
    };
  }

  binding() {
    const kw = this.next();
    const nameTok = this.tok;
    if (nameTok.t === 'kw') this.fail(`'${nameTok.v}' is a reserved keyword and cannot be a binding name`);
    if (nameTok.t !== 'id') this.fail(`expected a name after 'let' but found ${describeToken(nameTok)}`);
    this.next();
    if (!(this.tok.t === 'op' && this.tok.v === '=')) this.fail(`expected '=' after let ${nameTok.v} but found ${describeToken(this.tok)}`);
    this.next();
    const value = this.expr();
    return { k: 'let', name: nameTok.v, nameStart: nameTok.start, nameEnd: nameTok.end, value, start: kw.start, end: value.end };
  }

  expr() {
    const first = this.andExpr();
    if (!this.isKw('or')) return first;
    const items = [first];
    while (this.isKw('or')) { this.next(); items.push(this.andExpr()); }
    return { k: 'or', items, start: first.start, end: items[items.length - 1].end };
  }

  andExpr() {
    const first = this.unary();
    if (!this.isKw('and')) return first;
    const items = [first];
    while (this.isKw('and')) { this.next(); items.push(this.unary()); }
    return { k: 'and', items, start: first.start, end: items[items.length - 1].end };
  }

  unary() {
    if (this.isKw('not')) {
      const t = this.next();
      const item = this.unary();
      return { k: 'not', item, start: t.start, end: item.end };
    }
    return this.compare();
  }

  compare() {
    const left = this.atom();
    if (this.tok.t !== 'op') return left;
    const op = this.next();
    const right = this.atom();
    if (this.tok.t === 'op') {
      this.fail(`comparisons do not chain: "${op.v} … ${this.tok.v}" needs parentheses or 'and'`, this.tok);
    }
    return { k: 'cmp', op: op.v, left, right, opStart: op.start, opEnd: op.end, start: left.start, end: right.end };
  }

  atom() {
    const t = this.tok;
    switch (t.t) {
      case 'dur':
        this.next();
        return { k: 'dur', text: t.v, amount: t.amount, unit: t.unit, ms: t.ms, start: t.start, end: t.end };
      case 'num': {
        this.next();
        if (this.isP('%')) { const p = this.next(); return { k: 'pct', text: t.v, start: t.start, end: p.end }; }
        return { k: 'num', text: t.v, start: t.start, end: t.end };
      }
      case 'str':
        this.next();
        return { k: 'str', value: t.v, start: t.start, end: t.end };
      case 'id':
        if (this.peek().t === 'p' && this.peek().v === '(') return this.call();
        this.next();
        return { k: 'id', name: t.v, start: t.start, end: t.end };
      case 'p':
        if (t.v === '(') {
          this.next();
          const e = this.expr();
          this.expectP(')', 'to close the parenthesis');
          return e;
        }
        if (t.v === '[') return this.vector();
        if (t.v === '{') return this.choices();
        break;
      case 'kw':
        if (t.v === 'not') break;
        this.fail(`expected a value but found keyword '${t.v}'`, t);
        break;
      default: break;
    }
    this.fail(`expected a value (duration, number, string, name, call, (…), […] or {…|…}) but found ${describeToken(t)}`, t);
    return null;
  }

  vector() {
    const open = this.next();
    if (this.isP(']')) this.fail('a vector needs at least one value, e.g. [1h, 4h]');
    const items = [this.expr()];
    while (this.isP(',')) { this.next(); items.push(this.expr()); }
    const close = this.expectP(']', 'to close the vector');
    return { k: 'vec', items, start: open.start, end: close.end };
  }

  choices() {
    const open = this.next();
    const items = [this.expr()];
    if (!this.isP('|')) {
      if (this.isP('}')) this.fail('choices need at least two values separated by |, e.g. {30m | 1h}');
      this.fail(`expected '|' between choices but found ${describeToken(this.tok)}`);
    }
    while (this.isP('|')) { this.next(); items.push(this.expr()); }
    const close = this.expectP('}', 'to close the choices');
    return { k: 'choices', items, start: open.start, end: close.end };
  }

  call() {
    const nameTok = this.next();
    this.next(); // '('
    const args = [];
    if (!this.isP(')')) {
      for (;;) {
        const a = this.arg();
        if (a.name === null && args.length > 0) {
          throw new Fail(diag('syntax', `only the first argument of ${nameTok.v} may be positional; name this argument (key: value)`, a.start, a.end));
        }
        args.push(a);
        if (this.isP(',')) { this.next(); continue; }
        if (this.isP(')')) break;
        this.fail(`expected ',' or ')' in the arguments of ${nameTok.v} but found ${describeToken(this.tok)}`);
      }
    }
    const close = this.expectP(')', `to close ${nameTok.v}(`);
    return { k: 'call', name: nameTok.v, nameStart: nameTok.start, nameEnd: nameTok.end, args, start: nameTok.start, end: close.end };
  }

  arg() {
    const t = this.tok;
    if (t.t === 'id' && this.peek().t === 'p' && this.peek().v === ':') {
      this.next(); this.next();
      const value = this.expr();
      return { name: t.v, nameStart: t.start, nameEnd: t.end, value, start: t.start, end: value.end };
    }
    const value = this.expr();
    return { name: null, nameStart: null, nameEnd: null, value, start: value.start, end: value.end };
  }
}

/** Parse a whole question. Returns { ast, error }. */
export function parse(src) {
  try {
    const toks = lexAll(src);
    const ast = new Parser(src, toks).question();
    return { ast, error: null };
  } catch (e) {
    if (e instanceof Fail) return { ast: null, error: e.diag };
    throw e;
  }
}

/** Parse a standalone expression (used for registry composition bodies). */
export function parseExpression(src) {
  try {
    const toks = lexAll(src);
    const p = new Parser(src, toks);
    const e = p.expr();
    if (p.tok.t !== 'eof') p.fail(`unexpected ${describeToken(p.tok)} after the expression`);
    return { ast: e, error: null };
  } catch (e) {
    if (e instanceof Fail) return { ast: null, error: e.diag };
    throw e;
  }
}

/** Parse one scalar literal (guided-editor input). Returns { node, error }. */
export function parseLiteral(src) {
  const r = parseExpression(src.trim());
  if (r.error) return { node: null, error: r.error.message };
  const k = r.ast.k;
  if (!['dur', 'num', 'pct', 'str', 'id'].includes(k)) return { node: null, error: 'enter a single value such as 30m, 35% or 0.35' };
  return { node: stripSpans(r.ast), error: null };
}

// ---------------------------------------------------------------- printer

export function printQuestion(q) {
  const lines = [`on ${q.on.instrument.name} ${q.on.bar.text}`];
  for (const b of q.lets) lines.push(`let ${b.name} = ${printExpr(b.value)}`);
  lines.push(`find ${printExpr(q.find)}`);
  for (const w of q.wheres) lines.push(`where ${printExpr(w)}`);
  if (q.group) lines.push(`group by ${printExpr(q.group)}`);
  for (const m of q.measures) lines.push(`measure ${printExpr(m)}`);
  return lines.join('\n');
}

export function printExpr(e, ctx = 0) {
  let s;
  let p;
  switch (e.k) {
    case 'or': p = 1; s = e.items.map((x) => printExpr(x, 2)).join(' or '); break;
    case 'and': p = 2; s = e.items.map((x) => printExpr(x, 3)).join(' and '); break;
    case 'not': p = 3; s = 'not ' + printExpr(e.item, 3); break;
    case 'cmp': p = 4; s = `${printExpr(e.left, 5)} ${e.op} ${printExpr(e.right, 5)}`; break;
    default: p = 5; s = printAtom(e);
  }
  return p < ctx ? `(${s})` : s;
}

function printAtom(e) {
  switch (e.k) {
    case 'dur': return e.text;
    case 'num': return e.text;
    case 'pct': return e.text + '%';
    case 'str': return JSON.stringify(e.value);
    case 'id': return e.name;
    case 'call': return `${e.name}(${e.args.map((a) => (a.name ? `${a.name}: ${printExpr(a.value)}` : printExpr(a.value))).join(', ')})`;
    case 'vec': return `[${e.items.map((x) => printExpr(x)).join(', ')}]`;
    case 'choices': return `{${e.items.map((x) => printExpr(x)).join(' | ')}}`;
    default: throw new Error('cannot print node ' + e.k);
  }
}

// ---------------------------------------------------------------- AST helpers

const SPAN_KEYS = new Set(['start', 'end', 'nameStart', 'nameEnd', 'opStart', 'opEnd']);

export function stripSpans(x) {
  if (Array.isArray(x)) return x.map(stripSpans);
  if (x && typeof x === 'object') {
    const o = {};
    for (const [k, v] of Object.entries(x)) if (!SPAN_KEYS.has(k)) o[k] = stripSpans(v);
    return o;
  }
  return x;
}

export function sameStructure(a, b) {
  return JSON.stringify(stripSpans(a)) === JSON.stringify(stripSpans(b));
}

export function getAt(root, path) {
  let x = root;
  for (const k of path) x = x[k];
  return x;
}

/** Immutable update: returns a copy of root with the value at path replaced. */
export function setAt(root, path, value) {
  if (path.length === 0) return value;
  const [k, ...rest] = path;
  const copy = Array.isArray(root) ? root.slice() : { ...root };
  copy[k] = setAt(root[k], rest, value);
  return copy;
}

/** Remove an element from an array located at path (immutable). */
export function removeAt(root, path) {
  const parentPath = path.slice(0, -1);
  const idx = path[path.length - 1];
  const arr = getAt(root, parentPath).slice();
  arr.splice(idx, 1);
  return setAt(root, parentPath, arr);
}

export function lineCol(src, offset) {
  let line = 1;
  let col = 1;
  for (let i = 0; i < offset && i < src.length; i++) {
    if (src[i] === '\n') { line++; col = 1; } else col++;
  }
  return { line, col };
}

export function durNode(text) {
  const m = /^([1-9][0-9]*)([mhd])$/.exec(text);
  if (!m) throw new Error('bad duration text ' + text);
  const amount = Number(m[1]);
  return { k: 'dur', text, amount, unit: m[2], ms: amount * UNIT_MS[m[2]] };
}

/** Canonical duration text for an exact millisecond count (largest exact unit). */
export function msToText(ms) {
  if (ms % UNIT_MS.d === 0) return `${ms / UNIT_MS.d}d`;
  if (ms % UNIT_MS.h === 0) return `${ms / UNIT_MS.h}h`;
  if (ms % UNIT_MS.m === 0) return `${ms / UNIT_MS.m}m`;
  return `${ms}ms`;
}

/** Human elapsed text, e.g. 49h15m. */
export function elapsedText(ms) {
  if (ms === 0) return '0m';
  const h = Math.floor(ms / UNIT_MS.h);
  const m = Math.round((ms - h * UNIT_MS.h) / UNIT_MS.m);
  return (h ? `${h}h` : '') + (m ? `${m}m` : '');
}
