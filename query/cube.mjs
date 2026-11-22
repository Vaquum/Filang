// Bars from the market-state cube, read through Cube's own bridge, for the windows Cube offers.
// The bridge serves the cube's bars on its dyadic time grid (/cube/bars, MSCB blocks); this turns a window of
// them into the recording the study engine reads: open_ms,open,high,low,close,volume with prices in exact cents.
// Server side only. Nothing here is served to a browser, and a browser never talks to the bridge.
import { gunzipSync } from 'node:zlib';
import { createHash } from 'node:crypto';

export const PROTOCOL = '2';
export const MAX_COLUMNS = 4096;                 // the bridge answers at most this many bars at once
/** Bar intervals the cube's grid shares with the study language: 56.25 s × 2^n. */
export const INTERVALS = Object.freeze({ '15m': 4, '30m': 5, '1h': 6, '2h': 7, '4h': 8 });
const DAY = 86400;
/** Cube's time windows, by the key Cube uses for each. A span is seconds back from the latest complete bar. */
export const WINDOWS = Object.freeze([
  { key: '15m', name: 'Last 15 minutes', span: 900 }, { key: '30m', name: 'Last 30 minutes', span: 1800 },
  { key: '1h', name: 'Last hour', span: 3600 }, { key: '4h', name: 'Last 4 hours', span: 4 * 3600 },
  { key: '12h', name: 'Last 12 hours', span: 12 * 3600 }, { key: '24h', name: 'Last 24 hours', span: DAY },
  { key: '7d', name: 'Last 7 days', span: 7 * DAY }, { key: '30d', name: 'Last 30 days', span: 30 * DAY },
  { key: '45d', name: 'Last 45 days', span: 45 * DAY }, { key: '90d', name: 'Last 90 days', span: 90 * DAY },
  { key: '180d', name: 'Last 180 days', span: 180 * DAY }, { key: '270d', name: 'Last 270 days', span: 270 * DAY },
  { key: '1y', name: 'Last 12 months', span: 365 * DAY }, { key: 'ytd', name: 'This year' },
  { key: 'lastyear', name: 'Last year' }, { key: 'all', name: 'All history' },
]);
const COLUMNS = ['open_ms', 'open', 'high', 'low', 'close', 'volume'];
const FIELDS = ['open', 'high', 'low', 'close', 'vol', 'tbvol', 'btc', 'cnt'];   // MSCB order, f64 each, then the column u32

export class CubeError extends Error {}

/** A day named in a window key, `since:YYYY-MM-DD`, as UTC seconds; null when the key is not one. */
function sinceDay(key) {
  const m = /^since:(\d{4})-(\d{2})-(\d{2})$/.exec(key);
  if (!m) return null;
  const t = Date.UTC(+m[1], +m[2] - 1, +m[3]) / 1000;
  return new Date(t * 1000).toISOString().slice(0, 10) === key.slice(6) ? t : null;
}

/**
 * The base columns [b0, b1) a window covers at level n, for a cube whose data ends at base position `cutoff`.
 * A window ends at the latest complete bar, as Cube's do, except "last year", which ends where that year did.
 */
export function windowRange(key, n, { t0, baseSeconds, cutoff }) {
  const step = 2 ** n;
  const toBase = (seconds) => (seconds - t0) / baseSeconds;
  const down = (base) => Math.max(0, Math.floor(base / step) * step);
  const last = down(cutoff);                                   // the edge after the latest complete bar
  const year = new Date((t0 + last * baseSeconds) * 1000 - 1).getUTCFullYear();
  const window = WINDOWS.find((w) => w.key === key);
  const day = sinceDay(key);
  let b0; let b1 = last; let name;
  if (window?.span) { b0 = down(last - window.span / baseSeconds); name = window.name; }
  else if (key === 'ytd') { b0 = down(toBase(Date.UTC(year, 0, 1) / 1000)); name = `${year}`; }
  else if (key === 'lastyear') { b0 = down(toBase(Date.UTC(year - 1, 0, 1) / 1000)); b1 = Math.min(last, down(toBase(Date.UTC(year, 0, 1) / 1000))); name = `${year - 1}`; }
  else if (key === 'all') { b0 = 0; name = 'All history'; }
  else if (day !== null) { b0 = down(toBase(day)); name = `Since ${key.slice(6)}`; }
  else throw new CubeError(`unknown window "${key}"`);
  if (b0 >= b1) throw new CubeError(`the window "${key}" holds no complete ${Object.keys(INTERVALS).find((k) => INTERVALS[k] === n)} bar yet`);
  return { b0, b1, name };
}

/** One MSCB block: its header and arrays. */
export function decodeMscb(base64) {
  const raw = gunzipSync(Buffer.from(base64, 'base64'));
  if (raw.length < 32 || raw.toString('latin1', 0, 4) !== 'MSCB') throw new CubeError('the bridge answered something that is not an MSCB block');
  const n = raw.readUInt8(4); const col0 = raw.readUInt32LE(8); const col1 = raw.readUInt32LE(12); const count = raw.readUInt32LE(16);
  if (raw.length !== 32 + count * (FIELDS.length * 8 + 4)) throw new CubeError('the MSCB block is not the length its header says');
  const out = { n, col0, col1, count };
  let at = 32;
  for (const field of FIELDS) {
    const a = new Float64Array(count);
    for (let i = 0; i < count; i++) a[i] = raw.readDoubleLE(at + i * 8);
    out[field] = a; at += count * 8;
  }
  out.col = new Uint32Array(count);
  for (let i = 0; i < count; i++) out.col[i] = raw.readUInt32LE(at + i * 4);
  return out;
}

/** A price as the engine reads it: exact cents, or a refusal. The cube's prices are trades, so they are whole cents. */
function cents(value, what, openMs) {
  const scaled = value * 100; const whole = Math.round(scaled);
  if (!Number.isFinite(value) || value < 0 || Math.abs(scaled - whole) > 1e-6) throw new CubeError(`the bar opening ${new Date(openMs).toISOString()} has ${what} ${value}, which is not a whole number of cents`);
  return `${Math.floor(whole / 100)}.${String(whole % 100).padStart(2, '0')}`;
}
const volume = (value) => {
  if (!Number.isFinite(value) || value < 0) throw new CubeError(`a bar has volume ${value}`);
  const text = value.toFixed(8).replace(/\.?0+$/, '');
  return text === '' ? '0' : text;
};

/** A client of one bridge. It holds the bridge's current pack and the last few windows it built. */
export function cubeSource({ url, fetch: get = fetch, keep = 4, packMaxAgeMs = 30_000, now = Date.now }) {
  const base = url.replace(/\/+$/, '');
  let pack = null; let packAt = -Infinity;
  const built = new Map();

  async function ask(path) {
    let res;
    try { res = await get(`${base}${path}`, { headers: { Accept: 'application/json' }, signal: AbortSignal.timeout(60_000) }); }
    catch (e) { throw new CubeError(`the cube bridge did not answer: ${e.message}`); }
    let body = null;
    try { body = await res.json(); } catch { /* reported below */ }
    if (!res.ok || body === null) {
      const error = new CubeError(`the cube bridge answered ${res.status}${body?.error ? `: ${body.error}` : ''}`);
      error.status = res.status;
      throw error;
    }
    return body;
  }

  /** What the bridge's pack says about the cube now. Asked again at most every packMaxAgeMs. */
  async function state(force = false) {
    if (pack && !force && now() - packAt < packMaxAgeMs) return pack;
    const answer = await ask(`/cube/pack?proto=${PROTOCOL}&since=${encodeURIComponent(pack?.token || '')}`);
    if (answer.status === 'current' && pack) { packAt = now(); return pack; }
    const from = answer.status === 'pack' ? answer.pack : answer;
    const next = {
      token: from.state_token, cutoff: from.cutoffBase, canonicalThrough: from.canonical_through || null,
      t0: from.t0 ?? pack?.t0, baseSeconds: from.base_seconds ?? pack?.baseSeconds,
    };
    if (typeof next.token !== 'string' || !Number.isFinite(next.cutoff) || !Number.isFinite(next.t0) || !Number.isFinite(next.baseSeconds)) {
      throw new CubeError('the cube bridge did not say where its data ends');
    }
    pack = next; packAt = now();
    return pack;
  }

  async function read(key, interval, held) {
    const n = INTERVALS[interval];
    const { b0, b1, name } = windowRange(key, n, held);
    const step = 2 ** n; const intervalMs = Math.round(held.baseSeconds * step * 1000);
    const lines = [COLUMNS.join(',')];
    let end = b0; let lastOpen = -Infinity;
    for (let from = b0; from < b1; from += MAX_COLUMNS * step) {
      const to = Math.min(b1, from + MAX_COLUMNS * step);
      const answer = await ask(`/cube/bars?proto=${PROTOCOL}&n=${n}&b0=${from}&b1=${to}&pack=${encodeURIComponent(held.token)}`);
      const block = decodeMscb(answer.bars.gzip_base64);
      if (block.n !== n) throw new CubeError(`the bridge answered level ${block.n} for level ${n}`);
      // A bar is kept only when the cube has measured all of it: `end` is where its measures stop.
      const measured = Math.floor(answer.end / step);
      for (let i = 0; i < block.count; i++) {
        if (block.col[i] >= measured) continue;
        const openMs = Math.round((held.t0 + block.col[i] * step * held.baseSeconds) * 1000);
        if (openMs <= lastOpen) throw new CubeError('the bridge answered bars out of time order');
        lastOpen = openMs;
        lines.push([openMs, cents(block.open[i], 'open', openMs), cents(block.high[i], 'high', openMs), cents(block.low[i], 'low', openMs),
          cents(block.close[i], 'close', openMs), volume(block.btc[i])].join(','));
      }
      end = Math.min(to, measured * step);
      if (end < to) break;                       // the cube has not measured further: the window ends here
    }
    if (lines.length === 1) throw new CubeError(`the cube holds no bars in the window "${key}"`);
    const csv = lines.join('\n') + '\n';
    const ms = (b) => Math.round((held.t0 + b * held.baseSeconds) * 1000);
    const canonicalMs = held.canonicalThrough ? Date.parse(held.canonicalThrough) : null;
    let provisional = 0;
    if (canonicalMs !== null) for (let i = lines.length - 1; i > 0 && Number(lines[i].slice(0, lines[i].indexOf(','))) + intervalMs > canonicalMs; i--) provisional++;
    return {
      provenance: {
        instrument: 'Binance BTCUSDT spot', interval_ms: intervalMs, timestamp_role: 'open', columns: COLUMNS,
        row_count: lines.length - 1, csv_sha256: createHash('sha256').update(csv).digest('hex'),
        source: 'cube', window: key, window_name: name, interval, from: new Date(ms(b0)).toISOString(), through: new Date(ms(end)).toISOString(),
        canonical_through: held.canonicalThrough, provisional_rows: provisional, state_token: held.token,
        derived_by: 'Cube bridge /cube/bars (MSCB), open, high, low, close in exact cents and BTC volume. No rows or prices generated.',
      },
      csv,
    };
  }

  /** The recording for one of Cube's windows at one interval, as { provenance, csv }. */
  async function bars(key, interval = '15m') {
    if (!(interval in INTERVALS)) throw new CubeError(`unknown interval "${interval}"`);
    let held = await state();
    const id = () => `${held.token}|${interval}|${key}`;
    if (built.has(id())) return built.get(id());
    let answer;
    try { answer = await read(key, interval, held); }
    catch (e) {
      // The cube moved on while the window was read: the bridge no longer holds that pack. Read once more on the new one.
      if (!(e instanceof CubeError) || e.status !== 409) throw e;
      held = await state(true);
      answer = await read(key, interval, held);
    }
    built.set(id(), answer);
    while (built.size > keep) built.delete(built.keys().next().value);
    return answer;
  }

  return { bars, state };
}
