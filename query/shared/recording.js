// The bars the bench draws. The engine answers every question; this only reads the CSV the engine was given into
// arrays for the charts, on the same grid: slot i opens at t0 + i bars, and a slot with no row is a gap.

const cents = (text) => Math.round(Number(text) * 100);
const counterHeader = 'open_ms,open,high,low,close,base_volume,volume,taker_buy_volume,trade_count';

/** Read `open_ms,open,high,low,close,…` rows into slot arrays of integer cents. */
export function readRecording(csv, provenance) {
  const barMs = provenance.interval_ms;
  if (!Number.isSafeInteger(barMs) || barMs <= 0) throw Error('the recording names no bar interval');
  const lines = csv.split('\n');
  if (lines[lines.length - 1] === '') lines.pop();
  const rows = lines.length - 1;
  if (rows < 1) throw Error('the recording holds no bars');
  const openOf = (line) => Number(line.slice(0, line.indexOf(',')));
  const t0 = openOf(lines[1]);
  const n = (openOf(lines[rows]) - t0) / barMs + 1;
  if (!Number.isSafeInteger(n) || n < rows) throw Error('the recording is off its bar grid');
  const O = new Float64Array(n); const H = new Float64Array(n); const L = new Float64Array(n); const C = new Float64Array(n);
  const present = new Uint8Array(n);
  const hasCounters = lines[0].trimEnd() === counterHeader;
  for (let r = 1; r <= rows; r++) {
    const f = lines[r].split(','); const i = (Number(f[0]) - t0) / barMs;
    if (!Number.isInteger(i) || i < 0 || i >= n || present[i]) throw Error(`line ${r + 1} of the recording is off its bar grid`);
    O[i] = cents(f[1]); H[i] = cents(f[2]); L[i] = cents(f[3]); C[i] = cents(f[4]); present[i] = 1;
  }
  const parts = String(provenance.instrument || '').split(/\s+/);
  const instrument = parts.find((p) => /^[A-Z0-9]{5,}$/.test(p));
  if (!instrument) throw Error(`the recording names no instrument: "${provenance.instrument}"`);
  const minutes = barMs / 60000;
  const derived = new Map();
  let values;
  const dimension = (key) => {
    if (!hasCounters) return null;
    if (!values) {
      values = Object.fromEntries(['volume', 'taker', 'trades'].map(name => [name, new Float64Array(n).fill(NaN)]));
      for (const line of csv.trimEnd().split('\n').slice(1)) {
        const f = line.split(','); const i = (Number(f[0]) - t0) / barMs;
        values.volume[i] = Number(f[6]);
        values.taker[i] = Number(f[7]);
        values.trades[i] = Number(f[8]);
      }
    }
    if (key === 'volume' || key === 'trades') return values[key];
    if (!derived.has(key)) {
      const result = values.volume.map((volume, i) => {
        if (key === 'size') return values.trades[i] > 0 ? volume / values.trades[i] : NaN;
        const delta = 2 * values.taker[i] - volume;
        if (key === 'delta') return delta;
        return key === 'imbalance' && volume > 0 ? delta / volume : NaN;
      });
      derived.set(key, result);
    }
    return derived.get(key);
  };
  return {
    instrument, venue: parts.filter((p) => p !== instrument).join(' '), barMs, barText: minutes % 60 === 0 ? `${minutes / 60}h` : `${minutes}m`,
    t0, n, O, H, L, C, present, presentCount: rows, lastClose: t0 + n * barMs, hasCounters, dimension,
    openTime: (i) => t0 + i * barMs,
    closeTime: (i) => t0 + (i + 1) * barMs,
    /** The slot whose bar closes exactly at t, which may lie outside the recording; null when t is off the grid. */
    slotClosingAt: (t) => { const x = (t - t0) / barMs - 1; return Number.isInteger(x) ? x : null; },
  };
}
