// Shared interface parts: header, clause phrases with editable slots, the slot popover, the source plate.
import { int } from './filang.js';
import { phraseParts, slotLabel, step, PATTERNS } from './vocab.js';

export function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'class') el.className = v;
    else if (k === 'html') el.innerHTML = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat(Infinity)) if (kid !== null && kid !== undefined && kid !== false) el.append(kid);
  return el;
}
export const mount = (el, ...kids) => { el.replaceChildren(...kids.flat(Infinity).filter((k) => k !== null && k !== undefined && k !== false)); return el; };
export const $ = (sel, root = document) => root.querySelector(sel);

export function siteHeader(current) {
  const link = (href, id, text) => h('a', { href, class: 'micro', 'aria-current': current === id ? 'page' : null }, text);
  return h('header', { class: 'site' },
    h('a', { class: 'mark', href: '/' }, h('b', null, 'Filang'), h('span', { class: 'micro' }, 'Query builder / three directions')),
    h('nav', { 'aria-label': 'Directions' }, link('/', 'index', 'Index'), link('/ledger/', 'ledger', 'A · Ledger'), link('/sentence/', 'sentence', 'B · Sentence'), link('/specimen/', 'specimen', 'C · Specimen')));
}

// ---------------------------------------------------------------- source plate

const esc = (t) => t.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
export function highlight(text) {
  return esc(text).replace(/(--[^\n]*)|("(?:[^"\\]|\\.)*")|\b(on|let|find|where|group by|measure|and|or|not)\b|\b(\d+(?:\.\d+)?(?:%|[mhd]\b)?)|\b([a-z_][a-z0-9_]*)(?=\()/g,
    (m, c, str, kw, num, call) => (c ? `<span class="c">${c}</span>` : str ? `<span class="s">${str}</span>` : kw ? `<span class="k">${kw}</span>` : num ? `<span class="n">${num}</span>` : `<span class="k">${call}</span>`));
}

/** The formal query on a navy plate. With onEdit it is an editor that reports each change. */
export function plate({ label = 'Filang / the formal query', text = '', onEdit = null }) {
  const pre = h('pre', { 'aria-hidden': onEdit ? 'true' : null });
  const copy = h('button', { class: 'micro', type: 'button', onclick: async () => { try { await navigator.clipboard.writeText(current); copy.textContent = 'Copied'; } catch { copy.textContent = 'Select'; } setTimeout(() => { copy.textContent = 'Copy'; }, 1200); } }, 'Copy');
  const diag = h('div', { class: 'diag', role: 'status', hidden: true });
  let current = text;
  let area = null;
  const paint = () => { pre.innerHTML = highlight(current) + '\n'; };
  if (onEdit) {
    area = h('textarea', { spellcheck: 'false', autocapitalize: 'off', autocomplete: 'off', 'aria-label': 'Formal query',
      oninput: () => { current = area.value; paint(); onEdit(current); } });
  }
  const el = h('figure', { class: 'plate', style: 'margin:0' },
    h('header', null, h('span', { class: 'micro' }, label), copy),
    onEdit ? h('div', { class: 'editor' }, pre, area) : pre, diag);
  const api = {
    el,
    set(t, message = '') {
      current = t;
      if (area && document.activeElement !== area) area.value = t;
      else if (area && area.value !== t && !message) area.value = t;
      paint();
      diag.hidden = !message; diag.textContent = message;
    },
    message(m) { diag.hidden = !m; diag.textContent = m || ''; },
  };
  api.set(text);
  return api;
}

// ---------------------------------------------------------------- popover

let open = null;
export function closePopover() { if (open) { open.close(); open = null; } }

/**
 * Options for one slot. countFor(value) returns the matches that value would leave, or null.
 * A sweepable slot can hold several values at once: each becomes its own candidate run.
 * With multi the options are switches; with empty as well, every one of them can be off.
 * onChange(value, closing) is told when the choice also closes the popover: a caller that redraws the anchor
 * must then put the focus back on the redrawn slot itself, since the anchor it replaced can no longer take it.
 */
export function slotPopover(anchor, { slot, value, onChange, countFor, allowCompare = false, multi = false, empty = false, title = null }) {
  closePopover();
  const selected = new Set(Array.isArray(value) ? value : [value]);
  const isPattern = slot.kind === 'pattern';
  const free = ['dur', 'pct', 'num'].includes(slot.kind);
  const search = (isPattern || free) && h('input', { type: 'text', placeholder: isPattern ? 'Search English or Japanese' : 'Or type a value', 'aria-label': 'Filter or enter a value' });
  const list = h('ul', { role: 'listbox' });
  const pop = h('div', { class: 'pop', role: 'dialog', 'aria-label': 'Choose a value' },
    h('header', null, h('span', { class: 'micro' }, title || (isPattern ? 'Named candle' : slot.key.replace('_', ' '))), h('span', { class: 'micro' }, countFor ? 'Closes left' : '')),
    search, list,
    multi ? h('footer', { class: 'micro' }, 'Click to add or remove') : allowCompare && slot.sweep ? h('footer', { class: 'micro' }, 'Alt-click a second value to compare both') : null);
  let rows = []; let active = 0;
  const pick = (v, compare) => {
    if (multi || (compare && allowCompare && slot.sweep)) {
      if (selected.has(v)) { if (selected.size > 1 || (multi && empty)) selected.delete(v); } else selected.add(v);
      const ordered = slot.options.filter((o) => selected.has(o)).concat([...selected].filter((o) => !slot.options.includes(o)));
      onChange(multi || ordered.length > 1 ? ordered : ordered[0]);
      render();
      // Switches are thrown one after another: the one just thrown keeps the keyboard and its place in the redrawn
      // list, so the arrows carry on from it and Escape still closes.
      const at = multi && empty ? rows.findIndex((r) => r.v === v) : -1;
      if (at >= 0) { active = at; mark(); rows[at].el.firstChild.focus({ preventScroll: true }); }
    } else { onChange(v, true); close(); }
  };
  function render() {
    const q = (search?.value || '').trim().toLowerCase();
    let opts = slot.options;
    if (isPattern && q) opts = PATTERNS.filter((p) => (p.name + ' ' + p.ja + ' ' + p.aliases.join(' ')).toLowerCase().includes(q)).map((p) => p.id);
    rows = opts.map((v) => {
      const p = isPattern ? PATTERNS.find((x) => x.id === v) : null;
      const n = countFor ? countFor(v) : null;
      return { v, el: h('li', null, h('button', { type: 'button', role: 'option', 'aria-checked': String(selected.has(v)), onclick: (e) => pick(v, e.altKey || e.shiftKey || e.metaKey) },
        h('span', null, p ? p.name : slotLabel(slot, v), p ? h('small', null, `${p.ja} · ${p.bars} ${p.bars === 1 ? 'candle' : 'candles'}`) : null),
        h('span', { class: 'fig' }, n === null || n === undefined ? '' : int(n)))) };
    });
    mount(list, rows.map((r) => r.el));
    active = Math.max(0, rows.findIndex((r) => selected.has(r.v)));
    mark();
  }
  const mark = () => rows.forEach((r, i) => r.el.firstChild.classList.toggle('active', i === active));
  const onKey = (e) => {
    if (e.key === 'Escape') { e.preventDefault(); close(); } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault(); if (!rows.length) return; active = (active + (e.key === 'ArrowDown' ? 1 : -1) + rows.length) % rows.length; mark(); rows[active].el.scrollIntoView({ block: 'nearest' });
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const typed = search && !isPattern ? search.value.trim() : '';
      if (typed) pick(typed, false); else if (rows[active]) pick(rows[active].v, e.altKey || e.shiftKey);
    }
  };
  const outside = (e) => { if (!pop.contains(e.target) && e.target !== anchor && !anchor.contains(e.target)) close(); };
  function close() {
    pop.remove(); document.removeEventListener('mousedown', outside, true);
    anchor.setAttribute('aria-expanded', 'false');
    if (open?.pop === pop) open = null;
    if (document.body.contains(anchor)) anchor.focus({ preventScroll: true });
  }
  pop.addEventListener('keydown', onKey);
  if (search) search.addEventListener('input', () => { if (isPattern) render(); });
  document.body.append(pop);
  render();
  const r = anchor.getBoundingClientRect();
  pop.style.left = Math.max(8, Math.min(window.innerWidth - pop.offsetWidth - 8, r.left)) + window.scrollX + 'px';
  const below = r.bottom + 6 + pop.offsetHeight < window.innerHeight || r.top < pop.offsetHeight;
  pop.style.top = (below ? r.bottom + 6 : r.top - pop.offsetHeight - 6) + window.scrollY + 'px';
  anchor.setAttribute('aria-expanded', 'true');
  document.addEventListener('mousedown', outside, true);
  (search || rows[active]?.el.firstChild || pop).focus({ preventScroll: true });
  if (!search) pop.tabIndex = -1;
  open = { pop, close };
  return open;
}

/**
 * A clause as prose with its values as editable slots.
 * Click or Enter opens the options. Up and Down step the value in place.
 */
export function phrase(clause, { onChange, countFor, allowCompare = false, capital = false } = {}) {
  const parts = phraseParts(clause);
  const out = [];
  parts.forEach((p, idx) => {
    if (typeof p === 'string') { out.push(idx === 0 && capital ? p[0].toUpperCase() + p.slice(1) : p); return; }
    const { slot, value } = p;
    if (!onChange) { out.push(h('b', { style: 'font-weight:500' }, slotLabel(slot, value))); return; }
    const label = Array.isArray(value)
      ? value.flatMap((v, i) => (i ? [h('span', { class: 'alt' }, '|'), slotLabel(slot, v)] : [slotLabel(slot, v)]))
      : slotLabel(slot, value);
    const btn = h('button', { type: 'button', class: 'slot', 'aria-haspopup': 'dialog', 'aria-expanded': 'false', 'data-slot': slot.key,
      title: slot.kind === 'pattern' ? 'Choose a candle' : 'Click to choose. Up and Down step the value.',
      onclick: () => slotPopover(btn, { slot, value, allowCompare, countFor: countFor ? (v) => countFor(slot.key, v) : null, onChange: (v, closing) => onChange(slot.key, v, closing) }),
      onkeydown: (e) => {
        if ((e.key === 'ArrowUp' || e.key === 'ArrowDown') && !Array.isArray(value)) {
          e.preventDefault();
          const next = step(slot, value, e.key === 'ArrowUp' ? 1 : -1);
          if (next !== value) onChange(slot.key, next, true);
        }
      } }, label);
    out.push(btn);
  });
  return out;
}

/** Restore focus to the same slot after a re-render. */
export function refocusSlot(root, path) {
  if (!path) return;
  const el = root.querySelector(`[data-clause="${path.clause}"] [data-slot="${path.slot}"]`);
  if (el) el.focus({ preventScroll: true });
}
