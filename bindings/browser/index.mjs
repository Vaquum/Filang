const ABI = 1;
const BAR_SIZE = 57;
const encoder = new TextEncoder();
const decoder = new TextDecoder();

const mode = (oriented) => oriented ? "oriented" : "unoriented";
const names = (dimensions) => dimensions.join(",");
const fields = (...values) => values.join("\t");

/** One recording and its lazily prepared windows. Works in a page or a worker. */
export class FilangEngine {
  #wasm;
  #handle;

  static async create(source = new URL("./filang_engine.wasm", import.meta.url)) {
    const input = source instanceof URL || typeof source === "string"
      ? await fetch(source).then((response) => {
          if (!response.ok) throw new Error(`Filang WebAssembly returned HTTP ${response.status}`);
          return response.arrayBuffer();
        })
      : source;
    const wasm = await WebAssembly.instantiate(input, {});
    return new FilangEngine((wasm.instance ?? wasm).exports);
  }

  constructor(wasm) {
    if (wasm.filang_abi_version() !== ABI) throw new Error("unsupported Filang engine ABI");
    this.#wasm = wasm;
    this.#handle = wasm.filang_session_new();
  }

  close() {
    if (this.#handle) this.#wasm.filang_session_drop(this.#handle);
    this.#handle = 0;
  }

  memoryBytes() { return this.#wasm.memory.buffer.byteLength; }
  version() { return this.#call("version"); }
  catalogue() { return this.#call("catalogue"); }
  inspect(code) { return this.#call("inspect", code); }
  geometryShape(code) { return this.#call("geometry-shape", code); }
  distance(left, right) { return this.#call("distance", fields(left, right)); }

  domain(width, {oriented = true, dimensions = []} = {}) {
    return this.#call("domain", fields(width, mode(oriented), names(dimensions)));
  }

  /** Rows are OHLC, with optional USDT volume, taker-buy USDT and trades. Null is a grid gap. */
  load(bars) {
    if (bars.length > 1_000_000) throw new RangeError("Filang recording exceeds 1,000,000 slots");
    const data = new DataView(new ArrayBuffer(bars.length * BAR_SIZE));
    for (let i = 0; i < bars.length; i++) {
      const bar = bars[i];
      if (bar === null) continue;
      if ((bar.length !== 4 && bar.length !== 7) || !bar.every(Number.isFinite)) {
        throw new TypeError(`invalid Filang bar at slot ${i}`);
      }
      const offset = i * BAR_SIZE;
      data.setUint8(offset, bar.length === 4 ? 1 : 2);
      for (let j = 0; j < bar.length; j++) data.setFloat64(offset + 1 + 8 * j, bar[j], true);
    }
    return this.#call("load", new Uint8Array(data.buffer));
  }

  loadCsv(csv, intervalMs, {instrument = "BTCUSDT"} = {}) {
    return this.#call("load-csv", `${fields(intervalMs, instrument)}\n${csv}`);
  }

  setCalendar(tsv = "", {table} = {}) {
    return table === undefined ? this.#call("calendar", tsv)
      : this.#call("calendar-named", `${table}\n${tsv}`);
  }

  installDefinition(text, sha256) {
    return this.#call("install-definition", `${sha256}\n${text}`);
  }
  check(query) { return this.#call("check", query); }

  study(query, {candidate = null} = {}) {
    return this.#call("study", `${candidate ?? "-"}\n${query}`);
  }

  studyCounts(queries) { return this.#call("study-counts", JSON.stringify(queries)); }

  studyRows(query, {candidate = 0, start = 0, limit = 4096} = {}) {
    return this.#call("study-rows", `${fields(candidate, start, limit)}\n${query}`);
  }

  studyClose(query, t, {candidate = 0} = {}) {
    return this.#call("study-close", `${fields(candidate, t)}\n${query}`);
  }

  sessionClock(t) { return this.#call("session-clock", String(t)); }

  prepare(width, {oriented = true, reading = "recorded", dimensions = []} = {}) {
    return this.#call("prepare", fields(width, mode(oriented), reading, names(dimensions)));
  }

  release(width) { return this.#call("release", String(width)); }

  at(end, width, {oriented = true, reading = "recorded", dimensions = []} = {}) {
    return this.#call("at", fields(end, width, mode(oriented), reading, names(dimensions)));
  }

  draw(bars, options) { return this.#drawing("draw", bars, options); }
  drawCounts(bars, options) { return this.#drawing("draw-counts", bars, options); }

  #drawing(operation, bars, {oriented = true, reading = "recorded", axes = {}} = {}) {
    const rows = [fields(mode(oriented), reading, bars.length)];
    for (const bar of bars) rows.push(fields(...bar));
    for (const [axis, marks] of Object.entries(axes)) rows.push(fields(axis, ...marks));
    return this.#call(operation, rows.join("\n"));
  }

  drawingProtocol() { return this.#call("drawing-protocol"); }

  decodeDrawing(packet, expectedCode = "") {
    return this.#call("read-drawing", `${expectedCode}\n${packet}`);
  }

  encodeDrawing(packet) {
    const protocol = this.drawingProtocol();
    const revision = packet.dimensions?.length ? protocol.dimensioned : protocol.plain;
    const marked = {...packet, version: protocol.version, revision};
    if (revision === protocol.plain) delete marked.dimensions;
    const text = JSON.stringify(marked);
    this.decodeDrawing(text);
    return text;
  }

  counts(code, {reading = "recorded"} = {}) { return this.#call("counts", fields(reading, code)); }

  positions(code, {reading = "recorded", start = 0, limit = 100} = {}) {
    return this.#call("positions", fields(reading, start, limit, code));
  }

  classify(code, {reading = "recorded", start = 0, limit = 4096} = {}) {
    return this.#call("classify", fields(reading, start, limit, code));
  }

  #call(operation, payload = "") {
    if (!this.#handle) throw new Error("Filang engine is closed");
    const wasm = this.#wasm;
    const head = encoder.encode(operation + "\n");
    const tail = typeof payload === "string" ? encoder.encode(payload) : payload;
    const len = head.length + tail.length;
    const ptr = wasm.filang_alloc(len);
    if (!ptr) throw new RangeError("Filang request exceeds its buffer limit");
    try {
      const request = new Uint8Array(wasm.memory.buffer, ptr, len);
      request.set(head);
      request.set(tail, head.length);
      const status = wasm.filang_call(this.#handle, ptr, len);
      const out = wasm.filang_output(this.#handle);
      const outLen = wasm.filang_output_len(this.#handle);
      const value = decoder.decode(new Uint8Array(wasm.memory.buffer, out, outLen));
      if (status !== 0) throw new Error(value);
      return JSON.parse(value);
    } finally {
      wasm.filang_free(ptr, len);
    }
  }
}
