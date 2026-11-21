import assert from 'node:assert/strict';
import { loadEnvironment } from './node-env.js';
import { analyze, registerExtension } from '../src/check.js';
import { runAnalysis, EvalContext, U } from '../src/engine.js';
import { g1FromRecording, parseG1 } from '../src/g1.js';
import { runConformance } from '../src/conformance.js';
import { Registry } from '../src/registry.js';
import { installExtension } from '../src/boot.js';

const e = loadEnvironment();
const anchor = e.rec.slotClosingAt(Date.parse('2025-03-28T19:30:00Z'));
const code = g1FromRecording(e.rec, anchor);
assert.equal(code, 'g1:o:0,1,2,2,u');
const exact = 'exact_g1(' + JSON.stringify(code) + ')';
const wick = '"Wick rejection"';
function run(find, suffix = '', ctx = e.ctx) {
  const a = analyze('on BTCUSDT 15m\nfind ' + find + '\n' + suffix, e.env);
  assert.equal(a.ok, true, JSON.stringify(a.errors));
  return runAnalysis(ctx, a, { extensions: e.extensions, digestVerified: e.digestVerified });
}
const all = run(exact).results[0], ratio = run(wick).results[0];
assert.equal(all.columns.length, 0);
assert.equal(all.matches.length, 324);
assert.equal(ratio.matches.length, 2077);
assert.equal(all.matches.filter((r) => ratio.rowsBySlot.has(r.i)).length, 49);
const context = 'where quiet_friday_close(last: {30m | 1h})\nmeasure close_return(after: [1h, 4h])';
for (const [find, n] of [[wick, [2, 4]], [exact, [0, 1]]]) {
  const run1 = run(find, context);
  assert.deepEqual(run1.manifest.pins.extensions.map((x) => x.id), ['quiet_friday_close@1']);
  run1.results.forEach((r,k) => {
    const p = r.populations, eligible = [10, 20][k];
    assert.equal(p.matching.count, n[k]);
    assert.equal(p.eligible.count, eligible);
    assert.equal(p.nonmatching.count, eligible - n[k]);
    assert.equal(p.unknownDetector.count, 0);
    assert.equal(p.eligible.sessionCount, 5);
    assert.equal(p.eligible.summary[0].observed, eligible);
    assert.deepEqual(p.matching.rows.map((x) => x.i), r.matches.map((x) => x.i));
    assert.ok(p.unknownContextCount > 0);
    assert.equal(p.unknownContextCount,p.unknownContextAnchors.length);
    assert.ok(p.unknownContextAnchors.includes(e.rec.closeTime(0)));
  });
}
for (const oriented of [true,false]) {
  const pair = g1FromRecording(e.rec, anchor, 2, oriented);
  const selected = run('exact_g1(' + JSON.stringify(pair) + ')').results[0];
  // Composer matcher at 133e301 agrees on every matching slot of this two-bar drawing.
  assert.equal(selected.matches.length, oriented ? 9 : 10);
  const independent = [];
  for (let i = 1; i < e.rec.n; i++) if (g1FromRecording(e.rec,i,2,oriented) === pair) independent.push(i);
  assert.deepEqual(selected.matches.map((r) => r.i), independent);
  assert.deepEqual(selected.populations.unknownDetector.rows.map((r) => r.i), [0]);
  const gap = e.rec.withoutSlots([anchor-1], 'test: remove recorded bar');
  const changed = run('exact_g1(' + JSON.stringify(pair) + ')','', new EvalContext(gap,e.calendars)).results[0];
  assert.equal(changed.event.series.vals[anchor], U);
  assert.equal(g1FromRecording(gap,anchor,2,oriented), null);
  assert.equal(changed.counts.absent,1);
  assert.ok(changed.populations.unknownDetector.rows.some(r=>r.i===anchor));
  assert.ok(!changed.populations.nonmatching.rows.some(r=>r.i===anchor));
}
for (const malformed of ['g1:u:', 'g1:o:0,1,2,2,z','g1:u:0,1,3,3','g1:o:0,1,1,2,u','g1:u:0,00,1,2','g1:u:0,2,1,2','g1:o:0,1,2,2,u;','g1:u:0,1,1,2,z']) {
  assert.throws(() => parseG1(malformed));
  assert.equal(analyze('on BTCUSDT 15m find exact_g1(' + JSON.stringify(malformed) + ')',e.env).ok,false);
}
const v2run=run(wick,context.replace('quiet_friday_close(', 'quiet_friday_close_v2('));
assert.deepEqual(v2run.results.map(r=>r.matches.length),[0,0]);
assert.deepEqual(v2run.manifest.pins.extensions.map(x=>x.id), ['quiet_friday_close@2']);
assert.ok(v2run.manifest.pins.definitions.includes('range_contained@1'));
assert.deepEqual(run(wick).manifest.pins.extensions,[]);
for (const ext of e.extensions) {
  assert.ok(ext.ok, JSON.stringify(ext.errors));
  assert.ok(runConformance(e,ext.def).every(c=>c.pass));
}
const art=e.extensions[1].artifact;
assert.equal(registerExtension(new Registry(),{...art,depends:art.depends.slice(1)},e.env).ok,false);
assert.equal(registerExtension(e.registry,art,e.env).ok,false);
const corrupted = { ...art, version: 3, conformance: [{ anchor: '2025-03-28T19:30:00Z', args: {}, expect: 'true' }] };
const refused = installExtension(e, { file: 'agent-v3', bytes: new TextEncoder().encode(JSON.stringify(corrupted)) });
assert.equal(refused.ok,false);
assert.ok(!e.registry.get('quiet_friday_close_v3'));
console.log('Passed exact G1, query-only runs, both extension versions, conformance, gap handling and recorded comparison populations.');
