// Before/after comparison of two candidate results: membership, reasons, changed clauses.

import { printExpr } from './lang.js';
import { T, KNAME } from './engine.js';

function clauseTexts(ast) {
  return {
    find: printExpr(ast.find),
    wheres: ast.wheres.map((w) => printExpr(w)),
    group: ast.group ? printExpr(ast.group) : null,
    measures: ast.measures.map((m) => printExpr(m)),
  };
}

function lcsPairs(a, b) {
  const m = a.length;
  const n = b.length;
  const d = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
  for (let i = m - 1; i >= 0; i--) for (let j = n - 1; j >= 0; j--) d[i][j] = a[i] === b[j] ? d[i + 1][j + 1] + 1 : Math.max(d[i + 1][j], d[i][j + 1]);
  const pairs = [];
  let i = 0;
  let j = 0;
  while (i < m && j < n) {
    if (a[i] === b[j]) { pairs.push([i, j]); i++; j++; } else if (d[i + 1][j] >= d[i][j + 1]) i++; else j++;
  }
  return pairs;
}

/** Clause-level changes from basis to current (resolved candidate ASTs). */
export function clauseChanges(basisAst, curAst) {
  const A = clauseTexts(basisAst);
  const B = clauseTexts(curAst);
  const out = [];
  if (A.find !== B.find) out.push({ slot: 'find', from: A.find, to: B.find });
  const listDiff = (slot, a, b) => {
    if (a.length === b.length) {
      a.forEach((x, k) => { if (x !== b[k]) out.push({ slot, index: k, from: x, to: b[k] }); });
      return;
    }
    const pairs = lcsPairs(a, b);
    const inA = new Set(pairs.map((p) => p[0]));
    const inB = new Set(pairs.map((p) => p[1]));
    a.forEach((x, k) => { if (!inA.has(k)) out.push({ slot, index: k, from: x, to: null }); });
    b.forEach((x, k) => { if (!inB.has(k)) out.push({ slot, index: k, from: null, to: x }); });
  };
  listDiff('where', A.wheres, B.wheres);
  if (A.group !== B.group) out.push({ slot: 'group by', from: A.group, to: B.group });
  listDiff('measure', A.measures, B.measures);
  return out;
}

export function describeChange(c) {
  const where = c.slot === 'where' || c.slot === 'measure' ? `${c.slot} #${c.index + 1}` : c.slot;
  if (c.from === null) return `${where} added: ${c.to}`;
  if (c.to === null) return `${where} removed: ${c.from}`;
  return `${where}: ${c.from} → ${c.to}`;
}

function failing(result, row) {
  return row.results
    .map((r, k) => ({ k, text: result.clauses[k].text, v: r.v, why: r.why }))
    .filter((x) => x.v !== T);
}

/** Map clause index in `from` to its counterpart in `to` (index-wise if counts match, else LCS on text). */
function alignClauses(from, to) {
  const a = from.clauses.map((c) => c.text);
  const b = to.clauses.map((c) => c.text);
  const map = new Map();
  if (a.length === b.length) a.forEach((_, k) => map.set(k, k));
  else for (const [i, j] of lcsPairs(a, b)) map.set(i, j);
  return map;
}

/** Why a row is a match in `inResult` but not in `outResult` (same anchor slot). */
function reasonFor(row, inResult, outResult, outToIn) {
  const other = outResult.rowsBySlot.get(row.i);
  if (!other) {
    const v = outResult.event.series.vals[row.i];
    return [{ side: 'detector', text: `${outResult.event.text} is ${KNAME[v]} at this bar: ${outResult.event.series.why(row.i)}` }];
  }
  return failing(outResult, other).map((x) => {
    const k2 = outToIn.has(x.k) ? outToIn.get(x.k) : -1;
    const now = k2 >= 0 ? row.results[k2] : null;
    return {
      side: 'clause',
      clause: `where #${x.k + 1} ${x.text}`,
      v: x.v,
      text: `${KNAME[x.v]}: ${x.why}`,
      other: now ? { clause: `where #${k2 + 1} ${inResult.clauses[k2].text}`, v: now.v, text: `${KNAME[now.v]}: ${now.why}` } : null,
    };
  });
}

/**
 * Compare basis → current. Membership is keyed by stable occurrence identity when both use the
 * same detector; otherwise by anchor time (labelled as such).
 */
export function compareResults(basis, cur, labels = {}) {
  const sameDetector = basis.event.identity === cur.event.identity;
  const key = sameDetector ? (r) => r.id : (r) => r.t;
  const bSet = new Map(basis.matches.map((r) => [key(r), r]));
  const cSet = new Map(cur.matches.map((r) => [key(r), r]));
  const basisToCur = alignClauses(basis, cur);
  const curToBasis = alignClauses(cur, basis);
  const added = cur.matches.filter((r) => !bSet.has(key(r))).map((r) => ({ row: r, reasons: reasonFor(r, cur, basis, basisToCur) }));
  const removed = basis.matches.filter((r) => !cSet.has(key(r))).map((r) => ({ row: r, reasons: reasonFor(r, basis, cur, curToBasis) }));
  const kept = cur.matches.filter((r) => bSet.has(key(r)));
  return {
    mode: sameDetector ? 'occurrence identity' : 'anchor time (detectors differ)',
    sameDetector,
    basisLabel: labels.basis || basis.cand.label,
    curLabel: labels.cur || cur.cand.label,
    changes: clauseChanges(basis.cand.resolvedAst, cur.cand.resolvedAst),
    added, removed, kept,
    status: (r) => (cSet.has(key(r)) ? (bSet.has(key(r)) ? 'kept' : 'added') : bSet.has(key(r)) ? 'removed' : null),
    addedKeys: new Set(added.map((a) => key(a.row))),
    removedKeys: new Set(removed.map((a) => key(a.row))),
    keyOf: key,
  };
}
