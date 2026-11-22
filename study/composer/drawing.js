// Portable state for the local edition of Composer 133e301.
import { parseG1 } from '../src/g1.js';

export const COMPOSER_REVISION = '133e3017ba9143f7dc255df7218ff7bfe46d9d06';
// A drawing with a dimension switched on is written in a later revision of the format: the same packet with one more
// field, `dimensions`, the dimension parts of its g1 code in order (["volume:0,1", "delta:0,2/1"]). A packet in the
// first revision has no such field and means every dimension off. The revision names the Composer commit the format
// was cut from, as Composer's bench/model.js has it.
export const DIMENSIONS_REVISION = 'bd6a0ba32e18548b641267418491bfb5f011a274';
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
  const parts = packet.dimensions && packet.dimensions.length ? '|' + packet.dimensions.join('|') : '';
  return 'g1:' + (packet.oriented ? 'o:' : 'u:') + rows.join(';') + parts;
}

export function decodeDrawing(text, expectedG1) {
  requireValue(
    typeof text === 'string' && text.length > 0 && text.length <= MAX_PACKET_LENGTH,
    'Drawing packet has an invalid size.',
  );
  const p = JSON.parse(text);
  requireValue(
    object(p) && p.version === 1 && (p.revision === COMPOSER_REVISION || p.revision === DIMENSIONS_REVISION),
    'Unsupported Composer drawing version.',
  );
  requireValue(
    p.dimensions === undefined ||
      (p.revision === DIMENSIONS_REVISION &&
        Array.isArray(p.dimensions) &&
        p.dimensions.length <= 5 &&
        p.dimensions.every((part) => typeof part === 'string' && part.length <= 200)),
    'Invalid drawing dimensions.',
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
  // The dimension parts are read as strictly as the g1 code they belong to: names, order, one rank a bar, dense ranks.
  if (p.dimensions && p.dimensions.length) parseG1(drawingG1(p));
  if (expectedG1 !== undefined && expectedG1 !== null)
    requireValue(drawingG1(p) === expectedG1, 'The drawing and exact G1 disagree.');
  return p;
}
export function encodeDrawing(packet) {
  const text = JSON.stringify(packet);
  decodeDrawing(text);
  return text;
}

/** Manual pins as fixed-lag rules. Drawn distances supply only order and ties. */
export function pinnedExpression(packet) {
  const {bars, pins, oriented} = packet;
  const point = ({bar,part}) => {
    if (part === 'L' || part === 'H') return part === 'L' ? 'low' : 'high';
    const candle = bars[bar];
    if (!oriented) return part === 'B' ? 'body_low' : 'body_high';
    const rising = candle.d === 'u' || candle.v[1] === candle.v[2];
    return (part === 'T') === rising ? 'close' : 'open';
  };
  const call = (bar, name) => 'price(' + name + ', bars_ago: ' + (bars.length - 1 - bar) + ')';
  const compare = (left, r, right) => 'candle_relation(' + left + ', is: ' +
    (r < 0 ? 'below' : r > 0 ? 'above' : 'equal') + ', right: ' + right + ')';
  const coordinate = ({bar,part}) => bars[bar].v['LBTH'.indexOf(part)];
  const rules = new Set();
  for (const pin of pins) {
    if (pin.color) {
      if (!oriented) continue;
      const {bar} = pin, b = bars[bar];
      rules.add(compare(call(bar,'close'), b.v[1] === b.v[2] ? 0 : b.d === 'u' ? 1 : -1, call(bar,'open')));
    } else if (pin.a.bar !== pin.b.bar || pin.a.part !== pin.b.part) {
      rules.add(compare(call(pin.a.bar,point(pin.a)), coordinate(pin.a)-coordinate(pin.b), call(pin.b.bar,point(pin.b))));
    }
  }
  if (!rules.size) return null;
  const event = [...rules].join(' and ');
  return bars.length === 1 ? event : 'candle_window(' + event + ', bars: ' + bars.length + ')';
}
