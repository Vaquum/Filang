// Engine adapter. Everything the bench shows is asked of the shared Filang engine, which the server hands the page
// at /engine/. The bench keeps no checker and no evaluator of its own: this file loads the bars into the engine and
// turns the engine's answers into the shapes the bench draws.
import { FilangEngine } from '/engine/index.mjs';
import { readRecording } from '/shared/recording.js';

/** The page's one engine session. Importing this module waits for it. */
export const engine = await FilangEngine.create();

export const T = 1;
export const F = 0;
export const U = -1;
const tri = (v) => (v === true ? T : v === false ? F : U);

export const HEAD = 'on BTCUSDT 15m';
// The language requires an event in `find`. This relation holds on every recorded candle.
export const ANY_CLOSE = 'candle_relation(price(high), is: at_or_above, right: price(low))';
/** The pinned recording, as a window key. Every other key is one of Cube's time windows. */
export const PINNED = 'pinned';

const pad = (x) => String(x).padStart(2, '0');
export function isoUTC(ms) {
  const d = new Date(ms);
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}Z`;
}
export const dateUTC = (ms) => new Date(ms).toISOString().slice(0, 10);
export const hmUTC = (ms) => { const d = new Date(ms); return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`; };

// ---------------------------------------------------------------- what the engine publishes

/** The engine's named candles: id, name, ja, bars, rule and aliases. */
export const CANDLES = engine.catalogue().patterns;
/** The id of the candle a name, alias or translation means; null when it names none. */
export const candleNamed = (name) => engine.resolveCandle(name).id;
const TERMS = new Map(engine.studyTerms().terms.map((t) => [t.name, t]));
/** A term's title, summary and formula, as the engine states them. */
export const definition = (name) => TERMS.get(name) ?? null;

// A drawing is read by the engine: its g1, the packet as the engine keeps it, and the relations held on it as text.
const drawn = new WeakMap();
const drawnText = new Map();
function reading(packet) {
  let d = drawn.get(packet);
  if (d) return d;
  const text = JSON.stringify(packet);
  d = drawnText.get(text);
  if (!d) {
    d = engine.decodeDrawing(text);
    if (drawnText.size >= 64) drawnText.delete(drawnText.keys().next().value);
    drawnText.set(text, d);
  }
  drawn.set(packet, d);
  return d;
}
/** The packet a drawing's text holds. Throws when the engine cannot read it, or when it is not the g1 expected. */
export function decodeDrawing(text, expected) {
  const d = engine.decodeDrawing(text, expected ?? '');
  drawn.set(d.packet, d);
  return d.packet;
}
export const drawingG1 = (packet) => reading(packet).shape.code;
/** The relations held on a drawing, as one Filang expression; null when it holds none. */
export const pinnedExpression = (packet) => reading(packet).pinned_expression ?? null;
/** The revision a plain drawing packet is marked with. */
export const drawingRevision = () => engine.drawingProtocol().plain;
/** A g1's ranks per bar as [low, body low, body high, high], how many ranks there are, and its directions. Throws on a bad code. */
export const shapeOf = (code) => engine.geometryShape(code);

// ---------------------------------------------------------------- bars

let bundle = null;
let held = null;
const runs = new Map();
const tallies = new Map();
const receipts = new Map();

/** What this server can read: { cube, default, windows: [{ key, name }] }. Without a cube, the pinned recording only. */
export async function sources() {
  try {
    const r = await fetch('/bars/windows', { cache: 'no-store' });
    if (r.ok) return await r.json();
  } catch { /* an older server, or none: the pinned recording */ }
  return { cube: false, default: PINNED, windows: [] };
}

async function pinned() {
  const get = async (name) => { const r = await fetch('/recording/' + name, { cache: 'no-cache' }); if (!r.ok) throw Error(`${name}: ${r.status}`); return r; };
  const [csv, provenance] = await Promise.all([get('bars.csv').then((r) => r.text()), get('provenance.json').then((r) => r.json())]);
  return { csv, provenance };
}
async function fromCube(window) {
  const answer = await fetch('/bars?w=' + encodeURIComponent(window), { cache: 'no-store' });
  const body = await answer.json().catch(() => null);
  if (!answer.ok || !body?.csv) throw Error(body?.error || `bars: ${answer.status}`);
  return { csv: body.csv, provenance: body.provenance };
}

/** Load the bars the bench reads: the pinned recording, or one of Cube's windows from the cube itself. */
export async function load(window = PINNED) {
  if (bundle && held === window) return bundle;
  const { csv, provenance } = window === PINNED ? await pinned() : await fromCube(window);
  const rec = readRecording(csv, provenance);
  // The engine holds one recording, and its pinned calendar is set again for each. It keeps the bars it has when it
  // refuses new ones; bars it took but the charts read differently are put out again for the ones on screen.
  const give = (text, r) => { const { slots } = engine.loadCsv(text, r.barMs, { instrument: r.instrument }); engine.setCalendar(); return slots; };
  const slots = give(csv, rec);
  if (slots !== rec.n) {
    if (bundle) give(bundle.csv, bundle.rec);
    throw Error(`the engine reads ${slots} slots where the charts read ${rec.n}`);
  }
  runs.clear(); tallies.clear(); receipts.clear();
  const digest = engine.describeStudy(`${HEAD}\nfind ${ANY_CLOSE}`).manifest.pins.source.csv_sha256;
  bundle = { rec, csv, provenance, digest, digestVerified: digest === provenance.csv_sha256, rangeText: `${dateUTC(rec.t0)} → ${dateUTC(rec.lastClose - 1)} UTC` };
  held = window;
  return bundle;
}

/** The window the loaded bars cover. */
export const loaded = () => held;
/** The loaded bars' provenance, the digest the engine took of them, and whether it is the one the provenance names. */
export const env = () => bundle;
export const rec = () => bundle.rec;

// ---------------------------------------------------------------- questions

const PAGE = 4096;

class Clause {
  constructor(owner, t, k, v) { this.owner = owner; this.t = t; this.k = k; this.v = v; }
  get why() { return this.owner.close(this.t).where_why[this.k]; }
}
class Outcome {
  constructor(owner, t, k, o) { this.owner = owner; this.t = t; this.k = k; this.status = o.status; this.value = o.value; }
  get why() { return this.owner.close(this.t).outcome_why[this.k]; }
}

/** One run of a question: one candidate of its compared values. Its rows are read from the engine when first asked for. */
class Result {
  #text; #timed; #head; #rows; #bySlot; #matches; #groups; #summary; #whole; #vals; #columns; #closes = new Map();

  constructor(text, cand, timed) {
    this.#text = text; this.#timed = timed; this.cand = cand;
    const lines = cand.resolvedText.split('\n');
    const of = (word) => lines.filter((l) => l.startsWith(word + ' ')).map((l) => l.slice(word.length + 1));
    this.lines = { find: of('find')[0], wheres: of('where'), group: of('group by')[0] ?? null };
  }

  #page(start) { return this.#timed(() => engine.studyRows(this.#text, { candidate: this.cand.index, start, limit: PAGE })); }
  #first() { return this.#head ??= this.#page(0); }
  #study() { return this.#whole ??= this.#timed(() => engine.study(this.#text, { candidate: this.cand.index })).results[0]; }
  /** Everything the engine says about one close: the event, each line, the group, the outcomes, and why. */
  close(t) {
    let c = this.#closes.get(t);
    if (!c) {
      c = this.#timed(() => engine.studyClose(this.#text, t, { candidate: this.cand.index }));
      if (this.#closes.size >= 256) this.#closes.delete(this.#closes.keys().next().value);
      this.#closes.set(t, c);
    }
    return c;
  }

  /** Every close where the pattern occurs, with each line's verdict on it, in time order. */
  get rows() {
    if (this.#rows) return this.#rows;
    const rows = [];
    for (let page = this.#first(); ; page = this.#page(page.next)) {
      for (const r of page.rows) rows.push({
        i: r.slot, t: r.t, failAt: r.fail_at, pass: r.fail_at === -1, detector: T, group: r.group, reclaim: r.reclaim ?? null,
        results: r.where.map((v, k) => new Clause(this, r.t, k, tri(v))),
        out: r.out.map((o, k) => new Outcome(this, r.t, k, o)),
      });
      if (page.next === null) break;
    }
    return this.#rows = rows;
  }
  get rowsBySlot() { return this.#bySlot ??= new Map(this.rows.map((r) => [r.i, r])); }
  get matches() { return this.#matches ??= this.rows.filter((r) => r.pass); }

  /** T: closes where the pattern occurs. U: recorded closes where the engine cannot say. */
  get counts() {
    const study = () => this.#study();
    return { T: this.#first().event_count, get U() { return study().unknown.event.length; } };
  }
  get survivors() { return this.#first().survivors; }
  get clauseStats() { return this.#first().clause_stats.map(([t, f, u]) => ({ T: t, F: f, U: u })); }

  /** The answer divided by the question's group; null when it has none. An empty unknown group is left out. */
  get groups() {
    if (this.lines.group === null) return null;
    if (this.#groups) return this.#groups;
    const by = new Map(this.#first().group_labels.map((g) => [g.key, { key: g.key, label: g.label, rows: [] }]));
    for (const r of this.matches) by.get(r.group ?? 'unknown')?.rows.push(r);
    return this.#groups = [...by.values()].filter((g) => g.key !== 'unknown' || g.rows.length).map((g) => ({ ...g, count: g.rows.length }));
  }
  /** Per measured column, over the answer: how many outcomes were observed, how many were positive, their median and mean. */
  get summary() {
    return this.#summary ??= this.columns.map((_, k) => {
      // summed in time order, as the reference engine summed them, so the mean is the same to the last bit
      let sum = 0; let n = 0; let positive = 0;
      for (const r of this.matches) { const o = r.out[k]; if (o.status === 'observed') { sum += o.value; n++; if (o.value > 0) positive++; } }
      const v = observed(this.matches, k); const mid = n >> 1;
      return { observed: n, positive, median: n ? (n % 2 ? v[mid] : (v[mid - 1] + v[mid]) / 2) : null, mean: n ? sum / n : null };
    });
  }
  get group() { return this.lines.group === null ? null : { at: (i) => ({ key: this.close(bundle.rec.closeTime(i)).group ?? 'unknown' }) }; }

  /** One column per measured horizon, named by its duration. */
  get columns() {
    if (this.#columns) return this.#columns;
    const measures = this.#timed(() => engine.describeStudy(this.cand.resolvedText)).ast.measures;
    const texts = measures.flatMap((m) => { const v = (m.args.find((a) => a.name === 'after') ?? m.args[0])?.value; return (v?.k === 'vec' ? v.items : [v]).map((x) => x?.text ?? m.name); });
    return this.#columns = texts.map((text) => ({ text }));
  }

  get event() {
    const rows = () => this.rows; const cache = (v) => (v === undefined ? this.#vals : (this.#vals = v));
    return { text: this.lines.find, series: {
      /** T at each slot where the pattern occurs. */
      get vals() { if (!cache()) { const v = new Int8Array(bundle.rec.n); for (const r of rows()) v[r.i] = T; cache(v); } return cache(); },
      why: (i) => this.close(bundle.rec.closeTime(i)).event_why,
      /** The level a reclaim was measured against and the close that breached it; null for any other event. */
      evidence: (i) => { const w = this.rowsBySlot.get(i)?.reclaim; return w ? { level: w.level, breach: w.breach } : null; },
    } };
  }
  get clauses() {
    return this.lines.wheres.map((text, k) => ({ text, at: (i) => { const c = this.close(bundle.rec.closeTime(i)); return { v: tri(c.where[k]), why: c.where_why[k] }; } }));
  }
}

const errorsOf = (text, e) => {
  let errors = [];
  try { errors = engine.studyDiagnostics(text).errors; } catch { /* the engine's own message stands */ }
  return errors.length ? errors : [{ kind: 'engine', message: String(e.message || e) }];
};

/**
 * Ask the engine a full query text. Answers are kept by text. `ms` is the time the engine has spent on this text so far:
 * the first run is evaluated at once, and rows, reasons and further runs are read when the bench first shows them.
 */
export function run(text) {
  if (runs.has(text)) return runs.get(text);
  let spent = 0;
  const timed = (fn) => { const t0 = performance.now(); try { return fn(); } finally { spent += performance.now() - t0; } };
  let out;
  try {
    const d = timed(() => engine.describeStudy(text));
    const results = d.candidates.map((cand) => new Result(text, cand, timed));
    void results[0].counts.T;   // a question these bars cannot answer fails here, not while the bench is drawing
    const source = { ...d.manifest.pins.source, verified: bundle.digestVerified };
    out = { ok: true, text, errors: [], analysis: { axes: d.axes }, results, manifest: { ...d.manifest, pins: { ...d.manifest.pins, source } }, get ms() { return spent; } };
  } catch (e) {
    out = { ok: false, text, errors: errorsOf(text, e), results: [] };
  }
  if (runs.size > 600) runs.delete(runs.keys().next().value);
  runs.set(text, out);
  return out;
}

/** What the engine makes of a text before it is run: its canonical form and syntax tree, or the errors it found. */
export function describe(text) {
  try { const d = engine.describeStudy(text); return { ok: true, canonical: d.canonical, ast: d.ast, errors: [] }; } catch (e) { return { ok: false, errors: errorsOf(text, e) }; }
}

/** Matching closes for a query body (everything after the `on` line); null when it does not check. */
export function count(body) {
  const text = HEAD + '\n' + body;
  if (tallies.has(text)) return tallies.get(text);
  let n = null;
  try { n = engine.studyCounts([text])[0].count; } catch { /* a text the engine cannot read counts nothing */ }
  if (tallies.size > 4000) tallies.delete(tallies.keys().next().value);
  tallies.set(text, n);
  return n;
}

/** How many closes lie at each distance within a comparison radius of a shape: [[half-flips, closes], …]. */
export function geometryRadiusReceipt(code, read, radius) {
  const key = JSON.stringify([code, read, radius]);
  if (!receipts.has(key)) {
    if (receipts.size >= 64) receipts.delete(receipts.keys().next().value);
    receipts.set(key, engine.radiusSeries(code, { reading: read, radius }).by_distance);
  }
  return receipts.get(key);
}

// ---------------------------------------------------------------- formatting

export const int = (n) => n.toLocaleString('en-US');
export const price = (cents) => (cents / 100).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
export function pct(x, digits = 2) {
  if (x === null || x === undefined || Number.isNaN(x)) return '—';
  const v = x * 100;
  const s = Math.abs(v).toFixed(digits);
  return (v > 0 ? '+' : v < 0 ? '−' : '') + s + '%';
}
export const share = (a, b, digits = 0) => (b ? ((a / b) * 100).toFixed(digits) + '%' : '—');

/** The New York session clock at a time, as the engine's pinned calendar has it. */
export const nyText = (t) => engine.sessionClock(t).text;

/** Sorted observed outcome values for column k. */
export function observed(rows, k) {
  const v = [];
  for (const r of rows) if (r.out[k]?.status === 'observed') v.push(r.out[k].value);
  return v.sort((a, b) => a - b);
}
