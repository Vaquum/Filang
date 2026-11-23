// The shape hand-off with the Composer bench, checked on the pinned recording without a browser.
// A carried drawing must ask the engine exactly what the study page asks for the same drawing, the vocabulary must
// keep it through text and back, and what is sent to Composer must be a packet the engine's own decoder accepts.
// Run from the repository root, after study/prepare_recording.py and bindings/build.py: node query/verify/handoff.mjs
import assert from 'node:assert/strict';
import { install } from './site.mjs';

// The bench's modules import by site path and ask the shared engine, as they do in the page.
await install();
const { engine, load, run, rec: recording, drawingRevision } = await import('/shared/filang.js');
const { make, clone, toText, fromText, clauseText, phraseText, drawingBars, drawingHeld, drawingRecorded } = await import('/shared/vocab.js');
const { readLink, packetFromG1, casePacket, composerLink, relationsOf, attach, drawingG1, pinnedExpression } = await import('/shared/handoff.js');

await load();
const COMPOSER_REVISION = drawingRevision();
const encodeDrawing = (p) => engine.encodeDrawing(p);
const answer = (text) => { const a = run(text); assert.equal(a.ok, true, `${text}\n${JSON.stringify(a.errors)}`); return a.results[0].matches; };
const matches = (text) => answer(text).length;
const slotsOf = (text) => new Set(answer(text).map((r) => r.i));
const packet = (bars, pins = [], extra = {}) => ({ version: 1, revision: COMPOSER_REVISION, oriented: true, bars, pins, skeleton: 0, stretch: 0, next: { dir: 0, measure: 'any', bps: 10, atr: 1 }, limit: 12, ...extra });
const link = (p, held) => `?drawing=${encodeURIComponent(JSON.stringify(p))}&g1=${encodeURIComponent(drawingG1(p))}${held ? '&pin-relations=1' : ''}`;
const question = (r) => ({ find: { join: 'or', items: [make('drawing', { g1: r.g1, packet: r.packet, held: r.held, recorded: !!r.recorded })] }, wheres: [], split: null, horizons: [] });
const asRecorded = (r) => ({ ...r, recorded: true });

// ---- the answers the engine's own verification pins (study/verify/geometry-study.js, candle-native.mjs). A drawn
// shape is asked as a chain, chained_g1; the same shape with its opens as recorded is exact_g1; one bar reads the same
// either way; and the relations pinned on a drawing still read recorded opens.
const one = packet([{ v: [15, 50, 85, 85], d: 'u' }]);
const two = packet([{ v: [15, 20, 40, 50], d: 'u' }, { v: [30, 40, 60, 85], d: 'u' }], [{ a: { bar: 0, part: 'H' }, b: { bar: 1, part: 'H' } }, { bar: 1, color: true }]);
const PINS = 'candle_window(candle_relation(price(high, bars_ago: 1), is: below, right: price(high, bars_ago: 0)) and candle_relation(price(close, bars_ago: 0), is: above, right: price(open, bars_ago: 0)), bars: 2)';

const exact = readLink(link(one, false));
assert.equal(exact.g1, 'g1:o:0,1,2,2,u');
assert.equal(clauseText(question(exact).find.items[0]), 'chained_g1("g1:o:0,1,2,2,u")');
assert.equal(matches(toText(question(exact))), 324, 'the one-bar shape');
assert.equal(clauseText(question(asRecorded(exact)).find.items[0]), 'exact_g1("g1:o:0,1,2,2,u")');
assert.equal(matches(toText(question(asRecorded(exact)))), 324, 'one bar has no later open: as recorded it is the same shape');
assert.equal(drawingRecorded(question(asRecorded(exact)).find.items[0]), false, 'so a one-bar shape is never shown as "as recorded"');
assert.equal(matches(toText(question(readLink('?g1=' + encodeURIComponent('g1:o:0,1,2,2,u'))))), 324, 'a g1 alone asks the same');

const held = readLink(link(two, true));
assert.equal(held.held, true);
assert.equal(clauseText(question(held).find.items[0]), PINS, 'pins read as the study page reads them');
assert.equal(matches(toText(question(held))), 4828, 'the two pinned relations');
// without pin-relations the same drawing is its shape, read as the chain it is drawn as; as recorded it is the
// stricter reading, which needs the second bar to have opened on the first one's close to the cent
const shape = readLink(link(two, false));
assert.equal(shape.held, false);
assert.equal(clauseText(question(shape).find.items[0]), 'chained_g1("g1:o:0,1,3,4,u;2,3,5,6,u")');
assert.equal(matches(toText(question(shape))), 1463, 'the two-bar shape, chained');
assert.equal(clauseText(question(asRecorded(shape)).find.items[0]), 'exact_g1("g1:o:0,1,3,4,u;2,3,5,6,u")');
assert.equal(matches(toText(question(asRecorded(shape)))), 772, 'the two-bar shape, as recorded');
assert.equal(drawingRecorded(question(asRecorded(shape)).find.items[0]), true);
// a drawing that holds nothing cannot be asked as held relations, whatever the link says
assert.equal(readLink(link(one, true)).held, false);

// the same four questions in one batch, as the bench counts what a change would leave
assert.deepEqual(engine.studyCounts([exact, held, shape, asRecorded(shape)].map((r) => toText(question(r)))), [324, 4828, 1463, 772].map((count) => ({ count, error: null })));

// ---- a link that cannot be read says so and names nothing
for (const bad of ['?drawing=' + encodeURIComponent('{"version":1,"revision":"nope"}'), '?drawing=not-json', link(two, true).replace('g1%3Ao%3A0', 'g1%3Ao%3A9'), '?g1=g2:x']) assert.ok(readLink(bad).error, bad);
assert.equal(readLink(''), null); assert.equal(readLink('?pattern=hammer'), null);

// ---- the vocabulary keeps a drawn shape through text and back
for (const r of [exact, asRecorded(exact), held, shape, asRecorded(shape)]) {
  const m = question(r); m.horizons = ['1h', '4h']; const text = toText(m); const back = fromText(text).model;
  assert.equal(toText(back), text, 'text → model → text');
  assert.equal(drawingBars(m.find.items[0]), r.packet.bars.length);
  // and the packet finds its place again in whichever of the three forms the text asks
  attach(back, r.packet);
  const item = back.find.items[0];
  assert.deepEqual([back.find.items.length, item.type, item.args.packet, drawingHeld(item), drawingRecorded(item)],
    [1, 'drawing', r.packet, drawingHeld(m.find.items[0]), drawingRecorded(m.find.items[0])]);
  assert.equal(toText(back), text);
}
// either g1 event typed by hand is a drawn shape again, with the bars its g1 names and the reading its name says:
// chained_g1 the chain, exact_g1 the opens as recorded, so an older link keeps its meaning and its count
const typed = fromText('on BTCUSDT 15m\nfind exact_g1("g1:o:0,1,3,4,u;2,3,5,6,u")').model.find.items[0];
assert.deepEqual([typed.type, typed.args.g1, typed.args.packet, drawingBars(typed), drawingRecorded(typed)], ['drawing', 'g1:o:0,1,3,4,u;2,3,5,6,u', null, 2, true]);
const chain = fromText('on BTCUSDT 15m\nfind chained_g1("g1:o:0,1,3,4,u;2,3,5,6,u")').model.find.items[0];
assert.deepEqual([chain.type, chain.args.g1, chain.args.packet, drawingBars(chain), drawingRecorded(chain)], ['drawing', 'g1:o:0,1,3,4,u;2,3,5,6,u', null, 2, false]);
assert.match(phraseText(typed), /a drawn shape of 2 bars, opens as recorded/); assert.match(phraseText(chain), /a drawn shape of 2 bars$/);
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

// ---- recorded candles as a drawing. A drawing is a chain and so is the reading: the first bar as recorded, each
// later bar opening at the close before it. So for every window sent, whether or not a recorded open differs from
// that close, the drawing's g1 is the window's chained code and the window is a match of the shape drawn from it.
// Where no open differs, it is also the recording's own candles and the code the as-recorded reading gives.
const rec = recording(); let sent = 0; let whole = 0; let moved = 0;
const found = new Map();   // the closes that match a chained code, asked of the engine once per code
const chainedAt = (code) => { if (!found.has(code)) found.set(code, slotsOf(`on BTCUSDT 15m\nfind chained_g1(${JSON.stringify(code)})`)); return found.get(code); };
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
  const code = drawingG1(r.packet);
  assert.equal(code, engine.at(i, n, { reading: 'chained' }).code, `the chained code of the ${n} candles ending at slot ${i}`);
  assert.ok(chainedAt(code).has(i), `the ${n} candles ending at slot ${i} match the shape drawn from them`);
  if (r.joined) { moved++; continue; }
  whole++;
  assert.equal(code, engine.at(i, n, { reading: 'recorded' }).code, `as recorded, the same code for the ${n} candles ending at slot ${i}`);
}
assert.ok(whole >= 200 && moved >= 200, `${whole} whole, ${moved} joined`);
assert.ok(casePacket(rec, 0, 2).why);
const gap = Array.from(rec.present).findIndex((x, k) => k > 5 && !x);
if (gap > 5) assert.equal(casePacket(rec, gap + 1 < rec.n ? gap + 1 : gap, 3).why, 'a candle is missing from the recording');

// ---- a one-bar drawing with several relations held prints a bare conjunction. The vocabulary has no clause for
// its relations. The packet must find its place again, even with another expression beside it
{
  const p = packet([{ v: [15, 50, 85, 90], d: 'u' }], [{ a: { bar: 0, part: 'H' }, b: { bar: 0, part: 'T' } }, { bar: 0, color: true }]);
  const q = question({ g1: drawingG1(p), packet: p, held: true }); const text = toText(q);
  assert.ok(pinnedExpression(p).includes(' and '), 'a bare conjunction');
  const back = fromText(text).model;
  const hasText = Boolean(engine.describeStudy(text).ast.find.items[0].text);
  assert.deepEqual(back.find.items.map(c => c.type), hasText ? ['raw', 'raw'] : ['raw']);
  attach(back, p);
  assert.equal(back.find.items.length, 1); assert.equal(back.find.items[0].type, 'drawing'); assert.equal(drawingHeld(back.find.items[0]), true);
  assert.equal(toText(back), text);
  const edited = text + ' and candle_relation(price(low, bars_ago: 0), is: below, right: price(low, bars_ago: 1))';
  const more = fromText(edited).model; attach(more, p);
  assert.deepEqual(more.find.items.map(c => c.type), hasText ? ['drawing', 'raw'] : ['raw']);
  assert.deepEqual(slotsOf(toText(more)), slotsOf(edited));
}

// ---- dimensions: a drawing with a dimension switched on travels in the later revision of the format, with the
// dimension parts of its g1 code beside the bars. Composer's bench writes exactly this (its bench/model.js).
{
  const DIMENSIONS_REVISION = drawingRevision(['volume']);
  const bars = [{ v: [10, 20, 40, 50], d: 'u' }, { v: [30, 40, 60, 70], d: 'u' }];
  const dimensions = ['volume:0,1', 'delta:0,2/1'];
  const drawn = packet(bars, [], { revision: DIMENSIONS_REVISION, dimensions });
  const code = 'g1:o:0,1,3,4,u;2,3,5,6,u|volume:0,1|delta:0,2/1';
  assert.equal(drawingG1(drawn), code);
  const read = readLink(link(drawn));
  assert.equal(read.error, undefined, read.error); assert.equal(read.g1, code); assert.deepEqual(read.packet.dimensions, dimensions);
  // the question it asks is the code with its parts, and the text gives the same drawing back
  const m = question(read); const text = toText(m);
  assert.ok(text.includes(`chained_g1(${JSON.stringify(code)})`), text);
  const back = fromText(text).model; attach(back, read.packet);
  assert.deepEqual(back.find.items[0].args.packet, read.packet);
  // a g1 that came without a drawing is rebuilt with its parts, and the link to Composer carries them
  const rebuilt = packetFromG1(code);
  assert.equal(rebuilt.revision, DIMENSIONS_REVISION); assert.deepEqual(rebuilt.dimensions, dimensions); assert.equal(drawingG1(rebuilt), code);
  assert.ok(decodeURIComponent(composerLink('http://x/', rebuilt)).includes('"dimensions":["volume:0,1","delta:0,2/1"]'));
  assert.equal(packetFromG1('g1:o:0,1,3,4,u;2,3,5,6,u').revision, COMPOSER_REVISION, 'with every dimension off the packet is the first revision, to the letter');
  // what is refused: dimensions in the first revision, parts that are not a g1's, and a code that disagrees
  for (const bad of [packet(bars, [], { dimensions }), packet(bars, [], { revision: DIMENSIONS_REVISION, dimensions: ['delta:0,2/1', 'volume:0,1'] }),
    packet(bars, [], { revision: DIMENSIONS_REVISION, dimensions: ['volume:0'] }), packet(bars, [], { revision: DIMENSIONS_REVISION, dimensions: 'volume:0,1' }),
    packet(bars, [], { revision: DIMENSIONS_REVISION, dimensions: ['flow:0,1'] })]) {
    assert.ok(readLink(`?drawing=${encodeURIComponent(JSON.stringify(bad))}`).error, JSON.stringify(bad.dimensions));
  }
  assert.ok(readLink(link(drawn).replace(encodeURIComponent('volume:0,1|'), encodeURIComponent('volume:1,0|'))).error, 'the drawing and its g1 must agree on the dimension parts too');
  assert.equal(readLink(`?drawing=${encodeURIComponent(JSON.stringify(packet(bars, [], { revision: DIMENSIONS_REVISION })))}`).error, undefined, 'the later revision with nothing switched on reads as all off');
}

console.log(`Hand-off: 324, 1,463 chained and 772 as recorded, and 4,828 pinned, as the engine's own checks count them; all three forms round-trip; ${sent} recorded windows drawn, each the chained code of its candles and a match of it (${whole} with every open on the close before it, ${moved} without).`);
