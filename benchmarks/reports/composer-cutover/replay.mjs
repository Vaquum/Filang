// Drive the pinned Composer worker and its predecessor over the issue #94 fixtures.
// The adapter substitutions apply in memory to the pinned checkout.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
const [filang, composer, fix, oldMatcher, transfer = 'packed', only] = process.argv.slice(2);
if (!oldMatcher || !['baseline', 'paged', 'packed'].includes(transfer)) {
  throw new Error('usage: replay.mjs FILANG COMPOSER FIXTURES OLD_MATCHER [baseline|paged|packed] [CASE]');
}
const { FilangEngine } = await import(pathToFileURL(filang + '/target/engine-dist/browser/index.mjs'));
const engine = await FilangEngine.create(await readFile(filang + '/target/engine-dist/browser/filang_engine.wasm'));
let matcher = await readFile(composer + '/matcher.js', 'utf8');
function replaceMatcher(before, after) {
  assert.ok(matcher.includes(before), 'unexpected Composer matcher source');
  matcher = matcher.replace(before, after);
}
if (transfer === 'packed') {
  replaceMatcher(`  for (let from = 0; from !== null;) {
    const page = filang.composerPositions(T.sec * 1000, { kind, start: from, limit: 4096 });
    for (const w of page.positions) fn(T.at[w.start], w.span, w.picks);
    from = page.next;
  }`, `  const {starts, spans, picks} = filang.composerPositionsPacked(T.sec * 1000, {kind});
  const offsets = [];
  for (let i = 0; i < starts.length; i++) {
    if (kind === 'held') {
      offsets.length = 0;
      for (let mask = picks[i]; mask; mask &= mask - 1) offsets.push(31 - Math.clz32(mask & -mask));
    }
    fn(T.at[starts[i]], spans[i], offsets);
  }`);
}
if (transfer !== 'baseline') {
  replaceMatcher(`    // the engine's whole ranking, closest first: Vaquum/Filang#94 item 1
    for (let k = 0; k < tables.length; k++) {
      const T = tables[k];
      eachWindow(filang, T, 'ranked', (s, span, picks) => { const e = s + span - 1; addSet(k, T, s, picks, e, outcomeInto(T, e, oo)); });
    }`, transfer === 'packed' ? `    const {starts, spans, picks, frames} = filang.composerPositionsPacked(null, {kind: 'ranked'});
    const offsets = [];
    for (let i = 0; i < starts.length; i++) {
      const k = frames[i], T = tables[k], s = T.at[starts[i]], e = s + spans[i] - 1;
      offsets.length = 0;
      for (let mask = picks[i]; mask; mask &= mask - 1) offsets.push(31 - Math.clz32(mask & -mask));
      addSet(k, T, s, offsets, e, outcomeInto(T, e, oo));
    }` : `    const intervals = tables.map(T => T.sec * 1000);
    for (const {start, timeframe, span, picks} of filang.composerPositions(null, {kind: 'ranked'}).positions) {
      const k = intervals.indexOf(timeframe), T = tables[k], s = T.at[start], e = s + span - 1;
      addSet(k, T, s, picks, e, outcomeInto(T, e, oo));
    }`);
}
const now = await import('data:text/javascript;base64,' + Buffer.from(matcher).toString('base64'));
const old = new Function('self', 'window', await readFile(oldMatcher, 'utf8') + ';return {decode, decodeActivity, readings, search, set: (t, r) => { BARS = t; READ = r; }, setId: id => { latest = id; }};')(undefined, undefined);
const { heldOf } = await import(pathToFileURL(composer + '/bench/model.js'));
const slice = (b) => b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength);
const packed = await readFile(fix + '/bars'), act = await readFile(fix + '/activity');
const oldTables = old.decode(slice(packed)); const oldRead = old.decodeActivity(slice(act)).map((A, k) => old.readings(oldTables[k], A)); old.set(oldTables, oldRead);
let t0 = performance.now();
const tables = now.decode(slice(packed)); now.give(engine, tables); const giveMs = performance.now() - t0;
now.state.engine = engine; now.state.bars = tables; now.state.readings = now.decodeActivity(slice(act)).map((A, k) => now.readings(tables[k], A));
const timeframes = ['15m', '30m', '1h', '2h', '4h'];
function drawing(width) { let c = 42; return Array.from({ length: width }, (_, i) => { const o = c; c += i % 3 === 1 ? -18 : 14; return [o, Math.max(o, c) + 12, Math.min(o, c) - 12, c]; }); }
const pin = { bar: 0, color: true };
const double = [[50, 51, 44, 45], [45, 46, 38, 39], [39, 40, 33, 34], [34, 35, 28, 31], [31, 38, 30, 37], [37, 42, 36, 41], [41, 41.5, 34, 35], [35, 36, 29, 33], [33, 40, 32, 39], [39, 47, 38, 46]];
const point = (text) => { const [kind, ...digits] = text; const bar = Number(digits.join('')) - 1; const up = double[bar][3] >= double[bar][0]; return { bar, part: kind === 'O' ? (up ? 'B' : 'T') : kind === 'C' ? (up ? 'T' : 'B') : kind }; };
const doublePins = ['u10', 'L4<L1', 'L4<L2', 'L4<L3', 'L4<L5', 'L4<L6', 'L4<L7', 'L4<L8', 'L4<L9', 'L4<L10', 'L8<L7', 'L8<L9', 'H6>H5', 'H6>H7', 'H6>H8', 'H6>H9', 'C10>H6'].map((text) => { if (text === 'u10') return { bar: 9, color: true }; const [a, b] = text.split(/[<>]/); return { a: point(a), b: point(b) }; });
const cases = [
  ['default', 2, [], 0, 31, true], ['2-bars-only-4h', 2, [], 0, 16, true], ['3-bars', 3, [], 0, 31, true], ['10-bars', 10, [], 0, 31, true], ['20-bars', 20, [], 0, 31, true], ['20-bars-shape-only', 20, [], 0, 31, false],
  ['2-bars-pin', 2, [pin], 0, 31, true], ['2-bars-pin-stretch-4', 2, [pin], 4, 31, true], ['5-bars-pin-stretch-0', 5, [pin], 0, 31, true], ['5-bars-pin-stretch-4', 5, [pin], 4, 31, true], ['10-bars-pin-stretch-4', 10, [pin], 4, 31, true],
  ['5-bars-skeleton', 5, [], 2, 31, true, 2], ['5-bars-cross-pin', 5, [{ a: { bar: 0, part: 'H' }, b: { bar: 4, part: 'H' } }], 2, 31, true],
  ['10-bars-17-pins', 10, doublePins, 2, 31, true, 0, double], ['10-bars-17-pins-filter', 10, doublePins, 0, 31, true, 0, double, { dir: 1, measure: 'atr', value: 8 }],
  ['2-bars-pin-filter', 2, [pin], 4, 13, true, 0, drawing(2), { dir: 1, measure: 'atr', value: 1 }], ['2-bars-filter-up', 2, [], 0, 31, true, 0, drawing(2), { dir: 1, measure: 'any', value: 0 }], ['3-bars-skeleton-bps', 3, [], 0, 21, true, 1, drawing(3), { dir: -1, measure: 'bps', value: 10 }],
];
const close = (a, b, at) => { if (a === b || (a !== a && b !== b)) return; if (typeof a === 'number' && typeof b === 'number') { assert.ok(Math.abs(a - b) <= 1e-9 * Math.max(1, Math.abs(a), Math.abs(b)), `${at}: ${a} against ${b}`); return; } if (a === null || b === null || typeof a !== 'object') { assert.deepEqual(a, b, at); return; } if (ArrayBuffer.isView(a)) { a = Array.from(a); b = Array.from(b); } assert.deepEqual(Object.keys(a).sort(), Object.keys(b).sort(), at + ' keys'); for (const k of Object.keys(a)) close(a[k], b[k], at + '.' + k); };
let id = 0; const blocked = []; const rows = [];
const real = engine.composerPositions.bind(engine);
const packedRead = engine.composerPositionsPacked?.bind(engine);
const realStep = engine.composerStep.bind(engine);
let pageMs = 0, stepMs = 0, lacking = false;
engine.composerPositions = (iv, options) => {
  if (transfer === 'baseline' && options.kind === 'ranked') {
    lacking = true;
    return {positions: [], next: null, total: 0};
  }
  const t = performance.now();
  const response = real(iv, options);
  pageMs += performance.now() - t;
  return response;
};
engine.composerPositionsPacked = (iv, options) => {
  const t = performance.now();
  const response = packedRead(iv, options);
  pageMs += performance.now() - t;
  return response;
};
engine.composerStep = units => {
  const t = performance.now();
  const response = realStep(units);
  stepMs += performance.now() - t;
  return response;
};
for (const [name, width, pins, stretch, tf, oriented, skeleton = 0, bars = drawing(width), next = null] of cases) {
  if (only && name !== only) continue;
  const packet = { version: 1, revision: engine.drawingProtocol().plain, oriented, bars: bars.map(([o, h, l, c]) => ({ v: [l, Math.min(o, c), Math.max(o, c), h], d: c >= o ? 'u' : 'd' })), pins, skeleton, stretch, limit: 12, next: { dir: 0, measure: 'any', bps: 10, atr: 1 } };
  const holds = heldOf(bars, { pins, skel: skeleton, oriented }).map(({ h }) => h);
  const tfs = timeframes.map((_, i) => Boolean(tf & (1 << i)));
  old.setId(++id); let a = performance.now(); const was = await old.search({ bars, holds, stretch, x: 12, tfs, oriented, next }, id, () => {}); const oldMs = performance.now() - a;
  lacking = false; pageMs = 0; stepMs = 0;
  now.state.latest = id; a = performance.now(); const is = await now.search({ packet, tfs, next }, id, () => {}); const newMs = performance.now() - a;
  const at = name;
  for (const k of ['mode', 'exact', 'exactF', 'counts', 'countsF', 'split', 'base', 'filter', 'stretch']) close(is[k], was[k], `${at}.${k}`);
  close(is.results, was.results, at + '.results');
  close(is.panes.near, was.panes.near, at + '.near');
  if (lacking) { assert.equal(was.panes.kind, 'closest', at); blocked.push(name); }
  else { const { near: _n, ...p } = is.panes; const { near: _o, ...w } = was.panes; close(p, w, at + '.panes'); }
  const row = { name, mode: is.mode, set: was.panes.kind, n: was.panes.n, oldMs, newMs, engineSearch: stepMs,
    reading: pageMs, describing: newMs - stepMs - pageMs, panes: lacking ? 'missing ranking' : 'equal' };
  rows.push(row);
  console.log(JSON.stringify(row));
}
engine.close();
console.log(JSON.stringify({transfer, giveMs, bars: tables.reduce((sum, tape) => sum + tape.n, 0),
  cases: rows.length, missingPanes: blocked}));
