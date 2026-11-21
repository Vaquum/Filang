// The bench canvas. Columns are bars relative to the pattern's deciding close; each lane is one
// population of recorded closes, drawn as its median candles or as the share of closes that traded each price row.
import { rec, pct } from '/shared/filang.js';
import { s } from '/shared/chart.js';
import { sceneFor } from './motion.js';

const cache = new Map();
const quant = (arr, m, f) => { if (!m) return null; const x = (m - 1) * f; const a = Math.floor(x); const b = Math.min(m - 1, a + 1); return arr[a] + (arr[b] - arr[a]) * (x - a); };
export const barsOf = (text) => { const n = parseFloat(text); return Math.round(text.endsWith('d') ? n * 96 : text.endsWith('h') ? n * 4 : n / 15); };
export const offsetLabel = (k) => { const m = Math.abs(k) * 15; const t = m % 60 === 0 ? m / 60 + 'H' : m + 'M'; return k === 0 ? 'CLOSE' : (k > 0 ? '+' : '−') + t; };
export const unitText = (v, unit) => (v === null || v === undefined ? '—' : unit === 'range' ? (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(2) + ' R' : pct(v));

/** Per-column medians for a population of anchor slots. Values are measured from the anchor close. */
export function aggregate(key, slots, lead, H, unit) {
  const id = `${key}|${lead}|${H}|${unit}`;
  if (cache.has(id)) return cache.get(id);
  const R = rec(); const n = slots.length;
  const o = new Float64Array(n); const hi = new Float64Array(n); const lo = new Float64Array(n); const c = new Float64Array(n); const rg = new Float64Array(n);
  const cols = [];
  for (let k = -lead; k <= H; k++) {
    let m = 0; let up = 0;
    for (let q = 0; q < n; q++) {
      const i = slots[q]; const j = i + k;
      if (j < 0 || j >= R.n || !R.present[j] || !R.present[i]) continue;
      const base = R.C[i]; const u = unit === 'range' ? R.H[i] - R.L[i] : base;
      if (u <= 0) continue;
      o[m] = (R.O[j] - base) / u; hi[m] = (R.H[j] - base) / u; lo[m] = (R.L[j] - base) / u; c[m] = (R.C[j] - base) / u; rg[m] = (R.H[j] - R.L[j]) / base;
      if (R.C[j] > base) up++;
      m++;
    }
    const srt = (a) => a.subarray(0, m).slice().sort();
    const sc = srt(c); const sl = srt(lo); const sh = srt(hi);
    cols.push({ k, n: m, o: quant(srt(o), m, 0.5), h: quant(sh, m, 0.5), l: quant(sl, m, 0.5), c: quant(sc, m, 0.5),
      q1: quant(sc, m, 0.25), q3: quant(sc, m, 0.75), lo10: quant(sl, m, 0.1), hi90: quant(sh, m, 0.9), up: m ? up / m : null, rng: quant(srt(rg), m, 0.5) });
  }
  const out = { cols, n, slots, single: false };
  if (cache.size > 400) cache.delete(cache.keys().next().value);
  cache.set(id, out);
  return out;
}

/** The recorded candles around one close, on the same axes. */
export function caseColumns(i, lead, H, unit) {
  const R = rec(); const base = R.C[i]; const u = unit === 'range' ? Math.max(1, R.H[i] - R.L[i]) : base; const cols = [];
  for (let k = -lead; k <= H; k++) {
    const j = i + k;
    if (j < 0 || j >= R.n || !R.present[j]) { cols.push({ k, n: 0 }); continue; }
    const v = (x) => (x - base) / u;
    cols.push({ k, n: 1, o: v(R.O[j]), h: v(R.H[j]), l: v(R.L[j]), c: v(R.C[j]), q1: null, q3: null, lo10: v(R.L[j]), hi90: v(R.H[j]), up: R.C[j] > base ? 1 : 0, rng: (R.H[j] - R.L[j]) / base });
  }
  return { cols, n: 1, slots: [i], single: true };
}

export function domainOf(aggs, wide) {
  let lo = 0; let hi = 0;
  for (const a of aggs) for (const col of a.cols) {
    if (!col.n) continue;
    const l = wide || a.single ? col.lo10 : Math.min(col.l, col.q1 ?? col.l); const u = wide || a.single ? col.hi90 : Math.max(col.h, col.q3 ?? col.h);
    if (l < lo) lo = l; if (u > hi) hi = u;
  }
  const pad = (hi - lo) * 0.1 || 0.001;
  return [lo - pad, hi + pad];
}

const frame = (host, H) => { const W = Math.max(120, Math.floor(host.clientWidth)); const svg = s('svg', { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: 'img' }); host.replaceChildren(svg); return { svg, W }; };
/** Column geometry. The pattern's own bars get wider columns, so the pattern stays the largest thing on the canvas. */
export function geom(W, lead, H, pbars) {
  const n = lead + H + 1; const wide = Math.max(4, Math.min(14, 88 / ((W - 26) / n))); const weights = []; let total = 0;
  for (let q = 0; q < n; q++) { const k = q - lead; const w = k > -pbars && k <= 0 ? wide : 1; weights.push(w); total += w; }
  const padL = 12; const padR = 14; const unit = (W - padL - padR) / total; const left = []; let acc = 0;
  for (let q = 0; q < n; q++) { left.push(padL + acc * unit); acc += weights[q]; }
  return { n, unit, x: (k) => left[k + lead] + (weights[k + lead] * unit) / 2, x0: (k) => left[k + lead], w: (k) => weights[k + lead] * unit,
    band: [left[lead - pbars + 1], left[lead] + weights[lead] * unit], at: (px) => { let q = 0; while (q < n - 1 && px >= left[q + 1]) q++; return q - lead; } };
}
export const columnAt = (host, clientX, lead, H, pbars) => { const r = host.getBoundingClientRect(); return geom(r.width, lead, H, pbars).at(clientX - r.left); };

const f1 = (v) => (Math.round(v * 10) / 10);
const setLineX = (el, v) => { el.setAttribute('x1', f1(v[0])); el.setAttribute('x2', f1(v[0])); el.setAttribute('y2', f1(v[1])); };
const setLineY = (el, v) => { el.setAttribute('x1', f1(v[0])); el.setAttribute('x2', f1(v[1])); el.setAttribute('y1', f1(v[2])); el.setAttribute('y2', f1(v[2])); };
const setRect = (el, v) => { el.setAttribute('x', f1(v[0])); el.setAttribute('y', f1(v[1])); el.setAttribute('width', f1(Math.max(0, v[2]))); el.setAttribute('height', f1(Math.max(0, v[3]))); };
const setPoints = (el, v) => { let t = ''; for (let i = 0; i < v.length; i += 2) t += `${f1(v[i])},${f1(v[i + 1])} `; el.setAttribute('points', t); };
// A candle's geometry: centre x, wick top, wick bottom, body top, body bottom, body width.
const setCandle = (el, v) => {
  const wick = el.firstChild; const body = el.lastChild;
  wick.setAttribute('x1', f1(v[0])); wick.setAttribute('x2', f1(v[0])); wick.setAttribute('y1', f1(v[1])); wick.setAttribute('y2', f1(v[2]));
  body.setAttribute('x', f1(v[0] - v[5] / 2)); body.setAttribute('y', f1(v[3])); body.setAttribute('width', f1(Math.max(1, v[5]))); body.setAttribute('height', f1(Math.max(1, v[4] - v[3])));
};

/**
 * One lane of the canvas. The pattern band is a lens: its bars are fitted to the lane's height on their own
 * printed scale, so the pattern is always the largest drawing. Lead-in and aftermath share the common scale.
 * Marks persist between redraws and move to their new places on a spring; labels are set at once.
 */
export function drawLane(host, { agg, domain, lead, H, pbars, horizons, mode, unit, height, scale = false }) {
  const W = Math.max(120, Math.floor(host.clientWidth));
  const sc = sceneFor(host, ['back', 'cells', 'fan', 'candles', 'lines', 'text']); sc.size(W, height);
  const g0 = geom(W, lead, H, pbars); const ncol = g0.n; const padT = 9; const padB = 15; const inner = height - padT - padB;
  const x = g0.x; const cols = agg.cols; const inBand = (k) => k > -pbars && k <= 0;
  const bandCols = cols.filter((c) => inBand(c.k) && c.n);
  const dense = mode === 'density' && !agg.single;
  let bl = Math.min(...bandCols.map((c) => (dense ? c.lo10 : c.l))); let bh = Math.max(...bandCols.map((c) => (dense ? c.hi90 : c.h)));
  if (!bandCols.length || !(bh > bl)) { bl = domain[0]; bh = domain[1]; }
  const bd = [bl - (bh - bl) * 0.1, bh + (bh - bl) * 0.1];
  const to = (d) => (v) => padT + (1 - (Math.max(d[0], Math.min(d[1], v)) - d[0]) / (d[1] - d[0])) * inner;
  const y = to(domain); const yb = to(bd); const yk = (k) => (inBand(k) ? yb : y);
  sc.begin();
  sc.put('band', 'back', () => s('rect', { class: 'b-pattern' }), [g0.band[0], 0, g0.band[1] - g0.band[0], height], setRect);
  for (const k of horizons) if (k <= H) sc.put('hz' + k, 'back', () => s('line', { class: 'b-horizon', y1: 0 }), [x(k), height], setLineX);
  sc.put('zeroL', 'back', () => s('line', { class: 'b-zero' }), [0, g0.band[0], y(0)], setLineY);
  sc.put('zeroR', 'back', () => s('line', { class: 'b-zero' }), [g0.band[1], W, y(0)], setLineY);
  sc.put('zeroB', 'back', () => s('line', { class: 'b-zero' }), [g0.band[0], g0.band[1], yb(0)], setLineY);
  const candle = (c) => {
    const yy = yk(c.k); const bw = Math.max(1.5, Math.min(inBand(c.k) ? 40 : 13, g0.w(c.k) * (inBand(c.k) ? 0.46 : 0.52)));
    sc.put('c' + c.k, 'candles', () => s('g', {}, s('line'), s('rect')), [x(c.k), yy(c.h), yy(c.l), yy(Math.max(c.o, c.c)), yy(Math.min(c.o, c.c)), bw], setCandle,
      (c.c >= c.o ? 'b-up' : 'b-down') + (c.k > 0 ? ' b-after' : inBand(c.k) ? ' b-in' : ' b-lead'));
  };
  if (dense) {
    const R = rec(); const bins = Math.max(10, Math.round(inner / 6)); const bhgt = inner / bins;
    const counts = new Uint32Array(ncol * bins); const bodies = new Uint32Array(ncol * bins); const seen = new Uint32Array(ncol);
    for (const i of agg.slots) {
      if (!R.present[i]) continue;
      const base = R.C[i]; const u = unit === 'range' ? R.H[i] - R.L[i] : base; if (u <= 0) continue;
      for (let q = 0; q < ncol; q++) {
        const j = i + q - lead; if (j < 0 || j >= R.n || !R.present[j]) continue;
        const d = inBand(q - lead) ? bd : domain; const span = d[1] - d[0];
        seen[q]++;
        const bin = (p) => Math.floor((((p - base) / u - d[0]) / span) * bins);
        const a = Math.max(0, bin(R.L[j])); const b = Math.min(bins - 1, bin(R.H[j]));
        const ba = Math.max(0, bin(Math.min(R.O[j], R.C[j]))); const bb = Math.min(bins - 1, bin(Math.max(R.O[j], R.C[j])));
        for (let z = a; z <= b; z++) counts[q * bins + z]++;
        for (let z = ba; z <= bb; z++) bodies[q * bins + z]++;
      }
    }
    const g = s('g', { class: 'b-cells' });
    for (let q = 0; q < ncol; q++) for (let z = 0; z < bins; z++) {
      const sh = seen[q] ? counts[q * bins + z] / seen[q] : 0; const bo = seen[q] ? bodies[q * bins + z] / seen[q] : 0;
      if (sh > 0.015) g.append(s('rect', { x: g0.x0(q - lead) + 0.5, y: padT + (bins - 1 - z) * bhgt + 0.5, width: Math.max(1, g0.w(q - lead) - 1), height: Math.max(1, bhgt - 1), 'fill-opacity': (0.02 + 0.15 * sh + 0.72 * bo).toFixed(3) }));
    }
    sc.swap('cells', g);
    const flat = (list) => list.filter((c) => c.n).flatMap((c) => [x(c.k), yk(c.k)(c.c)]);
    const before = flat(cols.filter((c) => c.k < 1 - pbars)); const after = [g0.band[1], y(0), ...flat(cols.filter((c) => c.k > 0))];
    for (const cls of ['b-median-case', 'b-median']) { sc.put('mB' + cls, 'lines', () => s('polyline'), before, setPoints, cls); sc.put('mA' + cls, 'lines', () => s('polyline'), after, setPoints, cls); }
    for (const c of bandCols) candle(c);
  } else {
    sc.swap('cells', null);
    const after = agg.single ? [] : cols.filter((c) => c.k > 0 && c.n);
    if (after.length > 1) sc.put('fan', 'fan', () => s('polygon'), [g0.band[1], y(0), ...after.flatMap((c) => [x(c.k), y(c.q3)]), ...after.slice().reverse().flatMap((c) => [x(c.k), y(c.q1)])], setPoints, 'b-fan');
    for (const c of cols) if (c.n) candle(c);
  }
  sc.end();
  sc.layers.text.replaceChildren(s('text', { class: 'b-scale', x: (g0.band[0] + g0.band[1]) / 2, y: height - 4, 'text-anchor': 'middle' }, `${agg.single ? '' : 'MEDIAN '}RANGE ${unitText(bh - bl, unit).replace('+', '')}`),
    ...(scale ? [s('text', { class: 'b-scale', x: W - 4, y: 11, 'text-anchor': 'end' }, unitText(domain[1], unit)), s('text', { class: 'b-scale', x: W - 4, y: height - 4, 'text-anchor': 'end' }, unitText(domain[0], unit)),
      s('text', { class: 'b-scale', x: 4, y: y(0) - 4 }, 'ANCHOR CLOSE')] : []));
}

/** Column labels: elapsed time from the deciding close, with the measured horizons marked. */
export function drawAxis(host, { lead, H, pbars, horizons }) {
  const { svg, W } = frame(host, 26); const g0 = geom(W, lead, H, pbars); const cw = g0.unit; const x = g0.x;
  svg.append(s('rect', { class: 'b-pattern', x: g0.band[0], y: 0, width: g0.band[1] - g0.band[0], height: 26 }));
  const every = [4, 8, 16, 32].find((e) => e * cw >= 46) || 32; let last = -1e9;
  const put = (k, text, cls) => { if (Math.abs(x(k) - last) < 30 && !cls) return; if (cls) last = x(k); svg.append(s('text', { class: 'b-axis ' + (cls || ''), x: x(k), y: 16, 'text-anchor': 'middle' }, text)); };
  for (const k of horizons) if (k <= H) { put(k, offsetLabel(k), 'on'); svg.append(s('path', { class: 'b-tick', d: `M${x(k) - 3} 21H${x(k) + 3}L${x(k)} 25Z` })); }
  svg.append(s('text', { class: 'b-axis on', x: (g0.band[0] + g0.band[1]) / 2, y: 16, 'text-anchor': 'middle' }, pbars > 1 ? `PATTERN · ${pbars} BARS` : 'PATTERN'));
  for (let k = -lead; k <= H; k++) {
    if (k === 0 || k % every !== 0 || horizons.includes(k) || (k > -pbars - 2 && k < 3)) continue;
    if (horizons.some((hk) => Math.abs(x(hk) - x(k)) < 40) || Math.abs(x(k) - (g0.band[0] + g0.band[1]) / 2) < 56) continue;
    svg.append(s('text', { class: 'b-axis', x: x(k), y: 16, 'text-anchor': 'middle' }, offsetLabel(k)));
  }
}

/** The column track: one bar per column for the selected lane. Bars move on the same spring as the candles. */
export function drawColumnTrack(host, { agg, lead, H, pbars, horizons, measure, height = 61 }) {
  const W = Math.max(120, Math.floor(host.clientWidth));
  const sc = sceneFor(host, ['back', 'bars', 'text']); sc.size(W, height);
  const g0 = geom(W, lead, H, pbars); const x = g0.x; const bw = Math.max(1.5, Math.min(14, g0.unit * 0.5)); const text = [];
  sc.begin();
  sc.put('band', 'back', () => s('rect', { class: 'b-pattern' }), [g0.band[0], 0, g0.band[1] - g0.band[0], height], setRect);
  const bar = (k, top, hh, cls) => sc.put('b' + k, 'bars', () => s('rect'), [x(k) - bw / 2, top, bw, hh], setRect, cls);
  if (measure === 'up') {
    const mid = height / 2; const span = Math.max(0.06, ...agg.cols.map((c) => (c.k > 0 && c.n ? Math.abs(c.up - 0.5) * 1.15 : 0)));
    sc.put('zero', 'back', () => s('line', { class: 'b-zero' }), [0, W, mid], setLineY);
    text.push(s('text', { class: 'b-scale', x: 4, y: mid - 4 }, '50%'), s('text', { class: 'b-scale', x: 4, y: 10 }, Math.round((0.5 + span) * 100) + '%'), s('text', { class: 'b-scale', x: 4, y: height - 3 }, Math.round((0.5 - span) * 100) + '%'));
    for (const c of agg.cols) {
      if (c.k <= 0 || !c.n) continue;
      const d = Math.max(-span, Math.min(span, c.up - 0.5)); const hh = Math.max(1, (Math.abs(d) / span) * (mid - 12));
      bar(c.k, d >= 0 ? mid - hh : mid, hh, d >= 0 ? 'b-bar' : 'b-bar below');
      if (horizons.includes(c.k)) text.push(s('text', { class: 'b-axis on', x: x(c.k), y: d >= 0 ? Math.max(9, mid - hh - 3) : Math.min(height - 2, mid + hh + 10), 'text-anchor': 'middle' }, Math.round(c.up * 100) + '%'));
    }
  } else {
    const max = Math.max(...agg.cols.map((c) => (c.n ? c.rng : 0)), 1e-9);
    for (const c of agg.cols) {
      if (!c.n) continue;
      const hh = Math.max(1, (c.rng / max) * (height - 16));
      bar(c.k, height - 2 - hh, hh, 'b-bar');
      if (c.k === 0) text.push(s('text', { class: 'b-axis on', x: x(0), y: Math.max(9, height - 5 - hh), 'text-anchor': 'middle' }, pct(c.rng).replace('+', '')));
    }
  }
  sc.end();
  sc.layers.text.replaceChildren(...text);
}

/** A small drawing of a pattern's median candles, in units of the last candle's range. */
export function drawGlyph(host, agg, pbars, w = 30, height = 26) {
  const svg = s('svg', { class: 'glyph', viewBox: `0 0 ${w} ${height}`, width: w, height });
  host.replaceChildren(svg);
  const cols = agg.cols.filter((c) => c.k > -pbars && c.k <= 0 && c.n);
  if (!cols.length) return;
  const lo = Math.min(...cols.map((c) => c.l)); const hi = Math.max(...cols.map((c) => c.h)); const span = hi - lo || 1;
  const y = (v) => 2 + (1 - (v - lo) / span) * (height - 4); const step = w / (cols.length + 1); const bw = Math.min(7, step * 0.56);
  cols.forEach((c, idx) => {
    const cx = step * (idx + 1); const top = y(Math.max(c.o, c.c)); const bot = y(Math.min(c.o, c.c));
    svg.append(s('g', { class: (c.c >= c.o ? 'b-up' : 'b-down') + ' b-in' }, s('line', { x1: cx, x2: cx, y1: y(c.h), y2: y(c.l) }), s('rect', { x: cx - bw / 2, y: top, width: bw, height: Math.max(1, bot - top) })));
  });
}
