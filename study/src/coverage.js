// Coverage of the Quiet range width parameter on recorded bars — counts only, never returns.
// This is the evidence behind the 2% choice shown in the page.

import { parseExpression } from './lang.js';
import { Checker, analyze } from './check.js';
import { compileBool, runCandidate, T } from './engine.js';

function shareOf(bundle, exprText) {
  const { ast } = parseExpression(exprText);
  const errs = [];
  const plan = new Checker(bundle.env, (d) => errs.push(d)).expr(ast);
  if (!plan || errs.length) throw new Error(errs.map((e) => e.message).join('; '));
  const c = compileBool(bundle.ctx, plan);
  let t = 0;
  for (let i = 0; i < bundle.rec.n; i++) if (c.at(i).v === T) t++;
  return t;
}

export const COVERAGE_WIDTHS = ['1%', '1.5%', '2%', '2.5%', '3%', '4%'];

export const STARTER_WITH_WIDTH = (w) => `on BTCUSDT 15m
find "Wick rejection"
where weekday(nyse_regular) = fri
where session_tail(nyse_regular, last: {30m | 1h})
where held(quiet_range(width_max: ${w}), for: 48h)
measure close_return(after: [1h, 4h])`;

export function quietCoverage(bundle, widths = COVERAGE_WIDTHS) {
  return widths.map((w) => {
    const stateTrue = shareOf(bundle, `quiet_range(width_max: ${w})`);
    const heldTrue = shareOf(bundle, `held(quiet_range(width_max: ${w}), for: 48h)`);
    const a = analyze(STARTER_WITH_WIDTH(w), bundle.env);
    if (!a.ok) throw new Error(a.errors.map((e) => e.message).join('; '));
    const counts = a.candidates.map((c) => runCandidate(bundle.ctx, c).matches.length);
    return { width: w, bars: bundle.rec.n, stateTrue, heldTrue, starter30m: counts[0], starter1h: counts[1] };
  });
}
