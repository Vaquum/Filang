// Filang g1 stores global endpoint ranks in the drawing's supplied order.
// The query contract uses oldest first and anchors at the last candle's close.
export function parseG1(code) {
  if (typeof code !== 'string' || !/^g1:[ou]:/.test(code)) {
    throw new Error('expected a Filang code beginning g1:o: or g1:u:');
  }
  const oriented = code[3] === 'o';
  const input = code.slice(5).split(';');
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
  return { oriented, rows, rankCount: used.size };
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

function codeFromRecording(rec, endSlot, barCount, oriented, chained) {
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
  return 'g1:' + (oriented ? 'o:' : 'u:') + codes.join(';');
}

export function g1FromRecording(rec, endSlot, barCount = 1, oriented = true) {
  return codeFromRecording(rec, endSlot, barCount, oriented, false);
}

// The window's code in the chained reading. A one-bar window has no later bar, so it equals g1FromRecording.
export function chainedG1FromRecording(rec, endSlot, barCount = 1, oriented = true) {
  return codeFromRecording(rec, endSlot, barCount, oriented, true);
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
