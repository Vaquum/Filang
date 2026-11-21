import assert from 'node:assert/strict';
import '../composer/sync-patterns.mjs';
import { inputBytes } from '../native/inputs.mjs';
import vm from 'node:vm';
import { createHash } from 'node:crypto';
import {
  COMPOSER_REVISION,
  DEFAULT_ANCHOR,
  drawingG1,
  encodeDrawing,
  decodeDrawing,
} from '../composer/drawing.js';
import { loadEnvironment } from './node-env.js';
const file = (name) => inputBytes('composer/' + name);
const { rec } = loadEnvironment();
const upstream = vm.runInNewContext(
  file('matcher.js').toString() + '\n({ decode, decodeActivity, compile, flips })',
);
const bytes = file('bars');
assert.equal(
  createHash('sha256').update(bytes).digest('hex'),
  '9f301d3f74a75d828814af74c59cf4781fa63b68f300379ddb47bc667f10b324',
);
const [frame] = upstream.decode(new Uint8Array(bytes).buffer);
assert.equal(frame.n, rec.n);
for (let i = 0; i < frame.n; i++) {
  for (const field of ['O', 'H', 'L', 'C']) assert.equal(frame[field][i], rec[field][i]);
  assert.equal((frame.ts[i] + frame.sec) * 1000, rec.closeTime(i));
}
// The worker counts the descriptor on the integer tape and returns observed closes in UTC.
let reply;
const worker = vm.createContext({ self: { postMessage: (message) => { reply = message; } }, frame });
vm.runInContext(file('patterns.js').toString() + '\n' + file('matcher.js').toString() + '\nBARS = [frame];', worker);
async function scan(pattern) {
  await worker.self.onmessage({data: {type: 'named-pattern', id:1, pattern, timeframe:'15m'}});
  assert.equal(reply.type,'named-pattern');
  assert.equal(reply.error,undefined);
  return reply;
}
let matches = 0;
for (let i = 0; i < frame.n; i++) {
  const body = Math.abs(frame.O[i] - frame.C[i]);
  const lower = Math.min(frame.O[i], frame.C[i]) - frame.L[i];
  const upper = frame.H[i] - Math.max(frame.O[i], frame.C[i]);
  if (body > 0 && lower >= 2 * body && 2 * upper <= body) matches++;
}
const hammers = await scan('hammer');
assert.equal(matches,439);
assert.equal(hammers.count,matches);
assert.equal(hammers.eligible,rec.n);
assert.equal(hammers.samples.length,8);
for (const [index,sample] of hammers.samples.entries()) {
  const i = rec.slotClosingAt(sample.close * 1000);
  assert.deepEqual([...sample.bars[0]], [rec.O[i],rec.H[i],rec.L[i],rec.C[i]]);
  if (index) assert(hammers.samples[index-1].close > sample.close);
}
assert.equal((await scan('four-price-doji')).count,0);
assert.equal((await scan('inside-bar')).eligible,rec.n-1);
// Omit an intervening observed candle between two real endpoint bars whose prices satisfy Inside bar.
let gapped = false;
for (let i=2; i<frame.n && !gapped; i++) {
  if (frame.L[i] > frame.L[i-2] && frame.H[i] < frame.H[i-2]) {
    const segment={name:'15m',n:2,sec:frame.sec,run:[1,1]};
    for (const field of ['O','H','L','C','ts']) segment[field]=[frame[field][i-2],frame[field][i]];
    worker.gappedFrame = segment;
    vm.runInContext('BARS = [gappedFrame]',worker);
    const result = await scan('inside-bar');
    assert.equal(result.eligible,0);
    assert.equal(result.count,0);
    gapped = true;
  }
}
assert(gapped);
const activity = file('activity');
assert.equal(
  createHash('sha256').update(activity).digest('hex'),
  '7b59f7882fde0a7de11413f5b2a53f9b7cb628ad871036f0c430ec25e21f62b0',
);
assert.equal(upstream.decodeActivity(new Uint8Array(activity).buffer)[0].n, frame.n);
const i = rec.slotClosingAt(DEFAULT_ANCHOR);
const base = {
  version: 1,
  revision: COMPOSER_REVISION,
  bars: [
    { v: [frame.L[i], Math.min(frame.O[i], frame.C[i]), Math.max(frame.O[i], frame.C[i]), frame.H[i]], d: 'u' },
  ],
  oriented: true,
  pins: [],
  skeleton: 0,
  stretch: 0,
  next: { dir: 0, measure: 'any', bps: 10, atr: 1 },
  limit: 12,
};
const id = drawingG1(base);
assert.equal(id, 'g1:o:0,1,2,2,u');
const query = upstream.compile({
  bars: [[frame.O[i], frame.H[i], frame.L[i], frame.C[i]]],
  oriented: true,
  holds: [],
});
let count = 0;
for (let j = 0; j < frame.n; j++)
  if (
    upstream.flips(query, [frame.O[j]], [frame.H[j]], [frame.L[j]], [frame.C[j]], new Float64Array(4), 0) === 0
  )
    count++;
assert.equal(count, 324);
assert.deepEqual(decodeDrawing(encodeDrawing(base), id), base);
assert.throws(() => decodeDrawing(encodeDrawing(base), 'g1:u:0,1,2,2'));
assert.throws(() => encodeDrawing({ ...base, bars: [...base.bars, ...base.bars] }));
assert.throws(() => encodeDrawing({ ...base, pins: [{ bar: 999, color: true }] }));
assert.throws(() => encodeDrawing({ ...base, stretch: 4 }));
const two = {
  ...base,
  bars: [
    { v: [0, 1, 2, 3], d: 'u' },
    { v: [-1, 1, 2, 4], d: 'd' },
  ],
  pins: [
    { bar: 0, color: true },
    { a: { bar: 0, part: 'T' }, b: { bar: 1, part: 'B' } },
  ],
  skeleton: 1,
  stretch: 2,
  oriented: false,
  next: { dir: -1, measure: 'atr', bps: 10, atr: 0.5 },
  limit: 48,
};
assert.deepEqual(decodeDrawing(encodeDrawing(two), drawingG1(two)), two);
console.log(
  'Composer verified. All 14,496 OHLC rows agree, the selected candle has 324 exact twins, and drawings replay with their pins and settings.',
);
