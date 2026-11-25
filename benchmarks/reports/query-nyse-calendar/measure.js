// How the Query bench's session conditions resolve on Cube's windows, with the engine's pinned table and with a
// nyse_regular table from field-data-api. Paste into the developer console of the Query bench (query.vaquum.fi),
// signed in. It uses a fresh engine of its own, so the page's state is untouched, and reads the bars the page reads.
//
// `tsv` is the table to compare. Once this change is deployed:
//   const { tsv, table } = await (await fetch('/calendar/nyse')).json();
// Before that, run `node query/verify/calendar.mjs --print <field-data-api origin>` and paste the lines after its JSON.
// `measure(tsv, table, ['30d', '180d'])` answers, per window, [true, false, unknown] closes for each condition.
async function measure(tsv, table, windows = ['30d', '180d', '1y', 'ytd', 'lastyear', 'all']) {
  const { FilangEngine } = await import('/engine/index.mjs');
  const engine = await FilangEngine.create();
  const question = (where) => `on BTCUSDT 15m\nfind candle_relation(price(high), is: at_or_above, right: price(low))\nwhere ${where}`;
  const conditions = ['weekday(nyse_regular) = fri', 'session_tail(nyse_regular, last: 1h)'];
  const stats = () => conditions.map((where) => engine.studyRows(question(where), { limit: 1 }).clause_stats[0]);
  const start = Number(tsv.split('\t')[0]);
  const out = {};
  for (const window of windows) {
    const bars = await (await fetch(`/bars?w=${window}`, { cache: 'no-store' })).json();
    const barMs = bars.provenance.interval_ms;
    const closes = bars.csv.trimEnd().split('\n').slice(1).map((line) => Number(line.slice(0, line.indexOf(','))) + barMs);
    engine.loadCsv(bars.csv, barMs, { instrument: 'BTCUSDT' });
    engine.setCalendar();
    const pinned = { calendar: engine.describeStudy(question(conditions[0])).manifest.pins.calendars, conditions: stats() };
    engine.setCalendar(tsv, { table });
    const field = { calendar: engine.describeStudy(question(conditions[0])).manifest.pins.calendars, conditions: stats() };
    out[window] = {
      from: bars.provenance.from, through: bars.provenance.through, rows: bars.provenance.row_count, csv_sha256: bars.provenance.csv_sha256,
      closes: closes.length, closes_before_table: closes.filter((t) => t < start).length, pinned, field,
    };
  }
  return out;
}
