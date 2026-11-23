import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { install } from '../../../query/verify/site.mjs';

await install();
const { engine, load, run } = await import('/shared/filang.js');
const { PRESETS } = await import('/shared/vocab.js');
const { digest } = await load();
const calls = {};
for (const name of ['describeStudy', 'studyRows', 'study']) {
  calls[name] = 0;
  const method = engine[name].bind(engine);
  engine[name] = (...args) => { calls[name]++; return method(...args); };
}
const start = performance.now();
const receipt = PRESETS.map(({ text }) => {
  const answer = run(text);
  assert.equal(answer.ok, true, text);
  const row = answer.results[0];
  const { find, wheres, group } = row.lines;
  return { counts: row.counts, survivors: row.survivors, columns: row.columns, find, wheres, group,
    unknown: row.counts.U };
});
const elapsedMs = performance.now() - start;
const sha256 = createHash('sha256').update(JSON.stringify(receipt)).digest('hex');
console.log(JSON.stringify({ elapsedMs, calls, recording: digest, sha256 }));
