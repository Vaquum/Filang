// Verify the engine responses needed by the Query bench using its actual vocabulary.
import assert from "node:assert/strict";
import {createHash} from "node:crypto";
import {readFile} from "node:fs/promises";
import {register} from "node:module";
import {loadInputs} from "../../study/native/inputs.mjs";
import {analyze} from "../../study/src/check.js";
import {runCandidate} from "../../study/src/engine.js";
import {parseG1} from "../../study/src/g1.js";
import {FilangEngine} from "../../target/engine-dist/browser/index.mjs";

const root = new URL("../../", import.meta.url).href;
register("data:text/javascript," + encodeURIComponent(`
  const root = ${JSON.stringify(root)};
  export function resolve(spec, context, next) {
    if (spec.startsWith("/study/")) return {url: new URL(spec.slice(1), root).href, shortCircuit: true};
    if (spec.startsWith("/shared/")) return {url: new URL("query" + spec, root).href, shortCircuit: true};
    return next(spec, context);
  }
`), import.meta.url);
const {PRESETS, OFFERS, clone, fromText, toText} = await import("/shared/vocab.js");

const {bundle, assets} = loadInputs();
const engine = await FilangEngine.create(await readFile(
  new URL("../../target/engine-dist/browser/filang_engine.wasm", import.meta.url),
));
const csv = assets.get("recorded-bars.csv");
engine.loadCsv(csv.toString("utf8"), bundle.rec.barMs);
engine.setCalendar();

const presets = PRESETS.map(preset => preset.text);
const starting = fromText(presets[3]).model;
const suggestions = OFFERS.map(offer => {
  const model = clone(starting);
  model.wheres.push(clone(offer));
  return toText(model);
});
assert.equal(suggestions.length, 16);

const head = "on BTCUSDT 15m\nfind ";
const relation = "candle_relation(price(high), is: at_or_above, right: price(low))";
const extra = [
  head + "candle_relation(price(close), is: above, right: price(high, bars_ago: 2))",
  head + relation + "\nwhere candle_share(body, min: 0%, max: 20%)",
  head + relation + "\nwhere held(quiet_range(width_max: 2.5%), for: 48h)",
  head + "channel_breakout(over: {1h | 4h | 12h})\nwhere weekday(nyse_regular) = fri",
];
const receipts = [...presets, ...suggestions, ...extra];
for (const question of receipts) {
  const oracle = analyze(question, bundle.env);
  assert.equal(oracle.ok, true, JSON.stringify(oracle.errors));
  const answers = engine.study(question).results;
  assert.equal(answers.length, oracle.candidates.length);
  for (const [i, candidate] of oracle.candidates.entries()) {
    const expected = runCandidate(bundle.ctx, candidate);
    assert.deepEqual(answers[i].anchors, expected.matches.map(row => row.t), question);
    const page = engine.studyRows(question, {candidate: i, limit: 8});
    assert.equal(page.event_count, expected.rows.length, question);
    assert.deepEqual(page.survivors, expected.survivors, question);
    assert.deepEqual(page.clause_stats, expected.clauseStats.map(s => [s.T, s.F, s.U]), question);
    assert.deepEqual(page.group_labels, expected.group?.keys.map(key => ({
      key, label: expected.group.labels[key],
    })) ?? [], question);
    const receipt = row => ({
      slot: row.i, t: row.t, group: row.group?.key ?? null,
      where: row.results.map(r => r.v < 0 ? null : r.v === 1),
      fail_at: row.failAt, out: row.out.map(({status, value}) => ({status, value})),
    });
    assert.deepEqual(page.rows.map(({reclaim, ...row}) => row), expected.rows.slice(0, 8).map(receipt), question);
    assert.equal(page.next, expected.rows[8]?.i ?? null, question);
    if (page.next !== null) {
      const next = engine.studyRows(question, {candidate: i, start: page.next, limit: 2});
      assert.deepEqual(next.rows.map(({reclaim, ...row}) => row), expected.rows.slice(8, 10).map(receipt), question);
    }
    const slot = Math.min(123, bundle.rec.n - 1);
    const facts = engine.studyClose(question, bundle.rec.closeTime(slot), {candidate: i});
    assert.equal(facts.slot, slot);
    assert.equal(facts.group, expected.group?.at(slot).key ?? null, question);
    assert.deepEqual(facts.where, expected.clauses.map(c => {
      const {v} = c.at(slot);
      return v < 0 ? null : v === 1;
    }), question);
  }
}
const expected = receipts.map(query => ({count: engine.study(query, {candidate: 0}).results[0].counts.matches, error: null}));
assert.deepEqual(engine.studyCounts(receipts), expected);
const broken = head + "missing_term_here";
assert.deepEqual(engine.studyCounts([presets[0], broken, presets[1]]).map(x => x.count),
  [expected[0].count, null, expected[1].count]);
assert.equal(typeof engine.studyCounts([broken])[0].error, "string");
assert.deepEqual(engine.studyCounts([]), []);
assert.throws(() => engine.studyCounts(Array(65).fill(broken)), /exceeds 64 questions/);

const shapes = [
  "g1:o:0,1,3,4,u;2,3,5,6,u",
  "g1:o:0,1,2,3,d;0,1,1,2,z",
  "g1:o:0,1,2,3,u;4,5,6,7,u",
  "g1:u:0,1,2,3",
];
for (const code of shapes) {
  const shape = engine.geometryShape(code);
  const oracle = parseG1(code);
  assert.deepEqual(shape.ranks, oracle.rows.map(row => row.ranks));
  assert.equal(shape.rank_count, oracle.rankCount);
  assert.deepEqual(shape.directions, oracle.oriented ? oracle.rows.map(row => row.direction) : null);
  const rows = oracle.oriented ? oracle.rows.map(({ranks: [l, b, t, h], direction}) =>
    direction === "d" ? [t, h, l, b] : [b, h, l, t]) : null;
  assert.deepEqual(shape.rows, rows);
  assert.equal(shape.chained, rows?.slice(1).every((row, i) => row[0] === rows[i][3]) ?? null);
}
assert.throws(() => engine.geometryShape("g2:unknown"));

for (const t of [0, ...Array.from({length: 24}, (_, i) => bundle.rec.closeTime(i * 121))]) {
  const day = bundle.cal.dayAt(t);
  const expected = day.kind === "session"
    ? `${day.s.weekday.toUpperCase()} ${bundle.cal.localHM(t, day.s)}`
    : day.kind === "closed" ? "no session" : "outside calendar";
  assert.equal(engine.sessionClock(t).text, expected);
}

const order = process.argv[2];
if (order) {
  assert.ok(order === "base-first" || order === "candidate-first");
  const legacy = () => suggestions.map(query => engine.study(query, {candidate: 0}).results[0].counts.matches);
  const batch = () => engine.studyCounts(suggestions).map(x => x.count);
  const timed = (run, want) => {
    const start = performance.now();
    const answer = run();
    const ms = performance.now() - start;
    assert.deepEqual(answer, want);
    return ms;
  };
  const want = expected.slice(presets.length, presets.length + suggestions.length).map(x => x.count);
  const warm = {legacy: [], batch: [], presets: []};
  for (let trial = 0; trial < 5; trial++) {
    if ((trial % 2 === 0) === (order === "base-first")) {
      warm.legacy.push(timed(legacy, want));
      warm.batch.push(timed(batch, want));
    } else {
      warm.batch.push(timed(batch, want));
      warm.legacy.push(timed(legacy, want));
    }
    warm.presets.push(timed(() => presets.map(query => engine.study(query).results[0].counts.matches),
      expected.slice(0, presets.length).map(x => x.count)));
  }
  console.log(JSON.stringify({order, node: process.version,
    csv_sha256: createHash("sha256").update(csv).digest("hex"), questions: suggestions.length, warm}));
} else {
  console.log(`Query contract: ${receipts.length} questions and ${shapes.length} rank descriptions agree`);
}
engine.close();
