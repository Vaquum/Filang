// g1 dimensions in the study engine (docs/G1_DIMENSIONS.md): the shared vectors, the text, the recording's counters,
// and exact_g1 / chained_g1 on a recording that carries them. Run from study/: node verify/dimensions.mjs
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { loadEnvironment, readBytes, ROOT } from './node-env.js';
import { buildEnvironment, DATA_FILES } from '../src/boot.js';
import { COUNTER_COLUMNS, DataError, parseRecording, sha256Hex } from '../src/data.js';
import { analyze } from '../src/check.js';
import { runAnalysis } from '../src/engine.js';
import { chainedG1FromRecording, dimensionsFit, DIMENSIONS, g1FromRecording, matchesChainedG1, matchesG1, parseG1 } from '../src/g1.js';
import { centsText } from '../src/num.js';

let passed = 0;
const ok = (name, fn) => { fn(); passed++; console.log('  ✓ ' + name); };
const NAMES = DIMENSIONS.map((d) => d.name);
const provenanceFor = (rows) => ({ instrument: 'Binance BTCUSDT spot', interval_ms: 900000, timestamp_role: 'open', columns: COUNTER_COLUMNS, row_count: rows });
const csvOf = (bars, t0 = 0) => [COUNTER_COLUMNS.join(','), ...bars.map((b, k) =>
  [t0 + k * 900000, centsText(b[0]), centsText(b[1]), centsText(b[2]), centsText(b[3]), '0', String(b[4]), String(b[5]), String(b[6])].join(','))].join('\n') + '\n';
const recordingOf = (bars) => parseRecording(csvOf(bars), provenanceFor(bars.length), null);

// ---------------------------------------------------------------- the shared vectors
const doc = JSON.parse(fs.readFileSync(path.join(ROOT, 'verify', 'dimension-vectors.json'), 'utf8'));
ok('the vectors name the dimensions in the order their parts are written', () => assert.deepEqual(doc.dimensions, NAMES));
ok(`every vector reads to its code for no dimension, each dimension and all five, under both readings (${doc.vectors.length} windows)`, () => {
  for (const v of doc.vectors) {
    const rec = recordingOf(v.bars), n = v.bars.length, end = n - 1;
    for (const [reading, read, fits] of [['as_recorded', g1FromRecording, matchesG1], ['chained', chainedG1FromRecording, matchesChainedG1]]) {
      assert.equal(read(rec, end, n), v[reading], v.name);
      const sets = [[], ...NAMES.map((name) => [name]), NAMES, [...NAMES].reverse()];
      for (const set of sets) {
        const parts = NAMES.filter((name) => set.includes(name)).map((name) => v.parts[name]);
        const expected = parts.includes(null) ? null : [v[reading], ...parts].join('|');
        assert.equal(read(rec, end, n, true, set), expected, `${v.name}: ${reading} with ${set.join(',') || 'none'}`);
        if (expected === null) continue;
        const pattern = parseG1(expected);
        assert.deepEqual(pattern.dims.map((d) => d.name), NAMES.filter((name) => set.includes(name)));
        assert.equal(dimensionsFit(rec, 0, pattern), 1, `${v.name}: its own code does not fit`);
        assert.equal(fits(rec, 0, pattern, new Float64Array(pattern.rankCount)), true);
      }
    }
  }
});
ok('a code that differs in one dimension does not fit, and one that needs an absent value is unknown', () => {
  const two = doc.vectors.find((v) => v.name.startsWith('two bars: volume rises'));
  const rec = recordingOf(two.bars);
  assert.equal(dimensionsFit(rec, 0, parseG1(two.as_recorded + '|volume:1,0')), 0);
  assert.equal(dimensionsFit(rec, 0, parseG1(two.as_recorded + '|volume:0,0')), 0);
  assert.equal(dimensionsFit(rec, 0, parseG1(two.as_recorded + '|delta:1,2/0')), 0);   // both net buying: the first is not
  assert.equal(dimensionsFit(rec, 0, parseG1(two.as_recorded + '|volume:0,1|delta:0,2/1')), 1);
  const idle = doc.vectors.find((v) => v.name.startsWith('a bar without trades'));
  const quiet = recordingOf(idle.bars);
  assert.equal(dimensionsFit(quiet, 0, parseG1(idle.as_recorded + '|size:0,0')), -1);
  assert.equal(dimensionsFit(quiet, 0, parseG1(idle.as_recorded + '|volume:1,0|imbalance:1,0/0')), -1);
  assert.equal(dimensionsFit(quiet, 0, parseG1(idle.as_recorded + '|volume:1,0|delta:1,0/0')), 1);
});

// ---------------------------------------------------------------- the text
ok('a code with no dimension part parses as it always did, with no dimensions', () => {
  const p = parseG1('g1:o:0,1,3,4,u;2,3,5,6,u');
  assert.deepEqual(p.dims, []);
  assert.equal(p.rankCount, 7);
  assert.equal(parseG1('g1:u:0,1,2,2').dims.length, 0);
});
ok('malformed dimension parts are rejected', () => {
  const base = 'g1:o:0,1,2,3,u';
  for (const tail of ['|', '|volume:', '|volume:00', '|volume:0,1', '|volume:0/1', '|volume:1', '|delta:1', '|delta:0/', '|delta:2/0', '|delta:0/2',
    '|flow:0', '|Volume:0', '|volume:0|volume:0', '|delta:1/0|volume:0', '|volume:0 ', '|volume:-0', '|volume:0|', '|imbalance:0/0/0']) {
    assert.throws(() => parseG1(base + tail), Error, base + tail);
  }
  assert.throws(() => parseG1('g1:o:0,1,2,3,u;4,5,6,7,u|volume:0'), /one rank for each candle/);
  assert.throws(() => g1FromRecording(recordingOf(doc.vectors[0].bars), 0, 1, true, ['flow']), /unknown G1 dimension/);
});

// ---------------------------------------------------------------- the recording
ok('the six-column recording carries no dimension, and a code that switches one on is refused on it', () => {
  const e = loadEnvironment();
  assert.equal(e.rec.dimension('volume'), null);
  assert.equal(e.env.recording.caps.has('bars.counters'), false);
  assert.equal(g1FromRecording(e.rec, 10, 2, true, ['volume']), null);
  const a = analyze('on BTCUSDT 15m\nfind exact_g1("g1:o:0,1,2,2,u|volume:0")', e.env);
  assert.equal(a.ok, false);
  assert.equal(a.errors[0].kind, 'capability');
  assert.match(a.errors[0].message, /volume/);
  assert.equal(analyze('on BTCUSDT 15m\nfind exact_g1("g1:o:0,1,2,2,u")', e.env).ok, true);
});
ok('a recording whose counters cannot be right is refused', () => {
  const bar = [1000000, 1050000, 990000, 1040000];
  const text = (v, b, n) => [COUNTER_COLUMNS.join(','), ['0', '10000.00', '10500.00', '9900.00', '10400.00', '0', v, b, n].join(',')].join('\n') + '\n';
  for (const [v, b, n] of [['1000', '1001', '10'], ['1000', '600', '10.5'], ['-1', '0', '1'], ['NaN', '0', '1'], ['Infinity', '600', '10'], ['1e999', '600', '10'], ['1000', '', '10'], ['1000', '600', ''], ['1000', '600', '1e1']]) {
    assert.throws(() => parseRecording(text(v, b, n), provenanceFor(1), null), DataError, [v, b, n].join(' '));
  }
  assert.equal(recordingOf([[...bar, 1000, 1000, 1]]).dimension('imbalance')[0], 1);
  assert.throws(() => parseRecording(csvOf([[...bar, 1, 1, 1]]).replace(',1\n', '\n'), provenanceFor(1), null), DataError);
});
ok('counters written as text read back to the same floats', () => {
  const values = [10076955.5409877, 0.1 + 0.2, 652854.14, 1678986.8, 1e-6, 123456789012345.67];
  const rec = recordingOf(values.map((v) => [1000000, 1050000, 990000, 1040000, v, v / 3, 7]));
  values.forEach((v, i) => { assert.equal(rec.VOL[i], v); assert.equal(rec.TBV[i], v / 3); });
});

// ---------------------------------------------------------------- the engine, on the pinned prices with counters beside them
// The counters below are a deterministic test fixture, not market data: they exist so that every branch is exercised
// on a recording of real length. Every fortieth bar has no trades, so size and imbalance are absent there.
const pinned = loadEnvironment();
function fixture() {
  let seed = 20261122;
  const next = () => { seed = (Math.imul(seed, 1103515245) + 12345) >>> 0; return seed / 4294967296; };
  const lines = [COUNTER_COLUMNS.join(',')];
  for (let i = 0; i < pinned.rec.n; i++) {
    if (!pinned.rec.present[i]) continue;
    const f = pinned.rec.raw[i];
    const idle = i % 40 === 39;
    const vol = idle ? 0 : Math.round(next() * 8) * 250000 + 250000;          // few distinct values, so volumes tie
    const share = [0.3, 0.4, 0.5, 0.5, 0.6, 0.7][Math.floor(next() * 6)];      // exact balance is common
    const cnt = idle ? 0 : 100 + Math.floor(next() * 5) * 100;
    lines.push([pinned.rec.openTime(i), f[0], f[1], f[2], f[3], f[4], String(vol), String(vol * share), String(cnt)].join(','));
  }
  const csv = new TextEncoder().encode(lines.join('\n') + '\n');
  const provenance = { ...pinned.provenance, columns: COUNTER_COLUMNS, row_count: lines.length - 1, csv_sha256: sha256Hex(csv) };
  return buildEnvironment({ csvBytes: csv, provenanceBytes: new TextEncoder().encode(JSON.stringify(provenance)), sessionsBytes: readBytes(DATA_FILES.sessions) });
}
const e = fixture();
const ask = (env, find) => {
  const a = analyze(`on BTCUSDT 15m\nfind ${find}`, env.env);
  assert.equal(a.ok, true, JSON.stringify(a.errors));
  return runAnalysis(env.ctx, a, { extensions: env.extensions, digestVerified: env.digestVerified }).results[0];
};
const slots = (result) => result.matches.map((r) => r.i);

ok('the fixture has the pinned prices, and declares its counters', () => {
  assert.equal(e.rec.n, pinned.rec.n);
  assert.deepEqual(e.rec.C, pinned.rec.C);
  assert.equal(e.env.recording.caps.has('bars.counters'), true);
  assert.equal(e.digestVerified, true);
});
ok('with every dimension off, a code finds the same windows as on the six-column recording', () => {
  for (const [event, code] of [['exact_g1', 'g1:o:0,1,2,2,u'], ['chained_g1', 'g1:o:0,1,3,4,u;2,3,5,6,u'], ['exact_g1', 'g1:u:0,1,2,2'], ['chained_g1', 'g1:o:1,3,4,5,u;0,2,4,6,d']]) {
    const find = `${event}(${JSON.stringify(code)})`;
    assert.deepEqual(slots(ask(e, find)), slots(ask(pinned, find)), find);
  }
});

for (const [event, read] of [['exact_g1', g1FromRecording], ['chained_g1', chainedG1FromRecording]]) {
  for (const set of [['volume'], ['delta'], ['volume', 'delta'], ['trades', 'size', 'imbalance'], NAMES]) {
    ok(`${event} with ${set.join(', ')} on: the refinements of a price code split its windows exactly`, () => {
      // this file's own grouping of every two-bar window: price code -> full code -> anchor slots
      const byPrice = new Map(), unknown = new Map();
      for (let i = 1; i < e.rec.n; i++) {
        const price = read(e.rec, i, 2);
        if (price === null) continue;
        const full = read(e.rec, i, 2, true, set);
        if (full === null) { unknown.set(price, (unknown.get(price) || 0) + 1); continue; }
        if (!byPrice.has(price)) byPrice.set(price, new Map());
        const group = byPrice.get(price);
        if (!group.has(full)) group.set(full, []);
        group.get(full).push(i);
      }
      const [price, group] = [...byPrice.entries()].sort((a, b) => b[1].size - a[1].size || (a[0] < b[0] ? -1 : 1))[0];
      const all = new Set(slots(ask(e, `${event}(${JSON.stringify(price)})`)));
      const seen = new Set();
      let total = 0;
      for (const [full, expected] of group) {
        const result = ask(e, `${event}(${JSON.stringify(full)})`);
        assert.deepEqual(slots(result), expected, full);
        for (const i of expected) { assert.ok(all.has(i), `${full}: slot ${i} is not a window of ${price}`); assert.ok(!seen.has(i)); seen.add(i); }
        total += expected.length;
      }
      assert.ok(group.size > 1, 'the fixture did not split the code');
      assert.equal(total + (unknown.get(price) || 0), all.size, `${price}: refinements and unknown windows do not add up to its windows`);
    });
  }
}
ok('a window missing a value it is asked about is unknown, not false', () => {
  const idle = 39;                                   // no trades on this bar: no size, no imbalance
  assert.equal(Number.isNaN(e.rec.dimension('size')[idle]), true);
  assert.equal(e.rec.dimension('delta')[idle], 0);
  const price = g1FromRecording(e.rec, idle, 1);
  const withSize = ask(e, `exact_g1(${JSON.stringify(price + '|size:0')})`);
  assert.equal(withSize.matches.some((r) => r.i === idle), false);
  // every bar without trades is unknown for size; one-bar windows are never unknown for any other reason
  const idleBars = Array.from({ length: e.rec.n }, (_, i) => i).filter((i) => e.rec.present[i] && e.rec.CNT[i] === 0).length;
  assert.ok(idleBars > 300);
  assert.equal(withSize.counts.U, idleBars);
  assert.equal(withSize.counts.T + withSize.counts.F + withSize.counts.U, withSize.counts.slots);
  assert.equal(ask(e, `exact_g1(${JSON.stringify(price)})`).counts.U, 0);
  const withDelta = ask(e, `exact_g1(${JSON.stringify(price + '|delta:0/0')})`);
  assert.equal(withDelta.matches.some((r) => r.i === idle), true);
});

// ---------------------------------------------------------------- readings in the language
const analysisOf = (env, text) => analyze(`on BTCUSDT 15m\n${text}`, env.env);
const refused = (env, text, kind, pattern) => {
  const a = analysisOf(env, text);
  assert.equal(a.ok, false, text);
  assert.equal(a.errors[0].kind, kind, `${text}: ${a.errors[0].message}`);
  if (pattern) assert.match(a.errors[0].message, pattern, text);
};
const where = (env, clause) => {
  const a = analysisOf(env, `find candle_relation(price(high), is: at_or_above, right: price(low))\nwhere ${clause}`);
  assert.equal(a.ok, true, JSON.stringify(a.errors));
  return runAnalysis(env.ctx, a, { extensions: env.extensions, digestVerified: env.digestVerified }).results[0].clauseStats[0];
};
const D = Object.fromEntries(NAMES.map((name) => [name, e.rec.dimension(name)]));
const every = (test) => { const out = []; for (let i = 0; i < e.rec.n; i++) if (test(i)) out.push(i); return out; };

ok('a reading compares with the same reading of another candle', () => {
  assert.deepEqual(slots(ask(e, 'candle_relation(volume(), is: above, right: volume(bars_ago: 1))')), every((i) => i >= 1 && D.volume[i] > D.volume[i - 1]));
  assert.deepEqual(slots(ask(e, 'candle_relation(volume(), is: equal, right: volume(bars_ago: 1))')), every((i) => i >= 1 && D.volume[i] === D.volume[i - 1]));
  assert.deepEqual(slots(ask(e, 'candle_relation(trades(bars_ago: 1), is: at_or_below, right: trades(bars_ago: 3))')), every((i) => i >= 3 && D.trades[i - 1] <= D.trades[i - 3]));
  const size = ask(e, 'candle_relation(size(), is: at_or_above, right: size(bars_ago: 2))');
  assert.deepEqual(slots(size), every((i) => i >= 2 && D.size[i] >= D.size[i - 2]));
  assert.equal(size.counts.U, every((i) => i < 2 || Number.isNaN(D.size[i]) || Number.isNaN(D.size[i - 2])).length);
});
ok('delta and imbalance compare with zero, and a candle without the value is unknown', () => {
  assert.deepEqual(slots(ask(e, 'candle_relation(delta(), is: above, right: 0)')), every((i) => D.delta[i] > 0));
  assert.deepEqual(slots(ask(e, 'candle_relation(0, is: above, right: delta())')), every((i) => D.delta[i] < 0));
  const balanced = ask(e, 'candle_relation(delta(), is: equal, right: 0)');
  assert.deepEqual(slots(balanced), every((i) => D.delta[i] === 0));
  assert.ok(balanced.matches.length > 2000, 'the fixture has too few balanced bars to test the tie');
  const selling = ask(e, 'candle_relation(imbalance(), is: below, right: 0.0)');
  assert.deepEqual(slots(selling), every((i) => D.imbalance[i] < 0));
  assert.equal(selling.counts.U, every((i) => Number.isNaN(D.imbalance[i])).length);
});
ok('a two-bar code with volume on agrees with the same statement made as a relation', () => {
  const rising = new Set(slots(ask(e, 'candle_relation(volume(), is: above, right: volume(bars_ago: 1))')));
  for (let i = 1; i < e.rec.n; i++) {
    const code = g1FromRecording(e.rec, i, 2, true, ['volume']);
    assert.equal(code.endsWith('|volume:0,1'), rising.has(i), `slot ${i}`);
  }
});
ok('a prior level can be taken from a dimension', () => {
  const n = 16, top = (i) => Math.max(...D.volume.slice(i - n, i)), floor = (i) => Math.min(...D.size.slice(i - n, i));
  assert.deepEqual(slots(ask(e, 'candle_relation(volume(), is: above, right: prior_high(over: 4h, of: volume))')), every((i) => i >= n && D.volume[i] > top(i)));
  const low = ask(e, 'candle_relation(size(), is: below, right: prior_low(over: 4h, of: size))');
  assert.deepEqual(slots(low), every((i) => i >= n && D.size[i] < floor(i)));   // Math.min is NaN over a window with a missing value
  assert.equal(low.counts.U, every((i) => i < n || Number.isNaN(D.size[i]) || Number.isNaN(floor(i))).length);
});
ok('a dimension is measured against the median of the candles before it', () => {
  const n = 16;
  // a window holding a candle without the value has no median
  const middle = (x, i) => { const w = [...x.slice(i - n, i)]; if (w.some(Number.isNaN)) return NaN; w.sort((a, b) => a - b); return w[7] + w[8]; };
  for (const [name, min, max] of [['volume', 1.5, null], ['trades', 0.5, 1], ['size', 1.25, null]]) {
    const x = D[name];
    const known = (i) => i >= n && !Number.isNaN(x[i]) && middle(x, i) > 0;
    const holds = (i) => known(i) && 2 * x[i] >= min * middle(x, i) && (max === null || 2 * x[i] <= max * middle(x, i));
    const stats = where(e, `dimension_multiple(${name}, over: 4h, min: ${min}${max === null ? '' : `, max: ${max}`})`);
    assert.equal(stats.T, every(holds).length, name);
    assert.equal(stats.U, every((i) => !known(i)).length, name);
    assert.ok(stats.T > 100 && stats.F > 100, `${name}: the fixture does not exercise both answers`);
  }
});
ok('values on different axes are never compared', () => {
  refused(e, 'find candle_relation(volume(), is: above, right: price(close))', 'type', /one axis/);
  refused(e, 'find candle_relation(volume(), is: above, right: delta())', 'type', /one axis/);
  refused(e, 'find candle_relation(volume(), is: above, right: 0)', 'type', /reference point/);
  refused(e, 'find candle_relation(price(close), is: above, right: 0)', 'type', /reference point/);
  refused(e, 'find candle_relation(0, is: above, right: 0)', 'type', /reference point/);
  refused(e, 'find candle_relation(volume(), is: above, right: prior_high(over: 4h))', 'type', /one axis/);
  refused(e, 'find candle_relation(volume(), is: above, right: prior_high(over: 4h, of: trades))', 'type', /one axis/);
  refused(e, 'find breach_reclaim(prior_low(over: 4h, of: volume))', 'type', /works on prices/);
  refused(e, 'find "Wick rejection"\nwhere near_level(prior_high(over: 4h, of: volume), point: price(close), within: 1%)', 'type', /works on prices/);
  refused(e, 'find "Wick rejection"\nwhere near_level(prior_high(over: 4h), point: volume(), within: 1%)', 'type');
  refused(e, 'find "Wick rejection"\nwhere dimension_multiple(delta, over: 4h, min: 1.5)', 'domain', /cannot be negative/);
  assert.equal(analysisOf(e, 'find candle_relation(price(close), is: above, right: prior_high(over: 4h))').ok, true);
});
ok('on a recording without counters the readings are refused and are not offered', () => {
  refused(pinned, 'find candle_relation(volume(), is: above, right: volume(bars_ago: 1))', 'capability');
  refused(pinned, 'find candle_relation(price(close), is: above, right: prior_high(over: 4h, of: volume))', 'capability');
  refused(pinned, 'find "Wick rejection"\nwhere dimension_multiple(volume, over: 4h, min: 1.5)', 'capability');
  const offered = (env) => new Set(env.registry.implemented().map((f) => f.name));
  for (const name of [...NAMES, 'dimension_multiple']) { assert.equal(offered(pinned).has(name), false, name); assert.equal(offered(e).has(name), true, name); }
  assert.equal(offered(pinned).has('candle_relation'), true);
});

console.log(`\n${passed} passed, 0 failed`);
