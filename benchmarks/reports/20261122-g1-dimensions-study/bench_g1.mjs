// Times price-only g1 questions on the pinned recording with the study engine found under <root>.
// node bench_g1.mjs <root>   prints one line of JSON: the times of the measured passes, in ms.
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const root = process.argv[2];
const at = (p) => pathToFileURL(path.join(root, p)).href;
const { loadEnvironment } = await import(at('study/verify/node-env.js'));
const { analyze } = await import(at('study/src/check.js'));
const { runAnalysis } = await import(at('study/src/engine.js'));
const { chainedG1FromRecording, g1FromRecording } = await import(at('study/src/g1.js'));

const first = loadEnvironment();
const top = (bars, read, k) => {
  const counts = new Map();
  for (let i = bars - 1; i < first.rec.n; i++) { const c = read(first.rec, i, bars); if (c) counts.set(c, (counts.get(c) || 0) + 1); }
  return [...counts].sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1)).slice(0, k).map(([c]) => c);
};
const questions = [
  ...top(2, chainedG1FromRecording, 120).map((c) => `chained_g1(${JSON.stringify(c)})`),
  ...top(3, chainedG1FromRecording, 120).map((c) => `chained_g1(${JSON.stringify(c)})`),
  ...top(2, g1FromRecording, 120).map((c) => `exact_g1(${JSON.stringify(c)})`),
  ...top(4, g1FromRecording, 40).map((c) => `exact_g1(${JSON.stringify(c)})`),
];
function pass() {
  const e = loadEnvironment();                        // a fresh context: nothing cached from the pass before
  const t = process.hrtime.bigint();
  let matches = 0;
  for (const q of questions) {
    const a = analyze(`on BTCUSDT 15m\nfind ${q}\nmeasure close_return(after: 1h)`, e.env);
    matches += runAnalysis(e.ctx, a, { extensions: e.extensions, digestVerified: e.digestVerified }).results[0].matches.length;
  }
  return { ms: Number(process.hrtime.bigint() - t) / 1e6, matches };
}
pass(); pass();                                        // warm up
const runs = Array.from({ length: 9 }, pass);
console.log(JSON.stringify({ questions: questions.length, matches: runs[0].matches, ms: runs.map((r) => Math.round(r.ms * 10) / 10) }));
