// Loads the supplied files from disk (read-only) and builds the same environment the browser uses.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { buildEnvironment, DATA_FILES, EXTENSION_FILES } from '../src/boot.js';

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
import { inputBytes } from '../native/inputs.mjs';

export const readBytes = (f) => new Uint8Array(inputBytes(f));

export function loadEnvironment() {
  return buildEnvironment({
    csvBytes: readBytes(DATA_FILES.bars),
    provenanceBytes: readBytes(DATA_FILES.provenance),
    sessionsBytes: readBytes(DATA_FILES.sessions),
    extensions: EXTENSION_FILES.filter((f) => fs.existsSync(path.join(ROOT, f))).map((f) => ({ file: f, bytes: readBytes(f) })),
  });
}
