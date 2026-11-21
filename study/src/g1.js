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

function endpoints(rec, i) {
  const o = rec.O[i], c = rec.C[i];
  return [rec.L[i], Math.min(o, c), Math.max(o, c), rec.H[i]];
}

export function g1FromRecording(rec, endSlot, barCount = 1, oriented = true) {
  const start = endSlot - barCount + 1;
  if (!Number.isInteger(endSlot) || !Number.isSafeInteger(barCount) || barCount < 1 || start < 0 || endSlot >= rec.n) return null;
  const rows = [];
  for (let i = start; i <= endSlot; i++) {
    if (!rec.present[i]) return null;
    rows.push(endpoints(rec, i));
  }
  const sorted = [...new Set(rows.flat())].sort((a, b) => a - b);
  const ranks = new Map(sorted.map((value, rank) => [value, rank]));
  const codes = rows.map((row, j) => {
    const fields = row.map((value) => ranks.get(value));
    if (oriented) fields.push(direction(rec.O[start + j], rec.C[start + j]));
    return fields.join(',');
  });
  return 'g1:' + (oriented ? 'o:' : 'u:') + codes.join(';');
}

// Assign one observed price to each required rank. Equality within a rank and
// strict increase between adjacent ranks suffice for the whole global order.
export function matchesG1(rec, start, pattern, rankPrices) {
  rankPrices.fill(NaN);
  for (let j = 0; j < pattern.rows.length; j++) {
    const i = start + j;
    const row = pattern.rows[j];
    if (pattern.oriented && row.direction !== direction(rec.O[i], rec.C[i])) return false;
    const prices = endpoints(rec, i);
    for (let k = 0; k < 4; k++) {
      const rank = row.ranks[k], price = prices[k];
      if (!Number.isNaN(rankPrices[rank]) && rankPrices[rank] !== price) return false;
      rankPrices[rank] = price;
    }
  }
  for (let rank = 1; rank < rankPrices.length; rank++) if (rankPrices[rank] <= rankPrices[rank - 1]) return false;
  return true;
}
