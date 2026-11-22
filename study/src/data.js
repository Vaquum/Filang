// Data layer: recorded bars (fixed-point cents on a UTC grid), pinned session calendar, SHA-256.
// The input files are read as-is and never modified.

import { parseCents, centsText } from './num.js';

export class DataError extends Error {}

// ---------------------------------------------------------------- SHA-256 (pure JS, FIPS 180-4)

const K256 = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]);

export function sha256Hex(bytes) {
  const len = bytes.length;
  const total = ((len + 9 + 63) >> 6) << 6;
  const buf = new Uint8Array(total);
  buf.set(bytes);
  buf[len] = 0x80;
  const dv = new DataView(buf.buffer);
  dv.setUint32(total - 8, Math.floor(len / 0x20000000));
  dv.setUint32(total - 4, (len * 8) >>> 0);
  let h0 = 0x6a09e667 | 0, h1 = 0xbb67ae85 | 0, h2 = 0x3c6ef372 | 0, h3 = 0xa54ff53a | 0;
  let h4 = 0x510e527f | 0, h5 = 0x9b05688c | 0, h6 = 0x1f83d9ab | 0, h7 = 0x5be0cd19 | 0;
  const w = new Int32Array(64);
  const rotr = (x, n) => (x >>> n) | (x << (32 - n));
  for (let off = 0; off < total; off += 64) {
    for (let i = 0; i < 16; i++) w[i] = dv.getInt32(off + i * 4);
    for (let i = 16; i < 64; i++) {
      const a = w[i - 15];
      const b = w[i - 2];
      const s0 = rotr(a, 7) ^ rotr(a, 18) ^ (a >>> 3);
      const s1 = rotr(b, 17) ^ rotr(b, 19) ^ (b >>> 10);
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) | 0;
    }
    let a = h0, b = h1, c = h2, d = h3, e = h4, f = h5, g = h6, h = h7;
    for (let i = 0; i < 64; i++) {
      const S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
      const ch = (e & f) ^ (~e & g);
      const t1 = (h + S1 + ch + K256[i] + w[i]) | 0;
      const S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const t2 = (S0 + maj) | 0;
      h = g; g = f; f = e; e = (d + t1) | 0; d = c; c = b; b = a; a = (t1 + t2) | 0;
    }
    h0 = (h0 + a) | 0; h1 = (h1 + b) | 0; h2 = (h2 + c) | 0; h3 = (h3 + d) | 0;
    h4 = (h4 + e) | 0; h5 = (h5 + f) | 0; h6 = (h6 + g) | 0; h7 = (h7 + h) | 0;
  }
  return [h0, h1, h2, h3, h4, h5, h6, h7].map((x) => (x >>> 0).toString(16).padStart(8, '0')).join('');
}

// ---------------------------------------------------------------- time formatting (UTC)

const pad = (x) => String(x).padStart(2, '0');
export function isoUTC(ms) {
  const d = new Date(ms);
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}Z`;
}
export function isoUTCFull(ms) { return new Date(ms).toISOString().replace('.000Z', 'Z'); }
export function hmUTC(ms) { const d = new Date(ms); return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`; }
export function dateUTC(ms) { return new Date(ms).toISOString().slice(0, 10); }
const WD = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'];
const WD_TITLE = { sun: 'Sun', mon: 'Mon', tue: 'Tue', wed: 'Wed', thu: 'Thu', fri: 'Fri', sat: 'Sat' };

// ---------------------------------------------------------------- recording

export class Recording {
  constructor(o) { Object.assign(this, o); }
  openTime(i) { return this.t0 + i * this.barMs; }
  closeTime(i) { return this.t0 + (i + 1) * this.barMs; }
  /** Slot whose bar closes exactly at t (may be out of range); null if t is off-grid. */
  slotClosingAt(t) {
    const x = (t - this.t0) / this.barMs - 1;
    return Number.isInteger(x) ? x : null;
  }
  get firstClose() { return this.t0 + this.barMs; }
  get lastClose() { return this.t0 + this.n * this.barMs; }
  has(i) { return i >= 0 && i < this.n && this.present[i] === 1; }
  ohlcText(i) {
    const f = this.raw[i];
    if (!f) return null;
    const prices = { open: f[0], high: f[1], low: f[2], close: f[3] };
    return this.VOL ? { ...prices, base_volume: f[4], volume: f[5], taker_buy_volume: f[6], trade_count: f[7] } : { ...prices, volume: f[4] };
  }
  price(c) { return centsText(c); }

  /**
   * One value per slot on a g1 dimension, NaN where the candle or the value is absent; null when the recording
   * carries no counters. Each value is the float its formula gives, evaluated exactly as written here
   * (docs/G1_DIMENSIONS.md): order and equality between candles are those of these floats.
   */
  dimension(name) {
    if (!this.VOL) return null;
    if (!this.dims) this.dims = new Map();
    if (this.dims.has(name)) return this.dims.get(name);
    const formula = DIMENSION_VALUE[name];
    if (!formula) throw new DataError(`unknown dimension "${name}"`);
    const values = new Float64Array(this.n).fill(NaN);
    for (let i = 0; i < this.n; i++) if (this.present[i]) values[i] = formula(this.VOL[i], this.TBV[i], this.CNT[i]);
    this.dims.set(name, values);
    return values;
  }

  /** Test fixture only: a copy in which the given slots are absent (source data untouched). */
  withoutSlots(slots, label) {
    const present = this.present.slice();
    const raw = this.raw.slice();
    for (const s of slots) { present[s] = 0; raw[s] = null; }
    return new Recording({ ...this, present, raw, dims: null, presentCount: present.reduce((a, b) => a + b, 0), fixture: label || 'slots removed in memory' });
  }

  /** Test fixture only: a copy that ends after slot i (used to prove no post-anchor data is read). */
  truncatedAfter(i) {
    const n = i + 1;
    return new Recording({
      ...this, n,
      O: this.O.slice(0, n), H: this.H.slice(0, n), L: this.L.slice(0, n), C: this.C.slice(0, n),
      ...(this.VOL ? { VOL: this.VOL.slice(0, n), TBV: this.TBV.slice(0, n), CNT: this.CNT.slice(0, n) } : {}), dims: null,
      present: this.present.slice(0, n), raw: this.raw.slice(0, n),
      presentCount: this.present.slice(0, n).reduce((a, b) => a + b, 0), fixture: `truncated after slot ${i}`,
    });
  }
}

// A candle's value on each dimension, from its counters: USDT traded, taker-buy USDT and trades (Cube's formulas).
const DIMENSION_VALUE = {
  volume: (vol) => vol,
  trades: (vol, tbvol, cnt) => cnt,
  delta: (vol, tbvol) => 2 * tbvol - vol,
  size: (vol, tbvol, cnt) => (cnt > 0 ? vol / cnt : NaN),
  imbalance: (vol, tbvol) => (vol > 0 ? (2 * tbvol - vol) / vol : NaN),
};

/** The nine-column recording: prices, then the cube's counters under the cube's names. `volume` is USDT. */
export const COUNTER_COLUMNS = Object.freeze(['open_ms', 'open', 'high', 'low', 'close', 'base_volume', 'volume', 'taker_buy_volume', 'trade_count']);

function instrumentFrom(provenance) {
  const parts = String(provenance.instrument || '').split(/\s+/);
  const sym = parts.find((p) => /^[A-Z0-9]{5,}$/.test(p));
  if (!sym) throw new DataError(`cannot find an instrument symbol in provenance "${provenance.instrument}"`);
  return { symbol: sym, venue: parts.filter((p) => p !== sym).join(' ') };
}

/**
 * Parse recorded-bars.csv. Prices become integer cents; refuses anything the fixed-point
 * model cannot represent exactly. Returns a Recording on a timestamp-indexed UTC grid.
 */
export function parseRecording(text, provenance, digest) {
  const issues = [];
  if (text.includes('\r')) issues.push('CSV has CR characters (CRLF line endings); they were ignored, but the digest will not match provenance');
  const lines = text.replace(/\r/g, '').split('\n');
  if (lines.length && lines[lines.length - 1] === '') lines.pop();
  const header = lines[0];
  const expected = (provenance.columns || []).join(',');
  if (header !== expected) throw new DataError(`CSV header "${header}" does not match provenance columns "${expected}"`);
  if (provenance.timestamp_role !== 'open') throw new DataError(`timestamp_role must be "open", got ${provenance.timestamp_role}`);
  const barMs = provenance.interval_ms;
  if (!Number.isSafeInteger(barMs) || barMs <= 0) throw new DataError('bad interval_ms');
  const rows = lines.length - 1;
  if (rows !== provenance.row_count) throw new DataError(`CSV has ${rows} rows; provenance row_count is ${provenance.row_count}`);
  const times = new Array(rows);
  const vals = new Array(rows);
  const counters = header === COUNTER_COLUMNS.join(',');
  const width = counters ? 9 : 6;
  let badOhlc = 0;
  for (let r = 0; r < rows; r++) {
    const f = lines[r + 1].split(',');
    if (f.length !== width) throw new DataError(`line ${r + 2}: expected ${width} fields, got ${f.length}`);
    if (!/^\d+$/.test(f[0])) throw new DataError(`line ${r + 2}: open_ms "${f[0]}" is not an integer`);
    const t = Number(f[0]);
    const o = parseCents(f[1]);
    const h = parseCents(f[2]);
    const l = parseCents(f[3]);
    const c = parseCents(f[4]);
    for (const [k, v, s] of [['open', o, f[1]], ['high', h, f[2]], ['low', l, f[3]], ['close', c, f[4]]]) {
      if (v === null) throw new DataError(`line ${r + 2}: ${k} "${s}" is not a nonnegative decimal with at most 2 places; integer cents cannot represent it exactly`);
    }
    if (!/^\d+(\.\d+)?$/.test(f[5])) throw new DataError(`line ${r + 2}: volume "${f[5]}" is not a nonnegative decimal`);
    if (h < Math.max(o, c) || l > Math.min(o, c)) badOhlc++;
    times[r] = t;
    vals[r] = [o, h, l, c, f.slice(1)];
    if (counters) {
      // An amount may be written with an exponent: that is how the shortest text of a very small float reads.
      for (const k of [6, 7]) if (!/^\d+(\.\d+)?(e[+-]?\d+)?$/.test(f[k])) throw new DataError(`line ${r + 2}: ${COUNTER_COLUMNS[k]} "${f[k]}" is not a nonnegative number`);
      if (!/^\d+$/.test(f[8])) throw new DataError(`line ${r + 2}: trade_count "${f[8]}" is not a whole number`);
      const vol = Number(f[6]), tbvol = Number(f[7]), cnt = Number(f[8]);
      if (!Number.isFinite(vol) || !Number.isFinite(tbvol) || !Number.isSafeInteger(cnt)) throw new DataError(`line ${r + 2}: a counter is too large to hold exactly`);
      if (tbvol > vol) throw new DataError(`line ${r + 2}: taker_buy_volume ${f[7]} exceeds volume ${f[6]}`);
      vals[r].push(vol, tbvol, cnt);
    }
  }
  const t0 = times[0];
  if (t0 % barMs !== 0) throw new DataError('first bar is not aligned to the UTC bar grid');
  for (let r = 1; r < rows; r++) {
    if (times[r] <= times[r - 1]) throw new DataError(`line ${r + 2}: timestamps must strictly increase`);
    if ((times[r] - t0) % barMs !== 0) throw new DataError(`line ${r + 2}: timestamp is off the ${barMs} ms grid`);
  }
  const n = (times[rows - 1] - t0) / barMs + 1;
  const O = new Float64Array(n);
  const H = new Float64Array(n);
  const L = new Float64Array(n);
  const C = new Float64Array(n);
  const present = new Uint8Array(n);
  const raw = new Array(n).fill(null);
  const VOL = counters ? new Float64Array(n).fill(NaN) : null;
  const TBV = counters ? new Float64Array(n).fill(NaN) : null;
  const CNT = counters ? new Float64Array(n).fill(NaN) : null;
  for (let r = 0; r < rows; r++) {
    const i = (times[r] - t0) / barMs;
    const [o, h, l, c, rawf] = vals[r];
    O[i] = o; H[i] = h; L[i] = l; C[i] = c; present[i] = 1; raw[i] = rawf;
    if (counters) { VOL[i] = vals[r][5]; TBV[i] = vals[r][6]; CNT[i] = vals[r][7]; }
  }
  const { symbol, venue } = instrumentFrom(provenance);
  const minutes = barMs / 60000;
  return new Recording({
    instrument: symbol, venue, barMs, barText: minutes % 60 === 0 ? `${minutes / 60}h` : `${minutes}m`,
    t0, n, O, H, L, C, VOL, TBV, CNT, dims: null, present, raw, presentCount: rows, badOhlc, issues,
    digest, digestShort: digest ? digest.slice(0, 12) : 'unverified', provenance,
  });
}

// ---------------------------------------------------------------- pinned session calendar

const WEEKDAY_NAMES = { Monday: 'mon', Tuesday: 'tue', Wednesday: 'wed', Thursday: 'thu', Friday: 'fri', Saturday: 'sat', Sunday: 'sun' };

function ymd(s) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
  if (!m) throw new DataError(`bad date ${s}`);
  return [Number(m[1]), Number(m[2]) - 1, Number(m[3])];
}

export class SessionCalendar {
  constructor(json, digest) {
    if (!json || !Array.isArray(json.sessions) || !json.sessions.length) throw new DataError('session table has no sessions');
    this.id = json.id;
    this.zone = json.zone;
    this.digest = digest || null;
    this.sources = json.sources || [];
    this.startDate = json.start_date_inclusive;
    this.endDate = json.end_date_exclusive;
    this.sessions = json.sessions.map((s, k) => {
      const [y, m, d] = ymd(s.date);
      const wd = WEEKDAY_NAMES[s.weekday];
      if (!wd) throw new DataError(`session ${s.date}: unknown weekday ${s.weekday}`);
      if (WD[new Date(Date.UTC(y, m, d)).getUTCDay()] !== wd) throw new DataError(`session ${s.date}: stored weekday ${s.weekday} does not match the date`);
      if (!(s.open_ms < s.close_ms)) throw new DataError(`session ${s.date}: open must precede close`);
      const offsetMs = s.open_ms - Date.UTC(y, m, d, 9, 30);
      if (offsetMs % 60000 !== 0 || Math.abs(offsetMs) > 14 * 3600000) throw new DataError(`session ${s.date}: open is not 09:30 local at a plausible UTC offset`);
      const dayStart = Date.UTC(y, m, d) + offsetMs;
      return { k, date: s.date, weekday: wd, open: s.open_ms, close: s.close_ms, offsetMs, dayStart, dayEnd: dayStart + 86_400_000 };
    });
    for (let k = 1; k < this.sessions.length; k++) {
      if (this.sessions[k].dayStart < this.sessions[k - 1].dayEnd) throw new DataError(`sessions ${this.sessions[k - 1].date} and ${this.sessions[k].date} are not in order`);
    }
    const first = this.sessions[0];
    const last = this.sessions[this.sessions.length - 1];
    const [sy, sm, sd] = ymd(this.startDate);
    const [ey, em, ed] = ymd(this.endDate);
    // Coverage bounds use the UTC offset of the nearest session in the pinned table.
    this.covStart = Date.UTC(sy, sm, sd) + first.offsetMs;
    this.covEnd = Date.UTC(ey, em, ed) + last.offsetMs;
    if (first.dayStart < this.covStart || last.dayEnd > this.covEnd) throw new DataError('sessions fall outside the declared coverage');
    this.shortestSessionMs = Math.min(...this.sessions.map((s) => s.close - s.open));
    this.offsets = [...new Set(this.sessions.map((s) => s.offsetMs))];
  }

  /** Session whose New York local day contains t, else closed (covered) or uncovered. */
  dayAt(t) {
    const ss = this.sessions;
    let lo = 0;
    let hi = ss.length - 1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (t < ss[mid].dayStart) hi = mid - 1;
      else if (t >= ss[mid].dayEnd) lo = mid + 1;
      else return { kind: 'session', s: ss[mid] };
    }
    if (t >= this.covStart && t < this.covEnd) return { kind: 'closed', prev: ss[hi] || null, next: ss[lo] || null };
    return { kind: 'uncovered' };
  }

  /** First session with close ≥ t, or null. */
  closeAtOrAfter(t) {
    const ss = this.sessions;
    let lo = 0;
    let hi = ss.length;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (ss[mid].close < t) lo = mid + 1; else hi = mid; }
    return ss[lo] || null;
  }

  covers(a, b) { return a >= this.covStart && b <= this.covEnd; }

  tzLabel(offsetMs) {
    if (this.zone === 'America/New_York') { if (offsetMs === 5 * 3600000) return 'EST'; if (offsetMs === 4 * 3600000) return 'EDT'; }
    const h = offsetMs / 3600000;
    return `UTC${h > 0 ? '−' : '+'}${Math.abs(h)}`;
  }

  /** Local wall time of t using a session's pinned offset, e.g. "15:30 EDT". */
  localHM(t, s) { return `${hmUTC(t - s.offsetMs)} ${this.tzLabel(s.offsetMs)}`; }
  localHMshort(t, s) { return hmUTC(t - s.offsetMs); }

  /** Display-only New York date for t (session day, or nearest session's offset otherwise). */
  localDateText(t) {
    const day = this.dayAt(t);
    if (day.kind === 'session') return `${WD_TITLE[day.s.weekday]} ${day.s.date}`;
    const ref = (day.prev || day.next || this.sessions[0]);
    const d = new Date(t - ref.offsetMs);
    return `${WD_TITLE[WD[d.getUTCDay()]]} ${d.toISOString().slice(0, 10)}`;
  }

  describe(t) {
    const day = this.dayAt(t);
    if (day.kind === 'session') return `${WD_TITLE[day.s.weekday]} ${day.s.date} ${this.localHM(t, day.s)}`;
    if (day.kind === 'closed') return `${this.localDateText(t)} (no session)`;
    return 'outside calendar coverage';
  }
}

export const WEEKDAY_TITLE = WD_TITLE;
