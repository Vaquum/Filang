// Same pinned price-only questions as Filang #73.
import {loadInputs} from "../../../study/native/inputs.mjs";
import {compile} from "../../../study/native/compiler.mjs";
import {chainedG1FromRecording, g1FromRecording} from "../../../study/src/g1.js";

const {bundle} = loadInputs();
const {rec} = bundle;
function top(width, read, cap) {
  const counts = new Map();
  for (let i = width - 1; i < rec.n; i++) {
    const code = read(rec, i, width);
    if (code) counts.set(code, (counts.get(code) ?? 0) + 1);
  }
  return [...counts].sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1))
    .slice(0, cap).map(([code]) => code);
}
const questions = [];
for (const [width, reading, cap] of [[2, "chained", 120], [3, "chained", 120],
    [2, "recorded", 120], [4, "recorded", 40]]) {
  const chained = reading === "chained";
  for (const code of top(width, chained ? chainedG1FromRecording : g1FromRecording, cap)) {
    const op = chained ? "chained_g1" : "exact_g1";
    const query = `on BTCUSDT 15m\nfind ${op}(${JSON.stringify(code)})\nmeasure close_return(after: 1h)`;
    const {wire} = compile(bundle, {query, source: bundle.digest, calendar: bundle.sessionsDigest});
    questions.push({width, reading, code, wire});
  }
}
process.stdout.write(JSON.stringify(questions));
