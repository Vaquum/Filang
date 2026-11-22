// The dimension lanes, without a browser: which lanes are shown, how the address keeps them, each column's value,
// and how a value is printed. A lane is one dimension of the candles on the canvas, drawn under them.
import { DIMENSIONS } from '/shared/vocab.js';

const KEYS = DIMENSIONS.map((d) => d.key);
const SIGNED = new Set(DIMENSIONS.filter((d) => d.signed).map((d) => d.key));

/**
 * The lanes on show, in the dimensions' written order. A dimension the question refers to is shown unless it was
 * switched off; any other is shown once it was switched on. `set` holds only the switches that were thrown.
 */
export const lanesShown = (used, set) => KEYS.filter((d) => set[d] ?? used.includes(d));

/** Throw one switch. A switch put back to where the question leaves it is no longer a choice of its own. */
export function setLane(set, used, key, on) {
  if (on === used.includes(key)) delete set[key]; else set[key] = on;
  return set;
}

/**
 * The lanes as the address keeps them: the names on show, comma-separated. Null when the question refers to no
 * dimension and no lane is shown, which is every address written before there were lanes.
 */
export function lanesParam(used, set) {
  const shown = lanesShown(used, set);
  return shown.length || used.length ? shown.join(',') : null;
}

/** The switches an address asks for, given what its question refers to. Names it does not know are passed over. */
export function lanesFromParam(param, used) {
  const set = {};
  if (param === null || param === undefined) return set;
  const named = new Set(param.split(',').filter((d) => KEYS.includes(d)));
  for (const d of KEYS) if (named.has(d) !== used.includes(d)) set[d] = named.has(d);
  return set;
}

const quant = (arr, m, f) => { if (!m) return null; const x = (m - 1) * f; const a = Math.floor(x); const b = Math.min(m - 1, a + 1); return arr[a] + (arr[b] - arr[a]) * (x - a); };

/**
 * One dimension, column by column, for the candles around a set of closes: the median of the recorded values at each
 * offset from the close, the middle half, and how many candles had a value. For a single close the median is that
 * candle's own value. A candle that is absent, or has no such value, is left out; a column with none has n 0.
 */
export function dimensionColumns(rec, slots, lead, H, key) {
  const x = rec.dimension(key); const n = slots.length; const held = new Float64Array(n); const cols = [];
  for (let k = -lead; k <= H; k++) {
    let m = 0;
    for (let q = 0; q < n; q++) {
      const j = slots[q] + k;
      if (j < 0 || j >= rec.n || Number.isNaN(x[j])) continue;
      held[m++] = x[j];
    }
    const sorted = held.subarray(0, m).slice().sort();
    cols.push({ k, n: m, v: quant(sorted, m, 0.5), q1: quant(sorted, m, 0.25), q3: quant(sorted, m, 0.75) });
  }
  return { key, cols, n, single: n === 1, signed: SIGNED.has(key) };
}

/** What one unit of a dimension is, as a caption beside a figure. */
export const UNIT = { volume: 'USDT', trades: 'trades', delta: 'USDT', size: 'USDT a trade', imbalance: 'of volume' };

const short = (a) => (a >= 1e9 ? (a / 1e9).toFixed(2) + 'B' : a >= 1e6 ? (a / 1e6).toFixed(2) + 'M' : a >= 1e4 ? (a / 1e3).toFixed(1) + 'K' : a >= 100 ? Math.round(a).toLocaleString('en-US') : a.toFixed(2));
/** A value as a figure: amounts shortened to three or four digits, counts whole, a signed dimension with its sign. */
export function dimensionText(key, v) {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  const sign = SIGNED.has(key) ? (v > 0 ? '+' : v < 0 ? '−' : '') : '';
  const a = Math.abs(v);
  if (a === 0) return '0';
  if (key === 'imbalance') return sign + a.toFixed(3);
  if (key === 'trades') return a >= 1e6 ? short(a) : (Number.isInteger(a) ? a : Math.round(a * 10) / 10).toLocaleString('en-US');
  return sign + short(a);
}
/** A recorded value in full, for one candle: nothing shortened. */
export function dimensionExact(key, v) {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  const sign = SIGNED.has(key) ? (v > 0 ? '+' : v < 0 ? '−' : '') : '';
  const a = Math.abs(v);
  if (key === 'imbalance') return sign + a.toFixed(4);
  if (key === 'trades') return a.toLocaleString('en-US');
  return sign + a.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
