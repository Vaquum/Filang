// Verify the engine responses needed by the Query bench using its actual vocabulary.
import assert from "node:assert/strict";
import {createHash} from "node:crypto";
import {readFile} from "node:fs/promises";
import {loadInputs} from "../../study/native/inputs.mjs";
import {analyze} from "../../study/src/check.js";
import {manifestFor, runCandidate} from "../../study/src/engine.js";
import {parseG1} from "../../study/src/g1.js";
import {stripSpans} from "../../study/src/lang.js";
import {FUNCTIONS} from "../../study/src/registry.js";
import {FilangEngine} from "../../target/engine-dist/browser/index.mjs";
import {install} from "../../query/verify/site.mjs";

// The bench's vocabulary imports by site path and asks the shared engine, as it does in the page.
await install();
await (await import("/shared/filang.js")).load();
const {PRESETS, OFFERS, clone, fromText, toText} = await import("/shared/vocab.js");

const atomText = new Set(["num", "pct", "dur"]);
function olderAst(node) {
  if (Array.isArray(node)) return node.map(olderAst);
  if (!node || typeof node !== "object") return node;
  return Object.fromEntries(Object.entries(node).filter(([key]) =>
    key !== "canonical_text" && (key !== "text" || atomText.has(node.k)))
    .map(([key, value]) => [key, olderAst(value)]));
}

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
  "on BTCUSDT 15m\nlet window = {60m | 240m}\nfind channel_breakout(over: window)\nwhere session_tail(nyse_regular, last: {30m | 1h})",
];
const reclaim = head + "breach_reclaim(prior_high(over: 4h), within_min: 1, within_max: 4)" +
  "\nwhere candle_relation(price(high), is: below, right: price(low))" +
  "\nmeasure close_return(after: [1h, 4h])";
const receipts = [...presets, ...suggestions, ...extra];
const definition = bundle.extensions.find(entry => entry.version === 2);
if (!process.argv[2]) {
  engine.installDefinition(definition.text, definition.sha256);
  receipts.push(reclaim,
    head + '"Wick rejection" where quiet_friday_close_v2(last: 1h)',
    head + 'カラカサ or engulfing measure close_return(after: [1h, 4h])');
}
for (const question of receipts) {
  const oracle = analyze(question, bundle.env);
  assert.equal(oracle.ok, true, JSON.stringify(oracle.errors));
  if (!process.argv[2]) {
    const description = engine.describeStudy(question);
    assert.equal(description.canonical, oracle.canonical, question);
    assert.deepEqual(olderAst(description.ast), stripSpans(oracle.ast), question);
    assert.equal(description.ast.find.text, description.canonical.split("\n")
      .find(line => line.startsWith("find ")).slice(5), question);
    assert.deepEqual(description.axes.map(a => [a.label, olderAst(a.values)]),
      oracle.axes.map(a => [a.label, stripSpans(a.values)]), question);
    assert.deepEqual(description.candidates, oracle.candidates.map(({index, label, assignment, resolvedText}) =>
      ({index, label, assignment, resolvedText})), question);
    assert.equal(description.manifest.pins.source.csv_sha256, bundle.rec.digest);
    assert.equal(description.manifest.pins.source.rows, bundle.rec.presentCount);
    assert.deepEqual(description.manifest.pins.calendars, [{id: bundle.cal.id, sha256: bundle.cal.digest}]);
    assert.equal(description.manifest.engine.version, engine.version().version);
    const pins = manifestFor(bundle.ctx, oracle, {extensions: bundle.extensions}).pins;
    assert.deepEqual(description.manifest.pins.definitions, pins.definitions, question);
    assert.deepEqual(description.manifest.pins.candlePatterns, pins.candlePatterns ?? [], question);
    assert.deepEqual(description.manifest.pins.extensions,
      pins.extensions, question);
  }
  const answers = engine.study(question).results;
  assert.equal(answers.length, oracle.candidates.length);
  for (const [i, candidate] of oracle.candidates.entries()) {
    const expected = runCandidate(bundle.ctx, candidate);
    assert.deepEqual(answers[i].anchors, expected.matches.map(row => row.t), question);
    const page = engine.studyRows(question, {candidate: i, limit: 8});
    assert.equal(page.event_count, expected.rows.length, question);
    assert.equal(page.event_unknown, answers[i].unknown.event.length, question);
    assert.deepEqual(page.columns, expected.columns.map(column => column.text), question);
    const lines = (keyword) => candidate.resolvedText.split("\n")
      .filter(line => line.startsWith(keyword + " ")).map(line => line.slice(keyword.length + 1));
    assert.deepEqual(page.lines, {on: lines("on")[0], find: lines("find")[0],
      wheres: lines("where"), group: lines("group by")[0] ?? null, measures: lines("measure")}, question);
    assert.deepEqual(page.survivors, expected.survivors, question);
    assert.deepEqual(page.clause_stats, expected.clauseStats.map(s => [s.T, s.F, s.U]), question);
    assert.deepEqual(page.group_labels, expected.group?.keys.map(key => ({
      key, label: expected.group.labels[key],
    })) ?? [], question);
    const receipt = row => ({
      slot: row.i, t: row.t, group: row.group?.key ?? null,
      where: row.results.map(r => r.v < 0 ? null : r.v === 1),
      fail_at: row.failAt, out: row.out.map(({status, value}) => ({status, value})),
      ...(expected.event.series.evidence?.(row.i) ? {reclaim: expected.event.series.evidence(row.i)} : {}),
    });
    assert.deepEqual(page.rows, expected.rows.slice(0, 8).map(receipt), question);
    assert.equal(page.next, expected.rows[8]?.i ?? null, question);
    if (page.next !== null) {
      const next = engine.studyRows(question, {candidate: i, start: page.next, limit: 2});
      assert.deepEqual(next.rows, expected.rows.slice(8, 10).map(receipt), question);
    }
    const slot = Math.min(123, bundle.rec.n - 1);
    const facts = engine.studyClose(question, bundle.rec.closeTime(slot), {candidate: i});
    assert.equal(facts.slot, slot);
    assert.ok(facts.event_why.length > 0);
    assert.equal(facts.where_why.length, expected.clauses.length);
    assert.ok(facts.where_why.every(Boolean));
    assert.equal(Boolean(facts.group_why), Boolean(expected.group));
    if (facts.present) {
      assert.deepEqual(facts.outcome_why, expected.columns.map(col => col.at(slot).why), question);
    }
    if (question === reclaim) {
      assert.ok(expected.rows.length > 0);
      const witness = expected.rows[0];
      const occurrence = engine.studyClose(question, witness.t);
      assert.equal(occurrence.event_why, expected.event.series.why(witness.i));
      assert.deepEqual(occurrence.reclaim, expected.event.series.evidence(witness.i));
      assert.deepEqual(occurrence.where, [false]);
      const last = bundle.rec.n - 1;
      assert.deepEqual(engine.studyClose(question, bundle.rec.closeTime(last)).outcome_why,
        expected.columns.map(col => col.at(last).why));
    }
    assert.equal(facts.group, expected.group?.at(slot).key ?? null, question);
    assert.deepEqual(facts.where, expected.clauses.map(c => {
      const {v} = c.at(slot);
      return v < 0 ? null : v === 1;
    }), question);
  }
}
const t = Date.parse("2025-03-25T03:00:00Z");
const explain = head + "wick_rejection(body_max: 35%, wick_min: 45%)" +
  "\nwhere near_level(prior_high(over: 4h), point: price(close), within: 0.25%)" +
  "\nwhere candle_share(lower_wick, min: 50%)" +
  "\nwhere range_multiple(over: 24h, min: 1.5)" +
  "\nwhere weekday(nyse_regular) = mon";
const facts = engine.studyClose(explain, t);
assert.match(facts.event_why, /35%/);
assert.match(facts.event_why, /45%/);
assert.match(facts.where_why[0], /0\.25%/);
assert.match(facts.where_why[1], /50%/);
assert.match(facts.where_why[2], /preceding 24h median/);
assert.match(facts.where_why[3], /New York date 2025-03-24/);
const unknownDay = engine.studyClose(explain, bundle.rec.closeTime(0));
assert.match(unknownDay.where_why[3], /New York dates 2025-01-01 … 2025-06-01/);
assert.ok(engine.studyClose(head + "hammer", t).event_why.includes(engine.catalogue().patterns
  .find(pattern => pattern.id === "hammer").rule));
const heldQuestion = head + relation + "\nwhere held(quiet_range(width_max: 2.5%), for: 48h)";
assert.match(engine.studyClose(heldQuestion, t).where_why[0], /true since .*48h/);

const unavailable = head + "candle_relation(delta(), is: above, right: 0)";
const refused = engine.studyDiagnostics(unavailable);
assert.equal(refused.errors[0].kind, "capability");
assert.equal(refused.canonical, unavailable);
assert.equal(refused.ast.find.text, unavailable.slice(head.length));

const mixed = head + "hammer or candle_relation(price(high, bars_ago: 1), is: above, right: price(close))" +
  "\nwhere candle_share(lower_wick, min: 50%) and range_multiple(over: 4h, min: 1, max: 2)";
const model = fromText(mixed).model;
assert.deepEqual(model.find.items.map(item => item.type), ["pattern", "raw"]);
assert.deepEqual(model.wheres.map(item => item.type), ["share", "raw"]);
assert.deepEqual(engine.study(toText(model)).results[0].anchors, engine.study(mixed).results[0].anchors);

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
const glossary = new Map(engine.studyTerms().terms.map(entry => [entry.name, entry]));
for (const name of ["wick_rejection", "hammer", "quiet_range", "close_return", "session_tail"]) {
  const expected = FUNCTIONS.find(entry => entry.name === name);
  const {title, summary, formula} = glossary.get(name);
  assert.deepEqual({title, summary, formula},
    {title: expected.title, summary: expected.summary, formula: expected.formula});
}
assert.equal(engine.resolveCandle("Hammer").id, "hammer");
assert.equal(engine.resolveCandle("ハンマー").id, "hammer");
assert.equal(engine.resolveCandle("カラカサ").id, "hammer");
assert.equal(engine.resolveCandle("not a candle").id, null);
assert.deepEqual(engine.studyDiagnostics(presets[0]), {ok: true, errors: []});
const invalidClauses = head + 'missing_event()\nwhere still_missing()\nwhere カラカサ and also_missing()';
const diagnostics = engine.studyDiagnostics(invalidClauses);
assert.equal(diagnostics.ok, false);
assert.deepEqual(diagnostics.errors.map(({kind, start, end}) => [kind, invalidClauses.slice(start, end)]),
  [["name", "missing_event()"], ["name", "still_missing()"], ["name", "カラカサ and also_missing()"]]);
assert.ok(diagnostics.errors.every(({message, hint}) => message && hint));
assert.equal(engine.studyDiagnostics(head + "wick_rejection(").errors[0].kind, "parse");

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
