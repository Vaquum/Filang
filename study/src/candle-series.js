import { isoUTC } from './data.js';
import { geRatTimes, leRatTimes, ratToNumber } from './num.js';
import { axisOf } from './candle-definitions.js';

const T = 1, F = 0, U = -1;
const toTruth = (value) => value ? T : F;
const within = (num, den, min, max) => geRatTimes(num, min, den) && (!max || leRatTimes(num, max, den));
const whole = (v) => Number(v.rat.num);

function endpoint(r, i, point) {
  switch (point) {
    case 'open': return r.O[i];
    case 'high': return r.H[i];
    case 'low': return r.L[i];
    case 'close': return r.C[i];
    case 'body_low': return Math.min(r.O[i], r.C[i]);
    case 'body_high': return Math.max(r.O[i], r.C[i]);
    default: throw Error('Unknown price point ' + point);
  }
}

function levels(ctx, n) {
  return ctx.cached('prior-levels:' + n, () => {
    const r = ctx.rec, low = new Float64Array(r.n).fill(NaN), high = new Float64Array(r.n).fill(NaN);
    const lows = [], highs = [];
    let l = 0, h = 0, run = 0;
    for (let i = 0; i < r.n; i++) {
      if (run >= n) {
        while (lows[l] < i - n) l++;
        while (highs[h] < i - n) h++;
        low[i] = r.L[lows[l]];
        high[i] = r.H[highs[h]];
      }
      if (!r.has(i)) { run = 0; lows.length = 0; highs.length = 0; l = 0; h = 0; continue; }
      run++;
      while (lows.length > l && r.L[lows.at(-1)] >= r.L[i]) lows.pop();
      while (highs.length > h && r.H[highs.at(-1)] <= r.H[i]) highs.pop();
      lows.push(i);
      highs.push(i);
    }
    return { low, high };
  });
}

// The lowest and highest value of a dimension over the n candles before each one. A missing candle, or one without
// the value, empties the window, as a missing candle does for prices.
function dimensionLevels(ctx, n, name) {
  return ctx.cached('prior-levels:' + name + ':' + n, () => {
    const r = ctx.rec, x = r.dimension(name), low = new Float64Array(r.n).fill(NaN), high = new Float64Array(r.n).fill(NaN);
    const lows = [], highs = [];
    let l = 0, h = 0, run = 0;
    for (let i = 0; i < r.n; i++) {
      if (run >= n) {
        while (lows[l] < i - n) l++;
        while (highs[h] < i - n) h++;
        low[i] = x[lows[l]];
        high[i] = x[highs[h]];
      }
      if (Number.isNaN(x[i])) { run = 0; lows.length = 0; highs.length = 0; l = 0; h = 0; continue; }
      run++;
      while (lows.length > l && x[lows.at(-1)] >= x[i]) lows.pop();
      while (highs.length > h && x[highs.at(-1)] <= x[i]) highs.pop();
      lows.push(i);
      highs.push(i);
    }
    return { low, high };
  });
}

// The two middle values of a dimension over the n candles before each one, added. NaN where the window is incomplete.
function dimensionMedians(ctx, n, name) {
  return ctx.cached('prior-medians:' + name + ':' + n, () => {
    const r = ctx.rec, x = r.dimension(name), values = new Float64Array(r.n).fill(NaN), sorted = [];
    let run = 0;
    for (let i = 0; i < r.n; i++) {
      if (run >= n) values[i] = sorted[(n - 1) >> 1] + sorted[n >> 1];
      if (Number.isNaN(x[i])) { run = 0; sorted.length = 0; continue; }
      if (run >= n) sorted.splice(lowerBound(sorted, x[i - n]), 1);
      sorted.splice(lowerBound(sorted, x[i]), 0, x[i]);
      run++;
    }
    return values;
  });
}

function prices(ctx, p) {
  if (p.type === 'Zero') return ctx.cached('study-zero', () => new Float64Array(ctx.rec.n));
  if (p.type === 'Level') {
    const n = p.args.over.ms / ctx.rec.barMs, side = p.name === 'prior_low' ? 'low' : 'high';
    return p.args.of ? dimensionLevels(ctx, n, p.args.of.value)[side] : levels(ctx, n)[side];
  }
  if (p.type === 'Reading') {
    return ctx.cached('study-reading:' + p.identity, () => {
      const r = ctx.rec, x = r.dimension(p.def.dimension), lag = whole(p.args.bars_ago), values = new Float64Array(r.n).fill(NaN);
      for (let i = lag; i < r.n; i++) values[i] = x[i - lag];
      return values;
    });
  }
  return ctx.cached('study-price:' + p.identity, () => {
    const r = ctx.rec, lag = whole(p.args.bars_ago), values = new Float64Array(r.n).fill(NaN);
    for (let i = lag; i < r.n; i++) if (r.has(i - lag)) values[i] = endpoint(r, i - lag, p.args.point.value);
    return values;
  });
}

function relation(a, op, b) {
  switch (op) {
    case 'above': return a > b;
    case 'at_or_above': return a >= b;
    case 'below': return a < b;
    case 'at_or_below': return a <= b;
    case 'equal': return a === b;
    case 'unequal': return a !== b;
    default: throw Error('Unknown candle comparison ' + op);
  }
}

function lowerBound(xs, x) {
  let lo = 0, hi = xs.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (xs[mid] < x) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

function priorMedians(ctx, n) {
  return ctx.cached('prior-medians:' + n, () => {
    const r = ctx.rec, values = new Array(r.n).fill(null), sorted = [];
    const span = i => r.H[i] - r.L[i];
    let run = 0;
    for (let i = 0; i < r.n; i++) {
      if (run >= n) values[i] = BigInt(sorted[(n - 1) >> 1]) + BigInt(sorted[n >> 1]);
      if (!r.has(i)) { run = 0; sorted.length = 0; continue; }
      if (run >= n) sorted.splice(lowerBound(sorted, span(i - n)), 1);
      const x = span(i);
      sorted.splice(lowerBound(sorted, x), 0, x);
      run++;
    }
    return values;
  });
}

function valueSeries(r, test, explain) {
  const vals = new Int8Array(r.n);
  for (let i = 0; i < r.n; i++) vals[i] = r.has(i) ? test(i) : U;
  return { vals, why: i => r.has(i) ? explain(i, vals[i]) : 'Candle absent from the recording.' };
}

function reclaim(ctx, a) {
  const r = ctx.rec, reference = prices(ctx, a.reference);
  const side = a.reference.name === 'prior_low' ? 1 : -1;
  const min = whole(a.within_min), max = whole(a.within_max);
  const starts = new Int32Array(r.n).fill(-1);
  const result = valueSeries(r, i => {
    let earlier = -Infinity, gap = false, unknown = false;
    const close = side * r.C[i];
    for (let lag = 0; lag <= max; lag++) {
      const j = i - lag, present = r.has(j);
      if (lag) {
        if (present) earlier = Math.max(earlier, side * r.C[j]);
        else gap = true;
      }
      if (lag < min) continue;
      // If an earlier close is at least as far inside as the current close,
      // the current close cannot be first at any level for this breach.
      if (earlier >= close) break;
      const level = side * reference[j];
      if (!Number.isFinite(level)) { unknown = true; continue; }
      if (close <= level || earlier > level) continue;
      if (!present) { unknown = true; continue; }
      const extreme = side * (side === 1 ? r.L[j] : r.H[j]);
      if (side * r.O[j] < level || extreme >= level) continue;
      if (gap) { unknown = true; continue; }
      starts[i] = j;
      return T;
    }
    return unknown ? U : F;
  }, (i, v) => {
    if (v === U) return 'Missing candles or lookback coverage prevent deciding the first reclaim.';
    if (v === F) return 'No first reclaim of a pierced level in the selected candle window.';
    const j = starts[i];
    return `Breach candle ${isoUTC(r.closeTime(j))}. First reclaim ${isoUTC(r.closeTime(i))}. Frozen level ${r.price(reference[j])}.`;
  });
  return {...result, evidence: i => starts[i] < 0 ? null : {
    breach: r.closeTime(starts[i]), reclaim: r.closeTime(i), level: reference[starts[i]],
  }};
}

export function candleSeries(ctx, plan) {
  const { rec: r } = ctx, a = plan.args;
  return ctx.cached('candle-series:' + plan.identity, () => {
    switch (plan.name) {
      case 'breach_reclaim': return reclaim(ctx, a);
      case 'candle_relation':
      case 'near_level': {
        const near = plan.name === 'near_level';
        const left = prices(ctx, near ? a.point : a.left);
        const right = prices(ctx, near ? a.reference : a.right);
        const onPrices = near || (axisOf(a.left) === 'price' && axisOf(a.right) === 'price');
        const show = (value) => onPrices ? r.price(value) : String(value);
        const said = (p, value) => p.type === 'Zero' ? 'zero' : `${p.label} ${show(value)}`;
        return valueSeries(r, i => {
          if (!Number.isFinite(left[i]) || !Number.isFinite(right[i])) return U;
          return toTruth(near ? leRatTimes(Math.abs(left[i]-right[i]), a.within.rat, right[i])
            : relation(left[i], a.is.value, right[i]));
        }, (i, v) => {
          if (v === U) return onPrices ? 'One or both price operands are unavailable.' : 'One or both operands are unavailable.';
          return near
            ? `${r.price(left[i])} is ${(100*Math.abs(left[i]-right[i])/right[i]).toFixed(3)}% from ${r.price(right[i])}. Limit ${a.within.text}.`
            : `${said(a.left, left[i])} and ${said(a.right, right[i])}. The test was ${a.is.label.toLowerCase()}.`;
        });
      }
      case 'candle_share': {
        const lag = whole(a.bars_ago);
        const part = i => ({
          body: () => Math.abs(r.C[i]-r.O[i]),
          lower_wick: () => Math.min(r.O[i],r.C[i])-r.L[i],
          upper_wick: () => r.H[i]-Math.max(r.O[i],r.C[i]),
        })[a.part.value]();
        return valueSeries(r, i => {
          const j = i - lag, span = r.H[j]-r.L[j];
          if (!r.has(j) || span <= 0) return U;
          return toTruth(within(part(j),span,a.min.rat,a.max.rat));
        }, (i, v) => v === U ? 'The selected candle is absent or has zero range.'
          : `${a.part.label} was ${(100*part(i-lag)/(r.H[i-lag]-r.L[i-lag])).toFixed(2)}% of the candle range.`);
      }
      case 'range_multiple': {
        const med = priorMedians(ctx, a.over.ms / r.barMs);
        return valueSeries(r, i => {
          if (!med[i]) return U;
          return toTruth(within(2n*BigInt(r.H[i]-r.L[i]), med[i], a.min.rat, a.max?.rat));
        }, (i, v) => v === U ? 'The previous window is incomplete or its median range is zero.'
          : `This range was ${(2*(r.H[i]-r.L[i])/Number(med[i])).toFixed(3)} × the preceding ${a.over.text} median.`);
      }
      case 'dimension_multiple': {
        const name = a.dimension.value, x = r.dimension(name), med = dimensionMedians(ctx, a.over.ms / r.barMs, name);
        const min = ratToNumber(a.min.rat), max = a.max ? ratToNumber(a.max.rat) : null;
        return valueSeries(r, i => {
          if (!(med[i] > 0) || Number.isNaN(x[i])) return U;
          const twice = 2 * x[i];
          return toTruth(twice >= min * med[i] && (max === null || twice <= max * med[i]));
        }, (i, v) => v === U ? 'The previous window is incomplete, a candle has no such value, or the median is zero.'
          : `This ${name} was ${(2*x[i]/med[i]).toFixed(3)} × the preceding ${a.over.text} median.`);
      }
      default: throw Error('No candle series for ' + plan.name);
    }
  });
}
