// Minimal DOM helpers (no framework).

export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v === null || v === undefined || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'text') el.textContent = v;
      else if (k === 'html') throw new Error('html attribute not allowed');
      else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
      else if (k === 'dataset') Object.assign(el.dataset, v);
      else if (v === true) el.setAttribute(k, '');
      else el.setAttribute(k, String(v));
    }
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const c of children) {
    if (c === null || c === undefined || c === false) continue;
    if (Array.isArray(c)) append(el, c);
    else if (c instanceof Node) el.appendChild(c);
    else el.appendChild(document.createTextNode(String(c)));
  }
}

export function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }
export function mount(el, ...children) { clear(el); append(el, children); return el; }
export const $ = (sel, root = document) => root.querySelector(sel);

export function kleeneBadge(v, title) {
  const cls = v === 1 ? 'k-t' : v === 0 ? 'k-f' : 'k-u';
  const sym = v === 1 ? '✓' : v === 0 ? '✗' : '?';
  const word = v === 1 ? 'true' : v === 0 ? 'false' : 'unknown';
  return h('span', { class: `kb ${cls}`, title: title || word }, h('span', { 'aria-hidden': 'true' }, sym), h('span', { class: 'sr' }, word));
}

export function fmtInt(n) { return n.toLocaleString('en-US'); }

let uid = 0;
export function nextId(prefix = 'id') { uid += 1; return `${prefix}-${uid}`; }
