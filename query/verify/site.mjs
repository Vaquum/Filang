// Stands in for the bench's server when its modules run under Node: site paths become the repository's files.
// /shared and /bench are this folder's; /engine is the engine's browser package, as bindings/build.py leaves it or
// from the folder FILANG_QUERY_ENGINE_DIR names, as for the server; /recording is the pinned recording and its
// provenance, as query/serve.mjs hands them out.
import { readFile } from 'node:fs/promises';
import { register } from 'node:module';
import { resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

/** The repository these checks stand in. */
export const ROOT = fileURLToPath(new URL('../../', import.meta.url));
/** The folder of the engine's browser package these checks run on. */
export const engineDir = () => resolve(ROOT, process.env.FILANG_QUERY_ENGINE_DIR || 'target/engine-dist/browser');
/** The pinned recording, where study/prepare_recording.py writes it. */
export const recordingFile = () => resolve(process.env.FILANG_STUDY_DATA || resolve(ROOT, 'data/study'), 'recorded-bars.csv');

export async function install() {
  const base = pathToFileURL(ROOT).href;
  const engine = pathToFileURL(engineDir() + '/').href;
  register('data:text/javascript,' + encodeURIComponent(`
    const root = ${JSON.stringify(base)};
    const engine = ${JSON.stringify(engine)};
    export function resolve(spec, context, next) {
      if (spec.startsWith('/shared/') || spec.startsWith('/bench/')) return { url: new URL('query' + spec, root).href, shortCircuit: true };
      if (spec.startsWith('/engine/')) return { url: new URL(spec.slice(8), engine).href, shortCircuit: true };
      return next(spec, context);
    }`), import.meta.url);
  const files = { '/recording/bars.csv': pathToFileURL(recordingFile()).href, '/recording/provenance.json': 'study/data-provenance.json' };
  const web = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    const url = String(input instanceof URL ? input.href : input);
    const file = files[url] ? new URL(files[url], base) : url.startsWith('file:') ? new URL(url) : null;
    if (!file) return url.startsWith('/') ? new Response('Not found', { status: 404 }) : web(input, init);
    return new Response(await readFile(file));
  };
}
