import assert from 'node:assert/strict';
import { loadEnvironment } from './node-env.js';
import { analyze, registerExtension } from '../src/check.js';
import { runAnalysis, EvalContext, U } from '../src/engine.js';
import { chainedG1FromRecording, g1FromRecording, parseG1 } from '../src/g1.js';
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
// ---- chained_g1: the window read as a chain. The first bar is as recorded; every later bar opens at the close of the
// recorded bar just before it, and its low and high widen to include that open. Written here from the recorded
// columns alone, so the engine is held to a second, separate statement of the reading.
function chainCode(rec, end, bars, oriented) {
  const start = end - bars + 1; if (start < 0) return null;
  const rows = [], dirs = [];
  for (let i = start; i <= end; i++) {
    if (!rec.present[i]) return null;
    const first = i === start, o = first ? rec.O[i] : rec.C[i - 1], c = rec.C[i];
    rows.push([first ? rec.L[i] : Math.min(rec.L[i], o), Math.min(o, c), Math.max(o, c), first ? rec.H[i] : Math.max(rec.H[i], o)]);
    dirs.push(c > o ? 'u' : c < o ? 'd' : 'z');
  }
  const rank = new Map([...new Set(rows.flat())].sort((a, b) => a - b).map((v, k) => [v, k]));
  return 'g1:' + (oriented ? 'o:' : 'u:') + rows.map((r, j) => r.map((v) => rank.get(v)).concat(oriented ? [dirs[j]] : []).join(',')).join(';');
}
const slots = (find, ctx) => run(find, '', ctx).results[0].matches.map((r) => r.i);
const chained = (g) => 'chained_g1(' + JSON.stringify(g) + ')', asRecorded = (g) => 'exact_g1(' + JSON.stringify(g) + ')';
// a one-bar shape has no later bar: the two readings agree on every one-bar code the recording holds
const oneBar = new Set();
for (let i = 0; i < e.rec.n; i++) { const g = g1FromRecording(e.rec, i); if (g) { oneBar.add(g); assert.equal(chainedG1FromRecording(e.rec, i), g); } }
assert.equal(oneBar.size, 9);
for (const g of oneBar) assert.deepEqual(slots(chained(g)), slots(asRecorded(g)), g);
assert.equal(slots(chained(code)).length, 324);
for (const oriented of [true, false]) {
  const pair = chainedG1FromRecording(e.rec, anchor, 2, oriented);
  assert.equal(pair, chainCode(e.rec, anchor, 2, oriented));
  const result = run(chained(pair)).results[0], found = result.matches.map((r) => r.i);
  const independent = [];
  for (let i = 1; i < e.rec.n; i++) if (chainCode(e.rec, i, 2, oriented) === pair) independent.push(i);
  assert.deepEqual(found, independent);
  assert.ok(found.includes(anchor));
  // With directions kept, the code says which body edge is each open, so a window that matches as recorded has its
  // later open on the previous close already and matches chained too. Without directions that does not follow: a
  // recorded window can make the same tie between other body edges, and read as a chain it is a different shape.
  const kept = new Set(found), recorded = slots(asRecorded(pair));
  if (oriented) for (const i of recorded) assert.ok(kept.has(i), `slot ${i} matches as recorded but not chained`);
  else assert.ok(recorded.some((i) => !kept.has(i)), 'this unoriented pair has a recorded match the chain reads differently');
  assert.deepEqual(result.populations.unknownDetector.rows.map((r) => r.i), [0]);
  // an absent bar makes the window unknown, never false
  const gap = e.rec.withoutSlots([anchor - 1], 'test: remove recorded bar');
  const changed = run(chained(pair), '', new EvalContext(gap, e.calendars)).results[0];
  assert.equal(changed.event.series.vals[anchor], U);
  assert.equal(chainedG1FromRecording(gap, anchor, 2, oriented), null);
  assert.ok(changed.populations.unknownDetector.rows.some((r) => r.i === anchor));
}
// three bars, every window: the engine's code is the separate statement's code
for (let i = 0; i < e.rec.n; i += 7) assert.equal(chainedG1FromRecording(e.rec, i, 3), chainCode(e.rec, i, 3, true));
// the shape the reading was first counted on: its later open ties the previous close, which half the record misses by a cent
const tied = 'g1:o:0,1,3,4,u;2,3,5,6,u';
assert.equal(slots(asRecorded(tied)).length, 772);
assert.equal(slots(chained(tied)).length, 1463);
assert.equal(run(chained(tied)).manifest.pins.definitions.includes('chained_g1@1'), true);
assert.equal(analyze('on BTCUSDT 15m find chained_g1("g1:o:0,1,2,2,z")', e.env).ok, false);
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
console.log('Passed exact and chained G1, query-only runs, both extension versions, conformance, gap handling and recorded comparison populations.');
