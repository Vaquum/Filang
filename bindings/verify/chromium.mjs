// Run the real browser and its module worker in a fresh local profile.
import {spawn} from "node:child_process";
import {createServer} from "node:http";
import {once} from "node:events";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {fileURLToPath} from "node:url";

const root = fileURLToPath(new URL("../../", import.meta.url));
const [binary, priceFixture, counterFixture, page = "browser.html"] = process.argv.slice(2);
if (!binary || !priceFixture || !counterFixture || !/^[a-z-]+\.html$/.test(page)) {
  throw new Error("usage: chromium.mjs CHROMIUM PRICE_CSV COUNTER_CSV [PAGE]");
}
let resolveReport, rejectReport;
const reply = new Promise((resolve, reject) => {
  resolveReport = resolve;
  rejectReport = reject;
});
const profile = await fs.mkdtemp(path.join(os.tmpdir(), "filang-chromium-"));
const types = {".mjs": "text/javascript", ".js": "text/javascript", ".html": "text/html", ".wasm": "application/wasm",
  ".json": "application/json", ".csv": "text/csv"};
const fixtures = new Map([["/fixture/pinned.csv", priceFixture], ["/fixture/counters.csv", counterFixture]]);
if (process.env.FILANG_BENCH_CORPUS) {
  fixtures.set("/fixture/corpus.json", process.env.FILANG_BENCH_CORPUS);
}
const allowed = ["/bindings/verify/", "/study/verify/", "/study/src/", "/target/engine-dist/browser/"];

const server = createServer(async (req, res) => {
  try {
    const url = new URL(req.url, "http://localhost");
    if (req.method === "POST" && url.pathname === "/report") {
      const chunks = [];
      let bytes = 0;
      for await (const chunk of req) {
        bytes += chunk.length;
        if (bytes > 8_000_000) throw new Error("oversized browser report");
        chunks.push(chunk);
      }
      const report = JSON.parse(Buffer.concat(chunks));
      res.end("ok");
      resolveReport(report);
      return;
    }
    const asset = fixtures.get(url.pathname) ??
      (allowed.some(prefix => url.pathname.startsWith(prefix)) && path.join(root, url.pathname));
    if (!asset) {
      res.writeHead(404).end();
      return;
    }
    const payload = await fs.readFile(asset);
    res.writeHead(200, {"Content-Type": types[path.extname(asset)] ?? "application/octet-stream"});
    res.end(payload);
  } catch {
    res.writeHead(404).end();
  }
});
server.listen(0, "127.0.0.1");
await once(server, "listening");
const port = server.address().port;
const chrome = spawn(binary, ["--headless", "--disable-gpu", "--no-first-run",
  "--disable-background-networking", `--user-data-dir=${profile}`,
  `http://127.0.0.1:${port}/bindings/verify/${page}?first=${process.env.FILANG_BENCH_FIRST === "candidate" ? "candidate" : "base"}`],
  {stdio: ["ignore", "ignore", "inherit"]});
chrome.once("error", rejectReport);
chrome.once("exit", (code, signal) => rejectReport(new Error(`Chromium exited with ${code ?? signal}`)));
const timeout = setTimeout(() => rejectReport(new Error("Chromium proof timed out")), 240000);
try {
  const result = await reply;
  console.log(JSON.stringify(result));
  if (!result.passed) process.exitCode = 1;
} finally {
  clearTimeout(timeout);
  if (chrome.exitCode === null && chrome.signalCode === null) {
    chrome.kill("SIGTERM");
    await once(chrome, "exit");
  }
  server.close();
  await fs.rm(profile, {recursive: true, force: true});
}
