import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { analyze } from '../src/check.js';
import { EvalContext, runCandidate, U } from '../src/engine.js';
import { compile } from '../native/compiler.mjs';
import { loadInputs } from '../native/inputs.mjs';
import { startWorker } from '../native/worker.mjs';

const {bundle, assets} = loadInputs();
const r = bundle.rec;
const head = 'on BTCUSDT 15m\nfind ';
const low = head + 'breach_reclaim(prior_low(over: 4h))';
const wick = '\nwhere candle_share(lower_wick, min: 50%)';
const expanded = '\nwhere range_multiple(over: 4h, min: 1.5)';
const later = (direction, min, max) =>
  head + 'breach_reclaim(prior_' + direction + '(over: 4h), within_min: ' + min + ', within_max: ' + max + ')';
const outcome = '\nmeasure close_return(after: [1h,4h])';
const pins = head + 'candle_window(candle_relation(price(high,bars_ago:1), is: below, right:price(high)) and candle_relation(price(close),right:price(open)), bars:2)';
const near = head + 'candle_relation(price(close), right: price(high,bars_ago:1))\nwhere near_level(prior_high(over:4h),point:price(close),within:0.25%)';
const input = assets.get('recorded-bars.csv');
const worker = await startWorker(bundle,input);
const cases = [
  [low,842],[low+wick,312],[low+wick+expanded,126],
  [later('low',1,3),432],[later('high',1,3),454],[near,1682],[pins,4828],
];
function body(query,extensions) {
  return compile(bundle,{ query, extensions, source:bundle.digest, calendar:bundle.sessionsDigest }).wire;
}
async function check(query,n, engine = worker, ctx = bundle.ctx) {
  const a = analyze(query,bundle.env);
  assert.equal(a.ok,true,JSON.stringify(a.errors));
  const expected = runCandidate(ctx,a.candidates[0]);
  const answer = await engine.evaluate(body(query));
  assert.equal(answer.error,undefined);
  const got = answer.results[0];
  if (n !== undefined) assert.equal(got.counts.matches,n);
  assert.deepEqual(got.anchors,expected.matches.map(x=>x.t));
  assert.deepEqual(got.eligible,expected.populations.eligible.rows.map(x=>x.t));
  assert.deepEqual(got.unknown.eligibility,expected.populations.unknownContextAnchors);
  assert.deepEqual(got.unknown.detectorWithinContext,expected.populations.unknownDetector.rows.map(x=>x.t));
  assert.deepEqual(got.rows,expected.matches.map(({i,t,group,out})=>{
    const trace=expected.event.series.evidence?.(i);
    return {t,group:group?.key ?? null,out:out.map(({status,value})=>({status,value})),...(trace ? {reclaim: trace} : {})};
  }));
  return got;
}

// Independent, direct first-reclaim oracle for the complete recording.
function oracle(high, min, max) {
  const rows = new Map();
  const side = high ? -1 : 1;
  for(let j=16;j<r.n;j++) {
    const prev = Array.from(high ? r.H.slice(j-16,j):r.L.slice(j-16,j));
    const level = high ? Math.max(...prev) : Math.min(...prev);
    if (side*r.O[j] < side*level || side*(high ? r.H[j] : r.L[j]) >= side*level) continue;
    for(let lag=0;lag<=max && j+lag<r.n;lag++) {
      const i=j+lag;
      if (side*r.C[i] <= side*level) continue;
      if(lag>=min) rows.set(r.closeTime(i), {breach:r.closeTime(j),reclaim:r.closeTime(i),level});
      break;
    }
  }
  return rows;
}
try {
  for(const [query,n] of cases) {
    const result=await check(query+outcome,n);
    if(query.includes('within_min')) {
      const wants=oracle(query.includes('prior_high'),1,3);
      assert.deepEqual(result.anchors,[...wants.keys()].sort((a,b)=>a-b));
      for(const row of result.rows) assert.deepEqual(row.reclaim,wants.get(row.t));
    }
    console.log(n, query.split('\n').slice(1).join(' · '));
  }

  const one=later('low',1,1);
  const original=await check(one);
  const removed=r.slotClosingAt(original.rows[0].reclaim.breach);
  const laterPoint=original.rows[0].t;
  const recorded=input.toString('utf8').split('\n').filter((_,i)=>i!==removed+1).join('\n');
  const gapWorker=await startWorker(bundle,recorded);
  try {
    const gap=new EvalContext(r.withoutSlots([removed],'with one observed row removed'),bundle.calendars);
    const gappy=await check(one,undefined,gapWorker,gap);
    assert.ok(gappy.unknown.event.includes(laterPoint));
    assert.ok(!gappy.anchors.includes(laterPoint));
  } finally {gapWorker.close();}

  const exact=await check(low+wick+expanded,126);
  const def=await readFile(new URL('../examples/long_wick_reclaim.v1.json',import.meta.url),'utf8');
  const portable=await worker.evaluate(body(head+'long_wick_reclaim()',[{text:def,sha256:createHash('sha256').update(def).digest('hex')}]));
  assert.deepEqual(portable.results[0].anchors,exact.anchors);

  const sweep=await worker.evaluate(body(low+'\nwhere range_multiple(over:4h,min:{1 | 1.5 | 2})'));
  assert.equal(sweep.work.candidates,3);
  assert.equal(sweep.work.medianWindows,1);
  assert.equal(analyze(later('low',4,3),bundle.env).ok,false);
  assert.equal(analyze(later('low',0,65),bundle.env).ok,false);
  console.log('Confirmed native evidence, exact boundaries, recorded gaps, shared median preparation and portable event definitions.');
} finally {worker.close();}
