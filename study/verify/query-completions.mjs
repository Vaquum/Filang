import assert from 'node:assert/strict';
import { analyze } from '../src/check.js';
import { queryCompletions, applyCompletion } from '../src/query-completions.js';
import { loadEnvironment } from './node-env.js';
import { installSaved } from '../src/study-extensions.js';
import { sha256Hex } from '../src/data.js';

const bundle = loadEnvironment();
const { env } = bundle;
const header = 'on BTCUSDT 15m\n';
const study = header + 'find "Wick rejection"\n';
function suggest(marked, environment = env) {
  const caret = marked.indexOf('§');
  assert.notEqual(caret, -1);
  const text = marked.replace('§', '');
  const { context, items } = queryCompletions(text, caret, environment);
  return {
    items,
    labels: items.map(x => x.label),
    context,
    choose(label) {
      const item = items.find(x => x.label === label);
      assert.ok(item, JSON.stringify({ label, context, labels: items.map(x => x.label) }));
      return applyCompletion(text, item);
    },
  };
}
function valid(text) {
  const result = analyze(text, env);
  assert.equal(result.ok, true, JSON.stringify({ text, errors: result.errors }));
}
function everyRuns(base) {
  const res = suggest(base + '§');
  assert.ok(res.items.length);
  for (const item of res.items) valid(applyCompletion(base, item).text);
  return res;
}
const find = everyRuns(header + 'find ');
const where = everyRuns(study + 'where ');
const group = everyRuns(study + 'group by ');
everyRuns(study + 'measure ');
assert.ok(find.labels.includes('exact_g1') && find.labels.includes('channel_breakout'));
assert.ok(!find.labels.includes('quiet_range') && !find.labels.includes('breach_reclaim'));
assert.ok(where.labels.includes('quiet_friday_close') && where.labels.includes('quiet_friday_close_v2'));
assert.ok(!where.labels.includes('close_return'));
assert.ok(group.choose('completed_trend').text.endsWith('completed_trend(frame: 4h)'));
assert.ok(where.choose('completed_trend').text.endsWith('completed_trend(frame: 4h) = up'));

const catalog = env.registry.implemented().filter(f => f.patternId);
assert.ok(catalog.length >= 20);
for (const def of catalog) {
  const named = find.items.filter(x => x.label === def.canonicalName);
  assert.equal(named.length, 1);
  assert.ok(named[0].aliases.includes(def.ja));
  assert.ok(suggest(header + 'find ' + def.ja + '§').labels.includes(def.canonicalName));
}
const hammered = suggest(header + 'find "Ha§mmer"\nmeasure close_return(after: 1h)').choose('Hammer');
valid(hammered.text);
assert.equal(hammered.text.slice(hammered.caret), '\nmeasure close_return(after: 1h)');
assert.ok(suggest(header + 'find bullish engu§').labels.includes('Bullish engulfing'));
valid(suggest(header + 'find bullish engu§').choose('Bullish engulfing').text);

assert.equal(suggest('§').choose('on').text, header);
assert.equal(suggest('on B§TCUSDT 15m\nfind hammer').choose('BTCUSDT').text, header + 'find hammer');
assert.ok(suggest('on BTCUSDT §').labels.includes('15m'));
assert.ok(suggest(header + '§').labels.includes('find'));
assert.ok(
  suggest(header + 'let §')
    .choose('lookback')
    .text.includes('lookback = {12h | 24h}')
);

const param = suggest(header + 'find channel_breakout(ov§er: 4h)\nmeasure close_return(after: 1h)');
assert.equal(param.choose('over:').text, header + 'find channel_breakout(over: 4h)\nmeasure close_return(after: 1h)');
const existing = suggest(header + 'find channel_bre§akout(over: 4h)').choose('channel_breakout');
assert.equal(existing.text, header + 'find channel_breakout(over: 4h)');
const combined = suggest(study + 'where weekday(nyse_regular) = fri and (§)\nmeasure close_return(after: 1h)');
valid(combined.choose('quiet_range').text);
const reversed = suggest(study + 'where fri = §');
valid(reversed.choose('weekday').text);
assert.ok(!reversed.labels.includes('completed_trend'));
const comparison = suggest(study + 'where weekday(nyse_regular) != §');
assert.ok(comparison.labels.includes('fri') && !comparison.labels.includes('down'));
const continuation = suggest(study + 'group by weekday(nyse_regular) §');
assert.ok(continuation.labels.includes('measure') && !continuation.labels.includes('and'));
const timed = suggest(study + 'where session_tail(nyse_regular, last: §)');
assert.ok(timed.labels.includes('1h') && !timed.labels.includes('12h'));
const state = suggest(study + 'where held(§, for: 1h)');
valid(state.choose('Quiet range').text);
const held = suggest(study + 'where held("Quiet range" §');
assert.ok(held.labels.includes('for:') && !held.labels.includes('state:'));
valid(held.choose('for:').text);

const sweep = suggest(header + 'find channel_breakout(over: §)');
valid(sweep.choose(sweep.items.find(x => x.kind === 'sweep').label).text);
const durations = suggest(study + 'measure close_return(after: [1h, §])');
assert.ok(durations.labels.includes('4h') && !durations.labels.includes('1h'));
valid(durations.choose('4h').text);
const enums = suggest(study + 'where completed_trend(frame: 4h) = {flat | §}');
assert.ok(!enums.labels.includes('flat'));
valid(enums.choose('up').text);
const measure = suggest(study + 'measure close_return(after: 1h)\nmeasure §');
valid(measure.choose('close_return').text);
const bound = header + 'let lookback = {12h | 24h}\n';
const boundUse = suggest(bound + 'find channel_breakout(over: §)');
valid(boundUse.choose('lookback').text);
valid(suggest(bound + 'find §').choose('channel_breakout with lookback').text);
const patternBinding = header + 'let event = "Hammer"\n';
valid(suggest(patternBinding + 'find §').choose('event').text);
assert.ok(!suggest(header + 'let p = 25%\nfind channel_breakout(over: §)').labels.includes('p'));
assert.equal(suggest(study + '-- no §suggestions').items.length, 0);

const vectorReplaced = suggest(study + 'measure close_return(after: §[1h, 4h])');
valid(vectorReplaced.choose('12h').text);
const boundVector = suggest(header + 'let h = 4h\nfind hammer\nmeasure close_return(after: [1h, §])');
valid(boundVector.choose('h').text);
const patternAxis = suggest(header + 'find {"Hammer" | §}');
valid(patternAxis.choose('Doji').text);
const nested = suggest(study + 'where session_tail(§nyse_regular, last: 30m)');
valid(nested.choose('nyse_regular').text);
const afterComma = suggest(study + 'where session_tail(nyse_regular,§last: 30m)');
valid(afterComma.choose('last:').text);
const beforeCall = study + 'where §weekday(nyse_regular) = fri';
for (const option of suggest(beforeCall).items) valid(applyCompletion(beforeCall.replace('§', ''), option).text);
const arbitrary = suggest(header + 'find channel_breakout(over: 90§)');
valid(arbitrary.choose('90m').text);
assert.ok(!arbitrary.labels.includes('90d'));
const refined = suggest(header + 'find hammer§');
valid(refined.choose('measure').text);
const customDuration = suggest(study + 'measure close_return(after: 45m§)');
valid(customDuration.choose('45m').text);
const newColumn = suggest(study + 'measure close_return(after: [1h, 4h])\nmeasure close_return(after: §)');
assert.ok(!newColumn.labels.includes('1h') && !newColumn.labels.includes('4h'));
for (const join of ['and', 'or']) {
  const joinAfter = suggest(header + 'find hammer§');
  assert.ok(joinAfter.labels.includes(join));
  const operand = suggest(header + 'find (hammer ' + join + ' Do§ji)\nwhere weekday(nyse_regular) = fri');
  const chosen = operand.choose('Doji');
  assert.equal(chosen.text, header + 'find (hammer ' + join + ' "Doji")\nwhere weekday(nyse_regular) = fri');
  valid(chosen.text);
  const choices = suggest(header + 'find hammer ' + join + ' §');
  assert.ok(
    choices.labels.includes('exact_g1') && !choices.labels.includes('quiet_range') && !choices.labels.includes('weekday')
  );
}
const selected = 'g1:u:0,1,1,2';
const g1 = suggest(header + 'find exact_g1(§)', { ...env, selectedG1: selected });
valid(g1.choose(JSON.stringify(selected)).text);
const selection = header + 'find "Wick rejection"\nwhere "Quiet range"';
const from = selection.indexOf('"'),
  to = selection.indexOf('\nwhere');
const item = queryCompletions(selection, from, env, to).items.find(x => x.label === 'Hammer');
assert.equal(applyCompletion(selection, item).text, header + 'find "Hammer"\nwhere "Quiet range"');
for (const partial of [
  header + 'find breach_reclaim(',
  study + 'where unregistered(',
  'find ) = ',
  study + 'where ?? = ',
  study + 'where held(((',
  study + 'measure close_return(after: [1h, {',
  study + '-- incomplete\nwhere (weekday(nyse_regular) = fr)',
]) {
  for (let i = 0; i <= partial.length; i++) assert.doesNotThrow(() => queryCompletions(partial, i, env));
}
// An installed callable may own the ASCII name of a subsequently added pattern.
const specimen = bundle.extensions.find(r => r.def.version === 1).artifact;
const custom = { ...specimen, id: 'hammer', title: 'Tester’s custom condition' };
const text = JSON.stringify(custom);
installSaved(bundle, [{ file: 'hammer.json', text, sha256: sha256Hex(new TextEncoder().encode(text)) }]);
valid(suggest(header + 'find §').choose('Hammer').text);
const customQuery = suggest(study + 'where §').choose('hammer').text;
valid(customQuery);
assert.equal(analyze(customQuery, env).candidates[0].plan.wheres[0].def.status, 'extension');
assert.equal(analyze(suggest(header + 'find §').choose('Hammer').text, env).candidates[0].plan.find.def.patternId, 'hammer');
console.log(
  'Passed grammar slots, registry, Japanese names, argument domains, bindings, vectors, sweeps, operators and caret replacement.'
);
