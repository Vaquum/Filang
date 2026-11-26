// UI smoke test: runs the real src/app.js against a minimal in-memory DOM stand-in and the real
// data files, then drives the main interactions. It catches runtime errors in the browser code;
// it does not replace a look at the page in a real browser. Usage: node verify/ui-smoke.js
import fs from 'node:fs';
import { inputPath } from '../native/inputs.mjs';
import { loadEnvironment } from './node-env.js';
import { analyze } from '../src/check.js';
import { renderControls } from '../src/study-controls.js';
import { setupBuilder } from '../src/study-builder.js';

// ---------------------------------------------------------------- tiny DOM
const byId = new Map();
class Node {
  constructor() { this.parentNode = null; this.childNodes = []; }
  get firstChild() { return this.childNodes[0] || null; }
  appendChild(c) { if (c.parentNode) c.parentNode.removeChild(c); c.parentNode = this; this.childNodes.push(c); return c; }
  removeChild(c) { const i = this.childNodes.indexOf(c); if (i >= 0) this.childNodes.splice(i, 1); c.parentNode = null; return c; }
  prepend(c) { if (c.parentNode) c.parentNode.removeChild(c); c.parentNode = this; this.childNodes.unshift(c); }
  replaceChildren(...cs) { for (const c of this.childNodes.slice()) this.removeChild(c); for (const c of cs) this.appendChild(c); }
  contains(n) { while (n) { if (n === this) return true; n = n.parentNode; } return false; }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(''); }
  set textContent(v) { this.replaceChildren(); if (v !== '') this.appendChild(new Text(String(v))); }
}
class Text extends Node { constructor(t) { super(); this.data = t; } get textContent() { return this.data; } set textContent(v) { this.data = v; } }
class Element extends Node {
  constructor(tag) { super(); this.tagName = tag.toUpperCase(); this.attrs = {}; this.listeners = {}; this.style = {}; this.dataset = {}; this.hidden = false; this.open = false; this.tabIndex = 0; }
  get className() { return this.attrs.class || ''; }
  set className(v) { this.attrs.class = v; }
  get classList() { return {
    contains: (name) => this.className.split(/\s+/).includes(name),
    add: (name) => { if (!this.classList.contains(name)) this.className = (this.className + ' ' + name).trim(); },
    remove: (name) => { this.className = this.className.split(/\s+/).filter((c) => c !== name).join(' '); },
  }; }
  setAttribute(k, v) { this.attrs[k] = String(v); if (k === 'id') byId.set(String(v), this); if (k === 'value') this._value = undefined; }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(t, f) { (this.listeners[t] ||= []).push(f); }
  dispatch(type, extra = {}) {
    const ev = { type, target: this, key: extra.key, ctrlKey: !!extra.ctrlKey, metaKey: false, clientX: extra.clientX || 0, preventDefault() {}, ...extra };
    for (const f of this.listeners[type] || []) f(ev);
  }
  dispatchEvent(ev) { this.dispatch(ev.type); return true; }
  get children() { return this.childNodes.filter((c) => c instanceof Element); }
  get value() {
    if (this.tagName === 'SELECT') { const opts = this.querySelectorAll('option'); const s = opts.find((o) => o._selected === true || (o._selected === undefined && 'selected' in o.attrs)); return (s || opts[0] || { value: '' }).value; }
    if (this.tagName === 'OPTION') return this.getAttribute('value') ?? this.textContent;
    return this._value !== undefined ? this._value : (this.getAttribute('value') ?? '');
  }
  set value(v) {
    if (this.tagName === 'SELECT') { for (const o of this.querySelectorAll('option')) o._selected = o.value === v; return; }
    this._value = String(v);
  }
  get checked() { return this._checked !== undefined ? this._checked : 'checked' in this.attrs; }
  set checked(v) { this._checked = !!v; }
  get disabled() { return 'disabled' in this.attrs; }
  focus() { doc.activeElement = this; }
  setSelectionRange(a, b) { this.selectionStart = a; this.selectionEnd = b; }
  scrollIntoView() {}
  getBoundingClientRect() { return { left: 0, top: 0, width: 800, height: 300 }; }
  get clientWidth() { return 800; }
  get clientHeight() { return this.tagName === 'CANVAS' ? 300 : 20; }
  get scrollHeight() { return 200; }
  showModal() { this.open = true; }
  close() { this.open = false; }
  getContext() { const s = {}; return new Proxy(s, { get: (t, k) => (k in t ? t[k] : () => {}), set: (t, k, v) => { t[k] = v; return true; } }); }
  matches(sel) {
    const m = /^([a-zA-Z]*)((?:[.#][\w-]+)*)((?:\[[^\]]+\])*)$/.exec(sel.trim());
    if (!m) throw new Error('unsupported selector ' + sel);
    if (m[1] && this.tagName !== m[1].toUpperCase()) return false;
    for (const part of m[2].match(/[.#][\w-]+/g) || []) {
      if (part[0] === '.' && !this.className.split(/\s+/).includes(part.slice(1))) return false;
      if (part[0] === '#' && this.getAttribute('id') !== part.slice(1)) return false;
    }
    for (const a of m[3].match(/\[[^\]]+\]/g) || []) {
      const [k, v] = a.slice(1, -1).split('=');
      if (!(k in this.attrs)) return false;
      if (v !== undefined && this.attrs[k] !== v.replace(/^["']|["']$/g, '')) return false;
    }
    return true;
  }
  querySelectorAll(sel) { const out = []; const walk = (n) => { for (const c of n.children) { if (c.matches(sel)) out.push(c); walk(c); } }; walk(this); return out; }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}
const doc = {
  activeElement: null,
  createElement: (t) => new Element(t),
  createTextNode: (t) => new Text(t),
  getElementById: (id) => byId.get(id) || null,
  querySelector: () => null,
};
const body = new Element('body');
const mk = (tag, id, parent = body, attrs = {}) => { const e = new Element(tag); e.setAttribute('id', id); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); parent.appendChild(e); return e; };
for (const [tag, id] of [['div', 'badges'], ['pre', 'overlay'], ['textarea', 'query'], ['div', 'diag'], ['div', 'suggest'], ['div', 'guided'], ['button', 'run'], ['span', 'runstate'],
  ['div', 'live'], ['select', 'example-select'], ['div', 'candidates'], ['div', 'summary'], ['div', 'compare'], ['div', 'outcomes'], ['canvas', 'timeline'], ['canvas', 'chart'],
  ['p', 'chart-caption'], ['div', 'detail'], ['div', 'rows'], ['div', 'lesson'], ['div', 'spec-body'], ['div', 'defs-body'], ['div', 'prov-body'], ['button', 'tab-text'],
  ['button', 'tab-guided'], ['div', 'panel-text'], ['div', 'panel-guided'], ['details', 'resolution'], ['p', 'example-note']]) mk(tag, id);
const chartMode = mk('select', 'chart-mode');
for (const v of ['near', 'full']) { const o = new Element('option'); o.setAttribute('value', v); chartMode.appendChild(o); }
const le = mk('div', 'load-error'); le.hidden = true; const why = new Element('p'); why.setAttribute('class', 'why'); le.appendChild(why);
const dlg = mk('dialog', 'def-dialog'); mk('h2', 'def-title', dlg); const closeBtn = new Element('button'); closeBtn.setAttribute('class', 'close'); dlg.appendChild(closeBtn); mk('div', 'def-body', dlg);

globalThis.Node = Node;
globalThis.document = doc;
globalThis.window = { devicePixelRatio: 2, addEventListener() {} };
globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
globalThis.location = { protocol: 'http:' };
globalThis.fetch = async (p) => {
  const f = inputPath(p);
  if (!fs.existsSync(f)) return { ok: false, status: 404 };
  const b = fs.readFileSync(f);
  return { ok: true, status: 200, arrayBuffer: async () => b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength) };
};

// ---------------------------------------------------------------- harness
let passed = 0;
const failures = [];
const step = async (name, fn) => {
  try { await fn(); passed++; console.log(`  ✓ ${name}`); } catch (e) { failures.push(`${name}: ${e && e.stack ? e.stack.split('\n').slice(0, 4).join(' | ') : e}`); console.log(`  ✗ ${name}`); }
};
const expect = (cond, msg) => { if (!cond) throw new Error(msg); };
const $ = (id) => doc.getElementById(id);
const text = (id) => $(id).textContent;
const all = (root, sel) => root.querySelectorAll(sel);
const button = (root, label) => {
  const b = all(root, 'button').find((x) => x.textContent.includes(label));
  if (!b) throw new Error(`no button "${label}" in #${root.getAttribute('id') || root.tagName}`);
  return b;
};
process.on('unhandledRejection', (e) => { failures.push(`unhandled rejection: ${e && e.stack}`); });
const DUMP = process.argv.includes('--dump');
const dump = (label, ids) => {
  if (!DUMP) return;
  console.log(`\n----- ${label}`);
  for (const id of ids) console.log(`[#${id}]\n${$(id).textContent.replace(/\s+\n/g, '\n').slice(0, 2400)}\n`);
};

console.log('UI smoke test (real app.js, in-memory DOM stand-in, real data files)\n');
await import('../src/app.js');
for (let k = 0; k < 400 && !text('summary'); k++) await new Promise((r) => setTimeout(r, 25));

await step('boot: inputs verified, starter loaded and checked, nothing evaluated before the prediction', () => {
  expect(text('badges').includes('✓ provenance'), `badges: ${text('badges')}`);
  expect(text('summary').includes('Not run yet'), `summary: ${text('summary').slice(0, 120)}`);
  expect(text('runstate').includes('Not run yet'), 'run state');
  expect($('query').value.startsWith('on BTCUSDT 15m\nfind "Wick rejection"'), 'starter in the editor');
  expect(text('lesson').includes('Predict a local edit, then run the starter') && text('lesson').includes('2025-03-28'), `lesson: ${text('lesson').slice(0, 300)}`);
  expect(text('lesson').includes('only the tail decides it'), 'example passes the other clauses');
  expect(text('spec-body').includes('question  = "on" id duration'), 'spec EBNF');
  expect(text('prov-body').includes('equals provenance csv_sha256'), 'provenance');
  expect(text('diag').includes('2 candidate runs'), 'diagnostics ok line');
  dump('after boot', ['badges', 'lesson', 'diag', 'summary', 'compare', 'chart-caption']);
});

await step('lesson: predict, run the starter, check against the engine', () => {
  const form = all($('lesson'), 'form')[0];
  const pick = (name, v) => { const r = all(form, 'input').find((x) => x.getAttribute('name') === name && x.getAttribute('value') === v); r.dispatch('change'); };
  pick('q1', 'no'); pick('q2', 'yes'); pick('q3', 'a'); pick('q4', 'no');
  form.dispatch('submit');
  expect(text('lesson').includes('4/4 predictions matched'), `lesson check: ${text('lesson').slice(-600)}`);
  expect(text('compare').includes('+2 added') && text('compare').includes('−0 removed') && text('compare').includes('2 kept'), 'starter diff');
  expect(text('compare').includes('∉ (15:30, 16:00]'), 'reason in the compare panel');
  expect(text('summary').includes('Candidate session_tail.last=1h'), 'last candidate selected');
  expect(text('outcomes').includes('Measured returns'), 'outcomes table');
  expect(text('detail').includes('2025-03-28T19:30:00Z'), `first added row selected: ${text('detail').slice(0, 160)}`);
  dump('after the prediction check', ['lesson', 'candidates', 'compare', 'summary', 'outcomes', 'rows', 'detail']);
});

await step('row selection, chart context and the changes view', () => {
  const rowBtn = all($('rows'), 'button').find((b) => b.textContent === '2025-03-28 19:30Z');
  rowBtn.dispatch('click');
  expect(text('detail').includes('15:30 EDT'), 'detail for the selected row');
  chartMode.value = 'full'; chartMode.dispatch('change');
  button($('rows'), 'Changes vs basis').dispatch('click');
  expect(text('rows').includes('added'), 'changes view lists added rows');
  button($('rows'), 'All events').dispatch('click');
  expect(text('rows').includes('page 1 of'), 'pagination in the all-events view');
  expect(text('rows').includes('excluded by where #1 (unknown)') && text('rows').includes('excluded by where #1 (false)'), 'exclusions with their Kleene value');
  expect(!text('rows').includes('kept'), 'excluded rows are not labelled kept');
  button($('rows'), 'next').dispatch('click');
  expect(text('rows').includes('page 2 of'), 'next page');
});

await step('guided editor: edit a sweep value, add a condition, run, compare with the previous run', () => {
  $('tab-guided').dispatch('click');
  expect(text('guided').includes('wick rejection (body ≤ 35%'), 'friendly label from the template');
  const inp = all($('guided'), 'input').find((x) => x.getAttribute('aria-label') === 'session_tail last choice 2 (duration)');
  expect(inp, 'choice input');
  inp.value = '2h'; inp.dispatch('change');
  expect($('query').value.includes('last: {30m | 2h}'), `text updated: ${$('query').value}`);
  const wheres = () => $('query').value.split('\n').filter((l) => l.startsWith('where')).length;
  const before = wheres();
  const add = all($('guided'), 'select').find((x) => x.getAttribute('aria-label') === 'add a where condition');
  add.value = '2'; add.dispatch('change');
  expect(wheres() === before + 1 && $('query').value.includes('where weekday(nyse_regular) = fri\nwhere session_tail'), `where added: ${JSON.stringify($('query').value)}`);
  $('run').dispatch('click');
  expect(text('compare').includes('previous run'), `auto basis is the previous run: ${text('compare').slice(0, 200)}`);
  $('tab-text').dispatch('click');
});

await step('typed errors show spans; Run refuses invalid text', () => {
  const q = $('query');
  q.value = 'on BTCUSDT 15m\nfind "Wick rejection"\nwhere session_tail(nyse_regular, lst: 30m)\nmeasure close_return(after: [1h, 4%])';
  q.dispatch('input');
  expect(text('diag').includes('Signature error') && text('diag').includes('Type error'), `diagnostics: ${text('diag')}`);
  expect(all($('overlay'), 'mark').length >= 2, 'error spans highlighted');
  $('run').dispatch('click');
  expect(text('runstate').includes('Not run'), 'not run');
  button($('diag'), 'line 3').dispatch('click');
  expect(q.selectionStart === q.value.indexOf('lst'), 'span selected in the editor');
});

await step('suggestions from signatures insert text', () => {
  const q = $('query');
  q.value = 'on BTCUSDT 15m\nfind "Wick rejection"\nwhere session_tail(nyse_regular, ';
  q.dispatch('input');
  q.selectionStart = q.value.length; q.dispatch('keyup');
  button($('suggest'), 'last:').dispatch('click');
  expect(q.value.endsWith('last: '), `inserted: ${q.value}`);
});

await step('transfer: groups, then turn a group into a filter and compare', () => {
  const sel = $('example-select');
  sel.value = 'transfer'; sel.dispatch('change');
  $('run').dispatch('click');
  expect(text('outcomes').includes('Buckets partition the matches'), 'grouping invariant line');
  expect(text('lesson').includes('Turn the “up” group into a filter'), 'lesson step 3 offers the filter');
  button($('outcomes'), 'keep only up').dispatch('click');
  expect($('query').value.includes('where completed_trend(frame: 4h) = up'), 'filter clause added');
  expect(text('compare').includes('removed') && text('compare').includes('completed_trend(frame: 4h) = up'), 'diff names the new clause');
  expect(text('lesson').includes('kept'), 'lesson reports the filter run');
  dump('after group → filter', ['query', 'compare', 'outcomes', 'resolution']);
});

await step('definition dialogs: named preset, coverage table, extension conformance, planned capability', () => {
  const specBtn = (label) => all($('spec-body'), 'button').find((b) => b.textContent === label);
  specBtn('quiet_range@1').dispatch('click');
  expect(dlg.open && text('def-body').includes('Choice of width_max') && text('def-body').includes('(chosen)'), 'coverage section');
  closeBtn.dispatch('click');
  specBtn('quiet_friday_close@1').dispatch('click');
  const conf = /Conformance on recorded bars: (\d+)\/(\d+) pass/.exec(text('def-body'));
  expect(conf && conf[1] === conf[2] && Number(conf[2]) >= 10, `conformance: ${conf ? conf[0] : text('def-body').slice(0, 300)}`);
  specBtn('value_area_reclaim@0').dispatch('click');
  expect(text('def-body').includes('planned design example'), 'planned');
  all($('defs-body'), 'button').find((b) => b.textContent.includes('Wick rejection')).dispatch('click');
  expect(text('def-body').includes('not a Composer object'), 'named preset origin');
});

await step('every example loads, renders in the guided editor, and runs (diagnostics explain errors)', () => {
  const sel = $('example-select');
  for (const o of all(sel, 'option').filter((x) => x.value)) {
    sel.value = o.value; sel.dispatch('change');
    expect(text('runstate').includes('New question loaded'), `${o.value}: fresh-load state`);
    $('tab-guided').dispatch('click');
    expect(text('guided').length > 40, `${o.value}: guided view rendered`);
    const oneOption = all($('guided'), 'select').filter((s) => all(s, 'option').length < 2);
    expect(oneOption.length === 0, `${o.value}: no one-option selects (${oneOption.map((s) => s.getAttribute('aria-label')).join(', ')})`);
    if (DUMP && ['starter', 'transfer', 'band', 'extension'].includes(o.value)) dump(`guided view: ${o.value}`, ['guided']);
    $('tab-text').dispatch('click');
    $('run').dispatch('click');
    if (o.value.startsWith('err-')) expect(text('diag').includes('error'), `${o.value} diagnostics`);
    else expect(text('runstate').includes('Showing run'), `${o.value} ran: ${text('runstate')}`);
  }
});

await step('text editor: the phrase under the caret opens its definition', () => {
  const sel = $('example-select');
  sel.value = 'starter'; sel.dispatch('change');
  const q = $('query');
  q.selectionStart = q.value.indexOf('session_tail') + 3; q.dispatch('click');
  button($('suggest'), 'definition of session_tail@1').dispatch('click');
  expect(dlg.open && text('def-body').includes('c − D < t ≤ c'), `session_tail dialog: ${text('def-body').slice(0, 200)}`);
  closeBtn.dispatch('click');
  q.selectionStart = q.value.indexOf('"Quiet range"') + 2; q.dispatch('keyup');
  button($('suggest'), 'definition of “Quiet range”').dispatch('click');
  expect(text('def-body').includes('immutable named definition'), 'named preset dialog');
  closeBtn.dispatch('click');
});

await step('timeline click selects a row; candidate tabs follow arrow keys', () => {
  $('run').dispatch('click');
  $('timeline').dispatch('click', { clientX: 0 });
  const tabs = all($('candidates'), 'button');
  tabs[tabs.length - 1].dispatch('keydown', { key: 'ArrowRight' });
  expect(text('summary').includes('Candidate session_tail.last=30m'), 'arrow key wraps to the first candidate');
});

await step('a Boolean group becomes a filter (true → clause, false → not clause)', () => {
  const q = $('query');
  q.value = 'on BTCUSDT 15m\nfind "Wick rejection"\nwhere weekday(nyse_regular) = fri\ngroup by session_tail(nyse_regular, last: 1h)\nmeasure close_return(after: [1h, 4h])';
  q.dispatch('input');
  $('run').dispatch('click');
  expect(text('outcomes').includes('Buckets partition the matches: 10 true + 259 false'), `boolean buckets: ${text('outcomes').slice(-260)}`);
  button($('outcomes'), 'keep only false').dispatch('click');
  expect(q.value.includes('where not session_tail(nyse_regular, last: 1h)'), `not clause: ${q.value}`);
  expect(text('compare').includes('−10 removed') && text('compare').includes('259 kept'), `filter diff: ${text('compare').slice(0, 400)}`);
});

await step('basis selector and candidate tabs', () => {
  const sel = $('example-select');
  sel.value = 'practice'; sel.dispatch('change');
  $('run').dispatch('click');
  const tabs = all($('candidates'), 'button');
  expect(tabs.length === 2, 'two candidate tabs');
  tabs[0].dispatch('click');
  expect(text('summary').includes('Candidate session_tail.last=30m'), 'first candidate');
  const b = doc.getElementById('basis-select');
  b.value = 'none'; b.dispatch('change');
  expect(text('compare').includes('No basis yet'), 'no comparison');
});

await step('removed rows align returns with added, replaced and reordered horizon headers', () => {
  const run = (days, horizons) => {
    $('query').value = 'on BTCUSDT 15m\nfind "Wick rejection"\nwhere weekday(nyse_regular) = ' + days +
      '\nmeasure close_return(after: ' + (horizons.length === 1 ? horizons[0] : '[' + horizons.join(', ') + ']') + ')';
    $('query').dispatch('input');
    $('run').dispatch('click');
    expect(text('runstate').includes('Showing run'), text('diag'));
  };
  for (const [before, after] of [
    [['1h'], ['1h', '4h']],
    [['1h'], ['4h']],
    [['1h', '4h'], ['4h', '1h']],
  ]) {
    run('fri', before);
    const basis = new Map(all($('rows'), 'tbody')[0].children.map((row) => {
      const cells = all(row, 'td');
      const returns = cells.slice(-before.length - 1, -1);
      return [cells[0].textContent, new Map(before.map((h, k) => [h, returns[k].textContent]))];
    }));
    run('mon', after);
    button($('rows'), 'Changes vs basis').dispatch('click');
    expect(all($('rows'), 'th').slice(-after.length - 1, -1).map((c) => c.textContent).join(',') === after.map((h) => 'r ' + h).join(','), 'current horizon headers');
    const removed = all($('rows'), 'tr.st-removed');
    expect(removed.length > 0, 'removed basis rows are visible');
    for (const row of removed) {
      const cells = all(row, 'td');
      const saved = basis.get(cells[0].textContent);
      expect(saved, 'removed row was recorded in the basis table');
      const returns = cells.slice(-after.length - 1, -1);
      after.forEach((h, k) => expect(returns[k].textContent === (saved.get(h) ?? '—'), `${cells[0].textContent}: return ${h} aligned with its own horizon`));
    }
  }
});

await step('clearing comparison resets a later Changes page and preserves Matches and All events', () => {
  button($('rows'), 'next').dispatch('click');
  expect(text('rows').includes('page 2 of'), 'later Changes page');
  const basis = (value) => { const select = $('basis-select'); select.value = value; select.dispatch('change'); };
  basis('none');
  expect(button($('rows'), 'Matches').getAttribute('aria-checked') === 'true', 'Matches selected after clearing Changes');
  const diff = button($('rows'), 'Changes vs basis');
  expect(diff.disabled && diff.getAttribute('aria-checked') === 'false', 'Changes disabled and unselected');
  expect(text('rows').includes('page 1 of'), 'Matches starts on the first page');
  for (const view of ['Matches', 'All events']) {
    basis('auto');
    button($('rows'), view).dispatch('click');
    button($('rows'), 'next').dispatch('click');
    basis('none');
    expect(button($('rows'), view).getAttribute('aria-checked') === 'true', view + ' selection preserved');
    expect(text('rows').includes('page 2 of'), view + ' page preserved');
  }
});

const E = loadEnvironment();
await step('Adjust applies suggested scalar, vector and sweep horizons as standalone values', () => {
  const host = mk('div', 'builder');
  const dialog = mk('dialog', 'dialog');
  const state = { env: E, analysis: analyze('on BTCUSDT 15m\nfind channel_breakout(over: 18h)\nmeasure close_return(after: 4h)', E.env) };
  let edited = null;
  const builder = setupBuilder(host, {
    state,
    edit: (text) => { edited = text; return true; },
    openDialog: (...nodes) => { dialog.replaceChildren(...nodes); dialog.showModal(); },
    closeDialog: () => dialog.close(),
    getComposerURL: () => '/composer/',
  });
  builder.render();
  for (const value of ['1h', '[1h, 4h]', '{1h | 4h}']) {
    edited = null;
    const outcome = all(host, 'button').find((b) => b.getAttribute('aria-label') === 'Change outcome Close return');
    button(outcome.parentNode, 'Adjust').dispatch('click');
    const pick = all(dialog, '.param-picks')[0].querySelectorAll('button').find((b) => b.textContent === value);
    expect(pick, 'standalone suggestion ' + value);
    pick.dispatch('click');
    expect(all(dialog, 'input.arg-input')[0].value === value, 'suggestion fills the argument');
    all(dialog, 'form')[0].dispatch('submit');
    expect(edited?.endsWith('measure close_return(after: ' + value + ')'), 'suggestion applied: ' + dialog.textContent);
    expect(!dialog.open && analyze(edited, E.env).ok, 'valid query applied and dialog closed');
  }
});

await step('trend shortcut preserves weekday grouping by leaving mixed queries to the clause builder', () => {
  const host = mk('div', 'question-controls');
  let edited = null;
  const render = (clauses) => {
    edited = null;
    const analysis = analyze('on BTCUSDT 15m\nfind channel_breakout(over: 18h)\n' + clauses, E.env);
    expect(analysis.ok, 'valid controls query');
    renderControls(host, { analysis, env: E, candidate: 0, source: { anchor: null }, composerLink: '/composer/', edit: (text) => { edited = text; } });
    return all(host, 'select').find((s) => s.getAttribute('aria-label') === '4h bar direction');
  };
  expect(!render('where completed_trend(frame: 4h) = up\ngroup by weekday(nyse_regular)'), 'no shortcut for a weekday group with a trend filter');
  expect(host.textContent.includes('completed_trend(frame: 4h) = up') && host.textContent.includes('Group by weekday(nyse_regular)'), 'both clauses remain visible');
  expect(edited === null, 'rendering keeps the mixed query intact');
  for (const [clause, value, expected] of [
    ['group by completed_trend(frame: 4h)', 'down', 'where completed_trend(frame: 4h) = down'],
    ['where completed_trend(frame: 4h) = up', 'group', 'group by completed_trend(frame: 4h)'],
  ]) {
    const shortcut = render(clause);
    expect(shortcut, 'shortcut remains available for ' + clause);
    shortcut.value = value; shortcut.dispatch('change');
    expect(edited?.endsWith(expected) && analyze(edited, E.env).ok, 'shortcut still applies a valid trend change');
  }
});

console.log(`\n${passed} passed, ${failures.length} failed`);
if (failures.length) { console.log('\nFailures:'); for (const f of failures) console.log(`  - ${f}`); process.exit(1); }
process.exit(0);
