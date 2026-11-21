import { readFile } from 'node:fs/promises';
import { compile } from './native/compiler.mjs';
import { loadInputs } from './native/inputs.mjs';
import { startWorker } from './native/worker.mjs';

const [file] = process.argv.slice(2);
if (!file) throw Error('Pass a file containing a Filang study query.');
const {bundle,assets} = loadInputs();
const query = await readFile(file,'utf8');
const plan = compile(bundle,{query, source:bundle.digest, calendar:bundle.sessionsDigest});
const worker = await startWorker(bundle,assets.get('recorded-bars.csv'));
try {
  const result = await worker.evaluate(plan.wire);
  if (result.error) throw Error(result.error);
  console.log(JSON.stringify({...result, query:plan.canonical, labels:plan.candidates,
    source:bundle.digest, calendar:bundle.sessionsDigest}));
} finally { worker.close(); }
