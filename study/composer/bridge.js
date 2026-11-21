import { parseRecording, sha256Hex } from '../src/data.js';
import { parseG1, g1FromRecording } from '../src/g1.js';
import { COMPOSER_REVISION, DEFAULT_ANCHOR, decodeDrawing, encodeDrawing, drawingG1, pinnedExpression } from './drawing.js';

const $ = (id) => document.getElementById(id);
const CLOSE_FORMAT = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/New_York',
  dateStyle: 'medium',
  timeStyle: 'short',
});
const inputTime = (ms) => new Date(ms).toISOString().slice(0, 16);

async function recording() {
  const fetchOk = async (name) => {
    const response = await fetch('../' + name);
    if (!response.ok) throw new Error('Could not load ' + name);
    return response;
  };
  const [bytes, source] = await Promise.all([
    fetchOk('recorded-bars.csv').then((r) => r.arrayBuffer()),
    fetchOk('data-provenance.json').then((r) => r.json()),
  ]);
  const digest = sha256Hex(new Uint8Array(bytes));
  if (digest !== source.csv_sha256) throw new Error('Recording differs from its pinned source.');
  return parseRecording(new TextDecoder().decode(bytes), source, digest);
}
function recordedDrawing(rec, anchor) {
  const i = rec.slotClosingAt(anchor);
  if (i === null || !rec.has(i))
    throw new Error('Select a recorded close on the 15-minute grid between January and May 2025.');
  const [o, h, l, c] = [rec.O[i], rec.H[i], rec.L[i], rec.C[i]];
  // The editor uses free canvas coordinates. One affine transform preserves every relative distance and tie.
  const y = (x) => (h === l ? 50 : 15 + (70 * (x - l)) / (h - l));
  return {
    version: 1,
    revision: COMPOSER_REVISION,
    bars: [{ v: [l, Math.min(o, c), Math.max(o, c), h].map(y), d: c >= o ? 'u' : 'd' }],
    oriented: true,
    pins: [],
    skeleton: 0,
    stretch: 0,
    next: { dir: 0, measure: 'any', bps: 10, atr: 1 },
    limit: 12,
  };
}
export async function attachComposer(api) {
  const params = new URLSearchParams(location.search);
  function destination() {
    const dest = new URL('../', location.href);
    if (params.has('question')) dest.searchParams.set('question', params.get('question'));
    const fragment = new URLSearchParams(location.hash.slice(1));
    if (fragment.has('definitions'))
      dest.hash = new URLSearchParams({ definitions: fragment.get('definitions') }).toString();
    return dest;
  }
  $('send-named').addEventListener('click', () => {
    const entry = globalThis.CandlePatterns.resolve($('send-named').dataset.pattern);
    if (!entry) return;
    const dest = destination();
    dest.searchParams.set('pattern', entry.id);
    location.assign(dest.href);
  });
  const rec = await recording();
  const input = $('sample-time'),
    status = $('sample-status'),
    send = $('send-g1'), pins = $('send-pins');
  let sample = null,
    ordinal = null,
    rankDrawing = null;
  function preview(code, pattern, reason) {
    ordinal = code;
    pins.hidden = true;
    pins.disabled = true;
    document.body.classList.add('ordinal-only');
    $('ordinal-preview').hidden = false;
    $('ordinal-code').textContent = code;
    $('ordinal-why').textContent = reason;
    const body = $('ordinal-preview').querySelector('tbody');
    body.replaceChildren(
      ...pattern.rows.map((row, i) => {
        const tr = document.createElement('tr');
        for (const x of [
          i + 1,
          ...row.ranks,
          pattern.oriented ? { u: 'up', d: 'down', z: 'flat' }[row.direction] : 'unspecified',
        ]) {
          const cell = document.createElement('td');
          cell.textContent = String(x);
          tr.append(cell);
        }
        return tr;
      }),
    );
    $('drawing-label').textContent = 'Exact endpoint ranks';
    send.disabled = false;
  }
  input.min = inputTime(rec.firstClose);
  input.max = inputTime(rec.lastClose);
  const read = () => ({ version: 1, revision: COMPOSER_REVISION, ...api.read() });
  const sourceClose = (p) =>
    sample && JSON.stringify(sample.bars) === JSON.stringify(p.bars) ? sample.anchor : null;
  function show() {
    if (ordinal) return;
    const p = read();
    pins.disabled = !pinnedExpression(p);
    pins.hidden = pins.disabled;
    const anchor = sourceClose(p);
    document.body.classList.toggle('ordinal-distances', JSON.stringify(p.bars) === rankDrawing);
    const label = anchor
      ? CLOSE_FORMAT.format(anchor) + ' New York'
      : JSON.stringify(p.bars) === rankDrawing
        ? 'G1 drawing · evenly spaced ranks'
        : 'Custom drawing';
    $('drawing-label').textContent = label;
    $('send-g1').title = 'Use ' + drawingG1(p) + ' as an exact detector';
    $('sample-prev').disabled = !input.value || input.value <= input.min;
    $('sample-next').disabled = !input.value || input.value >= input.max;
  }
  function choose(anchor) {
    const p = recordedDrawing(rec, anchor);
    ordinal = null;
    rankDrawing = null;
    document.body.classList.remove('ordinal-only');
    $('ordinal-preview').hidden = true;
    sample = { anchor, bars: p.bars };
    input.value = inputTime(anchor);
    api.apply(p);
    const i = rec.slotClosingAt(anchor),
      prices = rec.ohlcText(i);
    status.textContent = [
      'Open ' + prices.open,
      'High ' + prices.high,
      'Low ' + prices.low,
      'Close ' + prices.close,
    ].join(' · ');
    send.disabled = false;
    show();
  }
  function change(anchor) {
    try {
      choose(anchor);
    } catch (e) {
      status.textContent = e.message;
    }
  }
  $('sample-form').addEventListener('submit', (e) => {
    e.preventDefault();
    change(Date.parse(input.value + 'Z'));
  });
  for (const [id, step] of [
    ['sample-prev', -1],
    ['sample-next', 1],
  ]) {
    $(id).addEventListener('click', () => change(Date.parse(input.value + 'Z') + step * rec.barMs));
  }
  function transfer(usePins) {
    try {
      const dest = destination();
      if (ordinal) {
        dest.searchParams.set('g1', ordinal);
        location.assign(dest.href);
        return;
      }
      const p = read(),
        code = api.g1();
      if (JSON.stringify(p.bars) === rankDrawing) p.coordinates = 'ordinal';
      const serialized = encodeDrawing(p);
      decodeDrawing(serialized, code);
      if (usePins) {
        if (!pinnedExpression(p)) throw Error('Add at least one active pin to the drawing.');
        dest.searchParams.set('pin-relations','1');
      }
      dest.searchParams.set('g1', code);
      dest.searchParams.set('drawing', serialized);
      const anchor = sourceClose(p);
      if (anchor !== null) dest.searchParams.set('anchor', String(anchor));
      location.assign(dest.href);
    } catch (e) {
      status.textContent = e.message;
    }
  }
  send.addEventListener('click', () => transfer(false));
  pins.addEventListener('click', () => transfer(true));
  api.onChange(show);
  input.value = inputTime(DEFAULT_ANCHOR);
  try {
    if (params.has('drawing')) {
      const p = decodeDrawing(params.get('drawing'), params.get('g1'));
      if (p.coordinates === 'ordinal') rankDrawing = JSON.stringify(p.bars);
      if (params.has('anchor')) {
        const anchor = Number(params.get('anchor')),
          original = recordedDrawing(rec, anchor);
        if (JSON.stringify(original.bars) !== JSON.stringify(p.bars))
          throw new Error('Source candle and saved drawing disagree.');
        sample = { anchor, bars: original.bars };
        input.value = inputTime(anchor);
      }
      api.apply(p);
      send.disabled = false;
      show();
      status.textContent = 'Restored drawing and exploration settings.';
    } else if (params.has('g1')) {
      const code = params.get('g1'),
        pattern = parseG1(code);
      if (params.has('anchor')) {
        const anchor = Number(params.get('anchor'));
        if (g1FromRecording(rec, rec.slotClosingAt(anchor), pattern.rows.length, pattern.oriented) !== code)
          throw new Error('G1 differs from its recorded candle window.');
        if (pattern.rows.length === 1) {
          choose(anchor);
          const p = read();
          p.oriented = pattern.oriented;
          api.apply(p);
          show();
          return;
        }
      }
      const p = recordedDrawing(rec, DEFAULT_ANCHOR);
      p.bars = pattern.rows.map((row) => ({
        d: row.direction === 'd' ? 'd' : 'u',
        v: row.ranks.map((r) => (pattern.rankCount === 1 ? 50 : 15 + (70 * r) / (pattern.rankCount - 1))),
      }));
      const chained = p.bars.every(
        (b, i) =>
          i === 0 ||
          (b.d === 'd' ? b.v[2] : b.v[1]) ===
            (p.bars[i - 1].d === 'd' ? p.bars[i - 1].v[1] : p.bars[i - 1].v[2]),
      );
      if (pattern.oriented && chained && p.bars.length <= 20) {
        rankDrawing = JSON.stringify(p.bars);
        api.apply(p);
        send.disabled = false;
        show();
        status.textContent =
          'G1 supplies global order and direction. Drawing distances begin at equal rank spacing.';
      } else {
        const reason = !pattern.oriented
          ? 'This code omits candle directions. The table preserves its supplied geometry.'
          : p.bars.length > 20
            ? 'The supplied pattern exceeds the editor’s 20-bar drawing limit.'
            : 'This pattern has an opening gap. Composer drawings join each new open to the preceding close.';
        preview(code, pattern, reason);
        status.textContent = 'Choose a recorded close to start another drawing.';
      }
    } else choose(params.has('anchor') ? Number(params.get('anchor')) : DEFAULT_ANCHOR);
  } catch (e) {
    status.textContent =
      'Drawing could not be restored. ' + e.message + ' Choose a recorded close to continue.';
    send.disabled = true;
  }
}
