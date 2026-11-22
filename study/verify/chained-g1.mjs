// CHAIN-G1, as its protocol says (benchmarks/reports/20261122-chained-g1/README.md, written before this file).
// Are the windows that match a chained two-bar shape as recorded a fair sample, by what the close did an hour later,
// of the windows that match it when the second bar is read as opening at the first bar's close?
// Run from the repository root, after study/prepare_recording.py: node study/verify/chained-g1.mjs
// It writes benchmarks/reports/20261122-chained-g1/results.json and prints a summary. Nothing here is tuned to a result.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { loadEnvironment, ROOT } from './node-env.js';
import { analyze } from '../src/check.js';
import { runAnalysis } from '../src/engine.js';
import { ENGINE } from '../src/registry.js';

const REPORT = path.join(ROOT, '..', 'benchmarks', 'reports', '20261122-chained-g1', 'results.json');
// fixed by the protocol
const CODES = 20, MIN_GROUP = 100, ALPHA = 0.05, MAX_DIFFERING = 2, MIN_TESTED = 5, HORIZON = '1h';

const e = loadEnvironment();
assert.equal(e.digestVerified, true, 'the recording is not the pinned one');
const rec = e.rec;

// ---- this file's own coding of a window, from the recorded columns alone and independent of the engine's.
// As recorded: every bar is [low, body low, body high, high] with its own open. Chained: the first bar is as recorded;
// every later bar opens at the close of the recorded bar just before it, and its low and high widen to include that open.
function code(end, bars, chained) {
  const start = end - bars + 1; if (start < 0) return null;
  const rows = [], dirs = [];
  for (let i = start; i <= end; i++) {
    if (!rec.present[i]) return null;
    const joined = chained && i > start;
    const o = joined ? rec.C[i - 1] : rec.O[i], c = rec.C[i];
    rows.push([joined ? Math.min(rec.L[i], o) : rec.L[i], Math.min(o, c), Math.max(o, c), joined ? Math.max(rec.H[i], o) : rec.H[i]]);
    dirs.push(c > o ? 'u' : c < o ? 'd' : 'z');
  }
  const rank = new Map([...new Set(rows.flat())].sort((a, b) => a - b).map((v, k) => [v, k]));
  return 'g1:o:' + rows.map((r, j) => [...r.map((v) => rank.get(v)), dirs[j]].join(',')).join(';');
}

// ---- step 2: code every two-bar window under the chained reading and rank the codes
const own = new Map();   // chained code -> the slots of its windows' anchor closes
for (let i = 1; i < rec.n; i++) { const g = code(i, 2, true); if (g) { if (!own.has(g)) own.set(g, []); own.get(g).push(i); } }
const ranked = [...own.entries()].sort((a, b) => b[1].length - a[1].length || (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
const chosen = ranked.slice(0, CODES);

// ---- step 3 and 4: the engine's matches under both readings, with the one-hour outcome it computes
function ask(event) {
  const a = analyze(`on BTCUSDT 15m\nfind ${event}\nmeasure close_return(after: ${HORIZON})`, e.env);
  assert.equal(a.ok, true, JSON.stringify(a.errors));
  return runAnalysis(e.ctx, a, { extensions: e.extensions, digestVerified: e.digestVerified }).results[0].matches;
}
const normalCdf = (z) => {   // Abramowitz and Stegun 7.1.26, absolute error under 1.5e-7
  const t = 1 / (1 + 0.3275911 * Math.abs(z) / Math.SQRT2);
  const erf = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-(z * z) / 2);
  return z >= 0 ? (1 + erf) / 2 : (1 - erf) / 2;
};
function group(rows) {
  const seen = rows.filter((r) => r.out[0].status === 'observed');
  const up = seen.filter((r) => r.out[0].value > 0).length;
  return { matches: rows.length, observed: seen.length, left_out: rows.length - seen.length, up, up_share: seen.length ? up / seen.length : null };
}
const round = (x, d = 6) => (x === null || !Number.isFinite(x) ? null : Number(x.toFixed(d)));

const perCode = chosen.map(([g, slots]) => {
  const chained = ask(`chained_g1(${JSON.stringify(g)})`), exact = ask(`exact_g1(${JSON.stringify(g)})`);
  // the two agreements the protocol requires
  assert.deepEqual(chained.map((r) => r.i), slots, `the engine's chained matches of ${g} are not this file's`);
  const inChained = new Set(slots);
  for (const r of exact) assert.ok(inChained.has(r.i), `${g}: slot ${r.i} matches as recorded but not chained`);
  const isExact = new Set(exact.map((r) => r.i));
  const recorded = group(exact), added = group(chained.filter((r) => !isExact.has(r.i)));
  const row = { code: g, chained_matches: chained.length, as_recorded_matches: exact.length, as_recorded: recorded, added_only: added, tested: recorded.observed >= MIN_GROUP && added.observed >= MIN_GROUP };
  if (row.tested) {
    const n1 = added.observed, n2 = recorded.observed, p1 = added.up_share, p2 = recorded.up_share;
    const pooled = (added.up + recorded.up) / (n1 + n2);
    const z = (p1 - p2) / Math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2));
    row.difference = p1 - p2;                                      // added-only minus as-recorded
    row.variance = p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2;        // of that difference, each share with its own variance
    row.z = z; row.p_value = 2 * (1 - normalCdf(Math.abs(z))); row.differs = row.p_value < ALPHA;
  }
  return row;
});

// ---- the criterion, exactly as fixed
const tested = perCode.filter((r) => r.tested);
const weight = tested.reduce((s, r) => s + 1 / r.variance, 0);
const mean = tested.length ? tested.reduce((s, r) => s + r.difference / r.variance, 0) / weight : null;
const se = tested.length ? Math.sqrt(1 / weight) : null;
const interval = tested.length ? [mean - 1.96 * se, mean + 1.96 * se] : null;
const differing = tested.filter((r) => r.differs).length;
const includesZero = interval ? interval[0] <= 0 && interval[1] >= 0 : null;
const verdict = tested.length < MIN_TESTED ? 'inconclusive' : !includesZero ? 'not-supported' : differing <= MAX_DIFFERING ? 'supported' : 'inconclusive';

// ---- description, not part of the hypothesis: how much of the record keeps its code under both readings
const unchanged = {};
for (let bars = 2; bars <= 5; bars++) {
  let windows = 0, same = 0;
  for (let i = bars - 1; i < rec.n; i++) { const a = code(i, bars, false); if (!a) continue; windows++; if (a === code(i, bars, true)) same++; }
  unchanged[bars] = { windows, same_code: same, share: round(same / windows) };
}
// description beyond the protocol's list, about the reading itself and not about outcomes
let pairs = 0, tie = 0, widened = 0, flipped = 0;
for (let i = 1; i < rec.n; i++) {
  if (!rec.present[i] || !rec.present[i - 1]) continue;
  pairs++; const o = rec.C[i - 1];
  if (rec.O[i] === o) tie++;
  if (o < rec.L[i] || o > rec.H[i]) widened++;
  if (Math.sign(rec.C[i] - rec.O[i]) !== Math.sign(rec.C[i] - o)) flipped++;
}
const widenedIn = (slots) => slots.filter((i) => rec.C[i - 1] < rec.L[i] || rec.C[i - 1] > rec.H[i]).length;

let commit = 'unknown', dirty = null;
try {
  commit = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: ROOT, encoding: 'utf8' }).trim();
  dirty = execFileSync('git', ['status', '--porcelain', '--untracked-files=no'], { cwd: ROOT, encoding: 'utf8' }).trim().length > 0;
} catch { /* not a checkout: the digest below still names the data */ }

const results = {
  experiment: 'CHAIN-G1',
  protocol: 'benchmarks/reports/20261122-chained-g1/README.md',
  recording: { symbol: 'BTCUSDT', interval: '15m', closes: rec.n, sha256: e.digest, digest_verified: e.digestVerified },
  engine: { version: ENGINE.version, events: ['exact_g1@1', 'chained_g1@1'], measure: `close_return@1(after: ${HORIZON})` },
  ran_at_commit: commit, working_tree_had_uncommitted_changes: dirty,
  fixed: { codes: CODES, min_group: MIN_GROUP, alpha: ALPHA, max_differing_for_supported: MAX_DIFFERING, min_tested: MIN_TESTED, endpoint: 'return above zero is up; zero is not up; a match without an observed outcome is left out' },
  two_bar_windows: { coded: [...own.values()].reduce((s, v) => s + v.length, 0), distinct_chained_codes: own.size },
  codes: perCode.map((r, k) => ({ rank: k + 1, ...r,
    as_recorded: { ...r.as_recorded, up_share: round(r.as_recorded.up_share) }, added_only: { ...r.added_only, up_share: round(r.added_only.up_share) },
    ...(r.tested ? { difference: round(r.difference), variance: round(r.variance, 9), z: round(r.z, 4), p_value: round(r.p_value, 4) } : {}) })),
  pooled: { tested_codes: tested.length, mean_difference: round(mean), standard_error: round(se), interval_95: interval && interval.map((x) => round(x)), includes_zero: includesZero, codes_differing_at_alpha: differing },
  verdict,
  description: {
    share_of_windows_with_the_same_code_under_both_readings: unchanged,
    adjacent_pairs: { pairs, later_open_equals_previous_close: tie, previous_close_outside_recorded_low_high: widened, direction_differs_between_readings: flipped },
    chosen_codes: { chained_matches: perCode.reduce((s, r) => s + r.chained_matches, 0), with_a_widened_second_bar: chosen.reduce((s, [, slots]) => s + widenedIn(slots), 0), with_a_doji_bar: chosen.filter(([g]) => g.includes('z')).length },
  },
};
fs.writeFileSync(REPORT, JSON.stringify(results, null, 2) + '\n');

const pct = (x) => (x * 100).toFixed(1) + '%';
for (const r of perCode) console.log(`${r.code}  chained ${r.chained_matches}  as recorded ${r.as_recorded_matches}` + (r.tested
  ? `  up: added ${pct(r.added_only.up_share)} of ${r.added_only.observed}, recorded ${pct(r.as_recorded.up_share)} of ${r.as_recorded.observed}, p ${r.p_value.toFixed(3)}${r.differs ? ' *' : ''}` : '  not tested (a group under ' + MIN_GROUP + ')'));
console.log(`CHAIN-G1: ${tested.length} codes tested, ${differing} differ at ${ALPHA}; pooled difference ${interval ? (mean * 100).toFixed(2) + ' points, 95% interval ' + (interval[0] * 100).toFixed(2) + ' to ' + (interval[1] * 100).toFixed(2) : 'none'}; verdict ${verdict}.`);
