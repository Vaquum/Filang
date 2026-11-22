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
const cache = new Map();

const bytes = async (name) => {
  const r = await fetch('/study/' + name, { cache: 'no-cache' });
  if (!r.ok) throw Error(`${name}: ${r.status}`);
  return new Uint8Array(await r.arrayBuffer());
};

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
  if (window === PINNED) {
    const names = [DATA_FILES.bars, DATA_FILES.provenance, DATA_FILES.sessions, ...EXTENSION_FILES];
    const [csvBytes, provenanceBytes, sessionsBytes, ...ext] = await Promise.all(names.map(bytes));
    next = buildEnvironment({
      csvBytes, provenanceBytes, sessionsBytes,
      extensions: EXTENSION_FILES.map((file, i) => ({ file, bytes: ext[i] })),
    });
  } else {
    const [answer, sessionsBytes] = await Promise.all([fetch('/bars?w=' + encodeURIComponent(window), { cache: 'no-store' }), bytes(DATA_FILES.sessions)]);
    const body = await answer.json().catch(() => null);
    if (!answer.ok || !body?.csv) throw Error(body?.error || `bars: ${answer.status}`);
    const enc = new TextEncoder();
    next = buildEnvironment({ csvBytes: enc.encode(body.csv), provenanceBytes: enc.encode(JSON.stringify(body.provenance)), sessionsBytes });
  }
  bundle = next; held = window; cache.clear();
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
