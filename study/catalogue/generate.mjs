// Lower Composer's pinned declarative rules into the native study instruction set.
import fs from "node:fs";
import "../composer/patterns.js";
import {FUNCTIONS, NAMED} from "../src/registry.js";

const operators = {"==": "eq", "!=": "ne", "<": "lt", "<=": "le", ">": "gt", ">=": "ge"};
const operand = (x) => Array.isArray(x) ? `${x[1]}*${x[2]}` : x;
function emit(spec) {
  if (spec.all || spec.any) {
    const key = spec.all ? "all" : "any";
    return [`${key}:${spec[key].length}`, ...spec[key].flatMap(emit)];
  }
  return [operators[spec[0]], operand(spec[1]), operand(spec[2])];
}
const functions = FUNCTIONS.filter((entry) => entry.patternId);
const named = Object.entries(NAMED);
const patterns = globalThis.CandlePatterns.patterns.map((entry) => {
  const def = functions.find((fn) => fn.patternId === entry.id);
  return {
    ...entry,
    function: def.name,
    labels: named.filter(([, value]) => value.def === def.name).map(([label]) => label),
    instruction: ["pattern", entry.bars, ...emit(entry.spec)].join(" "),
  };
});
const text = JSON.stringify({schema: "filang-candles-v1", patterns}, null, 2) + "\n";
const path = new URL("./candles.json", import.meta.url);
if (process.argv.includes("--check")) {
  if (fs.readFileSync(path, "utf8") !== text) throw new Error("Filang candle catalogue is stale");
} else {
  fs.writeFileSync(path, text);
}

const {SessionCalendar} = await import("../src/data.js");
const calendar = new SessionCalendar(JSON.parse(fs.readFileSync(
  new URL("../nyse-sessions.json", import.meta.url), "utf8",
)));
const rows = [[calendar.covStart, calendar.covEnd],
  ...calendar.sessions.map(({dayStart, close, weekday}) => [dayStart, close, weekday])];
const table = rows.map((row) => row.join("\t")).join("\n") + "\n";
const calendarPath = new URL("./nyse.tsv", import.meta.url);
if (process.argv.includes("--check")) {
  if (fs.readFileSync(calendarPath, "utf8") !== table) throw new Error("Filang calendar is stale");
} else {
  fs.writeFileSync(calendarPath, table);
}
