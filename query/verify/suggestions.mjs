// Drive the bench's actual add-condition handlers with controlled engine counts and a small DOM stand-in.
// No browser, recording or engine build is needed: node query/verify/suggestions.mjs
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createContext, runInContext } from 'node:vm';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');
const bench = await read('../bench/bench.js');
const vocab = (await read('../shared/vocab.js')).replace(/^import .*;\n/gm, '').replace(/^export /gm, '');
const ui = await read('../shared/ui.js');
const candles = JSON.parse(await read('../../study/catalogue/candles.json')).patterns;
const section = bench.slice(bench.indexOf('const FILLER ='), bench.indexOf('// ---------------------------------------------------------------- panels, keys, start'));

class Element {
  constructor(tag) { this.tag = tag; this.attrs = {}; this.children = []; this.listeners = {}; this.style = {}; this.value = ''; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k] ?? null; }
  removeAttribute(k) { delete this.attrs[k]; }
  set className(v) { this.attrs.class = v; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  get textContent() { return this.children.map(c => typeof c === 'object' ? c.textContent : String(c)).join(''); }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  dispatch(type, extra = {}) { for (const fn of this.listeners[type] || []) fn({ preventDefault() {}, ...extra }); }
  querySelectorAll(selector) {
    const match = (el) => selector === '.active' ? el.className?.split(' ').includes('active')
      : selector === '[role="option"]' ? el.attrs.role === 'option' : selector === '[data-count]' && 'data-count' in el.attrs;
    return this.children.filter(c => c instanceof Element).flatMap(c => [...(match(c) ? [c] : []), ...c.querySelectorAll(selector)]);
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  get className() { return this.attrs.class || ''; }
  closest() { return this; }
  getBoundingClientRect() { return { width: 440, left: 0, top: 500 }; }
  get offsetHeight() { return 356; }
  scrollIntoView() {}
  remove() { this.removed = true; }
  focus() {}
}

function harness(empty = false, known = 7) {
  const input = new Element('input');
  const frames = []; const timers = []; const counted = []; const unknowns = [];
  const context = createContext({
    CANDLES: candles,
    document: { createElement: tag => new Element(tag), body: new Element('body'), querySelector: () => input },
    requestAnimationFrame: fn => frames.push(fn), setTimeout: fn => timers.push(fn),
    int: n => String(n), render() {},
    count(body) {
      counted.push(body);
      if (empty) return 0;
      const last = [...body.matchAll(/^where (.*)$/gm)].at(-1)?.[1] || '';
      if (last.includes('delta(), is: below')) return null;
      if (last.includes('delta(), is: above')) return 7;
      if (/dimension_multiple|volume\(bars_ago|prior_high\(over: 4h, of: volume|candle_share/.test(last)) return 0;
      return known;
    },
    unknownLeft(body) {
      unknowns.push(body);
      return !empty && body.includes('volume(bars_ago: 1)') ? { n: 3, why: 'look-back incomplete' } : null;
    },
  });
  runInContext(vocab, context);
  runInContext(ui.slice(ui.indexOf('export function h('), ui.indexOf('export function siteHeader(')).replace(/^export /gm, ''), context);
  runInContext(`
    const state = { model: { find: { join: 'or', items: [make('pattern', { p: 'hammer' })] }, wheres: [], horizons: ['1h'], split: null } };
    const ctx = { answer: { rows: ${empty ? '[]' : '[1]'} } };
    const can = () => true;
    const cap = t => t[0].toUpperCase() + t.slice(1);
    const label = (text, cls = '') => h('span', { class: 'label ' + cls }, text);
    const update = fn => fn(state.model);
    ${section}
  `, context);
  const api = runInContext('({ state, showAdd, hideAdd, get list() { return addList; }, get pick() { return addPick; }, get box() { return addBox; } })', context);
  return { api, input, counted, unknowns,
    flush() { while (frames.length) frames.shift()(); while (timers.length) timers.shift()(); },
    key(key) { input.dispatch('keydown', { key }); },
    search(value) { input.value = value; input.dispatch('input'); },
  };
}
const options = h => h.api.box.querySelectorAll('[role="option"]');
const rank = s => s.mode || s.n > 0 ? 0 : s.n === 0 ? 2 : 1;
function ordered(h) {
  const ranks = Array.from(h.api.list, rank);
  assert.deepEqual(ranks, ranks.slice().sort(), 'known positives precede pending counts and zero counts');
}
function aligned(h) {
  const buttons = options(h);
  assert.equal(buttons.length, h.api.list.length);
  buttons.forEach((b, i) => {
    assert.equal(b.attrs.id, `add-opt-${i}`);
    assert.equal(b.attrs['aria-selected'], String(i === h.api.pick));
    assert.equal(b.className.includes('active'), i === h.api.pick);
    assert.equal(b.className.includes('zero'), h.api.list[i].n === 0);
    assert.ok(b.textContent.includes(h.api.list[i].label[0].toUpperCase() + h.api.list[i].label.slice(1)));
    const s = h.api.list[i];
    assert.equal(b.children[1].textContent, s.mode ? '' : s.readCount ? '…' : s.unknown ? `? ${s.unknown.n} unknown` : String(s.n));
  });
  assert.equal(h.input.getAttribute('aria-activedescendant'), buttons[h.api.pick]?.attrs.id ?? null);
}

const h = harness();
h.api.showAdd();
ordered(h); aligned(h);
const original = Array.from(h.api.list);
const pending = original.filter(s => s.defer);
assert.ok(pending.length > 0);
assert.ok(pending.every(s => s.n === undefined));
assert.equal(h.api.box.querySelectorAll('[data-count]').length, pending.length);
assert.ok(h.counted.every(body => !/dimension_multiple|where candle_relation\((volume|delta)\(/.test(body)), 'dimension counts stay deferred');
const target = pending.find(s => s.label.includes('net buying'));
assert.ok(target);
const reads = h.counted.length;
for (let i = 0; i < original.indexOf(target); i++) h.key('ArrowDown');
assert.equal(h.api.list[h.api.pick], target);
assert.equal(h.counted.length, reads, 'arrows reuse the suggestions');
aligned(h);
h.flush();
ordered(h); aligned(h);
assert.equal(h.counted.length, reads + pending.length, 'each pending count runs once despite arrow navigation');
assert.equal(h.api.list[h.api.pick], target, 'the picked suggestion survives sorting');
assert.equal(target.n, 7);
assert.ok(h.api.list.every(s => s.n !== undefined && s.n !== null));
assert.ok(h.api.list.every(s => original.includes(s)), 'completion updates the existing suggestions');
assert.ok(pending.some(s => s.n === null) && pending.some(s => s.n === 0));
const unknown = h.api.list.find(s => s.unknown);
assert.ok(unknown, 'a deferred zero reads unknownLeft');
const unknownButton = options(h)[h.api.list.indexOf(unknown)];
assert.equal(unknownButton.attrs.title, 'Leaves no close: the engine cannot say for 3 of them. Look-back incomplete.');
assert.ok(unknownButton.children[1].className.includes('unk'));
assert.equal(unknownButton.children[1].textContent, '? 3 unknown');
assert.ok(options(h).some(b => b.attrs.title === 'Leaves no close'));
h.key('ArrowUp'); aligned(h);
h.key('ArrowDown'); aligned(h);
assert.equal(h.api.list[h.api.pick], target);
h.key('Enter');
assert.equal(h.api.box, null);
assert.equal(h.api.state.model.wheres.at(-1).type, 'taker');
assert.equal(h.api.state.model.wheres.at(-1).args.side, 'above');

const first = harness();
first.api.showAdd(); first.flush(); aligned(first);
assert.ok(first.api.list[first.api.pick].n > 0, 'default Enter keeps closes');
const chosen = first.api.list[first.api.pick].label;
options(first)[first.api.pick].dispatch('click');
assert.equal(first.api.state.model.wheres.length, 1, chosen);

const deferredFirst = harness(false, 0);
deferredFirst.api.showAdd();
assert.equal(deferredFirst.api.list[0].n, undefined);
deferredFirst.flush(); aligned(deferredFirst);
assert.ok(deferredFirst.api.list[deferredFirst.api.pick].n > 0, 'default selection follows the first kept line when all known counts were zero');

// A search or closed popover makes the old deferred callback stale.
const empty = harness(true);
empty.api.showAdd();
empty.search('measure 2h');
const measure = empty.api.list[0];
empty.flush();
assert.equal(empty.api.list[0], measure);
assert.equal(options(empty)[0].attrs.title, 'Leaves no close');
empty.key('Enter');
assert.ok(empty.api.state.model.horizons.includes('2h'));
empty.search('or doji');
assert.equal(empty.api.list[0].tag, 'Or');
assert.equal(options(empty)[0].attrs.title, 'Leaves no close');
empty.search('');
empty.api.hideAdd(); empty.flush();
assert.equal(empty.api.box, null);
assert.equal(empty.input.getAttribute('aria-expanded'), 'false');
assert.equal(empty.input.getAttribute('aria-activedescendant'), null);
console.log('Passed deferred suggestion ordering, counts, unknowns, navigation, selection, Enter, click and zero titles.');
