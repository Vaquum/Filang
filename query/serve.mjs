// Server for the Filang query bench.
// It serves this folder, the shared Filang engine's browser package and the pinned recording, read-only, so the
// bench asks the engine real Filang queries in the browser. It has no login of its own: in production it listens on
// 127.0.0.1 only, behind the host's Caddy and the Portal login.
// With CUBE_URL set to Cube's bridge it also serves the cube's bars for Cube's time windows (/bars); without it,
// or when the bridge cannot answer, the bench reads the pinned recording.
// With FIELD_DATA_URL set to Vaquum's field-data-api, the service Cube reads its calendar from, it also serves the
// nyse_regular table the cube windows are asked with (/calendar/nyse), rewritten from the NYSE sessions that service
// publishes. Without it, or when the service cannot answer, cube windows use the engine's pinned table.
import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { extname, join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { cubeSource, CubeError, INTERVALS, WINDOWS } from './cube.mjs';
import { fieldDataCalendar, CalendarError } from './calendar.mjs';

const HERE = fileURLToPath(new URL('.', import.meta.url));
// The pinned recording and the provenance that names its digest. The recording is built by study/prepare_recording.py.
const RECORDING = resolve(process.env.FILANG_STUDY_DATA || join(HERE, '../data/study'), 'recorded-bars.csv');
const PROVENANCE = resolve(process.env.FILANG_QUERY_PROVENANCE || join(HERE, '../study/data-provenance.json'));
// The engine's browser package: a pinned release in the image, a local build (bindings/build.py) in a checkout.
const ENGINE = resolve(process.env.FILANG_QUERY_ENGINE_DIR || join(HERE, '../target/engine-dist/browser'));
const engineAssets = new Set(['index.mjs', 'worker-client.mjs', 'worker.mjs', 'filang_engine.wasm']);
const host = process.env.HOST || '127.0.0.1';
const port = Number(process.env.PORT || process.argv[2] || 8790);
const cube = process.env.CUBE_URL ? cubeSource({ url: process.env.CUBE_URL }) : null;
const fieldData = process.env.FIELD_DATA_URL ? fieldDataCalendar({ url: process.env.FIELD_DATA_URL, token: process.env.FIELD_DATA_API_TOKEN || null }) : null;
// The window the bench opens on when the cube answers: about as many 15m bars as the pinned recording holds.
const DEFAULT_WINDOW = '180d';

const mime = new Map([
  ['.html', 'text/html; charset=utf-8'], ['.css', 'text/css; charset=utf-8'],
  ['.js', 'text/javascript; charset=utf-8'], ['.mjs', 'text/javascript; charset=utf-8'],
  ['.json', 'application/json; charset=utf-8'], ['.csv', 'text/csv; charset=utf-8'],
  ['.svg', 'image/svg+xml'], ['.wasm', 'application/wasm'],
]);
const pageAsset = /^(?:index\.html|(?:bench|shared)\/[\w.-]+\.(?:js|css))$/;
// The bench cannot answer without these, so their absence is a failed health check, not a blank page.
const required = [RECORDING, PROVENANCE, ...[...engineAssets].map((asset) => join(ENGINE, asset))];

function locate(path) {
  if (path.startsWith('engine/')) {
    const asset = path.slice(7);
    return engineAssets.has(asset) ? join(ENGINE, asset) : null;
  }
  if (path === 'recording/bars.csv') return RECORDING;
  if (path === 'recording/provenance.json') return PROVENANCE;
  const name = path === '' ? 'index.html' : path;
  if (!pageAsset.test(name)) return null;
  const file = resolve(HERE, name);
  return file.startsWith(HERE.endsWith(sep) ? HERE : HERE + sep) ? file : null;
}
const missing = async () => (await Promise.all(required.map((file) => stat(file).then(() => null, () => file)))).filter(Boolean);

const server = createServer(async (req, res) => {
  try {
    if (!['GET', 'HEAD'].includes(req.method)) { res.writeHead(405); return res.end(); }
    const path = decodeURIComponent(new URL(req.url, 'http://127.0.0.1').pathname).slice(1);
    if (path === 'healthz') {
      const gone = await missing();
      res.writeHead(gone.length ? 503 : 200, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
      // The answer names the service: a deploy must be able to tell Query from whatever else holds a port.
      return res.end(JSON.stringify(gone.length ? { service: 'filang-query', ok: false, missing: gone.length } : { service: 'filang-query', ok: true }));
    }
    const json = (status, body) => { res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' }); res.end(req.method === 'HEAD' ? undefined : JSON.stringify(body)); };
    if (path === 'calendar/nyse') {
      if (!fieldData) return json(404, { error: 'this server reads no field-data-api calendar' });
      try { return json(200, await fieldData.nyse()); }
      catch (e) {
        if (!(e instanceof CalendarError)) throw e;
        return json(502, { error: e.message });
      }
    }
    if (path === 'bars/windows' || path === 'bars') {
      // What the bench may ask for. Without a cube there is the pinned recording only.
      if (path === 'bars/windows') return json(200, { cube: Boolean(cube), default: DEFAULT_WINDOW, intervals: Object.keys(INTERVALS), windows: cube ? WINDOWS.map(({ key, name }) => ({ key, name })) : [] });
      if (!cube) return json(404, { error: 'this server has no cube to read; the bench uses its pinned recording' });
      const asked = new URL(req.url, 'http://127.0.0.1').searchParams;
      try { return json(200, await cube.bars(asked.get('w') || DEFAULT_WINDOW, asked.get('tf') || '15m')); }
      catch (e) {
        if (!(e instanceof CubeError)) throw e;
        // An unknown window or interval is the asker's mistake; anything else is the cube or its bridge.
        return json(/^unknown /.test(e.message) ? 400 : 502, { error: e.message });
      }
    }
    if (path.split('/').some((s) => s === '..')) { res.writeHead(400); return res.end(); }
    const file = locate(path);
    if (!file) { res.writeHead(404); return res.end('Not found'); }
    const body = await readFile(file);
    // Every response sits behind the Portal login, so nothing is cached past a logout.
    res.writeHead(200, { 'Content-Type': mime.get(extname(file)) || 'application/octet-stream', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' });
    res.end(req.method === 'HEAD' ? undefined : body);
  } catch (e) {
    res.writeHead(e.code === 'ENOENT' ? 404 : e instanceof URIError ? 400 : 500);
    res.end(e.code === 'ENOENT' ? 'Not found' : 'Server error');
    if (e.code !== 'ENOENT' && !(e instanceof URIError)) console.error(e);
  }
});
for (const sig of ['SIGTERM', 'SIGINT']) process.once(sig, () => server.close(() => process.exit(0)));
server.listen(port, host, async () => {
  const gone = await missing();
  // The port it bound, which is the port asked for unless that was 0: a check that starts its own server asks for any.
  console.log(`Filang query bench on http://${host}:${server.address().port}/ · engine ${ENGINE} · bars ${cube ? `cube at ${process.env.CUBE_URL}` : 'pinned recording'} · calendar ${fieldData ? `field-data-api at ${process.env.FIELD_DATA_URL}` : 'pinned table'}${gone.length ? ` · MISSING ${gone.join(', ')}` : ''}`);
});
