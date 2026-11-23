import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {FilangEngine} from "../../target/engine-dist/browser/index.mjs";
import {verifyVectors} from "./vectors.mjs";

const engine = await FilangEngine.create(await readFile(
  new URL("../../target/engine-dist/browser/filang_engine.wasm", import.meta.url),
));
try {
  assert.deepEqual(engine.version(), {abi: 1, version: process.argv[2]});
  const vectors = await Promise.all(["chained", "dimension"].map(async (name) =>
    JSON.parse(await readFile(new URL(`../../study/verify/${name}-vectors.json`, import.meta.url))),
  ));
  console.log(`Browser package: ${verifyVectors(engine, ...vectors)} vector cases, ABI 1`);
} finally {
  engine.close();
}
