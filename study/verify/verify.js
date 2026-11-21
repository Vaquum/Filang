// Runnable verification on the actual recorded data. Usage: node verify/verify.js
// Read-only: the supplied files are hashed and parsed, never written.
import crypto from 'node:crypto';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { loadEnvironment, readBytes, ROOT } from './node-env.js';
import { parse, printQuestion, sameStructure, setAt, parseExpression, lineCol } from '../src/lang.js';
import { analyze, Checker, registerExtension } from '../src/check.js';
import { runAnalysis, runCandidate, compileBool, compileColumn, compileCat, T, F, U, KNAME, EvalContext } from '../src/engine.js';
import { compareResults } from '../src/diff.js';
import { EXAMPLES, exampleById } from '../src/examples.js';
import { sha256Hex, parseRecording, isoUTCFull } from '../src/data.js';
import { parseCents, ratFromText, ratToDecimalText, ratToPercentText } from '../src/num.js';
import { runConformance, evaluateConditionText } from '../src/conformance.js';
import { quietCoverage } from '../src/coverage.js';
import { completionsAt, whereExample } from '../src/assist.js';
import { Registry } from '../src/registry.js';

const SUPPLIED_SHA256 = {
  'recorded-bars.csv': '21df2ed15f787479b3e871be0048b5721cd18e7e085881e4175975c8d056889a',
  'nyse-sessions.json': '363823f32c9460349619877ae92b148e3b25ea4b05f109e1d28fe56ef43f9d97',
  'data-provenance.json': '5725646307fafc88a87a06c75bc2382f10ad6402114603db0d206c3b322720a0',
};

let passed = 0;
const failures = [];
let current = '';
function test(name, fn) {
  current = name;
  const before = failures.length;
  try { fn(); } catch (e) { failures.push(`${name}: threw ${e && e.stack ? e.stack.split('\n').slice(0, 3).join(' | ') : e}`); }
  if (failures.length === before) { passed++; console.log(`  ✓ ${name}`); } else console.log(`  ✗ ${name}`);
}
function ok(cond, msg) { if (!cond) failures.push(`${current}: ${msg}`); }
function eq(a, b, msg) { const sa = JSON.stringify(a); const sb = JSON.stringify(b); if (sa !== sb) failures.push(`${current}: ${msg} — expected ${sb}, got ${sa}`); }

const E = loadEnvironment();
const { rec, cal, env, ctx } = E;
const at = (iso) => rec.slotClosingAt(Date.parse(iso));
const run = (text, bundle = E) => {
  const a = analyze(text, bundle.env);
  if (!a.ok) throw new Error(`analysis failed for:\n${text}\n${a.errors.map((e) => e.message).join('\n')}`);
  return { a, r: runAnalysis(bundle.ctx, a) };
};
const cond = (text, iso, bundle = E) => {
  const r = evaluateConditionText(bundle, text, iso);
  if (r.error) throw new Error(r.error);
  return r;
};
const errorsOf = (text) => analyze(text, env).errors;
const spanText = (text, d) => text.slice(d.start, d.end);
const Q = (body) => `on BTCUSDT 15m\nfind "Wick rejection"\n${body}\nmeasure close_return(after: [1h, 4h])`;

console.log(`Filang study — verification on ${rec.instrument} ${rec.barText}, ${rec.n} slots\n`);

console.log('Data and provenance');
test('supplied files are byte-for-byte unchanged (SHA-256)', () => {
  for (const [f, want] of Object.entries(SUPPLIED_SHA256)) {
    const got = crypto.createHash('sha256').update(readBytes(f)).digest('hex');
    eq(got, want, `${f} digest`);
  }
});
test('pure-JS SHA-256 used by the page equals node:crypto and the provenance csv_sha256', () => {
  const bytes = readBytes('recorded-bars.csv');
  eq(sha256Hex(bytes), crypto.createHash('sha256').update(bytes).digest('hex'), 'pure JS vs node:crypto');
  eq(E.digest, E.provenance.csv_sha256, 'computed digest vs provenance');
  ok(E.digestVerified, 'digestVerified flag');
  eq(sha256Hex(new Uint8Array(0)), 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'empty-input vector');
  eq(sha256Hex(new TextEncoder().encode('abc')), 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad', '"abc" vector');
});
test('recording loads as a complete 15m UTC grid with exact cents', () => {
  eq(rec.presentCount, E.provenance.row_count, 'rows');
  eq(rec.n, 14496, 'grid slots');
  eq(rec.n - rec.presentCount, 0, 'absent slots in the real recording');
  eq(rec.badOhlc, 0, 'OHLC inconsistencies');
  eq(isoUTCFull(rec.t0), '2025-01-01T00:00:00Z', 'first open');
  eq(isoUTCFull(rec.lastClose), '2025-06-01T00:00:00Z', 'last close (recording end)');
  eq(rec.ohlcText(0), { open: '93576.0', high: '93702.15', low: '93489.03', close: '93656.18', volume: '175.85673' }, 'first row text kept verbatim');
  eq([rec.O[0], rec.H[0], rec.L[0], rec.C[0]], [9357600, 9370215, 9348903, 9365618], 'first row cents');
});
test('pinned calendar: 102 sessions, 6h30m each, EST/EDT from the table; cross-checked with Intl', () => {
  eq(cal.sessions.length, 102, 'sessions');
  eq(cal.shortestSessionMs, 6.5 * 3600000, 'shortest session');
  eq(cal.offsets.map((o) => cal.tzLabel(o)), ['EST', 'EDT'], 'offsets');
  eq(isoUTCFull(cal.covStart), '2025-01-01T05:00:00Z', 'coverage start (New York midnight)');
  eq(isoUTCFull(cal.covEnd), '2025-06-01T04:00:00Z', 'coverage end');
  let checked = 0;
  try {
    const f = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
    for (const s of cal.sessions) { eq([f.format(new Date(s.open)), f.format(new Date(s.close))], ['09:30', '16:00'], `${s.date} local open/close`); checked++; }
  } catch (e) { console.log('    (Intl time-zone data unavailable; skipped the cross-check)'); }
  ok(checked === 0 || checked === 102, 'Intl cross-check count');
  eq(cal.dayAt(Date.parse('2025-03-07T20:00:00Z')).s.offsetMs, 5 * 3600000, 'before DST');
  eq(cal.dayAt(Date.parse('2025-03-10T20:00:00Z')).s.offsetMs, 4 * 3600000, 'after DST');
});

console.log('\nLexer, parser and canonical printer');
test('every example parses; canonical examples print back verbatim and round-trip structurally', () => {
  for (const ex of EXAMPLES) {
    const { ast, error } = parse(ex.text);
    if (ex.group === 'Diagnostics' && ex.id === 'err-syntax') { ok(error, 'syntax example must fail'); continue; }
    ok(!error, `${ex.id} parses (${error && error.message})`);
    if (!ast) continue;
    eq(printQuestion(ast), ex.text, `${ex.id} canonical print`);
    ok(sameStructure(parse(printQuestion(ast)).ast, ast), `${ex.id} structural round trip`);
  }
});
test('non-canonical input (comments, spacing, parentheses) normalizes and round-trips', () => {
  const src = `on   BTCUSDT 15m -- instrument and bar size
let   w = {2% | 3 %}   -- a percentage may be written "3 %"
find "Wick \\u0072ejection"
where ((weekday(nyse_regular) = fri)) and (session_tail(nyse_regular, last: 1h) or held(quiet_range(width_max: w), for: 48h))
where not not session_tail(nyse_regular, last: 30m)
measure close_return(after: [1h,4h])`;
  const { ast, error } = parse(src);
  ok(!error, `parses: ${error && error.message}`);
  const canon = printQuestion(ast);
  eq(canon.split('\n')[1], 'let w = {2% | 3%}', 'percent spacing normalized');
  eq(canon.split('\n')[2], 'find "Wick rejection"', 'JSON escape decoded');
  eq(canon.split('\n')[3], 'where weekday(nyse_regular) = fri and (session_tail(nyse_regular, last: 1h) or held(quiet_range(width_max: w), for: 48h))', 'minimal parentheses');
  ok(sameStructure(parse(canon).ast, ast), 'structure preserved');
  eq(printQuestion(parse(canon).ast), canon, 'printing is idempotent');
  ok(analyze(src, env).ok, 'the escaped name resolves to the named definition');
});
test('syntax errors carry exact spans', () => {
  const cases = [
    [Q('where weekday(nyse_regular) = = fri'), '=', 'expected a value'],
    ['on BTCUSDT 15m\nfind "Wick rejection"\nwhere weekday(nyse_regular) = fri\nmeasure', '', "expected a call after 'measure'"],
    [Q('where weekday(nyse_regular) = fri = fri'), '=', 'do not chain'],
    [Q('where session_tail(last: 30m, nyse_regular)'), 'nyse_regular', 'only the first argument'],
    [Q('where held("Quiet range, for: 48h)'), '"Quiet range, for: 48h)', 'unterminated string'],
    [Q('where held("Quiet range", for: 1.5h)'), '1.5h', 'whole numbers'],
    [Q('where held("Quiet range", for: 48x)'), '48x', 'unknown duration unit'],
    [Q('where held("Quiet range", for: 048h)'), '048h', 'leading zeros'],
    [Q('where held("Quiet range", for: 0h)'), '0h', 'positive'],
    ['on BTCUSDT 15m\nlet find = 1h\nfind "Wick rejection"\nmeasure close_return(after: 1h)', 'find', 'reserved keyword'],
    ['on BTCUSDT 15m\nFind "Wick rejection"\nmeasure close_return(after: 1h)', 'Find', "expected 'let' or 'find'"],
    [Q('simulate entry(after: 1h)'), 'simulate', 'not a clause'],
    [Q('where "\\x"'), '"\\x"', 'invalid escape'],
    [Q('where weekday(nyse_regular) == fri'), '==', 'single ='],
    [Q('where {30m}'), '}', 'at least two values'],
  ];
  for (const [src, want, msg] of cases) {
    const { error } = parse(src);
    ok(error, `expected a syntax error for ${JSON.stringify(src.slice(30, 90))}`);
    if (!error) continue;
    eq(spanText(src, error), want, `span for "${msg}"`);
    ok(error.message.includes(msg), `message "${error.message}" should mention "${msg}"`);
    ok(error.kind === 'syntax', 'kind');
  }
  const lc = lineCol(Q('where weekday(nyse_regular) = = fri'), parse(Q('where weekday(nyse_regular) = = fri')).error.start);
  eq([lc.line, lc.col], [3, 31], 'line and column of the second =');
  const rr = parse(Q('where simulate'));
  ok(rr.ast, 'simulate as a bare name parses (then fails typing)');
  const hint = parse(Q('simulate x(1h)')).error.hint || '';
  ok(hint.includes('planned design example'), 'planned clause hint');
});

console.log('\nSignatures, types, domains and capabilities');
test('typed errors name the offending span and are actionable', () => {
  const cases = [
    [Q('where session_tail(nyse_regular, lst: 30m)'), 'lst', 'signature', 'unknown argument lst', 'did you mean last'],
    [Q('where held("Quiet range", for: 48h, for: 24h)'), 'for: 24h', 'signature', 'duplicate argument for', null],
    [Q('where held("Quiet range")'), 'held("Quiet range")', 'signature', 'missing required argument for', null],
    [Q('where held("Quiet range", for: 50m)'), '50m', 'domain', 'not a whole number of 15m bars', '45m or 1h'],
    [Q('where session_tail(nyse_regular, last: 7h)'), '7h', 'domain', 'longer than the shortest nyse_regular session', null],
    [Q('where completed_trend(frame: 5h) = up'), '5h', 'domain', 'does not divide 24h', null],
    [Q('where session_tail(nyse_regular, last: 30%)'), '30%', 'type', 'expects a duration', null],
    [Q('where weekday(nyse) = fri'), 'nyse', 'name', 'unknown calendar nyse', 'nyse_regular'],
    [Q('where weekday(nyse_regular) = friday'), 'friday', 'name', 'not a session day value', 'did you mean fri'],
    [Q('where weekday(nyse_regular) = sat'), 'sat', 'type', 'never occurs', null],
    [Q('where weekday(nyse_regular) < fri'), '<', 'type', 'needs ordered values', 'use = or !='],
    [Q('where completed_trend(frame: 4h)'), 'completed_trend(frame: 4h)', 'type', 'where needs a condition', 'group by'],
    [Q('where close_return(after: 1h)'), 'close_return(after: 1h)', 'type', 'where needs a condition', 'outcomes use bars after the anchor'],
    [Q('where session_tail(nyse_regular, last: [30m, 1h])'), '[30m, 1h]', 'type', 'takes a single Duration', '{30m | 1h}'],
    [Q('where wick_rejection(body_max: 35)'), '35', 'domain', 'above 100%', 'did you mean 35%'],
    [Q('where sesion_tail(nyse_regular, last: 30m)'), 'sesion_tail', 'name', 'unknown function', 'session_tail'],
    [Q('where fri'), 'fri', 'type', 'not a condition', 'weekday(nyse_regular) = fri'],
    ['on BTCUSDT 15m\nfind session_tail(nyse_regular, last: 30m)\nmeasure close_return(after: 1h)', 'session_tail(nyse_regular, last: 30m)', 'type', 'find needs an Event', null],
    ['on BTCUSDT 15m\nfind "Wick rejections"\nmeasure close_return(after: 1h)', '"Wick rejections"', 'name', 'no definition named', '"Wick rejection"'],
    ['on BTCUSDT 15m\nfind "Quiet range"\nmeasure close_return(after: 1h)', '"Quiet range"', 'type', 'find needs an Event', null],
    ['on BTCUSDT 15m\nfind "Wick rejection"\nmeasure close_return(1h)', '1h', 'signature', 'takes no positional argument', null],
    ['on BTCUSDT 15m\nfind "Wick rejection"\nmeasure close_return(after: [1h, 60m])', '60m', 'type', 'duplicate after value', null],
    ['on BTCUSDT 15m\nfind "Wick rejection"\nmeasure close_return(after: [1h, 4h])\nmeasure close_return(after: 4h)', '4h', 'type', 'already measured', null],
    ['on BTCUSDT 15m\nfind "Wick rejection"\nmeasure weekday(nyse_regular)', 'weekday(nyse_regular)', 'type', 'measure needs an outcome', null],
    ['on ETHUSDT 15m\nfind "Wick rejection"\nmeasure close_return(after: 1h)', 'ETHUSDT', 'capability', 'no recording for ETHUSDT', null],
    ['on BTCUSDT 1h\nfind "Wick rejection"\nmeasure close_return(after: 1h)', '1h', 'capability', 'bars are not enabled', null],
    ['on BTCUSDT 15m\nfind value_area_reclaim()\nmeasure close_return(after: 1h)', 'value_area_reclaim', 'capability', 'trades.aggressor', 'OHLCV bars cannot substitute'],
    [Q('where relative_volume(over: 24h, min: 150%)'), 'relative_volume', 'capability', 'planned capability', null],
    ['on BTCUSDT 15m\nfind breach_reclaim(prior_utc_day_low(), within: [1, 3])\nmeasure close_return(after: 1h)', 'breach_reclaim', 'capability', 'planned capability', null],
  ];
  for (const [src, want, kind, msg, hint] of cases) {
    const errs = errorsOf(src);
    const d = errs.find((e) => e.message.includes(msg));
    ok(d, `expected an error mentioning "${msg}" for ${JSON.stringify(src.split('\n').slice(1, 3).join(' / '))}; got ${JSON.stringify(errs.map((e) => e.message))}`);
    if (!d) continue;
    eq(spanText(src, d), want, `span for "${msg}"`);
    eq(d.kind, kind, `kind for "${msg}"`);
    if (hint) ok((d.hint || '').includes(hint), `hint for "${msg}" should include "${hint}", got "${d.hint}"`);
  }
});
test('bindings and choices: literal-only, one axis per let, duplicate and size limits', () => {
  const L = (lets, body) => `on BTCUSDT 15m\n${lets}\nfind channel_breakout(over: 12h)\n${body}\nmeasure close_return(after: 1h)`;
  const cases = [
    [L('let a = 12h', 'where session_tail(nyse_regular, last: 30m)'), 'a', 'binding', 'never used'],
    [L('let a = 12h\nlet a = 24h', 'where held("Quiet range", for: a)'), 'a', 'binding', 'duplicate binding'],
    [L('let fri = 1h', 'where held("Quiet range", for: fri)'), 'fri', 'binding', 'conflicts'],
    [L('let a = session_tail(nyse_regular, last: 1h)', 'where a'), 'session_tail(nyse_regular, last: 1h)', 'binding', 'scalar literal'],
    [L('let a = 12h\nlet b = a', 'where held("Quiet range", for: b)'), 'a', 'binding', 'cannot refer'],
    [L('let a = {1h | 60m}', 'where held("Quiet range", for: a)'), '60m', 'sweep', 'duplicate choice'],
    [L('let a = {1h | {2h | 4h}}', 'where held("Quiet range", for: a)'), '{2h | 4h}', 'sweep', 'scalar literals'],
    ['on BTCUSDT 15m\nfind "Wick rejection"\nmeasure close_return(after: [1h, {2h | 4h}])', '{2h | 4h}', 'sweep', 'inside a vector'],
    [Q('where session_tail(nyse_regular, last: {15m | 30m | 45m | 1h | 2h}) and held(quiet_range(width_max: {1% | 2% | 3% | 4% | 5% | 6% | 7% | 8% | 9% | 10% | 11% | 12% | 13%}), for: 48h)'), '{1% | 2% | 3% | 4% | 5% | 6% | 7% | 8% | 9% | 10% | 11% | 12% | 13%}', 'sweep', 'expands to 65 candidate runs'],
  ];
  for (const [src, want, kind, msg] of cases) {
    const d = errorsOf(src).find((e) => e.message.includes(msg));
    ok(d, `expected "${msg}"; got ${JSON.stringify(errorsOf(src).map((e) => e.message))}`);
    if (!d) continue;
    eq(spanText(src, d), want, `span for "${msg}"`);
    eq(d.kind, kind, `kind for "${msg}"`);
  }
  const ok64 = analyze(Q('where session_tail(nyse_regular, last: {15m | 30m | 45m | 1h | 75m | 90m | 105m | 2h}) and held(quiet_range(width_max: {1% | 2% | 3% | 4% | 5% | 6% | 7% | 8%}), for: 48h)'), env);
  ok(ok64.ok && ok64.candidates.length === 64, '8 × 8 = 64 candidates is allowed');
  const viaLet = errorsOf('on BTCUSDT 15m\nlet lb = {12h | 50m}\nfind channel_breakout(over: lb)\nmeasure close_return(after: 1h)').find((e) => e.kind === 'domain');
  ok(viaLet && viaLet.related, 'a domain error inside a let points at the literal and relates the use site');
});

console.log('\nSession endpoints, calendar coverage and DST');
test('session_tail is (close − D, close]: 15:30 out of a 30m tail, 15:45 and 16:00 in (EDT and EST dates)', () => {
  const t30 = 'session_tail(nyse_regular, last: 30m)';
  const t1h = 'session_tail(nyse_regular, last: 1h)';
  const expect = [
    [t30, '2025-03-28T19:30:00Z', F], [t30, '2025-03-28T19:45:00Z', T], [t30, '2025-03-28T20:00:00Z', T], [t30, '2025-03-28T20:15:00Z', F],
    [t1h, '2025-03-28T19:00:00Z', F], [t1h, '2025-03-28T19:15:00Z', T], [t1h, '2025-03-28T19:30:00Z', T],
    [t30, '2025-02-28T20:30:00Z', F], [t30, '2025-02-28T20:45:00Z', T], [t30, '2025-02-28T21:00:00Z', T], [t30, '2025-02-28T20:00:00Z', F],
    [t1h, '2025-02-28T20:00:00Z', F], [t1h, '2025-02-28T20:15:00Z', T],
  ];
  for (const [c, iso, v] of expect) eq(KNAME[cond(c, iso).v], KNAME[v], `${c} at ${iso}`);
  ok(cond(t30, '2025-03-28T19:30:00Z').why.includes('15:30 EDT ∉ (15:30, 16:00]'), 'reason names the half-open interval');
});
test('30–60 minute band = 1h tail and not 30m tail → only 15:15 and 15:30 closes', () => {
  const band = 'session_tail(nyse_regular, last: 1h) and not session_tail(nyse_regular, last: 30m)';
  const day = Date.parse('2025-03-28T00:00:00Z');
  const trues = [];
  for (let i = at('2025-03-28T00:15:00Z'); i <= at('2025-03-29T00:00:00Z'); i++) if (cond(band, isoUTCFull(rec.closeTime(i))).v === T) trues.push(isoUTCFull(rec.closeTime(i)));
  eq(trues, ['2025-03-28T19:15:00Z', '2025-03-28T19:30:00Z'], 'band anchors on 2025-03-28');
  ok(day > 0, 'date');
});
test('known closed dates are false; outside calendar coverage is unknown', () => {
  eq(KNAME[cond('weekday(nyse_regular) = closed', '2025-04-18T19:30:00Z').v], 'true', 'Good Friday is closed');
  eq(KNAME[cond('session_tail(nyse_regular, last: 1h)', '2025-04-18T19:30:00Z').v], 'false', 'no tail on a closed date');
  eq(KNAME[cond('weekday(nyse_regular) = closed', '2025-01-09T20:00:00Z').v], 'true', 'National Day of Mourning (Thursday) closed');
  eq(KNAME[cond('weekday(nyse_regular) = fri', '2025-01-01T00:15:00Z').v], 'unknown', 'New York 2024-12-31 is outside coverage');
  eq(KNAME[cond('session_tail(nyse_regular, last: 30m)', '2025-01-01T00:15:00Z').v], 'unknown', 'tail outside coverage');
  eq(KNAME[cond('weekday(nyse_regular) = closed', '2025-01-01T05:00:00Z').v], 'true', 'New Year’s Day (covered) is closed');
  eq(KNAME[cond('weekday(nyse_regular) = fri', '2025-01-03T21:00:00Z').v], 'true', 'stored weekday');
  const r = run(exampleById('practice').text).r.results[0];
  eq(r.clauseStats[0].U, 1, 'exactly one real event is unknown for weekday (before 2025-01-01T05:00Z)');
});

console.log('\nheld: uninterrupted grid samples, warmup and Kleene');
test('48h at 15m needs 193 samples; first possible true anchor is 52h after the first open', () => {
  const always = 'held(quiet_range(width_max: 100%), for: 48h)';
  const first = rec.t0 + 52 * 3600000;
  eq(KNAME[cond(always, isoUTCFull(first)).v], 'true', 'true at t0 + 52h');
  eq(KNAME[cond(always, isoUTCFull(first - 900000)).v], 'unknown', 'unknown 15m earlier (warmup)');
  ok(cond(always, isoUTCFull(first)).why.includes('all 193 samples'), '193 samples');
  eq(KNAME[cond('quiet_range(width_max: 100%)', isoUTCFull(rec.t0 + 4 * 3600000)).v], 'true', 'state first known at t0 + 4h');
  eq(KNAME[cond('quiet_range(width_max: 100%)', isoUTCFull(rec.t0 + 4 * 3600000 - 900000)).v], 'unknown', 'state unknown before its 16-bar window');
  let firstTrue = null;
  const c = compileBool(ctx, new Checker(env, () => {}).expr(parseExpression(always).ast));
  for (let i = 0; i < rec.n && firstTrue === null; i++) if (c.at(i).v === T) firstTrue = rec.closeTime(i);
  eq(isoUTCFull(firstTrue), '2025-01-03T04:00:00Z', 'scan finds the first true anchor at 52h');
});
test('a known false inside the window disproves held even during warmup', () => {
  const tight = 'held(quiet_range(width_max: 0.1%), for: 48h)';
  eq(KNAME[cond(tight, '2025-01-01T06:00:00Z').v], 'false', 'false despite missing pre-recording samples');
});

console.log('\nMissing coverage (real edges + an in-memory deletion fixture)');
const gapSlot = at('2025-05-01T12:00:00Z');
const gapRec = rec.withoutSlots([gapSlot], 'test fixture: bar 11:45–12:00Z on 2025-05-01 removed in memory');
const G = { ...E, rec: gapRec, ctx: new EvalContext(gapRec, E.calendars) };
test('fixture: absent samples make held unknown unless a known false exists', () => {
  const H2 = 'held(quiet_range(width_max: 2%), for: 48h)';
  eq(KNAME[cond(H2, '2025-05-02T19:15:00Z').v], 'true', 'full data: true');
  const r = cond(H2, '2025-05-02T19:15:00Z', G);
  eq(KNAME[r.v], 'unknown', 'fixture: unknown');
  ok(r.why.includes('no known false'), 'reason says no known false');
  eq(KNAME[cond(H2, '2025-05-01T19:30:00Z', G).v], 'false', 'fixture: a known false (2.27% > 2% at 2025-04-30 16:30Z) still disproves');
  // held(48h) over a 4h state reads bars closing in (t − 52h, t]; anchors whose span excludes the gap are unchanged.
  eq(cond(H2, '2025-05-01T11:45:00Z', G).why, cond(H2, '2025-05-01T11:45:00Z').why, 'before the gap: identical');
  for (const iso of ['2025-05-03T16:00:00Z', '2025-05-04T00:00:00Z', '2025-05-10T12:00:00Z']) {
    eq(KNAME[cond(H2, iso, G).v], KNAME[cond(H2, iso).v], `unaffected value at ${iso} (grid by timestamp, not array adjacency)`);
  }
  // samples s whose window (s − 4h, s] holds the absent 12:00Z bar are unknown, so the true run restarts at 16:00Z
  ok(cond(H2, '2025-05-03T16:00:00Z', G).why.includes('true since 2025-05-01 16:00Z (48h ≥ 48h)'), 'true run restarts after the unknown samples');
  // 2025-05-03T15:45Z: first sample t − 48h = 05-01 15:45Z, whose 4h window starts with the absent 12:00Z bar.
  ok(cond(H2, '2025-05-03T15:45:00Z', G).v !== T, 'the last anchor whose span contains the gap cannot be true');
  eq(KNAME[cond('held("Quiet range", for: 48h)', '2025-05-02T19:15:00Z', G).v], 'unknown', 'the named state behaves the same way');
});
test('fixture: close_return unknown for an absent interior endpoint; censored beyond the recording end', () => {
  const col = compileColumn(G.ctx, { key: 'k', h: 3600000, text: '1h' });
  eq(col.at(at('2025-05-01T11:00:00Z')).status, 'unknown', 'endpoint absent → unknown');
  eq(compileColumn(ctx, { key: 'k', h: 3600000, text: '1h' }).at(at('2025-05-31T23:15:00Z')).status, 'censored', 'beyond end → censored');
  eq(compileColumn(ctx, { key: 'k', h: 3600000, text: '1h' }).at(at('2025-05-31T23:00:00Z')).status, 'observed', 'ends exactly at the recording end → observed');
  const { r } = run('on BTCUSDT 15m\nfind "Wick rejection"\nmeasure close_return(after: [1h, 4h])');
  const s = r.results[0].summary;
  ok(s[1].censored > 0 && s[0].observed + s[0].censored === r.results[0].matches.length, 'censored rows stay in the matches; denominators are per horizon');
  ok(s[1].observed < s[0].observed, 'the 4h column has fewer observed outcomes than 1h');
});
test('fixture: completed_trend is unknown without fallback; channel/state partial windows', () => {
  const trend = 'completed_trend(frame: 4h) = up or completed_trend(frame: 4h) = down or completed_trend(frame: 4h) = flat';
  eq(KNAME[cond(trend, '2025-05-01T12:15:00Z').v], 'true', 'full data: known trend');
  const r = cond(trend, '2025-05-01T12:15:00Z', G);
  eq(KNAME[r.v], 'unknown', 'fixture: unknown');
  ok(r.why.includes('no fallback'), 'no fallback stated');
  eq(KNAME[cond(trend, '2025-05-01T16:00:00Z', G).v], 'true', 'next 4h bar is complete again');
  const brk = run('on BTCUSDT 15m\nfind channel_breakout(over: 12h)\nmeasure close_return(after: 1h)', G).r.results[0];
  const full = run('on BTCUSDT 15m\nfind channel_breakout(over: 12h)\nmeasure close_return(after: 1h)').r.results[0];
  ok(brk.counts.U > full.counts.U, 'more unknown breakouts with a gap');
  ok(brk.counts.T <= full.counts.T, 'a gap never creates breakouts');
});

console.log('\nSweeps versus vectors');
test('a vector makes columns in one run; choices make candidate runs with equal values', () => {
  const vec = run('on BTCUSDT 15m\nfind "Wick rejection"\nwhere weekday(nyse_regular) = fri\nmeasure close_return(after: [1h, 4h])').r;
  const swp = run('on BTCUSDT 15m\nfind "Wick rejection"\nwhere weekday(nyse_regular) = fri\nmeasure close_return(after: {1h | 4h})').r;
  eq(vec.results.length, 1, 'vector: one candidate');
  eq(vec.results[0].columns.length, 2, 'vector: two columns');
  eq(swp.results.length, 2, 'choices: two candidates');
  eq(swp.results.map((x) => x.columns.length), [1, 1], 'choices: one column each');
  for (let k = 0; k < 2; k++) {
    const a = vec.results[0].matches.map((m) => [m.id, m.out[k].status, m.out[k].value]);
    const b = swp.results[k].matches.map((m) => [m.id, m.out[0].status, m.out[0].value]);
    eq(a, b, `column ${k} equals candidate ${k}`);
  }
});
test('a let with choices is one axis however often it is used; inline choices are separate axes in source order', () => {
  const shared = run(exampleById('shared').text);
  eq(shared.a.axes.length, 1, 'one axis');
  eq(shared.a.candidates.map((c) => c.label), ['span=12h', 'span=24h'], 'two candidates');
  ok(shared.a.candidates[1].resolvedText.includes('channel_breakout(over: 24h)') && shared.a.candidates[1].resolvedText.includes('for: 24h)'), 'both references substituted with the same value');
  const two = analyze(Q('where session_tail(nyse_regular, last: {30m | 1h}) and held(quiet_range(width_max: {2% | 3%}), for: 48h)'), env);
  eq(two.candidates.map((c) => c.label), [
    'session_tail.last=30m, quiet_range.width_max=2%', 'session_tail.last=30m, quiet_range.width_max=3%',
    'session_tail.last=1h, quiet_range.width_max=2%', 'session_tail.last=1h, quiet_range.width_max=3%'], 'Cartesian product, first axis outermost');
});

console.log('\nEdit diff and comparison basis');
const practice = run(exampleById('practice').text).r;
test('starter: widening 30m → 1h adds exactly the two 15:30 closes, removes none, with reasons', () => {
  const st = run(exampleById('starter').text).r;
  eq(st.results.map((x) => x.matches.map((m) => isoUTCFull(m.t))), [
    ['2025-05-02T20:00:00Z', '2025-05-30T20:00:00Z'],
    ['2025-03-28T19:30:00Z', '2025-04-25T19:30:00Z', '2025-05-02T20:00:00Z', '2025-05-30T20:00:00Z']], 'starter matches (Quiet range 2.5%)');
  const d = compareResults(st.results[0], st.results[1]);
  eq([d.added.length, d.removed.length, d.kept.length], [2, 0, 2], 'diff');
  eq(st.results[1].survivors, [269, 10, 4], 'funnel: Friday → 1h tail → quiet 48h');
  for (const x of d.added) {
    eq(x.reasons.length, 1, 'exactly one clause explains each added row');
    ok(x.reasons[0].text.includes('15:30 EDT ∉ (15:30, 16:00]') && x.reasons[0].other.text.includes('15:30 EDT ∈ (15:00, 16:00]'), `reason (${x.reasons[0].text})`);
  }
});
test('starter without the quiet clause: widening adds exactly the 15:15/15:30 closes, removes none, with reasons', () => {
  const [a, b] = practice.results;
  eq([a.matches.length, b.matches.length], [5, 10], 'match counts');
  const d = compareResults(a, b);
  eq(d.mode, 'occurrence identity', 'same detector → identity comparison');
  eq(d.added.map((x) => isoUTCFull(x.row.t)), ['2025-03-21T19:15:00Z', '2025-03-28T19:30:00Z', '2025-04-04T19:30:00Z', '2025-04-25T19:30:00Z', '2025-05-16T19:30:00Z'], 'added anchors');
  eq(d.removed.length, 0, 'none removed');
  eq(d.kept.length, 5, 'kept');
  eq(d.changes, [{ slot: 'where', index: 1, from: 'session_tail(nyse_regular, last: 30m)', to: 'session_tail(nyse_regular, last: 1h)' }], 'changed condition');
  for (const x of d.added) {
    const r0 = x.reasons[0];
    ok(r0.clause.includes('session_tail(nyse_regular, last: 30m)') && r0.v === F && r0.text.includes('∉ (15:30, 16:00]'), `reason before (${r0.text})`);
    ok(r0.other && r0.other.v === T && r0.other.text.includes('∈ (15:00, 16:00]'), 'reason after');
  }
});
test('at the design’s 2% suggestion the starter would be sparse (1 match per tail, no diff)', () => {
  const st = run(exampleById('starter').text.replace('held("Quiet range", for: 48h)', 'held(quiet_range(width_max: 2%), for: 48h)')).r;
  eq(st.results.map((x) => x.matches.map((m) => isoUTCFull(m.t))), [['2025-05-02T20:00:00Z'], ['2025-05-02T20:00:00Z']], '2% matches');
  const d = compareResults(st.results[0], st.results[1]);
  eq([d.added.length, d.removed.length, d.kept.length], [0, 0, 1], 'no diff at 2%');
});
test('editing a scalar into a sweep compares specific candidates; basis labelled', () => {
  const before = run(Q('where weekday(nyse_regular) = fri\nwhere session_tail(nyse_regular, last: 30m)')).r.results[0];
  const after = run(Q('where weekday(nyse_regular) = fri\nwhere session_tail(nyse_regular, last: {30m | 1h})')).r.results;
  const d0 = compareResults(before, after[0], { basis: 'run #1' });
  const d1 = compareResults(before, after[1], { basis: 'run #1' });
  eq([d0.added.length, d0.removed.length, d0.changes.length], [0, 0, 0], 'candidate 30m equals the scalar run');
  eq([d1.added.length, d1.removed.length], [5, 0], 'candidate 1h adds 5');
  eq(d1.basisLabel, 'run #1', 'basis label');
});
test('different detectors compare by anchor time: every 24h breakout is a 12h breakout', () => {
  const t = run(exampleById('transfer').text).r.results;
  const d = compareResults(t[0], t[1]);
  eq(d.mode, 'anchor time (detectors differ)', 'mode');
  eq(d.added.length, 0, '24h adds nothing over 12h');
  eq(d.removed.length, t[0].matches.length - t[1].matches.length, 'removed = difference');
  ok(d.removed.every((x) => x.reasons[0].side === 'detector'), 'reasons come from the 24h detector');
});

console.log('\nGrouping invariant and group → filter');
test('transfer: buckets partition the matches; the up bucket equals the filter run', () => {
  const g = run(exampleById('transfer').text).r.results;
  const f = run(exampleById('transfer-filter').text).r.results;
  eq(g.map((x) => x.matches.length), [461, 261], 'breakout counts');
  for (let k = 0; k < 2; k++) {
    eq(g[k].groups.reduce((a, b) => a + b.count, 0), g[k].matches.length, `candidate ${k}: Σ buckets = matches`);
    eq(g[k].groups.find((b) => b.key === 'up').rows.map((r) => r.id), f[k].matches.map((r) => r.id), `candidate ${k}: up bucket = filter matches`);
    const d = compareResults(g[k], f[k]);
    eq(d.removed.length, g[k].matches.length - f[k].matches.length, 'filter removes the other buckets');
    ok(d.removed.every((x) => x.reasons[0].clause.includes('completed_trend(frame: 4h) = up') && x.reasons.length === 1), 'every removal names the new where clause');
  }
  eq(g.map((x) => x.groups.map((b) => [b.key, b.count])), [[['up', 358], ['down', 103], ['flat', 0]], [['up', 214], ['down', 47], ['flat', 0]]], 'bucket counts');
});
test('real data: an unknown bucket appears (calendar coverage) and still partitions the population', () => {
  const r = run('on BTCUSDT 15m\nfind "Wick rejection"\ngroup by weekday(nyse_regular)\nmeasure close_return(after: [1h, 4h])').r.results[0];
  const unk = r.groups.find((b) => b.key === 'unknown');
  ok(unk && unk.count === 1, 'one unknown (New York date 2024-12-31 is outside coverage)');
  ok(unk && unk.rows.every((x) => x.t < cal.covStart), 'unknown only before calendar coverage starts');
  eq(r.groups.reduce((a, b) => a + b.count, 0), r.matches.length, 'Σ buckets = matches');
  eq(r.matches.length, 2077, 'grouping keeps every event');
  const f = run('on BTCUSDT 15m\nfind "Wick rejection"\nwhere weekday(nyse_regular) = fri\nmeasure close_return(after: [1h, 4h])').r.results[0];
  eq(f.clauseStats[0].U, unk.count, 'the filter sees the same unknown and drops it (only true passes)');
  eq(f.matches.map((m) => m.id), r.groups.find((b) => b.key === 'fri').rows.map((m) => m.id), 'fri bucket = fri filter');
});
test('fixture: a gap inside an event’s 4h frame bar gives an unknown trend bucket (no fallback)', () => {
  const wr = run('on BTCUSDT 15m\nfind "Wick rejection"\nmeasure close_return(after: 1h)').r.results[0];
  const FR = 4 * 3600000;
  const pick = wr.matches.find((m) => m.t > Date.parse('2025-02-01T00:00:00Z') && m.t % FR !== 0);
  const E4 = Math.floor(pick.t / FR) * FR;
  const fx = rec.withoutSlots([rec.slotClosingAt(E4)], 'test fixture: last constituent of a 4h bar removed');
  const B = { ...E, rec: fx, ctx: new EvalContext(fx, E.calendars) };
  const g = run('on BTCUSDT 15m\nfind "Wick rejection"\ngroup by completed_trend(frame: 4h)\nmeasure close_return(after: 1h)', B).r.results[0];
  const unk = g.groups.find((b) => b.key === 'unknown');
  ok(unk && unk.rows.some((x) => x.id === pick.id), 'the picked event lands in the unknown bucket');
  ok(unk && unk.rows.every((x) => x.t >= E4 && x.t < E4 + FR), 'unknown only while that 4h bar is the expected one');
  eq(g.groups.reduce((a, b) => a + b.count, 0), g.matches.length, 'Σ buckets = matches');
});

console.log('\nIdentity, availability and arithmetic');
test('named definition, typed call and ratio spellings share one occurrence identity', () => {
  const forms = ['"Wick rejection"', 'wick_rejection(body_max: 35%, wick_min: 45%)', 'wick_rejection(body_max: 0.35, wick_min: 0.45)', 'wick_rejection()'];
  const ids = forms.map((f) => run(`on BTCUSDT 15m\nfind ${f}\nwhere weekday(nyse_regular) = fri\nmeasure close_return(after: 1h)`).r.results[0].matches.map((m) => m.id));
  for (let k = 1; k < forms.length; k++) eq(ids[k], ids[0], `${forms[k]} ≡ ${forms[0]}`);
  const other = run('on BTCUSDT 15m\nfind wick_rejection(body_max: 30%)\nwhere weekday(nyse_regular) = fri\nmeasure close_return(after: 1h)').r.results[0].matches.map((m) => m.id);
  ok(!other.some((id) => ids[0].includes(id)), 'different parameters → different identities');
  const st = run(exampleById('starter').text).r.results[1].matches[0].id;
  ok(practice.results[1].matches.some((m) => m.id === st), 'identity is independent of where clauses and horizons');
});
test('no post-anchor data: conditions evaluate identically on a recording truncated at the anchor', () => {
  const texts = ['weekday(nyse_regular) = fri', 'session_tail(nyse_regular, last: 1h)', 'held("Quiet range", for: 48h)', 'completed_trend(frame: 4h) = up', 'range_contained(over: 52h, width_max: 6%)', 'quiet_friday_close(width_max: 3%)', '"Wick rejection"', 'channel_breakout(over: 12h)'];
  const anchors = [...practice.results[1].matches.map((m) => m.i), at('2025-01-03T04:00:00Z'), at('2025-05-02T19:15:00Z'), at('2025-03-09T07:00:00Z')];
  for (const i of anchors) {
    const tr = rec.truncatedAfter(i);
    const B = { ...E, rec: tr, ctx: new EvalContext(tr, E.calendars) };
    for (const t of texts) {
      const a = cond(t, isoUTCFull(rec.closeTime(i)));
      const b = cond(t, isoUTCFull(rec.closeTime(i)), B);
      eq([a.v, a.why], [b.v, b.why], `${t} at ${isoUTCFull(rec.closeTime(i))}`);
    }
  }
});
test('fixed-point thresholds are exact and inclusive (synthetic boundary fixture, not market data)', () => {
  const csv = 'open_ms,open,high,low,close,volume\n'
    + '1735689600000,100.00,101.00,99.00,100.70,1\n' // body 35.0% exactly → true
    + '1735690500000,100.00,101.00,99.00,100.71,1\n' // body 35.5% → false
    + '1735691400000,99.90,101.00,99.00,100.00,1\n' // lower wick 45.0% exactly → true
    + '1735692300000,99.89,101.00,99.00,100.00,1\n' // lower wick 44.5% → false
    + '1735693200000,100.00,100.00,100.00,100.00,1\n'; // zero range → false
  const prov = { columns: ['open_ms', 'open', 'high', 'low', 'close', 'volume'], timestamp_role: 'open', interval_ms: 900000, row_count: 5, instrument: 'Synthetic BTCUSDT fixture' };
  const fr = parseRecording(csv, prov, null);
  const B = { ...E, rec: fr, ctx: new EvalContext(fr, E.calendars) };
  const vals = [0, 1, 2, 3, 4].map((i) => cond('"Wick rejection"', isoUTCFull(fr.closeTime(i)), B).v);
  eq(vals.map((v) => KNAME[v]), ['true', 'false', 'true', 'false', 'false'], 'inclusive exact boundaries');
  eq([parseCents('93576.0'), parseCents('100.7'), parseCents('1.005'), parseCents('-1')], [9357600, 10070, null, null], 'cents parsing');
  eq([ratToDecimalText(ratFromText('35', true)), ratToDecimalText({ num: 1n, den: 8n }), ratToPercentText(ratFromText('0.025'))], ['0.35', '0.125', '2.5%'], 'exact decimal text');
});

console.log('\nExtension artifact (agent-authored composition)');
test('quiet_friday_close@1 registers from its artifact and passes its recorded conformance cases', () => {
  const x = E.extensions.find((e) => e.file.endsWith('quiet_friday_close.v1.json'));
  ok(x && x.ok, `registered (${x && x.errors.join('; ')})`);
  const res = runConformance(E, x.def);
  eq(res.length, 11, 'cases');
  for (const r of res) ok(r.pass, `${r.anchor} ${r.call}: expected ${r.expect}, engine ${r.got} (${r.why})`);
  ok(res.some((r) => r.expect === 'true') && res.some((r) => r.expect === 'false') && res.some((r) => r.expect === 'unknown'), 'positive, negative and unknown examples');
});
test('the composition equals its expansion, and replay pins are enforced', () => {
  const ext = run(exampleById('extension').text).r.results.map((x) => x.matches.map((m) => m.id));
  const st = run(exampleById('starter').text).r.results.map((x) => x.matches.map((m) => m.id));
  eq(ext, st, 'quiet_friday_close(last: {30m | 1h}) with its defaults ≡ the starter’s two candidates');
  const art = JSON.parse(new TextDecoder().decode(readBytes('extensions/quiet_friday_close.v1.json')));
  const bad1 = registerExtension(new Registry(), { ...art, depends: [{ name: 'held', version: 2 }] }, env);
  ok(!bad1.ok && bad1.errors[0].includes('held@2'), 'a dependency version mismatch is rejected');
  const bad2 = registerExtension(new Registry(), { ...art, body: 'session_tail(nyse_regular, last: {30m | 1h})' }, env);
  ok(!bad2.ok && bad2.errors[0].includes('choices'), 'a body with choices is rejected');
  const bad3 = registerExtension(new Registry(), { ...art, body: 'completed_trend(frame: 4h)' }, env);
  ok(!bad3.ok, 'a non-condition body is rejected');
  const ok2 = registerExtension(new Registry(), art, env);
  ok(ok2.ok && ok2.def.params.map((p) => p.name).join() === 'last,quiet_for,width_max', 'signature comes from the artifact');
});

console.log('\nCoverage behind the Quiet range default, editor assistance, determinism');
test('coverage table (bars only, no returns): 2% is sparse; the chosen 2.5% is the first width whose widening adds matches', () => {
  const cov = quietCoverage(E);
  const row = (w) => cov.find((r) => r.width === w);
  eq(E.registry.named.get('Quiet range').args.width_max, '2.5%', 'named preset pins 2.5%');
  eq([row('2%').starter30m, row('2%').starter1h], [1, 1], '2% starter (as in the independent Mac reference)');
  eq([row('2.5%').starter30m, row('2.5%').starter1h], [2, 4], '2.5% starter');
  eq([row('3%').starter30m, row('3%').starter1h], [2, 5], '3% starter');
  const firstWidening = cov.find((r) => r.starter1h > r.starter30m);
  eq(firstWidening && firstWidening.width, '2.5%', 'smallest listed width where widening reveals new matches');
  // independent brute force (plain integer loops over the cents arrays) at 2% and 2.5%
  for (const [w, num, den] of [['2%', 2, 100], ['2.5%', 25, 1000]]) {
    const st = new Int8Array(rec.n);
    for (let i = 15; i < rec.n; i++) {
      let hi = -Infinity; let lo = Infinity;
      for (let j = i - 15; j <= i; j++) { hi = Math.max(hi, rec.H[j]); lo = Math.min(lo, rec.L[j]); }
      st[i] = (hi - lo) * den <= num * rec.C[i] ? 1 : 0;
    }
    let stateTrue = 0; let heldTrue = 0; let runLen = 0;
    for (let i = 0; i < rec.n; i++) { stateTrue += st[i]; runLen = st[i] ? runLen + 1 : 0; if (runLen >= 193) heldTrue++; }
    eq([row(w).stateTrue, row(w).heldTrue], [stateTrue, heldTrue], `engine equals brute force at ${w}`);
  }
  for (let k = 1; k < cov.length; k++) ok(cov[k].stateTrue >= cov[k - 1].stateTrue && cov[k].heldTrue >= cov[k - 1].heldTrue, 'monotone in width');
});
test('completions come from registry signatures', () => {
  const lbl = (text) => completionsAt(text, text.length, E.registry, env).items.map((i) => i.label);
  eq(lbl('on BTCUSDT 15m\nfind "Wick rejection"\nwhere session_tail(nyse_regular, '), ['last:'], 'positional used → only last:');
  ok(lbl('on BTCUSDT 15m\nfind ').includes('"Wick rejection"'), 'events after find');
  eq(lbl('on BTCUSDT 15m\nfind "Wick rejection"\nwhere weekday(nyse_regular) = '), ['mon', 'tue', 'wed', 'thu', 'fri', 'closed'], 'enum values');
  ok(lbl('on BTCUSDT 15m\nfind "Wick rejection"\nwhere ').includes('quiet_friday_close'), 'extension appears automatically');
  ok(lbl('on BTCUSDT 15m\nfind "Wick rejection"\nwhere ses').join() === 'session_tail', 'prefix filter');
  ok(lbl('on BTCUSDT 15m\nfind "Wick rejection"\nmeasure close_return(after: ').includes('[1h, 4h]'), 'list param offers a vector');
});
test('every template offered by the guided menus and completions is valid in its slot', () => {
  for (const f of E.registry.implemented()) {
    if (f.kind === 'condition' || f.kind === 'categorical') ok(analyze(Q(`where ${whereExample(f)}`), env).ok, `where ${whereExample(f)}`);
    if (f.kind === 'categorical' || f.kind === 'condition') {
      const g = f.kind === 'categorical' ? f.example.replace(/\s*=.*$/, '') : f.example;
      ok(analyze(`on BTCUSDT 15m\nfind "Wick rejection"\ngroup by ${g}\nmeasure close_return(after: 1h)`, env).ok, `group by ${g}`);
    }
    if (f.kind === 'event') ok(analyze(`on BTCUSDT 15m\nfind ${f.example}\nmeasure close_return(after: 1h)`, env).ok, `find ${f.example}`);
    if (f.kind === 'outcome') ok(analyze(`on BTCUSDT 15m\nfind "Wick rejection"\nmeasure ${f.example}`, env).ok, `measure ${f.example}`);
  }
  const prefix = 'on BTCUSDT 15m\nfind "Wick rejection"\nwhere ';
  const where = completionsAt(prefix, prefix.length, E.registry, env).items;
  ok(where.length >= 6, 'where completions offered');
  for (const it of where) ok(analyze(Q(`where ${it.insert}`), env).ok, `completion ${it.insert}`);
});
test('guided edits are AST edits printed to canonical text (same structure both ways)', () => {
  const { ast } = parse(exampleById('practice').text);
  const path = ['wheres', 1, 'args', 1, 'value'];
  const edited = setAt(ast, path, { k: 'dur', text: '2h', amount: 2, unit: 'h', ms: 7200000 });
  const text = printQuestion(edited);
  ok(text.includes('session_tail(nyse_regular, last: 2h)'), 'printed edit');
  ok(sameStructure(parse(text).ast, edited), 're-parse equals the edited AST');
  ok(analyze(text, env).ok, 'edited text validates');
});
test('robustness: thousands of random edits never throw; valid ones run; spans stay inside the text', () => {
  let seed = 20261113;
  const rnd = () => { seed |= 0; seed = (seed + 0x6d2b79f5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  const alphabet = ['(', ')', '[', ']', '{', '}', ',', ':', '|', '%', '=', '!', '<', '"', '\\', '-', ' ', '\n', '0', '1', '5', 'm', 'h', 'd', 'x', '_', 'a', 'é', 'and', 'or', 'not', 'where', 'let', '{1h | 2h}', '[1h, 4h]', '"Quiet range"'];
  let valid = 0;
  let total = 0;
  for (const ex of EXAMPLES) {
    for (let k = 0; k < 220; k++) {
      let s = ex.text;
      const edits = 1 + Math.floor(rnd() * 3);
      for (let e = 0; e < edits; e++) {
        const p = Math.floor(rnd() * (s.length + 1));
        const r = rnd();
        if (r < 0.4) s = s.slice(0, p) + s.slice(p + 1 + Math.floor(rnd() * 4));
        else if (r < 0.8) s = s.slice(0, p) + alphabet[Math.floor(rnd() * alphabet.length)] + s.slice(p);
        else { const q = Math.floor(rnd() * s.length); s = s.slice(0, p) + s.slice(q, q + 6) + s.slice(p); }
      }
      total++;
      const a = analyze(s, env);
      for (const d of a.errors) ok(d.start >= 0 && d.end <= s.length && d.start <= d.end && typeof d.message === 'string', `bad span ${JSON.stringify(d)} for ${JSON.stringify(s)}`);
      if (a.ok) { valid++; for (const c of a.candidates) runCandidate(ctx, c); }
      completionsAt(s, Math.floor(rnd() * (s.length + 1)), E.registry, env);
    }
  }
  // literal substitutions (including out-of-domain values) keep most questions parseable and exercise evaluation
  const durs = ['15m', '30m', '45m', '1h', '2h', '4h', '6h', '12h', '24h', '48h', '50m', '7h', '1d', '5h'];
  const pcts = ['0%', '1%', '2%', '2.5%', '3%', '35%', '45%', '100%', '150%'];
  let litValid = 0;
  let litTotal = 0;
  for (const ex of EXAMPLES.filter((x) => !x.id.startsWith('err-'))) {
    const toks = [];
    const re = /\b\d+(?:\.\d+)?(?:[mhd]\b|%)/g;
    for (let m; (m = re.exec(ex.text));) toks.push([m.index, m[0]]);
    for (let k = 0; k < 40; k++) {
      let s = ex.text;
      for (const [pos, lit] of toks.slice().reverse()) {
        if (rnd() < 0.5) continue;
        const pool = lit.endsWith('%') ? pcts : durs;
        s = s.slice(0, pos) + pool[Math.floor(rnd() * pool.length)] + s.slice(pos + lit.length);
      }
      litTotal++;
      const a = analyze(s, env);
      for (const d of a.errors) ok(d.start >= 0 && d.end <= s.length && d.start <= d.end, `bad span for ${JSON.stringify(s)}`);
      if (a.ok) { litValid++; for (const c of a.candidates) runCandidate(ctx, c); }
    }
  }
  console.log(`    (${total} random edits: ${valid} valid; ${litTotal} literal substitutions: ${litValid} valid and evaluated, the rest rejected with spans)`);
  ok(litValid > litTotal / 4 && litValid < litTotal, `literal family should mix valid and domain errors (${litValid}/${litTotal})`);
});
test('runs are deterministic', () => {
  const sig = () => JSON.stringify(run(exampleById('transfer').text).r.results.map((x) => [x.matches.map((m) => [m.id, m.out.map((o) => o.value)]), x.summary, x.groups.map((g) => g.count)]));
  eq(sig(), sig(), 'two runs');
});
test('every browser module passes a syntax check', () => {
  for (const f of ['src/app.js', 'src/ui/guided.js', 'src/ui/chart.js', 'src/ui/dom.js']) execFileSync(process.execPath, ['--check', path.join(ROOT, f)]);
});

console.log(`\n${passed} passed, ${failures.length} failed`);
if (failures.length) { console.log('\nFailures:'); for (const f of failures) console.log(`  - ${f}`); process.exit(1); }
