import {FilangEngine} from "./index.mjs";

const engine = FilangEngine.create();
const methods = new Set([
  "version", "inspect", "domain", "load", "loadCsv", "prepare", "release",
  "at", "draw", "counts", "positions",
]);

self.addEventListener("message", async ({data: {id, method, args = []}}) => {
  try {
    if (!methods.has(method)) throw new Error("unknown Filang worker method");
    const session = await engine;
    self.postMessage({id, value: session[method](...args)});
  } catch (error) {
    self.postMessage({id, error: error.message});
  }
});
