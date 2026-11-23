import {createHash} from "node:crypto";
import {readFile} from "node:fs/promises";
import {resolve} from "node:path";
import {pathToFileURL} from "node:url";

const [engineDir, composerMatcher, barsFile, mode] = process.argv.slice(2);
if (!barsFile || !["csv", "ticks"].includes(mode)) {
  throw new Error("usage: ingest.mjs ENGINE_DIR COMPOSER_MATCHER BARS csv|ticks");
}
const {FilangEngine} = await import(pathToFileURL(resolve(engineDir, "index.mjs")));
const engine = await FilangEngine.create(await readFile(resolve(engineDir, "filang_engine.wasm")));
const source = await readFile(composerMatcher, "utf8");
const module = Buffer.from(source + "\nexport {frameCsv};").toString("base64");
const {decode, frameCsv} = await import("data:text/javascript;base64," + module);
const input = new Uint8Array(await readFile(barsFile));
const started = performance.now();
const frames = decode(input.buffer);
const decodeMs = performance.now() - started;
let formatMs = 0, ingestMs = 0;
const slots = [];
for (const {ts, O, H, L, C, sec, ...frame} of frames) {
  let result;
  if (mode === "csv") {
    const start = performance.now();
    const csv = frameCsv({...frame, ts, O, H, L, C, sec});
    const formatted = performance.now();
    result = engine.loadComposerFrame(csv, sec * 1000);
    formatMs += formatted - start;
    ingestMs += performance.now() - formatted;
  } else {
    const start = performance.now();
    result = engine.loadComposerFrameTicks(sec * 1000, {
      times: ts, open: O, high: H, low: L, close: C, timeUnit: "s",
    });
    ingestMs += performance.now() - start;
  }
  slots.push(result.slots);
}

const hash = createHash("sha256");
const packet = {
  version: 1, revision: engine.drawingProtocol().plain, oriented: true,
  bars: [{v: [30, 42, 56, 68], d: "u"}, {v: [18, 36, 56, 80], d: "d"}],
  pins: [], skeleton: 0, stretch: 0, limit: 12, next: {dir: 0, measure: "any", bps: 10, atr: 1},
};
for (const question of [packet, {...packet, pins: [{bar: 0, color: true}], stretch: 4}]) {
  engine.composerStart(question, {timeframes: 31, radius: 2});
  let answer;
  do { answer = engine.composerStep(); } while (!answer.done);
  hash.update(JSON.stringify(answer));
  for (const {sec} of frames) {
    for (const kind of ["exact", "held", "within", ...answer.near.map((_, i) => "near:" + i)]) {
      const {starts} = engine.composerPositionsPacked(sec * 1000, {kind});
      hash.update(new Uint8Array(starts.buffer));
    }
  }
  hash.update(new Uint8Array(engine.composerPositionsPacked(null, {kind: "ranked"}).starts.buffer));
}

console.log(JSON.stringify({
  mode, bars: frames.reduce((total, frame) => total + frame.n, 0), slots,
  decodeMs, formatMs, ingestMs, totalMs: formatMs + ingestMs, digest: hash.digest("hex"),
}));
engine.close();
