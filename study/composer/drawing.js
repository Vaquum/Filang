// Portable state for the local edition of Composer 133e301.
export const COMPOSER_REVISION = '133e3017ba9143f7dc255df7218ff7bfe46d9d06';
export const DEFAULT_ANCHOR = Date.parse('2025-03-28T19:30:00Z');
const MAX_PACKET_LENGTH = 96_000;
const object = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const integer = (value, min, max) => Number.isInteger(value) && value >= min && value <= max;
function requireValue(ok, message) {
  if (!ok) throw new Error(message);
}
function barOHLC(b) {
  const [low, bottom, top, high] = b.v;
  return b.d === 'u' ? [bottom, high, low, top] : [top, high, low, bottom];
}
export function drawingG1(packet) {
  const sorted = [...new Set(packet.bars.flatMap((b) => b.v))].sort((a, b) => a - b);
  const rows = packet.bars.map((b) => {
    const rank = b.v.map((x) => sorted.indexOf(x));
    if (packet.oriented) rank.push(b.v[1] === b.v[2] ? 'z' : b.d);
    return rank.join(',');
  });
  return 'g1:' + (packet.oriented ? 'o:' : 'u:') + rows.join(';');
}

export function decodeDrawing(text, expectedG1) {
  requireValue(
    typeof text === 'string' && text.length > 0 && text.length <= MAX_PACKET_LENGTH,
    'Drawing packet has an invalid size.',
  );
  const p = JSON.parse(text);
  requireValue(
    object(p) && p.version === 1 && p.revision === COMPOSER_REVISION,
    'Unsupported Composer drawing version.',
  );
  requireValue(
    typeof p.oriented === 'boolean' && Array.isArray(p.bars) && integer(p.bars.length, 1, 20),
    'Drawing needs 1–20 bars.',
  );
  requireValue(p.coordinates === undefined || p.coordinates === 'ordinal', 'Invalid drawing coordinate source.');
  let lastClose;
  for (const b of p.bars) {
    requireValue(
      object(b) &&
        ['u', 'd'].includes(b.d) &&
        Array.isArray(b.v) &&
        b.v.length === 4 &&
        b.v.every((x, i) => Number.isFinite(x) && Math.abs(x) <= 1e12 && (!i || x >= b.v[i - 1])),
      'Invalid drawing price or direction.',
    );
    const [open, , , close] = barOHLC(b);
    requireValue(
      lastClose === undefined || lastClose === open,
      'The next drawn bar must open at the previous close.',
    );
    lastClose = close;
  }
  requireValue(
    integer(p.skeleton, 0, p.bars.length) && integer(p.stretch, 0, p.bars.length === 1 ? 0 : 4),
    'Invalid skeleton or stretch.',
  );
  requireValue(
    Array.isArray(p.pins) && p.pins.length <= p.bars.length * (4 * p.bars.length + 1) * 2,
    'Invalid drawing pins.',
  );
  const point = (x) =>
    object(x) && integer(x.bar, 0, p.bars.length - 1) && ['L', 'B', 'T', 'H'].includes(x.part);
  for (const pin of p.pins) {
    requireValue(
      object(pin) &&
        (pin.color === true ? integer(pin.bar, 0, p.bars.length - 1) : point(pin.a) && point(pin.b)),
      'Invalid drawing pin.',
    );
  }
  requireValue(
    object(p.next) &&
      [-1, 0, 1].includes(p.next.dir) &&
      ['any', 'bps', 'atr'].includes(p.next.measure) &&
      Number.isFinite(p.next.bps) &&
      p.next.bps > 0 &&
      Number.isFinite(p.next.atr) &&
      p.next.atr > 0,
    'Invalid continuation settings.',
  );
  requireValue([12, 24, 48].includes(p.limit), 'Invalid number of closest windows.');
  if (expectedG1 !== undefined && expectedG1 !== null)
    requireValue(drawingG1(p) === expectedG1, 'The drawing and exact G1 disagree.');
  return p;
}
export function encodeDrawing(packet) {
  const text = JSON.stringify(packet);
  decodeDrawing(text);
  return text;
}
