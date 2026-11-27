// Run with the local native worker, or pass a loopback origin to exercise HTTP.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { loadInputs } from '../native/inputs.mjs';
import { startWorker } from '../native/worker.mjs';
import { compile, QueryError } from '../native/compiler.mjs';
import { analyze } from '../src/check.js';
import { runCandidate, compileBool, kAnd, U, EvalContext } from '../src/engine.js';
import { chainedG1FromRecording, g1FromRecording } from '../src/g1.js';
import { EXAMPLES } from '../src/examples.js';
import { CANDLE_PATTERNS } from '../src/registry.js';

const base = process.argv[2];
const {bundle:e, assets} = loadInputs();
const worker = base ? null : await startWorker(e, assets.get('recorded-bars.csv'));
const previous = process.env.FILANG_BASELINE_NATIVE_ROOT;
let baseline;
if (previous && !base) {
  const original = process.env.FILANG_STUDY_BIN;
  const moduleAt = (name) => pathToFileURL(resolve(previous, 'study/native', name));
  process.env.FILANG_STUDY_BIN = process.env.FILANG_BASELINE_NATIVE_BIN || resolve(previous, 'target/release/filang');
  try {
    const [{ compile }, { startWorker }] = await Promise.all([
      import(moduleAt('compiler.mjs')), import(moduleAt('worker.mjs')),
    ]);
    baseline = { compile, startWorker, worker: await startWorker(e, assets.get('recorded-bars.csv')) };
  } finally {
    if (original === undefined) delete process.env.FILANG_STUDY_BIN;
    else process.env.FILANG_STUDY_BIN = original;
  }
}
async function evaluate(request) {
  if (base) {
    const r = await fetch(new URL('/api/filang/evaluate', base), {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(request)
    });
    return {status:r.status, result:await r.json()};
  }
  try {
    const checked = compile(e, request);
    const native = await worker.evaluate(checked.wire);
    if (baseline && !native.error) {
      const old = baseline.compile(e, request);
      assert.deepEqual(checked.canonical, old.canonical);
      assert.deepEqual(checked.candidates, old.candidates);
      assert.deepEqual(native, await baseline.worker.evaluate(old.wire), request.query);
    }
    if (native.error) return {status:422,result:native};
    const {results, ...metadata} = native;
    return {status:200,result:results.length === 1 ? {...results[0],...metadata} : native};
  } catch (err) {
    if (!(err instanceof QueryError)) throw err;
    return {status:422,result:{kind:err.kind,error:err.message}};
  }
}
function post(query, source = e.digest, extensions = [], candidate) {
  return evaluate({query, source, calendar: e.sessionsDigest, extensions, candidate});
}
try {
const find = 'on BTCUSDT 15m\nfind ';
const chainSlot = e.rec.slotClosingAt(Date.parse('2025-03-28T19:30:00Z'));
const queries = [
  ...['starter','transfer','transfer-filter'].map(id=>EXAMPLES.find(x=>x.id===id).text),
  find + 'exact_g1("g1:o:0,1,2,2,u") where quiet_friday_close(last: {30m | 1h})',
  find + 'exact_g1("g1:u:0,1,2,2") measure close_return(after: 4h)',
  find + 'exact_g1(' + JSON.stringify(g1FromRecording(e.rec,e.rec.slotClosingAt(Date.parse('2025-03-28T19:30:00Z')),2)) + ')',
  find + '"Wick rejection" where quiet_friday_close_v2(last: 1h) measure close_return(after: [1h,4h])',
  find + '"Wick rejection" where not held("Quiet range", for: 48h)',
  find + '"Wick rejection" group by weekday(nyse_regular) = fri measure close_return(after: 7d)',
  find + 'wick_rejection(body_max: 0.' + '3'.repeat(4310) + ', wick_min: 45%) where weekday(nyse_regular) = closed',
  find + 'exact_g1("g1:o:0,0,0,0,z") group by weekday(nyse_regular)',
  // the chained reading: a short window through the key cache, both orientations, and a window too long for keys
  find + 'chained_g1("g1:o:0,1,3,4,u;2,3,5,6,u") measure close_return(after: [1h,4h])',
  find + 'chained_g1(' + JSON.stringify(chainedG1FromRecording(e.rec,chainSlot,2,false)) + ')',
  find + 'chained_g1(' + JSON.stringify(chainedG1FromRecording(e.rec,chainSlot,3)) + ') group by weekday(nyse_regular)',
  find + 'chained_g1(' + JSON.stringify(chainedG1FromRecording(e.rec,chainSlot,12)) + ')',
  // both readings of one code in one plan: they must not answer from each other's keys
  find + 'chained_g1("g1:o:0,1,3,4,u;2,3,5,6,u") and exact_g1("g1:o:0,1,3,4,u;2,3,5,6,u")',
  find + 'chained_g1("g1:o:1,3,4,5,u;0,2,4,6,d") or exact_g1("g1:o:0,1,3,4,u;2,3,5,6,u")',
  find + '"Wick rejection" where weekday(nyse_regular) = closed and not session_tail(nyse_regular,last:390m)',
  find + '"Wick rejection" where completed_trend(frame:15m) = flat or not (weekday(nyse_regular) != fri)'
];
for (const entry of CANDLE_PATTERNS.patterns) queries.push(find + JSON.stringify(entry.ja));
queries.push(find + '包み線 where ハンマー or weekday(nyse_regular) = fri group by completed_trend(frame:4h) measure close_return(after:[1h,4h])');
queries.push(find + 'hammer or engulfing', find + 'hammer and engulfing',
  find + '(カラカサ or 陽の包み線) and inside_bar where weekday(nyse_regular) = fri measure close_return(after:1h)');
let count = 0;
for (const text of queries) {
  const checked = analyze(text,e.env);
  assert.equal(checked.ok,true,JSON.stringify(checked.errors));
  for (const candidate of checked.candidates) {
    const expected = runCandidate(e.ctx,candidate);
    const {status,result} = await post(candidate.resolvedText);
    assert.equal(status,200,result.error);
    const scopes = candidate.plan.wheres.map(p=>compileBool(e.ctx,p));
    const unknownEvent = [], unknownEligibility = [];
    for (let i=0;i<e.rec.n;i++) {
      if (!e.rec.present[i]) continue;
      if (expected.event.series.vals[i] === U) unknownEvent.push(e.rec.closeTime(i));
      if (kAnd(scopes.map(c=>c.at(i).v)) === U) unknownEligibility.push(e.rec.closeTime(i));
    }
    assert.deepEqual(result.unknown.event,unknownEvent);
    assert.deepEqual(result.unknown.eligibility,unknownEligibility);
    assert.deepEqual(result.eligible,expected.populations.eligible.rows.map(r=>r.t));
    assert.deepEqual(result.unknown.detectorWithinContext,expected.populations.unknownDetector.rows.map(r=>r.t));
    assert.equal(result.counts.event,expected.counts.T);
    assert.equal(result.counts.nonmatching,expected.populations.nonmatching.count);
    assert.deepEqual(result.anchors,expected.matches.map(r=>r.t));
    assert.deepEqual(result.rows,expected.matches.map(r=>({
      t:r.t, group:r.group?.key ?? null, out:r.out.map(o=>({status:o.status,value:o.value}))
    })));
    console.log('PASS',candidate.resolvedText.split('\n').slice(1,3).join(' • ').slice(0,95),result.counts.matches);
    count++;
  }
}
assert.equal((await post(queries[0],'changed')).result.kind,'pins');
assert.equal((await post('on BTCUSDT 15m find value_area_reclaim() measure close_return(after:1h)')).result.kind,'capability');
const definition = e.extensions.find(x => x.version === 2).artifact;
const text = JSON.stringify({...definition, version: 3});
const sha256 = createHash('sha256').update(text).digest('hex');
const localQuery = find + '"Wick rejection" where quiet_friday_close_v3(last: 1h, width_max: 6%)';
const original = await post(localQuery.replace('_v3', '_v2'));
const installed = await post(localQuery, e.digest, [{text,sha256}]);
assert.equal(installed.status,200,installed.result.error);
assert.deepEqual(installed.result.anchors,original.result.anchors);
assert.ok(installed.result.anchors.length);
assert.equal((await post(localQuery, e.digest, [{text,sha256:'changed'}])).result.kind,'pins');
console.log(count + ' native plans agree on timestamps, unknowns, cohorts, groups and outcomes. Pin and capability refusals passed.');
// This is a structural assertion, with no inference about timing or throughput.
const batchText = find + 'hammer where range_contained(over: 48h, width_max: {3% | 4% | 5%})';
const {status:batchStatus, result:batch} = await post(batchText);
assert.equal(batchStatus,200,batch.error);
assert.equal(batch.work.candidates,3);
assert.equal(batch.work.rollingWindows,1);
for (let i=0;i<3;i++) assert.deepEqual(batch.results[i].anchors,(await post(batchText,e.digest,[],i)).result.anchors);
const patterns = find + 'exact_g1({"g1:o:0,1,2,2,u" | "g1:o:0,1,2,2,d"})';
const {status:gStatus, result:geom} = await post(patterns);
assert.equal(gStatus,200,geom.error);
assert.equal(geom.work.geometryWindows,1);
assert.equal(geom.work.candidates,2);
// One preparation per reading: the chained keys are built once for both chained codes and never reused for exact_g1.
const readings = find + 'chained_g1({"g1:o:0,1,3,4,u;2,3,5,6,u" | "g1:o:1,3,4,5,u;0,2,4,6,d"}) or exact_g1("g1:o:0,1,3,4,u;2,3,5,6,u")';
const {status:rStatus, result:both} = await post(readings);
assert.equal(rStatus,200,both.error);
assert.equal(both.work.candidates,2);
assert.equal(both.work.geometryWindows,2);
const equivalent = [
  ['hammer where held(quiet_range(), for: 60m) and held(quiet_range(), for: 1h)', 4],
  ['hammer where range_multiple(over: 60m) and range_multiple(over: 1h)', 3],
  ['hammer where candle_share(body) and candle_share(body, min: 50%)', 3],
];
for (const [query, unique] of equivalent) {
  const {status, result} = await post(find + query);
  assert.equal(status, 200, result.error);
  assert.equal(result.work.nodes, unique, query);
}
console.log('Passed native batch parity and shared rolling-window and G1 preparation checks.');
// The native worker also checks an observed prefix with deleted real rows.
const hammer = analyze(find + 'hammer', e.env).candidates[0];
const anchors = runCandidate(e.ctx, hammer).matches;
const gap = anchors[0].i + 4;
const cutoff = anchors.at(-1).i + 1;
const csv = assets.get('recorded-bars.csv').toString('utf8').trimEnd().split('\n');
const observed = csv.slice(0, cutoff + 2).filter((_, i) => i !== gap + 1 && i !== 72).join('\n') + '\n';
const gappy = new EvalContext(e.rec.truncatedAfter(cutoff).withoutSlots([71, gap], 'delete recorded bars'), e.calendars);
const gapWorker = await startWorker(e, observed);
const baselineGap = baseline && await baseline.startWorker(e, observed);
try {
  const questions = [
    find + 'hammer measure close_return(after: 1h)',
    find + 'hammer or engulfing where not held(quiet_range(width_max: 3%), for: 48h) group by completed_trend(frame: 4h)',
    find + 'channel_breakout(over: 1h) where range_contained(over: 4h, width_max: 2.5%)',
  ];
  for (const q of questions) {
    const request = {query:q,source:e.digest,calendar:e.sessionsDigest};
    const {wire} = compile(e,request);
    const answer = await gapWorker.evaluate(wire);
    assert.equal(answer.error, undefined);
    if (baselineGap) assert.deepEqual(answer, await baselineGap.evaluate(baseline.compile(e, request).wire), q);
    const got = answer.results[0];
    const expected = runCandidate(gappy, analyze(q,e.env).candidates[0]);
    assert.equal(got.counts.absent, 2);
    assert.deepEqual(got.eligible, expected.populations.eligible.rows.map(x => x.t));
    assert.deepEqual(got.unknown.eligibility, expected.populations.unknownContextAnchors);
    assert.deepEqual(got.unknown.detectorWithinContext, expected.populations.unknownDetector.rows.map(x => x.t));
    assert.deepEqual(got.rows, expected.matches.map(x => ({
      t:x.t, group:x.group?.key ?? null, out:x.out.map(({status,value}) => ({status,value})),
    })));
    if (q === questions[0]) {
      assert.equal(got.rows[0].out[0].status,'unknown');
      assert.equal(got.rows.at(-1).out[0].status,'censored');
    }
  }
  console.log('Passed three native gap/prefix plans with recorded rows and distinct unknown and censored horizons.');
} finally { gapWorker.close(); baselineGap?.close(); }
if (baseline) console.log('Exact engine-to-engine parity for native responses, including custom definitions and gap fixtures.');
} finally { worker?.close(); baseline?.worker.close(); }
