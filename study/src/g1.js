// Filang g1 stores global endpoint ranks in the drawing's supplied order.
// The query contract uses oldest first and anchors at the last candle's close.

// The axes a pattern can switch on beside price, in the order their parts are written (docs/G1_DIMENSIONS.md).
// Each has one value per candle and is ranked only against itself. One with a reference point also ranks every
// candle against zero, which is what tells net buying from net selling.
export const DIMENSIONS = Object.freeze([
  Object.freeze({ name: 'volume', reference: false }),
  Object.freeze({ name: 'trades', reference: false }),
  Object.freeze({ name: 'delta', reference: true }),
  Object.freeze({ name: 'size', reference: false }),
  Object.freeze({ name: 'imbalance', reference: true }),
]);
const DIMENSION_AT = new Map(DIMENSIONS.map((d, k) => [d.name, k]));

function parseDimensions(parts, candles) {
  const dims = [];
  let last = -1;
  for (const part of parts) {
    const m = /^([a-z]+):([0-9,]*)(?:\/([0-9]*))?$/.exec(part);
    if (!m || !DIMENSION_AT.has(m[1])) throw new Error('a G1 dimension part is volume, trades, delta, size or imbalance, then a colon and one rank for each candle');
    const at = DIMENSION_AT.get(m[1]);
    if (at <= last) throw new Error('G1 dimension parts follow the order volume, trades, delta, size, imbalance, each at most once');
    last = at;
    const { name, reference } = DIMENSIONS[at];
    if ((m[3] !== undefined) !== reference) {
      throw new Error(reference ? `the ${name} part ends with "/" and the rank of zero` : `the ${name} part has no reference point, so it takes no "/"`);
    }
    const fields = m[2].split(',');
    if (fields.length !== candles) throw new Error(`the ${name} part needs one rank for each candle`);
    const all = reference ? [...fields, m[3]] : fields;
    if (all.some((field) => !/^(0|[1-9][0-9]*)$/.test(field))) throw new Error('G1 ranks must be canonical nonnegative integers');
    const ranks = all.map(Number);
    const used = new Set(ranks);
    for (let rank = 0; rank < used.size; rank++) if (!used.has(rank)) throw new Error(`G1 ${name} ranks must be dense starting at zero`);
    dims.push({ name, ranks: ranks.slice(0, candles), reference: reference ? ranks[candles] : null, rankCount: used.size });
  }
  return dims;
}
export function parseG1(code) {
  if (typeof code !== 'string' || !/^g1:[ou]:/.test(code)) {
    throw new Error('expected a Filang code beginning g1:o: or g1:u:');
  }
  const oriented = code[3] === 'o';
  const [price, ...parts] = code.slice(5).split('|');
  const input = price.split(';');
  const rows = [];
  const used = new Set();
  for (const item of input) {
    const fields = item.split(',');
    if (fields.length !== (oriented ? 5 : 4)) throw new Error('each G1 candle needs four ranks' + (oriented ? ' and a direction (u, d or z)' : ''));
    const ranks = fields.slice(0, 4).map((field) => {
      if (!/^(0|[1-9][0-9]*)$/.test(field)) throw new Error('G1 ranks must be canonical nonnegative integers');
      const rank = Number(field);
      if (rank >= 4 * input.length) throw new Error('G1 ranks must be dense starting at zero');
      used.add(rank);
      return rank;
    });
    if (ranks.some((rank, j) => j > 0 && rank < ranks[j - 1])) throw new Error('G1 ranks must follow low ≤ body low ≤ body high ≤ high');
    const direction = fields[4];
    if (oriented && (!['u', 'd', 'z'].includes(direction) || (direction === 'z') !== (ranks[1] === ranks[2]))) {
      throw new Error('G1 direction must agree with the body ranks (z exactly for a doji)');
    }
    rows.push({ ranks, direction });
  }
  for (let i = 0; i < used.size; i++) if (!used.has(i)) throw new Error('G1 ranks must be dense starting at zero');
  return { oriented, rows, rankCount: used.size, dims: parseDimensions(parts, rows.length) };
}

function direction(o, c) { return c > o ? 'u' : c < o ? 'd' : 'z'; }

// A bar's open under each reading. As recorded it is the bar's own open. In the chained reading the first bar of a
// window keeps its recorded open, and every later bar opens at the close of the recorded bar just before it: a drawn
// shape is a chain, and its later opens are never free prices.
function openAt(rec, i, chained, first) { return chained && !first ? rec.C[i - 1] : rec.O[i]; }

// [low, body low, body high, high]. A chained later bar widens its low and high to include its open, so the body
// always lies inside them; a bar read as recorded is left exactly as recorded.
function endpoints(rec, i, chained = false, first = true) {
  const o = openAt(rec, i, chained, first), c = rec.C[i];
  const joined = chained && !first;
  return [joined ? Math.min(rec.L[i], o) : rec.L[i], Math.min(o, c), Math.max(o, c), joined ? Math.max(rec.H[i], o) : rec.H[i]];
}

// One dimension's part of a window's code, or null when the recording has no value for one of its candles.
function dimensionPart(rec, start, barCount, name) {
  const values = rec.dimension(name);
  if (!values) return null;
  const window = [];
  for (let i = start; i < start + barCount; i++) {
    if (Number.isNaN(values[i])) return null;
    window.push(values[i]);
  }
  const { reference } = DIMENSIONS[DIMENSION_AT.get(name)];
  const sorted = [...new Set(reference ? [...window, 0] : window)].sort((a, b) => a - b);
  const ranks = new Map(sorted.map((value, rank) => [value, rank]));
  return name + ':' + window.map((value) => ranks.get(value)).join(',') + (reference ? '/' + ranks.get(0) : '');
}

// The names asked for, once each and in the order their parts are written.
function dimensionNames(dims) {
  for (const name of dims) if (!DIMENSION_AT.has(name)) throw new Error(`unknown G1 dimension "${name}"`);
  return DIMENSIONS.map((d) => d.name).filter((name) => dims.includes(name));
}

function codeFromRecording(rec, endSlot, barCount, oriented, chained, dims = []) {
  const start = endSlot - barCount + 1;
  if (!Number.isInteger(endSlot) || !Number.isSafeInteger(barCount) || barCount < 1 || start < 0 || endSlot >= rec.n) return null;
  const rows = [];
  for (let i = start; i <= endSlot; i++) {
    if (!rec.present[i]) return null;
    rows.push(endpoints(rec, i, chained, i === start));
  }
  const sorted = [...new Set(rows.flat())].sort((a, b) => a - b);
  const ranks = new Map(sorted.map((value, rank) => [value, rank]));
  const codes = rows.map((row, j) => {
    const fields = row.map((value) => ranks.get(value));
    if (oriented) fields.push(direction(openAt(rec, start + j, chained, j === 0), rec.C[start + j]));
    return fields.join(',');
  });
  let code = 'g1:' + (oriented ? 'o:' : 'u:') + codes.join(';');
  for (const name of dimensionNames(dims)) {
    const part = dimensionPart(rec, start, barCount, name);
    if (part === null) return null;
    code += '|' + part;
  }
  return code;
}

// `dims` names the dimensions to switch on. With none the code is the price code alone, exactly as before.
export function g1FromRecording(rec, endSlot, barCount = 1, oriented = true, dims = []) {
  return codeFromRecording(rec, endSlot, barCount, oriented, false, dims);
}

// The window's code in the chained reading. A one-bar window has no later bar, so it equals g1FromRecording.
export function chainedG1FromRecording(rec, endSlot, barCount = 1, oriented = true, dims = []) {
  return codeFromRecording(rec, endSlot, barCount, oriented, true, dims);
}

// Assign one observed price to each required rank. Equality within a rank and
// strict increase between adjacent ranks suffice for the whole global order.
function matches(rec, start, pattern, rankPrices, chained) {
  rankPrices.fill(NaN);
  for (let j = 0; j < pattern.rows.length; j++) {
    const i = start + j;
    const row = pattern.rows[j];
    if (pattern.oriented && row.direction !== direction(openAt(rec, i, chained, j === 0), rec.C[i])) return false;
    const prices = endpoints(rec, i, chained, j === 0);
    for (let k = 0; k < 4; k++) {
      const rank = row.ranks[k], price = prices[k];
      if (!Number.isNaN(rankPrices[rank]) && rankPrices[rank] !== price) return false;
      rankPrices[rank] = price;
    }
  }
  for (let rank = 1; rank < rankPrices.length; rank++) if (rankPrices[rank] <= rankPrices[rank - 1]) return false;
  return true;
}

export function matchesG1(rec, start, pattern, rankPrices) { return matches(rec, start, pattern, rankPrices, false); }

// The same comparison on the window read as a chain.
export function matchesChainedG1(rec, start, pattern, rankPrices) { return matches(rec, start, pattern, rankPrices, true); }

// Whether the window stands in the pattern's order on every dimension the pattern switches on: 1 when it does,
// 0 when it does not, and -1 when the recording has no value for a candle the pattern asks about. A chained
// reading changes price points only, so this is the same under both readings. `scratch` holds one array per
// dimension part, each as long as that part's rank count; it is optional and spares an allocation per window.
export function dimensionsFit(rec, start, pattern, scratch) {
  const { dims } = pattern, candles = pattern.rows.length;
  const series = new Array(dims.length);
  for (let k = 0; k < dims.length; k++) {
    const values = rec.dimension(dims[k].name);
    if (!values) return -1;
    for (let j = 0; j < candles; j++) if (Number.isNaN(values[start + j])) return -1;
    series[k] = values;
  }
  for (let k = 0; k < dims.length; k++) {
    const part = dims[k], values = series[k];
    const at = scratch ? scratch[k] : new Float64Array(part.rankCount);
    at.fill(NaN);
    if (part.reference !== null) at[part.reference] = 0;
    for (let j = 0; j < candles; j++) {
      const rank = part.ranks[j], value = values[start + j];
      if (!Number.isNaN(at[rank]) && at[rank] !== value) return 0;
      at[rank] = value;
    }
    for (let rank = 1; rank < at.length; rank++) if (at[rank] <= at[rank - 1]) return 0;
  }
  return 1;
}
