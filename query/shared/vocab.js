// The trader vocabulary: plain-English clauses with typed slots, each mapped to exact Filang text.
// All three directions edit this one model and print the same query.
import { parse, printExpr } from '/study/src/lang.js';
import { CANDLE_PATTERNS } from '/study/src/registry.js';
import { pinnedExpression } from '/study/composer/drawing.js';

export const PATTERNS = CANDLE_PATTERNS.patterns.map((p) => ({
  id: p.id.replaceAll('-', '_'), name: p.name, ja: p.ja, bars: p.bars, rule: p.rule, aliases: p.aliases || [],
}));
const patternById = new Map(PATTERNS.map((p) => [p.id, p]));

const opt = (key, kind, options, extra = {}) => ({ key, kind, options, sweep: true, ...extra });
const DAY = { mon: 'Monday', tue: 'Tuesday', wed: 'Wednesday', thu: 'Thursday', fri: 'Friday', closed: 'a non-session day' };
const POINT = { open: 'open', high: 'high', low: 'low', close: 'close' };
const PART = { lower_wick: 'lower wick', upper_wick: 'upper wick', body: 'body' };
const REL = { above: 'above', at_or_above: 'at or above', below: 'below', at_or_below: 'at or below' };
const BACK = { 1: 'one candle back', 2: 'two candles back', 3: 'three candles back', 4: 'four candles back' };
const WITHIN = { 0: 'on the same candle', 3: 'one to three candles later', 8: 'one to eight candles later' };
const PCT10 = ['10%', '20%', '30%', '40%', '50%', '60%', '70%', '80%', '90%'];

const S = {
  pattern: { key: 'p', kind: 'pattern', options: PATTERNS.map((p) => p.id), sweep: false,
    labels: Object.fromEntries(PATTERNS.map((p) => [p.id, (/^[aeiou]/i.test(p.name) ? 'an ' : 'a ') + p.name.toLowerCase()])) },
  over: (def) => opt('over', 'dur', ['1h', '2h', '4h', '8h', '12h', '24h', '48h'], { def }),
  side: opt('side', 'enum', ['low', 'high'], { labels: { low: 'low', high: 'high' }, sweep: false }),
};

// role: event → usable in find and where. cond → where only. cat → where, and usable as a split.
export const CLAUSES = {
  pattern: {
    role: 'event', group: 'Shape', title: 'Named candle', def: null,
    slots: [S.pattern], defaults: { p: 'hammer' },
    phrase: ['the candle is ', '$p'],
    text: (a) => a.p,
    keywords: 'pattern shape named candle ' + PATTERNS.map((p) => p.name + ' ' + p.ja).join(' '),
  },
  reclaim: {
    role: 'event', group: 'Level', title: 'Prior range reclaim', def: 'breach_reclaim',
    slots: [S.over('4h'), S.side, opt('within', 'enum', ['0', '3', '8'], { labels: WITHIN, sweep: false })],
    defaults: { over: '4h', side: 'low', within: '0' },
    phrase: ['price pierces the prior ', '$over', ' ', '$side', ' and closes back inside ', '$within'],
    text: (a) => `breach_reclaim(prior_${a.side}(over: ${a.over})${a.within === '0' ? '' : `, within_min: 1, within_max: ${a.within}`})`,
    keywords: 'reclaim sweep failed break stop run liquidity prior low high level',
  },
  breakout: {
    role: 'event', group: 'Level', title: 'Channel breakout', def: 'channel_breakout',
    slots: [S.over('12h')], defaults: { over: '12h' },
    phrase: ['the close breaks above the prior ', '$over', ' high'],
    text: (a) => `channel_breakout(over: ${a.over})`,
    keywords: 'breakout channel new high close above range',
  },
  relation: {
    role: 'event', group: 'Level', title: 'Compare candle prices', def: 'candle_relation',
    slots: [opt('a', 'enum', Object.keys(POINT), { labels: POINT }), opt('rel', 'enum', Object.keys(REL), { labels: REL }),
      opt('b', 'enum', Object.keys(POINT), { labels: POINT }), opt('back', 'enum', ['1', '2', '3', '4'], { labels: BACK })],
    defaults: { a: 'close', rel: 'above', b: 'high', back: '1' },
    phrase: ['the ', '$a', ' is ', '$rel', ' the ', '$b', ' of ', '$back'],
    text: (a) => `candle_relation(price(${a.a}), is: ${a.rel}, right: price(${a.b}, bars_ago: ${a.back}))`,
    keywords: 'compare close open high low previous candle above below relationship',
  },
  wickrej: {
    role: 'event', group: 'Shape', title: 'Wick rejection', def: 'wick_rejection',
    slots: [opt('body', 'pct', ['15%', '25%', '35%', '45%']), opt('wick', 'pct', ['35%', '45%', '55%', '65%'])],
    defaults: { body: '35%', wick: '45%' },
    phrase: ['a wick rejection forms, with the body at most ', '$body', ' and the lower wick at least ', '$wick', ' of the range'],
    text: (a) => `wick_rejection(body_max: ${a.body}, wick_min: ${a.wick})`,
    keywords: 'wick rejection pin bar long tail',
  },
  share: {
    role: 'cond', group: 'Anatomy', title: 'Wick or body share, at least', def: 'candle_share',
    slots: [opt('part', 'enum', Object.keys(PART), { labels: PART }), opt('min', 'pct', PCT10)],
    defaults: { part: 'lower_wick', min: '50%' },
    phrase: ['the ', '$part', ' is at least ', '$min', ' of the range'],
    text: (a) => `candle_share(${a.part}, min: ${a.min})`,
    keywords: 'wick body share long tail size anatomy',
  },
  sharemax: {
    role: 'cond', group: 'Anatomy', title: 'Wick or body share, at most', def: 'candle_share',
    slots: [opt('part', 'enum', Object.keys(PART), { labels: PART }), opt('max', 'pct', PCT10)],
    defaults: { part: 'body', max: '20%' },
    phrase: ['the ', '$part', ' is at most ', '$max', ' of the range'],
    text: (a) => `candle_share(${a.part}, min: 0%, max: ${a.max})`,
    keywords: 'small body short wick share anatomy',
  },
  rangex: {
    role: 'cond', group: 'Anatomy', title: 'Range versus recent median', def: 'range_multiple',
    slots: [opt('min', 'num', ['1.25', '1.5', '2', '2.5', '3']), S.over('4h')],
    defaults: { min: '1.5', over: '4h' },
    phrase: ['the range is at least ', '$min', ' × the prior ', '$over', ' median'],
    text: (a) => `range_multiple(over: ${a.over}, min: ${a.min})`,
    keywords: 'range wide big candle expansion volatility median',
  },
  near: {
    role: 'cond', group: 'Level', title: 'Close near a level', def: 'near_level',
    slots: [opt('within', 'pct', ['0.1%', '0.25%', '0.5%', '1%']), S.over('4h'), S.side],
    defaults: { within: '0.25%', over: '4h', side: 'high' },
    phrase: ['the close is within ', '$within', ' of the prior ', '$over', ' ', '$side'],
    text: (a) => `near_level(prior_${a.side}(over: ${a.over}), point: price(close), within: ${a.within})`,
    keywords: 'near level close to high low distance',
  },
  weekday: {
    role: 'cat', group: 'Calendar', title: 'Session day', def: 'weekday',
    slots: [opt('day', 'enum', Object.keys(DAY), { labels: DAY })], defaults: { day: 'fri' },
    phrase: ['the New York day is ', '$day'], notPhrase: ['the New York day is not ', '$day'],
    text: (a, not) => `weekday(nyse_regular) ${not ? '!=' : '='} ${a.day}`,
    splitText: () => 'weekday(nyse_regular)', splitLabel: 'New York session day',
    keywords: 'weekday day monday tuesday wednesday thursday friday weekend session calendar',
  },
  tail: {
    role: 'cond', group: 'Calendar', title: 'Session tail', def: 'session_tail',
    slots: [opt('last', 'dur', ['15m', '30m', '1h', '2h'])], defaults: { last: '1h' },
    phrase: ['the close falls in the last ', '$last', ' of the NYSE session'],
    notPhrase: ['the close falls outside the last ', '$last', ' of the NYSE session'],
    text: (a) => `session_tail(nyse_regular, last: ${a.last})`,
    keywords: 'session close end of day last hour nyse tail',
  },
  trend: {
    role: 'cat', group: 'Context', title: 'Higher-timeframe trend', def: 'completed_trend',
    slots: [opt('frame', 'dur', ['1h', '4h', '1d']), opt('dir', 'enum', ['up', 'down'], { labels: { up: 'up', down: 'down', flat: 'flat' } })],
    defaults: { frame: '4h', dir: 'up' },
    phrase: ['the last completed ', '$frame', ' bar is ', '$dir'], notPhrase: ['the last completed ', '$frame', ' bar is not ', '$dir'],
    text: (a, not) => `completed_trend(frame: ${a.frame}) ${not ? '!=' : '='} ${a.dir}`,
    splitText: (a) => `completed_trend(frame: ${a.frame})`, splitLabel: 'direction of the last completed bar',
    keywords: 'trend higher timeframe up down direction 4h daily',
  },
  quiet: {
    role: 'cond', group: 'Context', title: 'Quiet range held', def: 'held',
    slots: [opt('width', 'pct', ['1%', '1.5%', '2%', '2.5%', '3%', '4%']), opt('for', 'dur', ['4h', '12h', '24h', '48h', '72h'])],
    defaults: { width: '2.5%', for: '24h' },
    phrase: ['a 4h range at most ', '$width', ' wide has held for ', '$for'],
    text: (a) => `held(quiet_range(width_max: ${a.width}), for: ${a.for})`,
    keywords: 'quiet range consolidation compression tight calm held',
  },
  // A shape drawn in Composer. It holds the engine's drawing packet when one came with it, or the g1 alone, and is
  // asked one of three ways. The shape: a drawn shape is a chain, every later bar opening where the previous one
  // closed, so the recording is read the same way (chained_g1). The shape as recorded: later opens as the recording
  // has them (exact_g1), which is what an older link or a typed exact_g1 means. Or the relations held on fixed candles.
  drawing: {
    role: 'event', group: 'Shape', title: 'Drawn shape', def: 'chained_g1',
    slots: [], defaults: { g1: '', packet: null, held: false, recorded: false }, phrase: [],
    text: (a) => {
      const held = a.held && a.packet && pinnedExpression(a.packet);
      if (held) return held;
      const r = Array.isArray(a.radius) ? lit(a.radius) : Number(a.radius) || 0;
      return `${a.recorded ? 'exact_g1' : 'chained_g1'}(${JSON.stringify(a.g1)}${r ? `, radius: ${r}` : ''})`;
    },
    keywords: '',
  },
  raw: {
    role: 'cond', group: 'Formal', title: 'Formal expression', def: null,
    slots: [], defaults: { text: '' }, phrase: ['$text'],
    text: (a) => a.text,
    keywords: '',
  },
};

export const HORIZONS = ['15m', '30m', '1h', '2h', '4h', '8h', '24h'];

// ---------------------------------------------------------------- model helpers

export const make = (type, args = {}) => ({ type, args: { ...CLAUSES[type].defaults, ...args } });
export const clone = (m) => JSON.parse(JSON.stringify(m));
/** Bars in a drawn shape: the packet's, or the g1's own count. */
export const drawingBars = (c) => (c.args.packet ? c.args.packet.bars.length : c.args.g1.slice(5).split(';').length);
/** Whether a drawn shape is asked as its held relations, which needs a packet that holds some. */
export const drawingHeld = (c) => !!(c.args.held && c.args.packet && pinnedExpression(c.args.packet));
/** Whether a drawn shape is asked with its opens as recorded. A one-bar shape has no later open, so the two readings agree. */
export const drawingRecorded = (c) => !drawingHeld(c) && !!c.args.recorded && drawingBars(c) > 1;
const drawingPhrase = (c) => { const n = drawingBars(c); return `${drawingHeld(c) ? 'relations held on ' : ''}a drawn shape of ${n} ${n === 1 ? 'bar' : 'bars'}${drawingRecorded(c) ? ', opens as recorded' : ''}`; };
const lit = (v) => (Array.isArray(v) ? (v.length > 1 ? `{${v.join(' | ')}}` : v[0]) : v);
const wrap = (t) => (/ (or|and) /.test(t) ? `(${t})` : t);

export function clauseText(c) {
  const def = CLAUSES[c.type];
  const args = Object.fromEntries(Object.entries(c.args).map(([k, v]) => [k, lit(v)]));
  if (c.type === 'raw') return c.not ? `not (${args.text})` : args.text;
  if (c.type === 'drawing') return c.not ? `not (${def.text(c.args)})` : def.text(c.args);
  if (def.role === 'cat') return def.text(args, c.not);
  const t = def.text(args);
  return c.not ? `not ${t}` : t;
}

export function splitText(c) {
  const def = CLAUSES[c.type];
  const args = Object.fromEntries(Object.entries(c.args).map(([k, v]) => [k, lit(v)]));
  return def.splitText ? def.splitText(args) : def.text(args);
}

export function bodyText(m, { upTo = Infinity, without = -1 } = {}) {
  const lines = ['find ' + m.find.items.map((c) => wrap(clauseText(c))).join(` ${m.find.join} `)];
  m.wheres.forEach((c, i) => { if (!c.off && i < upTo && i !== without) lines.push('where ' + clauseText(c)); });
  if (m.split) lines.push('group by ' + splitText(m.split));
  if (m.horizons.length) lines.push(`measure close_return(after: ${m.horizons.length > 1 ? '[' + m.horizons.join(', ') + ']' : m.horizons[0]})`);
  return lines.join('\n');
}
export const toText = (m, o) => 'on BTCUSDT 15m\n' + bodyText(m, o);

export function slotLabel(slot, v) {
  if (Array.isArray(v)) return v.map((x) => slotLabel(slot, x)).join(' | ');
  return slot.labels?.[v] ?? v;
}

/** Phrase as parts: strings and { slot, value } entries. */
export function phraseParts(c) {
  const def = CLAUSES[c.type];
  if (c.type === 'raw') return [(c.not ? 'not ' : '') + c.args.text];
  if (c.type === 'drawing') return [(c.not ? 'not ' : '') + drawingPhrase(c)];
  const tpl = c.not && def.notPhrase ? def.notPhrase : def.phrase;
  const parts = c.not && !def.notPhrase ? ['it is not the case that '] : [];
  for (const p of tpl) {
    if (p[0] === '$') { const slot = def.slots.find((s) => s.key === p.slice(1)); parts.push({ slot, value: c.args[slot.key] }); } else parts.push(p);
  }
  return parts;
}
export const phraseText = (c) => phraseParts(c).map((p) => (typeof p === 'string' ? p : slotLabel(p.slot, p.value))).join('');
export const splitLabel = (c) => (CLAUSES[c.type].splitLabel ? (c.type === 'trend' ? `${c.args.frame} trend` : 'session day') : 'whether ' + phraseText(c));

/** Step a slot value along its ladder. Returns the same value at either end. */
export function step(slot, v, dir) {
  if (Array.isArray(v)) return v;
  const i = slot.options.indexOf(v);
  if (i < 0) return slot.options[dir > 0 ? 0 : slot.options.length - 1];
  return slot.options[Math.max(0, Math.min(slot.options.length - 1, i + dir))];
}

// ---------------------------------------------------------------- Filang text → model

function fromExpr(node, lets) {
  const val = (n) => {
    if (!n) return null;
    if (n.k === 'id' && lets.has(n.name)) return val(lets.get(n.name));
    if (n.k === 'choices') { const xs = n.items.map(val); return xs.every((x) => typeof x === 'string') ? xs : null; }
    if (n.k === 'dur' || n.k === 'num') return n.text;
    if (n.k === 'pct') return n.text + '%';
    if (n.k === 'id') return n.name;
    return null;
  };
  const arg = (call, name, pos) => call.args.find((a) => a.name === name)?.value ?? (pos !== undefined ? call.args.filter((a) => a.name === null)[pos]?.value : undefined);
  const raw = () => ({ type: 'raw', args: { text: printExpr(node) } });
  const ok = (type, args) => (Object.values(args).every((v) => v !== null && v !== undefined) ? { type, args } : raw());
  const prior = (n) => (n?.k === 'call' && /^prior_(low|high)$/.test(n.name) ? { side: n.name.slice(6), over: val(arg(n, 'over')) ?? '4h' } : null);

  if (node.k === 'not') { const inner = fromExpr(node.item, lets); return inner.not ? raw() : { ...inner, not: true }; }
  if (node.k === 'id' && patternById.has(node.name)) return { type: 'pattern', args: { p: node.name } };
  if (node.k === 'str') {
    if (node.value === 'Wick rejection') return make('wickrej');
    const hit = CANDLE_PATTERNS.resolve?.(node.value);
    if (hit) return { type: 'pattern', args: { p: hit.id.replaceAll('-', '_') } };
    return raw();
  }
  if (node.k === 'cmp' && (node.op === '=' || node.op === '!=') && node.left.k === 'call') {
    const not = node.op === '!=';
    if (node.left.name === 'weekday') return { ...ok('weekday', { day: val(node.right) }), ...(not ? { not } : {}) };
    if (node.left.name === 'completed_trend') return { ...ok('trend', { frame: val(arg(node.left, 'frame')), dir: val(node.right) }), ...(not ? { not } : {}) };
    return raw();
  }
  if (node.k !== 'call') return raw();
  const names = node.args.map((a) => a.name).filter(Boolean);
  const only = (...allowed) => names.every((n) => allowed.includes(n));
  switch (node.name) {
    case 'breach_reclaim': {
      const p = prior(arg(node, 'reference', 0));
      const lo = val(arg(node, 'within_min')) ?? '0';
      const hi = val(arg(node, 'within_max')) ?? '0';
      const within = lo === '0' && hi === '0' ? '0' : lo === '1' && (hi === '3' || hi === '8') ? hi : null;
      return p ? ok('reclaim', { ...p, within }) : raw();
    }
    case 'channel_breakout': return ok('breakout', { over: val(arg(node, 'over')) });
    case 'wick_rejection': return ok('wickrej', { body: val(arg(node, 'body_max')) ?? '35%', wick: val(arg(node, 'wick_min')) ?? '45%' });
    case 'candle_relation': {
      const l = arg(node, 'left', 0); const r = arg(node, 'right', 1);
      if (l?.k !== 'call' || l.name !== 'price' || r?.k !== 'call' || r.name !== 'price' || arg(l, 'bars_ago')) return raw();
      return ok('relation', { a: val(arg(l, 'point', 0)) ?? 'close', rel: val(arg(node, 'is')) ?? 'above', b: val(arg(r, 'point', 0)) ?? 'close', back: val(arg(r, 'bars_ago')) });
    }
    case 'candle_share': {
      if (!only('min', 'max', 'part')) return raw();
      const part = val(arg(node, 'part', 0)) ?? 'lower_wick';
      const min = val(arg(node, 'min')); const max = val(arg(node, 'max'));
      if (max && max !== '100%') return min === '0%' || min === '0' ? ok('sharemax', { part, max }) : raw();
      return ok('share', { part, min: min ?? '50%' });
    }
    case 'range_multiple': return only('over', 'min') ? ok('rangex', { min: val(arg(node, 'min')) ?? '1.5', over: val(arg(node, 'over')) ?? '4h' }) : raw();
    case 'near_level': {
      const p = prior(arg(node, 'reference', 0)); const pt = arg(node, 'point', 1);
      if (!p || pt?.k !== 'call' || pt.name !== 'price' || (val(arg(pt, 'point', 0)) ?? 'close') !== 'close' || arg(pt, 'bars_ago')) return raw();
      return ok('near', { within: val(arg(node, 'within')) ?? '0.25%', ...p });
    }
    case 'chained_g1': case 'exact_g1': {
      // either reading of a g1 is a drawn shape: the chain, or the same shape with its opens as recorded
      const code = arg(node, 'pattern', 0);
      const radiusNode = arg(node, 'radius');
      const radius = val(radiusNode);
      const allowed = node.args.length === 1 || (node.args.length === 2 && radiusNode && radius !== null);
      if (!allowed || code?.k !== 'str' || !/^g1:[ou]:/.test(code.value)) return raw();
      return { type: 'drawing', args: { g1: code.value, packet: null, held: false,
        recorded: node.name === 'exact_g1', ...(Array.isArray(radius) || Number(radius) > 0 ? {radius} : {}) } };

    }
    case 'session_tail': return ok('tail', { last: val(arg(node, 'last')) });
    case 'held': {
      const st = arg(node, 'state', 0);
      const width = st?.k === 'str' && st.value === 'Quiet range' ? '2.5%'
        : st?.k === 'call' && st.name === 'quiet_range' && !arg(st, 'window') ? (val(arg(st, 'width_max')) ?? '2.5%') : null;
      return ok('quiet', { width, for: val(arg(node, 'for')) });
    }
    default:
      if (!node.args.length && patternById.has(node.name)) return { type: 'pattern', args: { p: node.name } };
      return raw();
  }
}

export function fromText(text) {
  const { ast, error } = parse(text);
  if (error) return { model: null, error };
  const lets = new Map(ast.lets.map((b) => [b.name, b.value]));
  const top = ast.find.k === 'or' || ast.find.k === 'and' ? ast.find : { k: 'or', items: [ast.find] };
  const model = { find: { join: top.k, items: top.items.map((n) => fromExpr(n, lets)) }, wheres: [], split: null, horizons: [] };
  for (const w of ast.wheres) {
    if (w.k === 'and') w.items.forEach((n) => model.wheres.push(fromExpr(n, lets)));
    else model.wheres.push(fromExpr(w, lets));
  }
  if (ast.group) {
    const g = ast.group;
    if (g.k === 'call' && g.name === 'weekday') model.split = make('weekday');
    else if (g.k === 'call' && g.name === 'completed_trend') model.split = make('trend', { frame: g.args[0]?.value?.text ?? '4h' });
    else model.split = fromExpr(g, lets);
  }
  for (const m of ast.measures) {
    if (m.name !== 'close_return') continue;
    const v = m.args[0]?.value;
    const hs = v?.k === 'vec' ? v.items : [v];
    for (const hNode of hs) { const t = hNode?.k === 'id' && lets.has(hNode.name) ? lets.get(hNode.name).text : hNode?.text; if (t && !model.horizons.includes(t)) model.horizons.push(t); }
  }
  return { model, error: null };
}

// ---------------------------------------------------------------- starting questions

export const PRESETS = [
  { id: 'reclaim', title: 'Failed break of the prior low',
    text: 'on BTCUSDT 15m\nfind breach_reclaim(prior_low(over: 4h))\nwhere candle_share(lower_wick, min: 50%)\nwhere range_multiple(over: 4h, min: 1.5)\nmeasure close_return(after: [1h, 4h])' },
  { id: 'hammer', title: 'Hammers by 4h trend',
    text: 'on BTCUSDT 15m\nfind hammer\ngroup by completed_trend(frame: 4h)\nmeasure close_return(after: [1h, 4h])' },
  { id: 'friday', title: 'Quiet Friday close',
    text: 'on BTCUSDT 15m\nfind wick_rejection(body_max: 35%, wick_min: 45%)\nwhere weekday(nyse_regular) = fri\nwhere session_tail(nyse_regular, last: 1h)\nwhere held(quiet_range(width_max: 2.5%), for: 48h)\nmeasure close_return(after: [1h, 4h])' },
  { id: 'breakout', title: 'Breakout with the trend',
    text: 'on BTCUSDT 15m\nfind channel_breakout(over: 12h)\nwhere completed_trend(frame: 4h) = up\nmeasure close_return(after: [1h, 4h])' },
];

/** Conditions offered when adding a clause, each with its defaults. */
export const OFFERS = [
  make('share'), make('rangex'), make('sharemax'), make('weekday'), make('tail'), make('trend'),
  make('trend', { dir: 'down' }), make('quiet'), make('near'), make('near', { side: 'low' }),
  make('reclaim'), make('breakout'), make('pattern', { p: 'hammer' }), make('pattern', { p: 'engulfing' }),
  make('relation'), make('wickrej'),
];
