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
    const dropAxes = {reading, oriented: false};
    const projected = engine.at(anchor, width, dropAxes).code;
    for (const [slot, d] of distances.entries()) {
      if (d === null) continue;
      const observed = engine.at(slot, width, options);
      equal(engine.distance(code, observed.code).half_flips, d, name + " distance");
      const projectedWindow = engine.at(slot, width, dropAxes).code;
      if (engine.distance(projected, projectedWindow).half_flips > d) {
        throw new Error(name + " projection increased distance");
      }
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
  const two = vectors.find(v => v.reading === "chained" && v.dimensions.length === 5);
  const bars = two.bars.slice(two.anchor + 1 - two.width, two.anchor + 1);
  const packet = {
    version: 1, revision: "bd6a0ba32e18548b641267418491bfb5f011a274", oriented: true,
    bars: bars.map(([o, h, l, c], i) => {
      if (i) o = bars[i - 1][3];
      return {v: [Math.min(l, o), Math.min(o, c), Math.max(o, c), Math.max(h, o)], d: c >= o ? "u" : "d"};
    }),
    dimensions: two.code.split("|").slice(1),
    pins: [], skeleton: 0, stretch: 0, limit: 12, next: {dir: 0, measure: "any", bps: 10, atr: 1},
  };
  engine.loadComposerFrame(csv(two.bars), interval);
  const compare = radius => {
    engine.composerStart(packet, {timeframes: 1, radius});
    let result;
    do { result = engine.composerStep(); } while (!result.done);
    const want = two.distances.flatMap((d, i) => d !== null && d <= radius ? [i] : []);
    equal(engine.composerPositions(interval, {kind: "within"}).positions.map(p => p.start + two.width - 1),
      want, "Composer radius positions");
    const packed = engine.composerPositionsPacked(interval, {kind: "within"});
    equal(Array.from(packed.starts, (start, i) => start + packed.spans[i] - 1),
      want, "Composer packed radius positions");
    equal(radius ? result.within[0] : result.exact[0], want.length, "Composer radius count");
    for (const resultWindow of result.results) {
      const {window, half_flips} = resultWindow;
      equal(half_flips, two.distances[window.start + window.span - 1], "Composer distance");
    }
  };
  [0, 1, 2, 4, 8, 16, 64].forEach(compare);
  return checks;
}
