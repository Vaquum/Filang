// Builds the evaluation environment from raw file bytes. Shared by the browser and Node.

import { parseRecording, SessionCalendar, sha256Hex, dateUTC } from './data.js';
import { Registry, RECORDING_CAPABILITIES } from './registry.js';
import { registerExtension } from './check.js';
import { EvalContext } from './engine.js';
import { runConformance } from './conformance.js';

export const DATA_FILES = Object.freeze({
  bars: 'recorded-bars.csv',
  provenance: 'data-provenance.json',
  sessions: 'nyse-sessions.json',
});

export const EXTENSION_FILES = Object.freeze(['extensions/quiet_friday_close.v1.json', 'extensions/quiet_friday_close.v2.json']);

/** Calendar names usable in queries, bound to pinned tables. */
export const CALENDAR_BINDINGS = Object.freeze([
  { name: 'nyse_regular', file: DATA_FILES.sessions, description: 'NYSE regular (core) session, pinned table' },
]);

export function buildEnvironment({ csvBytes, provenanceBytes, sessionsBytes, extensions = [] }) {
  const dec = new TextDecoder('utf-8');
  const provenance = JSON.parse(dec.decode(provenanceBytes));
  const digest = sha256Hex(csvBytes);
  const digestVerified = digest === provenance.csv_sha256;
  const rec = parseRecording(dec.decode(csvBytes), provenance, digest);
  const sessionsDigest = sha256Hex(sessionsBytes);
  const cal = new SessionCalendar(JSON.parse(dec.decode(sessionsBytes)), sessionsDigest);
  const calendars = new Map([[CALENDAR_BINDINGS[0].name, cal]]);
  const registry = new Registry();
  registry.caps = new Set(rec.VOL ? [...RECORDING_CAPABILITIES, 'bars.counters'] : RECORDING_CAPABILITIES);
  const env = {
    registry,
    calendars,
    recording: {
      instrument: rec.instrument,
      venue: rec.venue,
      barMs: rec.barMs,
      barText: rec.barText,
      rangeText: `${dateUTC(rec.t0)} → ${dateUTC(rec.lastClose - 1)} UTC`,
      caps: registry.caps,
    },
  };
  const ctx = new EvalContext(rec, calendars);
  const bundle = { provenance, rec, cal, calendars, registry, env, ctx, digest, digestVerified, sessionsDigest, extensions: [] };
  for (const input of extensions) {
    const record = installExtension(bundle, input);
    if (!record.ok) bundle.extensions.push(record);
  }
  return bundle;
}

/** Stage the version and run its recorded cases before exposing it to queries. */
export function installExtension(bundle, { file, bytes }) {
  const text = new TextDecoder('utf-8').decode(bytes);
  const record = { file, text, sha256: sha256Hex(bytes), artifact: null, name: null, version: null, def: null };
  const fail = (errors) => ({ ...record, ok: false, errors });
  try {
    const artifact = JSON.parse(text);
    record.artifact = artifact;
    const staging = new Registry();
    staging.functions = new Map(bundle.registry.functions);
    staging.named = new Map(bundle.registry.named);
    staging.caps = bundle.registry.caps;
    const env = { ...bundle.env, registry: staging };
    const registered = registerExtension(staging, artifact, env);
    if (!registered.ok) return fail(registered.errors);
    if (!Array.isArray(artifact.conformance) || !artifact.conformance.length) return fail(['extension needs recorded conformance cases']);
    const results = runConformance({ ...bundle, env }, registered.def);
    const errors = results.filter((r) => !r.pass).map((r) => `${r.anchor}: expected ${r.expect}, observed ${r.got} (${r.why})`);
    if (errors.length) return fail(errors);
    bundle.registry.addFunction(registered.def);
    bundle.registry.extensions.push(registered.def);
    const installed = { ...record, ...registered, name: registered.def.name, version: registered.def.version };
    bundle.extensions.push(installed);
    return installed;
  } catch (e) {
    return fail([String(e.message || e)]);
  }
}
