// Query's pinned recording and JS behavior are the compatibility oracle.
import assert from "node:assert/strict";
import {createHash} from "node:crypto";
import {readFile} from "node:fs/promises";
import {loadInputs} from "../../study/native/inputs.mjs";
import {analyze} from "../../study/src/check.js";
import {runCandidate, U} from "../../study/src/engine.js";
import {chainedG1FromRecording, g1FromRecording} from "../../study/src/g1.js";
import {EXAMPLES} from "../../study/src/examples.js";
import {CANDLE_PATTERNS} from "../../study/src/registry.js";
import {FilangEngine} from "../../target/engine-dist/browser/index.mjs";

const {bundle, assets} = loadInputs();
const engine = await FilangEngine.create(await readFile(
  new URL("../../target/engine-dist/browser/filang_engine.wasm", import.meta.url),
));
const csv = assets.get("recorded-bars.csv").toString("utf8");
const {rec} = bundle;
engine.loadCsv(csv, rec.barMs);
engine.setCalendar();

const find = "on BTCUSDT 15m\nfind ";
const slot = rec.slotClosingAt(Date.parse("2025-03-28T19:30:00Z"));
const queries = [
  ...["starter", "transfer", "transfer-filter"].map(id => EXAMPLES.find(x => x.id === id).text),
  find + 'exact_g1({"g1:o:0,1,2,2,u" | "g1:o:0,1,2,2,d"}) where quiet_friday_close(last: {30m | 1h})',
  find + 'exact_g1("g1:u:0,1,2,2") measure close_return(after: 4h)',
  find + 'exact_g1(' + JSON.stringify(g1FromRecording(rec, slot, 2)) + ')',
  find + '"Wick rejection" where quiet_friday_close_v2(last: 1h) measure close_return(after: [1h,4h])',
  find + '"Wick rejection" where not held("Quiet range", for: 48h)',
  find + '"Wick rejection" group by weekday(nyse_regular) = fri measure close_return(after: 7d)',
  find + 'wick_rejection(body_max: 0.' + "3".repeat(4310) + ', wick_min: 45%) where weekday(nyse_regular) = closed',
  find + 'exact_g1("g1:o:0,0,0,0,z") group by weekday(nyse_regular)',
  find + 'chained_g1("g1:o:0,1,3,4,u;2,3,5,6,u") measure close_return(after: [1h,4h])',
  find + 'chained_g1(' + JSON.stringify(chainedG1FromRecording(rec, slot, 2, false)) + ')',
  find + 'chained_g1(' + JSON.stringify(chainedG1FromRecording(rec, slot, 3)) + ') group by weekday(nyse_regular)',
  find + 'chained_g1(' + JSON.stringify(chainedG1FromRecording(rec, slot, 12)) + ')',
  find + 'chained_g1("g1:o:0,1,3,4,u;2,3,5,6,u") and exact_g1("g1:o:0,1,3,4,u;2,3,5,6,u")',
  find + '"Wick rejection" where weekday(nyse_regular) = closed and not session_tail(nyse_regular,last:390m)',
  find + '"Wick rejection" where completed_trend(frame:15m) = flat or not (weekday(nyse_regular) != fri)',
  find + '包み線 where ハンマー or weekday(nyse_regular) = fri group by completed_trend(frame:4h) measure close_return(after:[1h,4h])',
  find + 'hammer or engulfing',
  find + 'hammer and engulfing',
  find + '(カラカサ or 陽の包み線) and inside_bar where weekday(nyse_regular) = fri measure close_return(after:1h)',
  find + 'candle_relation(price(close), is: above, right: prior_low(over: 4h)) where candle_share(lower_wick, min: 1%) and range_multiple(over: 4h, min: 0.5)',
  find + 'breach_reclaim(prior_high(over: 4h), within_min: 1, within_max: 4) where near_level(prior_low(over: 4h), point: price(close), within: 2%)',
  ...CANDLE_PATTERNS.patterns.map(entry => find + JSON.stringify(entry.ja)),
];

let count = 0;
for (const query of queries) {
  const checked = analyze(query, bundle.env);
  assert.equal(checked.ok, true, JSON.stringify(checked.errors));
  assert.equal(engine.check(query).candidates, checked.candidates.length);
  const actual = engine.study(query);
  for (const [i, candidate] of checked.candidates.entries()) {
    const expected = runCandidate(bundle.ctx, candidate);
    const result = actual.results[i];
    const unknown = [];
    for (let j = 0; j < rec.n; j++) {
      if (rec.present[j] && expected.event.series.vals[j] === U) unknown.push(rec.closeTime(j));
    }
    const label = query.slice(0, 250);
    assert.deepEqual(result.unknown.event, unknown, label);
    assert.equal(result.counts.nonmatching, expected.populations.nonmatching.count, label);
    assert.deepEqual(result.eligible, expected.populations.eligible.rows.map(r => r.t), label);
    assert.deepEqual(result.unknown.detectorWithinContext, expected.populations.unknownDetector.rows.map(r => r.t), label);
    assert.deepEqual(result.anchors, expected.matches.map(r => r.t), label);
    assert.deepEqual(result.rows.map(({t, group, out}) => ({t, group, out})),
      expected.matches.map(r => ({
        t: r.t, group: r.group?.key ?? null, out: r.out.map(o => ({status: o.status, value: o.value})),
      })), label);
    count++;
  }
}

const artifact = bundle.extensions.find(entry => entry.version === 2).artifact;
const text = JSON.stringify({...artifact, version: 3});
const sha = createHash("sha256").update(text).digest("hex");
assert.throws(() => engine.installDefinition(text, "changed"), /SHA-256/);
engine.installDefinition(text, sha);
engine.installDefinition(text, sha);
const badArtifact = JSON.stringify({...artifact, version: 4, conformance: [
  {...artifact.conformance[0], expect: artifact.conformance[0].expect === "true" ? "false" : "true"},
]});
const badSha = createHash("sha256").update(badArtifact).digest("hex");
assert.throws(() => engine.installDefinition(badArtifact, badSha), /conformance failed/);
assert.throws(() => engine.check(find + '"Wick rejection" where quiet_friday_close_v4()'), /unavailable/);
const source = find + '"Wick rejection" where quiet_friday_close_v2(last:1h)';
assert.deepEqual(engine.study(source).results, engine.study(source.replace("_v2", "_v3")).results);
assert.throws(() => engine.check(find + "value_area_reclaim()"), /unavailable/);
assert.throws(() => engine.check(find + "wick_rejection() where close_return(after: 1h)"), /unavailable/);
assert.throws(() => engine.check(find + 'exact_g1("g1:o:0,1,2,3,u|volume:0")'), /counters/);
console.log(`Query WASM: ${count} candidates match the existing query evaluator`);
engine.close();
