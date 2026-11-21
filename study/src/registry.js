// Registry: typed, versioned definitions. Signatures define calls and typing (not grammar).
// Declarative only — evaluation lives in engine.js, keyed by definition name and version.
import '../composer/patterns.js';

// Composer is also a standalone classic-script app. Both surfaces read the same catalog.
export const CANDLE_PATTERNS = globalThis.CandlePatterns;

export const ENGINE = Object.freeze({
  name: 'limen-sfd-browser-prototype',
  version: '0.2.0',
  semantics: 'strong-kleene-v1; anchor = bar close; only true passes a filter',
});

export const ENUMS = Object.freeze({
  SessionDay: {
    name: 'SessionDay',
    title: 'session day',
    values: ['mon', 'tue', 'wed', 'thu', 'fri', 'closed'],
    labels: { mon: 'Monday', tue: 'Tuesday', wed: 'Wednesday', thu: 'Thursday', fri: 'Friday', closed: 'closed (no session that New York date)' },
    note: 'Weekday stored in the pinned session table for the New York date of the anchor; dates in coverage without a session are closed.',
    never: { sat: 'nyse_regular has no Saturday sessions; non-session dates are `closed`', sun: 'nyse_regular has no Sunday sessions; non-session dates are `closed`' },
  },
  Trend: {
    name: 'Trend',
    title: 'completed-bar trend',
    values: ['up', 'down', 'flat'],
    labels: { up: 'up (close > open)', down: 'down (close < open)', flat: 'flat (close = open)' },
    note: 'Direction of a completed UTC-aligned higher-timeframe bar.',
  },
});

export const KIND_TYPE = Object.freeze({
  event: 'Event', state: 'State', condition: 'Condition', outcome: 'Outcome',
});

const D = (minMs, maxMs, extra) => ({ minMs, maxMs, ...extra });

export const FUNCTIONS = [
  {
    name: 'exact_g1', version: 1, kind: 'event', result: 'Event', status: 'implemented',
    title: 'Exact G1 twins',
    summary: 'The contiguous bars have the same global price ordering and ties as the selected Composer drawing.',
    positional: 'pattern',
    params: [{ name: 'pattern', type: 'G1', required: true, doc: 'canonical Filang g1:o: or g1:u: code, oldest candle first' }],
    requires: ['bars.ohlc'],
    formula: ['Rank all low, body low, body high and high endpoints across the window together.',
      'Every corresponding rank matches, including ties. In oriented mode every body direction also matches.'],
    anchor: 'close of the final bar in the contiguous window',
    availability: 'all source candles must have closed by the anchor',
    missing: 'an incomplete window is unknown',
    template: (a) => `exact twins of ${a.pattern}`,
    example: 'exact_g1("g1:o:0,1,2,2,u")',
  },
  {
    name: 'wick_rejection', version: 1, kind: 'event', result: 'Event', status: 'implemented',
    title: 'Wick rejection',
    summary: 'A bar whose small body sits at the top of its range after a long lower wick (rejection of lower prices).',
    params: [
      { name: 'body_max', type: 'Ratio', default: '35%', domain: { ratioMin: '0', ratioMax: '1' }, doc: 'largest body |close − open| as a share of the bar range' },
      { name: 'wick_min', type: 'Ratio', default: '45%', domain: { ratioMin: '0', ratioMinExclusive: true, ratioMax: '1' }, doc: 'smallest lower wick min(open, close) − low as a share of the bar range' },
    ],
    requires: ['bars.ohlc'],
    formula: [
      'range = high − low; the event needs range > 0',
      'body = |close − open|',
      'lower_wick = min(open, close) − low',
      'event ⇔ range > 0 ∧ body ≤ body_max × range ∧ lower_wick ≥ wick_min × range',
    ],
    anchor: 'close of the event bar: t = open + 15m',
    availability: 'uses only the event bar, complete at its close',
    missing: 'absent bar → no occurrence (counted as absent)',
    template: (a) => `wick rejection (body ≤ ${a.body_max}, lower wick ≥ ${a.wick_min} of range)`,
    example: 'wick_rejection(body_max: 35%, wick_min: 45%)',
  },
  {
    name: 'channel_breakout', version: 1, kind: 'event', result: 'Event', status: 'implemented',
    title: 'Channel breakout',
    summary: 'The trigger bar closes above the highest high of the preceding lookback; the trigger bar is excluded from the channel.',
    params: [
      { name: 'over', type: 'Duration', required: true, domain: D(900_000, 7 * 86_400_000, { barMultiple: true }), doc: 'lookback length L (whole bars before the trigger)' },
    ],
    requires: ['bars.ohlc'],
    formula: [
      'channel = bars with opens in [t − 15m − L, t − 15m) (the L/15m bars before the trigger)',
      'prior_high = max(high over channel)',
      'event ⇔ close(trigger) > prior_high (strict)',
    ],
    anchor: 'close of the trigger bar',
    availability: 'uses the trigger bar and earlier bars only',
    missing: 'an absent channel bar → unknown, unless close ≤ max of the present highs (then false)',
    template: (a) => `close breaks above the prior ${a.over} high`,
    example: 'channel_breakout(over: 12h)',
  },
  {
    name: 'quiet_range', version: 1, kind: 'state', result: 'State', status: 'implemented',
    title: 'Quiet range',
    summary: 'Rolling state sampled at every 15m close: the trailing window range is small relative to the close.',
    params: [
      { name: 'window', type: 'Duration', default: '4h', domain: D(1_800_000, 2 * 86_400_000, { barMultiple: true }), doc: 'trailing window W through the sample close (4h = 16 bars)' },
      { name: 'width_max', type: 'Ratio', default: '2.5%', domain: { ratioMin: '0', ratioMinExclusive: true, ratioMax: '1' }, doc: 'largest allowed (highest high − lowest low) / close' },
    ],
    requires: ['bars.ohlc'],
    formula: [
      'at each 15m close s: W = bars with opens in [s − window, s)',
      'width = max(high over W) − min(low over W)',
      'state(s) ⇔ width ≤ width_max × close(s)',
    ],
    anchor: 'each 15m close (a time series, used through held or sampled at the anchor)',
    availability: 'uses bars up to and including the bar closing at s',
    missing: 'an absent bar in W → unknown, unless the present bars already exceed the limit (then false)',
    template: (a) => `quiet range (${a.window} width ≤ ${a.width_max} of close)`,
    example: 'quiet_range(window: 4h, width_max: 2.5%)',
  },
  {
    name: 'held', version: 1, kind: 'condition', result: 'Condition', status: 'implemented',
    title: 'Held for',
    summary: 'Duration operator on a state: the state was true at every 15m sample from t − D through t.',
    positional: 'state',
    params: [
      { name: 'state', type: 'State', required: true, doc: 'a State such as "Quiet range" or quiet_range(width_max: 2%)' },
      { name: 'for', type: 'Duration', required: true, domain: D(900_000, 7 * 86_400_000, { barMultiple: true }), doc: 'required uninterrupted duration D (first true sample at elapsed zero = t − D)' },
    ],
    requires: ['bars.ohlc'],
    formula: [
      'samples s = t − D, t − D + 15m, …, t on the UTC 15m grid (D/15m + 1 samples; 48h → 193)',
      'held ⇔ state(s) is true at every sample',
      'any known false sample → false; otherwise any absent or unknown sample → unknown',
      'grid coverage is checked by timestamp, never by adjacent array elements',
    ],
    anchor: 'the anchor t (last sample)',
    availability: 'samples at or before t only',
    missing: 'samples before the first recorded close or on absent bars are unknown; a known false still disproves',
    template: (a) => `${a.state} has held for ${a.for}`,
    example: 'held("Quiet range", for: 48h)',
  },
  {
    name: 'range_contained', version: 1, kind: 'condition', result: 'Condition', status: 'implemented',
    title: 'Single-window containment',
    summary: 'One trailing window envelope; no held timer. A contrast to held(quiet_range(…), for: …).',
    params: [
      { name: 'over', type: 'Duration', required: true, domain: D(1_800_000, 7 * 86_400_000, { barMultiple: true }), doc: 'trailing window length' },
      { name: 'width_max', type: 'Ratio', required: true, domain: { ratioMin: '0', ratioMinExclusive: true, ratioMax: '1' }, doc: 'largest allowed envelope / close' },
    ],
    requires: ['bars.ohlc'],
    formula: [
      'W = bars with opens in [t − over, t)',
      'envelope = max(high over W) − min(low over W)',
      'true ⇔ envelope ≤ width_max × close(t)',
    ],
    anchor: 'the anchor t',
    availability: 'bars up to and including the bar closing at t',
    missing: 'an absent bar in W → unknown, unless the present bars already exceed the limit (then false)',
    template: (a) => `the last ${a.over} stayed within ${a.width_max} of close (one window)`,
    example: 'range_contained(over: 52h, width_max: 6%)',
  },
  {
    name: 'weekday', version: 1, kind: 'categorical', result: 'Cat:SessionDay', status: 'implemented',
    title: 'Session weekday',
    summary: 'The stored weekday of the calendar session on the anchor’s New York date; closed when that date has no session.',
    positional: 'calendar',
    params: [
      { name: 'calendar', type: 'Calendar', required: true, doc: 'registered session calendar' },
    ],
    requires: ['calendar'],
    formula: [
      'New York date of the anchor instant, using the pinned session table (local day = [open − 9h30m, open + 14h30m) of that session)',
      'value = stored weekday of that date’s session (mon … fri); closed if the date is covered but has no session',
    ],
    anchor: 'the anchor t',
    availability: 'pinned calendar; uses only the anchor timestamp',
    missing: 'anchor outside calendar coverage → unknown',
    template: (a) => `${a.calendar} session day`,
    example: 'weekday(nyse_regular) = fri',
  },
  {
    name: 'session_tail', version: 1, kind: 'condition', result: 'Condition', status: 'implemented',
    title: 'Session tail',
    summary: 'The anchor (bar close) falls in the half-open tail (session_end − D, session_end] of a session.',
    positional: 'calendar',
    params: [
      { name: 'calendar', type: 'Calendar', required: true, doc: 'registered session calendar' },
      { name: 'last', type: 'Duration', required: true, domain: { minMs: 60_000, maxShortestSession: true }, doc: 'tail length D before the session end' },
    ],
    requires: ['calendar'],
    formula: [
      'true ⇔ some session close c satisfies c − D < t ≤ c',
      'with 15m bars and a 16:00 close: last: 30m admits closes 15:45 and 16:00, not 15:30; last: 1h admits 15:15–16:00',
      'a 30–60 minute band is session_tail(cal, last: 1h) and not session_tail(cal, last: 30m)',
    ],
    anchor: 'the anchor t (event completion)',
    availability: 'pinned calendar (the schedule is known in advance); uses only the anchor timestamp',
    missing: 'known closed dates → false; [t, t + D) not fully inside calendar coverage → unknown',
    template: (a) => `bar closes in the last ${a.last} of the ${a.calendar} session`,
    example: 'session_tail(nyse_regular, last: 30m)',
  },
  {
    name: 'completed_trend', version: 1, kind: 'categorical', result: 'Cat:Trend', status: 'implemented',
    title: 'Completed higher-timeframe trend',
    summary: 'Close versus open of the most recent expected UTC-aligned bar of the frame that ended by t.',
    params: [
      { name: 'frame', type: 'Duration', required: true, domain: { minMs: 900_000, barMultiple: true, dividesDay: true }, doc: 'UTC-aligned frame length (must divide 24h)' },
    ],
    requires: ['bars.ohlc'],
    formula: [
      'E = floor(t / frame) × frame (UTC-aligned end ≤ t); the frame bar covers [E − frame, E)',
      'up if close(last constituent) > open(first constituent); down if <; flat if =',
      'every constituent 15m bar must be present; no fallback to an older frame bar',
    ],
    anchor: 'the anchor t',
    availability: 'the frame bar is complete at E ≤ t',
    missing: 'any constituent absent or before the recording → unknown',
    template: (a) => `last completed ${a.frame} bar direction`,
    example: 'completed_trend(frame: 4h)',
  },
  {
    name: 'close_return', version: 1, kind: 'outcome', result: 'Outcome', status: 'implemented',
    title: 'Close return',
    summary: 'Observed return from the anchor close to the close exactly h later. Each horizon is a column.',
    params: [
      { name: 'after', type: 'Duration', list: true, required: true, domain: D(900_000, 7 * 86_400_000, { barMultiple: true }), doc: 'horizon h, or a vector of horizons (one column each)' },
    ],
    requires: ['bars.ohlc'],
    formula: [
      'r(h) = C(t + h) / C(t) − 1, where C(x) is the close of the bar that closes exactly at x',
      't + h after the recording end → censored; bar absent inside the recording → unknown',
      'occurrences stay in the table when an outcome is missing; summaries use observed values only',
    ],
    anchor: 'measured after the anchor; never allowed in where',
    availability: 'uses bars after t (outcome only)',
    missing: 'censored beyond the recording end; unknown for an absent interior endpoint',
    template: (a) => `close return after ${a.after}`,
    example: 'close_return(after: [1h, 4h])',
  },
  // ---- planned typed capabilities (design examples; not executable here)
  {
    name: 'relative_volume', version: 0, kind: 'condition', status: 'planned',
    title: 'Relative-volume threshold (planned)',
    signature: 'relative_volume(over: Duration, min: Ratio) → Condition',
    note: 'A rule may add a relative-volume threshold with another sweep. Planned design example; this prototype stays an observed-return study.',
    requires: ['bars.volume'],
  },
  {
    name: 'breach_reclaim', version: 0, kind: 'event', status: 'planned',
    title: 'Breach and reclaim (planned)',
    signature: 'breach_reclaim(reference, within_min: Number, within_max: Number)',
    note: 'Freezes the reference (e.g. prior_utc_day_low()) at the breach, waits for the first strict reclaim within an inclusive bar range (a named min/max pair is preferred to a vector such as within: [1, 3]) and identifies both events. A gap can make the pairing unknown; first passage distinguishes unordered touches inside one OHLC bar.',
    requires: ['bars.ohlc'],
  },
  {
    name: 'prior_utc_day_low', version: 0, kind: 'reference', status: 'planned',
    title: 'Prior UTC day low (planned)',
    signature: 'prior_utc_day_low()',
    note: 'Reference level for breach_reclaim. Planned design example.',
    requires: ['bars.ohlc'],
  },
  {
    name: 'value_area_reclaim', version: 0, kind: 'event', status: 'planned',
    title: 'Value-area reclaim (planned, needs trades)',
    signature: 'value_area_reclaim(profile: prior_utc_day, seller_flow: …)',
    note: 'Uses a pinned prior UTC day volume profile and a seller-flow condition on the same supporting bar. OHLCV bars cannot substitute for ordered trades with aggressor side.',
    requires: ['trades.ordered', 'trades.aggressor'],
  },
  ...CANDLE_PATTERNS.patterns.map((entry) => {
    const name = entry.id.replaceAll('-', '_');
    return {
      id: 'composer.' + name, name, version: entry.version, kind: 'event', result: 'Event', status: 'implemented',
      patternId: entry.id, canonicalName: entry.name, ja: entry.ja, aliases: entry.aliases,
      patternBars: entry.bars, patternRule: entry.rule, patternSpec: entry.spec,
      title: entry.name, summary: entry.rule, params: [], requires: ['bars.ohlc'],
      formula: [entry.rule], anchor: 'close of the final candle',
      availability: `uses ${entry.bars} consecutive completed ${entry.bars === 1 ? 'candle' : 'candles'} through the anchor`,
      missing: 'a missing candle or incomplete opening window is unknown',
      template: () => entry.name, example: name,
    };
  }),
];

export const PLANNED_CLAUSES = [
  { name: 'simulate', note: 'one explicit simulate clause with its own ledger: entry at the first eligible open strictly after known-at, stop, target, expiry and costs, declared intrabar policy.' },
  { name: 'holdout', note: 'one chronological holdout clause; frozen in time and only genuinely sealed if withheld. Observational returns remain a separate measure.' },
];

export const NAMED = {
  'Wick rejection': {
    kind: 'event', def: 'wick_rejection', version: 1,
    args: { body_max: '35%', wick_min: '45%' },
    origin: 'Bundled example pattern for this prototype — not a Composer object (none was supplied).',
    note: 'In the full design a Composer object carries its own matcher, version, timeframe, parameters and anchor; selecting arbitrary candles does not determine how a pattern generalizes. The typed call wick_rejection(body_max: 35%, wick_min: 45%) is the same registered definition and yields the same occurrence identities.',
  },
  'Quiet range': {
    kind: 'state', def: 'quiet_range', version: 1,
    args: { window: '4h', width_max: '2.5%' },
    origin: 'Bundled rolling state for this prototype.',
    note: 'width_max = 2.5% was picked from coverage of real recorded matches (bar counts only; no returns were looked at). The design suggested starting at 2%. At 2% the starter keeps 1 match for each tail, so widening reveals nothing. 2.5% is the smallest step at which widening 30m → 1h adds real matches (2 → 4). The coverage table shows each width. Edit the parameter with quiet_range(width_max: …).',
  },
};

const candleFunctions = new Map(FUNCTIONS.filter((f) => f.patternId).map((f) => [f.patternId, f]));
for (const def of candleFunctions.values()) {
  const named = {
    kind: def.kind, def: def.name, version: def.version, args: {}, patternId: def.patternId,
    canonicalName: def.canonicalName, ja: def.ja, aliases: def.aliases,
    origin: 'Composer candle pattern catalog.', note: def.patternRule,
  };
  for (const label of new Set([def.canonicalName, def.ja, ...def.aliases])) {
    if (Object.hasOwn(NAMED, label)) throw Error(`Duplicate candle name: ${label}`);
    NAMED[label] = named;
  }
}

export const RECORDING_CAPABILITIES = ['bars.ohlc', 'bars.volume', 'calendar'];

export const CAPABILITY_TEXT = {
  'bars.ohlc': '15m OHLC bars',
  'bars.volume': '15m bar volume',
  calendar: 'pinned session calendar',
  'trades.ordered': 'ordered individual trades',
  'trades.aggressor': 'trade aggressor side',
};

// ---------------------------------------------------------------- registry object

export class Registry {
  constructor() {
    this.functions = new Map();
    for (const f of FUNCTIONS) this.functions.set(f.name, f);
    this.named = new Map(Object.entries(NAMED));
    this.extensions = [];
  }
  get(name) { return this.functions.get(name) || null; }
  getPattern(id) { return candleFunctions.get(id) || null; }
  getNamed(name) {
    if (typeof name !== 'string') return null;
    return this.named.get(name) || this.named.get(CANDLE_PATTERNS.resolve(name.replaceAll('_', '-'))?.name) || null;
  }
  getVersion(id, version) {
    if (typeof id !== 'string') return null;
    if (id.startsWith('composer.')) {
      const pattern = this.getPattern(id.slice(9).replaceAll('_', '-'));
      return pattern?.version === version ? pattern : null;
    }
    const def = this.get(version === 1 ? id : `${id}_v${version}`);
    return def && ((def.id || def.name) === id || def.patternId && def.name === id) && def.version === version ? def : null;
  }
  isEnumValue(name) { return Object.values(ENUMS).some((e) => e.values.includes(name)); }
  enumOf(type) { return type && type.startsWith('Cat:') ? ENUMS[type.slice(4)] : null; }
  list(filter) {
    const defs = [...this.functions.values()];
    // A previously installed extension can own the same call name as a pattern.
    for (const def of candleFunctions.values()) if (this.get(def.name) !== def) defs.push(def);
    return filter ? defs.filter(filter) : defs;
  }
  implemented() { return this.list((f) => f.status !== 'planned'); }
  addFunction(def) { this.functions.set(def.name, def); }
}

export function editDistance(a, b) {
  const m = a.length;
  const n = b.length;
  const d = Array.from({ length: m + 1 }, (_, i) => [i, ...new Array(n).fill(0)]);
  for (let j = 1; j <= n; j++) d[0][j] = j;
  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      const c = a[i - 1] === b[j - 1] ? 0 : 1;
      d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + c);
      if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) d[i][j] = Math.min(d[i][j], d[i - 2][j - 2] + 1);
    }
  }
  return d[m][n];
}

export function suggest(word, candidates, max = 3) {
  const w = word.toLowerCase();
  const scored = [];
  for (const c of candidates) {
    const cl = c.toLowerCase();
    let s = editDistance(w, cl);
    if (cl.startsWith(w) || w.startsWith(cl)) s = Math.min(s, 1);
    if (s <= Math.max(2, Math.floor(c.length / 3))) scored.push([s, c]);
  }
  scored.sort((x, y) => x[0] - y[0] || x[1].localeCompare(y[1]));
  return scored.slice(0, max).map((x) => x[1]);
}

export function typeText(param) {
  return param.list ? `${param.type} or [${param.type}, …]` : param.type;
}

export function signatureText(f) {
  if (f.status === 'planned') return f.signature;
  const ps = f.params.map((p) => {
    const pos = f.positional === p.name ? ' (may be positional)' : '';
    const def = p.default !== undefined ? ` = ${p.default}` : (p.required ? '' : ' (optional)');
    return `${p.name}: ${typeText(p)}${def}${pos}`;
  });
  return `${f.name}(${ps.join(', ')}) → ${f.result}`;
}
