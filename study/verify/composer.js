import assert from 'node:assert/strict';
import '../composer/sync-patterns.mjs';
import { inputBytes } from '../native/inputs.mjs';
import vm from 'node:vm';
import { createHash } from 'node:crypto';
import { attachComposer } from '../composer/bridge.js';
import {
  COMPOSER_REVISION,
  DEFAULT_ANCHOR,
  drawingG1,
  encodeDrawing,
  decodeDrawing,
  pinnedExpression,
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
const relation = { a: { bar: 0, part: 'L' }, b: { bar: 0, part: 'H' } };
for (const color of ['true', 1, 0, '', null, {}, []]) {
  assert.throws(() => decodeDrawing(JSON.stringify({ ...base, pins: [{ ...relation, color }] })), /Invalid drawing pin/);
}
for (const pin of [relation, { ...relation, color: false }, { bar: 0, color: true }]) {
  const packet = { ...base, pins: [pin] };
  assert.deepEqual(decodeDrawing(JSON.stringify(packet)), packet);
  assert.ok(pinnedExpression(packet));
}
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

// Exercise the editor's actual handlers without starting its canvas or market worker.
const source = file('index.html').toString();
const section = (start, end) => source.slice(source.indexOf(start), source.indexOf(end));
let historyKey;
const editor = vm.runInNewContext([
  section('function newBar(', 'function identity()'),
  section('const Ops = {', '/* ================= relations, names and words'),
  'Object.assign(Stage, {' + section('  move(e) {', '  draw() {') + '});',
  section('const Match = {', '// a day as the cards write it'),
  section('const Panes = {', "$('#rnear').addEventListener"),
  section("\naddEventListener('keydown', e => {", '// spacing is how you look'),
  '({ S, snap, hist, Ops, Stage, Match, Panes })',
].join('\n'), {
  MINN: 1,
  MAXN: 20,
  localStorage: { getItem: () => null },
  Stage: { cv: { style: {} }, view: { thi: 100, tlo: 0 }, fit() {}, retire() {}, local: () => ({ x: 0, y: 0 }), hit: () => null },
  App: { redraw() {} },
  Flow: { suspended: () => false },
  refresh() {},
  chain() {},
  requestAnimationFrame: () => 1,
  cancelAnimationFrame() {},
  addEventListener: (type, handler) => { assert.equal(type, 'keydown'); historyKey = handler; },
});
const snapshot = () => JSON.stringify(editor.snap());

// Removing the last bar ends its drag first and preserves separate drag/removal undo steps.
const beforeDrag = snapshot();
editor.Stage.drag = { bar: 1, kind: 'end', moved: true, start: editor.snap() };
editor.S.bars[1].v[3] += 5;
const afterDrag = snapshot();
editor.Ops.remove();
assert.equal(editor.Stage.drag, null, 'removing a bar must finish its active drag');
assert.equal(editor.S.bars.length, 1);
assert.doesNotThrow(() => editor.Stage.move({ altKey: false }));
editor.Ops.undo();
assert.equal(snapshot(), afterDrag);
editor.Ops.undo();
assert.equal(snapshot(), beforeDrag);

// Adding during a press or drag ends it first; pointer-up cannot undo the addition or throw.
for (const moved of [false, true]) {
  const before = snapshot();
  editor.Stage.drag = { bar: 1, kind: 'end', moved, start: editor.snap() };
  if (moved) editor.S.bars[1].v[3] += 5;
  const after = snapshot();
  editor.Ops.add();
  assert.doesNotThrow(() => editor.Stage.up());
  assert.equal(editor.Stage.drag, null, 'adding a bar must finish its active drag');
  assert.equal(editor.S.bars.length, 3);
  editor.Ops.undo();
  assert.equal(snapshot(), after);
  if (moved) {editor.Ops.undo(); assert.equal(snapshot(), before);}
}

// A >70-row result replaces Match.result before its old right-pane buttons disappear.
const presented = [];
editor.Panes.render = (result, side) => presented.push(side);
editor.Match.render = () => {};
editor.Match.id = 1;
editor.Match.onmsg({ type: 'result', id: 1, panes: {
  rows: Array(71).fill({}),
  near: [{ bars: [[42, 65, 20, 52], [52, 75, 15, 45]] }],
} });
const beforeNear = snapshot(), historyLength = editor.hist.past.length;
for (let frame = 0; frame < 2; frame++) {
  assert.ok(editor.Match.presentation);
  editor.Panes.tryNear(0);
  assert.equal(snapshot(), beforeNear, 'pending presentation must ignore old Try it buttons');
  assert.equal(editor.hist.past.length, historyLength);
  if (!frame) editor.Match.presentResult(false); // only the left pane has caught up
}
editor.Match.flushPresentation();
assert.equal(editor.Match.presentation, null);
assert.deepEqual(presented, ['left', 'right']);
editor.Panes.tryNear(0);
assert.notEqual(snapshot(), beforeNear);
assert.equal(editor.hist.past.length, historyLength + 1);

// Native field history is left alone; the same shortcuts still operate on the canvas.
const historyActions = [];
editor.Ops.undo = () => historyActions.push('undo');
editor.Ops.redo = () => historyActions.push('redo');
const shortcuts = [
  { key: 'z', ctrlKey: true, action: 'undo' },
  { key: 'z', metaKey: true, shiftKey: true, action: 'redo' },
  { key: 'y', ctrlKey: true, action: 'redo' },
];
for (const target of [
  { tagName: 'INPUT', id: 'sample-time' }, { tagName: 'INPUT', id: 'nval' },
  { tagName: 'TEXTAREA' }, { tagName: 'SELECT' }, { tagName: 'SPAN', isContentEditable: true },
]) {
  for (const shortcut of shortcuts) {
    historyKey({ ...shortcut, target, preventDefault() { assert.fail('native field undo was intercepted'); } });
  }
}
assert.deepEqual(historyActions, []);
for (const shortcut of shortcuts) {
  let prevented = false;
  historyKey({ ...shortcut, target: { tagName: 'CANVAS' }, preventDefault() { prevented = true; } });
  assert.equal(prevented, true);
  assert.equal(historyActions.at(-1), shortcut.action);
}

// G1-only imports pass through the real snap(), which emits bar properties in editor order.
const controls = new Map([
  'send-named', 'sample-time', 'sample-status', 'send-g1', 'send-pins', 'sample-form',
  'sample-prev', 'sample-next', 'drawing-label', 'ordinal-preview',
].map(id => [id, { addEventListener(type, handler) { this[type] = handler; } }]));
const classes = new Set();
globalThis.document = {
  getElementById: id => controls.get(id),
  body: { classList: { toggle: (name, on) => on ? classes.add(name) : classes.delete(name) } },
};
const importedG1 = 'g1:o:0,1,2,3,u;0,1,2,3,d';
let destination, packet, changed;
const search = '?g1=' + encodeURIComponent(importedG1);
globalThis.location = {
  href: 'https://filang.test/composer/' + search, search, hash: '',
  assign: href => { destination = new URL(href); },
};
globalThis.fetch = async url => {
  const bytes = inputBytes(url.slice(3));
  return { ok: true, arrayBuffer: async () => new Uint8Array(bytes).buffer, json: async () => JSON.parse(bytes.toString()) };
};
const readDrawing = () => ({ ...packet, ...editor.snap() });
await attachComposer({
  apply: drawing => { packet = drawing; editor.Ops.restore(drawing); },
  read: readDrawing,
  g1: () => drawingG1(readDrawing()),
  onChange: callback => { changed = callback; },
});
assert.equal(controls.get('send-g1').disabled, false);
assert.equal(controls.get('drawing-label').textContent, 'G1 drawing · evenly spaced ranks');
assert.ok(classes.has('ordinal-distances'));
controls.get('send-g1').click();
assert.equal(destination.searchParams.get('g1'), importedG1);
assert.equal(decodeDrawing(destination.searchParams.get('drawing'), importedG1).coordinates, 'ordinal');
editor.S.bars[1].v[3] += 5;
changed();
assert.equal(controls.get('drawing-label').textContent, 'Custom drawing');
assert.equal(classes.has('ordinal-distances'), false);
controls.get('send-g1').click();
assert.equal(decodeDrawing(destination.searchParams.get('drawing')).coordinates, undefined);
console.log(
  'Composer verified. All 14,496 OHLC rows agree, the selected candle has 324 exact twins, drawings replay with their pins and settings, and editor interaction regressions pass.',
);
