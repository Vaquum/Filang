const ABI = 1;
const BAR_SIZE = 57;
const encoder = new TextEncoder();
const decoder = new TextDecoder();
const littleEndian = new Uint8Array(new Uint32Array([1]).buffer)[0] === 1;

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
  studyTerms() { return this.#call("study-terms"); }
  resolveCandle(name) { return this.#call("resolve-candle", name); }
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

  loadComposerFrame(csv, intervalMs) {
    return this.#call("composer-load", `${intervalMs}\n${csv}`);
  }

  /** Timestamp and OHLC columns in recording order, with prices in integer cents. */
  loadComposerFrameTicks(intervalMs, {times, open, high, low, close, timeUnit = "ms"}) {
    if (!Number.isInteger(intervalMs) || intervalMs <= 0 || intervalMs > 0xffffffff) {
      throw new RangeError("invalid Composer interval");
    }
    if (timeUnit !== "ms" && timeUnit !== "s") {
      throw new RangeError("Composer tick times must use ms or s");
    }
    const columns = [times, open, high, low, close];
    const length = times?.length;
    if (!(length > 0 && length <= 1_000_000)
      || !columns.every(column => ArrayBuffer.isView(column) && column.length === length)) {
      throw new TypeError("expected five equally sized Composer tick columns");
    }
    const buffer = new ArrayBuffer(8 + 5 * 8 * length);
    const header = new DataView(buffer);
    header.setUint32(0, intervalMs, true);
    header.setUint32(4, timeUnit === "s" ? 1000 : 1, true);
    if (littleEndian) {
      const values = new Float64Array(buffer, 8);
      columns.forEach((column, i) => values.set(column, i * length));
    } else {
      columns.forEach((column, i) => {
        for (let row = 0; row < length; row++) {
          header.setFloat64(8 + 8 * (i * length + row), column[row], true);
        }
      });
    }
    return this.#call("composer-load-ticks", new Uint8Array(buffer));
  }

  composerStart(packet, {timeframes = 31, endMasks, radius = 0} = {}) {
    const options = JSON.stringify({timeframes, end_masks: endMasks, radius});
    const drawing = typeof packet === "string" ? packet : JSON.stringify(packet);
    return this.#call("composer-start", `${options}\n${drawing}`);
  }

  composerStep(units = 1024) { return this.#call("composer-step", String(units)); }

  composerCancel() { return this.#call("composer-cancel"); }

  composerPositions(intervalMs, {kind = "exact", start = 0, limit = 4096} = {}) {
    return this.#call("composer-positions", fields(intervalMs === null ? "-" : intervalMs, kind, start, limit));
  }

  composerPositionsPacked(intervalMs, {kind = "exact"} = {}) {
    const all = intervalMs === null;
    const bytes = this.#call("composer-positions-packed", fields(all ? "-" : intervalMs, kind), true);
    const length = bytes.length / (all ? 10 : 9);
    if (!Number.isInteger(length)) throw new Error("invalid packed Composer positions");
    if (!littleEndian) {
      const words = new DataView(bytes.buffer);
      for (let offset = 0; offset < 8 * length; offset += 4) {
        words.setUint32(offset, words.getUint32(offset, true));
      }
    }
    const result = {
      starts: new Uint32Array(bytes.buffer, 0, length),
      picks: new Uint32Array(bytes.buffer, 4 * length, length),
      spans: new Uint8Array(bytes.buffer, 8 * length, length),
    };
    if (all) result.frames = new Uint8Array(bytes.buffer, 9 * length, length);
    return result;
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
  describeStudy(query) { return this.#call("study-describe", query); }
  studyDiagnostics(query) { return this.#call("study-diagnostics", query); }

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

  counts(code, {reading = "recorded", radius = 0} = {}) {
    return radius === 0 ? this.#call("counts", fields(reading, code))
      : this.#call("counts-within", fields(reading, radius, code));
  }

  neighbourhood(code, {reading = "recorded", radius = 0} = {}) {
    return this.#call("neighbourhood", fields(reading, radius, code));
  }

  radiusSeries(code, {reading = "recorded", radius = 0} = {}) {
    return this.#call("radius-series", fields(reading, radius, code));
  }

  positions(code, {reading = "recorded", start = 0, limit = 100, radius = 0} = {}) {
    return radius === 0 ? this.#call("positions", fields(reading, start, limit, code))
      : this.#call("positions-within", fields(reading, start, limit, radius, code));
  }

  classify(code, {reading = "recorded", start = 0, limit = 4096, radius = 0} = {}) {
    return radius === 0 ? this.#call("classify", fields(reading, start, limit, code))
      : this.#call("classify-within", fields(reading, start, limit, radius, code));
  }

  #call(operation, payload = "", packed = false) {
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
      const bytes = new Uint8Array(wasm.memory.buffer, out, outLen);
      if (status !== 0) throw new Error(decoder.decode(bytes));
      if (packed) return bytes.slice();
      return JSON.parse(decoder.decode(bytes));
    } finally {
      wasm.filang_free(ptr, len);
    }
  }
}
