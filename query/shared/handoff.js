// The shape hand-off between this bench and the Composer bench.
// One interchange, the engine's own: its drawing packet, under the parameter names the study page already uses
// (drawing, g1, pin-relations). The engine reads every packet and every g1. Only the shape and what is held on it are
// carried. Each bench counts on its own history, so a count never crosses.
import { decodeDrawing, drawingG1, pinnedExpression, drawingRevision, shapeOf } from '/shared/filang.js';
import { make, clauseText } from '/shared/vocab.js';

export { decodeDrawing, drawingG1, pinnedExpression };

const blank = (bars, extra = {}) => ({ version: 1, revision: drawingRevision(), oriented: true, bars, pins: [], skeleton: 0, stretch: 0,
  next: { dir: 0, measure: 'any', bps: 10, atr: 1 }, limit: 12, ...extra });

/**
 * What a link carried in. Null when it names no drawing; { error } when it names one that cannot be read;
 * otherwise the packet (null when only a g1 came), its g1, and whether the question is the held relations.
 */
export function readLink(search) {
  const p = new URLSearchParams(search);
  if (!p.has('drawing') && !p.has('g1')) return null;
  try {
    if (p.has('drawing')) {
      const packet = decodeDrawing(p.get('drawing'), p.get('g1') ?? undefined);
      return { packet, g1: drawingG1(packet), held: p.has('pin-relations') && pinnedExpression(packet) !== null };
    }
    shapeOf(p.get('g1'));
    return { packet: null, g1: p.get('g1'), held: false };
  } catch (e) { return { error: String(e.message || e) }; }
}

/**
 * A drawing for a g1 that came without one: every endpoint at even rank spacing, as the bundled bridge rebuilds it.
 * Null when it cannot be drawn: no directions, an opening gap, or more than 20 bars.
 */
export function packetFromG1(code) {
  try {
    const shape = shapeOf(code);
    if (!shape.directions || shape.ranks.length > 20) return null;
    const bars = shape.ranks.map((ranks, k) => ({ v: ranks.map((r) => (shape.rank_count === 1 ? 50 : 15 + (70 * r) / (shape.rank_count - 1))), d: shape.directions[k] === 'd' ? 'd' : 'u' }));
    const packet = blank(bars, { coordinates: 'ordinal' });
    return decodeDrawing(JSON.stringify(packet), code);   // refuses an opening gap: a drawn bar opens at the previous close
  } catch { return null; }
}

/**
 * The n recorded candles ending at slot i as a drawing with nothing held, in USDT. A drawing is a chain, and the
 * window is read as one, exactly as chained_g1 reads it: the first bar as recorded, each later bar opening at the
 * close before it, with its low and high reaching that open. So the drawing's g1 is the window's chained code, and
 * the window is a match of the shape drawn from it. Returns { packet, joined, far }: how many recorded opens differ
 * from the close before them, and the largest such difference in USDT. Or { why } when a candle is missing.
 */
export function casePacket(rec, i, n) {
  const start = i - n + 1;
  if (start < 0) return { why: 'the recording begins inside these candles' };
  for (let k = start; k <= i; k++) if (!rec.present[k]) return { why: 'a candle is missing from the recording' };
  const bars = []; let joined = 0; let far = 0; let prev = null;
  for (let k = start; k <= i; k++) {
    const o = prev ?? rec.O[k]; const c = rec.C[k]; const lo = Math.min(o, c); const hi = Math.max(o, c);
    if (prev !== null && rec.O[k] !== prev) { joined++; far = Math.max(far, Math.abs(rec.O[k] - prev)); }
    bars.push({ v: [Math.min(rec.L[k], lo), lo, hi, Math.max(rec.H[k], hi)].map((x) => x / 100), d: c > o ? 'u' : c < o ? 'd' : rec.C[k] >= rec.O[k] ? 'u' : 'd' });
    prev = c;
  }
  try { return { packet: decodeDrawing(JSON.stringify(blank(bars))), joined, far: far / 100 }; } catch (e) { return { why: String(e.message || e).replace(/\.$/, '').toLowerCase() }; }
}

/** The link that opens a packet in the Composer bench. */
export const composerLink = (base, packet) => `${base}?drawing=${encodeURIComponent(JSON.stringify(packet))}`;

/** The relations a packet holds, in words: one per fixed-candle rule the engine reads, in the order it reads them. */
export function relationsOf(packet) {
  const { bars, pins, oriented } = packet; const out = new Map();   // keyed as the engine's rule is, so the count is its count
  const name = ({ bar, part }) => {
    if (part === 'L' || part === 'H') return part === 'L' ? 'low' : 'high';
    if (!oriented) return part === 'B' ? 'body low' : 'body high';
    const rising = bars[bar].d === 'u' || bars[bar].v[1] === bars[bar].v[2];
    return (part === 'T') === rising ? 'close' : 'open';
  };
  const at = ({ bar, part }) => bars[bar].v['LBTH'.indexOf(part)];
  const side = (d) => (d < 0 ? 'below' : d > 0 ? 'above' : 'level with');
  for (const pin of pins) {
    if (pin.color) {
      if (!oriented) continue;
      const b = bars[pin.bar]; const d = b.v[1] === b.v[2] ? 0 : b.d === 'u' ? 1 : -1;
      const key = `${pin.bar}.close|${d}|${pin.bar}.open`;
      if (!out.has(key)) out.set(key, `bar ${pin.bar + 1} closes ${d ? side(d) : 'at'} its open`);
    } else if (pin.a.bar !== pin.b.bar || pin.a.part !== pin.b.part) {
      const d = Math.sign(at(pin.a) - at(pin.b)); const key = `${pin.a.bar}.${name(pin.a)}|${d}|${pin.b.bar}.${name(pin.b)}`;
      if (!out.has(key)) out.set(key, `bar ${pin.a.bar + 1} ${name(pin.a)} ${side(d)} bar ${pin.b.bar + 1} ${name(pin.b)}`);
    }
  }
  return [...out.values()];
}

/**
 * Put a packet back on the find it belongs to: a question read from text knows the expression, not the drawing.
 * Usually the drawing is one item of the find. The relations held on a one-bar drawing are a bare conjunction,
 * though, which text gives back as several items joined by "and": those are gathered into the one drawn shape again.
 */
export function attach(model, packet) {
  const g1 = drawingG1(packet); const items = model.find.items;
  // the three ways a drawing is asked: as a chain, with its opens as recorded, and as the relations held on it
  for (const form of [{ held: false, recorded: false }, { held: false, recorded: true }, { held: true, recorded: false }]) {
    const { held } = form;
    if (held && !pinnedExpression(packet)) continue;
    const plain = make('drawing', { g1, packet, ...form }); const text = clauseText(plain);
    let done = false;
    items.forEach((c, i) => {
      const cand = c.not ? Object.assign(make('drawing', { g1, packet, ...form }), { not: true }) : plain;
      if (clauseText(cand) === clauseText(c)) { items[i] = cand; done = true; }
    });
    if (done || !held || model.find.join !== 'and') continue;
    for (let i = 0; i < items.length; i++) {
      for (let j = i + 1; j < items.length; j++) {
        const run = items.slice(i, j + 1);
        if (run.some((c) => c.not) || run.map(clauseText).join(' and ') !== text) continue;
        items.splice(i, run.length, plain); return;
      }
    }
  }
}
