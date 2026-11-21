import assert from 'node:assert/strict';
import { loadEnvironment } from './node-env.js';
import { checkPrediction, isTransferResult } from '../src/study-practice.js';
import { analyze } from '../src/check.js';
import { runAnalysis } from '../src/engine.js';
const env = loadEnvironment();
assert.deepEqual(checkPrediction(env, 'enters', 'edge'), { change: true, reason: true });
assert.deepEqual(checkPrediction(env, 'same', 'open'), { change: false, reason: false });
function run(text) {
  const a = analyze(text, env.env);
  assert.equal(a.ok, true);
  return runAnalysis(env.ctx, a);
}
const text =
  'on BTCUSDT 15m find channel_breakout(over: 18h) group by completed_trend(frame: 4h) measure close_return(after: [1h, 4h])';
assert.equal(isTransferResult(run(text)), true);
for (const wrong of [
  text.replace('18h', '24h'),
  text.replace('group by', 'where').replace(') measure', ') = up measure'),
  text.replace('[1h, 4h]', '[4h]'),
])
  assert.equal(isTransferResult(run(wrong)), false);
console.log('Practice checks passed on the recorded March candle and three different breakout answers.');
