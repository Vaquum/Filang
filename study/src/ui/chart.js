// Canvas views of real recorded bars: full-recording timeline and a candlestick context window.

import { centsText } from '../num.js';

function theme(canvas) {
  const cs = getComputedStyle(canvas);
  const v = (name, fb) => (cs.getPropertyValue(name) || '').trim() || fb;
  return {
    fg: v('--fg', '#1d2430'), muted: v('--muted', '#5b6575'), grid: v('--grid', '#e3e7ee'), bg: v('--chart-bg', '#ffffff'),
    up: v('--up', '#1d7f5a'), down: v('--down', '#b4372f'), accent: v('--accent', '#2457c5'),
    added: v('--added', '#1d7f5a'), removed: v('--removed', '#b4372f'), kept: v('--kept', '#2457c5'),
    shade: v('--shade', 'rgba(36, 87, 197, 0.08)'), shade2: v('--shade2', 'rgba(180, 120, 20, 0.10)'),
  };
}

function setup(canvas) {
  const dpr = window.devicePixelRatio || 1;
  const w = Math.max(200, canvas.clientWidth);
  const hgt = Math.max(80, canvas.clientHeight);
  canvas.width = Math.round(w * dpr);
  canvas.height = Math.round(hgt * dpr);
  const g = canvas.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { g, w, h: hgt };
}

const pad2 = (x) => String(x).padStart(2, '0');
const hm = (ms) => { const d = new Date(ms); return `${pad2(d.getUTCHours())}:${pad2(d.getUTCMinutes())}`; };
const md = (ms) => { const d = new Date(ms); return `${pad2(d.getUTCMonth() + 1)}-${pad2(d.getUTCDate())}`; };
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** Whole recording: close line plus a marker per row. Returns a hit-tester for clicks. */
export function drawTimeline(canvas, { rec, marks, selectedSlot }) {
  const { g, w, h } = setup(canvas);
  const c = theme(canvas);
  const padL = 8; const padR = 8; const padT = 6; const padB = 26;
  const pw = w - padL - padR;
  const ph = h - padT - padB;
  g.fillStyle = c.bg; g.fillRect(0, 0, w, h);
  let lo = Infinity; let hi = -Infinity;
  for (let i = 0; i < rec.n; i++) if (rec.present[i]) { if (rec.L[i] < lo) lo = rec.L[i]; if (rec.H[i] > hi) hi = rec.H[i]; }
  const x = (slot) => padL + (pw * (slot + 0.5)) / rec.n;
  const y = (p) => padT + ph - (ph * (p - lo)) / (hi - lo || 1);
  g.strokeStyle = c.grid; g.lineWidth = 1;
  g.fillStyle = c.muted; g.font = '11px system-ui, sans-serif';
  let lastMonth = -1;
  for (let i = 0; i < rec.n; i += 96) {
    const d = new Date(rec.openTime(i));
    if (d.getUTCMonth() !== lastMonth && d.getUTCDate() === 1) {
      lastMonth = d.getUTCMonth();
      g.beginPath(); g.moveTo(x(i), padT); g.lineTo(x(i), padT + ph); g.stroke();
      g.fillText(`${MONTHS[lastMonth]} ${d.getUTCFullYear()}`, x(i) + 3, h - 8);
    }
  }
  g.strokeStyle = c.muted; g.lineWidth = 1; g.beginPath();
  const step = Math.max(1, Math.floor(rec.n / pw));
  let started = false;
  for (let i = 0; i < rec.n; i += step) {
    if (!rec.present[i]) { started = false; continue; }
    if (!started) { g.moveTo(x(i), y(rec.C[i])); started = true; } else g.lineTo(x(i), y(rec.C[i]));
  }
  g.stroke();
  const order = { kept: 0, match: 0, event: -1, removed: 1, added: 2 };
  const sorted = marks.slice().sort((a, b) => (order[a.cls] || 0) - (order[b.cls] || 0));
  for (const m of sorted) {
    const col = m.cls === 'added' ? c.added : m.cls === 'removed' ? c.removed : m.cls === 'event' ? c.grid : c.kept;
    g.fillStyle = col;
    const px = x(m.slot);
    const top = m.cls === 'removed' ? padT + ph - 10 : padT + ph - 16;
    g.fillRect(px - 1, top, 2, m.cls === 'event' ? 6 : 10);
  }
  if (selectedSlot !== null && selectedSlot !== undefined) {
    const px = x(selectedSlot);
    g.strokeStyle = c.fg; g.lineWidth = 1.5;
    g.beginPath(); g.moveTo(px, padT); g.lineTo(px, padT + ph); g.stroke();
    g.beginPath(); g.arc(px, y(rec.C[selectedSlot]), 4, 0, Math.PI * 2); g.stroke();
  }
  g.fillStyle = c.muted;
  g.fillText(`high ${centsText(hi)}`, padL + 2, padT + 10);
  g.fillText(`low ${centsText(lo)}`, padL + 2, padT + ph - 2 - 18);
  return {
    hit(clientX) {
      const r = canvas.getBoundingClientRect();
      const px = clientX - r.left;
      let best = null; let bd = 7;
      for (const m of marks) { if (m.cls === 'event') continue; const d = Math.abs(x(m.slot) - px); if (d < bd) { bd = d; best = m.slot; } }
      return best;
    },
  };
}

/**
 * Candles around an anchor slot with inspectable overlays (all from recorded bars).
 * overlays: { windows: [{from, to, label, tone}], levels: [{from, to, price, label}],
 *             horizons: [{slot, label, value}], times: [{t, label}] }
 */
export function drawCandles(canvas, { rec, anchorSlot, from, to, overlays = {}, eventLabel }) {
  const { g, w, h } = setup(canvas);
  const c = theme(canvas);
  const padL = 64; const padR = 12; const padT = 22; const padB = 34;
  const pw = w - padL - padR;
  const ph = h - padT - padB;
  from = Math.max(0, from);
  to = Math.min(rec.n - 1, to);
  const count = to - from + 1;
  const stepX = pw / count;
  let lo = Infinity; let hi = -Infinity;
  for (let i = from; i <= to; i++) if (rec.present[i]) { lo = Math.min(lo, rec.L[i]); hi = Math.max(hi, rec.H[i]); }
  for (const lv of overlays.levels || []) { lo = Math.min(lo, lv.price); hi = Math.max(hi, lv.price); }
  const padP = (hi - lo) * 0.06 || 100;
  lo -= padP; hi += padP;
  const xL = (slot) => padL + (slot - from) * stepX;
  const xC = (slot) => xL(slot) + stepX / 2;
  const xR = (slot) => xL(slot) + stepX;
  const y = (p) => padT + ph - (ph * (p - lo)) / (hi - lo);
  g.fillStyle = c.bg; g.fillRect(0, 0, w, h);
  g.font = '11px system-ui, sans-serif';
  // windows
  for (const win of overlays.windows || []) {
    const a = Math.max(from, win.from); const b = Math.min(to, win.to);
    if (b < a) continue;
    g.fillStyle = win.tone === 2 ? c.shade2 : c.shade;
    g.fillRect(xL(a), padT, xR(b) - xL(a), ph);
    g.fillStyle = c.muted;
    g.fillText(win.label, xL(a) + 3, padT + 12 + (win.tone === 2 ? 12 : 0));
  }
  // grid + y labels
  g.strokeStyle = c.grid; g.lineWidth = 1; g.fillStyle = c.muted;
  for (let k = 0; k <= 4; k++) {
    const p = lo + ((hi - lo) * k) / 4;
    const yy = y(p);
    g.beginPath(); g.moveTo(padL, yy); g.lineTo(padL + pw, yy); g.stroke();
    g.fillText(centsText(Math.round(p)), 4, yy + 4);
  }
  // x labels
  const every = Math.max(1, Math.ceil(count / 8));
  for (let i = from; i <= to; i++) {
    if ((i - from) % every !== 0) continue;
    const t = rec.closeTime(i);
    g.fillText(hm(t), xR(i) - 14, padT + ph + 14);
    if (i === from || new Date(t).getUTCHours() === 0) g.fillText(md(t), xR(i) - 14, padT + ph + 27);
  }
  // candles
  const bw = Math.max(1, Math.min(10, stepX * 0.62));
  for (let i = from; i <= to; i++) {
    if (!rec.present[i]) continue;
    const o = rec.O[i]; const cl = rec.C[i];
    const col = cl >= o ? c.up : c.down;
    g.strokeStyle = col; g.fillStyle = col; g.lineWidth = 1;
    g.beginPath(); g.moveTo(xC(i), y(rec.H[i])); g.lineTo(xC(i), y(rec.L[i])); g.stroke();
    const top = y(Math.max(o, cl)); const bot = y(Math.min(o, cl));
    g.fillRect(xC(i) - bw / 2, top, bw, Math.max(1, bot - top));
  }
  // levels
  for (const lv of overlays.levels || []) {
    const a = Math.max(from, lv.from); const b = Math.min(to, lv.to);
    if (b < a) continue;
    g.strokeStyle = c.accent; g.setLineDash([4, 3]); g.lineWidth = 1.2;
    g.beginPath(); g.moveTo(xL(a), y(lv.price)); g.lineTo(xR(b), y(lv.price)); g.stroke(); g.setLineDash([]);
    g.fillStyle = c.accent; g.fillText(lv.label, xL(a) + 2, y(lv.price) - 4);
  }
  // times (e.g. session close)
  for (const tm of overlays.times || []) {
    const s = rec.slotClosingAt(tm.t);
    if (s === null || s < from || s > to) continue;
    g.strokeStyle = c.muted; g.setLineDash([2, 3]); g.lineWidth = 1;
    g.beginPath(); g.moveTo(xR(s), padT); g.lineTo(xR(s), padT + ph); g.stroke(); g.setLineDash([]);
    g.fillStyle = c.muted; g.fillText(tm.label, xR(s) + 3, padT + ph - 6);
  }
  // anchor bar + anchor time
  if (anchorSlot >= from && anchorSlot <= to) {
    g.strokeStyle = c.fg; g.lineWidth = 1.5;
    g.strokeRect(xC(anchorSlot) - bw / 2 - 2, y(rec.H[anchorSlot]) - 2, bw + 4, y(rec.L[anchorSlot]) - y(rec.H[anchorSlot]) + 4);
    g.beginPath(); g.moveTo(xR(anchorSlot), padT - 4); g.lineTo(xR(anchorSlot), padT + ph); g.stroke();
    g.fillStyle = c.fg; g.fillText(`anchor t = ${hm(rec.closeTime(anchorSlot))}Z${eventLabel ? ' · ' + eventLabel : ''}`, Math.min(xR(anchorSlot) + 4, w - 220), padT - 8);
  }
  // horizons
  for (const hz of overlays.horizons || []) {
    if (hz.slot > to) continue;
    g.strokeStyle = c.accent; g.lineWidth = 1; g.setLineDash([5, 3]);
    g.beginPath(); g.moveTo(xR(hz.slot), padT); g.lineTo(xR(hz.slot), padT + ph); g.stroke(); g.setLineDash([]);
    if (rec.present[hz.slot]) { g.fillStyle = c.accent; g.beginPath(); g.arc(xC(hz.slot), y(rec.C[hz.slot]), 3, 0, Math.PI * 2); g.fill(); }
    g.fillStyle = c.accent; g.fillText(hz.label, Math.min(xR(hz.slot) + 3, w - 90), padT + 24);
  }
}
