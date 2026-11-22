import {openFilangWorker} from "../../target/engine-dist/browser/worker-client.mjs";
import {parseG1, matchesG1, matchesChainedG1} from "../../study/src/g1.js";

const axes = ["volume", "trades", "delta", "size", "imbalance"];
const interval = 900000;
const edit = document.querySelector("#edit");
const output = document.querySelector("#result");
const time = () => performance.now();
const frame = () => new Promise(requestAnimationFrame);

function record(csv) {
  const bars = [];
  let start;
  for (const line of csv.trim().split("\n").slice(1)) {
    const [t, o, h, l, c, , volume, buy, trades] = line.split(",").map(Number);
    start ??= t;
    const i = (t - start) / interval;
    if (!Number.isInteger(i) || i < bars.length) throw new Error("invalid fixture grid");
    while (bars.length < i) bars.push(null);
    bars.push([o, h, l, c, volume, buy, trades]);
  }
  return bars;
}

function legacyRecording(bars) {
  const rec = {
    n: bars.length,
    O: new Float64Array(bars.length), H: new Float64Array(bars.length),
    L: new Float64Array(bars.length), C: new Float64Array(bars.length),
    present: new Uint8Array(bars.length),
  };
  for (const [i, bar] of bars.entries()) {
    if (bar) {
      [rec.O[i], rec.H[i], rec.L[i], rec.C[i]] = bar;
      rec.present[i] = 1;
    }
  }
  return rec;
}

function baseline(rec, code, reading) {
  const pattern = parseG1(code);
  const scratch = new Float64Array(pattern.rankCount);
  const fits = reading === "chained" ? matchesChainedG1 : matchesG1;
  let matched = 0;
  let unknown = 0;
  let consecutive = 0;
  for (let i = 0; i < rec.n; i++) {
    consecutive = rec.present[i] ? consecutive + 1 : 0;
    if (consecutive < pattern.rows.length) unknown++;
    else if (fits(rec, i - pattern.rows.length + 1, pattern, scratch)) matched++;
  }
  return {matched, false_count: rec.n - matched - unknown, unknown};
}

function readings(row) {
  const [, , , , volume, buy, trades] = row;
  const delta = 2 * buy - volume;
  return [volume, trades, delta, trades ? volume / trades : NaN, volume ? delta / volume : NaN];
}

function ranks(values) {
  const levels = [...new Set(values)].sort((a, b) => a - b);
  return values.map(x => levels.indexOf(x));
}

function reference(bars, width, dimensions, reading, want) {
  let matched = 0;
  let unknown = 0;
  for (let i = 0; i < bars.length; i++) {
    if (i + 1 < width) { unknown++; continue; }
    const rows = bars.slice(i + 1 - width, i + 1);
    if (rows.includes(null)) { unknown++; continue; }
    const parts = [];
    for (const axis of dimensions) {
      const j = axes.indexOf(axis);
      const values = rows.map(row => readings(row)[j]);
      if (values.some(Number.isNaN)) break;
      const signed = axis === "delta" || axis === "imbalance";
      const order = ranks(signed ? [...values, 0] : values);
      parts.push(`${axis}:${signed ? order.slice(0, -1).join(",") + "/" + order.at(-1) : order.join(",")}`);
    }
    if (parts.length !== dimensions.length) { unknown++; continue; }
    const prices = [];
    const dirs = [];
    for (const [j, [o, h, l, c]] of rows.entries()) {
      const open = reading === "chained" && j ? rows[j - 1][3] : o;
      prices.push(Math.min(l, open), Math.min(open, c), Math.max(open, c), Math.max(h, open));
      dirs.push(open < c ? "u" : open > c ? "d" : "z");
    }
    const order = ranks(prices);
    const price = dirs.map((d, j) => [...order.slice(j * 4, (j + 1) * 4), d].join(",")).join(";");
    if ([`g1:o:${price}`, ...parts].join("|") === want) matched++;
  }
  return {matched, false_count: bars.length - matched - unknown, unknown};
}

function equal(actual, expected, context) {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) throw new Error(
    `${context}: ${JSON.stringify(actual)} differs from ${JSON.stringify(expected)}`,
  );
}

const json = async (path) => fetch(path).then(response => response.json());
const text = async (path) => fetch(path).then(response => response.text());

async function run() {
  const [price, counter, corpus] = await Promise.all([
    text("/fixture/pinned.csv"), text("/fixture/counters.csv"), json("/fixture/corpus.json"),
  ]);
  const worker = openFilangWorker();
  const rec = legacyRecording(record(price));
  let start = time();
  await worker.ask("loadCsv", price, interval);
  const priceLoadMs = time() - start;
  const pricePrepares = [];
  for (const [width, reading] of [[2, "recorded"], [2, "chained"], [3, "chained"], [4, "recorded"]]) {
    start = time();
    await worker.ask("prepare", width, {reading});
    pricePrepares.push({width, reading, ms: time() - start});
  }
  const trials = {base: [], candidate: []};
  const order = new URL(location.href).searchParams.get("first") === "candidate"
    ? ["candidate", "base"] : ["base", "candidate"];
  for (const side of order) {
    const elapsed = [];
    const answers = [];
    for (const q of corpus) {
      start = time();
      answers.push(side === "base" ? baseline(rec, q.code, q.reading)
        : await worker.ask("counts", q.code, {reading: q.reading}));
      elapsed.push(time() - start);
    }
    trials[side] = {elapsed, answers};
  }
  equal(trials.candidate.answers, trials.base.answers, "price-only workload");
  const pricePeakWasmBytes = await worker.ask("memoryBytes");
  const bars = record(counter);
  start = time();
  await worker.ask("loadCsv", counter, interval);
  const loadMs = time() - start;
  const prepares = [];
  const widths = [2, 4, 12, 24];
  const modes = ["recorded", "chained"];
  for (const width of widths) {
    for (const reading of modes) {
      start = time();
      await worker.ask("prepare", width, {reading, dimensions: axes});
      prepares.push({width, reading, ms: time() - start});
    }
  }
  const cases = [];
  for (let step = 0; step < 300; step++) {
    const width = widths[step % widths.length];
    const reading = modes[Math.floor(step / widths.length) % modes.length];
    const dimensions = [[], ["volume", "delta"], axes][Math.floor(step / 8) % 3];
    const end = width - 1 + (step * 2017 + 191) % (bars.length - width);
    const encoded = await worker.ask("at", end, width, {reading, dimensions});
    if (!encoded) continue;
    const rows = bars.slice(end + 1 - width, end + 1);
    const marks = Object.fromEntries(dimensions.map(axis => [
      axis, rows.map(row => readings(row)[axes.indexOf(axis)]),
    ]));
    cases.push({width, reading, dimensions, code: encoded.code,
      ohlc: rows.map(row => row.slice(0, 4)), marks});
  }
  if (cases.length < 300) throw new Error("too few complete edit windows");
  for (let i = 0; i < cases.length; i += 19) {
    const q = cases[i];
    equal(await worker.ask("counts", q.code, {reading: q.reading}),
      reference(bars, q.width, q.dimensions, q.reading, q.code), "recorded count oracle");
  }
  const absent = await worker.ask("draw", [[0, 0, 0, 0], [1, 1, 1, 1]]);
  const absentExpected = reference(bars, 2, [], "recorded", absent.code);
  equal(absentExpected.matched, 0, "control is unobserved");
  equal(await worker.ask("counts", absent.code), absentExpected, "unobserved count");
  const edits = [];
  const workerEdits = [];
  edit.oninput = async (event) => {
    const {q, resolve, reject} = event.detail;
    const began = time();
    try {
      const result = await worker.ask("drawCounts", q.ohlc, {reading: q.reading, axes: q.marks});
      equal(result.shape.code, q.code, "editing and reading the same window");
      output.textContent = result.counts.matched;
      workerEdits.push(time() - began);
      await frame();
      resolve(time() - began);
    } catch (error) { reject(error); }
  };
  const varied = new URL(location.href).searchParams.get("arrival") === "varied";
  for (const [i, q] of cases.entries()) {
    if (varied) await new Promise(resolve => setTimeout(resolve, (i * 7) % 16));
    const elapsed = await new Promise((resolve, reject) =>
      edit.dispatchEvent(new CustomEvent("input", {detail: {q, resolve, reject}})));
    edits.push(elapsed);
  }
  const memoryBytes = await worker.ask("memoryBytes");
  worker.close();
  return {
    bars: bars.length,
    loadMs, prepares, edits, workerEdits, memoryBytes,
    parityChecks: 1 + Math.ceil(cases.length / 19),
    price: {
      loadMs: priceLoadMs, prepares: pricePrepares, memoryBytes: pricePeakWasmBytes,
      matches: trials.base.answers.reduce((sum, result) => sum + result.matched, 0),
      base: trials.base.elapsed, candidate: trials.candidate.elapsed,
    },
  };
}

let report;
try { report = {passed: true, ...await run()}; }
catch (error) { report = {passed: false, error: error.stack}; }
await fetch("/report", {method: "POST", body: JSON.stringify(report)});
