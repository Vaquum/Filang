import {FilangEngine} from "./index.mjs";

const engine = FilangEngine.create();
const methods = new Set([
  "version", "memoryBytes", "inspect", "distance", "domain", "load", "loadCsv", "prepare", "release",
  "drawingProtocol", "decodeDrawing", "encodeDrawing", "composerPositions",
  "at", "draw", "drawCounts", "counts", "positions", "classify", "catalogue", "setCalendar", "installDefinition", "check", "study",
]);


let latestComposer = 0;
const yields = [];
const channel = new MessageChannel();
channel.port1.onmessage = () => yields.shift()();
function tick() {
  return new Promise(resolve => {
    yields.push(resolve);
    channel.port2.postMessage(null);
  });
}

async function searchComposer(session, id, args) {
  const current = ++latestComposer;
  session.composerStart(...args);
  let units = 1024;
  for (;;) {
    if (current !== latestComposer) throw new DOMException("Composer search superseded", "AbortError");
    const start = performance.now();
    const step = session.composerStep(units);
    if (step.done) return step;
    const elapsed = performance.now() - start;
    units = Math.max(64, Math.min(8192, units * 2, Math.floor(6 * units / Math.max(elapsed, 0.1))));
    self.postMessage({id, progress: step});
    await tick();
  }
}

self.addEventListener("message", async ({data: {id, method, args = []}}) => {
  try {
    const session = await engine;
    let value;
    if (method === "searchComposer") {
      value = await searchComposer(session, id, args);
    } else if (method === "cancelComposerSearch") {
      ++latestComposer;
      value = session.composerCancel();
    } else if (method === "loadComposerFrame") {
      ++latestComposer;
      value = session.loadComposerFrame(...args);
    } else {
      if (!methods.has(method)) throw new Error("unknown Filang worker method");
      value = session[method](...args);
    }
    self.postMessage({id, value});
  } catch (error) {
    self.postMessage({id, error: error.message, errorName: error.name});
  }
});
