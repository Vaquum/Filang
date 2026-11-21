/* Named geometry, profile v1. Classic-script shared by Composer, its worker and research clients. */
(() => {
  'use strict';
  const all = (...clauses) => ({all: clauses}), any = (...clauses) => ({any: clauses});
  const is = (field, op, other) => [op, field, other], times = (n, field) => ['*', n, field];
  const body = is('body', '>', 0), flat = is('body', '==', 0);
  const lower = is('lower', '>', 0), upper = is('upper', '>', 0);
  const noLower = is('lower', '==', 0), noUpper = is('upper', '==', 0);
  const up = is('dir', '==', 1), down = is('dir', '==', -1);
  const opposite = all(is('dir', '!=', 0), is('prev.dir', '!=', 0), is('dir', '!=', 'prev.dir'));
  const contains = (bottom, top) => all(is(bottom, '<=', 'prev.' + bottom), is(top, '>=', 'prev.' + top),
    any(is(bottom, '<', 'prev.' + bottom), is(top, '>', 'prev.' + top)));
  const engulf = all(opposite, contains('bodyLow', 'bodyHigh'));
  const harami = all(is('bodyLow', '>', 'prev.bodyLow'), is('bodyHigh', '<', 'prev.bodyHigh'));
  const gapUp = is('low', '>', 'prev.high'), gapDown = is('high', '<', 'prev.low');
  const longWick = (long, short) => all(body, is(long, '>=', times(2, 'body')), is(times(2, short), '<=', 'body'));
  const patterns = [];
  function add(id, name, ja, bars, rule, spec, options = {}) {
    patterns.push({id, name, ja, bars, rule, spec, version: 1, kind: 'order', aliases: [],
      oriented: false, ...options});
  }
  add('marubozu', 'Marubozu', '丸坊主', 1, 'Nonzero body with neither an upper nor a lower wick.',
    all(body, noLower, noUpper), {aliases: ['寄引坊主']});
  add('doji', 'Doji', '十字線', 1, 'Open equals close, with a wick strictly above and below. Composer names the one-sided and four-price cases separately.',
    all(flat, lower, upper));
  add('dragonfly-doji', 'Dragonfly doji', 'トンボ', 1, 'Open, high and close are equal. The low is strictly lower.',
    all(flat, lower, noUpper), {aliases:['トンボ線','Tonbo']});
  add('gravestone-doji', 'Gravestone doji', '塔婆', 1, 'Open, low and close are equal. The high is strictly higher.',
    all(flat, noLower, upper), {aliases:['塔婆線']});
  add('opening-marubozu', 'Opening marubozu', '寄付坊主', 1, 'The opening end has no wick and the closing end has a wick. Either body direction qualifies.',
    any(all(up, noLower, upper), all(down, noUpper, lower)), {oriented:true});
  add('closing-marubozu', 'Closing marubozu', '大引坊主', 1, 'The closing end has no wick and the opening end has a wick. Either body direction qualifies.',
    any(all(up, noUpper, lower), all(down, noLower, upper)), {oriented:true});
  add('engulfing', 'Engulfing', '包み線', 2, 'Opposite-colored nonzero bodies. The second body covers the first, extending strictly beyond at least one end.',
    engulf, {oriented:true, group:true, aliases:['抱き線','Tsutsumi','Tsutsumi-sen','Tsutsumi sen']});
  add('bullish-engulfing', 'Bullish engulfing', '陽の包み線', 2, 'A rising body covers a falling body, extending strictly beyond at least one end.',
    all(engulf, up), {oriented:true});
  add('bearish-engulfing', 'Bearish engulfing', '陰の包み線', 2, 'A falling body covers a rising body, extending strictly beyond at least one end.',
    all(engulf, down), {oriented:true});
  add('harami', 'Harami', 'はらみ線', 2, 'The second nonzero body lies strictly inside the first body. Body colors and wicks are unrestricted.',
    all(harami, body));
  add('harami-cross', 'Harami cross', 'はらみ寄せ線', 2, 'The second open equals its close strictly inside the first body. Wicks are unrestricted.',
    all(harami, flat));
  add('window', 'Window', '窓', 2, 'The two complete high–low ranges are strictly separated by a gap in either direction.',
    any(gapUp, gapDown), {group:true});
  add('rising-window', 'Rising window', '上窓', 2, 'The second low is strictly above the first high.', gapUp,
    {aliases:['Gap up','Window up','窓開け上昇']});
  add('falling-window', 'Falling window', '下窓', 2, 'The second high is strictly below the first low.', gapDown,
    {aliases:['Gap down','Window down','窓開け下落']});
  add('tweezer-top', 'Tweezer top', '毛抜き天井', 2, 'The highs of the two bars are exactly equal.', is('high', '==', 'prev.high'));
  add('tweezer-bottom', 'Tweezer bottom', '毛抜き底', 2, 'The lows of the two bars are exactly equal.', is('low', '==', 'prev.low'));
  add('meeting-lines', 'Meeting lines', '出会い線', 2, 'Opposite-colored nonzero bodies close at the same price.',
    all(opposite, is('close', '==', 'prev.close')), {oriented:true});
  add('separating-lines', 'Separating lines', '行き違い線', 2, 'Opposite-colored nonzero bodies open at the same price.',
    all(opposite, is('open', '==', 'prev.open')), {oriented:true});
  add('hammer', 'Hammer', 'ハンマー', 1, 'Shape only. The body is nonzero, the lower wick is at least twice the body, and the upper wick is at most half the body. Prior decline and reversal confirmation are outside this rule.',
    longWick('lower', 'upper'), {kind:'ratio', aliases:['カラカサ','Karakasa','Hammer shape']});
  add('inverted-hammer', 'Inverted hammer', '逆ハンマー', 1, 'Shape only. The body is nonzero, the upper wick is at least twice the body, and the lower wick is at most half the body. Prior decline and reversal confirmation are outside this rule.',
    longWick('upper', 'lower'), {kind:'ratio', aliases:['トンカチ','Tonkachi','Inverted hammer shape']});
  add('spinning-top', 'Spinning top', 'コマ', 1, 'Both wicks are strictly longer than the nonzero body. Either body direction qualifies.',
    all(body, is('lower','>','body'), is('upper','>','body')), {kind:'ratio',aliases:['Koma']});
  add('inside-bar', 'Inside bar', 'インサイドバー', 2, 'The second complete range lies inside the first. One equal endpoint is allowed, but identical ranges are excluded.',
    all(is('low','>=','prev.low'), is('high','<=','prev.high'), any(is('low','>','prev.low'), is('high','<','prev.high'))));
  add('outside-bar', 'Outside bar', 'アウトサイドバー', 2, 'The second complete range contains the first. One equal endpoint is allowed, but identical ranges are excluded.',
    contains('low','high'));
  add('four-price-doji', 'Four-price doji', '四値同時線', 1, 'Open, high, low and close are all equal.',
    is('range','==',0), {aliases:['一本線','Four price doji']});

  const fields = {
    open: (o,h,l,c,i) => o[i], high: (o,h,l,c,i) => h[i], low: (o,h,l,c,i) => l[i], close: (o,h,l,c,i) => c[i],
    bodyLow: (o,h,l,c,i) => Math.min(o[i],c[i]), bodyHigh: (o,h,l,c,i) => Math.max(o[i],c[i]),
    body: (o,h,l,c,i) => Math.abs(c[i]-o[i]), range: (o,h,l,c,i) => h[i]-l[i],
    lower: (o,h,l,c,i) => Math.min(o[i],c[i])-l[i], upper: (o,h,l,c,i) => h[i]-Math.max(o[i],c[i]),
    dir: (o,h,l,c,i) => Math.sign(c[i]-o[i])
  };
  const comparisons = {'==':(a,b)=>a===b, '!=':(a,b)=>a!==b, '>':(a,b)=>a>b, '>=':(a,b)=>a>=b, '<':(a,b)=>a<b, '<=':(a,b)=>a<=b};
  function operand(value) {
    if (typeof value === 'number') return () => value;
    if (Array.isArray(value)) {
      if (value[0] !== '*' || !Number.isSafeInteger(value[1])) throw new Error('Invalid pattern multiplier');
      const f = operand(value[2]);
      return (o,h,l,c,i) => value[1] * f(o,h,l,c,i);
    }
    const previous = value.startsWith('prev.'), f = fields[previous ? value.slice(5) : value];
    if (!f) throw new Error('Unknown pattern field ' + value);
    return previous ? (o,h,l,c,i) => f(o,h,l,c,i-1) : f;
  }
  function predicate(spec) {
    if (spec.all || spec.any) {
      const every = !!spec.all, parts = (spec.all || spec.any).map(predicate);
      return (o,h,l,c,i) => {
        for (const f of parts) if (f(o,h,l,c,i) !== every) return !every;
        return every;
      };
    }
    const test = comparisons[spec[0]], a = operand(spec[1]), b = operand(spec[2]);
    if (!test) throw new Error('Invalid pattern comparison');
    return (o,h,l,c,i) => test(a(o,h,l,c,i), b(o,h,l,c,i));
  }
  const norm = s => s.normalize('NFKC').trim().toLowerCase(), names = new Map(), compiled = new Map();
  for (const p of patterns) {
    for (const name of [p.id, p.name, p.ja, ...p.aliases]) {
      const key = norm(name);
      if (names.has(key) && names.get(key) !== p) throw new Error('Ambiguous candle name ' + name);
      names.set(key,p);
    }
    const test = predicate(p.spec);
    compiled.set(p.id,(o,h,l,c,i) => i >= p.bars-1 && test(o,h,l,c,i));
  }
  function compile(id) {
    const f = compiled.get(id);
    if (!f) throw new Error('Unknown candle pattern ' + id);
    return f;
  }
  function matches(id, rows) {
    const [o,h,l,c] = [0,1,2,3].map(k => rows.map(row => row[k]));
    return compile(id)(o,h,l,c,rows.length-1);
  }
  globalThis.CandlePatterns = {patterns, resolve: name => typeof name === 'string' ? names.get(norm(name)) : undefined, compile, matches};
})();
