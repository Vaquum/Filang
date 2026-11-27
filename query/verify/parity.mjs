// The bench's answers on the shared engine against the JavaScript reference engine it used before, on the pinned
// recording and without a browser. Every question the bench's vocabulary can write is asked both ways, and every
// figure the bench draws from the answer must be the same: runs, counts, each line's verdict on each close, groups,
// outcomes and their values. Reasons are compared as text and reported, since wording is the engine's to choose.
// Run from the repository root, after study/prepare_recording.py and bindings/build.py:
//   node query/verify/parity.mjs [--timing] [--reasons]
import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { install, ROOT } from './site.mjs';

await install();
const { engine, run, count, load, rec, nyText, HEAD, ANY_CLOSE, T } = await import('/shared/filang.js');
const { PATTERNS, PRESETS, make, toText, clauseText, fromText } = await import('/shared/vocab.js');
const { loadEnvironment } = await import('../../study/verify/node-env.js');
const { analyze } = await import('../../study/src/check.js');
const { runAnalysis } = await import('../../study/src/engine.js');

const recording = await load();
const old = loadEnvironment();
const R = rec();
const baselineDir = process.env.FILANG_BASELINE_ENGINE_DIR;
let baseline;
if (baselineDir) {
  const { FilangEngine } = await import(pathToFileURL(resolve(baselineDir, 'index.mjs')));
  baseline = await FilangEngine.create(await readFile(resolve(baselineDir, 'filang_engine.wasm')));
  baseline.loadCsv(recording.csv, R.barMs, { instrument: R.instrument });
  baseline.setCalendar();
}

// ---- the recording the charts read is the recording the reference engine reads
assert.deepEqual([R.n, R.presentCount, R.barMs, R.t0, R.instrument, R.venue, R.barText], [old.rec.n, old.rec.presentCount, old.rec.barMs, old.rec.t0, old.rec.instrument, old.rec.venue, old.rec.barText]);
for (const k of ['O', 'H', 'L', 'C', 'present']) assert.deepEqual(Array.from(R[k]), Array.from(old.rec[k]), `${k} of every slot`);

// ---- the questions
const question = (find, wheres = [], extra = {}) => ({ find: { join: 'or', items: [].concat(find) }, wheres, split: null, horizons: ['1h', '4h'], ...extra });
const texts = new Map();
const add = (name, text) => texts.set(text, name);
for (const p of PRESETS) add('preset ' + p.id, p.text);
for (const p of PATTERNS) add('candle ' + p.id, toText(question(make('pattern', { p: p.id }))));
for (const side of ['low', 'high']) for (const over of ['1h', '4h', '24h']) for (const within of ['0', '3', '8']) add('reclaim', toText(question(make('reclaim', { side, over, within }))));
for (const over of ['1h', '4h', '12h', '48h']) add('breakout', toText(question(make('breakout', { over }))));
for (const [a, rel, b, back] of [['close', 'above', 'high', '1'], ['low', 'below', 'low', '1'], ['open', 'at_or_above', 'close', '2'], ['high', 'at_or_below', 'high', '4']]) add('relation', toText(question(make('relation', { a, rel, b, back }))));
add('wick rejection', toText(question(make('wickrej'))));
const any = { type: 'raw', args: { text: ANY_CLOSE } };
const conds = [];
for (const part of ['lower_wick', 'upper_wick', 'body']) conds.push(make('share', { part }), make('share', { part, min: '80%' }), make('sharemax', { part }), make('sharemax', { part, max: '10%' }));
for (const min of ['1.25', '2', '3']) conds.push(make('rangex', { min }), make('rangex', { min, over: '24h' }));
for (const side of ['high', 'low']) conds.push(make('near', { side }), make('near', { side, over: '24h', within: '1%' }));
for (const day of ['mon', 'tue', 'wed', 'thu', 'fri', 'closed']) conds.push(make('weekday', { day }));
for (const last of ['15m', '30m', '1h', '2h']) conds.push(make('tail', { last }));
for (const frame of ['1h', '4h', '1d']) for (const dir of ['up', 'down']) conds.push(make('trend', { frame, dir }));
for (const f of ['4h', '24h', '72h']) conds.push(make('quiet', { for: f }), make('quiet', { for: f, width: '1%' }));
for (const c of conds) { add('condition', toText(question(any, [c]))); add('negated', toText(question(any, [{ ...c, not: true }]))); }
// the patterns as conditions, several lines at once, a muted line, both joins, both groups, and compared values
add('lines', toText(question(make('reclaim'), [make('share'), make('rangex'), make('trend'), make('pattern', { p: 'hammer' })])));
add('muted', toText(question(make('breakout'), [make('trend'), { ...make('quiet'), off: true }, make('near')])));
add('or', toText({ ...question([make('pattern', { p: 'hammer' }), make('wickrej'), make('reclaim')]) }));
add('and', toText({ ...question([make('pattern', { p: 'hammer' }), make('wickrej')]), find: { join: 'and', items: [make('pattern', { p: 'hammer' }), make('wickrej')] } }));
for (const split of [make('weekday'), make('trend'), make('trend', { frame: '1d' })]) { add('split', toText(question(make('pattern', { p: 'hammer' }), [], { split }))); add('split', toText(question(any, [make('share')], { split }))); }
add('compare', toText(question(make('wickrej', { body: ['25%', '35%'], wick: ['45%', '55%'] }), [make('weekday', { day: 'fri' })])));
add('compare', toText(question(make('reclaim', { over: ['4h', '12h', '24h'] }), [make('share', { min: ['40%', '60%'] })], { split: make('trend') })));
add('horizons', toText(question(make('breakout'), [], { horizons: ['15m', '30m', '1h', '2h', '4h', '8h', '24h'] })));
add('no measure', toText(question(make('breakout'), [make('trend')], { horizons: [] })));
for (const g1 of ['g1:o:0,1,2,2,u', 'g1:o:0,1,3,4,u;2,3,5,6,u', 'g1:o:0,1,2,3,d;0,0,1,2,u;1,2,4,5,u']) for (const recorded of [false, true]) add('drawing', toText(question(make('drawing', { g1, recorded }))));
add('held', `${HEAD}\nfind candle_window(candle_relation(price(high, bars_ago: 1), is: below, right: price(high, bars_ago: 0)) and candle_relation(price(close, bars_ago: 0), is: above, right: price(open, bars_ago: 0)), bars: 2)\nmeasure close_return(after: [1h, 4h])`);
add('let', `${HEAD}\nlet span = 4h\nfind breach_reclaim(prior_low(over: span))\nwhere range_multiple(over: span, min: 1.5)\nmeasure close_return(after: [1h, span])`);
// questions that do not check: both engines must refuse them
const refused = [`${HEAD}\nfind nope()`, `${HEAD}\nfind hammer(\nwhere x`, `${HEAD}\nfind hammer\nwhere weekday(nyse_regular) = someday`, `${HEAD}\nfind channel_breakout(over: 7m)`, 'on ETHUSDT 15m\nfind hammer', `${HEAD}\nwhere hammer`];

// ---- ask both
const asked = (text) => { const a = analyze(text, old.env); return a.ok ? runAnalysis(old.ctx, a, { digestVerified: old.digestVerified }) : null; };
const tally = { questions: 0, runs: 0, rows: 0, verdicts: 0, outcomes: 0, reasons: 0, reasonsDiffer: 0 };
// Wording is grouped by its shape: figures, times and candle names aside, each kind of difference is listed once.
const shapeOf = (t) => String(t).replace(/\d{4}-\d{2}-\d{2}( \d{2}:\d{2})?Z?/g, '<time>').replace(/-?\d+(\.\d+)?/g, '#');
const kinds = new Map();
const reason = (was, now, where) => {
  tally.reasons++;
  if (was === now) return;
  tally.reasonsDiffer++;
  const kind = shapeOf(was) + ' → ' + shapeOf(now);
  if (!kinds.has(kind)) kinds.set(kind, { n: 0, where, was, now });
  kinds.get(kind).n++;
};
const timing = { old: 0, now: 0 };
const seen = (o) => [o.status, o.status === 'observed' ? o.value : null];

for (const [text, name] of texts) {
  if (baseline) {
    assert.deepEqual(engine.check(text), baseline.check(text), text);
    assert.deepEqual(engine.describeStudy(text), baseline.describeStudy(text), text);
    assert.deepEqual(engine.study(text), baseline.study(text), text);
  }
  const t0 = performance.now(); const was = asked(text); const t1 = performance.now();
  const now = run(text); for (const r of now.results) void r.rows;
  const t2 = performance.now();
  timing.old += t1 - t0; timing.now += t2 - t1;
  assert.ok(was, `the reference engine refuses a question of the corpus (${name}):\n${text}`);
  assert.equal(now.ok, true, `${name}: ${JSON.stringify(now.errors)}\n${text}`);
  tally.questions++;
  assert.equal(now.analysis.axes.length, was.results[0].cand.assignment.length, `${name}: compared axes`);
  assert.deepEqual(now.results.map((r) => r.cand.assignment.map((a) => [a.axis, a.value, a.valueIndex])), was.results.map((r) => r.cand.assignment.map((a) => [a.axis, a.value, a.valueIndex])), `${name}: runs and their values\n${text}`);
  assert.deepEqual(now.manifest.candidates.map((c) => c.label), was.manifest.candidates.map((c) => c.label), `${name}: run labels`);
  assert.equal(count(text.slice(HEAD.length + 1)), was.results[0].matches.length, `${name}: the count of the first run\n${text}`);
  now.results.forEach((r, ci) => {
    const w = was.results[ci]; const at = `${name}, run ${ci}\n${text}`;
    tally.runs++;
    assert.deepEqual([r.counts.T, r.counts.U], [w.counts.T, w.counts.U], `${at}: pattern closes and unknowns`);
    assert.deepEqual(r.survivors, w.survivors, `${at}: closes left after each line`);
    assert.deepEqual(r.clauseStats, w.clauseStats.map((c) => ({ T: c.T, F: c.F, U: c.U })), `${at}: verdicts per line`);
    assert.deepEqual(r.columns.map((c) => c.text), w.columns.map((c) => c.text), `${at}: measured columns`);
    assert.equal(r.rows.length, w.rows.length, `${at}: rows`);
    if (baseline) {
      let start = 0;
      do {
        const options = { candidate: ci, start };
        const page = engine.studyRows(text, options);
        assert.deepEqual(page, baseline.studyRows(text, options), `${at}: page ${start}`);
        start = page.next;
      } while (start !== null);
    }
    for (let q = 0; q < r.rows.length; q++) {
      const a = r.rows[q]; const b = w.rows[q];
      assert.deepEqual([a.i, a.t, a.failAt, a.pass, a.detector], [b.i, b.t, b.failAt, b.pass, b.detector], `${at}: row ${q}`);
      assert.deepEqual(a.results.map((x) => x.v), b.results.map((x) => x.v), `${at}: row ${q}, each line`);
      assert.deepEqual(a.out.map(seen), b.out.map(seen), `${at}: row ${q}, outcomes`);
      tally.rows++; tally.verdicts += a.results.length; tally.outcomes += a.out.length;
    }
    assert.deepEqual(r.matches.map((x) => x.i), w.matches.map((x) => x.i), `${at}: the answer`);
    assert.deepEqual(r.summary, w.summary.map((x) => ({ observed: x.observed, positive: x.positive, median: x.median, mean: x.mean })), `${at}: the answer's summary per column`);
    assert.deepEqual(r.groups?.map((g) => [g.key, g.label, g.count, g.rows.map((x) => x.i)]) ?? null, w.groups?.map((g) => [g.key, g.label, g.count, g.rows.map((x) => x.i)]) ?? null, `${at}: groups`);
    // reasons, on a handful of closes of every run
    const step = Math.max(1, Math.floor(r.rows.length / 5));
    for (let q = 0; q < r.rows.length; q += step) {
      const a = r.rows[q]; const b = w.rows[q];
      if (baseline) {
        const options = { candidate: ci };
        assert.deepEqual(engine.studyClose(text, a.t, options),
          baseline.studyClose(text, a.t, options), `${at}: explanation at ${a.t}`);
      }
      reason(w.event.series.why(b.i), r.event.series.why(a.i), `${name}: event`);
      a.results.forEach((x, k) => reason(b.results[k].why, x.why, `${name}: line ${k}`));
      a.out.forEach((o, k) => reason(b.out[k].why, o.why, `${name}: outcome ${k}`));
      const ev = w.event.series.evidence?.(b.i) ?? null;
      assert.deepEqual(r.event.series.evidence(a.i), ev ? { level: ev.level, breach: ev.breach } : null, `${at}: the reclaim's level and breach at row ${q}`);
    }
  });
}

// ---- what the inspector asks about one close: a line's verdict and a group's key at any slot, an event at any slot
const slots = []; for (let i = 3; i < R.n; i += 997) slots.push(i);
for (const c of conds) {
  const text = `${HEAD}\nfind ${ANY_CLOSE}\nwhere ${clauseText(c)}`; const was = asked(text).results[0]; const now = run(text).results[0];
  for (const i of slots) { const a = now.clauses[0].at(i); const b = was.clauses[0].at(i); assert.equal(a.v, b.v, `${clauseText(c)} at slot ${i}`); reason(b.why, a.why, `at a close: ${clauseText(c)}`); }
  assert.equal(now.survivors[0], was.survivors[0]);
}
for (const expr of ['weekday(nyse_regular)', 'completed_trend(frame: 4h)', 'completed_trend(frame: 1d)']) {
  const text = `${HEAD}\nfind ${ANY_CLOSE}\ngroup by ${expr}`; const was = asked(text).results[0]; const now = run(text).results[0];
  for (const i of slots) assert.equal(now.group.at(i).key, was.group.at(i).key, `${expr} at slot ${i}`);
}
for (const p of PATTERNS) {
  const text = `${HEAD}\nfind ${p.id}`; const was = asked(text).results[0]; const now = run(text).results[0];
  assert.deepEqual(Array.from(now.event.series.vals).map((v) => v === T), Array.from(was.event.series.vals).map((v) => v === T), `${p.id} at every slot`);
}
for (const i of slots) {
  const t = R.closeTime(i); const day = old.cal.dayAt(t);
  assert.equal(nyText(t), day.kind === 'session' ? `${day.s.weekday.toUpperCase()} ${old.cal.localHM(t, day.s)}` : day.kind === 'closed' ? 'no session' : 'outside calendar', `the New York clock at slot ${i}`);
}

// ---- every name a bench module imports from another is one that module provides. The page needs a browser, so
// its modules are read here, not run: a missing name would leave the page blank
{
  const sources = new Map();
  for (const dir of ['shared', 'bench']) for (const file of await readdir(join(ROOT, 'query', dir))) if (file.endsWith('.js')) sources.set(`/${dir}/${file}`, await readFile(join(ROOT, 'query', dir, file), 'utf8'));
  const provided = (source) => new Set([...source.matchAll(/^export\s+(?:async\s+)?(?:const|let|function\*?|class)\s+([\w$]+)/gm)].map((m) => m[1])
    .concat([...source.matchAll(/^export\s*\{([^}]+)\}/gm)].flatMap((m) => m[1].split(',').map((n) => n.trim().split(/\s+as\s+/).pop()))));
  let names = 0;
  for (const [path, source] of sources) for (const [, list, from] of source.matchAll(/^import\s*\{([^}]+)\}\s*from\s*'([^']+)';/gm)) {
    const target = from.startsWith('/') ? from : new URL(from, 'http://x' + path).pathname;
    if (!sources.has(target)) { assert.equal(target, '/engine/index.mjs', `${path} imports from ${from}`); continue; }
    for (const name of list.split(',').map((n) => n.trim().split(/\s+as\s+/)[0]).filter(Boolean)) { names++; assert.ok(provided(sources.get(target)).has(name), `${path} imports ${name}, which ${target} does not provide`); }
  }
  assert.ok(names > 60, `${names} imported names checked`);
}

// ---- refusals, and text through the vocabulary and back
for (const text of refused) { assert.equal(asked(text), null, text); assert.equal(run(text).ok, false, text); assert.ok(run(text).errors[0].message, text); assert.equal(fromText(text).model, null, text); }
if (baseline) {
  for (const text of refused) assert.deepEqual(engine.studyDiagnostics(text), baseline.studyDiagnostics(text), text);
  const questions = [...texts.keys()];
  for (let i = 0; i < questions.length; i += 64) {
    const batch = questions.slice(i, i + 64);
    assert.deepEqual(engine.studyCounts(batch), baseline.studyCounts(batch));
  }
  baseline.close();
  console.log(`Exact engine-to-engine parity across ${questions.length} questions and ${refused.length} refusals.`);
}
for (const text of texts.keys()) { const m = fromText(text).model; assert.ok(m, text); assert.equal(asked(toText(m)).results[0].matches.length, asked(text).results[0].matches.length, `text → rows → text asks the same\n${text}`); }
for (const text of texts.keys()) { const once = toText(fromText(text).model); assert.equal(toText(fromText(once).model), once, `the vocabulary's text is stable\n${text}`); }

console.log(`Parity: ${tally.questions} questions, ${tally.runs} runs, ${tally.rows.toLocaleString('en-US')} rows, ${tally.verdicts.toLocaleString('en-US')} line verdicts and ${tally.outcomes.toLocaleString('en-US')} outcomes identical to the reference engine; ${refused.length} refusals agree.`);
console.log(`Reasons: ${tally.reasons - tally.reasonsDiffer} of ${tally.reasons} sampled explanations read the same.`);
if (process.argv.includes('--reasons')) for (const d of [...kinds.values()].sort((a, b) => b.n - a.n)) console.log(`  ${d.n} × ${d.where}\n    was: ${d.was}\n    now: ${d.now}`);
if (process.argv.includes('--timing')) console.log(`Timing, whole corpus with every row read, one pass: reference ${timing.old.toFixed(0)} ms, shared engine ${timing.now.toFixed(0)} ms.`);
