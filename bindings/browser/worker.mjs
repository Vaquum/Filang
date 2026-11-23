import {FilangEngine} from "./index.mjs";

const engine = FilangEngine.create();
const methods = new Set([
  "version", "memoryBytes", "inspect", "geometryShape", "distance", "domain", "load", "loadCsv", "prepare", "release",
  "drawingProtocol", "decodeDrawing", "encodeDrawing",
  "at", "draw", "drawCounts", "counts", "neighbourhood", "positions", "classify", "catalogue", "setCalendar", "installDefinition", "check", "study", "studyCounts",
  "studyRows", "studyClose", "sessionClock", "studyTerms", "resolveCandle", "describeStudy", "studyDiagnostics",
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
