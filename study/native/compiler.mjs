// Check the builder request and send source to Filang’s shared compiler.
import { analyze } from '../src/check.js';
import { Registry } from '../src/registry.js';
import { installSaved } from '../src/study-extensions.js';

export class QueryError extends Error {
  constructor(kind, message, diagnostics = []) {
    super(message);
    this.kind = kind;
    this.diagnostics = diagnostics;
  }
}

export function compile(bundle, { query, source, calendar, extensions = [], candidate } = {}) {
  if (source !== bundle.digest || calendar !== bundle.sessionsDigest) {
    throw new QueryError('pins', 'The recording or calendar digest differs from the service.');
  }
  if (typeof query !== 'string' || !Array.isArray(extensions)) {
    throw new QueryError('query', 'Supply a query string and an array of pinned definitions.');
  }
  let env = bundle.env;
  if (extensions.length) {
    const registry = new Registry();
    registry.functions = new Map(bundle.registry.functions);
    registry.named = new Map(bundle.registry.named);
    registry.extensions = [...bundle.registry.extensions];
    env = { ...env, registry };
    try {
      installSaved({...bundle, registry, env, extensions:[...bundle.extensions]}, extensions.map((x,i) => ({
        file: 'query definition ' + (i + 1),
        text: x?.text,
        sha256: x?.sha256,
      })));
    } catch (e) {
      throw new QueryError('pins', e.message);
    }
  }
  const checked = analyze(query, env);
  if (!checked.ok) {
    const first = checked.errors[0];
    throw new QueryError(first.kind === 'capability' ? 'capability' : 'query', first.message, checked.errors);
  }
  if (candidate !== undefined && (!Number.isInteger(candidate) || !checked.candidates[candidate])) {
    throw new QueryError('query', 'Candidate is outside the checked study.');
  }
  const plans = candidate === undefined ? checked.candidates : [checked.candidates[candidate]];
  // The CLI evaluates just the selected candidate when one is requested.
  // The browser API can also retain the full batch plan for its receipts.
  const sourceText = candidate === undefined ? query : plans[0].resolvedText;
  const wire = JSON.stringify({ query: sourceText, extensions });
  if (Buffer.byteLength(wire) + 1 > 1_048_576) throw new QueryError('query', 'The study request exceeds 1 MiB.');
  return { wire, canonical: checked.canonical, candidates: plans.map(c => c.label) };
}
