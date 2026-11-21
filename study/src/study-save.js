// A portable study includes content pins and an independently recomputable population digest.
import { sha256Hex } from './data.js';

const version = 'limen-study/1';
const libraryKey = 'limen.study.library.1';
const hash = (value) => sha256Hex(new TextEncoder().encode(JSON.stringify(value)));

function evidence(result) {
  const digest = (population) =>
    hash(
      population.rows.map((row) => [
        row.t,
        row.group?.key ?? null,
        row.out.map((cell) => [cell.status, cell.value]),
      ]),
    );
  const p = result.populations;
  return hash([
    result.event.identity,
    digest(p.matching),
    digest(p.eligible),
    digest(p.nonmatching),
    digest(p.unknownDetector),
    p.unknownContextAnchors,
    result.counts,
  ]);
}

export function makeStudy(name, run, view) {
  return {
    schema: version,
    name,
    query: run.manifest.query,
    engine: run.manifest.engine.version,
    pins: run.manifest.pins,
    evidence: run.results.map(evidence),
    view,
  };
}

export function checkStudy(saved, run) {
  if (
    saved.schema !== version ||
    !Array.isArray(saved.evidence) ||
    !saved.view ||
    typeof saved.name !== 'string'
  )
    throw Error('Unrecognized saved question.');
  const current = makeStudy(saved.name, run, saved.view);
  if (current.engine !== saved.engine || hash(current.pins) !== hash(saved.pins))
    throw Error('The saved definition, engine, or recording differs from the local version.');
  if (hash(current.evidence) !== hash(saved.evidence))
    throw Error('Replayed cases or outcomes differ from the saved result.');
}

export function studyLink(saved) {
  const u = new URL('./', location.href);
  u.hash = new URLSearchParams({ study: JSON.stringify(saved) }).toString();
  return u.href;
}
export function studyFromLink() {
  const raw = new URLSearchParams(location.hash.slice(1)).get('study');
  if (!raw) return null;
  const saved = JSON.parse(raw);
  if (saved?.schema !== version || typeof saved.query !== 'string' || !saved.view)
    throw Error('Invalid study link.');
  return saved;
}
export function readLibrary() {
  const text = localStorage.getItem(libraryKey);
  if (!text) return [];
  const entries = JSON.parse(text);
  if (!Array.isArray(entries)) throw Error('Saved question library could not be read.');
  return entries;
}
export function saveToLibrary(saved) {
  const entries = readLibrary();
  const same = entries.findIndex((x) => JSON.stringify(x) === JSON.stringify(saved));
  if (same !== -1) entries.splice(same, 1);
  entries.unshift(saved);
  localStorage.setItem(libraryKey, JSON.stringify(entries));
}
