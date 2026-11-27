// The bench's interface for g1 dimensions (docs/G1_DIMENSIONS.md), checked without a browser on both kinds of
// recording: the pinned one, which carries no counters, and the same prices with counters beside them.
// Every dimension clause must print exact Filang text, come back from that text as the same clause, be offered only
// where the engine can answer it, and be refused by the engine, not by the bench, where it cannot. The lanes must
// show the dimensions a question refers to, hold each candle's own value, and survive the address.
// Run from the repository root, after study/prepare_recording.py: node query/verify/dimensions.mjs
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { runInNewContext } from 'node:vm';
import { install } from './site.mjs';

await install();
const { CLAUSES, DIMENSIONS, OFFERS, PRESETS, make, clone, toText, fromText, clauseText, phraseText, offered, dimensionsIn, g1Parts, g1Price, drawingBars, drawingDimensions } = await import('/shared/vocab.js');
// The canvas module initializes its motion preferences at import. The checks below use only its pure functions.
globalThis.window = { matchMedia: () => ({ matches: true }) };
globalThis.document = { addEventListener() {} };
const { lanesShown, setLane, lanesParam, lanesFromParam, dimensionColumns, dimensionText, dimensionExact } = await import('/bench/lanes.js');
const { casePacket, packetFromG1, drawingG1, readLink } = await import('/shared/handoff.js');
const { describe, engine, load, run } = await import('/shared/filang.js');

let checks = 0;
const ok = (name) => { checks++; console.log(`ok  ${name}`); };
const HEAD = 'on BTCUSDT 15m';
const ANY = 'candle_relation(price(high), is: at_or_above, right: price(low))';

// ---------------------------------------------------------------- the two recordings
// The counters are a deterministic fixture, not market data: few distinct volumes, so they tie; an exact taker
// balance on a third of the bars; and every fortieth bar without trades, so trade size and imbalance are absent there.
const pinned = await load();
const fetchRecording = fetch;
let seed = 20261122;
const next = () => { seed = (Math.imul(seed, 1103515245) + 12345) >>> 0; return seed / 4294967296; };
const [header, ...prices] = pinned.csv.trimEnd().split('\n');
const lines = prices.map(price => {
  const time = Number(price.slice(0, price.indexOf(',')));
  const slot = (time - pinned.rec.t0) / pinned.rec.barMs;
  const idle = slot % 40 === 39;
  const volume = idle ? 0 : Math.round(next() * 8) * 250000 + 250000;
  const share = [0.3, 0.4, 0.5, 0.5, 0.6, 0.7][Math.floor(next() * 6)];
  const trades = idle ? 0 : 100 + Math.floor(next() * 5) * 100;
  return `${price},${volume},${volume * share},${trades}`;
});
const columns = header.replace(/,volume$/, ',base_volume,volume,taker_buy_volume,trade_count');
const csv = [columns, ...lines].join('\n') + '\n';
const provenance = { ...pinned.provenance, columns: columns.split(','),
  csv_sha256: createHash('sha256').update(csv).digest('hex') };
globalThis.fetch = (url, init) => url === '/bars?w=fixture'
  ? Promise.resolve(Response.json({ csv, provenance })) : fetchRecording(url, init);
const cube = await load('fixture');
assert.equal(pinned.rec.hasCounters, false);
assert.equal(cube.rec.hasCounters, true);
assert.equal(cube.digestVerified, true);
assert.deepEqual(cube.rec.C, pinned.rec.C);

const check = (text) => describe(text);
const answer = (text) => {
  const receipt = run(text);
  assert.equal(receipt.ok, true, `${text}\n${JSON.stringify(receipt.errors)}`);
  return receipt.results;
};
const slots = (text) => answer(text)[0].matches.map(row => row.i);
const D = Object.fromEntries(DIMENSIONS.map((d) => [d.key, cube.rec.dimension(d.key)]));
const every = (test) => { const out = []; for (let i = 0; i < cube.rec.n; i++) if (test(i)) out.push(i); return out; };
const question = (find, wheres = []) => ({ find: { join: 'or', items: find }, wheres, split: null, horizons: ['1h', '4h'] });

// ---------------------------------------------------------------- the dimensions are Cube's
assert.deepEqual(DIMENSIONS.map((d) => [d.key, d.label, d.signed]), [['volume', 'Volume', false], ['trades', 'Trades', false], ['delta', 'Delta', true], ['size', 'Trade size', false], ['imbalance', 'Net taker imbalance', true]]);
ok('the five dimensions carry Cube’s keys, order and labels, and delta and imbalance have zero as their reference');

// ---------------------------------------------------------------- every clause: its text, its phrase, and the way back
// [clause, the exact Filang it prints, the sentence it reads as, its own count from the fixture's values]
const top = (x, i, n) => Math.max(...x.slice(i - n, i)); const floor = (x, i, n) => Math.min(...x.slice(i - n, i));
const middle = (x, i, n) => { const w = [...x.slice(i - n, i)]; if (w.some(Number.isNaN)) return NaN; w.sort((a, b) => a - b); return w[n / 2 - 1] + w[n / 2]; };
const CASES = [
  [make('dimback'), 'candle_relation(volume(), is: above, right: volume(bars_ago: 1))', 'the candle closes with volume above one candle back',
    (i) => i >= 1 && D.volume[i] > D.volume[i - 1]],
  [make('dimback', { dim: 'trades', rel: 'at_or_below', back: '3' }), 'candle_relation(trades(), is: at_or_below, right: trades(bars_ago: 3))', 'the candle closes with trades at or below three candles back',
    (i) => i >= 3 && D.trades[i] <= D.trades[i - 3]],
  [make('dimback', { dim: 'size', rel: 'equal', back: '2' }), 'candle_relation(size(), is: equal, right: size(bars_ago: 2))', 'the candle closes with trade size equal to two candles back',
    (i) => i >= 2 && D.size[i] === D.size[i - 2]],
  [make('dimback', { dim: 'imbalance', rel: 'below' }), 'candle_relation(imbalance(), is: below, right: imbalance(bars_ago: 1))', 'the candle closes with net taker imbalance below one candle back',
    (i) => i >= 1 && D.imbalance[i] < D.imbalance[i - 1]],
  [make('taker'), 'candle_relation(delta(), is: above, right: 0)', 'takers are net buying on this candle, by delta', (i) => D.delta[i] > 0],
  [make('taker', { side: 'below' }), 'candle_relation(delta(), is: below, right: 0)', 'takers are net selling on this candle, by delta', (i) => D.delta[i] < 0],
  [make('taker', { side: 'equal' }), 'candle_relation(delta(), is: equal, right: 0)', 'takers are balanced on this candle, by delta', (i) => D.delta[i] === 0],
  [make('taker', { side: 'below', by: 'imbalance' }), 'candle_relation(imbalance(), is: below, right: 0)', 'takers are net selling on this candle, by net taker imbalance', (i) => D.imbalance[i] < 0],
  [make('taker', { side: 'above', at: '2' }), 'candle_relation(delta(bars_ago: 2), is: above, right: 0)', 'takers are net buying on the candle two back, by delta', (i) => i >= 2 && D.delta[i - 2] > 0],
  [make('dimx'), 'dimension_multiple(volume, over: 4h, min: 1.5)', 'the candle closes with volume at least 1.5 × the prior 4h median',
    (i) => i >= 16 && middle(D.volume, i, 16) > 0 && 2 * D.volume[i] >= 1.5 * middle(D.volume, i, 16)],
  [make('dimx', { dim: 'size', min: '1.25', over: '2h' }), 'dimension_multiple(size, over: 2h, min: 1.25)', 'the candle closes with trade size at least 1.25 × the prior 2h median',
    (i) => i >= 8 && middle(D.size, i, 8) > 0 && 2 * D.size[i] >= 1.25 * middle(D.size, i, 8)],
  [make('dimxmax'), 'dimension_multiple(volume, over: 4h, min: 0, max: 0.5)', 'the candle closes with volume at most 0.5 × the prior 4h median',
    (i) => i >= 16 && middle(D.volume, i, 16) > 0 && 2 * D.volume[i] <= 0.5 * middle(D.volume, i, 16)],
  [make('dimxmax', { dim: 'trades', max: '0.75' }), 'dimension_multiple(trades, over: 4h, min: 0, max: 0.75)', 'the candle closes with trades at most 0.75 × the prior 4h median',
    (i) => i >= 16 && middle(D.trades, i, 16) > 0 && 2 * D.trades[i] <= 0.75 * middle(D.trades, i, 16)],
  [make('dimlevel'), 'candle_relation(volume(), is: above, right: prior_high(over: 4h, of: volume))', 'the candle sets a new 4h high in volume',
    (i) => i >= 16 && D.volume[i] > top(D.volume, i, 16)],
  [make('dimlevel', { side: 'low', dim: 'delta', over: '2h' }), 'candle_relation(delta(), is: below, right: prior_low(over: 2h, of: delta))', 'the candle sets a new 2h low in delta',
    (i) => i >= 8 && D.delta[i] < floor(D.delta, i, 8)],
  [make('dimlevel', { side: 'high', dim: 'size', over: '1h' }), 'candle_relation(size(), is: above, right: prior_high(over: 1h, of: size))', 'the candle sets a new 1h high in trade size',
    (i) => i >= 4 && D.size[i] > top(D.size, i, 4)],
];
const NEW = ['dimback', 'taker', 'dimx', 'dimxmax', 'dimlevel'];
assert.deepEqual([...new Set(CASES.map(([c]) => c.type))], NEW);
const same = (a, b) => assert.deepEqual({ type: a.type, args: a.args, not: !!a.not }, { type: b.type, args: b.args, not: !!b.not });
for (const [c, text, words, holds] of CASES) {
  const def = CLAUSES[c.type];
  assert.equal(clauseText(c), text);
  assert.equal(phraseText(c), words);
  // as a condition, affirmed and negated; and, where it is an event, as the pattern itself
  for (const not of [false, true]) {
    const line = Object.assign(clone(c), not ? { not } : {});
    const m = question([make('pattern', { p: 'hammer' })], [line]); const written = toText(m);
    assert.equal(written, `${HEAD}\nfind hammer\nwhere ${not ? 'not ' : ''}${text}\nmeasure close_return(after: [1h, 4h])`);
    const back = fromText(written).model;
    same(back.wheres[0], line);
    assert.equal(toText(back), written, 'text → model → text');
    assert.equal(check(written).ok, true, written);
  }
  assert.match(phraseText(Object.assign(clone(c), { not: true })), / not | no /);
  if (def.role === 'event') {
    const m = question([clone(c)]); const back = fromText(toText(m)).model;
    same(back.find.items[0], c); assert.equal(toText(back), toText(m));
  }
  // the engine answers it on the fixture exactly as this file counts it from the values
  const found = def.role === 'event' ? slots(`${HEAD}\nfind ${text}`) : slots(`${HEAD}\nfind ${ANY}\nwhere ${text}`);
  assert.deepEqual(found, every(holds), text);
  assert.ok(found.length > 20, `${text}: the fixture barely exercises it (${found.length})`);
  // and what it refers to is the dimension it names
  assert.deepEqual(dimensionsIn(`${HEAD}\nfind ${ANY}\nwhere ${text}`), [c.args.dim ?? c.args.by]);
}
ok(`${CASES.length} clauses print their exact text, read as one sentence, come back from the text as themselves affirmed and negated, and count on the fixture as their own values say`);

// Compared values make one run each, and come back as the same clause holding both.
{
  const sweeps = [
    [make('dimback', { rel: ['above', 'below'], back: ['1', '2'] }), 'candle_relation(volume(), is: {above | below}, right: volume(bars_ago: {1 | 2}))', 4],
    [make('taker', { side: ['above', 'below', 'equal'] }), 'candle_relation(delta(), is: {above | below | equal}, right: 0)', 3],
    [make('taker', { at: ['0', '1'] }), 'candle_relation(delta(bars_ago: {0 | 1}), is: above, right: 0)', 2],
    [make('dimx', { dim: ['volume', 'trades'], min: ['1.5', '2'] }), 'dimension_multiple({volume | trades}, over: 4h, min: {1.5 | 2})', 4],
    [make('dimxmax', { over: ['4h', '12h'] }), 'dimension_multiple(volume, over: {4h | 12h}, min: 0, max: 0.5)', 2],
    [make('dimlevel', { over: ['4h', '12h', '24h'] }), 'candle_relation(volume(), is: above, right: prior_high(over: {4h | 12h | 24h}, of: volume))', 3],
  ];
  for (const [c, text, runs] of sweeps) {
    assert.equal(clauseText(c), text);
    const written = `${HEAD}\nfind ${ANY}\nwhere ${text}`; const back = fromText(written).model.wheres[0];
    same(back, c); assert.equal(clauseText(back), text);
    assert.equal(answer(written).length, runs, text);
  }
  // a dimension that is written as a function name is one run: its slot does not take a second value
  for (const type of ['dimback', 'dimlevel']) assert.equal(CLAUSES[type].slots.find((s) => s.key === 'dim').sweep, false);
  assert.equal(CLAUSES.taker.slots.find((s) => s.key === 'by').sweep, false);
  ok('compared values print as choices, run once each, and come back as the same clause');
}

// What a clause cannot hold stays formal text, word for word: nothing is bent into a clause that says something else.
{
  const formal = [
    'candle_relation(volume(), is: above, right: volume(bars_ago: 7))',          // a lag the slot does not offer
    'candle_relation(volume(bars_ago: 1), is: above, right: volume(bars_ago: 2))',
    'candle_relation(volume(), is: unequal, right: volume(bars_ago: 1))',
    'candle_relation(delta(), is: at_or_above, right: 0)',                       // not one of the three sides
    'candle_relation(0, is: above, right: delta())',
    'candle_relation(volume(), is: above, right: prior_low(over: 4h, of: volume))',   // above the prior low is no new low
    'candle_relation(delta(), is: below, right: prior_high(over: 4h, of: delta))',
    'dimension_multiple(volume, over: 4h, min: 1, max: 2)',
  ];
  for (const text of formal) {
    const written = `${HEAD}\nfind ${ANY}\nwhere ${text}`; const back = fromText(written).model.wheres[0];
    assert.equal(back.type, 'raw', text); assert.equal(clauseText(back), text);
    assert.equal(check(written).ok, true, text);
  }
  // equal forms are read as the clause and printed in its one spelling
  const spelled = [['candle_relation(delta(bars_ago: 0), is: above, right: 0)', 'candle_relation(delta(), is: above, right: 0)'],
    ['candle_relation(imbalance(), is: below, right: 0.0)', 'candle_relation(imbalance(), is: below, right: 0)'],
    ['candle_relation(volume(), right: volume(bars_ago: 1))', 'candle_relation(volume(), is: above, right: volume(bars_ago: 1))'],
    ['dimension_multiple(over: 4h)', 'dimension_multiple(volume, over: 4h, min: 1.5)'],
    ['dimension_multiple(trades, min: 2)', 'dimension_multiple(trades, over: 4h, min: 2)'],
    ['candle_relation(trades(), is: below, right: prior_low(of: trades))', 'candle_relation(trades(), is: below, right: prior_low(over: 4h, of: trades))']];
  for (const [typed, printed] of spelled) {
    const a = `${HEAD}\nfind ${ANY}\nwhere ${typed}`; const b = `${HEAD}\nfind ${ANY}\nwhere ${printed}`;
    assert.equal(clauseText(fromText(a).model.wheres[0]), printed, typed);
    assert.deepEqual(slots(a), slots(b), typed);
  }
  // the price clauses still read as they did
  assert.equal(fromText(`${HEAD}\nfind candle_relation(price(close), is: above, right: price(high, bars_ago: 1))`).model.find.items[0].type, 'relation');
  assert.equal(fromText(`${HEAD}\nfind hammer\nwhere range_multiple(over: 4h, min: 1.5)`).model.wheres[0].type, 'rangex');
  ok('what no clause holds stays formal text word for word, and an equal spelling is read as the clause that means the same');
}

// ---------------------------------------------------------------- availability on both kinds of recording
{
  const base = Object.keys(CLAUSES).filter((type) => !NEW.includes(type));
  for (const type of NEW) { assert.equal(offered(type, cube.rec.hasCounters), true, type); assert.equal(offered(type, pinned.rec.hasCounters), false, type); }
  for (const type of base) { assert.equal(offered(type, cube.rec.hasCounters), true, type); assert.equal(offered(type, pinned.rec.hasCounters), true, type); assert.equal(CLAUSES[type].needs, undefined, type); }
  // On the pinned recording the conditions offered are exactly the sixteen offered before there were dimensions.
  const before = ['share', 'rangex', 'sharemax', 'weekday', 'tail', 'trend', 'trend', 'quiet', 'near', 'near', 'reclaim', 'breakout', 'pattern', 'pattern', 'relation', 'wickrej'];
  assert.deepEqual(OFFERS.filter((c) => offered(c.type, pinned.rec.hasCounters)).map((c) => c.type), before);
  const here = OFFERS.filter((c) => offered(c.type, cube.rec.hasCounters));
  assert.deepEqual(here.filter((c) => !CLAUSES[c.type].needs).map((c) => c.type), before);
  assert.deepEqual([...new Set(here.filter((c) => CLAUSES[c.type].needs).map((c) => c.type))], ['dimx', 'taker', 'dimback', 'dimlevel']);
  for (const c of here) assert.equal(check(toText(question([make('pattern', { p: 'hammer' })], [c]))).ok, true, clauseText(c));
  ok('with counters all five clauses are offered; without them none is, and the sixteen conditions offered before are offered unchanged');

  const baseAnswers = PRESETS.map(p => slots(toText(fromText(p.text).model)));
  await load();
  for (const [c, text] of CASES) {
    const written = toText(question([make('pattern', { p: 'hammer' })], [c]));
    const a = check(written);
    assert.equal(a.ok, false, text);
    assert.ok(a.errors.every((e) => e.kind === 'capability'), `${text}: ${JSON.stringify(a.errors)}`);
    assert.match(a.errors[0].message, /counters/);
    same(fromText(written).model.wheres[0], c);
  }
  const unmapped = 'candle_relation(delta(bars_ago: 1, extra: 2), is: above, right: 0)';
  const deferred = `${HEAD}\nfind ${unmapped}`;
  assert.equal(check(deferred).errors[0].kind, 'capability');
  assert.equal(fromText(deferred).model.find.items[0].type, 'raw');
  assert.equal(toText(fromText(deferred).model), deferred);
  for (const [i, p] of PRESETS.entries()) {
    const text = toText(fromText(p.text).model);
    assert.deepEqual(dimensionsIn(text), [], p.id);
    assert.equal(lanesParam(dimensionsIn(text), {}), null);
    assert.deepEqual(slots(text), baseAnswers[i], p.id);
  }

  // Exercise the real refusal renderer without booting the page or drawing its surrounding panels.
  const bench = await readFile(new URL('../bench/bench.js', import.meta.url), 'utf8');
  const source = bench.match(/^function renderRefused\(text, res\) \{[\s\S]*?^\}/m)[0];
  const element = () => ({ style: {}, classList: { remove() {} }, replaceChildren() {}, append() {}, remove() {} });
  const elements = new Map(); const nodes = new Map();
  const $ = (selector) => { if (!elements.has(selector)) elements.set(selector, element()); return elements.get(selector); };
  const model = question([make('taker')]); const text = toText(model); const res = run(text);
  assert.equal(res.ok, false); assert.equal(res.errors.length, 1); assert.equal(res.errors[0].kind, 'capability');
  const { message, hint } = res.errors[0]; const refusalText = message + (hint ? ` (${hint})` : '');
  const state = { model, notice: '' };
  const formal = { el: { querySelector: () => null }, set(_text, error) { this.error = error; } };
  const renderRefused = runInNewContext(`(${source})`, {
    state, ctx: null, $, nodes, formal, document: {}, ui: {}, addInput: {},
    run, HEAD, ANY_CLOSE: ANY, clauseText, phraseText, cap: (s) => s, label: (s) => s,
    closePopover() {}, hideAdd() {}, renderBars() {}, layoutDims() {}, renderLeft() {}, renderDrawer() {},
    h() {}, mount() {}, quiet() {},
    nodeFor(id) {
      if (!nodes.has(id)) nodes.set(id, { el: element(), note: {}, head: element(), svgHost: element(), track: element() });
      return nodes.get(id);
    },
  });
  for (const notice of [
    'The cube could not be read (cube: 503); this question needs its bars',
    'That window could not be read: window unavailable',
    '',
  ]) {
    state.notice = notice;
    renderRefused(text, res);
    assert.equal($('#status').textContent, notice ? `${notice} · ${refusalText}` : refusalText);
    assert.equal($('#status').className, 'err');
    assert.equal(formal.error, refusalText);
  }
  ok('a refused question shows automatic and later window failures beside the engine refusal, or only the refusal when there is no notice');

  await load('fixture');
  ok(`the engine refuses all ${CASES.length} forms on the pinned recording and the starting answers are equal`);

}

// ---------------------------------------------------------------- a g1 code with dimension parts
{
  const code = 'g1:o:4,5,6,7,d;0,1,2,3,d|volume:0,1|delta:0,2/1';
  assert.equal(g1Price(code), 'g1:o:4,5,6,7,d;0,1,2,3,d');
  assert.deepEqual(g1Parts(code).map((p) => [p.key, p.text, p.order]), [['volume', 'volume:0,1', 'bar 1 < bar 2'], ['delta', 'delta:0,2/1', 'bar 1 < zero < bar 2']]);
  assert.deepEqual(g1Parts('g1:u:0,1,2,3;0,1,2,3;0,1,2,3|volume:0,0,1|delta:2,0,1/1').map((p) => p.order), ['bar 1 = bar 2 < bar 3', 'bar 2 < bar 3 = zero < bar 1']);
  assert.deepEqual(g1Parts('g1:o:0,1,2,3,u|delta:1/0').map((p) => p.order), ['zero < bar 1']);
  assert.deepEqual(g1Parts('g1:o:0,1,2,3,u|trades:0|size:0|imbalance:0/1').map((p) => [p.key, p.order]), [['trades', 'bar 1'], ['size', 'bar 1'], ['imbalance', 'bar 1 < zero']]);
  assert.deepEqual(g1Parts('g1:o:0,1,3,4,u;2,3,5,6,u'), []);
  assert.deepEqual(g1Parts('g1:o:0,1,3,4,u;2,3,5,6,u|flow:0,1'), [], 'a part the engine does not know is not presented as one');
  for (const [event, recorded] of [['chained_g1', false], ['exact_g1', true]]) {
    const written = `${HEAD}\nfind ${event}(${JSON.stringify(code)})`; const item = fromText(written).model.find.items[0];
    assert.deepEqual([item.type, item.args.g1, item.args.recorded, drawingBars(item), drawingDimensions(item)], ['drawing', code, recorded, 2, 'volume and delta']);
    assert.equal(clauseText(item), `${event}(${JSON.stringify(code)})`);
    assert.equal(phraseText(item), `a drawn shape of 2 bars with volume and delta${recorded ? ', opens as recorded' : ''}`);
    assert.deepEqual(dimensionsIn(written), ['volume', 'delta'], 'its lanes are the ones its parts switch on');
    assert.equal(check(written).ok, true);
    await load();
    const refused = check(written);
    assert.equal(refused.ok, false); assert.equal(refused.errors[0].kind, 'capability'); assert.match(refused.errors[0].message, /counters/);
    await load('fixture');
  }
  const drawable = "g1:o:0,1,3,4,u;2,3,5,6,u|volume:0,1|delta:0,2/1";
  const packet = packetFromG1(drawable);
  assert.ok(packet);
  assert.equal(drawingG1(packet), drawable);
  assert.deepEqual(readLink(`?drawing=${encodeURIComponent(JSON.stringify(packet))}`).packet, packet);
  const i = 9; const dimensions = ['volume', 'delta'];
  const drawn = casePacket(cube.rec, i, 2, dimensions);
  assert.ok(drawn.packet, drawn.why);
  assert.equal(drawingG1(drawn.packet), engine.at(i, 2, { reading: 'chained', dimensions }).code);
  assert.equal(casePacket(cube.rec, i, 2).packet.revision, engine.drawingProtocol().plain);
  assert.ok(!('dimensions' in casePacket(cube.rec, i, 2, []).packet));
  assert.equal(phraseText(fromText(`${HEAD}\nfind chained_g1("g1:o:0,1,3,4,u;2,3,5,6,u")`).model.find.items[0]), 'a drawn shape of 2 bars');
  assert.equal(slots(`${HEAD}\nfind chained_g1("g1:o:0,1,3,4,u;2,3,5,6,u")`).length, 1463);
  // and a part is a refinement: its closes are among the price shape's
  const all = new Set(slots(`${HEAD}\nfind chained_g1("g1:o:0,1,3,4,u;2,3,5,6,u")`));
  const risen = slots(`${HEAD}\nfind chained_g1("g1:o:0,1,3,4,u;2,3,5,6,u|volume:0,1")`);
  assert.ok(risen.length > 0 && risen.length < all.size && risen.every((i) => all.has(i) && D.volume[i] > D.volume[i - 1]));
  ok('a g1 code with dimension parts reads as a shape with those dimensions, each part in order from lowest to highest, and is refused without counters');

  // Composer searches the drawing as a chain. Give both entry points the same
  // grid and compare every exact close, including with ordinal activity.
  engine.loadComposerFrame(csv, cube.rec.barMs);
  const base = g1Price(drawable);
  for (const pattern of [base, base + '|volume:0,1', drawable]) {
    const link = readLink(`?drawing=${encodeURIComponent(JSON.stringify(packetFromG1(pattern)))}&g1=${encodeURIComponent(pattern)}`);
    assert.equal(link.error, undefined);
    assert.equal(link.g1, pattern);
    const text = toText(question([make('drawing', { g1: link.g1, packet: link.packet })]));
    assert.ok(text.includes(`find chained_g1(${JSON.stringify(pattern)})`));
    const expected = slots(text);
    assert.ok(expected.length > 0, pattern);

    engine.composerStart(link.packet, { timeframes: 1 });
    while (!engine.composerStep(4096).done) {}
    const { starts, spans } = engine.composerPositionsPacked(cube.rec.barMs, { kind: 'exact' });
    const closes = Array.from(starts, (start, i) => start + spans[i] - 1).sort((a, b) => a - b);
    assert.deepEqual(closes, expected, pattern);
  }
  ok('Query and Composer return the same exact closes on one recording for price, volume and delta patterns');
}

// ---------------------------------------------------------------- what a question refers to
{
  const refers = [
    ['find hammer', []],
    ['find hammer\nwhere candle_relation(price(close), is: above, right: prior_high(over: 4h))', []],
    ['find hammer\nwhere candle_relation(price(close), is: above, right: prior_high(over: 4h))\nwhere candle_relation(trades(), is: above, right: trades(bars_ago: 1))', ['trades']],
    ['find candle_relation(imbalance(), is: below, right: 0) and candle_relation(volume(), is: above, right: volume(bars_ago: 1))', ['volume', 'imbalance']],
    ['find hammer\nwhere dimension_multiple(over: 4h, min: 2)', ['volume']],
    ['find hammer\nwhere dimension_multiple({size | trades}, over: 4h, min: 2)', ['trades', 'size']],
    ['let d = size\nfind hammer\nwhere dimension_multiple(d, over: 4h, min: 2)', ['size']],
    ['find hammer\nwhere not candle_relation(delta(bars_ago: 2), is: above, right: 0)', ['delta']],
    ['find hammer\ngroup by candle_relation(delta(), is: above, right: 0)', ['delta']],
    ['find exact_g1("g1:o:0,1,2,3,u|trades:0|size:0|imbalance:0/1")', ['trades', 'size', 'imbalance']],
  ];
  for (const [body, dims] of refers) {
    const text = `${HEAD}\n${body}`;
    assert.deepEqual(dimensionsIn(text), dims, body);
    assert.equal(check(text).ok, true, body);
    await load();
    assert.equal(check(text).ok, dims.length === 0, body);
    await load('fixture');
  }
  assert.deepEqual(dimensionsIn('find ('), [], 'text that does not parse refers to nothing');
  ok('the dimensions a question refers to are read from its text: readings, levels, medians, choices, bindings and g1 parts');
}

// ---------------------------------------------------------------- the lanes: which are shown, and the address
{
  const used = ['volume', 'delta'];
  assert.deepEqual(lanesShown(used, {}), ['volume', 'delta'], 'a lane the question refers to is shown by default');
  assert.deepEqual(lanesShown([], {}), []);
  const set = {};
  setLane(set, used, 'trades', true); assert.deepEqual(lanesShown(used, set), ['volume', 'trades', 'delta']);
  setLane(set, used, 'volume', false); assert.deepEqual(lanesShown(used, set), ['trades', 'delta']);
  setLane(set, used, 'volume', true); assert.deepEqual(set, { trades: true }, 'a switch put back is no longer a choice of its own');
  setLane(set, used, 'trades', false); assert.deepEqual(set, {});
  // every set of switches, for every set of dimensions a question could refer to, comes back from the address
  const keys = DIMENSIONS.map((d) => d.key); const subsets = Array.from({ length: 32 }, (_, bits) => keys.filter((_, k) => bits & (1 << k)));
  let links = 0;
  for (const refs of subsets) for (const shown of subsets) {
    const thrown = {}; for (const d of keys) setLane(thrown, refs, d, shown.includes(d));
    assert.deepEqual(lanesShown(refs, thrown), shown);
    const param = lanesParam(refs, thrown);
    assert.equal(param === null, refs.length === 0 && shown.length === 0);
    if (param !== null) { assert.match(param, /^[a-z,]*$/); assert.equal(new URLSearchParams(`q=x&w=30d&ln=${param}`).get('ln'), param); }
    const back = lanesFromParam(param, refs);
    assert.deepEqual(lanesShown(refs, back), shown, `refers to ${refs}, shows ${shown}`); links++;
    // and a dimension the question comes to refer to later is still shown by default
    for (const d of keys) if (!refs.includes(d) && !shown.includes(d)) assert.equal(lanesShown([...refs, d], back).includes(d), true);
  }
  assert.deepEqual(lanesFromParam('volume,flow,delta', []), { volume: true, delta: true }, 'a name the bench does not know is passed over');
  assert.deepEqual(lanesShown(['volume'], lanesFromParam('', ['volume'])), [], 'an empty list hides the lane the question refers to');
  assert.deepEqual(lanesFromParam(null, ['volume']), {});
  ok(`the lanes on show are the ones referred to and the ones switched on, less the ones switched off, and all ${links.toLocaleString('en-US')} combinations come back from the address`);
}

// ---------------------------------------------------------------- the lanes: each candle's value
{
  const rec = cube.rec; const lead = 8; const H = 16;
  // one close: every column is that candle's own recorded value
  for (const d of DIMENSIONS) for (const i of [0, 5, 39, 40, 2000, rec.n - 3]) {
    const one = dimensionColumns(rec, [i], lead, H, d.key);
    assert.equal(one.single, true); assert.equal(one.signed, d.signed); assert.equal(one.cols.length, lead + H + 1);
    one.cols.forEach((col, q) => {
      const j = i + q - lead; const there = j >= 0 && j < rec.n && !Number.isNaN(D[d.key][j]);
      assert.equal(col.k, q - lead); assert.equal(col.n, there ? 1 : 0);
      if (there) assert.equal(col.v, D[d.key][j]); else assert.equal(col.v, null);
    });
  }
  // a bar without trades has a volume and a delta of zero, and no trade size or imbalance: its column is empty, not zero
  assert.equal(dimensionColumns(rec, [39], 0, 0, 'delta').cols[0].v, 0);
  assert.equal(dimensionColumns(rec, [39], 0, 0, 'size').cols[0].n, 0);
  // many closes: the median of the values at each offset, counted over the candles that have one
  const closes = slots(`${HEAD}\nfind hammer`);
  for (const d of DIMENSIONS) {
    const agg = dimensionColumns(rec, closes, lead, H, d.key);
    assert.equal(agg.single, false);
    for (const col of agg.cols) {
      const xs = closes.map((i) => i + col.k).filter((j) => j >= 0 && j < rec.n && !Number.isNaN(D[d.key][j])).map((j) => D[d.key][j]).sort((a, b) => a - b);
      assert.equal(col.n, xs.length);
      const mid = xs.length >> 1; const median = xs.length % 2 ? xs[mid] : (xs[mid - 1] + xs[mid]) / 2;
      assert.ok(Math.abs(col.v - median) <= 1e-9 * Math.max(1, Math.abs(median)), `${d.key} at ${col.k}`);
      assert.ok(col.q1 <= col.v && col.v <= col.q3);
    }
  }
  // a question that asks for heavy volume shows it: the deciding column stands above the columns beside it
  const heavy = dimensionColumns(rec, slots(`${HEAD}\nfind ${ANY}\nwhere dimension_multiple(volume, over: 4h, min: 1.5)`), lead, H, 'volume');
  assert.ok(heavy.cols[lead].v > heavy.cols[lead - 1].v && heavy.cols[lead].v > heavy.cols[lead + 1].v);
  const selling = dimensionColumns(rec, slots(`${HEAD}\nfind candle_relation(delta(), is: below, right: 0)`), lead, H, 'delta');
  assert.ok(selling.cols[lead].v < 0, 'net selling closes sit below the zero line at the close');
  // the recording without counters has nothing to show
  assert.equal(pinned.rec.dimension('volume'), null);
  // figures
  assert.deepEqual([dimensionText('volume', 1920000), dimensionText('volume', 84500), dimensionText('delta', -312000.4), dimensionText('delta', 0), dimensionText('trades', 4210), dimensionText('trades', 350.5),
    dimensionText('size', 456.2), dimensionText('size', 12.345), dimensionText('imbalance', 0.1234), dimensionText('imbalance', -0.4), dimensionText('size', NaN), dimensionText('volume', null)],
  ['1.92M', '84.5K', '−312.0K', '0', '4,210', '350.5', '456', '12.35', '+0.123', '−0.400', '—', '—']);
  assert.deepEqual([dimensionExact('volume', 1920000.5), dimensionExact('delta', -312000.4), dimensionExact('trades', 4210), dimensionExact('imbalance', -0.4), dimensionExact('size', NaN)],
    ['1,920,000.50', '−312,000.40', '4,210', '−0.4000', '—']);
  ok('a lane holds each candle’s own value for one close and the median over many, leaves a candle without the value out, and shows what the question asks for');
}

console.log(`${checks} checks passed`);
