// Deterministic evaluator. Strong Kleene logic; only true passes a filter.
// Anchor of slot i = close of the bar opening at t0 + i·bar (complete bar available at its close).

import { leRatTimes, geRatTimes, centsText, ratToPercentText } from './num.js';
import { isoUTC, isoUTCFull, hmUTC, dateUTC, sha256Hex } from './data.js';
import { elapsedText, msToText } from './lang.js';
import { g1FromRecording, matchesG1 } from './g1.js';
import { candleSeries } from './candle-series.js';
import { CANDLE_PATTERNS, ENUMS, ENGINE } from './registry.js';
import { isBoolType, isCatType } from './check.js';

export const T = 1;
export const F = 0;
export const U = -1;
export const KNAME = { 1: 'true', 0: 'false', '-1': 'unknown' };
export const KSYM = { 1: '✓', 0: '✗', '-1': '?' };

export function kAnd(vs) { let u = false; for (const v of vs) { if (v === F) return F; if (v === U) u = true; } return u ? U : T; }
export function kOr(vs) { let u = false; for (const v of vs) { if (v === T) return T; if (v === U) u = true; } return u ? U : F; }
export function kNot(v) { return v === T ? F : v === F ? T : U; }

export const ARITHMETIC_MODEL = [
  'Prices are parsed from the CSV decimal text into integer cents (the recording has at most 2 decimals; load fails otherwise).',
  'Threshold literals (35%, 0.35, 2%) are exact rationals; decisions compare integers by cross-multiplication in BigInt (no rounding).',
  'Times are integer UTC milliseconds; durations are exact multiples of 1m, 1h or 1d (24h).',
  'Returns are float64: (C(t+h) − C(t)) / C(t) from integer cents. Display rounds to 2 decimals of a percent; summaries sum in chronological order.',
  'Median of an even count is the mean of the two middle values. Positive share counts r > 0 strictly.',
];

export const RECORDING_ASSUMPTIONS = [
  'Each CSV row is one 15m bar covering [open_ms, open_ms + 15m). The occurrence anchor is the bar close (open_ms + 15m), in UTC.',
  'A complete bar is assumed to be available at its close. Conditions read only bars that closed at or before the anchor.',
  'The session schedule is a pinned table, known in advance; using a scheduled session close is not post-anchor market data.',
  'New York local dates come from each session’s 09:30 open in the pinned table (DST from the table, not the runtime tz database).',
];

const fnv1a = (s) => {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193); }
  return (h >>> 0).toString(16).padStart(8, '0');
};

const pct1 = (num, den) => (den ? `${((100 * num) / den).toFixed(1)}%` : '—');

export class EvalContext {
  constructor(rec, calendars) {
    this.rec = rec;
    this.calendars = calendars;
    this.cache = new Map();
  }
  cached(key, fn) {
    if (!this.cache.has(key)) this.cache.set(key, fn());
    return this.cache.get(key);
  }
  time(i) { return this.rec.closeTime(i); }
}

// ---------------------------------------------------------------- series definitions

function wickSeries(ctx, p) {
  return ctx.cached('series:' + p.identity, () => {
    const { rec } = ctx;
    const bm = p.args.body_max.rat;
    const wm = p.args.wick_min.rat;
    const vals = new Int8Array(rec.n);
    for (let i = 0; i < rec.n; i++) {
      if (!rec.present[i]) { vals[i] = U; continue; }
      const o = rec.O[i]; const h = rec.H[i]; const l = rec.L[i]; const c = rec.C[i];
      const range = h - l;
      if (range <= 0) { vals[i] = F; continue; }
      const body = Math.abs(c - o);
      const lw = Math.min(o, c) - l;
      vals[i] = leRatTimes(body, bm, range) && geRatTimes(lw, wm, range) ? T : F;
    }
    const why = (i) => {
      if (!rec.has(i)) return 'bar absent from the recording';
      const o = rec.O[i]; const h = rec.H[i]; const l = rec.L[i]; const c = rec.C[i];
      const range = h - l;
      if (range <= 0) return 'zero range (high = low)';
      const body = Math.abs(c - o);
      const lw = Math.min(o, c) - l;
      const bOk = leRatTimes(body, bm, range);
      const wOk = geRatTimes(lw, wm, range);
      return `range ${centsText(range)}; body ${centsText(body)} = ${pct1(body, range)} ${bOk ? '≤' : '>'} ${p.args.body_max.text}; lower wick ${centsText(lw)} = ${pct1(lw, range)} ${wOk ? '≥' : '<'} ${p.args.wick_min.text}`;
    };
    return { vals, why };
  });
}

function exactGeometrySeries(ctx, p) {
  return ctx.cached('series:' + p.identity, () => {
    const { rec } = ctx;
    const { pattern, text } = p.args.pattern;
    const length = pattern.rows.length;
    const vals = new Int8Array(rec.n);
    const rankPrices = new Float64Array(pattern.rankCount);
    let consecutive = 0;
    for (let i = 0; i < rec.n; i++) {
      consecutive = rec.present[i] ? consecutive + 1 : 0;
      vals[i] = consecutive < length ? U : matchesG1(rec, i - length + 1, pattern, rankPrices) ? T : F;
    }
    const why = (i) => {
      if (vals[i] === U) return `exact twins require ${length} consecutive recorded bars through this close`;
      const observed = g1FromRecording(rec, i, length, pattern.oriented);
      return `${observed} ${vals[i] === T ? 'matches' : 'differs from'} ${text}`;
    };
    return { vals, why, windowBars: length };
  });
}

function candlePatternSeries(ctx, p) {
  return ctx.cached('series:' + p.identity, () => {
    const { rec } = ctx;
    const { patternId, patternBars, patternRule } = p.def;
    const matches = CANDLE_PATTERNS.compile(patternId);
    const vals = new Int8Array(rec.n);
    let consecutive = 0;
    for (let i = 0; i < rec.n; i++) {
      consecutive = rec.present[i] ? consecutive + 1 : 0;
      vals[i] = consecutive < patternBars ? U : matches(rec.O, rec.H, rec.L, rec.C, i) ? T : F;
    }
    function why(i) {
      if (vals[i] === U) return `${p.def.title} requires ${patternBars} consecutive completed candle(s).`;
      const evidence = [];
      for (let j = i - patternBars + 1; j <= i; j++) {
        evidence.push([rec.O[j], rec.H[j], rec.L[j], rec.C[j]].map(centsText).join(' / '));
      }
      return `${patternRule} Observed OHLC, oldest first: ${evidence.join(' → ')}.`;
    }
    return { vals, why, windowBars: patternBars };
  });
}

function breakoutSeries(ctx, p) {
  return ctx.cached('series:' + p.identity, () => {
    const { rec } = ctx;
    const L = p.args.over.ms / rec.barMs;
    const vals = new Int8Array(rec.n);
    const maxAtArr = new Int32Array(rec.n).fill(-1);
    const missArr = new Int32Array(rec.n);
    for (let i = 0; i < rec.n; i++) {
      if (!rec.present[i]) { vals[i] = U; continue; }
      let max = -Infinity;
      let maxAt = -1;
      let missing = 0;
      for (let j = i - L; j < i; j++) {
        if (j < 0 || !rec.present[j]) { missing++; continue; }
        if (rec.H[j] > max) { max = rec.H[j]; maxAt = j; }
      }
      maxAtArr[i] = maxAt;
      missArr[i] = missing;
      if (maxAt >= 0 && rec.C[i] <= max) vals[i] = F;
      else if (missing > 0) vals[i] = U;
      else vals[i] = T;
    }
    const why = (i) => {
      if (!rec.has(i)) return 'bar absent from the recording';
      const m = maxAtArr[i];
      const over = p.args.over.text;
      if (vals[i] === U) return `channel incomplete: ${missArr[i]} of ${L} prior bars absent or before the recording start${m >= 0 ? `; close ${centsText(rec.C[i])} > present high ${centsText(rec.H[m])}` : ''}`;
      const rel = vals[i] === T ? '>' : '≤';
      return `close ${centsText(rec.C[i])} ${rel} prior ${over} high ${centsText(rec.H[m])} (bar closing ${isoUTC(rec.closeTime(m))})`;
    };
    return { vals, why, maxAt: maxAtArr, lookbackBars: L };
  });
}

/** Window envelope state: used by quiet_range (series) and range_contained (at the anchor). */
function envelopeSeries(ctx, windowMs, widthRat, widthText, key) {
  return ctx.cached(key, () => {
    const { rec } = ctx;
    const W = windowMs / rec.barMs;
    const vals = new Int8Array(rec.n);
    const width = new Float64Array(rec.n);
    const miss = new Int32Array(rec.n);
    for (let i = 0; i < rec.n; i++) {
      let hi = -Infinity;
      let lo = Infinity;
      let missing = 0;
      for (let j = i - W + 1; j <= i; j++) {
        if (j < 0 || !rec.present[j]) { missing++; continue; }
        if (rec.H[j] > hi) hi = rec.H[j];
        if (rec.L[j] < lo) lo = rec.L[j];
      }
      miss[i] = missing;
      if (!rec.present[i]) { vals[i] = U; width[i] = NaN; continue; }
      const wdt = hi - lo;
      width[i] = wdt;
      if (!leRatTimes(wdt, widthRat, rec.C[i])) vals[i] = F;
      else if (missing > 0) vals[i] = U;
      else vals[i] = T;
    }
    const wText = msToText(windowMs);
    const why = (i) => {
      if (i < 0 || i >= rec.n) return 'sample outside the recording';
      if (!rec.present[i]) return `bar closing ${isoUTC(rec.closeTime(i))} absent`;
      const base = `${wText} width ${centsText(width[i])} = ${(100 * width[i] / rec.C[i]).toFixed(2)}% of close ${centsText(rec.C[i])}`;
      if (vals[i] === F) return `${base} > ${widthText}${miss[i] ? ` (already, with ${miss[i]} bars absent)` : ''}`;
      if (vals[i] === U) return `${base} ≤ ${widthText} so far, but ${miss[i]} of ${W} window bars are absent or before the recording start`;
      return `${base} ≤ ${widthText}`;
    };
    return { vals, why, width, windowBars: W };
  });
}

function quietSeries(ctx, p) {
  return envelopeSeries(ctx, p.args.window.ms, p.args.width_max.rat, p.args.width_max.text, 'series:' + p.identity);
}

function runIndex(ctx, key, vals) {
  return ctx.cached('runs:' + key, () => {
    const n = vals.length;
    const lastF = new Int32Array(n);
    const lastU = new Int32Array(n);
    let lf = -1;
    let lu = -1;
    for (let i = 0; i < n; i++) {
      if (vals[i] === F) lf = i;
      else if (vals[i] === U) lu = i;
      lastF[i] = lf;
      lastU[i] = lu;
    }
    return { lastF, lastU };
  });
}

/** State series for a State plan (named or call). */
export function stateSeries(ctx, p) {
  if (p.op === 'def' && p.name === 'quiet_range') return quietSeries(ctx, p);
  throw new Error(`no state implementation for ${p.name}`);
}

export function eventSeries(ctx, p) {
  if (p.op === 'or' || p.op === 'and') {
    const clause = compileBool(ctx, p);
    const vals = ctx.cached('event-set:' + p.identity,
      () => Int8Array.from({ length: ctx.rec.n }, (_, i) => clause.valueAt(i)));
    function why(i) {
      const evidence = clause.at(i);
      const terms = evidence.parts.map((part) => `${part.text} = ${KNAME[part.v]}`);
      return `${terms.join(' ' + p.op + ' ')}. ${evidence.why}`;
    }
    return { vals, why };
  }
  if (p.name === 'breach_reclaim' || p.name === 'candle_relation') return candleSeries(ctx, p);
  if (p.op === 'def' && p.def.patternId) return candlePatternSeries(ctx, p);
  if (p.op === 'def' && p.name === 'exact_g1') return exactGeometrySeries(ctx, p);
  if (p.op === 'def' && p.name === 'wick_rejection') return wickSeries(ctx, p);
  if (p.op === 'def' && p.name === 'channel_breakout') return breakoutSeries(ctx, p);
  throw new Error(`no event implementation for ${p.name}`);
}

// ---------------------------------------------------------------- conditions at the anchor

function heldAt(ctx, p) {
  const { rec } = ctx;
  const st = stateSeries(ctx, p.args.state);
  const { lastF, lastU } = runIndex(ctx, p.args.state.identity, st.vals);
  const nS = p.args.for.ms / rec.barMs + 1;
  const forText = p.args.for.text;
  const tm = (i) => isoUTC(rec.closeTime(i));
  return (i) => {
    const lo = i - nS + 1;
    const lf = lastF[i];
    if (lf >= Math.max(lo, 0)) {
      if (lf === i) return { v: F, why: `state false at t (${st.why(lf)})` };
      const held = lastU[i] > lf ? null : (i - lf - 1) * rec.barMs;
      return { v: F, why: `state false at ${tm(lf)} (${st.why(lf)}), inside the required ${forText} window from ${tm(lo)}${held !== null ? `; true since ${tm(lf + 1)}, only ${elapsedText(held)}` : ''}` };
    }
    if (lo < 0) return { v: U, why: `needs ${nS} samples from ${tm(lo)}; the first recorded close is ${tm(0)} (warmup: absent samples are unknown)` };
    const lu = lastU[i];
    if (lu >= lo) return { v: U, why: `state unknown at ${tm(lu)} (${st.why(lu)}); no known false in the window` };
    const runStart = Math.max(lastF[i], lastU[i]) + 1;
    return { v: T, why: `true at all ${nS} samples ${tm(lo)} … ${tm(i)}; true since ${tm(runStart)} (${elapsedText((i - runStart) * rec.barMs)} ≥ ${forText})` };
  };
}

function rangeContainedAt(ctx, p) {
  const s = envelopeSeries(ctx, p.args.over.ms, p.args.width_max.rat, p.args.width_max.text, 'series:' + p.identity);
  return (i) => ({ v: s.vals[i], why: s.why(i) });
}

function sessionTailAt(ctx, p) {
  const cal = ctx.calendars.get(p.args.calendar.name);
  const D = p.args.last.ms;
  const lastText = p.args.last.text;
  return (i) => {
    const t = ctx.time(i);
    const s = cal.closeAtOrAfter(t);
    if (s && s.close - D < t) {
      return { v: T, why: `${cal.localHM(t, s)} ∈ (${cal.localHMshort(s.close - D, s)}, ${cal.localHMshort(s.close, s)}] on ${s.date}` };
    }
    if (!cal.covers(t, t + D)) return { v: U, why: `[t, t + ${lastText}) is not inside ${p.args.calendar.name} coverage (New York dates ${cal.startDate} … ${cal.endDate}, end exclusive)` };
    const day = cal.dayAt(t);
    if (day.kind === 'session') {
      const ds = day.s;
      if (t <= ds.close - D) return { v: F, why: `${cal.localHM(t, ds)} ∉ (${cal.localHMshort(ds.close - D, ds)}, ${cal.localHMshort(ds.close, ds)}] on ${ds.date} (before the tail)` };
      return { v: F, why: `${cal.localHM(t, ds)} is after the ${cal.localHMshort(ds.close, ds)} close on ${ds.date}` };
    }
    return { v: F, why: `${cal.localDateText(t)} has no ${p.args.calendar.name} session (known closed)` };
  };
}

function weekdayAt(ctx, p) {
  const cal = ctx.calendars.get(p.args.calendar.name);
  return (i) => {
    const t = ctx.time(i);
    const day = cal.dayAt(t);
    if (day.kind === 'session') return { v: day.s.weekday, why: `New York date ${day.s.date} is a ${p.args.calendar.name} session (stored weekday ${ENUMS.SessionDay.labels[day.s.weekday]})` };
    if (day.kind === 'closed') return { v: 'closed', why: `${cal.localDateText(t)} has no ${p.args.calendar.name} session` };
    return { v: null, why: `anchor ${isoUTC(t)} is outside ${p.args.calendar.name} coverage (New York dates ${cal.startDate} … ${cal.endDate}, end exclusive)` };
  };
}

function completedTrendAt(ctx, p) {
  const { rec } = ctx;
  const Fm = p.args.frame.ms;
  const frameText = p.args.frame.text;
  return (i) => {
    const t = ctx.time(i);
    const E = Math.floor(t / Fm) * Fm;
    const startOpen = E - Fm;
    const s0 = (startOpen - rec.t0) / rec.barMs;
    const s1 = (E - rec.t0) / rec.barMs - 1;
    const span = `${frameText} bar ${dateUTC(startOpen)} ${hmUTC(startOpen)}–${hmUTC(E)}Z`;
    if (s0 < 0) return { v: null, why: `${span} starts before the recording (no fallback to an older bar)` };
    let missing = 0;
    for (let j = s0; j <= s1; j++) if (!rec.has(j)) missing++;
    if (missing) return { v: null, why: `${span} incomplete: ${missing} of ${s1 - s0 + 1} constituent bars absent (no fallback to an older bar)` };
    const o = rec.O[s0];
    const c = rec.C[s1];
    const v = c > o ? 'up' : c < o ? 'down' : 'flat';
    return { v, why: `${span}: open ${centsText(o)} → close ${centsText(c)} (${v})` };
  };
}

// ---------------------------------------------------------------- compile plans

function boolValueAt(clause, i) {
  return clause.valueAt ? clause.valueAt(i) : clause.at(i).v;
}

function combinedValueAt(clauses, i, decisive) {
  let unknown = false;
  for (const clause of clauses) {
    const v = boolValueAt(clause, i);
    if (v === decisive) return decisive;
    if (v === U) unknown = true;
  }
  return unknown ? U : (decisive === F ? T : F);
}

export function compileBool(ctx, p) {
  const base = { text: p.text, label: p.label, plan: p };
  if (p.op === 'def') {
    if (p.kind === 'event') { const s = eventSeries(ctx, p); return { ...base, valueAt: (i) => s.vals[i], at: (i) => ({ v: s.vals[i], why: s.why(i) }) }; }
    if (p.kind === 'state') { const s = stateSeries(ctx, p); return { ...base, valueAt: (i) => s.vals[i], at: (i) => ({ v: s.vals[i], why: `state at t: ${s.why(i)}` }) }; }
    if (p.kind === 'condition') {
      if (p.body) {
        const b = compileBool(ctx, p.body);
        return { ...b, ...base };
      }
      if (p.name === 'held') return { ...base, at: heldAt(ctx, p) };
      if (p.name === 'session_tail') return { ...base, at: sessionTailAt(ctx, p) };
      if (p.name === 'range_contained') return { ...base, at: rangeContainedAt(ctx, p) };
      if (['candle_share', 'range_multiple', 'near_level'].includes(p.name)) {
        const s = candleSeries(ctx, p);
        return { ...base, valueAt: i => s.vals[i], at: i => ({v:s.vals[i], why:s.why(i)}) };
      }
    }
    throw new Error(`no condition implementation for ${p.name}`);
  }
  if (p.op === 'and' || p.op === 'or') {
    const items = p.items.map((x) => compileBool(ctx, x));
    const comb = p.op === 'and' ? kAnd : kOr;
    return {
      ...base,
      valueAt: (i) => combinedValueAt(items, i, p.op === 'and' ? F : T),
      at: (i) => {
        const rs = items.map((it) => it.at(i));
        const v = comb(rs.map((r) => r.v));
        const parts = rs.map((r, k) => ({ text: items[k].text, label: items[k].label, v: r.v, why: r.why, parts: r.parts }));
        let why;
        const decisive = p.op === 'and' ? F : T;
        const d = parts.find((x) => x.v === decisive) || parts.find((x) => x.v === U);
        if (v === decisive && d) why = `${d.text} is ${KNAME[d.v]}: ${d.why}`;
        else if (v === U && d) why = `${d.text} is unknown: ${d.why}`;
        else why = parts.map((x) => `${x.text} ${KNAME[x.v]}`).join('; ');
        return { v, why, parts };
      },
    };
  }
  if (p.op === 'not') {
    const it = compileBool(ctx, p.item);
    return { ...base, valueAt: (i) => kNot(boolValueAt(it, i)), at: (i) => { const r = it.at(i); return { v: kNot(r.v), why: `${p.item.text} is ${KNAME[r.v]}: ${r.why}`, parts: [{ text: it.text, label: it.label, v: r.v, why: r.why, parts: r.parts }] }; } };
  }
  if (p.op === 'cmp') {
    const L = compileCat(ctx, p.left);
    const R = compileCat(ctx, p.right);
    const eqWanted = p.cmp === '=';
    return {
      ...base,
      at: (i) => {
        const a = L.at(i);
        const b = R.at(i);
        if (a.v === null || b.v === null) {
          const u = a.v === null ? a : b;
          return { v: U, why: `${(a.v === null ? L : R).text} is unknown: ${u.why}` };
        }
        const v = (a.v === b.v) === eqWanted ? T : F;
        const side = L.isConst ? b : a;
        const sideText = L.isConst ? R.text : L.text;
        return { v, why: `${sideText} is ${side.v}: ${side.why}` };
      },
    };
  }
  throw new Error('cannot compile ' + p.op);
}

export function compileCat(ctx, p) {
  if (p.op === 'enum') return { text: p.text, isConst: true, at: () => ({ v: p.value, why: 'value' }) };
  if (p.op === 'def' && p.name === 'weekday') return { text: p.text, label: p.label, at: weekdayAt(ctx, p) };
  if (p.op === 'def' && p.name === 'completed_trend') return { text: p.text, label: p.label, at: completedTrendAt(ctx, p) };
  throw new Error('cannot compile categorical ' + (p.name || p.op));
}

export function compileGroup(ctx, p) {
  if (isCatType(p.type)) {
    const c = compileCat(ctx, p);
    const e = ENUMS[p.type.slice(4)];
    return {
      text: p.text, label: p.label, kind: 'categorical', keys: [...e.values, 'unknown'], labels: { ...e.labels, unknown: 'unknown' },
      at: (i) => { const r = c.at(i); return { key: r.v === null ? 'unknown' : r.v, why: r.why }; },
    };
  }
  if (isBoolType(p.type)) {
    const b = compileBool(ctx, p);
    return {
      text: p.text, label: p.label, kind: 'boolean', keys: ['true', 'false', 'unknown'], labels: { true: 'true', false: 'false', unknown: 'unknown' },
      at: (i) => { const r = b.at(i); return { key: KNAME[r.v], why: r.why }; },
    };
  }
  throw new Error('cannot group by ' + p.type);
}

export function compileColumn(ctx, col) {
  const { rec } = ctx;
  const steps = col.h / rec.barMs;
  return {
    ...col,
    at: (i) => {
      const j = i + steps;
      const tt = rec.closeTime(j);
      if (tt > rec.lastClose) return { status: 'censored', value: null, why: `t + ${col.text} = ${isoUTC(tt)} is after the recording end ${isoUTC(rec.lastClose)}` };
      if (!rec.has(j)) return { status: 'unknown', value: null, why: `bar closing at t + ${col.text} (${isoUTC(tt)}) is absent` };
      const value = (rec.C[j] - rec.C[i]) / rec.C[i];
      return { status: 'observed', value, why: `C(t+${col.text}) ${centsText(rec.C[j])} / C(t) ${centsText(rec.C[i])} − 1`, endSlot: j };
    },
  };
}

// ---------------------------------------------------------------- summaries

export function summarize(rows, k) {
  const vals = [];
  let censored = 0;
  let unknown = 0;
  for (const r of rows) {
    const o = r.out[k];
    if (o.status === 'observed') vals.push(o.value);
    else if (o.status === 'censored') censored++;
    else unknown++;
  }
  const n = vals.length;
  let sum = 0;
  for (const v of vals) sum += v;
  const sorted = vals.slice().sort((a, b) => a - b);
  const mid = n >> 1;
  return {
    total: rows.length, observed: n, censored, unknown,
    mean: n ? sum / n : null,
    median: n ? (n % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2) : null,
    positive: vals.filter((v) => v > 0).length,
    min: n ? sorted[0] : null,
    max: n ? sorted[n - 1] : null,
  };
}

// ---------------------------------------------------------------- run

export function occurrenceId(rec, eventIdentity, t) {
  return `rec:sha256:${(rec.digest || 'unverified').slice(0, 16)}/${rec.instrument}/${rec.barText}/${eventIdentity}/${isoUTCFull(t)}`;
}

export function runCandidate(ctx, cand) {
  const { rec } = ctx;
  const plan = cand.plan;
  const evPlan = plan.find;
  const series = eventSeries(ctx, evPlan);
  const event = { identity: evPlan.identity, text: evPlan.text, label: evPlan.label, named: evPlan.named, plan: evPlan, series };
  const counts = { slots: rec.n, absent: rec.n - rec.presentCount, T: 0, F: 0, U: 0 };
  const occ = [];
  for (let i = 0; i < rec.n; i++) {
    if (!rec.present[i]) continue;
    const v = series.vals[i];
    if (v === T) { counts.T++; occ.push(i); } else if (v === F) counts.F++; else counts.U++;
  }
  const clauses = plan.wheres.map((w) => compileBool(ctx, w));
  const group = plan.group ? compileGroup(ctx, plan.group) : null;
  const cols = plan.columns.map((c) => compileColumn(ctx, c));
  function makeRow(i, results) {
    const t = rec.closeTime(i);
    const id = occurrenceId(rec, event.identity, t);
    const failAt = results.findIndex((r) => r.v !== T);
    return {
      i, t, id, short: fnv1a(id), results, pass: failAt === -1, failAt,
      detector: series.vals[i],
      group: group ? group.at(i) : null,
      out: cols.map((c) => c.at(i)),
    };
  }
  const rows = occ.map((i) => makeRow(i, clauses.map((clause) => clause.at(i))));
  const clauseStats = clauses.map((c, k) => {
    let nt = 0; let nf = 0; let nu = 0;
    for (const r of rows) { const v = r.results[k].v; if (v === T) nt++; else if (v === F) nf++; else nu++; }
    return { text: c.text, label: c.label, T: nt, F: nf, U: nu };
  });
  const survivors = [];
  for (let k = 0; k < clauses.length; k++) survivors.push(rows.filter((r) => r.failAt === -1 || r.failAt > k).length);
  const matches = rows.filter((r) => r.pass);
  const summary = cols.map((_, k) => summarize(matches, k));
  let groups = null;
  if (group) {
    const by = new Map(group.keys.map((k) => [k, []]));
    for (const r of matches) by.get(r.group.key).push(r);
    groups = group.keys
      .filter((k) => k !== 'unknown' || by.get('unknown').length > 0)
      .map((k) => ({ key: k, label: group.labels[k], rows: by.get(k), count: by.get(k).length, summary: cols.map((_, c) => summarize(by.get(k), c)) }));
  }
  const rowsBySlot = new Map(rows.map((r) => [r.i, r]));
  // Compute baseline populations on demand: a membership-only parameter sweep
  // should not retain a full set of comparison rows for every candidate.
  let populations;
  function comparisonPopulations() {
    const eligible = [];
    const nonmatching = [];
    const unknownDetector = [];
    const unknownContextAnchors = [];
    for (let i = 0; i < rec.n; i++) {
      if (!rec.present[i]) continue;
      const existing = rowsBySlot.get(i);
      const contextValue = existing ? kAnd(existing.results.map((r) => r.v)) : combinedValueAt(clauses, i, F);
      if (contextValue === U) unknownContextAnchors.push(rec.closeTime(i));
      if (contextValue !== T) continue;
      const row = existing || makeRow(i, clauses.map((clause) => clause.at(i)));
      eligible.push(row);
      if (row.detector === F) nonmatching.push(row);
      if (row.detector === U) unknownDetector.push(row);
    }
    const cal = ctx.calendars.get('nyse_regular');
    function population(members) {
      const dates = new Set();
      for (const row of members) {
        const day = cal.dayAt(row.t);
        if (day.kind === 'session') dates.add(day.s.date);
      }
      return { rows: members, count: members.length, sessionCount: dates.size, summary: cols.map((_, k) => summarize(members, k)) };
    }
    return { eligible: population(eligible), matching: population(matches), nonmatching: population(nonmatching),
      unknownDetector: population(unknownDetector), unknownContextAnchors, unknownContextCount: unknownContextAnchors.length };
  }
  return {
    get populations() { return populations ??= comparisonPopulations(); },
    cand, event, counts, clauses, clauseStats, survivors, group, groups,
    columns: cols, rows, rowsBySlot, matches, summary,
  };
}

/** Evaluate every candidate of an analysis. */
export function runAnalysis(ctx, analysis, meta = {}) {
  const t0 = (typeof performance !== 'undefined' ? performance : Date).now();
  const results = analysis.candidates.map((c) => runCandidate(ctx, c));
  const ms = (typeof performance !== 'undefined' ? performance : Date).now() - t0;
  return { results, ms, manifest: manifestFor(ctx, analysis, meta) };
}

function collectDefs(p, out) {
  if (!p) return;
  if (p.op === 'def') {
    out.add(`${p.def.id || p.name}@${p.version}`);
    for (const v of Object.values(p.args)) if (v && v.op) collectDefs(v, out);
    if (p.body) collectDefs(p.body, out);
  }
  if (p.items) p.items.forEach((x) => collectDefs(x, out));
  if (p.item) collectDefs(p.item, out);
  if (p.left) collectDefs(p.left, out);
  if (p.right) collectDefs(p.right, out);
}

export function manifestFor(ctx, analysis, meta) {
  const defs = new Set();
  for (const c of analysis.candidates) {
    const pl = c.plan;
    [pl.find, ...pl.wheres, pl.group, ...pl.measures].forEach((x) => collectDefs(x, defs));
  }
  const cals = [...ctx.calendars.values()].map((c) => ({ id: c.id, sha256: c.digest }));
  const patterns = CANDLE_PATTERNS.patterns.filter((p) => defs.has(`composer.${p.id.replaceAll('-', '_')}@${p.version}`))
    .map((p) => ({
      id: p.id, version: p.version,
      sha256: sha256Hex(new TextEncoder().encode(JSON.stringify([p.id, p.version, p.bars, p.spec]))),
    })).sort((a, b) => a.id.localeCompare(b.id));
  return {
    engine: ENGINE,
    query: analysis.canonical,
    candidates: analysis.candidates.map((c) => ({ label: c.label, resolved: c.resolvedText })),
    pins: {
      source: { csv_sha256: ctx.rec.digest, verified: meta.digestVerified ?? null, rows: ctx.rec.presentCount, instrument: ctx.rec.instrument, bar: ctx.rec.barText },
      calendars: cals,
      definitions: [...defs].sort(),
      ...(patterns.length ? { candlePatterns: patterns } : {}),
      extensions: (meta.extensions || []).map((e) => ({ id: `${e.def?.id || e.name}@${e.version}`, sha256: e.sha256 || null }))
        .filter((e) => defs.has(e.id)).sort((a, b) => a.id.localeCompare(b.id)),
    },
    arithmetic: 'integer cents + exact rational thresholds; float64 returns',
  };
}

export { ratToPercentText };
