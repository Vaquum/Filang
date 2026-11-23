// Compare the shared binding with Composer's pinned matcher on the same real bars.
import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {resolve} from "node:path";
import {pathToFileURL} from "node:url";
import {FilangEngine} from "../../target/engine-dist/browser/index.mjs";

const [oracle, fixture, selected] = process.argv.slice(2);
if (!oracle || !fixture) throw new Error("usage: composer.mjs COMPOSER_CHECKOUT FIXTURES [SCENARIO]");
const matcher = new Function("self", "window", await readFile(resolve(oracle, "matcher.js"), "utf8") +
  ";return {decode, search, setTables: t => { BARS = t; }, setId: id => { latest = id; }};")(undefined, undefined);
const {heldOf} = await import(pathToFileURL(resolve(oracle, "bench/model.js")));
const packed = await readFile(resolve(fixture, "bars"));
const history = matcher.decode(packed.buffer.slice(packed.byteOffset, packed.byteOffset + packed.byteLength));
matcher.setTables(history);
const timeframes = ["15m", "30m", "1h", "2h", "4h"];
const intervals = [900000, 1800000, 3600000, 7200000, 14400000];

const engine = await FilangEngine.create(await readFile(
  new URL("../../target/engine-dist/browser/filang_engine.wasm", import.meta.url)));
const loadStarted = performance.now();
for (const [i, frame] of timeframes.entries()) {
  engine.loadComposerFrame(await readFile(resolve(fixture, "tape-" + frame + ".csv"), "utf8"), intervals[i]);
}
console.log(JSON.stringify({stage: "load", milliseconds: performance.now() - loadStarted,
  bars: history.reduce((n, tape) => n + tape.n, 0)}));

function drawing(width) {
  let c = 42;
  return Array.from({length: width}, (_, i) => {
    const o = c;
    c += i % 3 === 1 ? -18 : 14;
    return [o, Math.max(o, c) + 12, Math.min(o, c) - 12, c];
  });
}
const pin = {bar: 0, color: true};
const double = [[50, 51, 44, 45], [45, 46, 38, 39], [39, 40, 33, 34],
  [34, 35, 28, 31], [31, 38, 30, 37], [37, 42, 36, 41], [41, 41.5, 34, 35],
  [35, 36, 29, 33], [33, 40, 32, 39], [39, 47, 38, 46]];
const point = text => {
  const [kind, ...digits] = text;
  const bar = Number(digits.join("")) - 1;
  const up = double[bar][3] >= double[bar][0];
  return {bar, part: kind === "O" ? (up ? "B" : "T") : kind === "C" ? (up ? "T" : "B") : kind};
};
const doublePins = ["u10", "L4<L1", "L4<L2", "L4<L3", "L4<L5", "L4<L6", "L4<L7",
  "L4<L8", "L4<L9", "L4<L10", "L8<L7", "L8<L9", "H6>H5", "H6>H7", "H6>H8", "H6>H9", "C10>H6"]
  .map(text => {
    if (text === "u10") return {bar: 9, color: true};
    const [a, b] = text.split(/[<>]/);
    return {a: point(a), b: point(b)};
  });

function endMasks(next) {
  return history.map(tape => {
    const slots = (tape.ts.at(-1) - tape.ts[0]) / tape.sec + 1;
    const mask = new Uint8Array(slots).fill(48);
    for (let i = 0; i + 1 < tape.n; i++) {
      if (tape.run[i + 1] < 2) continue;
      const move = tape.C[i + 1] - tape.C[i];
      const value = next.measure === "atr" ? move / tape.atr[i] : move / tape.C[i] * 1e4;
      if (Number.isFinite(value) && next.dir * value >= next.value) {
        mask[(tape.ts[i] - tape.ts[0]) / tape.sec] = 49;
      }
    }
    return new TextDecoder().decode(mask);
  });
}

const cases = [
  ["default", 2, [], 0, 31, true],
  ["default-repeat", 2, [], 0, 31, true],
  ["2-bars-only-4h", 2, [], 0, 16, true],
  ["10-bars", 10, [], 0, 31, true],
  ["20-bars", 20, [], 0, 31, true],
  ["20-bars-shape-only", 20, [], 0, 31, false],
  ["2-bars-pin", 2, [pin], 0, 31, true],
  ["5-bars-pin-stretch-0", 5, [pin], 0, 31, true],
  ["5-bars-pin-stretch-4", 5, [pin], 4, 31, true],
  ["10-bars-pin-stretch-4", 10, [pin], 4, 31, true],
  ["20-bars-pin-stretch-4", 20, [pin], 4, 31, true],
  ["5-bars-skeleton", 5, [], 2, 31, true, 2],
  ["5-bars-cross-pin", 5, [{a: {bar: 0, part: "H"}, b: {bar: 4, part: "H"}}], 2, 31, true],
  ["10-bars-17-pins", 10, doublePins, 2, 31, true, 0, double],
  ["10-bars-17-pins-filter", 10, doublePins, 0, 31, true, 0, double, {dir: 1, measure: "atr", value: 8}],
  ["2-bars-pin-filter", 2, [pin], 4, 13, true, 0, drawing(2), {dir: 1, measure: "atr", value: 1}],
];

let id = 0;
try {
  for (const [name, width, pins, stretch, tf, oriented, skeleton = 0, bars = drawing(width), next = null] of cases) {
    if (selected && name !== selected) continue;
    const packet = {
      version: 1, revision: "133e3017ba9143f7dc255df7218ff7bfe46d9d06", oriented,
      bars: bars.map(([o, h, l, c]) => ({v: [l, Math.min(o, c), Math.max(o, c), h], d: c >= o ? "u" : "d"})),
      pins, skeleton, stretch, limit: 12, next: {dir: 0, measure: "any", bps: 10, atr: 1},
    };
    const holds = heldOf(bars, {pins, skel: skeleton, oriented}).map(({h}) => h);
    const query = {bars, holds, stretch, x: 12, tfs: timeframes.map((_, i) => Boolean(tf & (1 << i))), oriented, next};
    const start = performance.now();
    engine.composerStart(packet, {timeframes: tf, endMasks: next ? endMasks(next) : undefined});
    let actual, maxStep = 0;
    do {
      const before = performance.now();
      actual = engine.composerStep(1024);
      maxStep = Math.max(performance.now() - before, maxStep);
      if (performance.now() - start > 30_000) throw new Error(name + ": search exceeded 30 seconds");
    } while (!actual.done);
    const elapsed = performance.now() - start;

    matcher.setId(++id);
    const expected = await matcher.search(query, id, () => {});
    console.log(JSON.stringify({scenario: name, elapsed, maxStep, oracle: expected.ms,
      mode: actual.mode, exact: actual.exact, held: actual.held, nearest: actual.results.length}));
    assert.equal(actual.mode, expected.mode, name);
    assert.deepEqual(actual.exact, expected.exact, name);
    assert.deepEqual(actual.held, expected.counts, name);
    assert.deepEqual(actual.qualified_exact, expected.exactF, name + " qualified exact");
    assert.deepEqual(actual.qualified_held, expected.countsF, name + " qualified held");
    assert.deepEqual(actual.near.map(v => [v.a, v.b, v.was, v.relation, v.count]),
      expected.panes.near.map(v => [v.a, v.b, v.was, v.rel, v.n]), name + " near");
    assert.deepEqual(actual.results.map(r => [r.timeframe, r.window.start_ms, r.window.end_ms,
      r.window.picks, r.half_flips, r.broken]), expected.results.map(r => [
      intervals[timeframes.indexOf(r.tf)], r.start * 1000, r.end * 1000, r.picks, r.flips * 2, r.broken,
    ]), name + " results");
    for (let i = 0; i < actual.results.length; i++) {
      assert.ok(Math.abs(actual.results[i].score - expected.results[i].score) < 1e-12, name + " score");
      assert.ok(Math.abs(actual.results[i].off - expected.results[i].off) < 1e-12, name + " off");
    }
    const kind = holds.length ? "held" : "exact";
    const counts = holds.length ? actual.held : actual.exact;
    for (const [i, interval] of intervals.entries()) {
      const page = engine.composerPositions(interval, {kind, limit: 7});
      assert.equal(page.total, counts[i], name);
      assert.equal(page.next, counts[i] > 7 ? 7 : null);
      assert.equal(page.positions.length, Math.min(7, counts[i]));
    }
    for (const [i, near] of actual.near.entries()) {
      const total = intervals.reduce((n, interval) => n + engine.composerPositions(interval, {
        kind: "near:" + i, limit: 0,
      }).total, 0);
      assert.equal(total, near.count);
    }
  }
} finally {
  engine.close();
}
