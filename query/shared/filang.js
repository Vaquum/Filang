// Engine adapter. Loads the pinned recording and runs real Filang studies in the browser,
// using the checker and evaluator from the query-builder checkout unchanged.
import { buildEnvironment, DATA_FILES, EXTENSION_FILES } from '/study/src/boot.js';
import { analyze } from '/study/src/check.js';
import { runAnalysis, T, F, U } from '/study/src/engine.js';
import { CANDLE_PATTERNS } from '/study/src/registry.js';
import { isoUTC, dateUTC, hmUTC } from '/study/src/data.js';

export { T, F, U, isoUTC, dateUTC, hmUTC, CANDLE_PATTERNS };

export const HEAD = 'on BTCUSDT 15m';
// The language requires an event in `find`. This relation holds on every recorded candle.
export const ANY_CLOSE = 'candle_relation(price(high), is: at_or_above, right: price(low))';
/** The pinned recording, as a window key. Every other key is one of Cube's time windows. */
export const PINNED = 'pinned';

let bundle = null;
let held = null;
let geometryEngine = null;
let engineLoading = null;
const radiusCache = new Map();
const cache = new Map();

const bytes = async (name) => {
  const r = await fetch('/study/' + name, { cache: 'no-cache' });
  if (!r.ok) throw Error(`${name}: ${r.status}`);
  return new Uint8Array(await r.arrayBuffer());
};

function browserEngine() {
  return engineLoading ??= (async () => {
    const endpoint = '/engine/index.mjs';
    const available = await fetch(endpoint, {method: 'HEAD', cache: 'no-cache'});
    if (!available.ok) return null;
    const {FilangEngine} = await import(endpoint);
    const engine = await FilangEngine.create();
    if (typeof engine.radiusSeries !== 'function') {
      engine.close();
      return null;
    }
    return engine;
  })().catch(() => {
    engineLoading = null;
    return null;
  });
}

function radiusGeometry(code, reading, radius) {
  const key = JSON.stringify([code, reading, radius]);
  if (radiusCache.has(key)) return radiusCache.get(key);
  const result = geometryEngine.radiusSeries(code, {reading, radius});
  const vals = Int8Array.from(result.states, state => state === '1' ? T : state === '0' ? F : U);
  const why = i => {
    if (vals[i] === U) return 'Geometry requires consecutive recorded bars and all selected readings.';
    const shape = geometryEngine.geometryShape(code);
    const dimensions = code.split('|').slice(1).map(part => part.slice(0, part.indexOf(':')));
    const observed = geometryEngine.at(i, shape.ranks.length, {reading, oriented: shape.directions !== null, dimensions});
    const distance = geometryEngine.distance(code, observed.code).half_flips;
    return `${observed.code} differs by ${distance} half-flips from ${code} (radius ${radius}).`;
  };
  const series = {vals, why, counts: result.counts, byDistance: result.by_distance};
  if (radiusCache.size >= 64) radiusCache.delete(radiusCache.keys().next().value);
  radiusCache.set(key, series);
  return series;
}

export const geometryRadiusAvailable = () => geometryEngine !== null;
export const geometryRadiusReceipt = (code, reading, radius) => radiusGeometry(code, reading, radius).byDistance;

/** What this server can read: { cube, default, windows: [{ key, name }] }. Without a cube, the pinned recording only. */
export async function sources() {
  try {
    const r = await fetch('/bars/windows', { cache: 'no-store' });
    if (r.ok) return await r.json();
  } catch { /* an older server, or none: the pinned recording */ }
  return { cube: false, default: PINNED, windows: [] };
}

/**
 * Load the bars the bench reads: the pinned recording, or one of Cube's windows from the cube itself.
 * The extensions carry cases recorded on the pinned recording, so they are installed with it alone.
 */
export async function load(window = PINNED) {
  if (bundle && held === window) return bundle;
  let next;
  let recording;
  const engine = browserEngine();
  if (window === PINNED) {
    const names = [DATA_FILES.bars, DATA_FILES.provenance, DATA_FILES.sessions, ...EXTENSION_FILES];
    const [csvBytes, provenanceBytes, sessionsBytes, ...ext] = await Promise.all(names.map(bytes));
    recording = csvBytes;
    next = buildEnvironment({
      csvBytes, provenanceBytes, sessionsBytes,
      extensions: EXTENSION_FILES.map((file, i) => ({ file, bytes: ext[i] })),
    });
  } else {
    const [answer, sessionsBytes] = await Promise.all([fetch('/bars?w=' + encodeURIComponent(window), { cache: 'no-store' }), bytes(DATA_FILES.sessions)]);
    const body = await answer.json().catch(() => null);
    if (!answer.ok || !body?.csv) throw Error(body?.error || `bars: ${answer.status}`);
    recording = body.csv;
    const enc = new TextEncoder();
    next = buildEnvironment({ csvBytes: enc.encode(body.csv), provenanceBytes: enc.encode(JSON.stringify(body.provenance)), sessionsBytes });
  }
  let geometry = await engine;
  if (geometry !== null) {
    try {
      geometry.loadCsv(typeof recording === 'string' ? recording : new TextDecoder().decode(recording), next.rec.barMs);
      next.ctx.radiusGeometry = radiusGeometry;
    } catch {
      geometry = null;
    }
  }
  geometryEngine = geometry;
  bundle = next; held = window; cache.clear(); radiusCache.clear();
  return bundle;
}

/** The window the loaded bars cover. */
export const loaded = () => held;
export const env = () => bundle;
export const rec = () => bundle.rec;

/** Check and evaluate a full query text. Results are memoized by text. */
export function run(text) {
  if (cache.has(text)) return cache.get(text);
  let out;
  try {
    const analysis = analyze(text, bundle.env);
    if (!analysis.ok) out = { ok: false, text, errors: analysis.errors, analysis, results: [] };
    else {
      const r = runAnalysis(bundle.ctx, analysis, { digestVerified: bundle.digestVerified });
      out = { ok: true, text, errors: [], analysis, results: r.results, ms: r.ms, manifest: r.manifest };
    }
  } catch (e) {
    out = { ok: false, text, errors: [{ kind: 'engine', message: String(e.message || e) }], results: [] };
  }
  if (cache.size > 600) cache.delete(cache.keys().next().value);
  cache.set(text, out);
  return out;
}

/** Matching closes for a query body (everything after the `on` line); null when it does not check. */
export function count(body) {
  const r = run(HEAD + '\n' + body);
  return r.ok ? r.results[0].matches.length : null;
}

// ---------------------------------------------------------------- formatting

export const int = (n) => n.toLocaleString('en-US');
export const price = (cents) => (cents / 100).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
export function pct(x, digits = 2) {
  if (x === null || x === undefined || Number.isNaN(x)) return '—';
  const v = x * 100;
  const s = Math.abs(v).toFixed(digits);
  return (v > 0 ? '+' : v < 0 ? '−' : '') + s + '%';
}
export const share = (a, b, digits = 0) => (b ? ((a / b) * 100).toFixed(digits) + '%' : '—');

export function nyText(t) {
  const cal = bundle.cal;
  const day = cal.dayAt(t);
  if (day.kind === 'session') return `${day.s.weekday.toUpperCase()} ${cal.localHM(t, day.s)}`;
  if (day.kind === 'closed') return 'no session';
  return 'outside calendar';
}

/** Outcome summary with the share of positive observations. */
export function describeSummary(s) {
  if (!s || !s.observed) return { n: 0, up: '—', median: '—', mean: '—' };
  return { n: s.observed, up: share(s.positive, s.observed), median: pct(s.median), mean: pct(s.mean) };
}

/** Sorted observed outcome values for column k. */
export function observed(rows, k) {
  const v = [];
  for (const r of rows) if (r.out[k]?.status === 'observed') v.push(r.out[k].value);
  return v.sort((a, b) => a - b);
}
