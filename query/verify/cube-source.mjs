// The cube as the bench's bar source, checked without the cube: a stand-in for Cube's bridge serves the pinned
// recording in the bridge's own protocol (/cube/pack, /cube/bars with MSCB blocks, its limits and refusals), and
// what the Query server builds from it must be the pinned recording again, bar for bar, window by window.
// Run from the repository root, after study/prepare_recording.py and bindings/build.py: node query/verify/cube-source.mjs
// To see the bench on a cube without one, keep the stand-in up and point the server at it:
//   node query/verify/cube-source.mjs --serve 8799   then   CUBE_URL=http://127.0.0.1:8799 node query/serve.mjs
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { spawn } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { gzipSync } from 'node:zlib';
import { createHash } from 'node:crypto';
import { cubeSource, CubeError, decodeMscb, windowRange, WINDOWS, MAX_COLUMNS } from '../cube.mjs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { readRecording } from '../shared/recording.js';
import { ROOT, engineDir, recordingFile } from './site.mjs';

const T0 = 1609459200; const BASE = 56.25; const N = 4; const STEP = 2 ** N;
const pinnedCsv = await readFile(recordingFile(), 'utf8');
const pinned = JSON.parse(await readFile(join(ROOT, 'study/data-provenance.json'), 'utf8'));
// The shared engine, as the bench loads it in the page.
const { FilangEngine } = await import(pathToFileURL(join(engineDir(), 'index.mjs')).href);
const engine = await FilangEngine.create(await readFile(join(engineDir(), 'filang_engine.wasm')));
// The pinned file writes a price as its source did (96733.0); the cube's bars are written in cents (96733.00).
// The same bar, so the pinned rows are compared in the second form. The pinned file has no counters, so the stand-in
// bridge makes them up from each bar's BTC volume and close: USDT traded, a taker-buy share that cycles from 30% to
// 70% (so every fifth bar is in exact balance), and a trade count that cycles too. A fixture, not market data.
const counters = (v, col) => { const traded = v[4] * v[3]; return [traded, traded * [0.3, 0.4, 0.5, 0.6, 0.7][col % 5], 10 + (col % 7) * 5]; };
const rows = pinnedCsv.trimEnd().split('\n').slice(1).map((text) => {
  const f = text.split(','); const v = f.slice(1).map(Number); const col = (Number(f[0]) / 1000 - T0) / (BASE * STEP);
  return { col, line: [f[0], ...f.slice(1, 5).map((x) => Number(x).toFixed(2)), f[5], ...counters(v, col).map(String)].join(','), v };
});
const HEADER = 'open_ms,open,high,low,close,base_volume,volume,taker_buy_volume,trade_count\n';
const pinnedInCents = HEADER + rows.map((r) => r.line).join('\n') + '\n';
const lastCol = rows[rows.length - 1].col;

// ---------------------------------------------------------------- the stand-in bridge

const bridge = { token: 'pack-1', cutoff: (lastCol + 1) * STEP + 5.37, canonical: null, measuredEnd: Infinity, drop: new Set(), spoil: null, overbought: null, halfTrade: null, changeOnce: false, asks: [] };
function mscb(n, col0, col1, bars) {
  const head = Buffer.alloc(32); head.write('MSCB', 0, 'latin1'); head.writeUInt8(n, 4); head.writeUInt8(20, 5);
  head.writeUInt32LE(col0, 8); head.writeUInt32LE(col1, 12); head.writeUInt32LE(bars.length, 16);
  const body = Buffer.alloc(bars.length * 68);
  // open, high, low, close, USDT volume, taker-buy volume, BTC volume, trades, then the column
  bars.forEach((b, i) => {
    const [o, h, l, c, vol] = b.v; const [traded, takerBuy, trades] = counters(b.v, b.col);
    const fields = [bridge.spoil === b.col ? o + 0.004 : o, h, l, c, traded, bridge.overbought === b.col ? traded * 2 : takerBuy, vol, bridge.halfTrade === b.col ? 10.5 : trades];
    fields.forEach((x, k) => body.writeDoubleLE(x, (k * bars.length + i) * 8));
    body.writeUInt32LE(b.col, bars.length * 64 + i * 4);
  });
  return gzipSync(Buffer.concat([head, body])).toString('base64');
}
const fake = createServer((req, res) => {
  const url = new URL(req.url, 'http://127.0.0.1'); const q = url.searchParams;
  const json = (body, status = 200) => { res.writeHead(status, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(body)); };
  bridge.asks.push(url.pathname + url.search);
  if (q.get('proto') !== '2') return json({ error: 'the explorer was updated; reload the page to see the latest data', reload: true }, 409);
  if (url.pathname === '/cube/pack') {
    if (q.get('since') === bridge.token) return json({ status: 'current', state_token: bridge.token });
    return json({ status: 'pack', pack: { t0: T0, base_seconds: BASE, cutoffBase: bridge.cutoff, canonical_through: bridge.canonical, state_token: bridge.token, blocks: {} } });
  }
  if (url.pathname === '/cube/bars') {
    const n = Number(q.get('n')); const b0 = Number(q.get('b0')); const b1 = Number(q.get('b1')); const step = 2 ** n;
    if (bridge.changeOnce) { bridge.changeOnce = false; bridge.token = 'pack-2'; }
    if (q.get('pack') !== bridge.token) return json({ error: 'cube_changed', detail: "the page's pack is no longer held by the server" }, 409);
    if (!(b0 >= 0 && b0 < b1 && b0 % step === 0)) return json({ error: "b0 must be a bar's edge and b1 after it" }, 400);
    if (Math.ceil(b1 / step) - b0 / step > MAX_COLUMNS) return json({ error: `more than ${MAX_COLUMNS} bars` }, 400);
    if (b1 > Math.ceil(bridge.cutoff)) return json({ error: "b1 is after the pack's cutoff" }, 400);
    const end = Math.max(b0, Math.min(b1, Math.floor(bridge.cutoff), bridge.measuredEnd));
    const col0 = b0 / step; const col1 = Math.max(col0, Math.ceil(end / step));
    // As the bridge does, it reads bars up to the pack's last complete column and says separately where the cube's
    // measures end: a bar past `end` can be in the answer, and the one holding `end` is partial.
    const read = Math.ceil(Math.min(b1, Math.floor(bridge.cutoff)) / step);
    const bars = n === N ? rows.filter((r) => r.col >= col0 && r.col < read && !bridge.drop.has(r.col)) : [];
    return json({ n, b0, b1, end, state_token: bridge.token, canonical_through: bridge.canonical, bars: { n, col0, col1, count: bars.length, layout: 'MSCB', encoding: 'gzip+base64', gzip_base64: mscb(n, col0, col1, bars) } });
  }
  return json({ error: 'not_found' }, 404);
});
const standing = process.argv.indexOf('--serve');
await new Promise((ok) => fake.listen(standing < 0 ? 0 : Number(process.argv[standing + 1] || 8799), '127.0.0.1', ok));
const CUBE_URL = `http://127.0.0.1:${fake.address().port}`;
if (standing >= 0) { console.log(`Stand-in cube bridge on ${CUBE_URL} · the pinned recording as the cube's bars`); await new Promise(() => {}); }
const fresh = () => cubeSource({ url: CUBE_URL, packMaxAgeMs: 0 });
const sha = (text) => createHash('sha256').update(text).digest('hex');
let checks = 0;
const ok = (name) => { checks++; console.log(`ok  ${name}`); };

// ---------------------------------------------------------------- the client

{
  bridge.asks.length = 0;
  const all = await fresh().bars('all');
  assert.equal(all.csv === pinnedInCents, true, 'all history must be the pinned recording, bar for bar');
  assert.equal(all.provenance.csv_sha256, sha(all.csv));
  assert.equal(all.provenance.row_count, pinned.row_count);
  assert.equal(all.provenance.interval_ms, 900000);
  assert.equal(all.provenance.source, 'cube');
  assert.equal(all.provenance.from, '2021-01-01T00:00:00.000Z');
  const asks = bridge.asks.filter((a) => a.startsWith('/cube/bars'));
  assert.ok(asks.length > 10, 'a long window is read in several requests');
  for (const a of asks) { const q = new URL(a, CUBE_URL).searchParams; assert.ok((Number(q.get('b1')) - Number(q.get('b0'))) / STEP <= MAX_COLUMNS); }
  ok(`all history is the pinned recording bar for bar, in ${asks.length} requests of at most ${MAX_COLUMNS} bars`);

  // The charts read it as they read the pinned file: the same slots, present or missing, with the same cents.
  const built = readRecording(all.csv, all.provenance); const own = readRecording(pinnedCsv, pinned);
  assert.equal(built.n, own.n); assert.equal(built.t0, own.t0);
  for (const k of ['O', 'H', 'L', 'C', 'present']) assert.deepEqual(built[k], own[k], `${k} differs from the pinned recording`);
  // And the engine takes it as it takes the pinned file, and answers the same.
  const questions = ['chained_g1', 'exact_g1'].map(op =>
    `on BTCUSDT 15m\nfind ${op}("g1:o:0,1,3,4,u;2,3,5,6,u")`);
  assert.equal(engine.loadCsv(all.csv, built.barMs).slots, built.n);
  assert.deepEqual(engine.studyCounts(questions), [1463, 772].map(count => ({count, error: null})));
  assert.equal(engine.describeStudy(questions[0]).manifest.pins.source.csv_sha256, all.provenance.csv_sha256);
  ok('the engine verifies its digest and counts 1,463 and 772 on it, as on the pinned file');

  // The counters arrive as the floats the bridge sent, and the dimensions read from them.
  assert.equal(built.hasCounters, true);
  const volume = built.dimension('volume'); const trades = built.dimension('trades'); const delta = built.dimension('delta');
  rows.forEach((r) => {
    const i = (Number(r.line.split(',')[0]) - built.t0) / built.barMs;
    const [traded, takerBuy, count] = counters(r.v, r.col);
    assert.equal(volume[i], traded);
    assert.equal(trades[i], count);
    assert.equal(delta[i], 2 * takerBuy - traded);
  });
  const count = (text) => {
    const answer = engine.studyCounts([text])[0];
    assert.equal(answer.error, null, text);
    return answer.count;
  };
  assert.equal(count('on BTCUSDT 15m\nfind candle_relation(delta(), is: equal, right: 0)'), rows.filter((r) => r.col % 5 === 2).length);
  assert.equal(count('on BTCUSDT 15m\nfind candle_relation(delta(), is: above, right: 0)'), rows.filter((r) => r.col % 5 > 2).length);
  const rising = count('on BTCUSDT 15m\nfind candle_relation(volume(), is: above, right: volume(bars_ago: 1))');
  assert.equal(rising, rows.filter((r, k) => k && r.col === rows[k - 1].col + 1 && counters(r.v, r.col)[0] > counters(rows[k - 1].v, rows[k - 1].col)[0]).length);
  assert.equal(count('on BTCUSDT 15m\nfind chained_g1("g1:o:0,1,3,4,u;2,3,5,6,u|volume:0,1")') <= 1463, true);
  ok(`the counters read back as the floats the bridge sent, and volume rose on ${rising.toLocaleString('en-US')} bars as it does in the bridge's own numbers`);
}

{
  const tail = (k) => HEADER + rows.slice(-k).map((r) => r.line).join('\n') + '\n';
  const source = fresh();
  for (const [key, bars] of [['15m', 1], ['30m', 2], ['1h', 4], ['4h', 16], ['12h', 48], ['24h', 96], ['7d', 672], ['30d', 2880], ['45d', 4320], ['90d', 8640]]) {
    const got = await source.bars(key);
    assert.equal(got.csv === tail(bars), true, `${key} is the last ${bars} bars`);
    assert.equal(got.provenance.window, key);
  }
  ok('each rolling window is exactly its last bars, ending at the latest complete bar');
  // The recording runs from 2025-01-01 to 2025-05-31: "this year" is all of it, "last year" has no bars.
  assert.equal((await source.bars('ytd')).csv === pinnedInCents, true);
  assert.equal((await source.bars('ytd')).provenance.window_name, '2025');
  await assert.rejects(source.bars('lastyear'), /holds no bars/);
  const may = await source.bars('since:2025-05-01');
  assert.equal(may.csv.split('\n')[1].split(',')[0], String(Date.UTC(2025, 4, 1)));
  assert.equal(may.provenance.window_name, 'Since 2025-05-01');
  await assert.rejects(source.bars('fortnight'), (e) => e instanceof CubeError && /unknown window/.test(e.message));
  await assert.rejects(source.bars('since:2025-02-30'), /unknown window/);
  await assert.rejects(source.bars('7d', '5m'), /unknown interval/);
  ok('this year, last year, since a day, and what is refused');
  assert.deepEqual(WINDOWS.map((w) => w.key), ['15m', '30m', '1h', '4h', '12h', '24h', '7d', '30d', '45d', '90d', '180d', '270d', '1y', 'ytd', 'lastyear', 'all']);
  ok("the windows are Cube's, in Cube's order");
}

{
  // A bar is whole only once the cube's data has passed its end: a cutoff inside a bar leaves that bar out.
  const range = windowRange('24h', N, { t0: T0, baseSeconds: BASE, cutoff: 1000 * STEP + 15.9 });
  assert.deepEqual([range.b0, range.b1], [(1000 - 96) * STEP, 1000 * STEP]);
  // Last year ends where the year did, wherever the data ends.
  const year = windowRange('lastyear', N, { t0: T0, baseSeconds: BASE, cutoff: (Date.UTC(2026, 10, 22) / 1000 - T0) / BASE });
  assert.deepEqual([range.b1 % STEP, year.b0, year.b1], [0, (Date.UTC(2025, 0, 1) / 1000 - T0) / BASE, (Date.UTC(2026, 0, 1) / 1000 - T0) / BASE]);
  ok('a window ends on a bar edge at or before the cutoff; last year is the calendar year');
}

{
  // The cube moves on while a window is read: the bridge refuses the old pack once, and the read starts again.
  const source = fresh();
  await source.state(); bridge.changeOnce = true;
  assert.equal((await source.bars('7d')).provenance.state_token, 'pack-2');
  ok('a pack that changes mid-read is read again on the new pack');

  // Where the cube's measures stop short of the window, the recording stops there too and says so.
  bridge.measuredEnd = (lastCol - 9) * STEP + 7;        // inside a bar: that bar is partial and is left out
  const short = await fresh().bars('24h');
  assert.equal(short.provenance.row_count, 96 - 10);
  assert.equal(Date.parse(short.provenance.through), (T0 + (lastCol - 9) * STEP * BASE) * 1000);
  bridge.measuredEnd = Infinity;
  ok('a window ends at the last bar the cube has measured whole');

  // A bar the cube has no trades for is a missing row, not an invented one.
  bridge.drop = new Set([lastCol - 3, lastCol - 4]);
  const gap = await fresh().bars('24h');
  assert.equal(gap.provenance.row_count, 94);
  const holed = readRecording(gap.csv, gap.provenance);
  assert.equal(holed.n, 96); assert.equal(holed.presentCount, 94);
  assert.equal(engine.loadCsv(gap.csv, holed.barMs).slots, 96);
  bridge.drop = new Set();
  ok('a column without trades is a gap the engine sees as a gap');

  // A price that is not whole cents is refused, never rounded.
  bridge.spoil = lastCol - 1;
  await assert.rejects(fresh().bars('24h'), /not a whole number of cents/);
  bridge.spoil = null;
  ok('a price off the cent grid is refused');
  // counters that cannot be right are refused too, as the engine would refuse them
  bridge.overbought = lastCol - 1;
  await assert.rejects(fresh().bars('1h'), (e) => e instanceof CubeError && /taker-buy volume/.test(e.message));
  bridge.overbought = null; bridge.halfTrade = lastCol - 1;
  await assert.rejects(fresh().bars('1h'), (e) => e instanceof CubeError && /trade count/.test(e.message));
  bridge.halfTrade = null;
  ok('a bar whose taker-buy amount exceeds its volume, or whose trade count is not whole, is refused');

  // Bars past the canonical mark are counted as provisional.
  bridge.canonical = new Date((T0 + (lastCol + 1 - 6) * STEP * BASE) * 1000).toISOString();
  assert.equal((await fresh().bars('24h')).provenance.provisional_rows, 6);
  bridge.canonical = null;
  ok('bars after the canonical mark are counted as provisional');

  assert.equal(decodeMscb(mscb(N, 0, 0, [])).count, 0);
  assert.throws(() => decodeMscb(gzipSync(Buffer.from('nope')).toString('base64')), /not an MSCB block/);
  ok('an empty block and a block that is not one');
}

// ---------------------------------------------------------------- the server

const children = new Set();
process.on('exit', () => { for (const child of children) child.kill('SIGKILL'); });
async function serve(env) {
  const child = spawn(process.execPath, [join(ROOT, 'query/serve.mjs')], { env: { ...process.env, HOST: '127.0.0.1', PORT: '0', FILANG_QUERY_ENGINE_DIR: engineDir(), ...env }, stdio: ['ignore', 'pipe', 'inherit'] });
  children.add(child); child.once('exit', () => children.delete(child));
  const line = await new Promise((resolve, reject) => { child.stdout.once('data', (d) => resolve(String(d))); child.once('exit', (c) => reject(Error(`server exited ${c}`))); });
  const port = /http:\/\/127\.0\.0\.1:(\d+)\//.exec(line)?.[1];
  assert.ok(port, `the server did not say where it listens: ${line}`);
  return { line, get: (path) => fetch(`http://127.0.0.1:${port}${path}`), stop: () => new Promise((done) => { child.once('exit', done); child.kill('SIGTERM'); }) };
}
{
  const withCube = await serve({ CUBE_URL });
  assert.match(withCube.line, /bars cube at http/);
  const offered = await (await withCube.get('/bars/windows')).json();
  assert.equal(offered.cube, true); assert.equal(offered.default, '180d'); assert.equal(offered.windows.length, WINDOWS.length);
  const answer = await withCube.get('/bars?w=7d');
  assert.equal(answer.status, 200); assert.equal(answer.headers.get('cache-control'), 'no-store');
  const body = await answer.json();
  assert.equal(body.provenance.row_count, 672); assert.equal(sha(body.csv), body.provenance.csv_sha256);
  assert.equal((await withCube.get('/bars?w=fortnight')).status, 400);
  assert.equal((await withCube.get('/bars?w=lastyear')).status, 502);
  assert.deepEqual(await (await withCube.get('/healthz')).json(), { service: 'filang-query', ok: true });
  // The browser gets the pinned recording, its provenance and the engine's package; never the server's own module,
  // and nothing of the engine the bench used to carry.
  assert.equal(sha(await (await withCube.get('/recording/bars.csv')).text()), pinned.csv_sha256);
  assert.deepEqual(await (await withCube.get('/recording/provenance.json')).json(), pinned);
  for (const asset of ['index.mjs', 'worker-client.mjs', 'worker.mjs', 'filang_engine.wasm']) assert.equal((await withCube.get('/engine/' + asset)).status, 200, asset);
  assert.equal((await withCube.get('/engine/filang_engine.wasm')).headers.get('content-type'), 'application/wasm');
  for (const gone of ['/cube.mjs', '/study/src/engine.js', '/study/recorded-bars.csv', '/study/composer/drawing.js']) assert.equal((await withCube.get(gone)).status, 404, gone);
  await withCube.stop();
  ok('the server offers the windows, serves one, and maps refusals to 400 and 502');

  const without = await serve({ CUBE_URL: '' });
  assert.match(without.line, /bars pinned recording/);
  assert.deepEqual(await (await without.get('/bars/windows')).json(), { cube: false, default: '180d', intervals: ['15m', '30m', '1h', '2h', '4h'], windows: [] });
  assert.equal((await without.get('/bars?w=7d')).status, 404);
  await without.stop();
  ok('without a cube the server offers the pinned recording only');

  // The bench answers nothing without the engine, so a server that has no engine package is not healthy.
  const bare = await serve({ CUBE_URL: '', FILANG_QUERY_ENGINE_DIR: '/nonexistent' });
  assert.match(bare.line, /MISSING/);
  assert.deepEqual([(await bare.get('/healthz')).status, (await bare.get('/engine/index.mjs')).status], [503, 404]);
  await bare.stop();
  ok('a server without the engine package fails its health check');

  // A bridge that is down is a 502 with its reason, and the health answer does not depend on it.
  const down = await serve({ CUBE_URL: 'http://127.0.0.1:9' });
  const refused = await down.get('/bars?w=7d');
  assert.equal(refused.status, 502); assert.match((await refused.json()).error, /did not answer/);
  assert.equal((await down.get('/healthz')).status, 200);
  await down.stop();
  ok('a bridge that is down is reported, and the bench stays up');
}

fake.close();
engine.close();
console.log(`${checks} checks passed`);
