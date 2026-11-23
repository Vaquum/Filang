function equal(actual, expected, label) {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(`${label}: got ${JSON.stringify(actual)}, expected ${JSON.stringify(expected)}`);
  }
}

const interval = 900000;
const header = "open_ms,open,high,low,close,base_volume,volume,taker_buy_volume,trade_count";
const csv = bars => [header, ...bars.flatMap((row, i) => row ? [[i * interval,
  ...row.slice(0, 4).map(cents => (cents / 100).toFixed(2)), 0, ...row.slice(4)].join(",")] : [])].join("\n");

export function verifyRadiusVectors(engine, vectors) {
  let checks = 0;
  for (const vector of vectors) {
    const {name, bars, width, anchor, reading, oriented, dimensions, code, distances} = vector;
    const options = {reading, oriented, dimensions};
    engine.load(bars);
    equal(engine.at(anchor, width, options).code, code, name);
    for (const [slot, d] of distances.entries()) {
      if (d === null) continue;
      const observed = engine.at(slot, width, options);
      equal(engine.distance(code, observed.code).half_flips, d, name + " distance");
    }
    const radii = [...new Set([0, 1, 2, 4, 8, 16, 64, ...distances.filter(d => d !== null)])].sort((a, b) => a - b);
    let previous = [];
    for (const radius of radii) {
      const outcomes = distances.map(d => d === null ? null : d <= radius);
      const matches = outcomes.flatMap((yes, slot) => yes ? [slot] : []);
      const histogram = distances.reduce((bins, d) => {
        if (d !== null && d <= radius) bins.set(d, (bins.get(d) ?? 0) + 1);
        return bins;
      }, new Map());
      const counts = {matched: matches.length, false_count: outcomes.filter(x => x === false).length,
        unknown: outcomes.filter(x => x === null).length};
      const search = {reading, radius};
      equal(engine.positions(code, search), matches, name + " positions");
      equal(engine.positions(code, {...search, start: 3, limit: 2}),
        matches.filter(slot => slot >= 3).slice(0, 2), name + " page");
      equal(engine.classify(code, search), outcomes, name + " classification");
      equal(engine.counts(code, search), counts, name + " counts");
      const summary = {counts, by_distance: [...histogram].sort((a, b) => a[0] - b[0])};
      equal(engine.neighbourhood(code, search), summary, name + " neighbourhood");
      equal(engine.radiusSeries(code, search), {...summary,
        states: outcomes.map(x => x === null ? "?" : x ? "1" : "0").join("")}, name + " mask");
      if (previous.some(slot => !matches.includes(slot))) throw new Error(name + " radius did not nest");
      previous = matches;
      if (radius === 0) equal(engine.counts(code, {reading}), engine.counts(code, search), name + " exact counts");
      checks++;
    }
    engine.loadCsv(csv(bars), interval);
    const op = reading === "recorded" ? "exact_g1" : "chained_g1";
    const query = radius => `on BTCUSDT 15m\nfind ${op}("${code}"${radius === undefined ? "" : `, radius: ${radius}`})`;
    equal(engine.study(query(0)), engine.study(query()), name + " zero wire output");
    equal(engine.describeStudy(query(0)), engine.describeStudy(query()), name + " canonical zero");
    for (const radius of radii) {
      const expected = distances.flatMap((d, slot) => d !== null && d <= radius ? [(slot + 1) * interval] : []);
      equal(engine.study(query(radius)).results[0].anchors, expected, name + " study anchors");
    }
    const sweep = query("{0 | 1 | 2}");
    equal(engine.study(sweep).results.map(result => result.anchors),
      [0, 1, 2].map(radius => engine.study(query(radius)).results[0].anchors), name + " radius sweep");
  }
  return checks;
}
