'use strict';
/* Ashi matcher. Runs in a Web Worker beside the composer.
   It reads the BTCUSDT klines, served by Composer's server from the Vaquum HuggingFace files, as exact integer cents and compares prices exactly as the engine's encoder
   does: low <= body bottom <= body top <= high, ties only on exact equality, direction from open and close.

   One query mixes the three ways of matching however the composer sets them:
     held relations (pins and the skeleton) must hold exactly on a window;
     stretch lets the drawn bars pick themselves out of a longer run of BTCUSDT bars, in order: the first
       drawn bar is the run's first bar, the last drawn bar its last, and up to `stretch` bars between
       them are skipped and ignored; the run itself never crosses a gap in the data;
     every candidate is ranked by how close it looks: first its colours (each bar whose direction differs
       costs a whole height, half against a doji), then its shape (both scaled to the same height, the mean
       distance of the bar ends, as a fraction of that height), then its sizes (each bar's body and range
       against the drawing's, as ratios, so a small body twice too big counts), plus a small charge for each
       comparison it flips. Flips (making or breaking a tie counts half) are still counted and shown: zero
       flips means the exact g1 pattern.

   What came next uses the engine's own definitions. The next bar rose or fell by the sign of
   close[t+1] - close[t] (the direction run's primary target, flat kept apart), and only when bar t+1
   follows bar t with no missing bar between them. ATR is the engine's ATR14: true range
   max(high - low, |high - previous close|, |low - previous close|) smoothed with Wilder's 1/14,
   seeded by the mean of the first 14 values and started again after any missing bar. */

const TF_NAMES = ['15m', '30m', '1h', '2h', '4h'];
// One display frame per worker task keeps replacement prompt while avoiding
// excessive task rescheduling on a busy host. The worker never paints the UI.
const WORK_SLICE_MS = 16;
let BARS = null, latest = 0, pending = null;
// what Composer reads about each bar beside its shape, once the activity has arrived (per timeframe, aligned with BARS)
let READ = null, pendingActivity = null, activityVersion = 0;

function decode(buffer) {
  const buf = new Uint8Array(buffer);
  let p = 0;
  const u8 = () => buf[p++];
  const u32 = () => { const x = (buf[p] | (buf[p + 1] << 8) | (buf[p + 2] << 16) | (buf[p + 3] << 24)) >>> 0; p += 4; return x; };
  const vu = () => { let x = 0, m = 1, b; do { b = buf[p++]; x += (b & 127) * m; m *= 128; } while (b & 128); return x; };
  const vz = () => { const x = vu(); return x % 2 ? -(x + 1) / 2 : x / 2; };
  if (String.fromCharCode(buf[0], buf[1], buf[2], buf[3], buf[4]) !== 'CBAR1') throw new Error('This is not Composer bar data.');
  p = 5;
  const out = [], count = u8();
  for (let k = 0; k < count; k++) {
    let name = '';
    for (let i = 0, len = u8(); i < len; i++) name += String.fromCharCode(u8());
    const sec = u32(), n = u32(), t0 = u32(), g = u32(), gaps = [];
    for (let i = 0; i < g; i++) gaps.push([u32(), u32()]);
    const O = new Int32Array(n), H = new Int32Array(n), L = new Int32Array(n), C = new Int32Array(n), ts = new Float64Array(n), run = new Int32Array(n);
    let gi = 0, missing = 0;
    for (let i = 0; i < n; i++) {
      let gap = false;
      if (gi < gaps.length && gaps[gi][0] === i) { missing += gaps[gi++][1]; gap = true; }
      ts[i] = t0 + (i + missing) * sec;
      run[i] = i === 0 || gap ? 1 : run[i - 1] + 1; // bars in an unbroken run ending here; windows never cross a gap
      O[i] = vz() + (i ? C[i - 1] : 0);
      C[i] = O[i] + vz();
      H[i] = Math.max(O[i], C[i]) + vu();
      L[i] = Math.min(O[i], C[i]) - vu();
    }
    if (p > buf.length) throw new Error('The bar data is truncated.');
    const atr = new Float64Array(n).fill(NaN);
    let count = 0, seed = 0, state = 0;
    for (let i = 0; i < n; i++) {
      if (run[i] < 2) { count = 0; seed = 0; state = 0; continue; } // no previous close after a gap: true range is undefined here
      const tr = Math.max(H[i] - L[i], Math.abs(H[i] - C[i - 1]), Math.abs(L[i] - C[i - 1]));
      if (count < 14) { seed += tr; count++; if (count === 14) { state = seed / 14; atr[i] = state; } }
      else { state = tr / 14 + (1 - 1 / 14) * state; atr[i] = state; }
    }
    out.push({ name, sec, n, ts, O, H, L, C, run, atr });
  }
  return out;
}

// what traded in each bar, served beside the bars: volume, quote volume (USDT) and trades as quantized natural logs,
// and the maker share of the volume (bars.py says how they are packed)
function decodeActivity(buffer) {
  const dv = new DataView(buffer);
  if (buffer.byteLength < 6 || String.fromCharCode(dv.getUint8(0), dv.getUint8(1), dv.getUint8(2), dv.getUint8(3), dv.getUint8(4)) !== 'CACT1') throw new Error('This is not Composer activity data.');
  let p = 5;
  const out = [], count = dv.getUint8(p++);
  for (let k = 0; k < count; k++) {
    let name = '';
    for (let i = 0, len = dv.getUint8(p++); i < len; i++) name += String.fromCharCode(dv.getUint8(p++));
    const n = dv.getUint32(p, true); p += 4;
    if (p + n * 2 * 4 + 48 > buffer.byteLength) throw new Error('The activity data is truncated.');
    const column = () => {
      const lo = dv.getFloat64(p, true), step = dv.getFloat64(p + 8, true), a = new Float64Array(n);
      p += 16;
      for (let i = 0; i < n; i++, p += 2) a[i] = Math.exp(lo + (dv.getUint16(p, true) - 1) * step);
      return a;
    };
    const vol = column(), quote = column(), trades = column(), maker = new Float64Array(n);
    for (let i = 0; i < n; i++, p += 2) maker[i] = dv.getUint16(p, true) / 65535;
    out.push({ name, n, vol, quote, trades, maker });
  }
  return out;
}

// What Composer reads about every bar, the way the cube explorer reads a cell: its volume, trades and trade size (USDT per
// trade) against the median of the eleven bars before it, the maker share of its volume, its range and body (open to close,
// either way: the colour already says which) in the ATR at the bar before it, and where it closed in the prior UTC day's range. The first three compare as ratios,
// so their means and spreads are taken over logs. Each timeframe also keeps every reading's count, sum and sum of
// squares over its whole history, for the comparison.
const READINGS = ['vol', 'trades', 'size', 'maker', 'range', 'body', 'day'];
const AS_LOG = [true, true, true, false, false, false, false];
function* readingsWork(T, A) {
  const n = T.n, R = {};
  if (A.n !== n) throw new Error(`The ${T.name} activity does not cover its bars.`);
  for (const key of READINGS) R[key] = new Float32Array(n).fill(NaN);
  const size = new Float64Array(n);
  for (let i = 0; i < n; i++) { size[i] = A.quote[i] / A.trades[i]; if ((i & 1023) === 1023) yield; }
  const w = new Float64Array(11);
  const median = (a, i) => { for (let j = 0; j < 11; j++) w[j] = a[i - 11 + j]; w.sort(); return w[5]; };
  for (let i = 0; i < n; i++) {
    R.maker[i] = A.maker[i];
    if (T.run[i] >= 12) { R.vol[i] = A.vol[i] / median(A.vol, i); R.trades[i] = A.trades[i] / median(A.trades, i); R.size[i] = size[i] / median(size, i); }
    const a = i ? T.atr[i - 1] : NaN;
    if (T.run[i] >= 2 && a > 0) { R.range[i] = (T.H[i] - T.L[i]) / a; R.body[i] = Math.abs(T.C[i] - T.O[i]) / a; }
    if ((i & 1023) === 1023) yield;
  }
  const days = new Map();
  for (let i = 0; i < n; i++) {
    const d = Math.floor(T.ts[i] / 86400), h = days.get(d);
    if (!h) days.set(d, [T.H[i], T.L[i]]);
    else { if (T.H[i] > h[0]) h[0] = T.H[i]; if (T.L[i] < h[1]) h[1] = T.L[i]; }
    if ((i & 1023) === 1023) yield;
  }
  for (let i = 0; i < n; i++) {
    const h = days.get(Math.floor(T.ts[i] / 86400) - 1);
    if (h && h[0] > h[1]) R.day[i] = (T.C[i] - h[1]) / (h[0] - h[1]);
    if ((i & 1023) === 1023) yield;
  }
  // Keep the exact log of each Float32 reading once, rather than repeating it
  // for every admitted placement in every search.
  R.features = []; R.base = [];
  for (let f = 0; f < READINGS.length; f++) {
    const values = AS_LOG[f] ? new Float64Array(n) : R[READINGS[f]];
    if (AS_LOG[f]) for (let i = 0; i < n; i++) { values[i] = Math.log(R[READINGS[f]][i]); if ((i & 1023) === 1023) yield; }
    R.features.push(values);
    let c = 0, sum = 0, sq = 0;
    for (let i = 0; i < n; i++) {
      const x = values[i]; if (x === x) { c++; sum += x; sq += x * x; }
      if ((i & 1023) === 1023) yield;
    }
    R.base.push([c, sum, sq]);
  }
  return R;
}
function readings(T, A) {
  const work = readingsWork(T, A); let step;
  do { step = work.next(); } while (!step.done);
  return step.value;
}
async function prepareReadings(tables, activity, current) {
  const prepared = []; let deadline = performance.now() + WORK_SLICE_MS;
  for (let k = 0; k < tables.length; k++) {
    const work = readingsWork(tables[k], activity[k]);
    for (;;) {
      const step = work.next();
      if (step.done) { prepared.push(step.value); break; }
      if (performance.now() >= deadline) {
        await tick(); if (!current()) return null;
        deadline = performance.now() + WORK_SLICE_MS;
      }
    }
  }
  return current() ? prepared : null;
}

// Grid's statistics: 95% intervals, Wilson for rates and t for means, and nothing for fewer than 30 windows
const Z95 = 1.959964;
function wilson(k, m) {
  if (m < 30) return null;
  const p = k / m, d = 1 + Z95 * Z95 / m, c = (p + Z95 * Z95 / (2 * m)) / d, h = Z95 * Math.sqrt(p * (1 - p) / m + Z95 * Z95 / (4 * m * m)) / d;
  return [p, c - h, c + h, m];
}
function tMean(c, sum, sq) {
  if (c < 30) return null;
  const m = sum / c, sd = Math.sqrt(Math.max(0, (sq - sum * sum / c) / (c - 1))), df = c - 1;
  // Student's t at 97.5% from its expansion in 1/df: within 0.001 of the table from 30 rows up
  const t = Z95 + (Z95 ** 3 + Z95) / (4 * df) + (5 * Z95 ** 5 + 16 * Z95 ** 3 + 3 * Z95) / (96 * df * df);
  const h = t * sd / Math.sqrt(c);
  return [m, m - h, m + h, c, sd];
}
// the one comparison in which a window differs from the drawing (W already filled): p * 3 + its relation + 1,
// or -1 when none or more than one differ
function oneAway(cq, W) {
  const A = cq.A, B = cq.B, R = cq.R, P = cq.P;
  let at = -1;
  for (let p = 0; p < P; p++) {
    const x = W[A[p]], y = W[B[p]], r = x < y ? -1 : x > y ? 1 : 0;
    if (r !== R[p]) { if (at >= 0) return -1; at = p * 3 + r + 1; }
  }
  return at;
}

// kinds of price a held relation can name: 0 open, 1 high, 2 low, 3 close, 4 body bottom, 5 body top
function priceOf(kind, o, h, l, c) {
  switch (kind) {
    case 0: return o; case 1: return h; case 2: return l; case 3: return c;
    case 4: return o < c ? o : c; default: return o < c ? c : o;
  }
}

// what the next bar did after a window ending at bar e, written into a reusable record
function outcomeInto(T, e, o) {
  if (e + 1 >= T.n) { o.why = 'end'; return o; }
  if (T.run[e + 1] < 2) { o.why = 'gap'; return o; }
  const move = T.C[e + 1] - T.C[e], a = T.atr[e];
  o.why = ''; o.dir = move > 0 ? 1 : move < 0 ? -1 : 0; o.bps = move / T.C[e] * 1e4; o.atrx = a > 0 ? move / a : NaN;
  return o;
}
function passes(o, f) {
  if (!f) return true;
  if (o.why) return false;
  if (f.measure === 'bps') return f.dir > 0 ? o.bps >= f.value : o.bps <= -f.value;
  if (f.measure === 'atr') return o.atrx === o.atrx && (f.dir > 0 ? o.atrx >= f.value : o.atrx <= -f.value);
  return o.dir === f.dir;
}

function compile(q) {
  const n = q.bars.length, E = new Float64Array(4 * n), D = new Int8Array(n), QN = new Float64Array(4 * n);
  q.bars.forEach(([o, h, l, c], i) => {
    E[4 * i] = l; E[4 * i + 1] = Math.min(o, c); E[4 * i + 2] = Math.max(o, c); E[4 * i + 3] = h;
    D[i] = c > o ? 1 : c < o ? -1 : 0;
  });
  let lo = Infinity, hi = -Infinity; for (const v of E) { if (v < lo) lo = v; if (v > hi) hi = v; }
  for (let i = 0; i < 4 * n; i++) QN[i] = (E[i] - lo) / (hi - lo || 1);
  // each bar's body and range as a share of the drawing's height, plus the size floor, logged for comparing as ratios
  const QB = new Float64Array(n), QR = new Float64Array(n);
  for (let i = 0; i < n; i++) { QB[i] = Math.log(QN[4 * i + 2] - QN[4 * i + 1] + SIZE_FLOOR); QR[i] = Math.log(QN[4 * i + 3] - QN[4 * i] + SIZE_FLOOR); }
  const P = (4 * n) * (4 * n - 1) / 2, A = new Int16Array(P), B = new Int16Array(P), R = new Int8Array(P);
  let p = 0;
  for (let a = 0; a < 4 * n; a++) for (let b = a + 1; b < 4 * n; b++) { A[p] = a; B[p] = b; R[p] = E[a] < E[b] ? -1 : E[a] > E[b] ? 1 : 0; p++; }
  // each held relation is checked as soon as the later of its two bars is placed
  const byBar = Array.from({ length: n }, () => []);
  q.holds.forEach(h => byBar[h.color ? h.bar : Math.max(h.a[0], h.b[0])].push(h));
  // the comparisons each bar settles (pairs whose later endpoint is on it), so flips can be counted while bars are placed
  const levels = Array.from({ length: n }, (_, g) => {
    const ix = []; for (let k = 0; k < P; k++) if (B[k] >> 2 === g) ix.push(k);
    return { A: Int16Array.from(ix, k => A[k]), B: Int16Array.from(ix, k => B[k]), R: Int8Array.from(ix, k => R[k]) };
  });
  return { n, oriented: q.oriented, D, QN, QB, QR, P, A, B, R, byBar, levels, holds: q.holds };
}

function holdOk(h, MO, MH, ML, MC) {
  if (h.color) { const x = MC[h.bar] - MO[h.bar]; return (x > 0 ? 1 : x < 0 ? -1 : 0) === h.dir; }
  const a = h.a[0], b = h.b[0];
  const va = priceOf(h.a[1], MO[a], MH[a], ML[a], MC[a]), vb = priceOf(h.b[1], MO[b], MH[b], ML[b], MC[b]);
  return (va < vb ? -1 : va > vb ? 1 : 0) === h.rel;
}

// comparisons that differ, in half-flips; returns -1 as soon as the count passes the bound
function flips(cq, MO, MH, ML, MC, W, bound) {
  const n = cq.n;
  let d = 0;
  for (let i = 0; i < n; i++) {
    const o = MO[i], c = MC[i];
    W[4 * i] = ML[i]; W[4 * i + 1] = o < c ? o : c; W[4 * i + 2] = o < c ? c : o; W[4 * i + 3] = MH[i];
    if (cq.oriented) { const s = c > o ? 1 : c < o ? -1 : 0, df = s - cq.D[i]; d += df < 0 ? -df : df; }
  }
  if (d > bound) return -1;
  const A = cq.A, B = cq.B, R = cq.R, P = cq.P;
  for (let p = 0; p < P; p++) {
    const x = W[A[p]], y = W[B[p]], df = (x < y ? -1 : x > y ? 1 : 0) - R[p];
    if (df !== 0) { d += df < 0 ? -df : df; if (d > bound) return -1; }
  }
  return d;
}

// one comparison flipped costs this much height in the ranking, spread over all comparisons of the composition
const FLIP_WEIGHT = 0.3;
// sizes compare as log ratios of (share of height + this floor): the floor is added, not a minimum, so a doji's size stays
// finite and thin bodies differ less than their raw ratio says, though not alike (a doji against a 2% body differs by
// ln 2, as two bodies twice apart do)
const SIZE_FLOOR = 0.02, SIZE_WEIGHT = 0.05;
// mean distance of the bar ends from the drawing's, both scaled to their own low..high (W already filled)
function shapeOf(cq, W) {
  const m = 4 * cq.n; let lo = Infinity, hi = -Infinity;
  for (let i = 0; i < m; i++) { const v = W[i]; if (v < lo) lo = v; if (v > hi) hi = v; }
  const span = hi - lo || 1, QN = cq.QN; let s = 0;
  for (let i = 0; i < m; i++) { const x = (W[i] - lo) / span - QN[i]; s += x < 0 ? -x : x; }
  return s / m;
}
// shape plus sizes: the mean distance of the bar ends, then each bar's body and range against the drawing's as ratios
function lookOf(cq, W) {
  const n = cq.n, m = 4 * n; let lo = Infinity, hi = -Infinity;
  for (let i = 0; i < m; i++) { const v = W[i]; if (v < lo) lo = v; if (v > hi) hi = v; }
  const span = hi - lo || 1, QN = cq.QN; let shape = 0, size = 0;
  for (let i = 0; i < m; i++) { const x = (W[i] - lo) / span - QN[i]; shape += x < 0 ? -x : x; }
  for (let i = 0; i < n; i++) {
    const b = Math.log((W[4 * i + 2] - W[4 * i + 1]) / span + SIZE_FLOOR) - cq.QB[i], r = Math.log((W[4 * i + 3] - W[4 * i]) / span + SIZE_FLOOR) - cq.QR[i];
    size += (b < 0 ? -b : b) + (r < 0 ? -r : r);
  }
  return shape / m + SIZE_WEIGHT * size / (2 * n);
}
// flipped comparisons between bar ends, in half-flips (W already filled); -1 once past the bound
function pairFlips(cq, W, bound) {
  const A = cq.A, B = cq.B, R = cq.R, P = cq.P; let d = 0;
  for (let p = 0; p < P; p++) { const x = W[A[p]], y = W[B[p]], df = (x < y ? -1 : x > y ? 1 : 0) - R[p]; if (df !== 0) { d += df < 0 ? -df : df; if (d > bound) return -1; } }
  return d;
}
// how close a placed window looks: colours, then shape and sizes, then a small charge per flip; -1 once past the bound
function closeness(cq, MO, MH, ML, MC, W, bound) {
  const n = cq.n; let c = 0;
  for (let i = 0; i < n; i++) {
    const o = MO[i], cl = MC[i];
    W[4 * i] = ML[i]; W[4 * i + 1] = o < cl ? o : cl; W[4 * i + 2] = o < cl ? cl : o; W[4 * i + 3] = MH[i];
    if (cq.oriented) { const sg = cl > o ? 1 : cl < o ? -1 : 0, df = sg - cq.D[i]; c += (df < 0 ? -df : df) / 2; }
  }
  if (c > bound) return -1;
  const sc = c + lookOf(cq, W);
  if (sc > bound) return -1;
  const d = pairFlips(cq, W, bound === Infinity ? Infinity : (bound - sc) * 2 * cq.P / FLIP_WEIGHT);
  return d < 0 ? -1 : sc + FLIP_WEIGHT * (d / 2) / cq.P;
}

// the M best candidates seen so far, worst on top
class Best {
  constructor(m) { this.m = m; this.d = []; this.v = []; }
  bound() { return this.d.length < this.m ? Infinity : this.d[0]; }
  push(d, v) {
    const D = this.d, V = this.v;
    if (D.length < this.m) {
      let i = D.length; D.push(d); V.push(v);
      while (i > 0) { const up = (i - 1) >> 1; if (D[up] >= D[i]) break; [D[up], D[i]] = [D[i], D[up]]; [V[up], V[i]] = [V[i], V[up]]; i = up; }
    } else if (d < D[0]) {
      D[0] = d; V[0] = v;
      let i = 0;
      for (;;) {
        const l = 2 * i + 1, r = l + 1; let top = i;
        if (l < D.length && D[l] > D[top]) top = l;
        if (r < D.length && D[r] > D[top]) top = r;
        if (top === i) break;
        [D[top], D[i]] = [D[i], D[top]]; [V[top], V[i]] = [V[i], V[top]]; i = top;
      }
    }
  }
  sorted() { return this.d.map((d, i) => ({ d, ...this.v[i] })).sort((a, b) => a.d - b.d || a.extra - b.extra || b.end - a.end); }
}

let tickChannel = null, tickWaiters = [];
function tick() {
  // Node's MessagePort can drain its own queue ahead of timers; its native
  // check-phase yield preserves the same replacement opportunity as a worker task.
  if (typeof setImmediate === 'function') return new Promise(resolve => setImmediate(resolve));
  if (!tickChannel) { tickChannel = new MessageChannel(); tickChannel.port1.onmessage = () => { const w = tickWaiters.shift(); if (w) w(); }; }
  return new Promise(r => { tickWaiters.push(r); tickChannel.port2.postMessage(0); });
}

async function search(q, id, report) {
  const read = READ, tables = BARS;
  const t0 = Date.now(), cq = compile(q), n = cq.n, held = q.holds.length > 0, stretch = held ? q.stretch : 0;
  const MO = new Float64Array(n), MH = new Float64Array(n), ML = new Float64Array(n), MC = new Float64Array(n), W = new Float64Array(4 * n);
  const picks = new Int32Array(n), exact = TF_NAMES.map(() => 0), counts = TF_NAMES.map(() => 0);
  const exactF = TF_NAMES.map(() => 0), countsF = TF_NAMES.map(() => 0);
  const f = q.next && q.next.dir ? q.next : null, oo = {}, o0 = {};
  const base = { n: 0, up: 0, down: 0, flat: 0, pass: 0 }, split = { n: 0, up: 0, down: 0, flat: 0, none: 0 };
  const best = new Best(Math.max(400, q.x * 40));
  const total = tables.reduce((a, T) => a + T.n, 0);
  let done = 0, sinceTick = 0, deadline = performance.now() + WORK_SLICE_MS;

  // The panes: the set of windows that match (exact twins with nothing held, the windows that hold otherwise, on the
  // timeframes shown and through the next-bar filter), summed as they are found. For each drawn bar, the readings of the
  // BTCUSDT bar it took; the next bar; and what the next six bars did in the shape's own scale (its low 0, its high 1),
  // with a fixed-seed sample of their closes for the fan.
  const NR = READINGS.length, AFTER = 6, SAMPLE = 20000;
  let acc = new Float64Array(n * NR * 3), setN = 0, setTf = TF_NAMES.map(() => [0, 0]);
  let fan = new Float32Array(SAMPLE * AFTER), cont = [0, 0, 0, 0], seed = 0x9e3779b9;
  let sequences = new Map();
  const rand = () => { seed = (seed + 0x6d2b79f5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  let batchPrefix = false, prefixWeight = 0;
  const firstOnly = cq.holds.every(h => h.color ? h.bar === 0 : h.a[0] === 0 && h.b[0] === 0);
  const addSet = (k, T, s, ps, e, o) => {
    setN++; if (batchPrefix) prefixWeight++;
    const R = read && read[k];
    if (R) {
      for (let g = 0; g < n; g++) {
        if (batchPrefix && g < n - 1) continue;
        const j = s + (ps ? ps[g] : g);
        for (let r = 0; r < NR; r++) {
          // where a window closed in the prior day's range is read on its last bar only
          if (r === NR - 1 && g !== n - 1) continue;
          const x = R.features[r][j];
          if (x !== x) continue;
          const a = (g * NR + r) * 3;
          acc[a]++; acc[a + 1] += x; acc[a + 2] += x * x;
        }
      }
    }
    if (!o.why) { setTf[k][0]++; if (o.dir > 0) setTf[k][1]++; }
    if (e + AFTER >= T.n || T.run[e + AFTER] < AFTER + 1) return;
    let lo = Infinity, hi = -Infinity;
    for (let g = 0; g < n; g++) { const j = s + (ps ? ps[g] : g); if (T.L[j] < lo) lo = T.L[j]; if (T.H[j] > hi) hi = T.H[j]; }
    if (!(hi > lo)) return;
    const m = ++cont[0];
    let up = false, down = false, sequenceCode = 0;
    for (let j = 1; j <= AFTER; j++) {
      if (T.H[e + j] > hi) up = true;
      if (T.L[e + j] < lo) down = true;
      // Classify exact integer prices before scaling: a close on either boundary is inside.
      sequenceCode = sequenceCode * 3 + (T.C[e + j] > hi ? 0 : T.C[e + j] < lo ? 2 : 1);
    }
    let sequence = sequences.get(sequenceCode);
    if (!sequence) {
      let code = sequenceCode, key = '';
      for (let j = 0; j < AFTER; j++) { key = 'UID'[code % 3] + key; code = Math.floor(code / 3); }
      const scale = v => (v - lo) / (hi - lo);
      const bars = Array.from({ length: AFTER }, (_, j) => [T.O[e + j + 1], T.H[e + j + 1], T.L[e + j + 1], T.C[e + j + 1]].map(scale));
      sequence = { key, n: 0, bars, start: scale(T.C[e]) };
      sequences.set(sequenceCode, sequence);
    }
    sequence.n++;
    if (up) cont[1]++;
    if (down) cont[2]++;
    if (T.C[e + AFTER] > T.C[e]) cont[3]++;
    const slot = m <= SAMPLE ? m - 1 : Math.floor(rand() * m);
    if (slot < SAMPLE) for (let j = 1; j <= AFTER; j++) fan[slot * AFTER + j - 1] = (T.C[e + j] - lo) / (hi - lo);
  };
  // one comparison away: windows of the drawing's length, with its colours, that differ from it in a single comparison
  const near = new Map();

  // held relations, with stretch: drawn bar g takes bar pos + skip, and the skipped bars are ignored.
  let T = null, s = 0, bestHere = null, on = false, any = false;
  const windowBest = { d: Infinity, picks: new Int32Array(n), extra: 0, span: 0 };
  // Every placement ends at the same candle. A hold against that endpoint can
  // reject a branch as soon as its other endpoint is placed, without waiting
  // through all intervening combinations. The normal final hold check remains.
  const endHolds=Array.from({length:n},()=>[]);
  for(const h of cq.holds)if(!h.color){const a=h.a[0],b=h.b[0];if(Math.max(a,b)===n-1&&a!==b)endHolds[Math.min(a,b)].push(h);}
  const endGroups=endHolds.flatMap((holds,g)=>holds.length?[{g,holds}]:[]),endLimits=endGroups.length?new Int32Array(n):null;
  const fits = (g, pos, skip) => {
    const last = pos + skip;
    if (last >= T.n || T.run[last] < last - s + 1) return -1;
    MO[g] = T.O[last]; MH[g] = T.H[last]; ML[g] = T.L[last]; MC[g] = T.C[last]; picks[g] = last - s;
    for (const h of cq.byBar[g]) if (!holdOk(h, MO, MH, ML, MC)) return 0;
    for (const h of endHolds[g]) if (!holdOk(h, MO, MH, ML, MC)) return 0;
    return 1;
  };
  // A window with stretch runs from start s to a chosen last bar e: the first drawn bar sits on s, the last on e,
  // and spare is exactly how many bars between them are skipped. `exists` settles whether any placement holds;
  // `closest` then finds the closest-looking placement. Colours and flips are counted bar by bar while placing and
  // only add to the score, so a placement already past the best it could still beat is dropped there; shape and
  // sizes are added once all bars are placed.
  // Minimum remaining colour cost over every legal skipped-bar placement.
  // This is an admissible bound: cross-bar holds and shape costs only add work
  // or nonnegative score. Store half-colour units in compact byte columns.
  let colourBounds = null;
  async function boundColours() {
    const columns = Array.from({ length: n }, () => Array(stretch + 1));
    for (let g = n - 1; g >= 0; g--) {
      const local = cq.byBar[g].filter(h => h.color || h.a[0] === h.b[0]);
      const own = new Uint8Array(T.n);
      for (let i = 0; i < T.n; i++) {
        if ((i & 1023) === 0 && performance.now() >= deadline) {
          await tick(); if (id !== latest) return null; deadline = performance.now() + WORK_SLICE_MS; report(done / total);
        }
        const o = T.O[i], c = T.C[i];
        own[i] = cq.oriented ? Math.abs((c > o ? 1 : c < o ? -1 : 0) - cq.D[g]) : 0;
        if (local.length) {
          MO[g] = o; MH[g] = T.H[i]; ML[g] = T.L[i]; MC[g] = c;
          for(const h of local)if(!holdOk(h,MO,MH,ML,MC)){own[i]=255;break;}
        }
      }
      // Successive spare counts share a diagonal minimum. This avoids scanning
      // all possible skips again for each DP cell.
      const tails = [new Uint8Array(T.n), new Uint8Array(T.n)];
      for (let spare = 0; spare <= stretch; spare++) {
        const column = columns[g][spare] = new Uint8Array(T.n).fill(255), tail = tails[spare % 2].fill(255);
        if (g === n - 1 && spare) continue;
        const end = T.n - (n - g - 1) - spare;
        for (let i = 0; i < end; i++) {
          if ((i & 1023) === 0 && performance.now() >= deadline) {
            await tick(); if (id !== latest) return null; deadline = performance.now() + WORK_SLICE_MS; report(done / total);
          }
          const rest = g === n - 1 ? 0 : Math.min(columns[g + 1][spare][i + 1], spare ? tails[(spare - 1) % 2][i + 1] : 255);
          tail[i] = rest;
          if (own[i] !== 255 && rest !== 255) column[i] = rest + own[i];
        }
      }
    }
    return columns;
  }
  // An explicit DFS can suspend inside a single expensive window. Its traversal
  // order is the original recursive order, including the first admitted picks
  // used by the cohort, and its score/tie handling is unchanged.
  const positions = new Int32Array(n), spares = new Int32Array(n), skips = new Int32Array(n);
  const colours = new Float64Array(n), differences = new Float64Array(n);
  let depth = 0, nodes = 0;
  function beginPlacement(extra,prepare=true) {
    const end=s+n-1+extra;MO[n-1]=T.O[end];MH[n-1]=T.H[end];ML[n-1]=T.L[end];MC[n-1]=T.C[end];
    if(endLimits&&prepare){
      endLimits.fill(extra);
      for(const {g,holds}of endGroups){
        let last=-1;
        for(let skip=0;skip<=(g?extra:0);skip++){
          const at=s+g+skip;MO[g]=T.O[at];MH[g]=T.H[at];ML[g]=T.L[at];MC[g]=T.C[at];
          let valid=true;for(const h of holds)if(!holdOk(h,MO,MH,ML,MC)){valid=false;break;}
          if(valid)last=skip;
        }
        if(last<0)return false;
        // Skips cannot be undone. Earlier bars cannot pass the last feasible
        // position of any later endpoint held against this window's end.
        for(let before=0;before<=g;before++)endLimits[before]=Math.min(endLimits[before],last);
      }
    }
    depth = 0; positions[0] = s; spares[0] = extra; skips[0] = 0; colours[0] = differences[0] = 0;
    return true;
  }
  function place(scoring) {
    while (depth >= 0) {
      if ((++nodes & 127) === 0 && performance.now() >= deadline) return true;
      const g = depth, spare = spares[g], skip = skips[g]++;
      if (skip > (g === 0 ? 0 : spare)) { depth--; continue; }
      const last = positions[g] + skip;
      if(endLimits&&last-s-g>endLimits[g]){depth--;continue;}
      if (colourBounds) {
        const lower = colourBounds[g][spare - skip]?.[last] ?? 255;
        if (lower === 255 || scoring && colours[g] + lower / 2 + FLIP_WEIGHT * differences[g] / (2 * cq.P) > Math.min(best.bound(), bestHere ? bestHere.d : Infinity)) continue;
      }
      const ok = fits(g, positions[g], skip);
      if (ok < 0) { depth--; continue; }
      if (!ok) continue;
      let c = colours[g], d = differences[g];
      if (scoring) {
        const o = MO[g], cl = MC[g];
        W[4 * g] = ML[g]; W[4 * g + 1] = Math.min(o, cl); W[4 * g + 2] = Math.max(o, cl); W[4 * g + 3] = MH[g];
        if (cq.oriented) c += Math.abs((cl > o ? 1 : cl < o ? -1 : 0) - cq.D[g]) / 2;
        const lv = cq.levels[g];
        for (let k = 0; k < lv.A.length; k++) { const x = W[lv.A[k]], y = W[lv.B[k]]; d += Math.abs((x < y ? -1 : x > y ? 1 : 0) - lv.R[k]); }
        const floor = c + FLIP_WEIGHT * d / (2 * cq.P), limit = Math.min(best.bound(), bestHere ? bestHere.d : Infinity);
        if (floor > limit) continue;
        if (g === n - 1) {
          const score = floor + lookOf(cq, W);
          if (score < limit) { windowBest.d = score; windowBest.picks.set(picks); windowBest.extra = last - s + 1 - n; windowBest.span = last - s + 1; bestHere = windowBest; }
          continue;
        }
      } else if (g === n - 1) { any = true; depth = -1; return false; }
      const child = g + 1, remaining = spare - skip;
      positions[child] = last + 1; spares[child] = remaining;
      skips[child] = child === n - 1 ? remaining : 0;
      colours[child] = c; differences[child] = d; depth = child;
    }
    return false;
  }

  for (let k = 0; k < tables.length; k++) {
    T = tables[k]; on = !!q.tfs[k];
    colourBounds = null;
    if (on && held && stretch && n > 2) {
      colourBounds = await boundColours(); if (id !== latest) return null;
    }
    for (s = 0; s + n <= T.n; s++) {
      if ((++sinceTick & 255) === 0 && performance.now() >= deadline) {
        await tick(); deadline = performance.now() + WORK_SLICE_MS;
        if (id !== latest) return null;
        report(done / total);
      }
      done++;
      if (T.run[s + n - 1] < n) continue;
      for (let i = 0; i < n; i++) { MO[i] = T.O[s + i]; MH[i] = T.H[s + i]; ML[i] = T.L[s + i]; MC[i] = T.C[s + i]; }
      // the whole history's own rate, for comparison: every window of this length on the timeframes shown
      outcomeInto(T, s + n - 1, o0);
      const pass0 = passes(o0, f);
      if (on && !o0.why) { base.n++; if (o0.dir > 0) base.up++; else if (o0.dir < 0) base.down++; else base.flat++; if (f && pass0) base.pass++; }
      // exact twins of the whole pattern are the windows with no flips at all
      if (flips(cq, MO, MH, ML, MC, W, 0) === 0) { exact[k]++; if (pass0) { exactF[k]++; if (on && !held) addSet(k, T, s, null, s + n - 1, o0); } }
      if (on) {
        let same = true;
        if (cq.oriented) for (let g = 0; g < n && same; g++) same = (MC[g] > MO[g] ? 1 : MC[g] < MO[g] ? -1 : 0) === cq.D[g];
        const at = same ? oneAway(cq, W) : -1;
        if (at >= 0) {
          let v = near.get(at);
          if (!v) near.set(at, v = { n: 0, out: 0, up: 0, look: Infinity, k: 0, s: 0 });
          v.n++;
          if (!o0.why) { v.out++; if (o0.dir > 0) v.up++; }
          const look = lookOf(cq, W);
          if (look < v.look) { v.look = look; v.k = k; v.s = s; }
        }
      }
      if (!held) {
        // nothing held: rank every window that passes the next-bar filter by how close it looks
        if (on && pass0) { const sc = closeness(cq, MO, MH, ML, MC, W, best.bound()); if (sc >= 0) best.push(sc, { k, s, picks: null, extra: 0, span: n, end: T.ts[s + n - 1] }); }
        continue;
      }
      // each run from this start to a possible last bar is its own window: it holds when some placement between its
      // ends does, its next bar is the one after that run, and the counts, rates and instance all describe it
      batchPrefix = firstOnly && on && !!read && stretch > 0; prefixWeight = 0;
      for (let extra = 0; extra <= stretch; extra++) {
        const e = s + n - 1 + extra;
        if (e >= T.n || T.run[e] < e - s + 1) break;
        bestHere = null; any = false;
        if(!beginPlacement(extra))continue;
        while (place(false)) { await tick(); if (id !== latest) return null; deadline = performance.now() + WORK_SLICE_MS; report(done / total); }
        if (!any) continue;
        counts[k]++;
        outcomeInto(T, e, oo);
        if (on) { split.n++; if (oo.why) split.none++; else if (oo.dir > 0) split.up++; else if (oo.dir < 0) split.down++; else split.flat++; }
        if (!passes(oo, f)) continue;
        countsF[k]++;
        if (on) {
          addSet(k, T, s, picks, e, oo);
          beginPlacement(extra,false);
          while (place(true)) { await tick(); if (id !== latest) return null; deadline = performance.now() + WORK_SLICE_MS; report(done / total); }
          if (bestHere) best.push(bestHere.d, { k, s, picks: Array.from(bestHere.picks), extra, span: n + extra, end: T.ts[e] });
        }
      }
      // With holds only on the first bar, every admitted span chooses the same
      // unskipped prefix. Accumulate its repeated readings once with that count;
      // endpoint readings, outcomes, fan sampling and ranking keep traversal order.
      if (batchPrefix && prefixWeight) {
        const R = read[k];
        for (let g = 0; g < n - 1; g++) for (let r = 0; r < NR - 1; r++) {
          const x = R.features[r][s + g]; if (x !== x) continue;
          const a = (g * NR + r) * 3;
          acc[a] += prefixWeight; acc[a + 1] += x * prefixWeight; acc[a + 2] += x * x * prefixWeight;
        }
      }
      batchPrefix = false;
    }
  }

  let mode = held ? 'held' : 'nearest';
  let ranked = best.sorted();
  if (held && countsF.every(c => c === 0)) {
    // nothing holds everything (and passes the next-bar filter): show the nearest windows that pass, each with the relations it breaks
    mode = 'fallback';
    const near = new Best(Math.max(400, q.x * 40));
    for (let k = 0; k < tables.length; k++) {
      if (!q.tfs[k]) continue;
      T = tables[k];
      for (s = 0; s + n <= T.n; s++) {
        if ((++sinceTick & 255) === 0 && performance.now() >= deadline) { await tick(); if (id !== latest) return null; deadline = performance.now() + WORK_SLICE_MS; }
        if (T.run[s + n - 1] < n) continue;
        if (f && !passes(outcomeInto(T, s + n - 1, o0), f)) continue;
        for (let i = 0; i < n; i++) { MO[i] = T.O[s + i]; MH[i] = T.H[s + i]; ML[i] = T.L[s + i]; MC[i] = T.C[s + i]; }
        const sc = closeness(cq, MO, MH, ML, MC, W, near.bound());
        if (sc >= 0) near.push(sc, { k, s, picks: null, extra: 0, span: n, end: T.ts[s + n - 1] });
      }
    }
    ranked = near.sorted();
  }

  // with nothing held, or nothing holding, and fewer than 30 exact twins, the set is the closest windows instead
  let setKind = held && mode === 'held' ? 'hold' : 'twins';
  if (setN < 30 && setKind === 'twins' || mode === 'fallback') {
    acc = new Float64Array(n * NR * 3); setN = 0; setTf = TF_NAMES.map(() => [0, 0]); fan = new Float32Array(SAMPLE * AFTER); cont = [0, 0, 0, 0]; seed = 0x9e3779b9; sequences = new Map();
    for (const r of ranked) { const R = tables[r.k], e = r.s + r.span - 1; addSet(r.k, R, r.s, r.picks, e, outcomeInto(R, e, oo)); }
    setKind = 'closest';
  }
  const panes = { kind: setKind, n: setN, readings: !!read, rows: [], next: null, byTf: setTf.map(([m, k]) => wilson(k, m)), tfN: setTf.map(([m]) => m), after: AFTER, cont: null, near: [] };
  if (read) {
    for (let g = 0; g < n; g++) for (let r = 0; r < NR; r++) {
      if (r === NR - 1 && g !== n - 1) continue;
      const a = (g * NR + r) * 3, set = tMean(acc[a], acc[a + 1], acc[a + 2]);
      let c = 0, sum = 0, sq = 0;
      for (let k = 0; k < BARS.length; k++) if (q.tfs[k]) { const b = read[k].base[r]; c += b[0]; sum += b[1]; sq += b[2]; }
      const all = tMean(c, sum, sq);
      if (set && all) panes.rows.push({ bar: g, key: READINGS[r], log: AS_LOG[r], set, all, d: all[4] > 0 ? (set[0] - all[0]) / all[4] : 0 });
    }
  }
  const outs = setTf.reduce((a, [m, k]) => [a[0] + m, a[1] + k], [0, 0]);
  panes.next = wilson(outs[1], outs[0]);
  if (cont[0] >= 30) {
    const m = Math.min(cont[0], SAMPLE), col = new Float32Array(m), qs = [];
    for (let j = 0; j < AFTER; j++) {
      for (let i = 0; i < m; i++) col[i] = fan[i * AFTER + j];
      col.sort();
      qs.push([0.1, 0.25, 0.5, 0.75, 0.9].map(p => col[Math.round(p * (m - 1))]));
    }
    const ordered = [...sequences.values()].sort((a, b) => b.n - a.n || a.key.localeCompare(b.key));
    panes.cont = {
      n: cont[0], sampled: m, fan: qs,
      aboveHigh: wilson(cont[1], cont[0]), belowLow: wilson(cont[2], cont[0]), aboveClose: wilson(cont[3], cont[0]),
      // At most 3^6 mutually exclusive sequences. Counts cover every complete window, not the fan sample.
      sequences: ordered.map(({ key, n }) => [key, n]),
      paths: ordered.slice(0, 4).map(s => ({ ...s, rate: wilson(s.n, cont[0]) })),
      examples: Object.fromEntries(ordered.map(({ key, bars, start }) => [key, { bars, start }])),
    };
  }
  panes.near = [...near].sort((a, b) => b[1].n - a[1].n).slice(0, 6).map(([at, v]) => {
    const p = Math.floor(at / 3), R = tables[v.k], bars = [];
    for (let g = 0; g < n; g++) { const j = v.s + g; bars.push([R.O[j] / 100, R.H[j] / 100, R.L[j] / 100, R.C[j] / 100]); }
    return { a: cq.A[p], b: cq.B[p], was: cq.R[p], rel: at % 3 - 1, n: v.n, up: wilson(v.up, v.out), bars };
  });

  // distinct moments: skip anything overlapping an earlier pick in time, on any timeframe
  const chosen = [], spans = [];
  for (const r of ranked) {
    const R = tables[r.k], a = R.ts[r.s], b = R.ts[r.s + r.span - 1] + R.sec;
    if (spans.some(([x, y]) => a < y && b > x)) continue;
    spans.push([a, b]); chosen.push(r);
    if (chosen.length >= q.x) break;
  }
  const results = chosen.map(r => {
    const R = tables[r.k], raw = [], drawn = [], ps = r.picks || Array.from({ length: n }, (_, i) => i);
    for (let i = 0; i < r.span; i++) { const j = r.s + i; raw.push([R.O[j] / 100, R.H[j] / 100, R.L[j] / 100, R.C[j] / 100]); }
    for (let g = 0; g < n; g++) {
      const j = r.s + ps[g];
      MO[g] = R.O[j]; MH[g] = R.H[j]; ML[g] = R.L[j]; MC[g] = R.C[j];
      drawn.push(raw[ps[g]]);
    }
    const broken = mode === 'fallback' ? q.holds.map((h, i) => (holdOk(h, MO, MH, ML, MC) ? -1 : i)).filter(i => i >= 0) : [];
    const flipped = flips(cq, MO, MH, ML, MC, W, Infinity) / 2, off = shapeOf(cq, W);
    const e = r.s + r.span - 1, o = outcomeInto(R, e, {});
    const next = o.why ? null : { dir: o.dir, bps: o.bps, atrx: o.atrx, bar: [R.O[e + 1] / 100, R.H[e + 1] / 100, R.L[e + 1] / 100, R.C[e + 1] / 100] };
    return { tf: TF_NAMES[r.k], start: R.ts[r.s], end: R.ts[e] + R.sec, flips: flipped, off, score: r.d, extra: r.extra, picks: ps, raw, drawn, broken, next, nextWhy: o.why };
  });
  return { mode, exact, exactF, counts, countsF, split, base, filter: f, results, holds: q.holds.length, stretch, panes, ms: Date.now() - t0 };
}

if (typeof self !== 'undefined' && typeof self.postMessage === 'function' && typeof window === 'undefined') {
  const memo = new Map();
  const run = async m => {
    const read = READ, tables = BARS, key = JSON.stringify([!!read,m.q]);
    if (memo.has(key)) { if (m.id === latest) self.postMessage({type:'result',id:m.id,...memo.get(key),ms:0}); return; }
    const r = await search(m.q, m.id, f => self.postMessage({ type: 'progress', id: m.id, f }));
    if (r) { if (read === READ && tables === BARS) { if(memo.size>=6)memo.delete(memo.keys().next().value);memo.set(key,r); } self.postMessage({ type: 'result', id: m.id, ...r }); }
  };
  self.onmessage = async e => {
    const m = e.data;
    if (m.type === 'bars') {
      try {
        BARS = decode(m.buffer); READ = null; activityVersion++; memo.clear();
        self.postMessage({ type: 'ready', bars: BARS.reduce((a, T) => a + T.n, 0), from: BARS[0].ts[0], to: BARS[0].ts[BARS[0].n - 1] + BARS[0].sec });
        if (pendingActivity) { const a = pendingActivity; pendingActivity = null; self.onmessage({ data: { type: 'activity', buffer: a } }); }
        if (pending) { const p = pending; pending = null; run(p); }
      } catch (err) { self.postMessage({ type: 'error', message: String(err.message || err) }); }
      return;
    }
    if (m.type === 'activity') {
      if (!BARS) { pendingActivity = m.buffer; return; }
      const tables = BARS, version = ++activityVersion;
      try {
        const A = decodeActivity(m.buffer);
        if (A.length !== tables.length) throw new Error('The activity does not cover every timeframe.');
        const prepared = await prepareReadings(tables, A, () => version === activityVersion && tables === BARS);
        if (!prepared) return;
        READ = prepared; memo.clear();
        self.postMessage({ type: 'readings' });
      } catch (err) { if (version === activityVersion && tables === BARS) self.postMessage({ type: 'readings-error', message: String(err.message || err) }); }
      return;
    }
    if (m.type === 'named-pattern') {
      try {
        if (!globalThis.CandlePatterns) importScripts(m.catalogURL);
        const p = CandlePatterns.resolve(m.pattern);
        const T = BARS?.find(t => t.name === m.timeframe);
        if (!p || !T) throw new Error('Pattern or timeframe unavailable in the recording.');
        const test = CandlePatterns.compile(p.id), samples = [];
        let count = 0, eligible = 0;
        for (let i = T.n - 1; i >= 0; i--) {
          if (T.run[i] < p.bars) continue;
          eligible++;
          if (!test(T.O,T.H,T.L,T.C,i)) continue;
          count++;
          if (samples.length < 8) {
            const bars = [];
            for (let j = i-p.bars+1; j <= i; j++) bars.push([T.O[j],T.H[j],T.L[j],T.C[j]]);
            samples.push({close: T.ts[i] + T.sec, bars});
          }
        }
        self.postMessage({type:'named-pattern', id:m.id, count, eligible, samples});
      } catch (err) {
        self.postMessage({type:'named-pattern', id:m.id, error:String(err.message || err)});
      }
      return;
    }
    if (m.type === 'query') {
      latest = m.id;
      if (!BARS) { pending = m; return; }
      run(m);
    }
  };
}
