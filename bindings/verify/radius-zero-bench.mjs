import assert from "node:assert/strict";
import {createHash} from "node:crypto";
import {readFile} from "node:fs/promises";
import {resolve} from "node:path";
import {pathToFileURL} from "node:url";

const [build, fixture, edition] = process.argv.slice(2);
if (!build || !fixture || !["base", "candidate"].includes(edition)) {
  throw new Error("usage: radius-zero-bench.mjs BROWSER_DIST COUNTERS_CSV base|candidate");
}
const {FilangEngine} = await import(pathToFileURL(resolve(build, "index.mjs")));
const engine = await FilangEngine.create(await readFile(resolve(build, "filang_engine.wasm")));
const bytes = await readFile(fixture);
const digest = createHash("sha256").update(bytes).digest("hex");
const interval = 900000;
const dimensions = ["volume", "trades", "delta", "size", "imbalance"];
const scenarios = [
  {name: "one", width: 1, reading: "recorded", dimensions: []},
  {name: "two", width: 2, reading: "chained", dimensions: []},
  {name: "two-all-axes", width: 2, reading: "recorded", dimensions},
  {name: "wide", width: 11, reading: "chained", dimensions: ["delta"]},
];
try {
  const {slots} = engine.loadCsv(bytes.toString("utf8"), interval);
  const results = [];
  for (const options of scenarios) {
    const {name, width, reading} = options;
    let anchor = slots - 1;
    let pattern;
    while (!pattern && anchor >= width - 1) {
      pattern = engine.at(anchor--, width, options)?.code;
    }
    assert.ok(pattern, name);
    engine.prepare(width, options);
    const before = engine.counts(pattern, options);
    assert.ok(before.matched > 0, name);
    const search = edition === "candidate" ? {...options, radius: 0} : options;
    const positions = engine.positions(pattern, {...search, limit: 100});
    const classified = engine.classify(pattern, {...search, start: Math.max(0, anchor - 200), limit: 200});
    const query = t => `on BTCUSDT 15m\nfind ${reading === "chained" ? "chained_g1" : "exact_g1"}("${pattern}"${t})`;
    const raw = JSON.stringify(engine.study(query("")));
    if (edition === "candidate") {
      assert.equal(JSON.stringify(engine.study(query(", radius: 0"))), raw);
      assert.deepEqual(engine.counts(pattern, search), before);
    }
    const fingerprint = createHash("sha256").update(raw)
      .update(JSON.stringify([pattern, before, positions, classified])).digest("hex");
    let observed = 0;
    const count = n => {
      for (let i = 0; i < n; i++) observed += engine.counts(pattern, search).matched;
    };
    count(2000);
    const micros = [];
    const repetitions = 8000;
    for (let sample = 0; sample < 5; sample++) {
      const start = performance.now();
      count(repetitions);
      micros.push((performance.now() - start) * 1000 / repetitions);
    }
    assert.equal(observed, before.matched * (2000 + repetitions * micros.length));
    const positive = [];
    if (edition === "candidate") {
      for (const radius of [1, 2, 8]) {
        const start = performance.now();
        const answer = engine.neighbourhood(pattern, {...options, radius});
        positive.push({radius, ms: performance.now() - start, matched: answer.counts.matched});
      }
    }
    results.push({name, fingerprint, counts: before, micros, positive});
  }
  console.log(JSON.stringify({edition, node: process.version, digest, slots, results}));
} finally {
  engine.close();
}
