// Browser controller. All parsing, checking and evaluation is done by the shared modules;
// this file only renders inputs and outputs and wires the two editors to the same structure.

import { h, mount, clear, kleeneBadge, fmtInt } from './ui/dom.js';
import { renderGuided } from './ui/guided.js';
import { drawTimeline, drawCandles } from './ui/chart.js';
import { buildEnvironment, DATA_FILES, EXTENSION_FILES, CALENDAR_BINDINGS } from './boot.js';
import { analyze, MAX_CANDIDATES, displayValue } from './check.js';
import { runAnalysis, T, F, U, KNAME, kAnd, kOr, kNot, ARITHMETIC_MODEL, RECORDING_ASSUMPTIONS } from './engine.js';
import { compareResults, describeChange, clauseChanges } from './diff.js';
import { EXAMPLES, exampleById } from './examples.js';
import { queryCompletions, applyCompletion } from './query-completions.js';
import { loadInstalled } from './study-extensions.js';
import { printQuestion, printExpr, lineCol, GRAMMAR_EBNF, LEXICAL_RULES, tokenizePrefix } from './lang.js';
import { isoUTC, isoUTCFull, dateUTC } from './data.js';
import { pctText, centsText, shareText } from './num.js';
import { signatureText, ENUMS, ENGINE, PLANNED_CLAUSES, CAPABILITY_TEXT, typeText } from './registry.js';
import { runConformance } from './conformance.js';
import { quietCoverage } from './coverage.js';

const PAGE = 50;
const S = {
  E: null, text: '', analysis: null, runs: [], cur: null, sel: 0, basisKey: 'auto', diff: null,
  rowView: 'matches', page: 0, selRef: null, tab: 'text', parent: null, exampleId: null,
  chartMode: 'near', lesson: { example: null, checked: null, transferChecked: null }, coverage: null,
};
const $ = (id) => document.getElementById(id);
const el = {};

const KIND_LABEL = {
  syntax: 'Syntax error', type: 'Type error', signature: 'Signature error', domain: 'Parameter domain error',
  name: 'Unresolved name', capability: 'Capability error', sweep: 'Sweep error', binding: 'Binding error', registry: 'Registry error',
};

function announce(msg) { el.live.textContent = msg; }

// ---------------------------------------------------------------- boot

async function fetchBytes(path) {
  const r = await fetch(path, { cache: 'no-store' });
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return new Uint8Array(await r.arrayBuffer());
}

async function boot() {
  for (const id of ['badges', 'query', 'overlay', 'diag', 'suggest', 'guided', 'run', 'runstate', 'live', 'example-select', 'candidates',
    'summary', 'compare', 'outcomes', 'timeline', 'chart', 'chart-caption', 'detail', 'rows', 'lesson', 'spec-body', 'defs-body', 'prov-body',
    'def-dialog', 'def-title', 'def-body', 'tab-text', 'tab-guided', 'panel-text', 'panel-guided', 'resolution', 'chart-mode', 'load-error', 'example-note']) el[id] = $(id);
  if (location.protocol === 'file:') { el['load-error'].hidden = false; return; }
  try {
    const [csv, prov, ses] = await Promise.all([fetchBytes(DATA_FILES.bars), fetchBytes(DATA_FILES.provenance), fetchBytes(DATA_FILES.sessions)]);
    const exts = [];
    for (const f of EXTENSION_FILES) { try { exts.push({ file: f, bytes: await fetchBytes(f) }); } catch (e) { console.warn(e); } }
    S.E = buildEnvironment({ csvBytes: csv, provenanceBytes: prov, sessionsBytes: ses, extensions: exts });
    try {
      if (globalThis.localStorage) loadInstalled(S.E);
    } catch (error) {
      S.E.extensionLoadError = error.message;
    }
  } catch (e) {
    el['load-error'].hidden = false;
    el['load-error'].querySelector('.why').textContent = String(e.message || e);
    mount(el.badges, h('span', { class: 'badge bad' }, 'inputs failed to load'));
    return;
  }
  renderBadges();
  renderExampleSelect();
  wire();
  renderSpec();
  renderRegistry();
  renderProvenance();
  prepareLesson();
  loadExample('starter');
  renderNotRun();
  renderLesson();
}

/** Before the first run: inputs are shown, nothing is evaluated yet (the guide asks for a prediction first). */
function renderNotRun() {
  const rec = S.E.rec;
  mount(el.summary, h('h3', null, 'Not run yet'), h('p', null, 'The starter question is parsed and checked. Make the prediction in the guide, then run it. Or just press Run.'));
  mount(el.compare, h('h3', { id: 'cmp-h' }, 'Before / after'), h('p', { class: 'muted' }, 'After a run, this panel compares sweep candidates, or your edit with the previous run.'));
  S.timelineHit = drawTimeline(el.timeline, { rec, marks: [], selectedSlot: null });
  el.timeline.setAttribute('aria-label', `Recorded closes ${dateUTC(rec.t0)} to ${dateUTC(rec.lastClose - 1)}; no run yet.`);
  mount(el['chart-caption'], `Recorded closes ${dateUTC(rec.t0)} → ${dateUTC(rec.lastClose - 1)} UTC (${fmtInt(rec.presentCount)} bars). Rows are marked here after a run.`);
  mount(el.rows, h('h3', null, 'Rows'), h('p', { class: 'muted' }, 'No run yet.'));
  mount(el.resolution, h('summary', null, 'How the question resolves (after a run)'), h('p', { class: 'muted' }, 'Run the question to see resolved parameters, identities and pins.'));
}

function renderBadges() {
  const { rec, cal, digestVerified, digest, extensions } = S.E;
  const extOk = extensions.filter((x) => x.ok).length;
  mount(el.badges,
    h('span', { class: 'badge' }, `${rec.instrument} · ${rec.barText} · ${rec.venue}`),
    h('span', { class: 'badge' }, `${dateUTC(rec.t0)} → ${dateUTC(rec.lastClose - 1)} UTC · ${fmtInt(rec.presentCount)} bars`),
    h('span', { class: `badge ${digestVerified ? 'good' : 'bad'}`, title: `computed SHA-256 ${digest}` }, digestVerified ? `CSV sha256 ${digest.slice(0, 10)}… ✓ provenance` : 'CSV digest MISMATCH'),
    h('span', { class: 'badge', title: cal.sources.join('\n') }, `calendar ${cal.id}`),
    h('span', { class: 'badge' }, `engine ${ENGINE.version}`),
    S.E.extensionLoadError ? h('span', { class: 'badge bad' }, 'Local definitions: ' + S.E.extensionLoadError) : null,
    extensions.length ? h('span', { class: `badge ${extOk === extensions.length ? '' : 'bad'}` }, `${extOk}/${extensions.length} extension`) : null);
}

function renderExampleSelect() {
  const groups = [...new Set(EXAMPLES.map((e) => e.group))];
  mount(el['example-select'], h('option', { value: '' }, 'Load an example…'),
    groups.map((g) => h('optgroup', { label: g }, EXAMPLES.filter((e) => e.group === g).map((e) => h('option', { value: e.id }, e.title)))));
}

function wire() {
  el.query.addEventListener('input', () => { S.text = el.query.value; reanalyze(); syncScroll(); });
  el.query.addEventListener('scroll', syncScroll);
  for (const ev of ['keyup', 'click']) el.query.addEventListener(ev, () => renderSuggestions());
  el.query.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); runNow(); }
    if (e.ctrlKey && e.key === ' ') { e.preventDefault(); const b = el.suggest.querySelector('button'); if (b) b.focus(); }
  });
  el.suggest.addEventListener('keydown', (e) => { if (e.key === 'Escape') el.query.focus(); });
  el.run.addEventListener('click', () => runNow());
  el['example-select'].addEventListener('change', () => { const v = el['example-select'].value; if (v) { loadExample(v); el['example-select'].value = ''; } });
  el['tab-text'].addEventListener('click', () => setTab('text'));
  el['tab-guided'].addEventListener('click', () => setTab('guided'));
  for (const t of [el['tab-text'], el['tab-guided']]) {
    t.addEventListener('keydown', (e) => { if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') { const n = S.tab === 'text' ? 'guided' : 'text'; setTab(n); $(`tab-${n}`).focus(); } });
  }
  el['chart-mode'].addEventListener('change', () => { S.chartMode = el['chart-mode'].value; renderChart(); });
  el['def-dialog'].querySelector('.close').addEventListener('click', () => el['def-dialog'].close());
  el.timeline.addEventListener('click', (e) => { if (!S.timelineHit) return; const s = S.timelineHit.hit(e.clientX); if (s !== null) selectRow(s, null); });
  let rt = null;
  window.addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(renderChart, 120); });
}

function setTab(t) {
  S.tab = t;
  const text = t === 'text';
  el['tab-text'].setAttribute('aria-selected', String(text));
  el['tab-guided'].setAttribute('aria-selected', String(!text));
  el['tab-text'].tabIndex = text ? 0 : -1;
  el['tab-guided'].tabIndex = text ? -1 : 0;
  el['panel-text'].hidden = !text;
  el['panel-guided'].hidden = text;
  if (!text) renderGuidedPanel();
  else { autosize(); renderOverlay(); }
}

// ---------------------------------------------------------------- editor

function loadExample(id) {
  const ex = exampleById(id);
  S.exampleId = id;
  S.parent = null;
  el.query.value = ex.text;
  S.text = ex.text;
  mount(el['example-note'], h('strong', null, ex.title), ' — ', ex.note);
  reanalyze();
  announce(`Loaded example: ${ex.title}. Press Run.`);
}

function autosize() {
  el.query.style.height = 'auto';
  el.query.style.height = `${el.query.scrollHeight + 2}px`;
}

function reanalyze() {
  S.analysis = analyze(S.text, S.E.env);
  autosize();
  renderDiagnostics();
  renderOverlay();
  renderSuggestions();
  if (S.tab === 'guided') renderGuidedPanel();
  renderRunState();
}

function syncScroll() { el.overlay.scrollTop = el.query.scrollTop; el.overlay.scrollLeft = el.query.scrollLeft; }

function renderOverlay() {
  const t = S.text;
  const marks = [];
  for (const d of S.analysis.errors) {
    marks.push({ s: d.start, e: Math.max(d.end, d.start + 1), cls: 'm-err' });
    if (d.related) marks.push({ s: d.related.start, e: d.related.end, cls: 'm-rel' });
  }
  marks.sort((a, b) => a.s - b.s || b.e - a.e);
  const out = [];
  let pos = 0;
  for (const m of marks) {
    if (m.s < pos) continue;
    out.push(t.slice(pos, m.s));
    const seg = t.slice(m.s, Math.min(m.e, t.length));
    out.push(h('mark', { class: m.cls }, seg.length ? seg : ' '));
    pos = Math.min(m.e, t.length);
    if (m.e > t.length) pos = t.length;
  }
  out.push(t.slice(pos), '\n');
  mount(el.overlay, ...out);
  syncScroll();
}

function selectSpan(start, end) {
  setTab('text');
  el.query.focus();
  el.query.setSelectionRange(start, Math.max(end, start));
}

function renderDiagnostics() {
  const a = S.analysis;
  if (!a.errors.length) {
    const axes = a.axes.map((x) => `${x.label} ∈ {${x.values.map((v) => printExpr(v)).join(', ')}}`);
    mount(el.diag, h('p', { class: 'ok' }, '✓ Parsed and checked. ',
      a.candidates.length === 1 ? 'One candidate run.' : `${a.candidates.length} candidate runs from ${axes.join(' × ')} (Cartesian product in source order; limit ${MAX_CANDIDATES}).`));
    return;
  }
  mount(el.diag, h('ul', { class: 'diag-list', 'aria-label': 'Problems' }, a.errors.map((d) => {
    const lc = lineCol(S.text, d.start);
    const snippet = S.text.slice(d.start, d.end);
    return h('li', { class: `diag d-${d.kind}` },
      h('span', { class: 'diag-kind' }, KIND_LABEL[d.kind] || d.kind), ' ',
      h('button', { type: 'button', class: 'linkish', onclick: () => selectSpan(d.start, d.end), title: 'select the offending span in the editor' },
        `line ${lc.line}, col ${lc.col}${snippet ? ` “${snippet.length > 40 ? snippet.slice(0, 40) + '…' : snippet}”` : ' (end of input)'}`),
      h('div', { class: 'diag-msg' }, d.message),
      d.hint ? h('div', { class: 'hint' }, d.hint) : null,
      d.related ? h('div', { class: 'hint' }, h('button', { type: 'button', class: 'linkish', onclick: () => selectSpan(d.related.start, d.related.end) }, d.related.note)) : null);
  })));
}

/** The definition named by the token under the caret (function name or quoted named definition). */
function phraseAt(caret) {
  const toks = tokenizePrefix(S.text);
  const k = toks.findIndex((t) => t.start <= caret && caret <= t.end && t.t !== 'eof');
  if (k < 0) return null;
  const t = toks[k];
  const reg = S.E.registry;
  if (t.t === 'id' && toks[k + 1] && toks[k + 1].v === '(' && reg.get(t.v)) return { name: t.v, named: null, label: `${t.v}@${reg.get(t.v).version}` };
  const nd = reg.getNamed(t.v);
  if (nd && (t.t === 'str' || t.t === 'id' && nd.patternId)) return { name: nd.def, named: t.v, label: `“${t.v}”` };
  return null;
}

function renderSuggestions() {
  if (!S.E) return;
  const caret = el.query.selectionStart ?? S.text.length;
  const r = queryCompletions(S.text, caret, S.E.env, Math.max(caret, el.query.selectionEnd ?? caret));
  const ph = phraseAt(caret);
  const inspect = ph ? h('button', { type: 'button', class: 'sg sg-def', title: 'open the definition behind this phrase', onclick: () => openDefinition(ph.name, ph.named) }, `definition of ${ph.label}`) : null;
  if (!r.items.length) { mount(el.suggest, inspect, h('span', { class: 'sg-label' }, inspect ? '' : 'Suggestions from registry signatures appear here as you type (Tab or Ctrl+Space reaches them). Put the caret on a phrase to inspect its definition.')); return; }
  mount(el.suggest, inspect, h('span', { class: 'sg-label', id: 'sg-label' }, 'Suggestions:'), r.items.map((it) => h('button', {
    type: 'button', class: 'sg', title: it.detail, 'aria-describedby': 'sg-label',
    onclick: () => {
      // The guide teaches argument names and values in two successive picks.
      const pick = it.kind === 'parameter' && it.insert.startsWith(it.label + ' ')
        ? { ...it, insert: it.label + ' ' } : it;
      const next = applyCompletion(S.text, pick);
      el.query.value = next.text; S.text = next.text;
      el.query.focus(); el.query.setSelectionRange(next.caret, next.caret);
      reanalyze();
    },
  }, it.label, h('span', { class: 'sg-detail' }, it.detail))));
}

function renderGuidedPanel() {
  const a = S.analysis;
  if (!a.ast) {
    const d = a.errors[0];
    mount(el.guided, h('div', { class: 'g-blocked' }, h('p', null, 'Guided editing needs a parsed question. Fix the syntax error in the Text tab:'), h('p', { class: 'diag-msg' }, d.message),
      h('button', { type: 'button', class: 'g-btn', onclick: () => selectSpan(d.start, d.end) }, 'show the error in the text')));
    return;
  }
  const focusLabel = document.activeElement && el.guided.contains(document.activeElement) ? document.activeElement.getAttribute('aria-label') : null;
  renderGuided(el.guided, {
    ast: a.ast, errors: a.errors, registry: S.E.registry, env: S.E.env, letNames: a.ast.lets.map((b) => b.name),
    onInspect: openDefinition,
    onEdit: (newAst, what) => {
      const before = S.text;
      const canonicalBefore = a.canonical;
      const text = printQuestion(newAst);
      el.query.value = text; S.text = text;
      reanalyze();
      const note = before !== canonicalBefore ? ' (rewritten in canonical form: comments and spacing normalized)' : '';
      announce(`Edited: ${what}${note}. Press Run to compare.`);
      mount(el.runstate, h('span', null, `Guided edit: ${what}${note}. `), h('strong', null, 'Run to compare.'));
    },
  });
  if (focusLabel) { const f = [...el.guided.querySelectorAll('[aria-label]')].find((x) => x.getAttribute('aria-label') === focusLabel); if (f) f.focus(); }
}

function renderRunState() {
  if (!S.cur) { mount(el.runstate, 'Not run yet.'); return; }
  if (S.text === S.cur.text) mount(el.runstate, `Showing run #${S.cur.id} of this text (${S.cur.results.length} candidate${S.cur.results.length > 1 ? 's' : ''}, ${S.cur.ms.toFixed(0)} ms).`);
  else if (S.parent === null) mount(el.runstate, h('strong', null, 'New question loaded.'), ` Results below are still run #${S.cur.id} of a different question. Press Run${S.analysis.ok ? '' : ' after fixing the errors'}.`);
  else mount(el.runstate, h('strong', null, 'Edited.'), ` Results below are run #${S.cur.id}. Run to compare with it${S.analysis.ok ? '' : ' (fix the errors first)'}.`);
}

// ---------------------------------------------------------------- run & basis

function runNow() {
  const a = S.analysis;
  if (!a.ok) {
    announce('Not run: fix the highlighted problem first.');
    mount(el.runstate, h('strong', null, 'Not run.'), ' Fix the problem listed below the editor; its span is highlighted.');
    return null;
  }
  const out = runAnalysis(S.E.ctx, a, { digestVerified: S.E.digestVerified, extensions: S.E.extensions.filter((x) => x.ok) });
  const run = { id: S.runs.length + 1, text: S.text, analysis: a, results: out.results, ms: out.ms, manifest: out.manifest, parent: S.parent, exampleId: S.exampleId };
  S.runs.push(run);
  S.cur = run;
  S.parent = run;
  S.sel = run.results.length - 1;
  S.basisKey = 'auto';
  S.rowView = 'matches';
  S.page = 0;
  S.selRef = null;
  renderResults();
  renderRunState();
  renderLesson();
  announce(`Run #${run.id}: ${run.results.map((x) => `${x.cand.label} ${x.matches.length} matches`).join('; ')}.`);
  return run;
}

const curResult = () => S.cur.results[S.sel];

function basisOptions() {
  const run = S.cur;
  const opts = [];
  run.results.forEach((r, k) => { if (k !== S.sel) opts.push({ key: `${run.id}:${k}`, label: `this run · ${r.cand.label}`, result: r }); });
  for (const pr of S.runs.slice(0, -1).reverse().slice(0, 6)) pr.results.forEach((r, k) => opts.push({ key: `${pr.id}:${k}`, label: `run #${pr.id} · ${r.cand.label}`, result: r }));
  return opts;
}

function autoBasis() {
  const run = S.cur;
  const cur = curResult();
  if (run.parent) {
    let best = null;
    let bestN = Infinity;
    run.parent.results.forEach((r, k) => {
      const n = clauseChanges(r.cand.resolvedAst, cur.cand.resolvedAst).length;
      if (n < bestN || (n === bestN && k === S.sel)) { best = { key: `${run.parent.id}:${k}`, label: `previous run #${run.parent.id} · ${r.cand.label}`, result: r, why: 'your last edit: the closest candidate of the previous run' }; bestN = n; }
    });
    return best;
  }
  if (run.results.length > 1) {
    const k = S.sel > 0 ? S.sel - 1 : 1;
    return { key: `${run.id}:${k}`, label: `this run · ${run.results[k].cand.label}`, result: run.results[k], why: 'the neighbouring sweep candidate' };
  }
  return null;
}

function currentBasis() {
  if (S.basisKey === 'none') return null;
  if (S.basisKey === 'auto') return autoBasis();
  return basisOptions().find((o) => o.key === S.basisKey) || autoBasis();
}

// ---------------------------------------------------------------- results

function renderResults() {
  const run = S.cur;
  mount(el.candidates, run.results.length > 1
    ? h('div', { class: 'cand-tabs', role: 'tablist', 'aria-label': 'Candidate runs' }, run.results.map((r, k) => h('button', {
      type: 'button', role: 'tab', 'aria-selected': String(k === S.sel), class: 'cand', tabIndex: k === S.sel ? 0 : -1,
      onclick: () => { S.sel = k; S.basisKey = 'auto'; S.page = 0; S.selRef = null; renderResults(); },
      onkeydown: (e) => { if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') { const n = (k + (e.key === 'ArrowRight' ? 1 : run.results.length - 1)) % run.results.length; S.sel = n; S.basisKey = 'auto'; S.selRef = null; renderResults(); el.candidates.querySelectorAll('.cand')[n].focus(); } },
    }, h('span', { class: 'cand-label' }, r.cand.label), h('span', { class: 'cand-count' }, `${fmtInt(r.matches.length)} matches`))))
    : null);
  const res = curResult();
  renderCompare(res);
  if (!S.selRef) {
    const first = S.diff && S.diff.added.length ? S.diff.added[0].row : S.diff && S.diff.removed.length ? null : res.matches[0];
    if (first) S.selRef = { slot: first.i, side: 'cur' };
    else if (S.diff && S.diff.removed.length) S.selRef = { slot: S.diff.removed[0].row.i, side: 'basis' };
    else if (res.rows[0]) S.selRef = { slot: res.rows[0].i, side: 'cur' };
  }
  renderSummary(res);
  renderOutcomes(res);
  renderRows(res);
  renderChart();
  renderResolution(res);
}

function renderSummary(res) {
  const c = res.counts;
  const steps = [h('li', null, h('span', { class: 'f-n' }, fmtInt(c.T)), ' ', h('span', { class: 'f-t' }, `${res.event.named ? `“${res.event.named}”` : res.event.text} events`),
    h('span', { class: 'muted' }, ` in ${fmtInt(c.slots)} bars · ${fmtInt(c.F)} false · ${fmtInt(c.U)} unknown · ${fmtInt(c.absent)} absent`))];
  res.clauseStats.forEach((s, k) => steps.push(h('li', null, h('span', { class: 'f-n' }, fmtInt(res.survivors[k])), ' ', h('span', { class: 'f-t' }, `after where #${k + 1} `, h('code', null, s.text)),
    h('span', { class: 'muted' }, ` · over all events: ${fmtInt(s.T)} true, ${fmtInt(s.F)} false, ${fmtInt(s.U)} unknown`))));
  steps.push(h('li', { class: 'f-final' }, h('span', { class: 'f-n' }, fmtInt(res.matches.length)), ' matches', res.groups ? ` → grouped by ${res.group.text}` : ''));
  mount(el.summary,
    h('h3', null, `Candidate ${res.cand.label}`),
    h('ol', { class: 'funnel', 'aria-label': 'Candidate counts' }, steps),
    h('p', { class: 'muted small' }, 'Only true passes a where clause (strong Kleene: unknown is kept apart from false). Counts are occurrences of the event; each where column is evaluated for every event so that exclusions have reasons.'));
}

function renderCompare(res) {
  const b = currentBasis();
  const opts = basisOptions();
  const auto = autoBasis();
  const sel = h('select', { id: 'basis-select', 'aria-label': 'comparison basis' },
    h('option', { value: 'auto', selected: S.basisKey === 'auto' }, `auto: ${auto ? auto.label : 'none available'}`),
    h('option', { value: 'none', selected: S.basisKey === 'none' }, 'no comparison'),
    opts.map((o) => h('option', { value: o.key, selected: S.basisKey === o.key }, o.label)));
  sel.addEventListener('change', () => { S.basisKey = sel.value; S.selRef = null; renderResults(); });
  const head = h('div', { class: 'cmp-head' }, h('h3', { id: 'cmp-h' }, 'Before / after'), h('label', { class: 'inline' }, 'Basis ', sel));
  if (!b) {
    S.diff = null;
    mount(el.compare, head, h('p', { class: 'muted' }, 'No basis yet: edit the question and run again, or run a sweep to compare its candidates.'));
    return;
  }
  const d = compareResults(b.result, res, { basis: b.label, cur: `run #${S.cur.id} · ${res.cand.label}` });
  S.diff = d;
  const item = (x, side) => h('li', null,
    h('button', { type: 'button', class: 'linkish', onclick: () => { selectRow(x.row.i, side); } }, isoUTC(x.row.t)),
    ' ', h('span', { class: 'muted' }, S.E.cal.describe(x.row.t)),
    h('ul', { class: 'reasons' }, x.reasons.map((r) => h('li', null,
      r.clause ? [h('code', null, r.clause), ` was ${r.text}`, r.other ? [h('br'), '→ now ', h('code', null, r.other.clause), ` ${r.other.text}`] : null] : r.text))));
  const LIMIT = 8;
  mount(el.compare, head,
    h('p', { class: 'cmp-basis' }, h('span', { class: 'muted' }, 'Basis '), h('strong', null, d.basisLabel), h('span', { class: 'muted' }, ' → current '), h('strong', null, d.curLabel),
      S.basisKey === 'auto' && b.why ? h('span', { class: 'muted' }, ` (auto: ${b.why})`) : null),
    h('p', { class: 'muted small' }, `Membership compared by ${d.mode}. Occurrence identity = recording digest + instrument + bar size + detector identity + anchor; it does not depend on filters or horizons.`),
    d.changes.length ? h('ul', { class: 'changes', 'aria-label': 'changed clauses' }, d.changes.map((c) => h('li', null, h('code', null, describeChange(c))))) : h('p', { class: 'muted' }, 'No clause changed.'),
    h('p', { class: 'cmp-counts' },
      h('span', { class: 'pill added' }, `+${fmtInt(d.added.length)} added`), ' ',
      h('span', { class: 'pill removed' }, `−${fmtInt(d.removed.length)} removed`), ' ',
      h('span', { class: 'pill kept' }, `${fmtInt(d.kept.length)} kept`), ' ',
      (d.added.length || d.removed.length) ? h('button', { type: 'button', class: 'linkish', onclick: () => { S.rowView = 'diff'; S.page = 0; renderRows(curResult()); $('rows').scrollIntoView({ block: 'start' }); } }, 'show all changes in the table') : null),
    d.added.length ? h('div', null, h('h4', null, 'Added'), h('ul', { class: 'cmp-list' }, d.added.slice(0, LIMIT).map((x) => item(x, 'cur'))), d.added.length > LIMIT ? h('p', { class: 'muted' }, `… ${d.added.length - LIMIT} more in the table`) : null) : null,
    d.removed.length ? h('div', null, h('h4', null, 'Removed'), h('ul', { class: 'cmp-list' }, d.removed.slice(0, LIMIT).map((x) => item(x, 'basis'))), d.removed.length > LIMIT ? h('p', { class: 'muted' }, `… ${d.removed.length - LIMIT} more in the table`) : null) : null);
}

function summaryCells(s) {
  return [
    h('td', null, `${fmtInt(s.observed)} / ${fmtInt(s.total)}`), h('td', null, fmtInt(s.censored)), h('td', null, fmtInt(s.unknown)),
    h('td', null, s.observed >= 30 ? pctText(s.mean) : '—'), h('td', null, s.observed >= 30 ? pctText(s.median) : '—'), h('td', null, s.observed >= 30 ? `${s.positive} (${shareText(s.positive, s.observed, 0)})` : String(s.positive)),
    h('td', null, pctText(s.min)), h('td', null, pctText(s.max)),
  ];
}

function renderOutcomes(res) {
  const head = h('tr', null, ['Horizon', 'Observed / matches', 'Censored', 'Unknown', 'Mean', 'Median', 'r > 0', 'Min', 'Max'].map((x) => h('th', { scope: 'col' }, x)));
  const table = h('table', { class: 'tbl' }, h('caption', null, 'Close returns of the matches (observed outcomes only; each horizon has its own denominator)'),
    h('thead', null, head), h('tbody', null, res.columns.map((c, k) => h('tr', null, h('th', { scope: 'row' }, c.text), summaryCells(res.summary[k])))));
  const parts = [h('h3', null, 'Measured returns'), h('div', { class: 'tbl-wrap' }, table)];
  if (res.groups) {
    const sum = res.groups.reduce((a, g) => a + g.count, 0);
    const ok = sum === res.matches.length;
    const gHead = h('tr', null, h('th', { scope: 'col' }, 'Bucket'), h('th', { scope: 'col' }, 'Matches'), res.columns.map((c) => h('th', { scope: 'col' }, `${c.text} mean (n)`)), h('th', { scope: 'col' }, h('span', { class: 'sr' }, 'Action')));
    const gt = h('table', { class: 'tbl' }, h('caption', null, `Grouped by ${res.group.text}`), h('thead', null, gHead), h('tbody', null, res.groups.map((g) => h('tr', null,
      h('th', { scope: 'row' }, g.key, h('span', { class: 'muted small' }, ` ${g.label !== g.key ? g.label : ''}`)), h('td', null, fmtInt(g.count)),
      g.summary.map((s) => h('td', null, s.observed >= 30 ? `${pctText(s.mean)} (${s.observed})` : `n=${s.observed}`)),
      h('td', null, g.key !== 'unknown' ? h('button', { type: 'button', class: 'g-btn', onclick: () => groupToFilterAndRun(g.key) }, `keep only ${g.key}`) : null)))));
    parts.push(h('div', { class: 'tbl-wrap' }, gt), h('p', { class: ok ? 'ok small' : 'bad small' }, `${ok ? '✓' : '✗'} Buckets partition the matches: ${res.groups.map((g) => `${g.count} ${g.key}`).join(' + ')} = ${sum} of ${res.matches.length}.${res.groups.some((g) => g.key === 'unknown') ? ' The unknown bucket holds matches whose group value is unknown.' : ''} A filter keeps only the true/selected bucket; a group keeps everyone.`));
  }
  mount(el.outcomes, ...parts);
}

function groupToFilterAst(ast, value) {
  const g = ast.group;
  const plan = S.analysis && S.analysis.candidates[0] && S.analysis.candidates[0].plan.group;
  const categorical = plan ? plan.type.startsWith('Cat:') : g.k === 'call' && ['weekday', 'completed_trend'].includes(g.name);
  const cond = categorical ? { k: 'cmp', op: '=', left: g, right: { k: 'id', name: value } } : value === 'true' ? g : { k: 'not', item: g };
  return { ...ast, group: null, wheres: [...ast.wheres, cond] };
}

function groupToFilterAndRun(value) {
  const base = S.cur && S.cur.analysis.ast;
  if (!base || !base.group) return null;
  if (S.text !== S.cur.text) { el.query.value = S.cur.text; S.text = S.cur.text; reanalyze(); }
  S.parent = S.cur;
  const text = printQuestion(groupToFilterAst(base, value));
  el.query.value = text; S.text = text;
  reanalyze();
  return runNow();
}

// ---------------------------------------------------------------- rows

/** Membership status against the basis: added, kept, removed (a basis match not matched now) or null. */
function statusOf(row) {
  return S.diff ? S.diff.status(row) : null;
}

function viewRows(res) {
  if (S.rowView === 'all') return res.rows.map((r) => ({ row: r, side: 'cur', res }));
  if (S.rowView === 'diff' && S.diff) {
    const b = currentBasis();
    return [...S.diff.added.map((x) => ({ row: x.row, side: 'cur', res })), ...S.diff.removed.map((x) => ({ row: x.row, side: 'basis', res: b.result }))].sort((a, b2) => a.row.t - b2.row.t);
  }
  return res.matches.map((r) => ({ row: r, side: 'cur', res }));
}

function renderRows(res) {
  const list = viewRows(res);
  const pages = Math.max(1, Math.ceil(list.length / PAGE));
  S.page = Math.min(S.page, pages - 1);
  const slice = list.slice(S.page * PAGE, S.page * PAGE + PAGE);
  const views = [['matches', `Matches (${fmtInt(res.matches.length)})`], ['all', `All events (${fmtInt(res.rows.length)})`], ['diff', `Changes vs basis (${S.diff ? fmtInt(S.diff.added.length + S.diff.removed.length) : 0})`]];
  const viewSel = h('div', { class: 'seg', role: 'radiogroup', 'aria-label': 'rows to show' }, views.map(([v, label]) => h('button', {
    type: 'button', role: 'radio', 'aria-checked': String(S.rowView === v), disabled: v === 'diff' && !S.diff ? true : null,
    onclick: () => { S.rowView = v; S.page = 0; renderRows(curResult()); },
  }, label)));
  const cols = res.clauses.map((c, k) => h('th', { scope: 'col', title: c.text }, `where #${k + 1}`));
  const head = h('tr', null, h('th', { scope: 'col' }, 'Anchor (bar close, UTC)'), h('th', { scope: 'col' }, 'New York'), h('th', { scope: 'col' }, 'Open'), h('th', { scope: 'col' }, 'High'), h('th', { scope: 'col' }, 'Low'), h('th', { scope: 'col' }, 'Close'),
    cols, res.group ? h('th', { scope: 'col' }, 'Group') : null, res.columns.map((c) => h('th', { scope: 'col' }, `r ${c.text}`)), h('th', { scope: 'col' }, 'Status'));
  const body = slice.map(({ row, side, res: rr }) => {
    const raw = S.E.rec.ohlcText(row.i);
    const st = statusOf(row, side);
    const selected = S.selRef && S.selRef.slot === row.i && S.selRef.side === side;
    return h('tr', { class: `${st ? 'st-' + st : ''}${selected ? ' selected' : ''}${row.pass ? '' : ' excluded'}` },
      h('td', null, h('button', { type: 'button', class: 'linkish mono', 'aria-pressed': String(!!selected), onclick: () => selectRow(row.i, side) }, isoUTC(row.t))),
      h('td', { class: 'small' }, S.E.cal.describe(row.t)),
      h('td', { class: 'mono' }, raw.open), h('td', { class: 'mono' }, raw.high), h('td', { class: 'mono' }, raw.low), h('td', { class: 'mono' }, raw.close),
      rr.clauses.map((c, k) => h('td', null, row.results[k] ? kleeneBadge(row.results[k].v, `${c.text}: ${KNAME[row.results[k].v]} — ${row.results[k].why}`) : '—')),
      res.group ? h('td', { title: row.group ? row.group.why : '' }, row.group ? row.group.key : '—') : null,
      res.columns.map((c, k) => { const o = row.out[k]; return h('td', { class: `mono ${o.status !== 'observed' ? 'muted' : o.value > 0 ? 'pos' : o.value < 0 ? 'neg' : ''}`, title: o.why }, o.status === 'observed' ? pctText(o.value) : o.status); }),
      h('td', { class: 'small' }, st ? h('span', { class: `pill ${st}` }, st) : row.pass ? 'match' : `excluded by where #${row.failAt + 1} (${KNAME[row.results[row.failAt].v]})`));
  });
  const pager = pages > 1 ? h('div', { class: 'pager' },
    h('button', { type: 'button', class: 'g-btn', disabled: S.page === 0 ? true : null, onclick: () => { S.page--; renderRows(curResult()); } }, '‹ previous'),
    h('span', null, ` page ${S.page + 1} of ${pages} `),
    h('button', { type: 'button', class: 'g-btn', disabled: S.page >= pages - 1 ? true : null, onclick: () => { S.page++; renderRows(curResult()); } }, 'next ›')) : null;
  mount(el.rows, h('div', { class: 'rows-head' }, h('h3', null, 'Rows'), viewSel),
    list.length ? h('div', { class: 'tbl-wrap' }, h('table', { class: 'tbl rows-tbl' }, h('caption', { class: 'sr' }, 'Occurrences with recorded OHLC, clause results and returns'), h('thead', null, head), h('tbody', null, body))) : h('p', { class: 'muted' }, S.rowView === 'matches' ? 'No matches for this candidate.' : 'Nothing to show.'),
    pager,
    res.rows.length && S.rowView !== 'diff' ? h('p', { class: 'muted small' }, 'Prices are the recorded CSV text. ✓ true · ✗ false · ? unknown; hover or select a row for the reason.') : null);
}

function selectRow(slot, side) {
  const res = curResult();
  if (!side) side = res.rowsBySlot.has(slot) ? 'cur' : 'basis';
  S.selRef = { slot, side };
  renderRows(res);
  renderChart();
}

function selectedContext() {
  if (!S.selRef) return null;
  const res = S.selRef.side === 'basis' ? (currentBasis() || {}).result : curResult();
  if (!res) return null;
  const row = res.rowsBySlot.get(S.selRef.slot);
  return row ? { res, row, side: S.selRef.side } : null;
}

// ---------------------------------------------------------------- chart & detail

function overlaysFor(res, row, mode) {
  const rec = S.E.rec;
  const i = row.i;
  const ov = { windows: [], levels: [], horizons: [], times: [] };
  let from = i - 32;
  let to = i + 4;
  res.columns.forEach((c, k) => {
    const j = i + c.h / rec.barMs;
    const o = row.out[k];
    ov.horizons.push({ slot: j, label: `${c.text}: ${o.status === 'observed' ? pctText(o.value) : o.status}` });
    to = Math.max(to, Math.min(j, rec.n - 1) + 2);
  });
  const ev = res.event.plan;
  if (ev.name === 'channel_breakout') {
    const L = ev.args.over.ms / rec.barMs;
    const m = res.event.series.maxAt[i];
    if (m >= 0) ov.levels.push({ from: i - L, to: i - 1, price: rec.H[m], label: `prior ${ev.args.over.text} high ${centsText(rec.H[m])}` });
    ov.windows.push({ from: i - L, to: i - 1, label: `channel (${ev.args.over.text}, trigger excluded)`, tone: 1 });
    from = Math.min(from, mode === 'full' ? i - L - 2 : i - Math.min(L, 48) - 2);
  }
  const visit = (p) => {
    if (!p) return;
    if (p.op === 'def') {
      if (p.name === 'session_tail') {
        const cal = S.E.calendars.get(p.args.calendar.name);
        const s = cal.closeAtOrAfter(rec.closeTime(i));
        if (s) {
          const sc = rec.slotClosingAt(s.close);
          if (sc !== null && sc - i < 48) {
            const st = rec.slotClosingAt(s.close - p.args.last.ms);
            ov.times.push({ t: s.close, label: `${p.args.calendar.name} close ${cal.localHMshort(s.close, s)}` });
            if (st !== null) ov.windows.push({ from: st + 1, to: sc, label: `last ${p.args.last.text}`, tone: 2 });
            to = Math.max(to, sc + 2);
          }
        }
      }
      if (p.name === 'held') {
        const stp = p.args.state;
        const W = stp.args.window.ms / rec.barMs;
        const D = p.args.for.ms / rec.barMs;
        ov.windows.push({ from: i - W + 1, to: i, label: `${stp.args.window.text} window at t`, tone: 1 });
        if (mode === 'full') { from = Math.min(from, i - D - W); ov.windows.push({ from: i - D - W + 1, to: i - D, label: `window of the first sample (t − ${p.args.for.text})`, tone: 2 }); }
      }
      if (p.name === 'range_contained') {
        const W = p.args.over.ms / rec.barMs;
        ov.windows.push({ from: i - W + 1, to: i, label: `${p.args.over.text} envelope`, tone: 1 });
        if (mode === 'full') from = Math.min(from, i - W);
      }
      if (p.name === 'completed_trend') {
        const t = rec.closeTime(i);
        const Fm = p.args.frame.ms;
        const E = Math.floor(t / Fm) * Fm;
        const s0 = (E - Fm - rec.t0) / rec.barMs;
        const s1 = (E - rec.t0) / rec.barMs - 1;
        ov.windows.push({ from: s0, to: s1, label: `completed ${p.args.frame.text} bar`, tone: 2 });
        from = Math.min(from, s0 - 2);
      }
      for (const v of Object.values(p.args)) if (v && v.op) visit(v);
      if (p.body) visit(p.body);
    }
    if (p.items) p.items.forEach(visit);
    if (p.item) visit(p.item);
    if (p.left) visit(p.left);
    if (p.right) visit(p.right);
  };
  res.cand.plan.wheres.forEach(visit);
  visit(res.cand.plan.group);
  return { ov, from, to };
}

function renderChart() {
  if (!S.cur) return;
  const res = curResult();
  const sel = selectedContext();
  const marks = [];
  if (S.diff) {
    for (const r of S.diff.kept) marks.push({ slot: r.i, cls: 'kept' });
    for (const x of S.diff.added) marks.push({ slot: x.row.i, cls: 'added' });
    for (const x of S.diff.removed) marks.push({ slot: x.row.i, cls: 'removed' });
  } else for (const r of res.matches) marks.push({ slot: r.i, cls: 'match' });
  S.timelineHit = drawTimeline(el.timeline, { rec: S.E.rec, marks, selectedSlot: sel ? sel.row.i : null });
  el.timeline.setAttribute('aria-label', `Recording timeline ${dateUTC(S.E.rec.t0)} to ${dateUTC(S.E.rec.lastClose - 1)} with ${marks.length} marked rows${S.diff ? ` (${S.diff.added.length} added, ${S.diff.removed.length} removed)` : ''}. Click a marker to select it.`);
  if (!sel) {
    clear(el.detail);
    mount(el['chart-caption'], 'No row selected: this candidate has no rows to inspect.');
    const g = el.chart.getContext('2d');
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.clearRect(0, 0, el.chart.width, el.chart.height);
    return;
  }
  const { res: rr, row, side } = sel;
  const { ov, from, to } = overlaysFor(rr, row, S.chartMode);
  drawCandles(el.chart, { rec: S.E.rec, anchorSlot: row.i, from, to, overlays: ov, eventLabel: rr.event.named || rr.event.plan.name });
  const desc = `${rr.event.named || rr.event.text} at ${isoUTC(row.t)} (${S.E.cal.describe(row.t)}), ${side === 'basis' ? 'from the basis run' : 'current run'}. Bars ${isoUTC(S.E.rec.closeTime(Math.max(0, from)))} to ${isoUTC(S.E.rec.closeTime(Math.min(S.E.rec.n - 1, to)))}.`;
  el.chart.setAttribute('aria-label', `Candlestick chart: ${desc}`);
  mount(el['chart-caption'], desc, ' Shaded: windows the conditions read. Dashed: horizons and the session close.');
  renderDetail(rr, row, side);
}

function partsList(parts) {
  if (!parts || !parts.length) return null;
  return h('ul', { class: 'parts' }, parts.map((p) => h('li', null, kleeneBadge(p.v), ' ', h('code', null, p.text), ` — ${p.why}`, partsList(p.parts))));
}

function renderDetail(res, row, side) {
  const raw = S.E.rec.ohlcText(row.i);
  const st = statusOf(row, side);
  mount(el.detail,
    h('h3', null, `Selected occurrence ${row.short}`, st ? h('span', { class: `pill ${st}` }, st) : null, side === 'basis' ? h('span', { class: 'muted small' }, ' (basis run)') : null),
    h('dl', { class: 'kv' },
      h('dt', null, 'Anchor'), h('dd', null, `${isoUTCFull(row.t)} · ${S.E.cal.describe(row.t)} (bar ${isoUTC(row.t - S.E.rec.barMs)} → close)`),
      h('dt', null, 'Recorded bar'), h('dd', { class: 'mono' }, `open ${raw.open} · high ${raw.high} · low ${raw.low} · close ${raw.close} · volume ${raw.volume}`),
      h('dt', null, 'find'), h('dd', null, kleeneBadge(T), ' ', h('code', null, res.event.text), ` — ${res.event.series.why(row.i)}`),
      res.clauses.map((c, k) => [h('dt', null, `where #${k + 1}`), h('dd', null, kleeneBadge(row.results[k].v), ' ', h('code', null, c.text), ` — ${row.results[k].why}`, partsList(row.results[k].parts))]),
      res.group ? [h('dt', null, 'group'), h('dd', null, h('strong', null, row.group.key), ` — ${row.group.why}`)] : null,
      res.columns.map((c, k) => [h('dt', null, `return ${c.text}`), h('dd', null, row.out[k].status === 'observed' ? pctText(row.out[k].value) : row.out[k].status, ` — ${row.out[k].why}`)]),
      h('dt', null, 'Occurrence id'), h('dd', { class: 'mono small wrap' }, row.id)));
}

function planNode(p, depth = 0) {
  if (!p) return null;
  if (p.op === 'def') {
    return h('li', null, h('code', null, `${p.name}@${p.version}`), p.named ? h('span', { class: 'muted' }, ` ← named "${p.named}" (immutable preset)`) : null,
      h('button', { type: 'button', class: 'linkish small', onclick: () => openDefinition(p.name, p.named) }, ' definition'),
      h('ul', null, Object.entries(p.args).map(([k, v]) => h('li', null, h('span', { class: 'mono' }, `${k} = `),
        v && v.op ? h('ul', null, planNode(v, depth + 1)) : h('span', { class: 'mono' }, displayValue(v)),
        h('span', { class: `src src-${p.argSource[k]}` }, ` ${p.argSource[k]}`))),
      p.body ? h('li', null, 'body: ', h('code', null, p.bodyText), h('ul', null, planNode(p.body, depth + 1))) : null),
      h('div', { class: 'mono small muted wrap' }, `identity ${p.identity}`));
  }
  if (p.op === 'and' || p.op === 'or') return h('li', null, h('strong', null, p.op), h('ul', null, p.items.map((x) => planNode(x, depth + 1))));
  if (p.op === 'not') return h('li', null, h('strong', null, 'not'), h('ul', null, planNode(p.item, depth + 1)));
  if (p.op === 'cmp') return h('li', null, h('strong', null, `compare ${p.cmp}`), h('ul', null, planNode(p.left, depth + 1), planNode(p.right, depth + 1)));
  if (p.op === 'enum') return h('li', null, h('code', null, `${p.enumName}.${p.value}`));
  return h('li', null, p.text);
}

function renderResolution(res) {
  const c = res.cand;
  const pl = c.plan;
  mount(el.resolution, h('summary', null, `How candidate ${c.label} resolves (parameters, identities, pins)`),
    c.assignment.length ? h('p', null, 'Axis values: ', c.assignment.map((a, k) => [k ? ', ' : '', h('code', null, `${a.axis} = ${a.value}`)])) : h('p', null, 'No sweep axes.'),
    h('p', null, 'Resolved question (choices and lets substituted):'), h('pre', { class: 'code-block' }, c.resolvedText),
    h('ul', { class: 'plan' },
      h('li', null, h('strong', null, 'find '), h('ul', null, planNode(pl.find))),
      pl.wheres.map((w, k) => h('li', null, h('strong', null, `where #${k + 1} `), h('ul', null, planNode(w)))),
      pl.group ? h('li', null, h('strong', null, 'group by '), h('ul', null, planNode(pl.group))) : null,
      pl.measures.map((m, k) => h('li', null, h('strong', null, `measure #${k + 1} `), h('ul', null, planNode(m))))),
    h('p', null, h('span', { class: 'src src-given' }, 'given'), ' written in the question · ', h('span', { class: 'src src-default' }, 'default'), ' from the signature · ', h('span', { class: 'src src-preset' }, 'preset'), ' pinned by a named definition'),
    h('p', null, 'Run manifest (pins registry definitions, calendar, source digest, query and engine):'),
    h('pre', { class: 'code-block small' }, JSON.stringify(S.cur.manifest, null, 2)));
}

// ---------------------------------------------------------------- definitions dialog

function openDefinition(name, named) {
  const reg = S.E.registry;
  const nd = named ? reg.getNamed(named) : null;
  const def = nd?.patternId ? reg.getPattern(nd.patternId) : reg.get(name);
  const dlg = el['def-dialog'];
  if (!def) return;
  mount(el['def-title'], `${def.title} — ${def.name}@${def.version}`);
  const body = [];
  const status = def.status === 'planned' ? 'planned design example (not executable)' : def.status === 'extension' ? 'agent-authored extension (versioned composition)' : 'implemented';
  body.push(h('p', null, h('span', { class: `pill ${def.status}` }, status), ' ', def.summary || ''));
  if (nd) {
    body.push(h('div', { class: 'callout' }, h('p', null, h('strong', null, `“${named}”`), ` is an immutable named definition: ${nd.def}@${nd.version} with `, h('code', null, Object.entries(nd.args).map(([k, v]) => `${k}: ${v}`).join(', ')), '.'),
      h('p', null, nd.origin), h('p', { class: 'small' }, nd.note)));
  }
  body.push(h('h4', null, 'Signature'), h('pre', { class: 'code-block' }, signatureText(def)));
  if (def.params) {
    body.push(h('table', { class: 'tbl' }, h('thead', null, h('tr', null, ['Parameter', 'Type', 'Default', 'Domain', 'Meaning'].map((x) => h('th', { scope: 'col' }, x)))),
      h('tbody', null, def.params.map((p) => h('tr', null, h('th', { scope: 'row' }, p.name, def.positional === p.name ? h('span', { class: 'muted small' }, ' (positional)') : null), h('td', null, typeText(p)), h('td', null, p.default || (p.required ? 'required' : '—')), h('td', { class: 'small' }, domainText(p)), h('td', { class: 'small' }, p.doc))))));
  }
  if (def.formula) body.push(h('h4', null, 'Exact meaning'), h('ul', { class: 'formula' }, def.formula.map((f) => h('li', null, h('code', null, f)))));
  if (def.anchor) body.push(h('dl', { class: 'kv' }, h('dt', null, 'Anchor'), h('dd', null, def.anchor), h('dt', null, 'Availability'), h('dd', null, def.availability), h('dt', null, 'Missing data'), h('dd', null, def.missing), h('dt', null, 'Requires'), h('dd', null, (def.requires || []).map((c) => CAPABILITY_TEXT[c] || c).join(', '))));
  if (def.status === 'planned') body.push(h('div', { class: 'callout' }, h('p', null, def.note), h('p', { class: 'small' }, 'Using it in a question gives a typed capability error at its span.')));
  if (def.name === 'quiet_range') body.push(coverageSection());
  if (def.status === 'extension') {
    const ext = S.E.extensions.find((x) => x.def === def);
    const results = runConformance(S.E, def);
    const pass = results.filter((r) => r.pass).length;
    body.push(h('h4', null, `Conformance on recorded bars: ${pass}/${results.length} pass`),
      h('table', { class: 'tbl' }, h('thead', null, h('tr', null, ['Anchor (UTC)', 'Call', 'Expected', 'Engine', 'Note / reason'].map((x) => h('th', { scope: 'col' }, x)))),
        h('tbody', null, results.map((r) => h('tr', { class: r.pass ? '' : 'bad' }, h('td', { class: 'mono small' }, r.anchor), h('td', null, h('code', null, r.call)), h('td', null, r.expect), h('td', null, r.pass ? `✓ ${r.got}` : `✗ ${r.got}`), h('td', { class: 'small' }, r.note, h('div', { class: 'muted' }, r.why)))))),
      h('p', null, `Artifact ${ext.file} · sha256 ${ext.sha256.slice(0, 16)}… · replay: ${def.artifact.replay}`),
      h('details', null, h('summary', null, 'Artifact JSON'), h('pre', { class: 'code-block small' }, ext.text)));
  }
  mount(el['def-body'], ...body);
  if (!dlg.open) dlg.showModal();
}

function domainText(p) {
  const d = p.domain || {};
  const out = [];
  if (d.barMultiple) out.push('multiple of 15m');
  if (d.minMs) out.push(`≥ ${d.minMs / 60000 >= 60 ? d.minMs / 3600000 + 'h' : d.minMs / 60000 + 'm'}`);
  if (d.maxMs) out.push(`≤ ${d.maxMs / 3600000}h`);
  if (d.dividesDay) out.push('divides 24h (UTC-aligned)');
  if (d.maxShortestSession) out.push('≤ shortest session in the pinned table');
  if (d.ratioMin !== undefined) out.push(`${d.ratioMinExclusive ? '>' : '≥'} ${Number(d.ratioMin) * 100}%`);
  if (d.ratioMax !== undefined) out.push(`≤ ${Number(d.ratioMax) * 100}%`);
  if (p.type === 'State') out.push('a State definition');
  if (p.type === 'Calendar') out.push('registered calendar');
  return out.join(', ') || '—';
}

function coverageSection() {
  if (!S.coverage) S.coverage = quietCoverage(S.E);
  const rows = S.coverage;
  const chosen = S.E.registry.named.get('Quiet range').args.width_max;
  return h('div', null, h('h4', null, 'Choice of width_max: coverage on recorded bars (no returns used)'),
    h('table', { class: 'tbl' }, h('thead', null, h('tr', null, ['width_max', 'state true (bars)', 'held 48h true (bars)', 'starter matches, last 30m', 'starter matches, last 1h'].map((x) => h('th', { scope: 'col' }, x)))),
      h('tbody', null, rows.map((r) => h('tr', { class: r.width === chosen ? 'selected' : '' }, h('th', { scope: 'row' }, r.width, r.width === chosen ? ' (chosen)' : ''),
        h('td', null, `${fmtInt(r.stateTrue)} (${shareText(r.stateTrue, r.bars)})`), h('td', null, `${fmtInt(r.heldTrue)} (${shareText(r.heldTrue, r.bars)})`), h('td', null, r.starter30m), h('td', null, r.starter1h))))),
    h('p', { class: 'small' }, `Chosen: ${chosen}. The design suggested starting at 2%, but there the starter keeps one match for each tail, so widening 30m → 1h reveals nothing. ${chosen} is the smallest step at which widening adds real matches; the state stays selective and the 48h hold is still a real filter. Only bar coverage and match counts were used, never returns. The engine computes these counts live.`));
}

// ---------------------------------------------------------------- lesson

function localClose(t) { const d = S.E.cal.dayAt(t); return d.kind === 'session' ? S.E.cal.localHMshort(t, d.s) : null; }

/** Picks the real Friday example for the prediction: an added row of the starter's 1h candidate (prefer a 15:30 close). */
function prepareLesson() {
  const a = analyze(exampleById('starter').text, S.E.env);
  const run = runAnalysis(S.E.ctx, a);
  const [r30, r1h] = run.results;
  const d = compareResults(r30, r1h);
  const pick = d.added.find((x) => localClose(x.row.t) === '15:30') || d.added[0];
  if (!pick) return;
  const t = pick.row.t;
  const day = S.E.cal.dayAt(t).s;
  const k = r30.clauses.findIndex((c) => c.text.startsWith('session_tail'));
  const before = r30.rowsBySlot.get(pick.row.i).results;
  const onlyTail = before.every((r, j) => (j === k ? r.v !== T : r.v === T));
  S.lesson.example = { slot: pick.row.i, t, date: day.date, close: S.E.cal.localHM(t, day), open: S.E.cal.localHMshort(t - S.E.rec.barMs, day), utc: isoUTC(t), onlyTail };
}

const Q3 = [
  { v: 'a', label: '15:15 and 15:30 New York time', set: ['15:15', '15:30'] },
  { v: 'b', label: '15:00, 15:15 and 15:30 New York time', set: ['15:00', '15:15', '15:30'] },
  { v: 'c', label: 'only 15:30 New York time', set: ['15:30'] },
  { v: 'd', label: 'only 15:45 New York time', set: ['15:45'] },
];

function radios(name, legend, options) {
  const preds = S.lesson.preds || (S.lesson.preds = {});
  return h('fieldset', { class: 'q' }, h('legend', null, legend), options.map(([v, label]) => h('label', { class: 'radio' },
    h('input', { type: 'radio', name, value: v, checked: preds[name] === v, onchange: () => { preds[name] = v; } }), ` ${label}`)));
}

const answerText = (q, v) => (v === null || v === undefined ? 'no answer' : q === 'q3' ? (Q3.find((o) => o.v === v) || { label: 'none of the options' }).label : v);

function checkPrediction(run) {
  const [r30, r1h] = run.results;
  const d = compareResults(r30, r1h);
  const ex = S.lesson.example;
  const preds = S.lesson.preds || {};
  const k = r30.clauses.findIndex((c) => c.text.startsWith('session_tail'));
  const a30 = r30.rowsBySlot.get(ex.slot).results[k];
  const a1h = r1h.rowsBySlot.get(ex.slot).results[k];
  // Which closes of that session does the 1h tail admit that the 30m tail does not? Evaluated by the engine.
  const day = S.E.cal.dayAt(ex.t).s;
  const band = [];
  for (let i = S.E.rec.slotClosingAt(day.open); i <= S.E.rec.slotClosingAt(day.close); i++) {
    if (r1h.clauses[k].at(i).v === T && r30.clauses[k].at(i).v !== T) band.push(S.E.cal.localHMshort(S.E.rec.closeTime(i), day));
  }
  const q3truth = (Q3.find((o) => o.set.join() === band.join()) || { v: '?' }).v;
  const addedTimes = [...new Set(d.added.map((x) => localClose(x.row.t)))].sort();
  const res = [
    { id: 'q1', q: `${ex.close} bar in the 30m tail?`, truth: a30.v === T ? 'yes' : 'no', why: a30.why },
    { id: 'q2', q: `${ex.close} bar in the 1h tail?`, truth: a1h.v === T ? 'yes' : 'no', why: a1h.why },
    { id: 'q3', q: 'Closes the 1h tail adds on a session', truth: q3truth, why: `on ${day.date} the engine admits ${band.join(' and ')} with last: 1h but not with last: 30m; the ${d.added.length} added rows close at ${addedTimes.join(', ')}` },
    { id: 'q4', q: 'Can a 30m match disappear?', truth: d.removed.length ? 'yes' : 'no', why: `${d.removed.length} removed: every close in (15:30, 16:00] is also in (15:00, 16:00]` },
  ].map((r) => ({ ...r, yours: preds[r.id] ?? null }));
  S.lesson.checked = { res, added: d.added.length, kept: d.kept.length, runId: run.id };
}

function renderLesson() {
  const L = S.lesson;
  const steps = [];
  const ex = L.example;
  const quietWidth = S.E.registry.named.get('Quiet range').args.width_max;
  const s1 = [h('p', null, 'The starter question in the editor runs on the real recording. ', h('code', null, '{30m | 1h}'), ' is one sweep axis, so it runs as two candidates. ', h('code', null, '[1h, 4h]'), ' is one vector argument, so it gives two return columns. Before running it, predict what widening the tail from 30m to 1h does.')];
  if (ex) {
    s1.push(h('p', null, h('strong', null, 'A real Friday bar: '), `${ex.date}, the “Wick rejection” bar ${ex.open}–${ex.close} (closes ${ex.utc}).`,
      ex.onlyTail ? ' It passes the weekday and quiet-range clauses, so only the tail decides it.' : '',
      ' Tails are half-open: ', h('code', null, 'last: 30m'), ' is (15:30, 16:00] and ', h('code', null, 'last: 1h'), ' is (15:00, 16:00]. The anchor is the bar close.'));
    const form = h('form', { id: 'predict-form', class: 'predict', onsubmit: (e) => { e.preventDefault(); loadExample('starter'); const run = runNow(); if (run) { checkPrediction(run); renderLesson(); } } },
      radios('q1', `Is the ${ex.close} bar in the 30m tail?`, [['yes', 'yes'], ['no', 'no']]),
      radios('q2', 'Is it in the 1h tail?', [['yes', 'yes'], ['no', 'no']]),
      radios('q3', 'Which closes of a session does the 1h tail add over the 30m tail?', Q3.map((o) => [o.v, o.label])),
      radios('q4', 'Can widening remove any 30m match?', [['yes', 'yes'], ['no', 'no']]),
      h('button', { type: 'submit', class: 'primary small-btn' }, 'Run the starter and check'));
    s1.push(form);
    if (L.checked) {
      const ok = L.checked.res.filter((r) => r.yours === r.truth).length;
      s1.push(h('div', { class: 'callout', role: 'status' }, h('p', null, h('strong', null, `${ok}/${L.checked.res.length} predictions matched run #${L.checked.runId}.`), ` last=1h adds ${L.checked.added} rows and keeps ${L.checked.kept}. Select an added row under “Before / after” to see its bars and the clause results that explain it.`),
        h('ul', null, L.checked.res.map((r) => h('li', null, r.yours === r.truth ? '✓ ' : r.yours ? '✗ ' : '– ', `${r.q} Engine: `, h('strong', null, answerText(r.id, r.truth)),
          r.yours !== r.truth ? ` (yours: ${answerText(r.id, r.yours)})` : '', h('div', { class: 'muted small' }, r.why))))));
    }
  } else s1.push(h('p', { class: 'bad' }, 'No added Friday example was found in this recording.'));
  s1.push(h('p', { class: 'small muted' }, `“Quiet range” uses width_max ${quietWidth}, picked from coverage of recorded matches and never from returns. `,
    h('button', { type: 'button', class: 'linkish', onclick: () => openDefinition('quiet_range', 'Quiet range') }, 'See the coverage table'),
    '. To see what the 48h clause removes, load “Starter without the quiet clause” from the examples.'));
  steps.push([L.checked ? `1 · Predict a local edit — ${L.checked.res.filter((r) => r.yours === r.truth).length}/${L.checked.res.length} matched the engine` : '1 · Predict a local edit, then run the starter', s1, true]);
  const s3 = [h('p', null, 'Now express a different setup in the same grammar. A channel breakout is a close above the prior lookback high, with the trigger bar excluded. Group it by the last completed 4h trend and study 1h and 4h close returns.'),
    h('button', { type: 'button', class: 'g-btn', onclick: () => { loadExample('transfer'); runNow(); } }, 'Load and run the transfer question')];
  const tr = S.cur && S.cur.analysis.ast && S.cur.analysis.ast.group && S.cur.results[S.sel] && S.cur.results[S.sel].groups ? S.cur : null;
  if (tr) {
    const r = tr.results[S.sel];
    s3.push(h('p', null, `Run #${tr.id}, ${r.cand.label}: ${r.matches.length} matches = ${r.groups.map((g) => `${g.count} ${g.key}`).join(' + ')}. Grouping keeps the whole population.`),
      h('button', { type: 'button', class: 'g-btn', onclick: () => groupToFilterAndRun(r.groups[0].key) }, `Turn the “${r.groups[0].key}” group into a filter and compare`));
  } else if (S.cur && S.cur.parent && S.cur.parent.analysis.ast.group && !S.cur.analysis.ast.group) {
    const r = curResult();
    const d = S.diff;
    if (d) s3.push(h('p', null, `Filter run #${S.cur.id}, ${r.cand.label}: kept ${d.kept.length} (the bucket), removed ${d.removed.length}. Every removed row’s reason names the new where clause. A filter keeps only true; a group keeps everyone and labels them.`));
  }
  steps.push(['2 · Transfer to a different setup', s3, !!L.checked || !!tr]);
  const openState = L.open || (L.open = {});
  mount(el.lesson, h('h2', { class: 'lesson-h' }, 'Guide'), h('ol', { class: 'steps' }, steps.map(([title, body, dflt], k) => {
    const d = h('details', { open: k in openState ? openState[k] : dflt }, h('summary', null, title), body);
    d.addEventListener('toggle', () => { openState[k] = d.open; });
    return h('li', null, d);
  })));
}

// ---------------------------------------------------------------- reference panels

function renderSpec() {
  const reg = S.E.registry;
  const tv = [T, F, U];
  const nm = (v) => KNAME[v];
  const truth = (op, f) => h('table', { class: 'tbl kleene' }, h('caption', null, op), h('thead', null, h('tr', null, h('th', null, ''), tv.map((b) => h('th', { scope: 'col' }, nm(b))))),
    h('tbody', null, tv.map((a) => h('tr', null, h('th', { scope: 'row' }, nm(a)), tv.map((b) => h('td', null, nm(f(a, b))))))));
  mount(el['spec-body'],
    h('p', null, 'This view is generated from the running build: the EBNF and lexical rules are the parser’s, the truth tables call the engine’s functions, and the signatures are read from the registry.'),
    h('h4', null, 'Grammar (implemented)'), h('pre', { class: 'code-block' }, GRAMMAR_EBNF),
    h('h4', null, 'Lexical rules'), h('ul', null, LEXICAL_RULES.map((r) => h('li', null, r))),
    h('h4', null, 'Clauses and types'), h('ul', null,
      h('li', null, 'Combine named events at the same close with ', h('code', null, 'find hammer or engulfing'), ' or require both with ', h('code', null, 'find hammer and engulfing'), '. Each close appears once.'),
      h('li', null, h('code', null, 'find'), ' needs an Event; ', h('code', null, 'where'), ' needs a condition (a Condition, or a State/Event sampled at the anchor); ', h('code', null, 'group by'), ' needs a categorical or Boolean value; ', h('code', null, 'measure'), ' needs an Outcome. Outcomes are rejected in where: no post-anchor data enters a condition.'),
      h('li', null, 'Calls: at most one positional first argument (only where the signature declares one), then named arguments. Unknown, duplicate and missing required keys, wrong types or units, unresolved names and invalid domains are errors with spans.'),
      h('li', null, 'A bare name is a let binding, a registered calendar (', [...S.E.calendars.keys()].join(', '), ') or an enum value (', Object.values(ENUMS).map((e) => `${e.name}: ${e.values.join(' ')}`).join('; '), '). A quoted name in a definition slot resolves to an immutable named definition: ', [...reg.named.keys()].map((n) => `"${n}"`).join(', '), '.'),
      h('li', null, 'Comparisons test a categorical value against one of its values with = or !=; the grammar admits < <= > >=, but no ordered per-bar values exist in this prototype, so they are type errors.'),
      h('li', null, `Bindings and choices hold typed scalar literals only (no nested lists, sweeps or references). A let with choices is one axis however often it is used; each inline choices is its own axis. Axes expand as a Cartesian product in source order (first axis outermost); duplicate choices and products above ${MAX_CANDIDATES} are rejected. A vector is one argument; each close_return horizon makes a column.`)),
    h('h4', null, 'Strong Kleene logic (only true passes)'), h('div', { class: 'kleene-row' }, truth('and', (a, b) => kAnd([a, b])), truth('or', (a, b) => kOr([a, b])),
      h('table', { class: 'tbl kleene' }, h('caption', null, 'not'), h('tbody', null, tv.map((a) => h('tr', null, h('th', { scope: 'row' }, nm(a)), h('td', null, nm(kNot(a))))))) ),
    h('h4', null, 'Registry signatures'), h('table', { class: 'tbl' }, h('thead', null, h('tr', null, ['Definition', 'Kind', 'Signature', 'Status'].map((x) => h('th', { scope: 'col' }, x)))),
      h('tbody', null, reg.list().map((f) => h('tr', null, h('th', { scope: 'row' }, h('button', { type: 'button', class: 'linkish', onclick: () => openDefinition(f.name) }, `${f.name}@${f.version}`)), h('td', null, f.kind), h('td', null, h('code', { class: 'small' }, signatureText(f))), h('td', null, f.status))))),
    h('h4', null, 'Planned clauses (design examples, not in this grammar)'), h('ul', null, PLANNED_CLAUSES.map((c) => h('li', null, h('code', null, c.name), ` — ${c.note}`))),
    h('h4', null, 'Arithmetic model'), h('ul', null, ARITHMETIC_MODEL.map((x) => h('li', null, x))));
}

function renderRegistry() {
  const reg = S.E.registry;
  const item = (f) => h('li', null, h('button', { type: 'button', class: 'linkish', onclick: () => openDefinition(f.name) }, `${f.title} — ${f.name}@${f.version}`), ` `, h('span', { class: `pill ${f.status}` }, f.status));
  mount(el['defs-body'],
    h('h4', null, 'Named definitions (immutable presets)'), h('ul', null, [...reg.named].map(([n, nd]) => h('li', null, h('button', { type: 'button', class: 'linkish', onclick: () => openDefinition(nd.def, n) }, `“${n}”`), ` = ${nd.def}@${nd.version}(${Object.entries(nd.args).map(([k, v]) => `${k}: ${v}`).join(', ')}) — ${nd.origin}`))),
    h('h4', null, 'Implemented'), h('ul', null, reg.list((f) => f.status === 'implemented').map(item)),
    h('h4', null, 'Extensions (agent-authored, versioned)'), h('ul', null, reg.list((f) => f.status === 'extension').map(item), S.E.extensions.filter((x) => !x.ok).map((x) => h('li', { class: 'bad' }, `${x.file}: ${x.errors.join('; ')}`))),
    h('h4', null, 'Planned (design examples; typed capability errors if used)'), h('ul', null, reg.list((f) => f.status === 'planned').map(item)));
}

function renderProvenance() {
  const { provenance: p, rec, cal, digest, digestVerified, sessionsDigest, extensions } = S.E;
  mount(el['prov-body'],
    h('h4', null, 'Recorded bars'), h('dl', { class: 'kv' },
      h('dt', null, 'File'), h('dd', { class: 'mono' }, DATA_FILES.bars),
      h('dt', null, 'Instrument'), h('dd', null, p.instrument),
      h('dt', null, 'Interval / timestamp'), h('dd', null, `${p.interval_ms} ms; timestamp role “${p.timestamp_role}” (bar covers [open, open + 15m))`),
      h('dt', null, 'Rows'), h('dd', null, `${fmtInt(rec.presentCount)} (provenance ${fmtInt(p.row_count)}); grid ${fmtInt(rec.n)} slots ${isoUTC(rec.t0)} … ${isoUTC(rec.openTime(rec.n - 1))} opens; ${fmtInt(rec.n - rec.presentCount)} absent; OHLC inconsistencies ${rec.badOhlc}`),
      h('dt', null, 'CSV SHA-256 (computed in page)'), h('dd', { class: 'mono wrap' }, digest, ' ', h('span', { class: digestVerified ? 'ok' : 'bad' }, digestVerified ? '✓ equals provenance csv_sha256' : `✗ provenance says ${p.csv_sha256}`)),
      h('dt', null, 'Source'), h('dd', { class: 'mono small wrap' }, `${p.source_path} @ ${p.source_commit} (sha256 ${p.source_sha256})`),
      h('dt', null, 'Derived by'), h('dd', null, p.derived_by)),
    h('h4', null, 'Session calendar'), h('dl', { class: 'kv' },
      h('dt', null, 'Name in queries'), h('dd', null, CALENDAR_BINDINGS.map((b) => `${b.name} → ${b.file}`).join('; ')),
      h('dt', null, 'Table'), h('dd', null, `${cal.id}, zone ${cal.zone}, ${cal.sessions.length} sessions, coverage ${cal.startDate} … ${cal.endDate} (end exclusive), shortest session ${(cal.shortestSessionMs / 3600000).toFixed(1)}h, UTC offsets ${cal.offsets.map((o) => cal.tzLabel(o)).join(' / ')}`),
      h('dt', null, 'SHA-256'), h('dd', { class: 'mono wrap' }, sessionsDigest),
      h('dt', null, 'Sources (as recorded; not fetched)'), h('dd', { class: 'small wrap' }, cal.sources.join(' · '))),
    h('h4', null, 'Extensions'), h('ul', null, extensions.map((x) => h('li', null, h('span', { class: 'mono' }, x.file), ` sha256 ${x.sha256.slice(0, 16)}… — ${x.ok ? `registered ${x.name}@${x.version}` : `rejected: ${x.errors.join('; ')}`}`))),
    h('h4', null, 'Recording assumptions'), h('ul', null, RECORDING_ASSUMPTIONS.map((x) => h('li', null, x))),
    h('p', { class: 'small muted' }, 'The page only reads these files. Nothing is sent anywhere; there is no service or API.'));
}

boot();
