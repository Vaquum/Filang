import assert from 'node:assert/strict';
import { loadEnvironment } from './node-env.js';
import { sha256Hex } from '../src/data.js';
import { installSaved, installLocal, loadInstalled } from '../src/study-extensions.js';
import { analyze } from '../src/check.js';
import { runAnalysis } from '../src/engine.js';
import { evaluateConditionText } from '../src/conformance.js';

const bundle = loadEnvironment();
const orig = bundle.extensions.find((r) => r.def.version === 2).artifact;
function source(artifact) {
  const text = JSON.stringify(artifact);
  return { file: artifact.id + '.json', text, sha256: sha256Hex(new TextEncoder().encode(text)) };
}
const anchor = '2025-03-28T20:00:00Z';
const event = {
  ...orig, id: 'test_retry', version: 1, kind: 'event',
  params: [{ name: 'last', type: 'Duration', default: '30m' }],
  body: 'weekday(nyse_regular) = fri and session_tail(nyse_regular, last: last)',
  depends: [{ name: 'weekday', version: 1 }, { name: 'session_tail', version: 1 },
    { calendar: 'nyse_regular', table: bundle.cal.id }],
  conformance: [{ anchor, args: { last: '30m' }, expect: 'false' }],
};
// A rejected event must not seed the series used by an edited retry or later query.
assert.throws(() => installSaved(bundle, [source(event)]), /expected false, observed true/);
const edited = { ...event, body: 'weekday(nyse_regular) = fri and not session_tail(nyse_regular, last: last)' };
assert.throws(() => installSaved(bundle, [source({ ...edited,
  conformance: [{ anchor, args: { last: '30m' }, expect: 'true' }] })]), /expected true, observed false/);
assert.equal(bundle.registry.get('test_retry'), null);
installSaved(bundle, [source(edited)]);
assert.equal(evaluateConditionText(bundle, 'test_retry(last: 30m)', anchor).got, 'false');
// Neither an argument value nor its name may escape the extension call.
for (const args of [
  { last: '30m) and not test_injection(last: 30m' },
  { 'last: 30m) and not test_injection(last': '30m' },
  { undeclared: '30m' },
]) {
  assert.throws(() => installSaved(bundle, [source({ ...event, id: 'test_injection',
    conformance: [{ anchor, args, expect: 'false' }] })]), /invalid conformance argument/);
  assert.equal(bundle.registry.get('test_injection'), null);
}
// Literal comments must not hide later arguments and substitute their defaults.
assert.throws(() => installSaved(bundle, [source({ ...orig, id: 'test_comment', version: 1,
  conformance: [{ anchor: '2025-03-28T19:30:00Z',
    args: { last: '30m --', width_max: '0\n' }, expect: 'false' }] })]), /width_max: 0 must be greater than 0%/);
assert.equal(bundle.registry.get('test_comment'), null);
assert.equal(installSaved(bundle, [source({ ...orig, id: 'test_literal', version: 1,
  conformance: [{ ...orig.conformance[1], args: { width_max: 0.06 } }] })])[0].ok, true);
const child = source({ ...orig, id: 'test_contained', version: 2 });
const parent = source({ ...orig, id: 'test_friday', version: 1,
  body: 'test_contained_v2(last: last, quiet_for: quiet_for, width_max: width_max)',
  depends: [{ name: 'test_contained', version: 2 }] });
const bad = source({ ...orig, id: 'test_bad', version: 1, conformance: [{anchor: '2025-03-28T19:30:00Z', args: {}, expect: 'true'}] });
assert.throws(() => installSaved(bundle,[child,bad]), /failed validation/);
assert.equal(bundle.registry.get('test_contained_v2'),null);
assert.throws(() => installSaved(bundle,[{...child,sha256:'000'}]), /digest mismatch/);
const files = new Map();
const store = { getItem: (k) => files.get(k) ?? null, setItem: (k,v) => files.set(k,v) };
assert.throws(() => installLocal(bundle,[child],{...store,setItem(){throw new Error('quota')}}),/quota/);
assert.equal(bundle.registry.get('test_contained_v2'),null);
const installed = installLocal(bundle,[parent,child],store);
assert.deepEqual(installed.map((r) => r.def.name),['test_friday','test_contained_v2']);
const restored = loadEnvironment();
loadInstalled(restored,store);
assert.equal(restored.registry.extensions.length,4);
assert.equal(installSaved(restored,[parent])[0].def,restored.registry.get('test_friday'));
assert.equal(restored.registry.extensions.length,4);
assert.throws(() => installSaved(restored,[source({...orig,id:'test_contained',version:2,title:'different'})]),/different content/);
const cycleA=source({...orig,id:'test_a',version:1,depends:[{name:'test_b',version:1}]});
const cycleB=source({...orig,id:'test_b',version:1,depends:[{name:'test_a',version:1}]});
assert.throws(()=>installSaved(restored,[cycleB,cycleA]),/Cyclic/);
const question = 'on BTCUSDT 15m find "Wick rejection" where test_friday(last: 1h)';
const a = analyze(question,restored.env);
assert.equal(a.ok,true);
const result = runAnalysis(restored.ctx,a,{extensions:restored.extensions});
assert.deepEqual(result.manifest.pins.extensions.map((r)=>r.id),['test_contained@2','test_friday@1']);
assert.equal(result.results[0].matches.length,0);
console.log('Passed local install, portable restore, transitive pins, digest conflicts and atomic failure checks.');
