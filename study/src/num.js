// Exact arithmetic helpers.
// Prices are integer cents parsed from the CSV text (no binary floating point).
// Threshold literals are exact rationals num/den (BigInt) built from their decimal text.
// Decisions compare integers by cross-multiplication. Returns are float64 ratios of integer cents.

function gcd(a, b) {
  a = a < 0n ? -a : a;
  b = b < 0n ? -b : b;
  while (b) { const t = a % b; a = b; b = t; }
  return a;
}

export function reduce(num, den) {
  const g = gcd(num, den) || 1n;
  return { num: num / g, den: den / g };
}

/** "35" -> 35/1, "0.35" -> 7/20; pct=true divides by 100 ("35" -> 7/20). */
export function ratFromText(text, pct = false) {
  const [ip, fp = ''] = text.split('.');
  const num = BigInt(ip + fp);
  let den = 10n ** BigInt(fp.length);
  if (pct) den *= 100n;
  return reduce(num, den);
}

export function ratCmp(a, b) {
  const l = a.num * b.den;
  const r = b.num * a.den;
  return l < r ? -1 : l > r ? 1 : 0;
}

export function ratKey(r) { return `${r.num}/${r.den}`; }

/** Exact decimal text of a rational whose denominator has only factors 2 and 5. */
export function ratToDecimalText(r) {
  let d = r.den;
  let a = 0;
  let b = 0;
  while (d % 2n === 0n) { d /= 2n; a++; }
  while (d % 5n === 0n) { d /= 5n; b++; }
  if (d !== 1n) return (Number(r.num) / Number(r.den)).toString();
  const k = Math.max(a, b);
  const num = r.num * (2n ** BigInt(k - a)) * (5n ** BigInt(k - b));
  const s = num.toString().padStart(k + 1, '0');
  if (k === 0) return s;
  return `${s.slice(0, s.length - k)}.${s.slice(s.length - k)}`.replace(/\.?0+$/, '');
}

export function ratToPercentText(r) { return ratToDecimalText({ num: r.num * 100n, den: r.den }) + '%'; }
export function ratToNumber(r) { return Number(r.num) / Number(r.den); }

/** Parse a CSV price with at most 2 decimals into integer cents; null if not representable. */
export function parseCents(s) {
  const m = /^(\d+)(?:\.(\d{1,2}))?$/.exec(s);
  if (!m) return null;
  const v = Number(m[1]) * 100 + Number((m[2] || '').padEnd(2, '0'));
  return Number.isSafeInteger(v) ? v : null;
}

export function centsText(c) {
  const neg = c < 0;
  const a = Math.abs(c);
  const s = `${Math.floor(a / 100)}.${String(a % 100).padStart(2, '0')}`;
  return neg ? '-' + s : s;
}

/** a ≤ r·b for nonnegative integers a, b (exact). */
export function leRatTimes(a, r, b) { return BigInt(a) * r.den <= r.num * BigInt(b); }
/** a ≥ r·b (exact). */
export function geRatTimes(a, r, b) { return BigInt(a) * r.den >= r.num * BigInt(b); }

/** Percent text for display with fixed decimals (display only). */
export function pctText(x, digits = 2) {
  if (x === null || x === undefined || Number.isNaN(x)) return '—';
  const v = x * 100;
  const s = v.toFixed(digits);
  return (v > 0 ? '+' : '') + (s === '-0.00' ? '0.00' : s) + '%';
}

export function shareText(a, b, digits = 1) {
  if (!b) return '—';
  return `${((100 * a) / b).toFixed(digits)}%`;
}
