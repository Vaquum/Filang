import {FilangEngine} from "../../target/engine-dist/browser/index.mjs";
import {openFilangWorker} from "../../target/engine-dist/browser/worker-client.mjs";
import {verifyVectors} from "./vectors.mjs";

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
    const [chained, dims, csv, counters] = await Promise.all([
      fetchFixture("/study/verify/chained-vectors.json", "json"),
      fetchFixture("/study/verify/dimension-vectors.json", "json"),
      fetchFixture("/fixture/pinned.csv"),
      fetchFixture("/fixture/counters.csv"),
    ]);
    const cases = verifyVectors(first, chained, dims);
    equal(await worker.ask("version"), first.version(), "page and worker ABI");
    await worker.ask("loadCsv", csv, interval);
    const source = JSON.stringify(packet);
    const carried = await worker.ask("decodeDrawing", source, shape);
    equal(carried.packet, packet, "Composer packet retained");
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
    await worker.ask("loadCsv", counters, interval);
    const g1 = await worker.ask("counts", expected, {reading: "chained"});
    const query = find + `chained_g1(${JSON.stringify(expected)})`;
    const dimensionedStudy = (await worker.ask("study", query)).results[0];
    equal(dimensionedStudy.counts.matches, g1.matched, "dimensioned Query and Composer counts");
    equal(dimensionedStudy.unknown.event.length, g1.unknown, "dimensioned unknowns");
    return {cases, counts, pinned: held.counts.matches, dimensioned: g1};
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
