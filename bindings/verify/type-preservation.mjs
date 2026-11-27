// One set of type and execution cases for the CLI worker, browser and baseline.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { compile } from '../../study/native/compiler.mjs';
import { loadInputs } from '../../study/native/inputs.mjs';
import { startWorker } from '../../study/native/worker.mjs';
import { engineDir } from '../../query/verify/site.mjs';

const vectors = JSON.parse(readFileSync(new URL('../../study/verify/typing-vectors.json', import.meta.url)));
const { bundle } = loadInputs();
const origin = Date.parse('2025-01-01T00:00:00Z');
const interval = 900_000;
const csv = [
  'open_ms,open,high,low,close,base_volume,volume,taker_buy_volume,trade_count',
  ...vectors.bars.map(([slot, o, h, l, c, volume, buys, trades]) =>
    [origin + slot * interval, o, h, l, c, 0, volume, buys, trades].join(',')),
].join('\n') + '\n';
const artifact = (definition) => {
  const text = JSON.stringify(definition);
  return { text, sha256: createHash('sha256').update(text).digest('hex') };
};
const definitions = vectors.definitions.map(artifact);
async function open(directory) {
  const { FilangEngine } = await import(pathToFileURL(resolve(directory, 'index.mjs')));
  const engine = await FilangEngine.create(readFileSync(resolve(directory, 'filang_engine.wasm')));
  engine.loadCsv(csv, interval);
  const cal = bundle.cal;
  engine.setCalendar([[cal.covStart, cal.covEnd], ...cal.sessions.map(s => [s.dayStart, s.close, s.weekday])]
    .map(row => row.join('\t')).join('\n') + '\n');
  for (const { text, sha256 } of definitions) engine.installDefinition(text, sha256);
  return engine;
}
const browser = await open(engineDir());
const baseline = process.env.FILANG_BASELINE_ENGINE_DIR
  ? await open(process.env.FILANG_BASELINE_ENGINE_DIR) : null;
const worker = await startWorker(bundle, csv);
const queryText = (body) => 'on BTCUSDT 15m\n' + body;
const request = (query, extensions = definitions) => worker.evaluate(JSON.stringify({ query, extensions }));
const compileRequest = (query, extensions) => compile(bundle, {
  query, extensions, source: bundle.digest, calendar: bundle.sessionsDigest,
});

function composerReceipts(engine, packet) {
  engine.loadComposerFrame(csv, interval);
  const encoded = engine.encodeDrawing(packet);
  const drawing = engine.decodeDrawing(encoded);
  engine.composerStart(encoded, { timeframes: 1 });
  let result;
  do { result = engine.composerStep(); } while (!result.done);
  const page = engine.composerPositions(interval);
  const packed = engine.composerPositionsPacked(interval);
  assert.ok(page.total > 0, 'the drawn shape occurs on the shared tape');
  return { encoded, drawing, result, page, packed };
}

try {
  for (const body of vectors.valid) {
    const query = queryText(body);
    const expected = browser.study(query);
    assert.deepEqual(await request(query), expected, query);
    if (baseline) {
      assert.deepEqual(expected, baseline.study(query), query);
      assert.deepEqual(browser.describeStudy(query), baseline.describeStudy(query), query);
      for (let candidate = 0; candidate < expected.results.length; candidate++) {
        assert.deepEqual(browser.studyRows(query, { candidate }), baseline.studyRows(query, { candidate }), query);
        for (let slot = 0; slot < 6; slot++) {
          const close = origin + (slot + 1) * interval;
          assert.deepEqual(browser.studyClose(query, close, { candidate }),
            baseline.studyClose(query, close, { candidate }), query);
        }
      }
    }
  }
  for (const [body, message] of vectors.invalid) {
    const query = queryText(body);
    const expected = (err) => err.message.includes(message);
    assert.throws(() => browser.check(query), expected, query);
    assert.throws(() => browser.study(query), expected, query);
    assert.ok((await request(query)).error?.includes(message), query);
  }

  for (const domain of [{ minMs: interval }, { ratioMin: true }, { ratioMaxExclusive: 'true' }]) {
    const bad = structuredClone(vectors.definitions[0]);
    bad.id = 'bad_domain';
    bad.params[0].domain = domain;
    const item = artifact(bad);
    const query = queryText('find hammer');
    const extensions = [...definitions, item];
    assert.throws(() => browser.installDefinition(item.text, item.sha256));
    assert.throws(() => compileRequest(query, extensions), /Ratio domain/);
    assert.ok((await request(query, extensions)).error);
  }
  const ratio = structuredClone(vectors.definitions[0]);
  ratio.id = 'bounded_ratio';
  ratio.params[0].domain = { ratioMin: 0, ratioMax: '75%', ratioMaxExclusive: true };
  ratio.conformance[0].args = { minimum: '25%' };
  const item = artifact(ratio);
  browser.installDefinition(item.text, item.sha256);
  const accepted = queryText('find bounded_ratio(minimum: 50%)');
  const rejected = queryText('find bounded_ratio(minimum: 75%)');
  assert.deepEqual(await worker.evaluate(compileRequest(accepted, [item]).wire), browser.study(accepted));
  assert.throws(() => compileRequest(rejected, [item]), /less than 75%/);
  assert.throws(() => browser.check(rejected), /outside its type or domain/);
  assert.match((await request(rejected, [item])).error, /outside its type or domain/);

  const packet = {
    version: 1, revision: browser.drawingProtocol().plain, oriented: true,
    bars: vectors.bars.slice(0, 2).map(([, o, h, l, c]) => ({ v: [l, o, c, h], d: 'u' })),
    pins: [], skeleton: 0, stretch: 0, limit: 12, next: { dir: 0, measure: 'any', bps: 10, atr: 1 },
  };
  const composer = composerReceipts(browser, packet);
  const shape = queryText('find chained_g1(' + JSON.stringify(composer.drawing.shape.code) + ')');
  assert.equal(browser.study(shape).results[0].anchors.length, composer.page.total);
  if (baseline) assert.deepEqual(composer, composerReceipts(baseline, packet));
  // A failed request, like a successful one, leaves no request-local definitions installed.
  assert.match((await request(queryText('find measured_shape()'), [])).error, /measured_shape/);
  assert.deepEqual(await request(queryText('find measured_shape()')), browser.study(queryText('find measured_shape()')));
} finally {
  worker.close();
  browser.close();
  baseline?.close();
}
console.log(`Type contract: ${vectors.valid.length} matching studies, ${vectors.invalid.length} shared refusals and a Query–Composer handoff${baseline ? ', with exact baseline results, receipts and explanations' : ''}.`);
