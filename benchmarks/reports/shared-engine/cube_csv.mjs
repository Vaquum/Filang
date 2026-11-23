// Use Query's existing decoder to preserve the bridge's binary64 counters.
import {readFile, writeFile} from "node:fs/promises";
import {createHash} from "node:crypto";
import {decodeMscb} from "../../../query/cube.mjs";

const [input, output] = process.argv.slice(2);
const raw = await readFile(input);
const capture = JSON.parse(raw);
const {origin_seconds: origin, base_seconds: base, width, first, last} = capture;
const price = (value) => {
  const ticks = Math.round(value * 100);
  if (ticks <= 0 || !Number.isSafeInteger(ticks) || Math.abs(value * 100 - ticks) > 1e-6) {
    throw new Error("Cube price is outside the exact cent grid");
  }
  return (ticks / 100).toFixed(2);
};
const lines = ["open_ms,open,high,low,close,base_volume,volume,taker_buy_volume,trade_count"];
let previous = first / width - 1;
for (const payload of capture.blocks) {
  const block = decodeMscb(payload);
  if (block.n !== 4) throw new Error("unexpected Cube level");
  for (let i = 0; i < block.count; i++) {
    const slot = block.col[i];
    if (slot <= previous || slot < first / width || slot >= last / width) {
      throw new Error("unexpected Cube grid order");
    }
    previous = slot;
    const values = [block.btc[i], block.vol[i], block.tbvol[i], block.cnt[i]];
    if (values.some(x => !Number.isFinite(x) || x < 0) ||
        !Number.isSafeInteger(values[3]) || values[2] > values[1]) {
      throw new Error("invalid Cube counters");
    }
    lines.push([Math.round((origin + slot * width * base) * 1000),
      ...[block.open[i], block.high[i], block.low[i], block.close[i]].map(price),
      ...values.map(String),
    ].join(","));
  }
}
if (lines.length !== 66001) throw new Error("Cube capture does not have 66,000 bars");
const csv = lines.join("\n") + "\n";
const sha = (bytes) => createHash("sha256").update(bytes).digest("hex");
await writeFile(output, csv);
console.log(JSON.stringify({
  rows: lines.length - 1, canonical_through: capture.canonical_through,
  from: new Date((origin + first * base) * 1000).toISOString(),
  through: new Date((origin + last * base) * 1000).toISOString(),
  capture_sha256: sha(raw), csv_sha256: sha(csv),
}));
