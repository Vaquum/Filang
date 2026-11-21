import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { buildEnvironment, DATA_FILES, EXTENSION_FILES } from '../src/boot.js';

export const STUDY = fileURLToPath(new URL('../', import.meta.url));
export const DATA = resolve(process.env.FILANG_STUDY_DATA || join(STUDY, '../data/study'));
export const BINARY = resolve(process.env.FILANG_STUDY_BIN || join(STUDY, '../target/release/filang'));
const bindings = new Map([
  ['recorded-bars.csv','recorded-bars.csv'], ['composer/bars','bars'], ['composer/activity','activity'],
]);
const sha256 = bytes => createHash('sha256').update(bytes).digest('hex');
export const inputPath = name => bindings.has(name) ? join(DATA, bindings.get(name)) : join(STUDY, name);
export const inputBytes = name => readFileSync(inputPath(name));

export function loadInputs() {
  const pins = JSON.parse(inputBytes('recording-lock.json'));
  const assets = new Map();
  for (const name of [...bindings.keys(), DATA_FILES.provenance, DATA_FILES.sessions]) {
    const data = inputBytes(name);
    if (sha256(data) !== pins.files[name]) throw Error(name + ' differs from the recorded input pin.');
    assets.set(name,data);
  }
  const bundle = buildEnvironment({
    csvBytes: assets.get(DATA_FILES.bars),
    provenanceBytes: assets.get(DATA_FILES.provenance),
    sessionsBytes: assets.get(DATA_FILES.sessions),
    extensions: EXTENSION_FILES.map(file => ({file, bytes:inputBytes(file)})),
  });
  if (!bundle.digestVerified || bundle.rec.badOhlc || bundle.extensions.some(e => !e.ok))
    throw Error('The pinned recording, calendar or definitions failed validation.');
  return {bundle,assets};
}
