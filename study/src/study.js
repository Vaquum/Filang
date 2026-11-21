import { buildEnvironment, DATA_FILES, EXTENSION_FILES } from './boot.js';
import { analyze } from './check.js';
import { runAnalysis } from './engine.js';
import { printQuestion, parseExpression, lineCol } from './lang.js';
import { g1FromRecording, parseG1 } from './g1.js';
import { decodeDrawing } from '../composer/drawing.js';
import { loadInstalled, installSaved, renderExtensions } from './study-extensions.js';
import { setupPractice } from './study-practice.js';
import { EXAMPLES } from './examples.js';
import { h, mount } from './ui/dom.js';
import { renderControls, FRIDAY, DEFAULT_SOURCE } from './study-controls.js';
import { setupBuilder } from './study-builder.js';
import { setupFormalMenu } from './study-menu.js';
import { renderEvidence } from './study-results.js';
import { readLibrary, saveToLibrary, makeStudy, checkStudy, studyLink, studyFromLink } from './study-save.js';

const el = (id) => document.getElementById(id);
const HAMMER = 'on BTCUSDT 15m\nfind hammer\nmeasure close_return(after: 1h)';
const transfer = EXAMPLES.find((e) => e.id === 'transfer').text;
const state = {
  env: null,
  analysis: null,
  run: null,
  candidate: 0,
  population: 'matching',
  inspect: null,
  source: null,
  bucket: null,
  page: 0,
  basis: null,
};
let nativeToken = 0,
  dirty = false,
  lastNative = null,
  practice = null,
  builder = null,
  hideFormalMenu = null,
  nativeRequest = null,
  editTimer = null;
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
function notice(message, bad = false) {
  const dest = el('message');
  dest.textContent = message;
  dest.hidden = !message;
  dest.classList.toggle('warn', bad);
}
async function bytes(path) {
  const r = await fetch(path, { cache: 'no-cache' });
  if (!r.ok) throw Error(`${path} returned HTTP ${r.status}.`);
  return new Uint8Array(await r.arrayBuffer());
}
function sourceFrom(value) {
  const rec = state.env.rec;
  if (!value || typeof value.g1 !== 'string') throw Error('The drawing has no G1 identity.');
  const pattern = parseG1(value.g1);
  const anchor = value.anchor ?? null;
  if (
    anchor !== null &&
    (!Number.isSafeInteger(anchor) ||
      g1FromRecording(rec, rec.slotClosingAt(anchor), pattern.rows.length, pattern.oriented) !== value.g1)
  )
    throw Error('The selected close and G1 drawing do not agree on this recording.');
  if (value.drawing) decodeDrawing(value.drawing, value.g1);
  return { g1: value.g1, anchor, drawing: value.drawing || null };
}
function seed() {
  const rec = state.env.rec;
  return sourceFrom({ g1: g1FromRecording(rec, rec.slotClosingAt(DEFAULT_SOURCE)), anchor: DEFAULT_SOURCE });
}
function portableDefinitions() {
  const used = new Set(state.run.manifest.pins.extensions.map((e) => e.sha256));
  return state.env.extensions
    .filter((e) => e.custom && used.has(e.sha256))
    .map(({ file, text, sha256 }) => ({ file, text, sha256 }));
}
function showInstalled() {
  renderExtensions(el('installations'), state.env, (def) => {
    if (dirty || !state.analysis) throw Error('Run the query before inserting a definition.');
    const q = structuredClone(state.analysis.ast);
    const position = current().cand.plan.wheres.findIndex((w) => w.def?.id === def.id && w.def?.composed);
    if (position >= 0 && q.wheres[position].k === 'call') q.wheres[position].name = def.name;
    else q.wheres.push(parseExpression(def.name + '()').ast);
    if (!runText(printQuestion(q))) throw Error('Review the parameter diagnostics in the formal query.');
  });
}
function composerURL() {
  const dest = new URL('./composer/', location.href);
  const patternId = state.run && current().event.plan.def?.patternId;
  if (patternId) {
    dest.searchParams.set('pattern', patternId);
    const close = current().matches[0]?.t;
    if (close) dest.searchParams.set('anchor', close);
  } else {
    if (state.source.drawing) dest.searchParams.set('drawing', state.source.drawing);
    if (state.source.anchor !== null) dest.searchParams.set('anchor', state.source.anchor);
    if (!state.source.drawing && state.source.anchor === null) dest.searchParams.set('g1', state.source.g1);
  }
  if (state.analysis) {
    dest.searchParams.set('question', state.analysis.canonical);
    const definitions = portableDefinitions();
    if (definitions.length)
      dest.hash = new URLSearchParams({ definitions: JSON.stringify(definitions) }).toString();
  }
  return dest.href;
}
function current() {
  return state.run.results[state.candidate];
}
function view() {
  return {
    source: state.source,
    candidate: state.candidate,
    population: state.population,
    inspect: state.inspect,
    bucket: state.bucket,
    page: state.page,
  };
}
function restoreView(v, run) {
  if (
    !Number.isInteger(v.candidate) ||
    !run.results[v.candidate] ||
    !['eligible', 'matching', 'nonmatching', 'unknownDetector'].includes(v.population)
  )
    throw Error('The saved view cannot be reopened.');
  return {
    candidate: v.candidate,
    population: v.population,
    inspect: v.inspect ?? null,
    bucket: v.bucket ?? null,
    page: Number.isSafeInteger(v.page) ? Math.max(0, v.page) : 0,
  };
}
function clearSavedURL() {
  if (location.hash || location.search) history.replaceState(null, '', location.pathname);
}
function runText(text, { saved = null, startFresh = false, source = null, live = false } = {}) {
  clearTimeout(editTimer);
  const a = analyze(text, state.env.env);
  if (!a.ok) {
    el('query').value = text;
    if (!dirty) markDirty();
    mount(
      el('errors'),
      a.errors.map((e) => {
        const pos = lineCol(text, e.start);
        return h('p', null, `Line ${pos.line}, column ${pos.col}. ${e.message}`, e.hint ? ' ' + e.hint : '');
      }),
    );
    el('query-state').textContent = 'Incomplete query · showing previous results';
    return false;
  }
  const env = state.env;
  const run = runAnalysis(env.ctx, a, { digestVerified: env.digestVerified, extensions: env.extensions });
  let resolvedSource = source || state.source;
  let next = { candidate: 0, population: 'matching', bucket: null, inspect: null, page: 0 };
  if (saved) {
    checkStudy(saved, run);
    next = restoreView(saved.view, run);
  }
  const detector = run.results[next.candidate].event.plan;
  const code = detector.name === 'exact_g1' ? detector.args.pattern.text : null;
  if (code && resolvedSource.g1 !== code) {
    if (saved) throw Error('The saved drawing does not match the query.');
    resolvedSource = sourceFrom({ g1: code });
  }
  const basis = !startFresh && state.run ? current() : null;
  Object.assign(state, next, { run, analysis: a, basis, source: resolvedSource });
  dirty = false;
  if (!live) hideFormalMenu?.();
  el('builder').inert = false;
  el('revert-edit').hidden = true;
  lastNative = null;
  if (!live) el('query').value = a.canonical;
  el('query-state').textContent = 'Evaluated on recorded bars';
  el('run').disabled = false;
  el('save-open').disabled = false;
  mount(el('errors'));
  notice('');
  if (!saved) clearSavedURL();
  const id =
    a.canonical === analyze(HAMMER, env.env).canonical
      ? 'hammer'
      : a.canonical === analyze(transfer, env.env).canonical
        ? 'breakout'
        : a.canonical === analyze(FRIDAY, env.env).canonical
          ? 'friday'
          : 'custom';
  el('examples').value = id;
  if (!basis && run.results.length > 1) state.basis = run.results[state.candidate === 0 ? 1 : 0];
  render();
  practice?.onRun();
  checkNative();
  if (saved)
    notice(
      'Reopened “' + saved.name + '”. Source, definitions, cases and outcomes match the saved question.',
    );
  return true;
}
function selectCandidate(id) {
  if (dirty || id === state.candidate) return;
  state.basis = current();
  state.candidate = id;
  state.inspect = null;
  state.bucket = null;
  state.page = 0;
  const g1 = current().event.plan.args?.pattern?.text;
  if (current().event.plan.name === 'exact_g1' && g1 !== state.source.g1) state.source = sourceFrom({ g1 });
  render();
  checkNative();
}
function render() {
  state.env.env.selectedG1 = state.source.g1;
  const url = composerURL();
  builder?.render();
  el('jump-results').hidden = false;
  const matches = current().matches.length;
  el('jump-results').textContent =
    matches.toLocaleString('en-US') + (matches === 1 ? ' match ↓' : ' matches ↓');
  const shortcuts = el('shortcuts');
  const detector = current().event.plan.name;
  shortcuts.hidden = !['channel_breakout', 'exact_g1', 'wick_rejection'].includes(detector);
  if (!shortcuts.hidden)
    renderControls(el('question-controls'), {
      analysis: state.analysis,
      env: state.env,
      candidate: state.candidate,
      source: state.source,
      composerLink: url,
      edit: runText,
    });
  document.querySelectorAll('a.composer-link').forEach((a) => (a.href = url));
  renderEvidence(state, selectCandidate);
  const r = current(),
    p = state.run.manifest.pins;
  const defs = [];
  function visit(v) {
    if (!v || typeof v !== 'object') return;
    if (v.op === 'def' && !defs.some((d) => d.def === v.def)) defs.push(v);
    if (v.op === 'def') Object.values(v.args).forEach(visit);
    if (v.body) visit(v.body);
    v.items?.forEach(visit);
    if (v.left) visit(v.left);
    if (v.right) visit(v.right);
    if (v.item) visit(v.item);
  }
  [r.cand.plan.find, ...r.cand.plan.wheres, r.cand.plan.group, ...r.cand.plan.measures].forEach(visit);
  mount(
    el('definitions'),
    defs.map((node) => {
      const def = node.def || state.env.registry.get(node.name);
      if (!def) return null;
      return h(
        'details',
        null,
        h('summary', null, def.title + ' · v' + def.version),
        h('p', null, node.label),
        h('p', null, def.summary),
        h(
          'ul',
          null,
          (def.formula || []).map((s) => h('li', null, h('code', null, s))),
        ),
        h('p', null, def.availability),
        h('p', null, def.missing),
      );
    }),
    h(
      'p',
      null,
      `${p.source.rows.toLocaleString('en-US')} Binance BTCUSDT 15-minute bars. A completed bar is assumed available at its close.`,
    ),
    h('a', { href: 'data-provenance.json' }, 'Recording provenance'),
    h('p', null, 'Calendar · ' + state.env.cal.id),
  );
}
function markDirty() {
  dirty = true;
  el('builder').inert = true;
  el('revert-edit').hidden = !state.analysis;
  nativeRequest?.abort();
  nativeToken++;
  el('run').disabled = false;
  el('save-open').disabled = true;
  el('query-state').textContent = 'Checking query…';
  el('native').textContent = 'Results reflect the last evaluated query.';
  el('question-controls')
    .querySelectorAll('select,button')
    .forEach((b) => (b.disabled = true));
  notice('Showing the last complete query while you edit.');
}
async function checkNative() {
  const token = ++nativeToken;
  nativeRequest?.abort();
  nativeRequest = new AbortController();
  const r = current(),
    env = state.env,
    native = el('native');
  lastNative = null;
  el('save-open').disabled = false;
  native.textContent = 'Checking cases with Filang…';
  const pins = new Set(state.run.manifest.pins.extensions.map((e) => e.sha256));
  const request = {
    query: r.cand.resolvedText,
    source: env.digest,
    calendar: env.sessionsDigest,
    extensions: env.extensions
      .filter((e) => e.ok && e.custom && pins.has(e.sha256))
      .map(({ text, sha256 }) => ({ text, sha256 })),
  };
  try {
    const response = await fetch('./api/filang/evaluate', {
      method: 'POST',
      signal: nativeRequest.signal,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    });
    if (token !== nativeToken) return;
    if (!response.headers.get('content-type')?.includes('application/json'))
      throw Error('Native service unavailable');
    const body = await response.json();
    if (!response.ok) {
      native.textContent = 'Browser evaluated · ' + (body.error || 'Filang unavailable');
      return;
    }
    const p = r.populations;
    const anchors = r.matches.map((x) => x.t),
      eligible = p.eligible.rows.map((x) => x.t);
    const match =
      body.source === env.digest &&
      body.calendar === env.sessionsDigest &&
      body.counts.event === r.counts.T &&
      body.counts.nonmatching === p.nonmatching.count &&
      body.unknown.event.length === r.counts.U &&
      same(body.unknown.eligibility, p.unknownContextAnchors) &&
      same(
        body.unknown.detectorWithinContext,
        p.unknownDetector.rows.map((x) => x.t),
      ) &&
      same(anchors, body.anchors) &&
      same(eligible, body.eligible) &&
      body.rows.length === r.matches.length &&
      body.rows.every((x, i) => {
        const row = r.matches[i];
        return (
          x.t === row.t &&
          (x.group ?? null) === (row.group?.key ?? null) &&
          x.out.length === row.out.length &&
          x.out.every((cell, k) => {
            const target = row.out[k];
            return (
              target.status === cell.status &&
              (cell.value === target.value ||
                (Number.isFinite(cell.value) &&
                  Number.isFinite(target.value) &&
                  Math.abs(cell.value - target.value) < 1e-12))
            );
          })
        );
      });
    if (token !== nativeToken) return;
    lastNative = match;
    native.textContent = match
      ? `Filang verified · ${anchors.length.toLocaleString('en-US')} matches · ${eligible.length.toLocaleString('en-US')} eligible`
      : 'Filang and browser results differ';
    if (!match) {
      el('save-open').disabled = true;
      notice('The native and browser results disagree. This run cannot be saved as verified.', true);
    }
  } catch (error) {
    if (token === nativeToken) native.textContent = 'Browser evaluated · ' + error.message;
  }
}
function setLibraryCount() {
  try {
    el('saved-count').textContent = String(readLibrary().length);
  } catch {
    el('saved-count').textContent = '—';
  }
}
function showDialog(...nodes) {
  mount(el('dialog-body'), ...nodes);
  if (!el('dialog').open) el('dialog').showModal();
}
function saveDialog() {
  if (dirty || !state.run || lastNative === false) return;
  const name = h('input', {
    id: 'name',
    class: 'name-input',
    maxlength: 100,
    value:
      el('examples').value === 'friday'
        ? 'Friday close'
        : current().event.plan.def?.title || current().event.label,
  });
  const status = h('p', { role: 'status' });
  const save = async () => {
    try {
      const title = name.value.trim();
      if (!title) {
        name.focus();
        return;
      }
      const saved = makeStudy(title, state.run, view());
      saved.artifacts = portableDefinitions();
      if (navigator.locks) await navigator.locks.request('limen.saved-questions', () => saveToLibrary(saved));
      else saveToLibrary(saved);
      setLibraryCount();
      const href = studyLink(saved);
      history.replaceState(null, '', href);
      const copy = h(
        'button',
        {
          type: 'button',
          onclick: async () => {
            try {
              await navigator.clipboard.writeText(href);
              copy.textContent = 'Copied';
            } catch {
              link.select();
            }
          },
        },
        'Copy link',
      );
      const link = h('input', {
        class: 'name-input',
        readonly: true,
        value: href,
        'aria-label': 'Saved question link',
        onclick: (e) => e.target.select(),
      });
      showDialog(
        h('h2', null, 'Question saved'),
        h('p', null, title),
        h(
          'p',
          { class: 'small' },
          'This link replays the pinned query and checks every saved population and outcome.',
        ),
        h('label', null, 'Local replay link'),
        link,
        h('div', { class: 'btn-row' }, copy, h('button', { onclick: () => el('dialog').close() }, 'Done')),
      );
    } catch (e) {
      status.textContent = e.message;
    }
  };
  name.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') save();
  });
  showDialog(
    h('h2', null, 'Save question'),
    h('label', { for: 'name' }, 'Question name'),
    name,
    h('div', { class: 'btn-row' }, h('button', { class: 'primary', onclick: save }, 'Save & create link')),
    status,
  );
  name.select();
}
function openLibrary() {
  try {
    const entries = readLibrary();
    showDialog(
      h('h2', null, 'Saved questions'),
      entries.length
        ? h(
            'ul',
            null,
            entries.map((saved) =>
              h(
                'li',
                null,
                h(
                  'a',
                  {
                    href: studyLink(saved),
                    onclick: (e) => {
                      e.preventDefault();
                      history.pushState(null, '', studyLink(saved));
                      el('dialog').close();
                      readLocation();
                    },
                  },
                  saved.name,
                ),
              ),
            ),
          )
        : h('p', null, 'Save a question to reopen its cases here.'),
    );
  } catch (e) {
    showDialog(h('p', null, e.message));
  }
}
function readLocation() {
  try {
    const saved = studyFromLink();
    if (saved) {
      installSaved(state.env, saved.artifacts || []);
      showInstalled();
      if (!runText(saved.query, { saved, startFresh: true, source: sourceFrom(saved.view.source) }))
        throw Error('The saved query cannot be resolved.');
      return;
    }
    const params = new URLSearchParams(location.search);
    if (params.has('g1') || params.has('pattern')) {
      const definitions = new URLSearchParams(location.hash.slice(1)).get('definitions');
      if (definitions) {
        installSaved(state.env, JSON.parse(definitions));
        showInstalled();
      }
      const pattern = params.has('pattern') ? state.env.registry.getPattern(params.get('pattern')) : null;
      if (params.has('pattern') && !pattern) throw Error('Unknown Composer pattern.');
      const source = pattern
        ? seed()
        : sourceFrom({
            g1: params.get('g1'),
            drawing: params.get('drawing'),
            anchor: params.has('anchor') ? Number(params.get('anchor')) : null,
          });
      const prior = params.get('question');
      const a = analyze(prior || (pattern ? HAMMER : FRIDAY), state.env.env);
      if (!a.ok) throw Error('The originating query could not be resolved.');
      const q = structuredClone(a.ast);
      q.find = parseExpression(
        pattern ? JSON.stringify(pattern.canonicalName) : 'exact_g1(' + JSON.stringify(source.g1) + ')',
      ).ast;
      const retained = new Set();
      // A binding used only by the previous detector no longer belongs to this query.
      function collect(n) {
        if (!n || typeof n !== 'object') return;
        if (n.k === 'id') retained.add(n.name);
        Object.values(n).forEach(collect);
      }
      [q.find, ...q.wheres, q.group, ...q.measures].forEach(collect);
      q.lets = q.lets.filter((b) => retained.has(b.name));
      const handoffURL = location.href;
      if (!runText(printQuestion(q), { source, startFresh: true }))
        throw Error('The imported pattern could not run.');
      history.replaceState(null, '', handoffURL);
      notice(
        pattern
          ? pattern.title + ' imported from Composer.'
          : 'Composer drawing imported. This study uses exact G1 twins.',
      );
      return;
    }
    runText(HAMMER, { source: seed(), startFresh: true });
  } catch (e) {
    if (!state.run) {
      el('query-state').textContent = 'Could not open question';
      el('run').disabled = true;
    }
    notice(e.message, true);
  }
}
async function start() {
  setLibraryCount();
  el('show-library').onclick = openLibrary;
  const jumpTo = (id) => {
    el(id).focus({ preventScroll: true });
    el(id).scrollIntoView({ block: 'start' });
  };
  el('jump-results').onclick = () => jumpTo('cases-title');
  el('jump-builder').onclick = () => jumpTo('question-title');
  el('save-open').onclick = saveDialog;
  try {
    const [csvBytes, provenanceBytes, sessionsBytes, ...defs] = await Promise.all(
      [...Object.values(DATA_FILES), ...EXTENSION_FILES].map(bytes),
    );
    state.env = buildEnvironment({
      csvBytes,
      provenanceBytes,
      sessionsBytes,
      extensions: EXTENSION_FILES.map((file, i) => ({ file, bytes: defs[i] })),
    });
    if (!state.env.digestVerified || state.env.extensions.some((e) => !e.ok))
      throw Error('Recording or definition verification failed.');
    let libraryProblem = '';
    try {
      loadInstalled(state.env);
    } catch (e) {
      libraryProblem = 'Local definitions could not be restored. ' + e.message;
    }
    showInstalled();
    if (libraryProblem) el('installations').prepend(h('p', { class: 'warn' }, libraryProblem));
    state.source = seed();
    builder = setupBuilder(el('builder'), {
      state,
      edit: runText,
      openDialog: showDialog,
      closeDialog: () => el('dialog').close(),
      getComposerURL: composerURL,
    });
    hideFormalMenu = setupFormalMenu(el('query'), el('formal-menu'), state.env.env);
    const newQuestion = el('new-question');
    newQuestion.disabled = false;
    newQuestion.onclick = () => {
      if (state.analysis) builder.newQuestion(newQuestion);
      else runText(HAMMER, { startFresh: true, source: seed() }) && builder.newQuestion(newQuestion);
    };
    el('examples').onchange = (e) =>
      runText({ breakout: transfer, friday: FRIDAY, hammer: HAMMER }[e.target.value], {
        startFresh: true,
        source: seed(),
      });
    el('query').addEventListener('input', () => {
      clearTimeout(editTimer);
      markDirty();
      mount(el('errors'));
      editTimer = setTimeout(() => runText(el('query').value, { live: true }), 450);
    });
    el('revert-edit').onclick = () => runText(state.analysis.canonical);
    el('run').onclick = () => runText(el('query').value);
    el('query').addEventListener('keydown', (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        e.preventDefault();
        runText(el('query').value);
      }
    });
    addEventListener('hashchange', readLocation);
    practice = setupPractice(el('practice'), {
      state,
      openDialog: showDialog,
      closeDialog: () => el('dialog').close(),
      hasPendingEdits: () => dirty,
    });
    el('practice').disabled = false;
    readLocation();
    let width = el('chart').clientWidth;
    new ResizeObserver(() => {
      const w = el('chart').clientWidth;
      if (w !== width && state.run) {
        width = w;
        renderEvidence(state, selectCandidate);
      }
    }).observe(el('chart'));
  } catch (e) {
    notice(e.message, true);
    el('query-state').textContent = 'Study unavailable';
  }
}
start();
