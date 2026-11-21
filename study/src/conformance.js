// Runs an extension artifact's recorded conformance cases with the same checker and engine.

import { parseExpression } from './lang.js';
import { Checker } from './check.js';
import { compileBool, KNAME } from './engine.js';

export function evaluateConditionText(bundle, text, anchorIso) {
  const { env, ctx, rec } = bundle;
  const { ast, error } = parseExpression(text);
  if (error) return { error: error.message };
  const errs = [];
  const plan = new Checker(env, (d) => errs.push(d)).expr(ast);
  if (!plan || errs.length) return { error: errs.map((e) => e.message).join('; ') || 'not a condition' };
  const slot = rec.slotClosingAt(Date.parse(anchorIso));
  if (slot === null || slot < 0 || slot >= rec.n) return { error: `anchor ${anchorIso} is not a bar close in the recording` };
  const r = compileBool(ctx, plan).at(slot);
  return { v: r.v, got: KNAME[r.v], why: r.why, parts: r.parts || [], plan };
}

export function runConformance(bundle, def) {
  const cases = (def.artifact && def.artifact.conformance) || [];
  return cases.map((c) => {
    const argText = Object.entries(c.args || {}).map(([k, v]) => `${k}: ${v}`).join(', ');
    const call = `${def.name}(${argText})`;
    const r = evaluateConditionText(bundle, call, c.anchor);
    return { ...c, call, got: r.error ? 'error' : r.got, pass: !r.error && r.got === c.expect, why: r.error || r.why, parts: r.parts || [] };
  });
}
