import {FilangEngine} from "../../target/engine-dist/browser/index.mjs";
import {openFilangWorker} from "../../target/engine-dist/browser/worker-client.mjs";
import {verifyVectors} from "./vectors.mjs";
import {verifyRadiusVectors} from "./radius-vectors.mjs";

const interval = 900000;
const find = "on BTCUSDT 15m\nfind ";
const shape = "g1:o:0,1,3,4,u;2,3,5,6,u";
const packet = {
  version: 1, revision: "133e3017ba9143f7dc255df7218ff7bfe46d9d06", oriented: true,
  bars: [{v: [15, 20, 40, 50], d: "u"}, {v: [30, 40, 60, 85], d: "u"}],
  pins: [{a: {bar: 0, part: "H"}, b: {bar: 1, part: "H"}}, {bar: 1, color: true}],
  skeleton: 0, stretch: 0, next: {dir: 0, measure: "any", bps: 10, atr: 1}, limit: 12,
};

function equal(actual, expected, label) {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(`${label}: got ${JSON.stringify(actual)}, expected ${JSON.stringify(expected)}`);
  }
}

async function fetchFixture(path, type = "text") {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`fixture ${path} returned ${response.status}`);
  return response[type]();
}

async function verify() {
  const first = await FilangEngine.create();
  const worker = openFilangWorker();
  try {
    const [chained, dims, radius, csv, counters] = await Promise.all([
      fetchFixture("/study/verify/chained-vectors.json", "json"),
      fetchFixture("/study/verify/dimension-vectors.json", "json"),
      fetchFixture("/study/verify/radius-vectors.json", "json"),
      fetchFixture("/fixture/pinned.csv"),
      fetchFixture("/fixture/counters.csv"),
    ]);
    const cases = verifyVectors(first, chained, dims);
    const radiusCases = verifyRadiusVectors(first, radius.vectors);
    equal(await worker.ask("version"), first.version(), "page and worker ABI");
    await worker.ask("loadCsv", csv, interval);
    const source = JSON.stringify(packet);
    const carried = await worker.ask("decodeDrawing", source, shape);
    equal(carried.packet, packet, "Composer packet retained");
    const endpoint = (bar, price) => ({bar, price});
    const rule = (a, b, relation, pin) => pin === undefined
      ? {a, b, relation, source: "skeleton"}
      : {a, b, relation, source: "pin", pin};
    const opening = {
      ...packet,
      bars: [{v: [30, 42, 56, 68], d: "u"}, {v: [18, 36, 56, 80], d: "d"}],
      skeleton: 1,
    };
    const {held_rules, skeleton_marks, skeleton_levels, names} =
      await worker.ask("decodeDrawing", JSON.stringify(opening));
    const o = endpoint(0, "open"), h = endpoint(1, "high"), l = endpoint(1, "low"), c = endpoint(1, "close");
    equal(held_rules, [
      rule(endpoint(0, "high"), h, -1, 0), {bar: 1, colour: -1, source: "pin", pin: 1},
      rule(o, h, -1), rule(o, l, 1), rule(o, c, 1), rule(h, l, 1), rule(h, c, 1),
      rule(l, c, -1), rule(l, endpoint(0, "low"), -1),
    ], "Composer fallback ledger order and provenance");
    equal(skeleton_levels, 1, "Composer number of skeleton levels");
    equal(skeleton_marks, [{...h, strength: 2}, {...l, strength: 2}], "Composer selected swings");
    equal(names, [{id: "bearish-engulfing", start: 0, end: 2}, {id: "outside-bar", start: 0, end: 2}],
      "Composer excludes grouped names and retains named ranges");
    const unoriented = await worker.ask("decodeDrawing", JSON.stringify({
      ...opening, oriented: false, skeleton: 0,
    }));
    equal(unoriented.names, [{id: "outside-bar", start: 0, end: 2}], "Composer hides direction-dependent names");
    equal(unoriented.skeleton_marks, [], "Composer level zero keeps no swings");
    equal(unoriented.skeleton_levels, 1, "Composer reports levels with skeleton disabled");
    equal(await worker.ask("encodeDrawing", packet), source, "legacy packet bytes");
    equal(carried.shape.code, shape, "canonical handoff code");
    const counts = [];
    for (const [reading, want] of [["recorded", 772], ["chained", 1463]]) {
      counts.push((await worker.ask("counts", shape, {reading})).matched);
      equal(counts.at(-1), want, `${reading} count`);
      const op = reading === "recorded" ? "exact_g1" : "chained_g1";
      const query = find + `${op}(${JSON.stringify(shape)})`;
      const study = (await worker.ask("study", query)).results[0];
      equal(study.counts.matches, want, "same result via Query study text");
    }
    const heldQuery = find + carried.pinned_expression;
    const held = (await worker.ask("study", heldQuery)).results[0];
    equal(held.counts.matches, 4828, "Composer pins evaluated by Query");
    const one = find + 'chained_g1("g1:o:0,1,2,2,u")';
    equal(await worker.ask("studyCounts", [one, heldQuery]),
      [324, 4828].map(count => ({count, error: null})), "Query workbench counts");
    const {rows, next} = await worker.ask("studyRows", one, {limit: 1});
    equal(rows.length, 1, "occurrence page");
    if (next <= rows[0].slot) throw new Error("occurrence cursor did not advance");
    const facts = await worker.ask("studyClose", one, rows[0].t);
    equal(facts.event, true, "event detail");
    if (!facts.event_why.includes("matches")) throw new Error("event explanation missing");
    equal((await worker.ask("describeStudy", one)).canonical, one, "canonical question");
    equal((await worker.ask("studyDiagnostics", one)).ok, true, "grammar diagnostics");
    equal((await worker.ask("resolveCandle", "カラカサ")).id, "hammer", "candle alias");
    equal((await worker.ask("geometryShape", shape)).rows, [[1, 4, 0, 3], [3, 6, 2, 5]], "g1 ranks");
    if (!(await worker.ask("studyTerms")).terms.some(term => term.name === "close_return")) {
      throw new Error("missing outcome term");
    }
    await worker.ask("setCalendar");
    equal((await worker.ask("sessionClock", Date.parse("2025-03-28T19:30:00Z"))).text,
      "FRI 15:30 EDT", "pinned NY clock");
    equal((await worker.ask("distance", shape, shape)).half_flips, 0, "zero comparison radius");
    const revised = await worker.ask("encodeDrawing", {...packet, dimensions: ["volume:0,1", "delta:0,2/1"]});
    const expected = shape + "|volume:0,1|delta:0,2/1";
    const decoded = await worker.ask("decodeDrawing", revised, expected);
    equal(decoded.shape.code, expected, "optional dimension axes retained");
    equal(await worker.ask("encodeDrawing", decoded.packet), revised, "dimensioned revision round-trip");
    const malformed = JSON.stringify({...decoded.packet, dimensions: ["delta:0,2/1", "volume:0,1"]});
    try {
      await worker.ask("decodeDrawing", malformed);
      throw new Error("accepted unordered dimension parts");
    } catch (error) {
      if (error.message === "accepted unordered dimension parts") throw error;
    }
    await worker.ask("loadComposerFrame", csv, interval);
    const nearest = await worker.searchComposer({...packet, pins: []}, {timeframes: 1});
    equal(nearest.exact, [1463, 0, 0, 0, 0], "Composer chained exact twins");
    const page = await worker.ask("composerPositions", interval, {limit: 2});
    equal(page.positions.length, 2, "Composer positions");
    equal(page.next, 2, "Composer positions cursor");
    equal(page.positions[0].picks, [0, 1], "Composer consecutive picks");
    const packed = await worker.ask("composerPositionsPacked", interval);
    equal([packed.starts.constructor.name, packed.picks.constructor.name, packed.spans.constructor.name],
      ["Uint32Array", "Uint32Array", "Uint8Array"], "Composer packed typed columns across worker");
    equal([packed.starts.length, packed.picks.length, packed.spans.length], [page.total, page.total, page.total],
      "Composer packed read is complete");
    equal([...packed.starts.subarray(0, 2)], page.positions.map(p => p.start), "Composer packed starts");
    equal([...packed.picks.subarray(0, 2)], [3, 3], "Composer packed picks masks");
    equal([...packed.spans.subarray(0, 2)], [2, 2], "Composer packed spans");
    const allRanked = await worker.ask("composerPositions", null, {kind: "ranked", limit: 3});
    const ranked = await worker.ask("composerPositionsPacked", null, {kind: "ranked"});
    equal(ranked.starts.length, 480, "Composer retains the full heap, including overlaps");
    equal([...ranked.starts.subarray(0, 3)], allRanked.positions.map(p => p.start), "Composer ranking order");
    equal([...ranked.frames.subarray(0, 3)], [0, 0, 0], "Composer packed timeframe indices");
    equal(allRanked.positions.map(p => p.timeframe), [interval, interval, interval], "Composer JSON timeframe");
    equal([...packed.starts.subarray(0, 2)], page.positions.map(p => p.start), "Composer keeps earlier packed reads");
    const ticks = {
      times: Float64Array.of(900, 1800, 3600, 4500), timeUnit: "s",
      open: Int32Array.of(20, 40, 20, 40),
      high: Int32Array.of(50, 85, 50, 85),
      low: Int32Array.of(15, 30, 15, 30),
      close: Int32Array.of(40, 60, 40, 60),
    };
    const drawing = {...packet, pins: []};
    const sparse = "open_ms,open,high,low,close,volume\n" +
      Array.from(ticks.times, (t, i) =>
        [t * 1000, ...["open", "high", "low", "close"].map(k => ticks[k][i] / 100), 0].join(",")).join("\n");
    equal(await worker.ask("loadComposerFrame", sparse, interval), {slots: 5}, "Composer CSV sparse grid");
    const csvResult = await worker.searchComposer(drawing, {timeframes: 1});
    const csvPage = await worker.ask("composerPositions", interval);
    equal(csvPage.positions.map(pos => [pos.start, pos.start_ms, pos.end_ms]),
      [[0, 900000, 2700000], [3, 3600000, 5400000]], "Composer excludes windows over gaps");
    equal(await worker.ask("loadComposerFrameTicks", interval, ticks), {slots: 5}, "Composer tick sparse grid");
    equal(await worker.searchComposer(drawing, {timeframes: 1}), csvResult, "Composer tick search matches CSV");
    equal(await worker.ask("composerPositions", interval), csvPage, "Composer tick times and positions match CSV");
    equal(await worker.ask("loadComposerFrameTicks", interval, {
      ...ticks, times: ticks.times.map(t => t * 1000), timeUnit: "ms",
    }), {slots: 5}, "Composer tick milliseconds");
    for (const invalid of [
      {...ticks, times: Float64Array.of(900, 900, 3600, 4500)},
      {...ticks, times: Float64Array.of(900, 1801, 3600, 4500)},
      {...ticks, high: Int32Array.of(19, 85, 50, 85)},
      {...ticks, close: Float64Array.of(40.5, 60, 40, 60)},
      {...ticks, close: Int32Array.of(40, 60)},
    ]) {
      const accepted = await worker.ask("loadComposerFrameTicks", interval, invalid).then(() => true, () => false);
      equal(accepted, false, "Composer rejects malformed tick columns");
    }
    equal(await worker.searchComposer(drawing, {timeframes: 1}), csvResult, "invalid tick loads preserve the frame");
    await worker.ask("loadCsv", counters, interval);
    const g1 = await worker.ask("counts", expected, {reading: "chained"});
    const query = find + `chained_g1(${JSON.stringify(expected)})`;
    const dimensionedStudy = (await worker.ask("study", query)).results[0];
    equal(dimensionedStudy.counts.matches, g1.matched, "dimensioned Query and Composer counts");
    equal(dimensionedStudy.unknown.event.length, g1.unknown, "dimensioned unknowns");
    const d = radius.vectors[0];
    await worker.ask("load", d.bars);
    equal((await worker.ask("counts", d.code, {radius: 2})).matched,
      d.distances.filter(x => x !== null && x <= 2).length, "worker radius");
    return {cases, radiusCases, counts, pinned: held.counts.matches, dimensioned: g1};
  } finally {
    worker.close();
    first.close();
  }
}

let result;
try { result = {passed: true, ...await verify()}; }
catch (error) { result = {passed: false, error: error.stack}; }
document.querySelector("#result").textContent = JSON.stringify(result);
await fetch("/report", {method: "POST", body: JSON.stringify(result)});
