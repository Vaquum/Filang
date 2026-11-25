// The NYSE sessions of the bench's cube windows, checked without field-data-api: a stand-in serves `nyse_sessions`
// in the service's own protocol (/v1/snapshots/latest, then /v1/data/nyse_sessions pinned to that publication and
// paged), and the table the Query server builds must be those sessions rewritten for the engine and nothing more,
// be refused when a record does not read as a session in coverage, and be what the engine answers session
// conditions with, pinned in the run's manifest.
// The stand-in's sessions are invented in the service's shape, for twelve days in 2030 that cross New York's change
// to summer time: a fixture of the rewriting, never a calendar. The bench's sessions are only ever field-data-api's.
// Run from the repository root, after study/prepare_recording.py and bindings/build.py: node query/verify/calendar.mjs
// To see the table a running service gives:  node query/verify/calendar.mjs --print http://127.0.0.1:8491
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { join } from 'node:path';
import { fieldDataCalendar, nyseTable, CalendarError } from '../calendar.mjs';
import { ROOT, engineDir, install } from './site.mjs';

const sha = (text) => createHash('sha256').update(text).digest('hex');
const ok = (what) => console.log(`ok  ${what}`);

if (process.argv[2] === '--print') {
  const answer = await fieldDataCalendar({ url: process.argv[3], token: process.env.FIELD_DATA_API_TOKEN || null }).nyse();
  console.log(JSON.stringify({ table: answer.table, provenance: answer.provenance }, null, 1));
  process.stdout.write(answer.tsv);
  process.exit(0);
}

// ---------------------------------------------------------------- the stand-in's sessions

const z = (iso) => Date.parse(iso);
// Wednesday 6 March is not a session and Friday 8 March closes early; New York moves to summer time on Sunday 10 March.
const SESSIONS = [
  ['2030-03-04', 'mon', '14:30', '21:00'], ['2030-03-05', 'tue', '14:30', '21:00'], ['2030-03-07', 'thu', '14:30', '21:00'],
  ['2030-03-08', 'fri', '14:30', '18:00', 'early_close'], ['2030-03-11', 'mon', '13:30', '20:00'], ['2030-03-12', 'tue', '13:30', '20:00'],
  ['2030-03-13', 'wed', '13:30', '20:00'], ['2030-03-14', 'thu', '13:30', '20:00'], ['2030-03-15', 'fri', '13:30', '20:00'],
].map(([date, weekday, open, close, kind = 'regular']) => ({ date, weekday, open_at: `${date}T${open}:00Z`, close_at: `${date}T${close}:00Z`, kind,
  ...(kind === 'early_close' ? { provenance: { url: 'https://example.invalid/fixture' } } : {}) }));
const REVISION = 'c'.repeat(64);
const META = { exchange: 'XNYS', timezone: 'America/New_York', coverage: { start: '2030-03-04', end: '2030-03-16' }, revision_id: REVISION,
  regular_hours: { open: '09:30', close: '16:00' }, closures: [{ date: '2030-03-06', reason: 'fixture', provenance: { url: 'https://example.invalid/fixture' } }] };

// ---------------------------------------------------------------- the rewriting

const built = nyseTable(SESSIONS, META);
const lines = built.tsv.trimEnd().split('\n');
assert.equal(lines[0], `${z('2030-03-04T05:00:00Z')}\t${z('2030-03-16T04:00:00Z')}`);
assert.deepEqual(lines.slice(1), SESSIONS.map((s) => `${z(`${s.date}T${s.date < '2030-03-10' ? '05' : '04'}:00:00Z`)}\t${z(s.close_at)}\t${s.weekday}`));
assert.equal(built.sessions, 9); assert.equal(built.earlyCloses, 1); assert.equal(built.closures, 1);
assert.equal(built.tsvSha256, sha(built.tsv));
ok('each published session becomes one row at its New York midnight with its own close, in either offset; nothing is added');

const refuses = (records, meta, pattern, what) => { assert.throws(() => nyseTable(records, meta), (e) => e instanceof CalendarError && pattern.test(e.message), what); };
const at = (i, over) => SESSIONS.map((s, j) => (j === i ? { ...s, ...over } : s));
refuses(SESSIONS, { ...META, exchange: 'XLON' }, /not XNYS/, 'another exchange');
refuses(SESSIONS, { ...META, coverage: null }, /declares no coverage/, 'no coverage');
refuses(SESSIONS, { ...META, coverage: { start: '2030-03-16', end: '2030-03-04' } }, /declares no coverage/, 'a reversed coverage');
refuses(at(8, { date: '2030-03-18', weekday: 'mon', open_at: '2030-03-18T13:30:00Z', close_at: '2030-03-18T20:00:00Z' }), META, /outside the declared coverage/, 'a session outside coverage');
refuses(at(1, { date: '2030-03-04' }), META, /one per date in order/, 'two sessions on one date');
refuses(at(0, { weekday: 'tue' }), META, /names weekday tue/, 'a weekday that is not the date’s');
refuses(at(2, { date: '2030-03-09', weekday: 'sat', open_at: '2030-03-09T14:30:00Z', close_at: '2030-03-09T21:00:00Z' }), META, /names weekday sat/, 'a Saturday');
refuses(at(0, { close_at: '2030-03-05T06:00:00Z' }), META, /outside its New York day/, 'a close on the next New York day');
refuses(at(0, { open_at: '2030-03-04T21:00:00Z' }), META, /outside its New York day/, 'an open after the close');
refuses(at(0, { close_at: '2030-03-04 21:00' }), META, /outside its New York day/, 'a close with no zone');
refuses(at(0, { kind: 'half_day' }), META, /of kind half_day/, 'an unknown kind');
ok('records that do not read as one session in the declared coverage are refused, not repaired');

// ---------------------------------------------------------------- the service's protocol

const PIN = 'a'.repeat(64); const DATASET = 'b'.repeat(64);
const service = { pin: PIN, dataset: DATASET, status: 'ok', pageSize: 4, records: SESSIONS, meta: META, projection: 'market_sessions/1', asks: [], spoil: null };
const standIn = createServer((req, res) => {
  const url = new URL(req.url, 'http://x'); service.asks.push(url.pathname + url.search);
  const send = (status, body) => { res.writeHead(status, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(body)); };
  if (url.pathname === '/v1/snapshots/latest') {
    return send(200, { snapshot_id: service.pin, published_at: '2030-03-01T00:00:00.000Z', calendar: null,
      datasets: service.status === 'absent' ? {} : { nyse_sessions: { dataset_id: service.dataset, status: service.status } } });
  }
  if (url.pathname !== '/v1/data/nyse_sessions') return send(404, { error: 'not_found' });
  if (url.searchParams.get('snapshot_id') !== service.pin) return send(400, { error: 'unknown_snapshot' });
  const offset = Number(url.searchParams.get('offset') || 0); const limit = Math.min(Number(url.searchParams.get('limit')), service.pageSize);
  const next = offset + limit < service.records.length ? offset + limit : null;
  const page = { snapshot_id: service.pin, source: 'nyse_sessions', dataset_id: service.dataset, page: { offset, limit, next_offset: next, total: service.records.length },
    data: { projection_version: service.projection, records: service.records.slice(offset, offset + limit), meta: service.meta } };
  if (service.spoil && offset > 0) service.spoil(page);
  send(200, page);
});
await new Promise((done) => standIn.listen(0, '127.0.0.1', done));
const URL_ = `http://127.0.0.1:${standIn.address().port}`;

let clock = 0;
const reader = fieldDataCalendar({ url: URL_, now: () => clock, maxAgeMs: 1000 });
const first = await reader.nyse();
assert.equal(first.table, `field-data-api.nyse_sessions.${REVISION.slice(0, 16)}`);
assert.equal(first.tsv, built.tsv);
assert.deepEqual(Object.keys(first), ['table', 'provenance', 'tsv'], 'the text comes last, after the id and provenance');
assert.equal(first.provenance.snapshot_id, PIN); assert.equal(first.provenance.dataset_id, DATASET); assert.equal(first.provenance.revision_id, REVISION);
assert.deepEqual(first.provenance.coverage, { start: '2030-03-04', end: '2030-03-16' }); assert.equal(first.provenance.tsv_sha256, sha(first.tsv));
const pages = service.asks.filter((a) => a.startsWith('/v1/data/nyse_sessions'));
assert.equal(pages.length, 3, 'nine sessions in pages of four');
for (const a of pages) assert.match(a, new RegExp(`snapshot_id=${PIN}`));
ok('one publication is pinned and every page of nyse_sessions is read under it');

service.asks.length = 0; clock = 500;
assert.equal(await reader.nyse(), first); assert.equal(service.asks.length, 0);
clock = 2000; service.pin = 'd'.repeat(64);
assert.equal(await reader.nyse(), first); assert.deepEqual(service.asks, ['/v1/snapshots/latest']);
ok('the table is kept while the published sessions are the same dataset, and the service is asked again only after a while');

service.status = 'error'; clock = 4000;
assert.equal(await reader.nyse(), first, 'a table already read outlasts the service failing');
service.status = 'ok';
ok('a table already read is kept when the service later cannot answer');

const fresh = () => fieldDataCalendar({ url: URL_ });
const failsWith = async (pattern, what) => { await assert.rejects(fresh().nyse(), (e) => e instanceof CalendarError && pattern.test(e.message), what); };
service.spoil = (page) => { page.snapshot_id = 'e'.repeat(64); };
await failsWith(/another publication/, 'a page from another publication');
service.spoil = (page) => { page.dataset_id = 'f'.repeat(64); };
await failsWith(/another publication/, 'a page of another dataset');
service.spoil = (page) => { page.page.next_offset = page.page.offset; page.page.total = 99; };
await failsWith(/do not advance/, 'a cursor that stands still');
service.spoil = null; service.projection = 'calendar/1';
await failsWith(/not market_sessions\/1/, 'another projection');
service.projection = 'market_sessions/1'; service.meta = { ...META, revision_id: 'x' };
await failsWith(/no content revision/, 'no content revision');
service.meta = META; service.status = 'error';
await failsWith(/publishes no nyse_sessions \(status error\)/, 'an unusable dataset');
service.status = 'absent';
await failsWith(/publishes no nyse_sessions \(status none\)/, 'a service without the dataset');
service.status = 'ok';
await assert.rejects(fieldDataCalendar({ url: 'http://127.0.0.1:9' }).nyse(), /did not answer/);
assert.throws(() => fieldDataCalendar({ url: 'http://user:pw@127.0.0.1:8491' }), /without credentials/);
ok('pages of another publication, stalled cursors, other projections, a missing dataset and a silent service are refused');

// ---------------------------------------------------------------- the server

const children = new Set();
async function serve(env) {
  const child = spawn(process.execPath, [join(ROOT, 'query/serve.mjs')], { env: { ...process.env, HOST: '127.0.0.1', PORT: '0', FILANG_QUERY_ENGINE_DIR: engineDir(), CUBE_URL: '', FIELD_DATA_URL: '', ...env }, stdio: ['ignore', 'pipe', 'inherit'] });
  children.add(child); child.once('exit', () => children.delete(child));
  const line = await new Promise((resolve, reject) => { child.stdout.once('data', (d) => resolve(String(d))); child.once('exit', (c) => reject(Error(`server exited ${c}`))); });
  const port = /http:\/\/127\.0\.0\.1:(\d+)\//.exec(line)?.[1];
  return { line, get: (path) => fetch(`http://127.0.0.1:${port}${path}`), stop: () => new Promise((done) => { child.once('exit', done); child.kill('SIGTERM'); }) };
}
try {
  const withService = await serve({ FIELD_DATA_URL: URL_ });
  assert.match(withService.line, /calendar field-data-api at http/);
  const answer = await withService.get('/calendar/nyse');
  assert.equal(answer.status, 200); assert.equal(answer.headers.get('cache-control'), 'no-store');
  const body = await answer.json();
  assert.equal(body.table, first.table); assert.equal(body.tsv, built.tsv); assert.equal(body.provenance.source, 'field-data-api');
  assert.equal((await withService.get('/calendar.mjs')).status, 404, 'the server’s own module is never served');
  await withService.stop();
  service.status = 'error';
  const failing = await serve({ FIELD_DATA_URL: URL_ });
  const refused = await failing.get('/calendar/nyse');
  assert.equal(refused.status, 502); assert.match((await refused.json()).error, /publishes no nyse_sessions/);
  await failing.stop();
  service.status = 'ok';
  const without = await serve({});
  assert.match(without.line, /calendar pinned table/);
  assert.equal((await without.get('/calendar/nyse')).status, 404);
  await without.stop();
} finally { for (const c of children) c.kill('SIGKILL'); }
ok('the server hands out the table it built, says why when it cannot, and has none without FIELD_DATA_URL');

// ---------------------------------------------------------------- the bench and the engine

// Bars for the fixture days, every 15 minutes from 00:00 UTC on 4 March to 12:00 UTC on 16 March 2030, all at one
// price: a fixture of close times, not market data.
const BAR = 900_000; const T0 = z('2030-03-04T00:00:00Z'); const T1 = z('2030-03-16T12:00:00Z');
const rows = ['open_ms,open,high,low,close,volume'];
for (let t = T0; t < T1; t += BAR) rows.push(`${t},100.00,100.00,100.00,100.00,1.0`);
const fixtureCsv = rows.join('\n') + '\n';
const fixtureProvenance = { instrument: 'Binance BTCUSDT spot', interval_ms: BAR, source: 'cube', window: '30d', window_name: 'Last 30 days', csv_sha256: sha(fixtureCsv), row_count: rows.length - 1 };

await install();
let calendarAnswer = () => Response.json({ table: first.table, tsv: first.tsv, provenance: first.provenance });
const site = globalThis.fetch;
globalThis.fetch = async (input, init) => {
  const url = String(input);
  if (url.startsWith('/bars?w=')) return Response.json({ csv: fixtureCsv, provenance: fixtureProvenance });
  if (url === '/calendar/nyse') return calendarAnswer();
  return site(input, init);
};
const bench = await import('/shared/filang.js');
const QUERY = (where) => `${bench.HEAD}\nfind ${bench.ANY_CLOSE}\nwhere ${where}`;
const stats = (where) => bench.engine.studyRows(QUERY(where), { limit: 1 }).clause_stats[0];

const window = await bench.load('30d');
assert.equal(window.calendar.pinned, false); assert.equal(window.calendar.table, first.table);
const pins = bench.engine.describeStudy(QUERY('weekday(nyse_regular) = fri')).manifest.pins.calendars;
assert.deepEqual(pins, [{ id: first.table, sha256: sha(first.tsv) }]);
ok('a cube window is asked with field-data-api’s table, and the manifest pins its id and digest');

// What the table says, worked out here from the fixture's own days rather than read back from the engine.
const from = z('2030-03-04T05:00:00Z'); const to = z('2030-03-16T04:00:00Z');
const newYorkDate = (t) => new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York' }).format(t);
const closes = []; for (let t = T0 + BAR; t <= T1; t += BAR) closes.push(t);
const inside = closes.filter((t) => from <= t && t < to);
const fridays = inside.filter((t) => ['2030-03-08', '2030-03-15'].includes(newYorkDate(t))).length;
assert.deepEqual(stats('weekday(nyse_regular) = fri'), [fridays, inside.length - fridays, closes.length - inside.length]);
const sessionCloses = lines.slice(1).map((l) => Number(l.split('\t')[1]));
const tail = closes.filter((t) => sessionCloses.some((c) => c - 3_600_000 < t && t <= c)).length;
const tailKnown = closes.filter((t) => sessionCloses.some((c) => c - 3_600_000 < t && t <= c) || (from <= t && t + 3_600_000 <= to)).length;
assert.deepEqual(stats('session_tail(nyse_regular, last: 1h)'), [tail, tailKnown - tail, closes.length - tailKnown]);
assert.equal(tail, 9 * 4);
assert.equal(bench.nyText(z('2030-03-08T17:45:00Z')), 'FRI 12:45 EST');
assert.equal(bench.nyText(z('2030-03-06T15:00:00Z')), 'no session');
assert.equal(bench.nyText(z('2030-03-13T15:00:00Z')), 'WED 11:00 EDT');
assert.equal(bench.nyText(z('2030-03-04T03:00:00Z')), 'outside calendar');
ok('weekday and session_tail are known at every close the table covers, early close and closed day included');

calendarAnswer = () => Response.json({ error: 'field-data-api answered 503' }, { status: 502 });
await bench.load('pinned');
const failed = await bench.load('7d');
assert.equal(failed.calendar.pinned, true); assert.match(failed.calendar.error, /503/);
assert.equal(bench.engine.describeStudy(QUERY('weekday(nyse_regular) = fri')).manifest.pins.calendars[0].id, 'nyse-core-2025-01-05-v1');
const pinnedBack = await bench.load('pinned');
assert.equal(pinnedBack.calendar.pinned, true); assert.equal(pinnedBack.calendar.error, null);
assert.deepEqual(stats('weekday(nyse_regular) = fri'), [2016, 12461, 19], 'the pinned recording keeps its answer');
ok('without field-data-api a cube window falls back to the pinned table and says why; the pinned recording is unchanged');

standIn.close();
console.log('calendar: all checks passed');
