// The shape hand-off with the Composer bench, checked on the pinned recording without a browser.
// A carried drawing must ask the engine exactly what the study page asks for the same drawing, the vocabulary must
// keep it through text and back, and what is sent to Composer must be a packet the engine's own decoder accepts.
// Run from the repository root, after study/prepare_recording.py: node query/verify/handoff.mjs
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { pathToFileURL } from 'node:url';

// The bench's modules import by site path. Here those paths are the repository's folders.
register('data:text/javascript,' + encodeURIComponent(`
  const root = ${JSON.stringify(pathToFileURL(process.cwd() + '/').href)};
  export function resolve(spec, context, next) {
    if (spec.startsWith('/study/')) return { url: new URL(spec.slice(1), root).href, shortCircuit: true };
    if (spec.startsWith('/shared/') || spec.startsWith('/bench/')) return { url: new URL('query' + spec, root).href, shortCircuit: true };
    return next(spec, context);
  }`), import.meta.url);

const { make, clone, toText, fromText, clauseText, phraseText, drawingBars, drawingHeld } = await import('/shared/vocab.js');
const { readLink, packetFromG1, casePacket, composerLink, relationsOf, decodeDrawing, drawingG1, pinnedExpression } = await import('/shared/handoff.js');
const { encodeDrawing, COMPOSER_REVISION } = await import('/study/composer/drawing.js');
const { loadEnvironment } = await import('/study/verify/node-env.js');
const { analyze } = await import('/study/src/check.js');
const { runAnalysis } = await import('/study/src/engine.js');
const { g1FromRecording } = await import('/study/src/g1.js');

const e = loadEnvironment();
const matches = (text) => { const a = analyze(text, e.env); assert.equal(a.ok, true, `${text}\n${JSON.stringify(a.errors)}`); return runAnalysis(e.ctx, a, { digestVerified: e.digestVerified }).results[0].matches.length; };
const packet = (bars, pins = [], extra = {}) => ({ version: 1, revision: COMPOSER_REVISION, oriented: true, bars, pins, skeleton: 0, stretch: 0, next: { dir: 0, measure: 'any', bps: 10, atr: 1 }, limit: 12, ...extra });
const link = (p, held) => `?drawing=${encodeURIComponent(JSON.stringify(p))}&g1=${encodeURIComponent(drawingG1(p))}${held ? '&pin-relations=1' : ''}`;
const question = (r) => ({ find: { join: 'or', items: [make('drawing', { g1: r.g1, packet: r.packet, held: r.held })] }, wheres: [], split: null, horizons: [] });

// ---- the two answers the study page is held to (study/verify/geometry-study.js, candle-native.mjs)
const one = packet([{ v: [15, 50, 85, 85], d: 'u' }]);
const two = packet([{ v: [15, 20, 40, 50], d: 'u' }, { v: [30, 40, 60, 85], d: 'u' }], [{ a: { bar: 0, part: 'H' }, b: { bar: 1, part: 'H' } }, { bar: 1, color: true }]);
const PINS = 'candle_window(candle_relation(price(high, bars_ago: 1), is: below, right: price(high, bars_ago: 0)) and candle_relation(price(close, bars_ago: 0), is: above, right: price(open, bars_ago: 0)), bars: 2)';

const exact = readLink(link(one, false));
assert.equal(exact.g1, 'g1:o:0,1,2,2,u');
assert.equal(clauseText(question(exact).find.items[0]), 'exact_g1("g1:o:0,1,2,2,u")');
assert.equal(matches(toText(question(exact))), 324, 'the one-bar exact shape');
assert.equal(matches(toText(question(readLink('?g1=' + encodeURIComponent('g1:o:0,1,2,2,u'))))), 324, 'a g1 alone asks the same');

const held = readLink(link(two, true));
assert.equal(held.held, true);
assert.equal(clauseText(question(held).find.items[0]), PINS, 'pins read as the study page reads them');
assert.equal(matches(toText(question(held))), 4828, 'the two pinned relations');
// without pin-relations the same drawing is its exact shape, and the engine agrees with its own g1 text
const shape = readLink(link(two, false));
assert.equal(shape.held, false);
assert.equal(matches(toText(question(shape))), matches('on BTCUSDT 15m\nfind exact_g1("g1:o:0,1,3,4,u;2,3,5,6,u")'));
// a drawing that holds nothing cannot be asked as held relations, whatever the link says
assert.equal(readLink(link(one, true)).held, false);

// ---- a link that cannot be read says so and names nothing
for (const bad of ['?drawing=' + encodeURIComponent('{"version":1,"revision":"nope"}'), '?drawing=not-json', link(two, true).replace('g1%3Ao%3A0', 'g1%3Ao%3A9'), '?g1=g2:x']) assert.ok(readLink(bad).error, bad);
assert.equal(readLink(''), null); assert.equal(readLink('?pattern=hammer'), null);

// ---- the vocabulary keeps a drawn shape through text and back
for (const r of [exact, held, shape]) {
  const m = question(r); m.horizons = ['1h', '4h']; const text = toText(m); const back = fromText(text).model;
  assert.equal(toText(back), text, 'text → model → text');
  assert.equal(drawingBars(m.find.items[0]), r.packet.bars.length);
}
// exact_g1 text is a drawn shape again, with the bars its g1 names; a pinned expression is formal text until its packet returns
const typed = fromText('on BTCUSDT 15m\nfind exact_g1("g1:o:0,1,3,4,u;2,3,5,6,u")').model.find.items[0];
assert.deepEqual([typed.type, typed.args.g1, typed.args.packet, drawingBars(typed)], ['drawing', 'g1:o:0,1,3,4,u;2,3,5,6,u', null, 2]);
assert.equal(fromText('on BTCUSDT 15m\nfind ' + PINS).model.find.items[0].type, 'raw');
assert.equal(clauseText(fromText('on BTCUSDT 15m\nfind ' + PINS).model.find.items[0]), clauseText(question(held).find.items[0]), 'so the bench can put the packet back on it');
// negation and a clone leave it whole
const not = question(held).find.items[0]; not.not = true;
assert.equal(clauseText(not), `not (${PINS})`); assert.equal(clauseText(clone(not)), clauseText(not)); assert.equal(drawingHeld(clone(not)), true);
assert.match(phraseText(question(held).find.items[0]), /relations held on a drawn shape of 2 bars/);
assert.deepEqual(relationsOf(two), ['bar 1 high below bar 2 high', 'bar 2 closes above its open']);
assert.equal(relationsOf(two).length, pinnedExpression(two).split(' and ').length, 'one phrase per rule');

// ---- what goes to Composer is a packet the engine's decoder accepts
const rebuilt = packetFromG1('g1:o:0,1,3,4,u;2,3,5,6,u');
assert.equal(rebuilt.coordinates, 'ordinal'); assert.equal(drawingG1(rebuilt), 'g1:o:0,1,3,4,u;2,3,5,6,u'); encodeDrawing(rebuilt);
assert.equal(packetFromG1('g1:u:0,1,2,3;1,2,3,4'), null, 'no directions: not a drawing');
assert.equal(packetFromG1('g1:o:0,1,2,3,u;4,5,6,7,u'), null, 'an opening gap: not a drawing');
assert.equal(packetFromG1('nonsense'), null);
assert.ok(composerLink('http://x/bench/', rebuilt).startsWith('http://x/bench/?drawing=%7B'));

// ---- recorded candles as a drawing. A recorded bar often opens a cent away from the previous close and a drawn bar
// never does, so later opens are joined to the close before them. Where nothing had to move, the drawing is the
// recording's own candles and its g1 is the one the engine reads there, so the window it came from matches it.
const rec = e.rec; let sent = 0; let whole = 0; let moved = 0;
const cents = (b) => b.v.map((x) => Math.round(x * 100));
for (let i = 40; i < rec.n && sent < 1200; i += 7) for (const n of [2, 3, 5]) {
  const r = casePacket(rec, i, n);
  assert.ok(r.packet, `the ${n} candles ending at slot ${i}: ${r.why}`);
  sent++; encodeDrawing(r.packet);
  r.packet.bars.forEach((b, k) => {
    const s = i - n + 1 + k; const open = k ? rec.C[s - 1] : rec.O[s]; const [low, bottom, top, high] = cents(b);
    assert.deepEqual([bottom, top], [Math.min(open, rec.C[s]), Math.max(open, rec.C[s])], 'a body from the close before it to its own close');
    assert.deepEqual([low, high], [Math.min(rec.L[s], bottom), Math.max(rec.H[s], top)], 'shadows as recorded, reaching at least the body');
  });
  const offs = []; for (let s = i - n + 2; s <= i; s++) if (rec.O[s] !== rec.C[s - 1]) offs.push(Math.abs(rec.O[s] - rec.C[s - 1]));
  assert.equal(r.joined, offs.length); assert.equal(Math.round(r.far * 100), Math.max(0, ...offs));
  if (r.joined) { moved++; continue; }
  whole++;
  assert.equal(drawingG1(r.packet), g1FromRecording(rec, i, n), `g1 of the ${n} candles ending at slot ${i}`);
  if (whole <= 60) assert.ok(matches(`on BTCUSDT 15m\nfind exact_g1(${JSON.stringify(drawingG1(r.packet))})`) >= 1, 'the window it was drawn from matches it');
}
assert.ok(whole >= 200 && moved >= 200, `${whole} whole, ${moved} joined`);
assert.ok(casePacket(rec, 0, 2).why);
const gap = Array.from(rec.present).findIndex((x, k) => k > 5 && !x);
if (gap > 5) assert.equal(casePacket(rec, gap + 1 < rec.n ? gap + 1 : gap, 3).why, 'a candle is missing from the recording');

console.log(`Hand-off: 324 and 4,828 as the study page counts them, text round-trips, ${sent} recorded windows drawn (${whole} as recorded, ${moved} with an open joined to the previous close).`);
