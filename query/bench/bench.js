// Filang query bench. One locked canvas shows the pattern; the question is written in its row labels.
// Panels around it toggle: the pattern catalogue, the inspector, and a drawer for cases, tape, query and the Limen hand-off.
import { load, loaded, geometryRadiusReceipt, sources, PINNED, run, count, rec, env, definition, HEAD, ANY_CLOSE, T, F, isoUTC, int, pct, share, nyText, price, observed } from '/shared/filang.js';
import { CLAUSES, PATTERNS, PRESETS, HORIZONS, OFFERS, DIMENSIONS, make, clone, toText, bodyText, fromText, clauseText, splitText, phraseText, drawingBars, drawingHeld, drawingRecorded, drawingDimensions, g1Price, g1Parts, offered, dimensionsIn } from '/shared/vocab.js';
import { readLink, packetFromG1, casePacket, composerLink, relationsOf, attach, decodeDrawing, drawingG1, pinnedExpression } from '/shared/handoff.js';
import { h, mount, $, plate, phrase, slotPopover, closePopover, refocusSlot } from '/shared/ui.js';
import { candleChart, candleAnatomy, distPlot, rateRail, tapeOverview } from '/shared/chart.js';
import { aggregate, caseColumns, columnAt, domainOf, drawLane, drawAxis, drawColumnTrack, drawDimensionLane, drawGlyph, drawShape, geom, barsOf, offsetLabel, unitText, lanesShown, setLane, lanesParam, lanesFromParam, dimensionColumns, dimensionText, dimensionExact, UNIT } from './lanes.js';

// The other two aspects of the tool. They are separate apps today; these links carry the pattern across.
// On a vaquum.fi host they are the deployed sites behind the same Portal login; elsewhere, the local servers.
const DEPLOYED = location.hostname.endsWith('.vaquum.fi');
const COMPOSER = DEPLOYED ? 'https://composer.vaquum.fi/bench/' : 'http://localhost:8794/bench/';
const CUBE = DEPLOYED ? 'https://cube.vaquum.fi/' : 'http://localhost:8791/';

const saved = (() => { try { return JSON.parse(localStorage.getItem('filang.bench') || '{}'); } catch { return {}; } })();
const ui = { left: saved.left ?? false, right: saved.right ?? window.innerWidth >= 1000, drawer: saved.drawer ?? null, window: saved.window ?? null };
const persist = () => { try { localStorage.setItem('filang.bench', JSON.stringify(ui)); } catch { /* storage is optional */ } };
const state = { model: null, preset: PRESETS[0].id, candidate: 0, rows: 'ledger', splitBy: 'trend', cells: 'candle', unit: 'pct', track: 'up', lead: 8,
  lane: null, slot: null, side: 'kept', page: 0, sort: 'date', focus: null, catalog: '', catSort: 'family',
  caseSort: { key: 't', dir: 1 }, casePage: 0, caseKey: '', caseFollow: false, notice: '',
  // The dimension lanes switched on or off by hand. A dimension the question refers to is shown without a switch.
  dims: {},
  // What the server can read (the cube's windows, or the pinned recording only) and whether a window is being fetched.
  // `asked` is a window the cube could not give when the page opened: the address keeps asking for it.
  source: { cube: false, default: PINNED, windows: [] }, loading: false, asked: null };
let ctx = null;
const pad = (n) => String(n).padStart(2, '0');
const cap = (t) => t[0].toUpperCase() + t.slice(1);
const SYM = { [T]: '✓', [F]: '✗', '-1': '?' };
const pc = (f) => (f === null || f === undefined ? '—' : Math.round(f * 100) + '%');
/** Wilson score interval for a share. It treats the observations as independent. */
function wilson(k, n) {
  if (!n) return null;
  const z = 1.96; const p = k / n; const d = 1 + (z * z) / n; const c = (p + (z * z) / (2 * n)) / d; const hw = (z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n))) / d;
  return [Math.max(0, c - hw), Math.min(1, c + hw)];
}
const label = (text, cls = '') => h('span', { class: 'label ' + cls }, text);
const note = (text, cls = '') => h('span', { class: 'note ' + cls }, text);
const quiet = (text, fn, title) => h('button', { class: 'quiet', type: 'button', title, onclick: (e) => { e.stopPropagation(); fn(); } }, text);
// A dimension is one number per candle beside its prices, read from the cube's counters. Bars without counters have
// none: there the bench offers no dimension clause and no lane, and the engine refuses a question that uses one.
const DIM = Object.fromEntries(DIMENSIONS.map((d) => [d.key, d]));
const counters = () => rec().hasCounters;
/** Whether the loaded bars can be asked this clause. */
const can = (c) => offered(c.type, counters());
/** Whether a run failed only because the bars lack what the question reads: the engine's capability refusal, and nothing else. */
const refusal = (res) => !res.ok && res.errors.length > 0 && res.errors.every((e) => e.kind === 'capability');

function summarize(rows, k) {
  const v = observed(rows, k); const n = v.length;
  if (!n) return { n: 0, up: '—', frac: null, median: null, mean: null, values: [] };
  const mid = n >> 1;
  const ups = v.filter((x) => x > 0).length;
  return { n, k: ups, up: share(ups, n), frac: ups / n, median: n % 2 ? v[mid] : (v[mid - 1] + v[mid]) / 2, mean: v.reduce((a, b) => a + b, 0) / n, values: v };
}
function update(fn, keep) { fn(state.model); state.focus = keep || null; state.notice = ''; render(); }
const target = (m, path) => (path[0] === 'f' ? m.find.items[+path.slice(1)] : m.wheres[+path.slice(1)]);
const slotEdit = (path) => ({
  allowCompare: true, capital: true,
  // A stepped value, or one chosen in a popover that then closes, keeps the keyboard on the redrawn slot.
  onChange: (key, value, refocus) => update((m) => { target(m, path).args[key] = value; if (Array.isArray(value)) state.rows = 'compare'; }, refocus ? { clause: path, slot: key } : null),
  countFor: (key, value) => { const c = clone(state.model); const t = target(c, path); t.args[key] = value; t.off = false; return count(bodyText(c)); },
});

// ---------------------------------------------------------------- shapes carried to and from Composer

// A drawn shape arrives from the Composer bench as the engine's drawing packet and leaves the same way. Only the shape
// and what is held on it cross: Composer searches 15m to 4h bars from 2020 to now, this bench the window it has open.
const OWN_COUNT = 'Composer searches 15m to 4h bars from 2020 to now. This bench counts the 15m bars of the window named at the foot of the page, so the two counts differ by design.';
/** Bars of the pattern in `find`, and whether the question says how many there are. */
const findBars = (m) => Math.max(1, ...m.find.items.map((c) => (c.type === 'pattern' ? PATTERNS.find((p) => p.id === c.args.p)?.bars || 1 : c.type === 'drawing' ? drawingBars(c) : 1)));
const findBarsKnown = (m) => m.find.items.some((c) => c.type === 'pattern' || c.type === 'drawing');
const rebuilt = new Map();
/** The drawing a drawn shape stands for: the packet it came with, or one rebuilt from its g1 at even rank spacing. */
function packetOf(c) {
  if (c.args.packet) return c.args.packet;
  const code = c.args.g1;            // the dimension parts travel with the drawing, as its `dimensions`
  if (!rebuilt.has(code)) rebuilt.set(code, packetFromG1(code));
  return rebuilt.get(code);
}
/** A g1 code as lines: the price shape, then each dimension it switches on with its candles from lowest to highest. */
function codeLines(c) {
  return [h('code', { class: 'g1' }, g1Price(c.args.g1)),
    g1Parts(c.args.g1).map((p) => h('code', { class: 'g1 part', title: `${DIM[p.key].label}: ${DIM[p.key].what}. Only the order is asked${p.reference === null ? '' : '; below zero is net selling, above it net buying'}.` },
      h('b', null, p.text), ` ${p.order}`))];
}
/** A drawn shape as a row label: its glyph at true proportions, what is asked of it, and its g1. */
function drawnParts(c) {
  const p = packetOf(c); const n = drawingBars(c); const rel = c.args.packet ? relationsOf(c.args.packet) : []; const glyph = h('span', { class: 'shape' });
  if (p) drawShape(glyph, p.bars);
  // Three ways to ask a drawing. The shape is the default and carries no qualifier: a drawn shape is a chain, and
  // the recording is read as one. Its opens as recorded is the older, stricter reading; one bar has no later open,
  // so there the two agree and only one is offered.
  const now = drawingHeld(c) ? 'held' : drawingRecorded(c) ? 'recorded' : 'shape';
  const form = (key, text, title, cls) => h('button', { type: 'button', class: cls || null, 'data-form': key, 'aria-pressed': String(now === key), title,
    onclick: (e) => {
      e.stopPropagation(); const at = e.currentTarget.closest('[data-clause]')?.dataset.clause;
      update(() => { c.args.held = key === 'held'; c.args.recorded = key === 'recorded'; });
      // the row is redrawn by the change: the option that was chosen keeps the focus, so the keys stay on the switch
      if (at) $(`[data-clause="${at}"] .join.form button[data-form="${key}"]`)?.focus();
    } }, text);
  const forms = [form('shape', 'shape', n === 1 ? 'Every endpoint in the same order, with the same ties and directions'
    : 'Every endpoint in the same order, with the same ties and directions, the candles read as the chain they are drawn as: each later one opens at the close before it')];
  if (rel.length) forms.push(form('held', `${rel.length} held`, cap(rel.join(' · ')) + '. Only which side each level lies on is kept.'));
  // A code that can be drawn ties each later open to the close before it. Only then are the two readings two
  // readings of one shape, and only then is the switch offered. A typed code whose later open lies away from that
  // close is no chain: it is shown with the reading it was typed with, and says so.
  if (n > 1 && p) forms.push(form('recorded', 'as recorded', 'The same shape with each later open as the recording has it, not as the close before it. The shape ties each later open to that close, so read this way it matches only where the recorded open equals it to the cent, about half of adjacent candles.', 'faint'));
  const loose = n > 1 && !p ? h('span', { class: 'from', title: drawingRecorded(c) ? 'This code has a later bar opening away from the close before it, or keeps no directions, so it cannot be drawn as a chain. It is counted with opens as recorded.' : 'This code cannot be drawn as a chain, and it is asked as one: a window read as a chain always opens each later bar at the close before it, so nothing can match.' }, drawingRecorded(c) ? 'opens as recorded · not a chain' : 'read as a chain · not a chain') : null;
  const radius = Number(c.args.radius) || 0;
  let radiusControl = null;
  if (!drawingHeld(c)) {
    const stepRadius = h('input', {type: 'number', min: 0, max: 4294967295, step: 1,
      value: Array.isArray(c.args.radius) ? '' : radius, placeholder: 'sweep', 'aria-label': 'Comparison radius',
      onchange: (event) => {
        const value = event.currentTarget.valueAsNumber;
        if (!Number.isInteger(value) || value < 0 || value > 4294967295) return;
        const path = event.currentTarget.closest('[data-clause]')?.dataset.clause;
        update(() => { c.args.radius = value; });
        if (path) $(`[data-clause="${path}"] input[aria-label="Comparison radius"]`)?.focus();
      }});
    const reading = c.args.recorded ? 'recorded' : 'chained';
    const bins = radius > 0 ? geometryRadiusReceipt(c.args.g1, reading, radius) : [];
    const expanded = bins.reduce((sum, [cost, count]) => sum + (cost > 0 ? count : 0), 0);
    radiusControl = h('span', {class: 'radius-control'},
      h('label', null, 'Radius ', stepRadius),
      radius > 0 ? h('small', {title: bins.map(([cost, count]) => `${cost} half-flips · ${int(count)}`).join('\n')},
        ` +${int(expanded)} within radius`) : null);
  }
  return [glyph, h('span', { class: 'drawn' }, `${c.not ? 'Not a' : 'A'} ${p ? 'drawn shape' : 'g1 code'} · ${n} ${n === 1 ? 'bar' : 'bars'}`,
    p && forms.length > 1 ? h('span', { class: 'join form' }, forms) : null), loose,
  codeLines(c), radiusControl,
  c.args.packet ? h('span', { class: 'from', title: OWN_COUNT }, 'From Composer · counted on this window') : null];
}
/** The row label of a find clause: a drawn shape reads as a shape, everything else as its phrase. */
const findParts = (c, path) => (c.type === 'drawing' ? drawnParts(c) : phrase(c, slotEdit(path)));
/** The recorded candles ending at one close, as a link that draws them in Composer; a reason when they are not a drawing. */
function candlesLink(i, cls = 'quiet') {
  const m = state.model; const n = Math.max(2, Math.min(20, findBarsKnown(m) ? findBars(m) : 3)); const res = casePacket(rec(), i, n, ctx?.dims ?? []);
  // the candles are sent as the chain they are read as, so what Composer draws is the shape this close matches
  return res.packet ? h('a', { class: cls + ' out', href: composerLink(COMPOSER, res.packet), target: '_blank', rel: 'noopener', onclick: (e) => e.stopPropagation(),
    title: `The ${n} recorded candles ending at this close, drawn as a chain: each later bar opens at the previous close. Nothing is held. Composer counts them on its own history.` }, `Draw these ${n} candles in Composer ↗`)
    : h('span', { class: cls + ' out off', title: `The ${n} candles ending at this close are not a drawing: ${res.why}.` }, `Not drawable in Composer: ${res.why}`);
}

// ---------------------------------------------------------------- menus

let popup = null;
function closeMenu() { if (popup) { popup.remove(); popup = null; document.removeEventListener('mousedown', outsideMenu, true); } }
function outsideMenu(e) { if (popup && !popup.contains(e.target) && !e.target.closest('[data-menu]')) closeMenu(); }
function menu(anchor, { title, hint, options, value, onChange }) {
  closeMenu(); closePopover();
  popup = h('div', { class: 'pop', role: 'menu', onkeydown: (e) => { if (e.key === 'Escape') { closeMenu(); anchor.focus(); } } },
    h('header', null, label(title)), hint ? h('p', { class: 'note' }, hint) : null,
    h('ul', null, options.map((o) => h('li', null, h('button', { type: 'button', role: 'menuitemradio', 'aria-checked': String(o.value === value), disabled: o.disabled,
      onclick: () => { closeMenu(); onChange(o.value); } }, h('span', null, o.label, o.detail ? h('small', null, o.detail) : null))))));
  document.body.append(popup);
  const r = anchor.getBoundingClientRect();
  popup.style.left = Math.max(8, Math.min(window.innerWidth - popup.offsetWidth - 8, r.left)) + 'px';
  popup.style.top = (r.bottom + popup.offsetHeight + 4 < window.innerHeight ? r.bottom + 1 : r.top - popup.offsetHeight - 1) + 'px';
  document.addEventListener('mousedown', outsideMenu, true);
}

// ---------------------------------------------------------------- lanes

function buildLanes(res, r, text, H) {
  const m = state.model; const lanes = [];
  const active = m.wheres.map((c, i) => ({ c, i })).filter((x) => !x.c.off);
  const key = (id) => `${text}#${state.candidate}#${id}`;
  const add = (lane) => { lane.slots = lane.rows.map((row) => row.i); lane.aggKey = lane.key || key(lane.id); lane.agg = aggregate(lane.aggKey, lane.slots, state.lead, H, state.unit); lanes.push(lane); return lane; };
  add({ id: 'find', kind: 'find', rows: r.rows, r, title: 'The pattern' });
  if (state.rows === 'ledger') {
    // Each pattern's compared values are its own runs. The query's axes are in source order and the patterns open it,
    // so pattern idx owns the next run of axes; pick its run with the values of the selected candidate.
    let axis = 0; // -1 once a pattern does not check on its own: the axes after it can no longer be placed
    if (m.find.items.length > 1) m.find.items.forEach((c, idx) => {
      const body = `find ${clauseText(c)}${m.horizons.length ? `\nmeasure close_return(after: [${m.horizons.join(', ')}])` : ''}`;
      const alt = run(`${HEAD}\n${body}`);
      if (!alt.ok) { axis = -1; return; }
      let ai = 0;
      if (axis >= 0) {
        const n = alt.analysis.axes.length; const want = r.cand.assignment.slice(axis, axis + n).map((a) => a.valueIndex); axis += n;
        ai = Math.max(0, alt.results.findIndex((x) => x.cand.assignment.every((a, j) => a.valueIndex === want[j])));
      }
      add({ id: 'f' + idx, kind: 'alt', idx, c, rows: alt.results[ai].rows, r: alt.results[ai], key: `${body}|alt#${ai}`, title: cap(phraseText(c)) });
    });
    m.wheres.forEach((c, i) => {
      const k = active.findIndex((x) => x.i === i);
      if (k < 0) { lanes.push({ id: 'w' + i, kind: 'off', wi: i, c, rows: [], slots: [] }); return; }
      // The text names the applied lines in order, so the k-th applied line is what fixes this population, not its index among muted ones.
      add({ id: 'w' + i, key: key('k' + k), kind: 'where', k, wi: i, c, r, rows: r.rows.filter((row) => row.failAt === -1 || row.failAt > k), removed: r.rows.filter((row) => row.failAt === k), title: `Line ${pad(i + 2)}` });
    });
  } else {
    if (active.length) add({ id: 'answer', kind: 'answer', rows: r.matches, r, title: 'The answer' });
    if (state.rows === 'split' && r.groups) for (const g of r.groups) if (g.count) add({ id: 'g:' + g.key, kind: 'group', label: g.label, rows: g.rows, r, title: cap(g.label) });
    if (state.rows === 'compare') res.results.forEach((x, ci) => add({ id: 'c:' + ci, kind: 'run', ci, label: x.cand.assignment.map((a) => `${a.axis.split('.').pop()} ${a.value}`).join(' · '), rows: x.matches, r: x, key: `${text}#${ci}#run`, title: 'Run ' + x.cand.assignment.map((a) => a.value).join(' · ') }));
  }
  return lanes;
}
const answerId = (lanes) => { const real = lanes.filter((l) => ['where', 'answer'].includes(l.kind)); return real.length ? real[real.length - 1].id : 'find'; };

function render() {
  const m = state.model;
  // A split read from the query keeps its own arguments, such as a 1d trend frame.
  if (state.rows !== 'split') m.split = null; else if (m.split?.type !== state.splitBy) m.split = make(state.splitBy);
  const text = toText(m);
  const res = run(text);
  const status = $('#status');
  const used = res.analysis.ast ? dimensionsIn(text, res.analysis.ast) : [];
  // The address reproduces the run. A drawn shape that came as a packet stays in it beside the text, so a reload or a
  // shared link still knows the drawing; it goes when the find is no longer that drawing. The dimension lanes on show
  // are named in it too. What a link carried in the query string is spent.
  const address = () => {
    const dr = m.find.items.find((c) => c.type === 'drawing' && c.args.packet)?.args.packet; const ln = lanesParam(used, state.dims);
    try { history.replaceState(null, '', location.pathname + '#q=' + encodeURIComponent(text) + (dr ? '&dr=' + encodeURIComponent(JSON.stringify(dr)) : '') + (state.source.cube ? '&w=' + encodeURIComponent(state.asked || loaded()) : '') + (ln === null ? '' : '&ln=' + ln)); } catch { /* the address is optional */ }
  };
  if (!res.ok) {
    // What these bars lack is the engine's to refuse and the bench's to show: the question stays, and so does its address.
    if (refusal(res)) { address(); return renderRefused(text, res); }
    const msg = res.errors.map((e) => e.message).join(' · '); status.textContent = msg; status.className = 'err'; formal.message(msg); return;
  }
  if (state.rows === 'compare' && res.results.length < 2) { state.rows = 'ledger'; return render(); }
  state.candidate = Math.min(state.candidate, res.results.length - 1);
  const r = res.results[state.candidate];
  const hk = m.horizons.map(barsOf); const H = Math.min(96, Math.max(16, ...hk));
  const pbars = Math.min(state.lead + 1, findBars(m));
  const lanes = buildLanes(res, r, text, H);
  ctx = { res, r, text, H, hk, pbars, lanes, answer: lanes.find((l) => l.id === answerId(lanes)), caseLanes: [], used, dims: counters() ? lanesShown(used, state.dims) : [] };
  address();
  if (document.activeElement !== formal.el.querySelector('textarea')) formal.set(text); else formal.message('');
  addInput.disabled = false;
  $('#left').hidden = !ui.left; $('#right').hidden = !ui.right; $('#drawer').hidden = !ui.drawer;
  status.className = ''; status.textContent = state.notice || `${res.ms.toFixed(0)} ms · sha256 ${env().digest.slice(0, 10)} ${env().digestVerified ? 'verified' : 'unverified'}`;
  renderBars(); renderCanvas(); renderLeft(); renderRight(); renderDrawer();
  refocusSlot($('#lanes'), state.focus); state.focus = null;
}

// ---------------------------------------------------------------- bars

const enc = (name, value, open) => { const b = h('button', { class: 'enc', type: 'button', 'data-menu': '1', onclick: () => open(b) }, label(name), h('span', { class: 'val' }, value), h('i', null, '▼')); return b; };
/** The bars the question is asked of, and the starting questions: the two choices that stand whether or not it can be answered. */
const windowEnc = () => (state.source.cube ? enc('Window', state.loading ? 'Loading…' : env().provenance.source === 'cube' ? env().provenance.window_name : 'Pinned recording', (b) => menu(b, { title: 'Window', hint: 'The bars the question is asked of: Cube’s time windows, read from the cube. A window ends at the latest complete bar.', value: loaded(),
  options: [...state.source.windows.map((w) => ({ value: w.key, label: w.name })), { value: PINNED, label: 'Pinned recording', detail: 'Jan to May 2025, the bars the verification suite counts' }], onChange: openWindow })) : null);
const questionEnc = () => enc('Question', PRESETS.find((p) => p.id === state.preset)?.title || 'Custom', (b) => menu(b, { title: 'Starting questions', value: state.preset, options: PRESETS.map((p) => ({ value: p.id, label: p.title })), onChange: (id) => open(PRESETS.find((p) => p.id === id)) }));

function renderBars() {
  const m = state.model; const R = rec();
  const prov = env().provenance; const fromCube = prov.source === 'cube';
  // Bars after the cube's canonical mark can still change: Cube shows them too, and says how far the mark has come.
  $('#chip').textContent = `${R.instrument} ${R.barText} · ${R.venue || 'Binance spot'} · ${env().rangeText} · ${int(R.presentCount)} ${R.presentCount === 1 ? 'close' : 'closes'} · `
    + (fromCube ? `cube, through ${isoUTC(Date.parse(prov.through)).slice(0, 16)} UTC${prov.provisional_rows ? ` · last ${int(prov.provisional_rows)} provisional` : ''}` : 'pinned recording');
  $('#chip').title = fromCube ? `Read from the market-state cube through Cube's bridge${prov.canonical_through ? `. Canonical through ${isoUTC(Date.parse(prov.canonical_through)).slice(0, 16)} UTC; later bars are provisional` : ''}.` : 'The pinned BTCUSDT 15m recording built into this server.';
  // Without an answer only the catalogue and the query text have anything to show: the other panels wait for one.
  for (const b of document.querySelectorAll('.toggles button')) { const p = b.dataset.panel; b.disabled = !ctx && p !== 'left' && p !== 'query'; b.setAttribute('aria-pressed', String(!b.disabled && (p === 'left' ? ui.left : p === 'right' ? ui.right : ui.drawer === p))); }
  $('#to-cube').href = CUBE; $('#to-cube').title = 'Open the Cube explorer';
  if (!ctx) {
    // A refused question has no answer to read out and no canvas to encode: the window and the question remain.
    mount($('#readout'), note('The engine refused this question'));
    mount($('#encbar'), windowEnc(), questionEnc());
    $('#to-composer').href = COMPOSER; $('#to-composer').title = 'Open the Composer bench';
    return;
  }
  const { res, r, answer } = ctx; const n = answer.rows.length;
  mount($('#readout'), h('b', null, int(n)), note(n === 1 ? 'close in the answer' : 'closes in the answer'), r.columns.length ? h('span', { class: 'sep' }) : null,
    r.columns.slice(0, 3).map((c, k) => h('span', { class: 'sub' }, h('b', { class: 'fig' }, summarize(answer.rows, k).up), ` up after ${c.text}`)));
  const sweeps = res.results.length > 1;
  const first = m.find.items[0]; const pid = first.type === 'pattern' ? first.args.p.replaceAll('_', '-') : null;
  const frame = m.split?.type === 'trend' ? m.split.args.frame : '4h';
  mount($('#encbar'),
    windowEnc(),
    questionEnc(),
    enc('Rows', { ledger: 'Ledger', split: state.splitBy === 'trend' ? `Split by ${frame} trend` : state.splitBy === 'weekday' ? 'Split by session day' : 'Split by condition', compare: 'Compared runs', cases: 'Cases' }[state.rows], (b) => menu(b, {
      title: 'Rows', hint: 'What each row under the pattern holds.', value: state.rows === 'split' ? 'split:' + state.splitBy : state.rows,
      options: [{ value: 'ledger', label: 'Ledger', detail: 'One row per condition, drawn from the closes it leaves' },
        { value: 'split:trend', label: `Split by ${frame} trend`, detail: `The answer divided by the last completed ${frame} bar` },
        { value: 'split:weekday', label: 'Split by session day', detail: 'The answer divided by New York session day' },
        { value: 'compare', label: 'Compared runs', detail: sweeps ? 'One row per compared value' : 'Alt-click a second value in a condition first', disabled: !sweeps },
        { value: 'cases', label: 'Cases', detail: 'The recorded closes of the answer, one per row' }],
      onChange: (v) => { const [mode, by] = v.split(':'); state.rows = mode; if (by) state.splitBy = by; state.lane = null; state.page = 0; if (mode !== 'cases') state.slot = null; render(); } })),
    enc('Cells', state.cells === 'candle' ? 'Median candle' : 'Traded range', (b) => menu(b, { title: 'Cells', hint: 'What is drawn in each column of a row.', value: state.cells,
      options: [{ value: 'candle', label: 'Median candle', detail: 'Median open, high, low and close. The band is the middle half of closes.' },
        { value: 'density', label: 'Traded range', detail: 'How often the row’s candles traded each price row: wicks faint, bodies bright. Line: median close.' }], onChange: (v) => { state.cells = v; render(); } })),
    enc('Scale', state.unit === 'pct' ? '% of close' : 'R, anchor range', (b) => menu(b, { title: 'Scale', hint: 'The price unit, measured from the anchor close.', value: state.unit,
      options: [{ value: 'pct', label: '% of the anchor close', detail: 'The unit of the measured return' }, { value: 'range', label: 'R', detail: 'Multiples of the anchor candle’s high–low range' }], onChange: (v) => { state.unit = v; render(); } })),
    enc('Columns', state.track === 'up' ? 'Closed above anchor' : 'Median range', (b) => menu(b, { title: 'Column track', hint: 'The band under the canvas, for the selected row.', value: state.track,
      options: [{ value: 'up', label: 'Closed above the anchor', detail: 'Share of closes above the anchor close, around 50%' }, { value: 'range', label: 'Median range', detail: 'Median high–low range of each column, as % of the anchor close' }], onChange: (v) => { state.track = v; render(); } })),
    // One switch per dimension, on bars that carry them. A lane the question refers to is on until it is switched off.
    counters() ? (() => { const b = h('button', { class: 'enc', type: 'button',
      onclick: () => slotPopover(b, { multi: true, empty: true, title: 'Dimension lanes', slot: { key: 'lanes', kind: 'enum', options: DIMENSIONS.map((d) => d.key), labels: Object.fromEntries(DIMENSIONS.map((d) => [d.key, d.label])) }, value: ctx.dims,
        onChange: (v) => { for (const d of DIMENSIONS) setLane(state.dims, ctx.used, d.key, v.includes(d.key)); render(); } }) },
    label('Lanes'), h('span', { class: 'val' }, ctx.dims.length > 2 ? `${ctx.dims.length} dimensions` : ctx.dims.map((d) => DIM[d].label).join(', ') || 'None'), h('i', null, '▼')); return b; })() : null,
    (() => { const b = h('button', { class: 'enc', type: 'button', onclick: () => slotPopover(b, { multi: true, title: 'Measured horizons', slot: { key: 'after', kind: 'enum', options: HORIZONS, sweep: true }, value: m.horizons, onChange: (v) => update((x) => { x.horizons = v; }) }) },
      label('Measure'), h('span', { class: 'val' }, m.horizons.join(', ') || 'None'), h('i', null, '▼')); return b; })(),
    enc('Lead-in', state.lead + ' bars', (b) => menu(b, { title: 'Lead-in', hint: 'Bars shown before the deciding close.', value: state.lead, options: [4, 8, 16, 32].map((v) => ({ value: v, label: v + ' bars' })), onChange: (v) => { state.lead = v; render(); } })));
  // The Composer bench opens on what the question is about: its named pattern, else the shape it draws.
  // Composer draws two bars or more, so a one-bar shape is not carried.
  const drawn = pid ? null : m.find.items.find((c) => c.type === 'drawing'); const out = drawn ? packetOf(drawn) : null; const carry = out && out.bars.length >= 2;
  $('#to-composer').href = pid ? `${COMPOSER}?pattern=${pid}` : carry ? composerLink(COMPOSER, out) : COMPOSER;
  $('#to-composer').title = pid ? 'Open this pattern in Composer' : carry ? `Draw this shape in Composer${drawn.args.packet ? '' : ', at even spacing: a g1 keeps order, not distances'}` : drawn ? 'Composer draws two bars or more and joins each open to the previous close: this shape is not carried' : 'Open the Composer bench';
}

// ---------------------------------------------------------------- canvas

// A row label is a ledger line: a hanging line number, a short role, the editable phrase, then a receipt and quiet actions.
function laneHead(lane) {
  const m = state.model; const R = rec(); const { r } = ctx;
  const head = (no, name, texts, receipt, actions = [], extra = null) => [
    h('span', { class: 'no' }, no || ''), h('span', { class: 'role' }, label(name), extra, actions.length ? h('span', { class: 'acts' }, actions) : null),
    h('div', { class: 'texts' }, texts),
    receipt ? h('div', { class: 'foot-line' }, h('span', { class: 'receipt' }, receipt)) : null];
  if (lane.kind === 'off') return [h('span', { class: 'no' }, pad(lane.wi + 2)), h('span', { class: 'text' }, cap(phraseText(lane.c))),
    quiet('Unmute', () => update(() => { lane.c.off = false; }), 'Apply this condition again'), quiet('Remove', () => update((x) => { x.wheres.splice(lane.wi, 1); }))];
  if (lane.kind === 'find') {
    const multi = m.find.items.length > 1;
    return head('01', multi && state.rows === 'ledger' ? 'Find, combined' : 'Find',
      multi && state.rows === 'ledger' ? h('div', { class: 'text' }, m.find.join === 'or' ? 'Any of the patterns below' : 'All of the patterns below, on one close')
        : m.find.items.map((c, idx) => h('div', { class: 'text' + (c.type === 'drawing' ? ' shape-line' : ''), 'data-clause': 'f' + idx }, idx ? label(m.find.join, 'or') : null, findParts(c, 'f' + idx))),
      `${share(r.counts.T, R.presentCount, 1)} of the tape${r.counts.U ? ` · ${int(r.counts.U)} unknown` : ''}`,
      [quiet('Change pattern', () => togglePanel('left', true), 'Open the pattern catalogue')],
      multi ? h('span', { class: 'join' }, ['or', 'and'].map((j) => h('button', { type: 'button', 'aria-pressed': String(m.find.join === j), onclick: () => update((x) => { x.find.join = j; }) }, j))) : null);
  }
  if (lane.kind === 'alt') return head(null, m.find.join, h('div', { class: 'text' + (lane.c.type === 'drawing' ? ' shape-line' : ''), 'data-clause': 'f' + lane.idx }, findParts(lane.c, 'f' + lane.idx)), 'on its own',
    [quiet('Remove', () => update((x) => { x.find.items.splice(lane.idx, 1); }), 'Remove this pattern')]);
  if (lane.kind === 'where') {
    const entering = lane.k === 0 ? r.counts.T : r.survivors[lane.k - 1]; const nu = lane.removed.filter((row) => row.results[lane.k].v !== F).length;
    return head(pad(lane.wi + 2), 'And', h('div', { class: 'text', 'data-clause': 'w' + lane.wi }, phrase(lane.c, slotEdit('w' + lane.wi))),
      `${int(entering)} → ${int(lane.rows.length)}${nu ? ` · ${int(nu)} unknown` : ''}`,
      [quiet(lane.c.not ? 'Affirm' : 'Negate', () => update(() => { lane.c.not = !lane.c.not; }), 'Turn this condition into its opposite'),
        quiet('Mute', () => update(() => { lane.c.off = true; }), 'Keep the line but stop applying it'),
        quiet('Remove', () => update((x) => { x.wheres.splice(lane.wi, 1); state.lane = null; }))]);
  }
  if (lane.kind === 'answer') return head(null, 'Answer, every condition', m.wheres.map((c, i) => (c.off ? null : h('div', { class: 'text small', 'data-clause': 'w' + i }, phrase(c, slotEdit('w' + i))))));
  if (lane.kind === 'group') return head(null, 'Split', h('div', { class: 'text' }, cap(lane.label)));
  if (lane.kind === 'run') return head(null, 'Run', h('div', { class: 'text fig' }, lane.label));
  return head(null, 'Case', h('div', { class: 'text fig' }, isoUTC(lane.row.t)), nyText(lane.row.t), [candlesLink(lane.row.i)]);
}

// The row track: one cell per measure, each a figure, a caption and a thin meter. Thin samples are dimmed.
function laneTrack(lane, shown) {
  const { r } = ctx; const R = rec();
  if (lane.kind === 'off') return [];
  const sub = (dim, value) => h('small', null, dim ? h('span', { class: 'dim' }, dim + ' ') : null, value);
  if (lane.kind === 'case') return [h('div', null, h('b', null, price(R.C[lane.row.i])), sub(null, 'close, USDT')),
    ...shown.map((k) => { const o = lane.row.out[k]; return h('div', null, h('b', { class: o.value < 0 ? 'neg' : '' }, o.status === 'observed' ? pct(o.value) : '—'), sub(null, o.status === 'observed' ? 'return' : o.status)); })];
  // A compared run keeps a share of its own detections, which differ between runs when a pattern value is compared.
  const n = lane.rows.length; const base = (lane.kind === 'run' ? lane.r : r).counts.T || 1;
  const centred = (frac) => { const d = (Math.max(-0.2, Math.min(0.2, frac - 0.5)) / 0.2) * 50; return h('div', { class: 'meter mid' }, h('i', { class: d < 0 ? 'below' : '', style: d >= 0 ? `left:50%;width:${d}%` : `left:${50 + d}%;width:${-d}%` })); };
  return [h('div', null, h('b', null, int(n)), sub(null, lane.kind === 'find' ? 'found' : lane.kind === 'alt' ? 'alone' : share(n, base) + ' kept'),
    h('div', { class: 'meter' }, h('i', { style: `width:${Math.min(100, (n / base) * 100)}%` }))),
  ...shown.map((k) => {
    const s = summarize(lane.rows, k); const thin = s.n > 0 && s.n < 30;
    return h('div', { title: s.n ? `${s.up} of ${s.n} observed closes were higher after ${r.columns[k].text}. Median return ${pct(s.median)}.${thin ? ' Fewer than 30 observations.' : ''}` : 'No observed outcome' },
      h('b', { class: thin ? 'thin' : '' }, s.up), thin ? sub('n', String(s.n)) : sub('med', pct(s.median)), s.n ? centred(s.frac) : null);
  })];
}

const nodes = new Map();
function nodeFor(id) {
  if (nodes.has(id)) return nodes.get(id);
  const n = { head: h('div', { class: 'lane-head' }), svgHost: h('div', { class: 'lane-svg' }), track: h('div', { class: 'lane-track cols' }), lane: null };
  n.el = h('div', { class: 'lane row3', tabindex: '0', 'data-lane': id }, n.head, n.svgHost, n.track);
  n.born = !document.hidden;
  n.el.addEventListener('click', (e) => { if (n.lane.kind !== 'off' && !e.target.closest('button, input, a')) selectLane(n.lane); });
  n.el.addEventListener('keydown', (e) => { if (e.key === 'Enter' && e.target === n.el && n.lane.kind !== 'off') selectLane(n.lane); });
  n.svgHost.addEventListener('mousemove', (e) => { if (n.lane.agg) hover(n.lane, n, e); });
  nodes.set(id, n);
  return n;
}

function renderCanvas() {
  const { r, H, hk, pbars, lanes } = ctx; const host = $('#lanes');
  const shown = r.columns.slice(0, 2).map((_, k) => k);
  $('#canvas').style.setProperty('--hz', Math.max(1, shown.length));
  layoutDims(ctx.dims);   // the lanes under the candles take their height first: the candles have what is left
  const avail = host.clientHeight; const slim = lanes.filter((l) => l.kind === 'off').length; const real = lanes.filter((l) => l.kind !== 'off');
  const pinnedH = real.length === 1 && state.rows !== 'cases' ? avail - slim * 33 - 1 : state.rows === 'cases' ? Math.round(Math.max(120, Math.min(176, avail * 0.24))) : Math.round(Math.max(132, Math.min(240, avail * 0.34)));
  const answerH = state.rows === 'cases' && real.length > 1 ? Math.min(150, 42 + 21 * state.model.wheres.filter((c) => !c.off).length) : 0;
  let caseLanes = [];
  if (state.rows === 'cases') {
    const per = Math.max(2, Math.floor((avail - pinnedH - answerH) / 68));
    const rows = ctx.answer.rows.slice(); const key = (row) => (row.out[0]?.status === 'observed' ? row.out[0].value : -Infinity);
    if (state.sort === 'best') rows.sort((a, b) => key(b) - key(a)); else if (state.sort === 'worst') rows.sort((a, b) => (key(a) === -Infinity ? 1 : key(b) === -Infinity ? -1 : key(a) - key(b)));
    const pages = Math.max(1, Math.ceil(rows.length / per)); state.page = Math.min(state.page, pages - 1);
    caseLanes = rows.slice(state.page * per, (state.page + 1) * per).map((row) => ({ id: 'case:' + row.i, kind: 'case', row, rows: [row], slots: [row.i], r: ctx.answer.r, title: isoUTC(row.t), agg: caseColumns(row.i, state.lead, H, state.unit) }));
    const order = { date: 'by date', best: 'highest return first', worst: 'lowest return first' };
    ctx.caseRows = rows; ctx.casePer = per;
    const sortBtn = h('button', { class: 'quiet', type: 'button', 'data-menu': '1', onclick: () => menu(sortBtn, { title: 'Order', value: state.sort, options: Object.entries(order).map(([value, text]) => ({ value, label: cap(text) })), onChange: (v) => { state.sort = v; state.page = 0; render(); } }) }, `${cap(order[state.sort])} ▾`);
    mount($('#pager'), h('span', { class: 'fig' }, `Closes ${int(state.page * per + 1)}–${int(Math.min(rows.length, (state.page + 1) * per))} of ${int(rows.length)}`),
      h('button', { class: 'quiet', type: 'button', title: 'Previous closes', 'aria-label': 'Previous closes', disabled: state.page === 0, onclick: () => { state.page--; render(); } }, '←'),
      h('button', { class: 'quiet', type: 'button', title: 'Next closes', 'aria-label': 'Next closes', disabled: state.page >= pages - 1, onclick: () => { state.page++; render(); } }, '→'), sortBtn);
  } else mount($('#pager'));
  const all = [...lanes, ...caseLanes]; ctx.all = all; ctx.caseLanes = caseLanes;
  if (!all.some((l) => l.id === state.lane && l.kind !== 'off')) state.lane = state.rows === 'cases' && state.slot !== null && caseLanes.some((l) => l.row.i === state.slot) ? 'case:' + state.slot : answerId(lanes);
  const sel = all.find((l) => l.id === state.lane); ctx.sel = sel;
  const others = all.filter((l) => l.kind !== 'off' && l.id !== 'find');
  const laneH = !others.length ? 0 : state.rows === 'cases' ? Math.max(64, Math.floor((avail - pinnedH - answerH) / Math.max(1, caseLanes.length)) - 1) : Math.max(90, Math.floor((avail - pinnedH - slim * 33) / others.length) - 1);
  const aggDomain = domainOf(all.filter((l) => l.agg && !l.agg.single).map((l) => l.agg), state.cells === 'density');

  const order = all.map((l) => l.id);
  for (const [id, n] of nodes) if (!order.includes(id)) { n.el.remove(); nodes.delete(id); }
  const heights = new Map();
  for (const lane of all) {
    const n = nodeFor(lane.id); n.lane = lane;
    const height = lane.kind === 'off' ? 32 : lane.id === 'find' ? pinnedH : lane.kind === 'answer' && answerH ? answerH : laneH; heights.set(lane.id, height);
    n.el.className = 'lane row3' + (n.born ? ' m-enter' : '') + (lane.kind === 'off' ? ' slim' : '') + (lane.id === 'find' ? ' pinned' : '') + (lane.id === state.lane ? ' sel' : '') + (lane.kind !== 'off' && height < 112 ? ' compact' : '');
    n.el.style.height = height + 'px';
    n.born = false;
    mount(n.head, laneHead(lane)); mount(n.track, laneTrack(lane, shown));
    if (lane.kind === 'off') n.svgHost.replaceChildren();
  }
  if ([...host.querySelectorAll(':scope > .lane')].map((e) => e.dataset.lane).join('|') !== order.join('|')) host.append(...order.map((id) => nodes.get(id).el));
  for (const lane of all) if (lane.agg) drawLane(nodes.get(lane.id).svgHost, { agg: lane.agg, domain: lane.kind === 'case' ? domainOf([lane.agg], true) : aggDomain, lead: state.lead, H, pbars, horizons: hk,
    mode: lane.kind === 'case' ? 'candle' : state.cells, unit: state.unit, height: heights.get(lane.id) - 1, scale: lane.id === 'find' });
  host.onmouseleave = () => { host.classList.remove('hot'); readDims(null); };
  host.classList.remove('hot');
  drawAxis($('#axis'), { lead: state.lead, H, pbars, horizons: hk });
  $('#rowlabel').textContent = { ledger: 'The question, line by line', split: 'The answer, split', compare: 'The answer, per compared value', cases: '' }[state.rows];
  mount($('#trackhead'), h('span', null, 'Closes'), shown.length ? shown.map((k) => h('span', { title: 'Share closing higher, and the median return' }, `${r.columns[k].text} up`)) : h('span', null, '—'));
  mount($('#collabel'), label(state.track === 'up' ? 'Closed above anchor' : 'Median range'), note(sel ? `${sel.title}, per bar` : ''));
  if (sel?.agg) drawColumnTrack($('#coltrack'), { agg: sel.agg, lead: state.lead, H, pbars, horizons: hk, measure: state.track });
  drawDims();
}

// ---------------------------------------------------------------- dimension lanes

// One lane per dimension on show, under the candles and on their columns, for the selected row: the median of its
// closes' candles in each column, or one close's own candles. Each lane names its dimension, carries its own switch,
// and reads out one column: the deciding close, or the column under the pointer.
const dimNodes = new Map(); const dimHeld = new WeakMap();
function layoutDims(keys) {
  if (!keys.length && !dimNodes.size) return;
  const canvas = $('#canvas');
  let host = $('#dims');
  if (!keys.length) {
    host.remove();
    canvas.classList.remove('with-dimensions');
    dimNodes.clear();
    return;
  }
  if (!host) {
    host = h('div', { id: 'dims' });
    canvas.insertBefore(host, canvas.querySelector('.band'));
    canvas.classList.add('with-dimensions');
  }
  for (const [key, n] of dimNodes) if (!keys.includes(key)) { n.el.remove(); dimNodes.delete(key); }
  for (const key of keys) {
    if (dimNodes.has(key)) continue;
    const d = DIM[key]; const n = { svgHost: h('div', { class: 'dim-svg' }), cursor: h('i', { class: 'dim-cursor', hidden: true }), read: h('div', { class: 'dim-read' }) };
    n.el = h('div', { class: 'dimlane row3', 'data-dim': key, role: 'group', 'aria-label': `${d.label} lane` },
      h('div', { class: 'dim-head' }, h('span', { class: 'name', title: cap(d.what) }, label(d.label), note(d.what)),
        quiet('Hide', () => { setLane(state.dims, ctx.used, key, false); render(); }, `Hide the ${d.label.toLowerCase()} lane`)),
      h('div', { class: 'dim-track' }, n.svgHost, n.cursor), n.read);
    n.svgHost.addEventListener('mousemove', (e) => readDims(columnAt(n.svgHost, e.clientX, state.lead, ctx.H, ctx.pbars)));
    n.svgHost.addEventListener('mouseleave', () => readDims(null));
    dimNodes.set(key, n);
  }
  if ([...host.children].map((e) => e.dataset.dim).join('|') !== keys.join('|')) host.append(...keys.map((key) => dimNodes.get(key).el));
}
function drawDims() {
  if (!ctx.dims.length) return;
  const { sel, H, hk, pbars } = ctx; const R = rec(); ctx.dimCols = new Map();
  if (!dimHeld.has(R)) dimHeld.set(R, new Map());
  const held = dimHeld.get(R);
  for (const key of ctx.dims) {
    const id = `${sel.kind === 'case' ? 'case:' + sel.row.i : sel.aggKey}|${state.lead}|${H}|${key}`;
    if (!held.has(id)) { if (held.size > 240) held.delete(held.keys().next().value); held.set(id, dimensionColumns(R, sel.slots, state.lead, H, key)); }
    ctx.dimCols.set(key, held.get(id));
    drawDimensionLane(dimNodes.get(key).svgHost, { agg: held.get(id), lead: state.lead, H, pbars, horizons: hk });
  }
  readDims(null);
}
/** Read every lane at one column: the deciding close when no column is pointed at. */
function readDims(k) {
  if (!ctx?.dimCols) return;
  const at = k ?? 0;
  for (const [key, agg] of ctx.dimCols) {
    const n = dimNodes.get(key); const col = agg.cols[at + state.lead]; const some = col && col.n;
    n.read.title = !some ? 'No recorded value in this column' : agg.single ? `${dimensionExact(key, col.v)} ${UNIT[key]}` : `Median of ${int(col.n)} candles. Middle half ${dimensionText(key, col.q1)} to ${dimensionText(key, col.q3)}.`;
    mount(n.read, h('b', { class: 'fig' }, some ? dimensionText(key, col.v) : '—'),
      h('small', null, agg.single ? null : h('span', { class: 'dim' }, 'med '), UNIT[key], h('span', { class: 'dim' }, ` · ${offsetLabel(at).toLowerCase()}`)));
    n.cursor.hidden = k === null;
    if (k !== null) n.cursor.style.left = geom(Math.max(120, Math.floor(n.svgHost.clientWidth)), state.lead, ctx.H, ctx.pbars).x(k) + 'px';
  }
}

// ---------------------------------------------------------------- a question these bars cannot answer

/**
 * The engine refused the question, as it does when a line reads a dimension and the bars carry no counters.
 * Nothing is drawn. Every line is listed and the engine's refusal stands where the line's drawing would be.
 * The ways out stay live: another window, another question, the catalogue, the formal text, or the line muted or removed.
 */
function renderRefused(text, res) {
  const m = state.model; const said = (errors) => [...new Set(errors.map((e) => e.message + (e.hint ? ` (${e.hint})` : '')))];
  const msg = said(res.errors).join(' · '); const status = $('#status');
  ctx = null; closePopover(); hideAdd(); addInput.disabled = true;
  status.textContent = msg; status.className = 'err';
  if (document.activeElement !== formal.el.querySelector('textarea')) formal.set(text, msg); else formal.message(msg);
  $('#left').hidden = !ui.left; $('#right').hidden = true; $('#drawer').hidden = ui.drawer !== 'query';
  renderBars();
  $('#axis').replaceChildren(); $('#coltrack').replaceChildren(); mount($('#pager')); mount($('#trackhead')); mount($('#collabel')); $('#rowlabel').textContent = '';
  layoutDims([]);
  // Each line is asked on its own, so the refusal is put on the lines it is about.
  const own = (body) => { const r = run(`${HEAD}\n${body}`); return r.ok ? [] : said(r.errors); };
  const rows = [
    ...m.find.items.map((c, k) => ({ id: 'x:f' + k, no: k ? '' : '01', role: k ? m.find.join : 'Find', c, why: own(`find ${clauseText(c)}`),
      acts: m.find.items.length > 1 ? [quiet('Remove', () => update((x) => { x.find.items.splice(k, 1); }), 'Remove this pattern')] : [quiet('Change pattern', () => togglePanel('left', true), 'Open the pattern catalogue')] })),
    ...m.wheres.map((c, i) => ({ id: 'x:w' + i, no: pad(i + 2), role: 'And', c, why: c.off ? [] : own(`find ${ANY_CLOSE}\nwhere ${clauseText(c)}`),
      acts: [c.off ? quiet('Unmute', () => update(() => { c.off = false; }), 'Apply this condition again') : quiet('Mute', () => update(() => { c.off = true; }), 'Keep the line but stop applying it'),
        quiet('Remove', () => update((x) => { x.wheres.splice(i, 1); }))] })),
    ...(m.split ? [{ id: 'x:g', no: '', role: 'Group by', c: m.split, why: own(`find ${ANY_CLOSE}\ngroup by ${splitText(m.split)}`),
      acts: [quiet('Remove', () => update(() => { state.rows = 'ledger'; }), 'Remove this grouping')] }] : []),
  ];
  if (!rows.some((row) => row.why.length)) rows[0].why = said(res.errors);   // the refusal is of the question as a whole
  const host = $('#lanes'); const order = rows.map((row) => row.id);
  for (const [id, n] of nodes) if (!order.includes(id)) { n.el.remove(); nodes.delete(id); }
  for (const row of rows) {
    const n = nodeFor(row.id); n.lane = { kind: 'off' }; n.born = false;
    n.el.className = 'lane row3 refused' + (row.c.off ? ' muted' : ''); n.el.style.height = ''; n.el.tabIndex = -1;
    mount(n.head, h('span', { class: 'no' }, row.no), h('span', { class: 'role' }, label(row.c.off ? 'Muted' : row.role), h('span', { class: 'acts' }, row.acts)),
      h('div', { class: 'texts' }, h('div', { class: 'text' + (row.c.type === 'drawing' ? ' shape-line' : '') }, h('span', null, row.id === 'x:g' ? splitText(row.c) : cap(phraseText(row.c))), row.c.type === 'drawing' ? codeLines(row.c) : null)));
    mount(n.svgHost, row.why.map((t) => h('p', { class: 'refusal' }, t))); mount(n.track);
  }
  host.append(...order.map((id) => nodes.get(id).el)); host.classList.remove('hot');
  renderLeft(); renderDrawer();
}

function hover(lane, n, e) {
  const { H, pbars } = ctx; const host = $('#lanes'); const cursor = $('#cursor'); const tip = $('#tip'); const R = rec();
  const box = n.svgHost.getBoundingClientRect(); const hostBox = host.getBoundingClientRect(); const g0 = geom(box.width, state.lead, H, pbars);
  const k = g0.at(e.clientX - box.left); const col = lane.agg.cols[k + state.lead]; const x = box.left - hostBox.left + g0.x(k);
  cursor.style.left = x + 'px'; cursor.style.height = host.scrollHeight + 'px';
  const lines = !col || !col.n ? ['no recorded bar']
    : lane.kind === 'case' ? [`${isoUTC(R.closeTime(lane.row.i + k))}`, `O ${price(R.O[lane.row.i + k])}  H ${price(R.H[lane.row.i + k])}`, `L ${price(R.L[lane.row.i + k])}  C ${price(R.C[lane.row.i + k])}`, `${unitText(col.c, state.unit)} from the anchor`]
      : k > 0 ? [`median close ${unitText(col.c, state.unit)}`, `${Math.round(col.up * 100)}% closed above the anchor`, `middle half ${unitText(col.q1, state.unit)} to ${unitText(col.q3, state.unit)}`, `n ${int(col.n)}`]
        : [`median close ${unitText(col.c, state.unit)}`, `median range ${pct(col.rng).replace('+', '')}`, `n ${int(col.n)}`];
  mount(tip, h('b', null, `${lane.title} · ${offsetLabel(k)}`), lines.map((t) => h('span', null, t)));
  readDims(k);
  tip.style.top = n.el.offsetTop + 8 + 'px';
  tip.style.left = (x + 14 + tip.offsetWidth > host.clientWidth - 8 ? x - 14 - tip.offsetWidth : x + 14) + 'px';
  host.classList.add('hot');
}

function selectLane(lane) {
  state.lane = lane.id; state.side = 'kept';
  state.slot = lane.kind === 'case' ? lane.row.i : null;
  if (ctx.res.results.length > 1 && lane.kind === 'run') state.candidate = lane.ci;
  render();
}

// ---------------------------------------------------------------- left: pattern catalogue

// A pattern's count and glyph are of one recording's bars: another window is another recording.
const catalogs = new WeakMap();
const catalogFor = () => { const R = rec(); if (!catalogs.has(R)) catalogs.set(R, new Map()); return catalogs.get(R); };
const LEVELS = [make('reclaim'), make('reclaim', { side: 'high' }), make('breakout'), make('relation'), make('wickrej')];
// Events read from a dimension, each under a short name of its own. They are listed only for bars that carry the dimensions.
const FLOWS = [['Net buying', make('taker')], ['Net selling', make('taker', { side: 'below' })], ['Rising volume', make('dimback')], ['New volume high', make('dimlevel')]];
function patternInfo(c) {
  const text = clauseText(c); const catalog = catalogFor();
  if (!catalog.has(text)) {
    const res = run(`${HEAD}\nfind ${text}`); const bars = c.type === 'pattern' ? PATTERNS.find((p) => p.id === c.args.p).bars : 1;
    catalog.set(text, res.ok ? { n: res.results[0].counts.T, bars, agg: aggregate('cat|' + text, res.results[0].rows.map((x) => x.i), bars - 1, 0, 'range') } : { n: 0, bars, agg: null });
  }
  return catalog.get(text);
}
function renderLeft() {
  const el = $('#left');
  if (!ui.left) return;
  const m = state.model; const R = rec(); const q = state.catalog.trim().toLowerCase(); const current = new Set(m.find.items.map(clauseText));
  const hadFocus = document.activeElement?.classList.contains('search'); const top = el.scrollTop;
  const items = [
    ...PATTERNS.map((p) => ({ c: make('pattern', { p: p.id }), name: p.name, sub: `${p.ja} · ${p.bars} ${p.bars === 1 ? 'bar' : 'bars'}`, hay: (p.name + ' ' + p.ja + ' ' + p.aliases.join(' ')).toLowerCase(), group: 'named' })),
    ...LEVELS.map((c) => ({ c, name: CLAUSES[c.type].title, sub: cap(phraseText(c)), hay: (phraseText(c) + ' ' + CLAUSES[c.type].title + ' ' + CLAUSES[c.type].keywords).toLowerCase(), group: 'level' })),
    ...FLOWS.filter(([, c]) => can(c)).map(([name, c]) => ({ c, name, sub: cap(phraseText(c)), hay: (name + ' ' + phraseText(c) + ' ' + CLAUSES[c.type].title + ' ' + CLAUSES[c.type].keywords).toLowerCase(), group: 'dimension' })),
  ].filter((x) => !q || x.hay.includes(q));
  if (state.catSort === 'count') for (const x of items) patternInfo(x.c);
  const info = (x) => catalogFor().get(clauseText(x.c)); const ready = items.every(info); const pending = [];
  const row = (x) => {
    const text = clauseText(x.c); const glyph = h('span'); const count = h('b'); const bar = h('u');
    const fill = () => { const i = patternInfo(x.c); count.textContent = int(i.n); bar.style.width = Math.min(100, (Math.sqrt(i.n / R.presentCount) / Math.sqrt(0.2)) * 100) + '%'; if (i.agg && i.n) drawGlyph(glyph, i.agg, i.bars); };
    if (info(x)) fill(); else pending.push(fill);
    return h('div', { class: 'pat' + (info(x) && !info(x).n ? ' none' : ''), role: 'button', tabindex: '0', 'aria-current': String(current.has(text)), title: info(x) ? `${int(info(x).n)} of ${int(R.presentCount)} recorded closes` : null,
      onclick: (e) => { if (e.target.closest('.plus')) return; update((y) => { y.find = { join: 'or', items: [clone(x.c)] }; state.lane = null; state.slot = null; state.preset = null; }); },
      onkeydown: (e) => { if (e.key === 'Enter' && e.target === e.currentTarget) e.currentTarget.click(); } },
    glyph, h('span', { class: 'name' }, x.name, h('small', null, x.sub)), h('span', { class: 'n' }, count, h('i', { class: 'freq' }, bar)),
    h('button', { class: 'plus', type: 'button', title: 'Add as another pattern', 'aria-label': `Add ${x.name} as another pattern`, onclick: () => update((y) => { if (!current.has(text)) y.find.items.push(clone(x.c)); state.rows = 'ledger'; state.preset = null; }) }, '+'));
  };
  const live = items.filter((x) => !ready || info(x).n > 0); const none = ready ? items.filter((x) => info(x).n === 0) : [];
  if (state.catSort === 'count') live.sort((a, b) => info(b).n - info(a).n);
  const sortBtn = quiet(state.catSort === 'count' ? 'Most frequent first' : 'In catalogue order', () => { state.catSort = state.catSort === 'count' ? 'family' : 'count'; renderLeft(); }, 'Change the order');
  const section = (title, list, right) => (list.length ? [h('div', { class: 'sec' }, label(title), right || null), list.map(row)] : null);
  const search = h('input', { class: 'search', type: 'text', placeholder: 'Search, in English or Japanese', value: state.catalog, 'aria-label': 'Search patterns', oninput: (e) => { state.catalog = e.target.value; renderLeft(); } });
  mount(el, search,
    state.catSort === 'count' ? section('On this tape', live, sortBtn)
      : [section('Named candles', live.filter((x) => x.group === 'named'), sortBtn), section('Level events', live.filter((x) => x.group === 'level'), live.some((x) => x.group === 'named') ? null : sortBtn),
        section('Dimension events', live.filter((x) => x.group === 'dimension'), live.some((x) => x.group !== 'dimension') ? null : sortBtn)],
    section('Not on this tape', none),
    !items.length ? h('p', { class: 'empty', style: 'padding:16px 18px' }, 'No pattern matches that search.') : null);
  el.scrollTop = top;
  if (hadFocus) { search.focus(); search.setSelectionRange(search.value.length, search.value.length); }
  const step = () => { for (let i = 0; i < 4 && pending.length; i++) pending.shift()(); if (pending.length) setTimeout(step, 0); else if (ui.left) renderLeft(); };
  if (pending.length) setTimeout(step, 0);
}

// ---------------------------------------------------------------- right: inspect

function factsAt(i, dimensions = false) {
  const R = rec(); const out = [];
  if (!R.present[i]) return out;
  const ev = (c, why) => { const res = run(`${HEAD}\nfind ${clauseText(c)}`); if (!res.ok) return null; const x = res.results[0]; return x.event.series.vals[i] === T ? { c, section: 'event', n: x.counts.T, why: why ?? x.event.series.why(i) } : null; };
  const cond = (c, section) => { const res = run(`${HEAD}\nfind ${ANY_CLOSE}\nwhere ${clauseText(c)}`); if (!res.ok) return null; const at = res.results[0].clauses[0].at(i); return at.v === T ? { c, section, n: res.results[0].survivors[0], why: at.why } : null; };
  const first = (list, fn, arg) => { for (const c of list) { const f = fn(c, arg); if (f) return f; } return null; };
  const push = (f) => { if (f) out.push(f); };
  if (dimensions) {
    // What the candle's dimensions say: the taker side, volume against its recent median and the candle before, and a new extreme.
    push(first(['above', 'below', 'equal'].map((side) => make('taker', { side })), ev));
    push(first(['3', '2.5', '2', '1.5', '1.25'].map((min) => make('dimx', { min })), cond) || first(['0.25', '0.5', '0.75'].map((max) => make('dimxmax', { max })), cond));
    push(ev(make('dimback')) || ev(make('dimback', { rel: 'below' })));
    for (const side of ['high', 'low']) push(first(['24h', '12h', '4h'].map((over) => make('dimlevel', { over, side })), ev));
    return out;
  }
  const groupAt = (expr) => run(`${HEAD}\nfind ${ANY_CLOSE}\ngroup by ${expr}`).results[0].group.at(i);
  for (const p of PATTERNS) push(ev(make('pattern', { p: p.id }), p.rule));
  for (const side of ['low', 'high']) push(first(['24h', '12h', '4h'].map((over) => make('reclaim', { side, over })), ev) || first(['24h', '12h', '4h'].map((over) => make('reclaim', { side, over, within: '3' })), ev));
  push(first(['48h', '24h', '12h', '4h'].map((over) => make('breakout', { over })), ev));
  push(ev(make('relation'))); push(ev(make('relation', { rel: 'below', b: 'low' })));
  const range = R.H[i] - R.L[i];
  if (range > 0) {
    const top = Math.max(R.O[i], R.C[i]); const bot = Math.min(R.O[i], R.C[i]);
    for (const [part, size] of [['lower_wick', bot - R.L[i]], ['upper_wick', R.H[i] - top], ['body', top - bot]]) {
      const sh = (size / range) * 100;
      if (sh >= 30) push(cond(make('share', { part, min: Math.min(90, Math.floor(sh / 10) * 10) + '%' }), 'anatomy'));
      if (sh <= 20) push(cond(make('sharemax', { part, max: Math.max(10, Math.ceil(sh / 10) * 10) + '%' }), 'anatomy'));
    }
  }
  push(first(['3', '2.5', '2', '1.5', '1.25'].map((min) => make('rangex', { min })), cond, 'anatomy'));
  const day = groupAt('weekday(nyse_regular)'); if (day.key !== 'unknown') push(cond(make('weekday', { day: day.key }), 'context'));
  push(first(['30m', '1h', '2h'].map((last) => make('tail', { last })), cond, 'context'));
  for (const frame of ['4h', '1d']) { const g = groupAt(`completed_trend(frame: ${frame})`); if (g.key === 'up' || g.key === 'down') push(cond(make('trend', { frame, dir: g.key }), 'context')); }
  push(first(['72h', '48h', '24h', '12h'].map((d) => make('quiet', { for: d })), cond, 'context'));
  for (const side of ['high', 'low']) push(first(['24h', '4h'].map((over) => make('near', { side, over })), cond, 'context'));
  return out;
}

function definitionOf(c) {
  if (c.type === 'drawing') {
    const n = drawingBars(c); const rel = c.args.packet ? relationsOf(c.args.packet) : []; const held = drawingHeld(c);
    const parts = held ? [] : g1Parts(c.args.g1); const dims = held ? '' : drawingDimensions(c);
    const same = `every endpoint in the drawn order, with the same ties${c.args.g1[3] === 'o' ? ' and the same directions' : ''}`;
    return { title: `${packetOf(c) ? 'Drawn shape' : 'G1 code'} · ${n} ${n === 1 ? 'bar' : 'bars'}`,
      summary: (held ? `${rel.length === 1 ? 'One relation' : rel.length + ' relations'} held on ${n} fixed candles ending at the close. Only which side each level lies on is kept, not the drawn distance.`
        : n === 1 ? `The last candle has ${same}.`
          : drawingRecorded(c) ? `The last ${n} candles, with their opens as recorded, have ${same}. ${packetOf(c) ? 'This shape ties each later open to the close before it, so the recorded open must equal that close to the cent.' : 'In this code a later open lies away from the close before it, or no directions are kept, so it is not a chain and cannot be drawn as one.'}`
            : `The last ${n} candles, read as a chain, have ${same}: the first as recorded, each later one opening at the close before it.${packetOf(c) ? '' : ' This code is not a chain, so no window read this way can match it.'}`)
        + (dims ? ` ${cap(dims)} ${parts.length > 1 ? 'stand' : 'stands'} in the code’s order from candle to candle, ties included${parts.some((p) => p.reference !== null) ? ', each signed one on its side of zero' : ''}. A candle without the value leaves the window unknown.` : ''),
      formula: [...(held ? rel.map(cap) : [g1Price(c.args.g1), ...parts.map((p) => `${p.text} · ${DIM[p.key].label}: ${p.order}`)]), ...(c.args.packet ? ['Composer’s skeleton, stretch, next-bar term, timeframes and picks are not part of this question.', OWN_COUNT] : [])] };
  }
  if (c.type === 'pattern') { const p = PATTERNS.find((x) => x.id === c.args.p); return { title: `${p.name} · ${p.ja}`, summary: p.rule, formula: [] }; }
  const d = CLAUSES[c.type].def && definition(CLAUSES[c.type].def);
  return d ? { title: d.title, summary: d.summary, formula: (d.formula || []).filter((f) => f !== d.summary) } : null;
}

/** The closes the inspector steps through: the selected row's, in time order. */
const inspectRows = () => (ctx.sel.kind === 'case' ? ctx.answer.rows : state.side === 'removed' && ctx.sel.removed ? ctx.sel.removed : ctx.sel.rows);
function stepClose(d) {
  const rows = inspectRows(); const at = rows.findIndex((x) => x.i === state.slot); const next = rows[at < 0 ? (d > 0 ? 0 : rows.length - 1) : at + d];
  if (!next) return;
  state.slot = next.i; state.caseFollow = true;
  if (state.rows === 'cases' && ctx.caseRows) { state.lane = 'case:' + next.i; state.page = Math.floor(Math.max(0, ctx.caseRows.findIndex((x) => x.i === next.i)) / ctx.casePer); }
  render();
}

function renderRight() {
  const el = $('#right');
  if (!ui.right) return;
  const { r, sel } = ctx; const m = state.model; const R = rec(); const top = el.scrollTop;
  if (state.slot !== null) {
    const i = state.slot; const ar = ctx.answer.r; const row = ar.rowsBySlot.get(i) || null; const drawing = h('div', { class: 'dist' });
    const inQuery = new Map([...m.find.items.map((c, k) => [clauseText(c), 'f' + k]), ...m.wheres.map((c, k) => [clauseText(c), 'w' + k])]);
    const facts = factsAt(i); const rows = inspectRows(); const at = rows.findIndex((x) => x.i === i); const applied = m.wheres.filter((c) => !c.off);
    const fact = (f) => {
      const text = clauseText(f.c); const on = inQuery.has(text); const path = inQuery.get(text);
      const left = on ? null : (() => { const x = clone(m); x.wheres.push(f.c); return count(bodyText(x)); })();
      return h('button', { class: 'fact', type: 'button', role: 'checkbox', 'aria-checked': String(on), title: on ? (path[0] === 'w' ? 'Remove this condition' : 'This is the pattern') : 'Add as a condition',
        onclick: () => { if (on && path[0] === 'w') update((x) => { x.wheres.splice(+path.slice(1), 1); }); else if (!on) update((x) => { x.wheres.push(clone(f.c)); if (state.rows !== 'cases') state.rows = 'ledger'; state.lane = null; }); } },
      h('span', { class: 'box', 'aria-hidden': 'true' }), h('span', null, cap(phraseText(f.c))), h('span', { class: 'n' }, on ? `${int(f.n)} on tape` : `leaves ${int(left)}`), h('small', null, f.why));
    };
    const group = (title, key) => { const list = facts.filter((f) => f.section === key); return list.length ? [label(title, 'sub-label'), list.map(fact)] : null; };
    const dimensionFacts = counters() ? h('details', null, h('summary', null, 'Dimension facts')) : null;
    if (dimensionFacts) dimensionFacts.addEventListener('toggle', () => {
      if (!dimensionFacts.isConnected || !dimensionFacts.open || dimensionFacts.childElementCount > 1) return;
      const values = h('dl', { class: 'kv2' }, DIMENSIONS.map(d => [
        h('dt', { title: cap(d.what) }, d.label),
        h('dd', null, dimensionExact(d.key, R.dimension(d.key)[i]), h('span', { class: 'base' }, ` ${UNIT[d.key]}`)),
      ]));
      dimensionFacts.append(values, ...factsAt(i, true).map(fact));
    });
    const mark = (v) => h('span', { class: 'v' + (v === T ? '' : ' f') }, SYM[v]);
    const nav = (text, d, title) => h('button', { class: 'quiet step', type: 'button', title, 'aria-label': title, disabled: at < 0 ? !rows.length : !rows[at + d], onclick: () => stepClose(d) }, text);
    mount(el,
      h('div', { class: 'sec close-head' }, h('span', { class: 'fig when' }, isoUTC(R.closeTime(i))),
        h('span', { class: 'nav' }, nav('←', -1, 'Previous close in this row ( , )'), nav('→', 1, 'Next close in this row ( . )'),
          quiet('Back to the row', () => { state.slot = null; if (state.lane?.startsWith('case:')) state.lane = null; render(); }, 'Esc'))),
      h('section', { class: 'block' }, h('div', { class: 'close-sub' }, note(`New York: ${nyText(R.closeTime(i))}`),
        note(at >= 0 ? `${int(at + 1)} of ${int(rows.length)}${state.side === 'removed' && ctx.sel.removed ? ' removed' : ''}` : 'not in this row', 'fig')), drawing,
        h('div', { class: 'carry' }, candlesLink(i, 'link'))),
      h('section', { class: 'block' }, h('div', { class: 'sec' }, label('Why this close')),
        row ? h('ul', { class: 'why' },
          h('li', null, mark(row.detector), h('span', null, cap(m.find.items.length === 1 ? phraseText(m.find.items[0]) : ar.event.text)), h('small', null, ar.event.series.why(i))),
          row.results.map((x, k) => h('li', null, mark(x.v), h('span', null, cap(applied[k] ? phraseText(applied[k]) : ar.clauses[k].text)), h('small', null, x.why))),
          row.out.map((o, k) => h('li', null, h('span', { class: 'v' }, '→'), h('span', null, `After ${ar.columns[k].text}: `, h('b', { class: 'fig' }, o.status === 'observed' ? pct(o.value) : o.status)), h('small', null, o.why))))
          : h('p', { class: 'empty' }, 'The pattern does not occur at this close. ' + r.event.series.why(i))),
      h('section', { class: 'block' }, h('div', { class: 'sec' }, label('Facts at this close'), note('Tick to add')), group('What happened', 'event'), group('Anatomy', 'anatomy'), group('Context', 'context'), dimensionFacts));
    candleAnatomy(drawing, { rec: R, i, height: 176 });
    el.scrollTop = top;
    return;
  }
  const lane = sel; const res = lane.r; const rows = lane.rows;
  const base = m.horizons.length ? run(`${HEAD}\nfind ${ANY_CLOSE}\nmeasure close_return(after: [${m.horizons.join(', ')}])`).results[0] : null;
  const defs = (lane.kind === 'where' || lane.kind === 'alt' ? [lane.c] : lane.kind === 'find' ? m.find.items : m.wheres.filter((c) => !c.off)).map(definitionOf).filter(Boolean);
  const plots = []; const fig = (text, cls = '') => h('span', { class: 'fig ' + cls }, text);
  mount(el,
    h('div', { class: 'sec' }, label(lane.title, 't1'), rows.length ? quiet(`${int(rows.length)} ${rows.length === 1 ? 'close' : 'closes'} →`, () => stepClose(1), 'Inspect them one by one') : note('no closes')),
    res.columns.length ? res.columns.map((col, k) => {
      const s = summarize(rows, k); const b = base.summary[k]; const bf = b.observed ? b.positive / b.observed : null; const ci = wilson(s.k, s.n);
      const rail = h('div', { class: 'rail' }); const dist = h('div', { class: 'dist' });
      if (s.n) plots.push(() => { rateRail(rail, { p: s.frac, lo: ci[0], hi: ci[1], base: bf }); distPlot(dist, { values: s.values, median: s.median, baseline: b.median }); });
      const delta = s.n && bf !== null ? Math.round((s.frac - bf) * 100) : null;
      return h('section', { class: 'block' }, h('div', { class: 'sec' }, label(`After ${col.text}`), note(`n ${int(s.n)}`, 'fig')),
        h('div', { class: 'big' }, h('b', null, s.up), note('closed higher'), delta !== null ? h('span', { class: 'vs' }, `${delta > 0 ? '+' : delta < 0 ? '−' : '±'}${Math.abs(delta)} pts vs all closes`) : null),
        s.n ? [rail, h('p', { class: 'ci', title: 'Wilson score interval. It treats the closes as independent observations, which overlapping horizons are not.' },
          `95% interval ${pc(ci[0])} to ${pc(ci[1])}. All closes: ${pc(bf)}, ${bf >= ci[0] && bf <= ci[1] ? 'inside' : 'outside'} it.${s.n < 30 ? ' Thin sample.' : ''}`),
        dist, h('div', { class: 'cmp' }, h('span'), label('This row'), label('All closes'),
          h('span', null, 'Median'), fig(pct(s.median)), fig(pct(b.median), 'base'), h('span', null, 'Mean'), fig(pct(s.mean)), fig(pct(b.mean), 'base'))]
          : h('p', { class: 'empty' }, 'No observed outcome at this horizon.'));
    }) : h('section', { class: 'block' }, h('p', { class: 'empty' }, 'Choose a horizon under Measure to see what followed.')),
    defs.map((d) => h('section', { class: 'block' }, h('div', { class: 'sec' }, label('Definition'), note(d.title)), h('p', { class: 'def' }, d.summary),
      d.formula.length ? h('details', null, h('summary', null, 'Formula and edge cases'), h('ul', { class: 'formula' }, d.formula.map((f) => h('li', null, f)))) : null)));
  for (const d of plots) d();
  el.scrollTop = top;
}

// ---------------------------------------------------------------- drawer: cases, tape, query, limen

const formal = plate({ label: 'Filang', onEdit: (text) => {
  const f = fromText(text);
  if (!f.model) return formal.message(f.error.message);
  for (const c of state.model.find.items) if (c.type === 'drawing' && c.args.packet) attach(f.model, c.args.packet);
  const check = run(toText(f.model));
  if (!check.ok && !refusal(check)) return formal.message(check.errors.map((e) => e.message + (e.hint ? ` (${e.hint})` : '')).join(' · '));
  state.model = f.model; state.preset = null; state.lane = null; state.slot = null; state.notice = '';
  if (f.model.split) { state.rows = 'split'; state.splitBy = f.model.split.type; } else if (state.rows === 'split') state.rows = 'ledger';
  render();
} });

/** Recorded closes of a row: sortable, with each return drawn as a small bar, and the reason when the row removed them. */
function casesTable(host, lane, rows, removed) {
  const R = rec(); const res = lane.r; const cols = res.columns; const sort = state.caseSort;
  const get = sort.key === 't' ? (row) => row.t : sort.key === 'c' ? (row) => R.C[row.i] : (row) => (row.out[sort.key]?.status === 'observed' ? row.out[sort.key].value : null);
  const sorted = rows.slice().sort((a, b) => { const x = get(a); const y = get(b); return x === null ? 1 : y === null ? -1 : (x - y) * sort.dir; });
  if (!sorted.length) { mount(host, h('p', { class: 'empty', style: 'padding:18px 0' }, removed ? 'This line removes nothing.' : 'No recorded close in this row.')); return; }
  const size = Math.max(3, Math.floor((host.clientHeight - 74) / 31)); const pages = Math.max(1, Math.ceil(sorted.length / size));
  if (state.caseFollow && state.slot !== null) { const at = sorted.findIndex((x) => x.i === state.slot); if (at >= 0) state.casePage = Math.floor(at / size); }
  state.caseFollow = false; state.casePage = Math.min(state.casePage, pages - 1);
  const scale = cols.map((_, k) => { const v = sorted.map((x) => x.out[k]).filter((o) => o.status === 'observed').map((o) => Math.abs(o.value)).sort((a, b) => a - b); return v.length ? v[Math.floor((v.length - 1) * 0.95)] || 1e-9 : 1; });
  const th = (key, text, cls = '') => h('th', { class: cls, 'aria-sort': sort.key === key ? (sort.dir > 0 ? 'ascending' : 'descending') : 'none' },
    h('button', { type: 'button', class: 'sort', title: 'Sort by this column', onclick: () => { state.caseSort = { key, dir: sort.key === key ? -sort.dir : key === 't' ? 1 : -1 }; state.casePage = 0; render(); } }, text, h('i', null, sort.key === key ? (sort.dir > 0 ? '▲' : '▼') : '')));
  const pick = (row) => { state.slot = row.i; state.caseFollow = true; if (!ui.right) ui.right = true; render(); $('#drawer').querySelector(`[data-slot-i="${row.i}"]`)?.focus(); };
  const body = sorted.slice(state.casePage * size, (state.casePage + 1) * size).map((row) => h('tr', { tabindex: '0', 'aria-selected': String(row.i === state.slot), 'data-slot-i': row.i,
    onclick: () => pick(row),
    onkeydown: (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(row); }
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); e.stopPropagation(); const next = sorted[sorted.indexOf(row) + (e.key === 'ArrowDown' ? 1 : -1)]; if (next) pick(next); }
    } },
  h('td', { class: 'fig' }, isoUTC(row.t)), removed ? null : h('td', { class: 'fig muted' }, nyText(row.t)), h('td', { class: 'fig num' }, price(R.C[row.i])),
  removed ? h('td', { class: 'reason', title: row.results[lane.k].why }, `${SYM[row.results[lane.k].v]} ${row.results[lane.k].why}`) : null,
  cols.map((_, k) => { const o = row.out[k]; if (o.status !== 'observed') return h('td', { class: 'fig num muted', title: o.why }, o.status);
    const d = (Math.max(-1, Math.min(1, o.value / scale[k])) * 50);
    return h('td', { class: 'num', title: o.why }, h('span', { class: 'mini' }, h('i', { class: d < 0 ? 'below' : '', style: d >= 0 ? `left:50%;width:${d}%` : `left:${50 + d}%;width:${-d}%` })), h('span', { class: 'fig' + (o.value < 0 ? ' neg' : '') }, pct(o.value))); })));
  mount(host, h('table', { class: 'ruled' },
    h('thead', null, h('tr', null, th('t', 'Close, UTC'), removed ? null : h('th', null, 'New York'), th('c', 'Close, USDT', 'num'), removed ? h('th', null, 'Why it was removed') : null, cols.map((c, k) => th(k, `After ${c.text}`, 'num')))),
    h('tbody', null, body)),
  h('div', { class: 'pager' }, h('span', { class: 'fig' }, `Closes ${int(state.casePage * size + 1)}–${int(Math.min(sorted.length, (state.casePage + 1) * size))} of ${int(sorted.length)}`),
    h('button', { class: 'quiet', type: 'button', title: 'Previous page', 'aria-label': 'Previous page', disabled: state.casePage === 0, onclick: () => { state.casePage--; render(); } }, '←'),
    h('button', { class: 'quiet', type: 'button', title: 'Next page', 'aria-label': 'Next page', disabled: state.casePage >= pages - 1, onclick: () => { state.casePage++; render(); } }, '→')));
}

function renderDrawer() {
  const el = $('#drawer');
  if (!ui.drawer || (!ctx && ui.drawer !== 'query')) { delete el.dataset.tab; return; }   // a refused question has only its text to show
  // The query editor must survive a redraw: rebuilding the drawer would detach the textarea being typed in,
  // drop its focus after every valid keystroke, and send the next keys to the global shortcuts.
  if (ui.drawer === 'query' && el.dataset.tab === 'query' && el.contains(formal.el)) return;
  const was = el.dataset.tab; el.dataset.tab = ui.drawer;
  const { sel, res } = ctx || {}; const R = rec(); const body = h('div', { class: 'body' });
  const head = (title, text, ...seg) => h('header', null, label(title, 'title'), note(text), h('span', { class: 'seg' }, seg), quiet('Close', () => togglePanel(ui.drawer)));
  if (ui.drawer === 'cases') {
    const lane = sel.kind === 'case' ? ctx.answer : sel; const hasRemoved = lane.kind === 'where';
    if (!hasRemoved) state.side = 'kept';
    const removed = state.side === 'removed'; const rows = removed ? lane.removed : lane.rows;
    const key = `${ctx.text}#${lane.id}#${state.side}`; if (state.caseKey !== key) { state.caseKey = key; state.casePage = 0; state.caseFollow = true; }
    const seg = (id, text) => h('button', { type: 'button', 'aria-pressed': String(state.side === id), onclick: () => { state.side = id; render(); } }, text);
    mount(el, head('Cases', `${lane.title} · ${removed ? 'closes this line removed' : 'recorded closes'} · click a column to sort`,
      hasRemoved ? [seg('kept', `Kept ${int(lane.rows.length)}`), seg('removed', `Removed ${int(lane.removed.length)}`)] : null), body);
    casesTable(body, lane, rows, removed);
  } else if (ui.drawer === 'tape') {
    const lane = sel.kind === 'case' ? ctx.answer : sel; const i = state.slot ?? lane.slots[0] ?? 0; const from = Math.max(0, i - 70); const to = Math.min(R.n - 1, i + 50);
    // The overview holds the pointer while it is dragged, and each seek redraws the bench: an open tape keeps its
    // hosts and only its header is replaced, so the captured element stays in the page for the rest of the drag.
    const header = head('Tape', `${lane.title} · ${int(lane.slots.length)} closes marked · click a candle to inspect that close`);
    let tape = was === 'tape' ? el.querySelector(':scope > .body > .tape') : null;
    if (tape) el.firstElementChild.replaceWith(header); else { tape = h('div', { class: 'tape' }, h('div'), h('div')); mount(el, header, body); mount(body, tape); }
    const [over, chart] = tape.children;
    const ev = ctx.answer.r.event.series.evidence?.(i);
    tapeOverview(over, { rec: R, marks: lane.slots, window: [from, to], selected: i, height: 58, onSeek: (slot) => { state.slot = slot; render(); } });
    candleChart(chart, { rec: R, from, to, anchor: i, marks: new Set(lane.slots), label: state.slot === null ? 'FIRST CLOSE' : 'INSPECTED', height: Math.max(120, tape.parentElement.clientHeight - 80),
      levels: ev ? [{ price: ev.level, label: 'FROZEN LEVEL', from: R.slotClosingAt(ev.breach) ?? i }] : [], onPick: (slot) => { state.slot = slot; if (!ui.right) ui.right = true; render(); } });
  } else if (ui.drawer === 'query') {
    const copy = h('button', { type: 'button', onclick: async () => { try { await navigator.clipboard.writeText(toText(state.model)); copy.textContent = 'Copied'; } catch { copy.textContent = 'Select the text to copy'; } setTimeout(() => { copy.textContent = 'Copy'; }, 1400); } }, 'Copy');
    mount(el, head('Query', 'The rows write this text. Editing it rewrites the rows as soon as it checks.', copy), body);
    mount(body, formal.el);
  } else {
    const man = res.manifest;
    mount(el, head('Limen', 'Hand-off as a rule-based Single-File Decoder. Not connected in this prototype.',
      h('button', { type: 'button', disabled: true, title: 'The Limen connection is not wired in this prototype' }, 'Send to Limen')), body);
    mount(body, h('div', { class: 'handoff' },
      h('div', null, label('Pinned by the engine for this run'), h('dl', null,
        h('dt', null, 'query'), h('dd', null, man.query),
        h('dt', null, 'runs'), h('dd', null, man.candidates.map((c) => c.label).join(' · ')),
        h('dt', null, 'source'), h('dd', null, `${man.pins.source.instrument} ${man.pins.source.bar} · ${int(man.pins.source.rows)} rows · sha256 ${man.pins.source.csv_sha256.slice(0, 16)}… ${man.pins.source.verified ? 'verified' : 'unverified'}`),
        h('dt', null, 'calendar'), h('dd', null, man.pins.calendars.map((c) => `${c.id} · sha256 ${c.sha256.slice(0, 16)}…`).join(' · ')),
        h('dt', null, 'definitions'), h('dd', null, man.pins.definitions.join(' · ')),
        h('dt', null, 'engine'), h('dd', null, `${man.engine.name} ${man.engine.version} · ${man.arithmetic}`))),
      h('div', null, label('Still to declare before it is a strategy'), h('ul', null,
        ['Entry: the first eligible open strictly after the deciding close.', 'Exit: stop, target and expiry, with a declared intrabar policy.', 'Costs: fees and slippage on its own ledger.', 'Holdout: one chronological holdout, sealed before the search.',
          'This bench measures observed close-to-close returns. It is a study, not a backtest.'].map((t) => h('li', null, t))))));
  }
}

// ---------------------------------------------------------------- add a condition

const FILLER = new Set(['and', 'the', 'is', 'a', 'an', 'where', 'of', 'in', 'on', 'at', 'it', 'with', 'by', 'to', 'than', 'least', 'most']);
function pool() {
  const out = [];
  for (const part of ['lower_wick', 'upper_wick', 'body']) out.push(make('share', { part }), make('sharemax', { part }));
  out.push(make('rangex'), make('tail'), make('quiet'));
  for (const dim of ['volume', 'trades', 'size']) out.push(make('dimx', { dim }), make('dimxmax', { dim }));
  for (const by of ['delta', 'imbalance']) for (const side of ['above', 'below', 'equal']) out.push(make('taker', { side, by }));
  for (const d of DIMENSIONS) out.push(make('dimback', { dim: d.key }), make('dimlevel', { dim: d.key }), make('dimlevel', { dim: d.key, side: 'low' }));
  for (const dir of ['up', 'down']) out.push(make('trend', { dir }));
  for (const side of ['high', 'low']) out.push(make('near', { side }), make('reclaim', { side }));
  out.push(make('breakout'), make('relation'), make('wickrej'));
  for (const day of ['mon', 'tue', 'wed', 'thu', 'fri', 'closed']) out.push(make('weekday', { day }));
  for (const p of PATTERNS) out.push(make('pattern', { p: p.id }));
  return out.filter(can);   // bars without the cube's counters are offered no dimension
}
function suggestions(q) {
  const m = state.model; const tokens = q.toLowerCase().split(/[\s,]+/).filter(Boolean); const out = [];
  const words = tokens.filter((t) => !/^\d/.test(t) && !FILLER.has(t) && !['or', 'not', 'no'].includes(t));
  const pctTok = tokens.find((t) => /^\d+(\.\d+)?%$/.test(t)); const durTok = tokens.find((t) => /^\d+[mhd]$/.test(t)); const numTok = tokens.find((t) => /^\d+(\.\d+)?$/.test(t));
  const asOr = tokens[0] === 'or'; const negate = tokens.includes('not') || tokens.includes('no');
  const has = (hay) => { const toks = hay.toLowerCase().split(/[^a-z0-9%.]+/); return words.every((w) => (/^[a-z0-9%.]+$/.test(w) ? toks.some((t) => t.startsWith(w)) : hay.includes(w))); };
  if (durTok && has('measure return after horizon')) out.push({ tag: 'Measure', label: `the return after ${durTok}`, apply: (x) => { if (!x.horizons.includes(durTok)) x.horizons.push(durTok); } });
  const wantsSplit = words.some((w) => 'split'.startsWith(w) || 'group'.startsWith(w));
  if (wantsSplit && has('split by group 4h trend')) out.push({ tag: 'Rows', label: 'split the answer by 4h trend', mode: () => { state.rows = 'split'; state.splitBy = 'trend'; state.model.split = make('trend'); } });
  if (wantsSplit && has('split by group session day weekday')) out.push({ tag: 'Rows', label: 'split the answer by session day', mode: () => { state.rows = 'split'; state.splitBy = 'weekday'; } });
  const present = new Set([...m.find.items, ...m.wheres].map(clauseText));
  const offers = OFFERS.filter(can); const room = 15 + (tokens.length ? 0 : offers.filter((c) => CLAUSES[c.type].needs).length);   // the dimension offers are added to the list, not put in place of others
  for (const base of tokens.length ? pool() : offers) {
    const def = CLAUSES[base.type];
    // Clauses that come in variants (a day, a direction, a dimension) match on their own wording, so "friday" finds Friday only.
    const hay = phraseText(base) + ' ' + (base.type === 'pattern' ? PATTERNS.find((p) => p.id === base.args.p).ja : base.type === 'weekday' ? 'weekday calendar' : base.type === 'trend' ? 'trend higher timeframe direction' : def.needs ? def.keywords : def.title + ' ' + def.keywords);
    if (tokens.length && (!words.length || !has(hay))) continue;
    const c = clone(base);
    for (const sl of def.slots) { if (sl.kind === 'pct' && pctTok) c.args[sl.key] = pctTok; else if (sl.kind === 'dur' && durTok) c.args[sl.key] = durTok; else if (sl.kind === 'num' && numTok) c.args[sl.key] = numTok; }
    if (negate) c.not = true;
    if (present.has(clauseText(c)) || (asOr && def.role !== 'event')) continue;
    out.push(asOr ? { tag: 'Or', label: phraseText(c), apply: (x) => { x.find.join = 'or'; x.find.items.push(c); } } : { tag: 'And', label: phraseText(c), defer: !tokens.length && !!def.needs, apply: (x) => { x.wheres.push(c); } });
    if (out.length > room) break;
  }
  for (const s of out) if (s.apply) {
    const x = clone(m); s.apply(x); const body = bodyText(x);
    if (s.defer) s.readCount = () => count(body); else s.n = count(body);
  }
  return out.filter((s) => s.mode || s.n !== null);
}
const addInput = $('#add'); let addBox = null; let addList = []; let addPick = 0;
function showAdd() {
  addList = suggestions(addInput.value); addPick = Math.min(addPick, Math.max(0, addList.length - 1));
  if (!addBox) { addBox = h('div', { class: 'pop', role: 'listbox', style: 'max-height:356px' }); document.body.append(addBox); }
  mount(addBox, h('header', null, label(addInput.value.trim() ? 'Matches' : 'Conditions to add'), label('Closes left')),
    h('ul', null, addList.length ? addList.map((s, i) => h('li', null, h('button', { type: 'button', class: i === addPick ? 'active' : '', onmousedown: (e) => e.preventDefault(), onclick: () => applyAdd(s) },
      h('span', null, label(s.tag, 'tag'), cap(s.label)), h('span', { class: 'fig', 'data-count': s.defer ? i : null }, s.mode ? '' : s.defer ? '…' : int(s.n))))) : h('li', { class: 'none' }, 'Nothing matches. Try wick, range, friday, session, trend, quiet, level, or a candle name.')),
    h('footer', null, 'Type to search. Add numbers to set values: wick 60%, quiet 48h. Begin with “or” for another pattern.'));
  const list = addList;
  if (list.some(s => s.readCount)) requestAnimationFrame(() => setTimeout(() => {
    if (!addBox || addList !== list) return;
    for (const cell of addBox.querySelectorAll('[data-count]')) {
      const s = list[Number(cell.dataset.count)];
      const n = s.readCount();
      cell.textContent = n === null ? '—' : int(n);
    }
  }, 0));
  const r = addInput.closest('.cell').getBoundingClientRect();
  addBox.style.width = Math.max(440, r.width) + 'px'; addBox.style.maxWidth = '560px'; addBox.style.left = r.left + 'px'; addBox.style.top = Math.max(8, r.top - addBox.offsetHeight - 1) + 'px';
}
function hideAdd() { if (addBox) { addBox.remove(); addBox = null; } }
function applyAdd(s) {
  addInput.value = ''; addPick = 0; hideAdd();
  if (s.mode) { s.mode(); state.lane = null; render(); } else { state.lane = null; state.slot = null; state.preset = null; if (state.rows !== 'ledger' && s.tag !== 'Measure') state.rows = 'ledger'; update(s.apply); }
  addInput.focus(); showAdd();
}
addInput.addEventListener('focus', showAdd);
addInput.addEventListener('input', () => { addPick = 0; showAdd(); });
addInput.addEventListener('blur', hideAdd);
addInput.addEventListener('keydown', (e) => {
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); if (addList.length) { addPick = (addPick + (e.key === 'ArrowDown' ? 1 : -1) + addList.length) % addList.length; showAdd(); addBox.querySelector('.active')?.scrollIntoView({ block: 'nearest' }); } }
  if (e.key === 'Enter' && addList[addPick]) { e.preventDefault(); applyAdd(addList[addPick]); }
  if (e.key === 'Escape') { addInput.value = ''; addInput.blur(); }
});

// ---------------------------------------------------------------- panels, keys, start

function togglePanel(p, force) {
  if (p === 'left' || p === 'right') ui[p] = force ?? !ui[p]; else ui.drawer = ui.drawer === p ? null : p;
  persist(); render();
  // Entrance motion plays only on a deliberate toggle, and never while the page is in the background.
  const el = p === 'left' || p === 'right' ? $('#' + p) : $('#drawer');
  if (!el.hidden && !document.hidden) { el.classList.remove('enter'); void el.offsetWidth; el.classList.add('enter'); el.addEventListener('animationend', () => el.classList.remove('enter'), { once: true }); }
}
for (const b of document.querySelectorAll('.toggles button')) b.addEventListener('click', () => togglePanel(b.dataset.panel));
document.addEventListener('keydown', (e) => {
  if (e.metaKey || e.ctrlKey || e.altKey || /INPUT|TEXTAREA/.test(document.activeElement.tagName)) return;
  const map = { p: 'left', i: 'right', c: 'cases', t: 'tape', q: 'query', l: 'limen' };
  if (map[e.key] && (ctx || e.key === 'p' || e.key === 'q')) { e.preventDefault(); togglePanel(map[e.key]); }
  if (e.key === '/') { e.preventDefault(); addInput.focus(); }
  if ((e.key === ',' || e.key === '.') && ctx && (state.slot !== null || ctx.sel.rows.length)) { e.preventDefault(); if (!ui.right) ui.right = true; stepClose(e.key === '.' ? 1 : -1); }
  if (e.key === 'Escape' && state.slot !== null && !document.querySelector('.pop')) { state.slot = null; if (state.lane?.startsWith('case:')) state.lane = null; render(); }
  if ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && ctx && !document.activeElement.closest('.pop, .slot, table')) {
    const list = ctx.all.filter((l) => l.kind !== 'off'); const at = list.findIndex((l) => l.id === state.lane); const next = list[at + (e.key === 'ArrowDown' ? 1 : -1)];
    if (next) { e.preventDefault(); selectLane(next); }
  }
});

function openModel(model, preset, lanes = null) {
  Object.assign(state, { model, preset, candidate: 0, lane: null, slot: null, page: 0, side: 'kept' });
  // A new question shows the lanes it refers to and the ones a link names. A lane switched on by hand stays on; one switched off comes back.
  state.dims = lanes === null ? Object.fromEntries(Object.entries(state.dims).filter(([, on]) => on)) : lanesFromParam(lanes, dimensionsIn(toText(model)));
  state.rows = state.model.split ? 'split' : 'ledger';
  if (state.model.split) state.splitBy = state.model.split.type;
  render();
}
const open = (p) => { state.notice = ''; openModel(fromText(p.text).model, p.id); };
/** Whether a question can be opened: it runs, or the engine refuses it only for what these bars lack, and the bench then says so. */
const opens = (model) => { const r = run(toText(model)); return r.ok || refusal(r); };
/** The question a link asks: a drawing carried from Composer, else the text in the address, else none. */
function asked() {
  const link = readLink(location.search);
  if (link && !link.error) {
    const model = { find: { join: 'or', items: [make('drawing', { g1: link.g1, packet: link.packet, held: link.held })] }, wheres: [], split: null, horizons: ['1h', '4h'] };
    if (opens(model)) return { model, preset: null };
  }
  if (link) state.notice = `The drawing in the link could not be read${link.error ? `: ${link.error.replace(/\.$/, '')}` : ''}`;
  const hash = new URLSearchParams(location.hash.slice(1)); const q = hash.get('q'); const given = q ? fromText(q).model : null;
  if (!given || !opens(given)) return null;
  const preset = PRESETS.find((p) => toText(fromText(p.text).model) === toText(given))?.id ?? null;
  if (hash.get('dr')) try { attach(given, decodeDrawing(hash.get('dr'))); } catch { /* the text still asks the question; only the drawing is lost */ }
  return { model: given, preset, lanes: hash.get('ln') };
}
const fail = (what) => (e) => { console.error(e); $('#status').textContent = `${what}: ${e.message}`; $('#status').className = 'err'; };
/** Ask the same question of another window. The question stays; what was selected on the old bars does not. */
async function openWindow(key) {
  if (state.loading) return;
  if (key === loaded()) {
    // Choosing what is already on screen still settles the choice. After a cube read that failed, the pinned recording
    // is shown while the address keeps asking for the cube's window: picking it makes it the window that is kept.
    if (state.asked || ui.window !== key) { ui.window = key; persist(); state.asked = null; state.notice = ''; render(); }
    return;
  }
  state.loading = true; $('#status').className = ''; $('#status').textContent = 'Reading the window…'; renderBars();
  try {
    await load(key);
    ui.window = key; persist(); state.asked = null;
    Object.assign(state, { candidate: 0, lane: null, slot: null, page: 0, casePage: 0, caseKey: '', notice: '' });
  } catch (e) { state.notice = `That window could not be read: ${e.message}`; }
  state.loading = false; render();
}
/** The bars to open on: the window in the address, else the one last used, else the server's default. Failing that, the pinned recording. */
async function firstLoad() {
  state.source = await sources();
  const known = (key) => key === PINNED || state.source.windows.some((w) => w.key === key) || /^since:\d{4}-\d{2}-\d{2}$/.test(key || '');
  const want = state.source.cube ? [new URLSearchParams(location.hash.slice(1)).get('w'), ui.window, state.source.default].find(known) : PINNED;
  try { await load(want); } catch (e) {
    if (want === PINNED) throw e;
    await load(PINNED); state.asked = want;
    state.notice = `The cube could not be read (${e.message}); showing the pinned recording`;
  }
}
firstLoad().then(async () => {
  try {
    const a = asked();
    // A question that reads a dimension needs the cube's bars. When the link names no window and the bench was last
    // left on the pinned recording, it opens on the cube's default window rather than on a refusal.
    if (a && state.source.cube && !counters() && !new URLSearchParams(location.hash.slice(1)).get('w') && dimensionsIn(toText(a.model)).length) {
      try {
        await load(state.source.default);
        state.asked = null;
        state.notice = '';
      } catch (e) { state.notice = `The cube could not be read (${e.message}); this question needs its bars`; }
    }
    if (a) openModel(a.model, a.preset, a.lanes ?? null); else openModel(fromText(PRESETS[0].text).model, PRESETS[0].id);
  } catch (e) { fail('The bench could not be drawn')(e); }
}, fail('The bars could not be loaded'));
let timer; window.addEventListener('resize', () => { clearTimeout(timer); timer = setTimeout(() => state.model && render(), 120); });
