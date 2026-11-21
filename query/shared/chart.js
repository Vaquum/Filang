// Ruled SVG drawings of the recorded tape. Every mark is a recorded value; gold marks the selection.
import { hmUTC, dateUTC, price, pct } from './filang.js';

const NS = 'http://www.w3.org/2000/svg';
export function s(tag, attrs = {}, ...kids) {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) if (v !== null && v !== undefined && v !== false) el.setAttribute(k, v);
  for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) el.append(kid);
  return el;
}
const MONTH = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
const dayLabel = (t) => { const d = new Date(t); return `${MONTH[d.getUTCMonth()]} ${String(d.getUTCDate()).padStart(2, '0')}`; };
function frame(host, height) {
  const W = Math.max(320, Math.floor(host.clientWidth || host.parentElement?.clientWidth || 720));
  const svg = s('svg', { viewBox: `0 0 ${W} ${height}`, width: W, height, role: 'img' });
  host.replaceChildren(svg);
  host.classList.add('chart');
  return { svg, W, H: height };
}
function niceStep(span, target) {
  const raw = span / target; const mag = 10 ** Math.floor(Math.log10(raw)); const f = raw / mag;
  return (f < 1.5 ? 1 : f < 3.5 ? 2 : f < 7.5 ? 5 : 10) * mag;
}

/** Candles for slots [from, to]. Up candles are open, down candles are solid. */
export function candleChart(host, { rec, from, to, anchor = null, marks = null, levels = [], outcomes = [], onPick, onHover, height = 300, label = 'ANCHOR' }) {
  from = Math.max(0, from); to = Math.min(rec.n - 1, to);
  const { svg, W, H } = frame(host, height);
  const padL = 6; const padR = 70; const padT = 22; const padB = 26;
  let lo = Infinity; let hi = -Infinity;
  for (let i = from; i <= to; i++) if (rec.present[i]) { lo = Math.min(lo, rec.L[i]); hi = Math.max(hi, rec.H[i]); }
  for (const l of levels) { lo = Math.min(lo, l.price); hi = Math.max(hi, l.price); }
  if (!Number.isFinite(lo)) return;
  const padY = (hi - lo) * 0.06 || 1; lo -= padY; hi += padY;
  const n = to - from + 1; const stepX = (W - padL - padR) / n;
  const x = (i) => padL + (i - from + 0.5) * stepX;
  const y = (p) => padT + (1 - (p - lo) / (hi - lo)) * (H - padT - padB);
  const bw = Math.max(1, Math.min(11, stepX * 0.62));
  const grid = s('g');
  const st = niceStep((hi - lo) / 100, 4);
  for (let p = Math.ceil(lo / 100 / st) * st; p * 100 <= hi; p += st) {
    grid.append(s('line', { class: 'c-grid', x1: padL, x2: W - padR, y1: y(p * 100), y2: y(p * 100) }),
      s('text', { x: W - padR + 8, y: y(p * 100) + 3 }, p.toLocaleString('en-US')));
  }
  const every = [1, 2, 4, 8, 16, 32, 96].find((k) => k * stepX >= 64) || 96;
  for (let i = from; i <= to; i++) {
    const t = rec.openTime(i);
    if ((t / rec.barMs) % every !== 0) continue;
    const midnight = t % 86_400_000 === 0;
    grid.append(s('line', { class: 'c-grid', x1: x(i) - stepX / 2, x2: x(i) - stepX / 2, y1: H - padB, y2: H - padB + 4 }),
      s('text', { x: x(i) - stepX / 2, y: H - 8, 'text-anchor': 'middle' }, midnight ? dayLabel(t) : hmUTC(t)));
  }
  grid.append(s('line', { class: 'c-axis', x1: padL, x2: W - padR, y1: H - padB, y2: H - padB }));
  svg.append(grid);
  const plates = [];
  for (const l of levels) {
    const x1 = l.from !== undefined ? Math.max(padL, x(l.from) - stepX / 2) : padL;
    const text = `${l.label} ${price(l.price)}`; const tw = text.length * 6.7 + 10; const tx = Math.min(W - padR - tw, x1 + 6);
    svg.append(s('line', { class: 'c-level', x1, x2: W - padR, y1: y(l.price), y2: y(l.price) }));
    plates.push(s('rect', { class: 'c-plate', x: tx - 4, y: y(l.price) - 17, width: tw, height: 13 }), s('text', { class: 'c-level-label', x: tx, y: y(l.price) - 7 }, text));
  }
  if (anchor !== null && anchor >= from && anchor <= to) {
    svg.append(s('line', { class: 'c-anchor-guide', x1: x(anchor), x2: x(anchor), y1: padT - 6, y2: H - padB }),
      s('text', { class: 'c-anchor-label', x: x(anchor), y: 10, 'text-anchor': x(anchor) > W - 190 ? 'end' : x(anchor) < 120 ? 'start' : 'middle' }, `${label} · ${hmUTC(rec.closeTime(anchor))}Z`));
  }
  const body = s('g');
  for (let i = from; i <= to; i++) {
    if (!rec.present[i]) continue;
    const o = rec.O[i]; const c = rec.C[i];
    const g = s('g', { class: (c >= o ? 'c-up' : 'c-down') + (i === anchor ? ' c-anchor' : '') });
    g.append(s('line', { class: 'c-wick', x1: x(i), x2: x(i), y1: y(rec.H[i]), y2: y(rec.L[i]) }),
      s('rect', { class: 'c-body', x: x(i) - bw / 2, y: y(Math.max(o, c)), width: bw, height: Math.max(1, Math.abs(y(o) - y(c))) }));
    if (marks?.has(i) && i !== anchor) g.append(s('path', { class: 'c-mark', d: `M${x(i) - 3} ${H - padB - 2}L${x(i) + 3} ${H - padB - 2}L${x(i)} ${H - padB - 8}Z` }));
    body.append(g);
  }
  svg.append(body, ...plates);
  if (anchor !== null) {
    for (const o of outcomes) {
      if (o.slot < from || o.slot > to || !rec.present[o.slot]) continue;
      svg.append(s('line', { class: 'c-out-line', x1: x(anchor), y1: y(rec.C[anchor]), x2: x(o.slot), y2: y(rec.C[o.slot]) }),
        s('circle', { class: 'c-out', cx: x(o.slot), cy: y(rec.C[o.slot]), r: 3.5 }),
        s('text', { class: 'c-out-label', x: x(o.slot), y: y(rec.H[o.slot]) - 8, 'text-anchor': 'middle' }, o.label));
    }
  }
  if (onPick || onHover) {
    const cross = s('line', { class: 'c-cross', y1: padT, y2: H - padB, visibility: 'hidden' });
    const hit = s('rect', { x: padL, y: 0, width: W - padL - padR, height: H, fill: 'transparent', style: onPick ? 'cursor:crosshair' : '' });
    const at = (e) => { const r = svg.getBoundingClientRect(); return Math.max(from, Math.min(to, from + Math.floor(((e.clientX - r.left) * (W / r.width) - padL) / stepX))); };
    hit.addEventListener('mousemove', (e) => { const i = at(e); cross.setAttribute('x1', x(i)); cross.setAttribute('x2', x(i)); cross.setAttribute('visibility', 'visible'); onHover?.(i); });
    hit.addEventListener('mouseleave', () => { cross.setAttribute('visibility', 'hidden'); onHover?.(null); });
    if (onPick) hit.addEventListener('click', (e) => onPick(at(e)));
    svg.append(cross, hit);
  }
}

/** One candle as a dimensioned drawing: price levels on the left, shares of the range on the right. */
export function candleAnatomy(host, { rec, i, height = 260 }) {
  const { svg, W, H } = frame(host, height);
  if (!rec.present[i]) return;
  const o = rec.O[i]; const c = rec.C[i]; const hi = rec.H[i]; const lo = rec.L[i];
  const top = Math.max(o, c); const bot = Math.min(o, c); const range = hi - lo || 1;
  const padT = 14; const padB = 14; const narrow = W < 380;
  const y = (p) => padT + (1 - (p - lo) / range) * (H - padT - padB);
  const cx = narrow ? 126 : Math.round(W * 0.42); const bw = narrow ? 30 : 44;
  const g = s('g', { class: (c >= o ? 'c-up' : 'c-down') + ' c-anchor' });
  g.append(s('line', { class: 'c-wick', x1: cx, x2: cx, y1: y(hi), y2: y(lo) }),
    s('rect', { class: 'c-body', x: cx - bw / 2, y: y(top), width: bw, height: Math.max(1.5, y(bot) - y(top)) }));
  svg.append(g);
  // Price labels sit in their own column and never collide: each is pushed at least a line below the last.
  const lv = [['High', hi], [c >= o ? 'Close' : 'Open', top], [c >= o ? 'Open' : 'Close', bot], ['Low', lo]];
  const lx = cx - bw / 2 - 12; let last = -99;
  lv.forEach(([name, p], k) => {
    const yy = Math.min(H - 4 - (lv.length - 1 - k) * 13, Math.max(y(p) + 3, last + 13)); last = yy;
    svg.append(s('path', { class: 'c-grid', d: `M${cx - bw / 2 - 2} ${y(p)}H${lx + 4}L${lx} ${yy - 3}`, fill: 'none' }),
      s('text', { class: 'c-price', x: lx - 4, y: yy, 'text-anchor': 'end' }, `${name} ${price(p)}`));
  });
  const dims = [['Upper wick', hi, top], ['Body', top, bot], ['Lower wick', bot, lo]];
  const dx = cx + bw / 2 + 22; let lastR = -99;
  for (const [name, a, b] of dims) {
    const ya = y(a); const yb = y(b); const yy = Math.max((ya + yb) / 2 + 3, lastR + 13); lastR = yy;
    svg.append(s('path', { class: 'c-dim', d: `M${dx - 4} ${ya}H${dx + 4}M${dx} ${ya}V${yb}M${dx - 4} ${yb}H${dx + 4}` }),
      s('text', { class: 'c-dim-label', x: dx + 12, y: yy }, `${name} ${(((a - b) / range) * 100).toFixed(1)}%`));
  }
}

/** Every observed outcome as one tick on a shared axis, with the median marked. */
export function stripPlot(host, { values, median, baseline = null, height = 58 }) {
  const { svg, W, H } = frame(host, height);
  if (!values.length) { svg.append(s('text', { x: 0, y: H / 2 }, 'NO OBSERVED OUTCOMES')); return; }
  const q = (f) => values[Math.min(values.length - 1, Math.max(0, Math.round(f * (values.length - 1))))];
  const m = Math.max(Math.abs(q(0.02)), Math.abs(q(0.98)), 0.0005) * 1.15;
  const padX = 4; const x = (v) => padX + ((Math.max(-m, Math.min(m, v)) + m) / (2 * m)) * (W - 2 * padX);
  const y0 = 16; const y1 = H - 16;
  svg.append(s('line', { class: 'c-axis', x1: padX, x2: W - padX, y1, y2: y1 }), s('line', { class: 'c-zero', x1: x(0), x2: x(0), y1: y0 - 6, y2: y1 }));
  const ticks = s('g', { class: 'c-ticks', style: `opacity:${Math.max(0.16, Math.min(0.8, 60 / values.length))}` });
  for (const v of values) ticks.append(s('line', { x1: x(v), x2: x(v), y1: y0, y2: y1 }));
  svg.append(ticks);
  if (baseline !== null) svg.append(s('path', { class: 'c-base', d: `M${x(baseline) - 4} ${y1 + 7}L${x(baseline) + 4} ${y1 + 7}L${x(baseline)} ${y1 + 1}Z` }));
  if (median !== null) svg.append(s('line', { class: 'c-median', x1: x(median), x2: x(median), y1: y0 - 6, y2: y1 }));
  svg.append(s('text', { x: padX, y: H - 2 }, pct(-m, 1)), s('text', { x: W - padX, y: H - 2, 'text-anchor': 'end' }, pct(m, 1)),
    s('text', { x: x(0), y: H - 2, 'text-anchor': 'middle' }, '0'),
    median !== null && s('text', { class: 'c-median-label', x: x(median), y: 8, 'text-anchor': x(median) > W - 90 ? 'end' : x(median) < 90 ? 'start' : 'middle' }, `MEDIAN ${pct(median)}`));
}

/** Observed outcomes as one smooth distribution, with the median and an optional baseline marked. */
export function distPlot(host, { values, median, baseline = null, height = 66 }) {
  const { svg, W, H } = frame(host, height);
  if (!values.length) { svg.append(s('text', { x: 0, y: H / 2 }, 'NO OBSERVED OUTCOMES')); return; }
  const q = (f) => values[Math.min(values.length - 1, Math.max(0, Math.round(f * (values.length - 1))))];
  const m = Math.max(Math.abs(q(0.02)), Math.abs(q(0.98)), 0.0005) * 1.15;
  const top = 6; const base = H - 16; const bins = Math.max(14, Math.min(40, Math.round(W / 8)));
  const x = (v) => ((Math.max(-m, Math.min(m, v)) + m) / (2 * m)) * W;
  let counts = new Array(bins).fill(0);
  for (const v of values) counts[Math.min(bins - 1, Math.max(0, Math.floor(((Math.max(-m, Math.min(m, v)) + m) / (2 * m)) * bins)))]++;
  for (let pass = 0; pass < 2; pass++) counts = counts.map((c, i) => ((counts[i - 1] ?? c) + 2 * c + (counts[i + 1] ?? c)) / 4);
  const peak = Math.max(...counts) || 1; const y = (c) => base - (c / peak) * (base - top);
  const pts = counts.map((c, i) => [((i + 0.5) / bins) * W, y(c)]);
  let d = `M0 ${y(counts[0]).toFixed(1)}`;
  for (let i = 0; i < pts.length; i++) { const [px, py] = pts[i]; const [nx, ny] = pts[i + 1] || [W, py]; d += ` Q${px.toFixed(1)} ${py.toFixed(1)} ${((px + nx) / 2).toFixed(1)} ${((py + ny) / 2).toFixed(1)}`; }
  svg.append(s('path', { class: 'd-area', d: `${d} L${W} ${base} L0 ${base} Z` }), s('path', { class: 'd-line', d }),
    s('line', { class: 'c-axis', x1: 0, x2: W, y1: base, y2: base }), s('line', { class: 'd-zero', x1: x(0), x2: x(0), y1: top, y2: base }));
  if (baseline !== null) svg.append(s('line', { class: 'd-base', x1: x(baseline), x2: x(baseline), y1: top, y2: base }));
  if (median !== null) svg.append(s('line', { class: 'd-median', x1: x(median), x2: x(median), y1: top, y2: base }));
  svg.append(s('text', { x: 0, y: H - 3 }, pct(-m, 1)), s('text', { x: W, y: H - 3, 'text-anchor': 'end' }, pct(m, 1)), s('text', { x: x(0), y: H - 3, 'text-anchor': 'middle' }, '0'));
}

/** A share with its interval on one rail: the estimate, the interval around it, and a baseline share. */
export function rateRail(host, { p, lo, hi, base = null, height = 30 }) {
  const { svg, W, H } = frame(host, height);
  const span = Math.max(0.12, ...[p, lo, hi, base].filter((v) => v !== null).map((v) => Math.abs(v - 0.5))) + 0.04;
  const x = (v) => ((v - (0.5 - span)) / (2 * span)) * W; const y = 9; const t = (v) => Math.round(v * 100) + '%';
  svg.append(s('line', { class: 'c-axis', x1: 0, x2: W, y1: y, y2: y }), s('line', { class: 'd-zero', x1: x(0.5), x2: x(0.5), y1: y - 7, y2: y + 7 }),
    s('line', { class: 'r-ci', x1: x(lo), x2: x(hi), y1: y, y2: y }));
  if (base !== null) svg.append(s('line', { class: 'd-base', x1: x(base), x2: x(base), y1: y - 7, y2: y + 7 }));
  svg.append(s('line', { class: 'd-median', x1: x(p), x2: x(p), y1: y - 7, y2: y + 7 }),
    s('text', { x: 0, y: H - 2 }, t(0.5 - span)), s('text', { x: W, y: H - 2, 'text-anchor': 'end' }, t(0.5 + span)), s('text', { x: x(0.5), y: H - 2, 'text-anchor': 'middle' }, '50%'));
}

/** Close-to-close paths after each matched close, anchored at zero, with the median path. */
export function pathFan(host, { rec, slots, steps = 16, height = 220, marks = [4, 16] }) {
  const { svg, W, H } = frame(host, height);
  const padL = 4; const padR = 58; const padT = 14; const padB = 24;
  const pick = slots.length > 500 ? slots.filter((_, k) => k % Math.ceil(slots.length / 500) === 0) : slots;
  const paths = []; const cols = Array.from({ length: steps + 1 }, () => []);
  for (const i of pick) {
    const p = [];
    for (let k = 0; k <= steps; k++) { const j = i + k; if (j >= rec.n || !rec.present[j]) break; const v = (rec.C[j] - rec.C[i]) / rec.C[i]; p.push(v); cols[k].push(v); }
    if (p.length > 1) paths.push(p);
  }
  if (!paths.length) { svg.append(s('text', { x: 0, y: H / 2 }, 'NO RECORDED PATHS')); return; }
  const all = cols.flat().sort((a, b) => a - b);
  const q = (f) => all[Math.round(f * (all.length - 1))];
  const m = Math.max(Math.abs(q(0.02)), Math.abs(q(0.98)), 0.001) * 1.1;
  const x = (k) => padL + (k / steps) * (W - padL - padR);
  const y = (v) => padT + (1 - (Math.max(-m, Math.min(m, v)) + m) / (2 * m)) * (H - padT - padB);
  svg.append(s('line', { class: 'c-axis', x1: padL, x2: W - padR, y1: y(0), y2: y(0) }),
    s('text', { x: W - padR + 8, y: y(0) + 3 }, '0'), s('text', { x: W - padR + 8, y: y(m) + 8 }, pct(m, 1)), s('text', { x: W - padR + 8, y: y(-m) }, pct(-m, 1)));
  for (const k of marks) if (k <= steps) svg.append(s('line', { class: 'c-grid', x1: x(k), x2: x(k), y1: padT, y2: H - padB }), s('text', { x: x(k), y: H - 8, 'text-anchor': 'middle' }, `+${k * 15 >= 60 ? k / 4 + 'H' : k * 15 + 'M'}`));
  svg.append(s('text', { x: padL, y: H - 8 }, 'CLOSE'));
  const g = s('g', { class: 'c-fan', style: `opacity:${Math.max(0.07, Math.min(0.5, 14 / paths.length))}` });
  for (const p of paths) g.append(s('polyline', { points: p.map((v, k) => `${x(k).toFixed(1)},${y(v).toFixed(1)}`).join(' ') }));
  const med = cols.filter((c) => c.length).map((c) => { const t = c.slice().sort((a, b) => a - b); const h = t.length >> 1; return t.length % 2 ? t[h] : (t[h - 1] + t[h]) / 2; });
  svg.append(g, s('polyline', { class: 'c-median', points: med.map((v, k) => `${x(k).toFixed(1)},${y(v).toFixed(1)}`).join(' ') }),
    s('text', { class: 'c-median-label', x: W - padR + 8, y: Math.max(padT + 8, Math.min(H - padB - 4, y(med[med.length - 1]) - 6)) }, `MED ${pct(med[med.length - 1])}`));
}

/** The whole recording as one line, with matches ticked above it and the visible window framed. */
export function tapeOverview(host, { rec, marks = [], window: win = null, selected = null, onSeek, height = 92 }) {
  const { svg, W, H } = frame(host, height);
  const top = 16; const bot = H - 18;
  let lo = Infinity; let hi = -Infinity;
  for (let i = 0; i < rec.n; i++) if (rec.present[i]) { lo = Math.min(lo, rec.L[i]); hi = Math.max(hi, rec.H[i]); }
  const x = (i) => (i / (rec.n - 1)) * W; const y = (p) => top + (1 - (p - lo) / (hi - lo)) * (bot - top);
  const per = Math.max(1, Math.floor(rec.n / W)); let d = '';
  for (let i = 0; i < rec.n; i += per) if (rec.present[i]) d += `${d ? 'L' : 'M'}${x(i).toFixed(1)} ${y(rec.C[i]).toFixed(1)}`;
  svg.append(s('line', { class: 'c-axis', x1: 0, x2: W, y1: bot, y2: bot }));
  let month = -1;
  for (let i = 0; i < rec.n; i += 96) { const dt = new Date(rec.openTime(i)); if (dt.getUTCMonth() !== month) { month = dt.getUTCMonth(); svg.append(s('line', { class: 'c-grid', x1: x(i), x2: x(i), y1: top, y2: bot + 4 }), s('text', { x: x(i) + 4, y: H - 4 }, MONTH[month])); } }
  svg.append(s('path', { class: 'c-line', d }));
  const g = s('g', { class: 'c-ticks-gold', style: `opacity:${Math.max(0.35, Math.min(1, 160 / (marks.length || 1)))}` });
  for (const i of marks) g.append(s('line', { x1: x(i), x2: x(i), y1: 2, y2: 12 }));
  svg.append(g);
  if (win) svg.append(s('rect', { class: 'c-window', x: x(win[0]), y: top - 2, width: Math.max(3, x(win[1]) - x(win[0])), height: bot - top + 4 }));
  if (selected !== null) svg.append(s('line', { class: 'c-median', x1: x(selected), x2: x(selected), y1: 0, y2: bot }));
  if (onSeek) {
    // Handlers live on the host so a redraw during a drag keeps the gesture.
    const at = (e) => { const r = host.getBoundingClientRect(); return Math.max(0, Math.min(rec.n - 1, Math.round(((e.clientX - r.left) / r.width) * (rec.n - 1)))); };
    host.style.cursor = 'ew-resize'; host.style.touchAction = 'none';
    host.onpointerdown = (e) => { host.dataset.down = '1'; host.setPointerCapture(e.pointerId); onSeek(at(e)); };
    host.onpointermove = (e) => { if (host.dataset.down) onSeek(at(e)); };
    host.onpointerup = host.onpointercancel = () => { delete host.dataset.down; };
  }
}

export { dayLabel, dateUTC };
