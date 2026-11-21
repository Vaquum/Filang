// Example questions shown in the page. Every one is parsed, checked and run by the same engine.

export const EXAMPLES = [
  {
    id: 'starter',
    group: 'Lesson',
    title: 'Starter: quiet Friday wick rejections',
    text: `on BTCUSDT 15m
find "Wick rejection"
where weekday(nyse_regular) = fri
where session_tail(nyse_regular, last: {30m | 1h})
where held("Quiet range", for: 48h)
measure close_return(after: [1h, 4h])`,
    note: 'The design’s starting question and the first exercise. {30m | 1h} is one sweep axis, so it runs as two candidates. [1h, 4h] is one vector argument, so it makes two columns.',
  },
  {
    id: 'transfer',
    group: 'Lesson',
    title: 'Transfer: breakout grouped by the 4h trend',
    text: `on BTCUSDT 15m
let lookback = {12h | 24h}
find channel_breakout(over: lookback)
group by completed_trend(frame: 4h)
measure close_return(after: [1h, 4h])`,
    note: 'A different setup in the same grammar. The groups partition the matches; turning a group into a filter keeps only that bucket.',
  },
  {
    id: 'transfer-filter',
    group: 'Lesson',
    title: 'Transfer as a filter: only an up 4h trend',
    text: `on BTCUSDT 15m
let lookback = {12h | 24h}
find channel_breakout(over: lookback)
where completed_trend(frame: 4h) = up
measure close_return(after: [1h, 4h])`,
    note: 'Same population as the transfer question, filtered to its "up" group. Compare it with the grouped run.',
  },
  {
    id: 'practice',
    group: 'More examples',
    title: 'Starter without the quiet clause',
    text: `on BTCUSDT 15m
find "Wick rejection"
where weekday(nyse_regular) = fri
where session_tail(nyse_regular, last: {30m | 1h})
measure close_return(after: [1h, 4h])`,
    note: 'A less restrictive variant of the starter. Compare it with the starter to see which matches the 48h quiet clause removes.',
  },
  {
    id: 'shared',
    group: 'More examples',
    title: 'One named parameter used twice',
    text: `on BTCUSDT 15m
let span = {12h | 24h}
find channel_breakout(over: span)
where held(quiet_range(width_max: 3%), for: span)
measure close_return(after: [1h, 4h])`,
    note: 'A let with choices is one axis however often it is referenced: two candidates, not four.',
  },
  {
    id: 'band',
    group: 'More examples',
    title: '30–60 minute band before the close',
    text: `on BTCUSDT 15m
find "Wick rejection"
where weekday(nyse_regular) = fri
where session_tail(nyse_regular, last: 1h) and not session_tail(nyse_regular, last: 30m)
measure close_return(after: [1h, 4h])`,
    note: 'Boundaries are inherited from the two tail tests: closes at 15:15 and 15:30 New York time.',
  },
  {
    id: 'typed',
    group: 'More examples',
    title: 'Typed call of the same definition',
    text: `on BTCUSDT 15m
find wick_rejection(body_max: 35%, wick_min: 45%)
where weekday(nyse_regular) = fri
where session_tail(nyse_regular, last: {30m | 1h})
measure close_return(after: [1h, 4h])`,
    note: 'Same registered definition as "Wick rejection", so the occurrence identities are identical.',
  },
  {
    id: 'extension',
    group: 'More examples',
    title: 'Extension: Quiet Friday close (v1)',
    text: `on BTCUSDT 15m
find "Wick rejection"
where quiet_friday_close(last: {30m | 1h})
measure close_return(after: [1h, 4h])`,
    note: 'An agent-authored, versioned composition loaded from extensions/quiet_friday_close.v1.json. Its typed parameters (last, quiet_for, width_max) come from its signature, and with its defaults its matches equal the starter’s candidates.',
  },
  {
    id: 'contain',
    group: 'More examples',
    title: 'Contrast: one-window containment',
    text: `on BTCUSDT 15m
find "Wick rejection"
where weekday(nyse_regular) = fri
where session_tail(nyse_regular, last: 1h)
where range_contained(over: 52h, width_max: {4% | 6%})
measure close_return(after: [1h, 4h])`,
    note: 'One trailing 52h envelope with no held timer. It is a different definition from held("Quiet range", for: 48h).',
  },
  {
    id: 'err-syntax',
    group: 'Diagnostics',
    title: 'Syntax error (exact span)',
    text: `on BTCUSDT 15m
find "Wick rejection"
where weekday(nyse_regular) = = fri
measure close_return(after: [1h, 4h])`,
    note: 'The parser reports the offending token with its line and column.',
  },
  {
    id: 'err-signature',
    group: 'Diagnostics',
    title: 'Signature errors (key, unit, domain)',
    text: `on BTCUSDT 15m
find "Wick rejection"
where session_tail(nyse_regular, lst: 30m)
where held("Quiet range", for: 50m)
measure close_return(after: [1h, 4%])`,
    note: 'An unknown key, an off-grid duration and a wrong unit, each with its own span.',
  },
  {
    id: 'err-capability',
    group: 'Diagnostics',
    title: 'Capability error (needs trades)',
    text: `on BTCUSDT 15m
find value_area_reclaim()
measure close_return(after: [1h, 4h])`,
    note: 'A planned, trade-derived capability. OHLCV bars cannot substitute for ordered trades with aggressor side.',
  },
];

export const exampleById = (id) => EXAMPLES.find((e) => e.id === id) || null;
