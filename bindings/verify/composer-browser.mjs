import {openFilangWorker} from "../../target/engine-dist/browser/worker-client.mjs";

const frames = ["15m", "30m", "1h", "2h", "4h"];
const ms = [900000, 1800000, 3600000, 7200000, 14400000];
const colour = {bar: 0, color: true};
const scenarios = [
  ["default", 2, [], 0, 31, true], ["default-repeat", 2, [], 0, 31, true],
  ["2-bars-only-4h", 2, [], 0, 16, true], ["10-bars", 10, [], 0, 31, true],
  ["20-bars", 20, [], 0, 31, true], ["20-bars-shape-only", 20, [], 0, 31, false],
  ["2-bars-pin", 2, [colour], 0, 31, true], ["5-bars-pin-stretch-0", 5, [colour], 0, 31, true],
  ["5-bars-pin-stretch-4", 5, [colour], 4, 31, true], ["10-bars-pin-stretch-4", 10, [colour], 4, 31, true],
  ["20-bars-pin-stretch-4", 20, [colour], 4, 31, true],
];

function packet(n, pins, stretch, oriented = true) {
  let c = 42;
  const bars = Array.from({length: n}, (_, i) => {
    const open = c;
    c += i % 3 === 1 ? -18 : 14;
    const a = Math.min(open, c), b = Math.max(open, c);
    return {v: [a - 12, a, b, b + 12], d: c >= open ? "u" : "d"};
  });
  return {version: 1, revision: "133e3017ba9143f7dc255df7218ff7bfe46d9d06", oriented, bars,
    pins, stretch, skeleton: 0, limit: 12, next: {dir: 0, measure: "any", bps: 10, atr: 1}};
}

const worker = openFilangWorker();
let report;
try {
  const csvs = await Promise.all(frames.map(async frame => {
    const response = await fetch(`/fixture/tape-${frame}.csv`);
    if (!response.ok) throw new Error(`missing Composer fixture ${frame}`);
    return response.text();
  }));
  const loadStarted = performance.now();
  const loaded = [];
  for (const [i, csv] of csvs.entries()) loaded.push(await worker.ask("loadComposerFrame", csv, ms[i]));
  const loadMs = performance.now() - loadStarted;
  const timings = [];
  const failures = [];
  for (const [name, n, pins, stretch, timeframes, oriented] of scenarios) {
    let scanned = 0, gaps = 0, maxGap = 0;
    const started = performance.now();
    let previous = started;
    const sample = () => {
      const now = performance.now();
      maxGap = Math.max(maxGap, now - previous);
      previous = now;
    };
    const value = await worker.searchComposer(packet(n, pins, stretch, oriented), {timeframes,
      onProgress(update) {
        if (update.scanned < scanned || update.scanned > update.total) {
          failures.push(`${name} returned invalid progress`);
        }
        scanned = update.scanned;
        sample();
        gaps++;
      },
    });
    sample();
    const elapsed = previous - started;
    timings.push({name, elapsed, maxGap, gaps, exact: value.exact, held: value.held});
    if (elapsed >= 5000 || maxGap >= 100 || !gaps || !value.results.length) failures.push(name);
  }
  const cancellation = [];
  for (const width of [5, 20]) {
    const started = performance.now();
    const stale = worker.searchComposer(packet(width, [colour], 4)).then(
      () => ({staleResult: true, elapsed: performance.now() - started}),
      error => ({error: error.name, elapsed: performance.now() - started}),
    );
    await new Promise(resolve => setTimeout(resolve, 10));
    const latest = worker.searchComposer(packet(2, [], 0));
    const old = await stale;
    cancellation.push({width, ...old});
    if (old.error !== "AbortError" || old.elapsed >= 100) failures.push(`cancel ${width}`);
    if (!(await latest).results.length) failures.push(`replacement ${width}`);
  }
  report = {passed: failures.length === 0, userAgent: navigator.userAgent, loadMs, loaded, timings, cancellation, failures};
} catch (error) {
  report = {passed: false, error: error.stack};
} finally {
  worker.close();
}
document.querySelector("#result").textContent = JSON.stringify(report);
await fetch("/report", {method: "POST", body: JSON.stringify(report)});
