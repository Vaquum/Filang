import assert from 'node:assert/strict';
import { loadEnvironment } from './node-env.js';
import { installExtension } from '../src/boot.js';
import { analyze } from '../src/check.js';
import { EvalContext, eventSeries, kAnd, kOr, runAnalysis, U } from '../src/engine.js';
import { CANDLE_PATTERNS } from '../src/registry.js';
import { checkStudy, makeStudy } from '../src/study-save.js';

const e = loadEnvironment();
const source = 'on BTCUSDT 15m\n';
function checked(body) {
  const a = analyze(source + body, e.env);
  assert.equal(a.ok, true, JSON.stringify(a.errors));
  return a;
}
function plan(find) { return checked('find ' + find).candidates[0].plan.find; }
function run(body) {
  return runAnalysis(e.ctx, checked(body), { extensions: e.extensions, digestVerified: true });
}
const removed = 71;
const gap = new EvalContext(e.rec.withoutSlots([removed], 'delete one recorded candle'), e.calendars);
for (const p of CANDLE_PATTERNS.patterns) {
  const slug = p.id.replaceAll('-', '_'), canonical = plan(slug);
  assert.equal(canonical.identity, `composer.${slug}@1()`);
  assert.equal(e.registry.getPattern(p.id), canonical.def);
  for (const name of [p.name, p.name.toUpperCase(), p.ja, p.id, ...p.aliases]) {
    assert.equal(plan(JSON.stringify(name)).identity, canonical.identity, name);
    if (/^[\p{ID_Start}_][\p{ID_Continue}_]*$/u.test(name))
      assert.equal(plan(name).identity, canonical.identity, name);
  }
  assert.equal(plan(slug + '()').identity, canonical.identity);
  const live = eventSeries(e.ctx, canonical), withGap = eventSeries(gap, canonical);
  for (let i = 0; i < e.rec.n; i++) {
    const inGap = i >= removed && i < removed + p.bars;
    assert.equal(withGap.vals[i], inGap ? U : live.vals[i], `${slug} gap at ${i}`);
    assert.equal(live.vals[i] === U, i < p.bars - 1, slug);
  }
}

// Abstract tick-grid boundary examples, never mixed into recorded study populations.
const matches = (id, ...ohlc) => CANDLE_PATTERNS.matches(id, ohlc);
assert.ok(matches('hammer', [10, 13, 6, 12])); // lower = 2 bodies and upper = 1/2 body
assert.ok(matches('hammer', [12, 13, 6, 10])); // same shape with negative body
assert.ok(!matches('hammer', [10, 14, 6, 12]));
assert.ok(!matches('hammer', [10, 13, 7, 12]));
assert.ok(!matches('hammer', [10, 10, 4, 10]));
assert.ok(matches('bullish-engulfing', [11, 12, 7, 9], [9, 14, 8, 12]));
assert.ok(!matches('bullish-engulfing', [11, 12, 7, 9], [9, 14, 8, 11]));
assert.ok(!matches('bullish-engulfing', [9, 12, 7, 11], [8, 14, 7, 12]));
assert.ok(!matches('rising-window', [5, 7, 4, 6], [8, 10, 7, 9]));
assert.ok(matches('rising-window', [5, 7, 4, 6], [9, 11, 8, 10]));
assert.ok(matches('harami-cross', [5, 13, 3, 12], [7, 9, 6, 7]));
assert.ok(!matches('harami', [5, 13, 3, 12], [7, 9, 6, 7]));
assert.ok(matches('harami', [5, 13, 3, 12], [7, 9, 6, 8]));
assert.ok(!matches('harami', [5, 13, 3, 12], [5, 9, 4, 8]));
const bullish = eventSeries(e.ctx, plan('bullish_engulfing')).vals;
const bearish = eventSeries(e.ctx, plan('bearish_engulfing')).vals;
const either = eventSeries(e.ctx, plan('engulfing')).vals;
for (let i = 1; i < e.rec.n; i++) assert.equal(bullish[i] + bearish[i], either[i]);

// A rule's version and machine-readable spec are pinned regardless of the spelling used.
const newStudy = run('find ハンマー where bullish_engulfing');
assert.deepEqual(newStudy.manifest.pins.candlePatterns.map(p => p.id), ['bullish-engulfing', 'hammer']);
const saved = makeStudy('Hammer', newStudy, {});
checkStudy(saved, run('find Hammer where "陽の包み線"'));
const changed = structuredClone(saved);
changed.pins.candlePatterns[0].sha256 = 'changed';
assert.throws(() => checkStudy(changed, newStudy), /differs/);

// Pre-catalog studies retain their pins, including valid old bindings and agent identifiers.
const old = run('let hammer = "Wick rejection"\nfind hammer');
assert.equal(old.results[0].event.identity, plan('"Wick rejection"').identity);
assert.equal('candlePatterns' in old.manifest.pins, false);
const previous = e.extensions.find(ext => ext.version === 1).artifact;
const legacy = { ...previous, id: 'hammer', title: 'My quiet close' };
const installed = installExtension(e, { file: 'archived-hammer.json', bytes: new TextEncoder().encode(JSON.stringify(legacy)) });
assert.equal(installed.ok, true, JSON.stringify(installed.errors));
const oldRun = run('find "Wick rejection" where hammer()');
assert.deepEqual(oldRun.manifest.pins.extensions.map(x => x.id), ['hammer@1']);
assert.equal('candlePatterns' in oldRun.manifest.pins, false);
assert.equal(plan('hammer').def.patternId, 'hammer');
assert.equal(plan('"Hammer"').def.patternId, 'hammer');
assert.ok(e.registry.implemented().some(d => d.patternId === 'hammer'));
assert.equal(e.registry.getVersion('composer.hammer', 1).patternId, 'hammer');
assert.equal(e.registry.getVersion('hammer', 1), installed.def);
const composition = {
  artifact: 'limen.sfd.definition', id: 'my_hammer_filter', version: 1, kind: 'condition',
  body: 'カラカサ', params: [], depends: [{ name: 'composer.hammer', version: 1 }],
  conformance: [
    { anchor: '2025-01-02T01:45:00Z', args: {}, expect: 'true' },
    { anchor: '2025-01-01T00:15:00Z', args: {}, expect: 'false' },
  ],
};
const filter = installExtension(e, { file: 'my-hammer.json', bytes: new TextEncoder().encode(JSON.stringify(composition)) });
assert.equal(filter.ok, true, JSON.stringify(filter.errors));
const filtered = run('find 包み線 where my_hammer_filter()');
assert.deepEqual(filtered.manifest.pins.candlePatterns.map(p => p.id), ['engulfing', 'hammer']);
assert.deepEqual(filtered.manifest.pins.extensions.map(p => p.id), ['my_hammer_filter@1']);
assert.deepEqual(filtered.results[0].matches.map(r => r.t), run('find engulfing where hammer').results[0].matches.map(r => r.t));

const eitherStudy = run('find hammer or engulfing');
const union = eitherStudy.results[0], both = run('find hammer and engulfing').results[0];
const h = eventSeries(e.ctx, plan('hammer')).vals;
const overlaps = [];
const expectedUnion = [];
for (let i = 0; i < e.rec.n; i++) {
  const expectedOr = kOr([h[i], either[i]]), expectedAnd = kAnd([h[i], either[i]]);
  assert.equal(union.event.series.vals[i], expectedOr);
  assert.equal(both.event.series.vals[i], expectedAnd);
  if (expectedOr === 1) expectedUnion.push(i);
  if (expectedAnd === 1) overlaps.push(i);
}
assert.ok(overlaps.length > 0);
assert.deepEqual(both.matches.map(r => r.i), overlaps);
assert.deepEqual(union.matches.map(r => r.i), expectedUnion);
assert.equal(plan('包み線 or "カラカサ"').identity, union.event.identity);
assert.equal(plan('hammer or (engulfing or hammer)').identity, union.event.identity);
assert.equal(plan('hammer or ハンマー').identity, plan('hammer').identity);
assert.notEqual(plan('hammer and (engulfing or inside_bar)').identity, plan('(hammer and engulfing) or inside_bar').identity);
assert.deepEqual(eitherStudy.manifest.pins.candlePatterns.map(p => p.id), ['engulfing', 'hammer']);
checkStudy(makeStudy('Either', eitherStudy, {}), run('find 包み線 or カラカサ'));
for (const invalid of ['hammer or "Quiet range"', 'hammer and not engulfing', 'hammer or weekday(nyse_regular) = fri']) {
  assert.equal(analyze(source + 'find ' + invalid, e.env).ok, false, invalid);
}
console.log(`Passed all ${CANDLE_PATTERNS.patterns.length} candle rules, aliases, warm-ups, deleted bars, exact boundaries, study pins and historical name collisions.`);
