// Compile the same checked plans the builder displays into one native batch.
import { analyze } from '../src/check.js';
import { Registry } from '../src/registry.js';
import { installSaved } from '../src/study-extensions.js';

const compare = new Map([['==','eq'],['!=','ne'],['>','gt'],['>=','ge'],['<','lt'],['<=','le']]);
const operand = (x) => Array.isArray(x) ? x[1] + '*' + x[2] : x;
function specification(x) {
  if (x.all || x.any) {
    const key = x.all ? 'all' : 'any';
    return [key + ':' + x[key].length, ...x[key].flatMap(specification)];
  }
  return [compare.get(x[0]), operand(x[1]), operand(x[2])];
}
const ratio = ({rat}) => rat.num + '/' + rat.den;
const priceRelation = {
  above:'gt', at_or_above:'ge', below:'lt', at_or_below:'le', equal:'eq', unequal:'ne',
};

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
  const nodes = new Map();
  function intern(tokens) {
    const text = tokens.join(' ');
    if (!nodes.has(text)) nodes.set(text, nodes.size);
    return nodes.get(text);
  }
  function emit(node) {
    if (node.body) return emit(node.body);
    if (node.op === 'and' || node.op === 'or') return intern([node.op,...node.items.map(emit)]);
    if (node.op === 'not') return intern(['not', emit(node.item)]);
    if (node.op === 'cmp') return intern([node.cmp === '=' ? 'eq' : 'ne', emit(node.left), emit(node.right)]);
    if (node.op === 'enum') return intern(['category', node.value]);
    if (node.op !== 'def' || node.version !== 1)
      throw new QueryError('capability', 'No native study implementation for ' + (node.name || node.op));
    const a = node.args;
    if (node.def.patternId) return intern(['pattern', node.def.patternBars, ...specification(node.def.patternSpec)]);
    switch (node.name) {
      case 'exact_g1': return intern(['g1', a.pattern.text]);
      case 'wick_rejection': return intern(['wick', ratio(a.body_max), ratio(a.wick_min)]);
      case 'channel_breakout': return intern(['breakout', a.over.ms]);
      case 'quiet_range': return intern(['range', a.window.ms, ratio(a.width_max)]);
      case 'range_contained': return intern(['range', a.over.ms, ratio(a.width_max)]);
      case 'held': return intern(['held', emit(a.state), a.for.ms]);
      case 'price': return intern(['price', a.point.value, a.bars_ago.rat.num]);
      case 'prior_low': return intern(['prior-low', a.over.ms]);
      case 'prior_high': return intern(['prior-high', a.over.ms]);
      case 'breach_reclaim': return intern(['reclaim',emit(a.reference),a.within_min.rat.num,a.within_max.rat.num]);
      case 'candle_window': return intern(['window',emit(a.event),a.bars.rat.num]);
      case 'candle_relation': return intern(['relate',emit(a.left),priceRelation[a.is.value],emit(a.right)]);
      case 'near_level': return intern(['near',emit(a.reference),emit(a.point),ratio(a.within)]);
      case 'candle_share': return intern(['share',a.part.value,a.bars_ago.rat.num,ratio(a.min),ratio(a.max)]);
      case 'range_multiple': return intern(['multiple',a.over.ms,ratio(a.min),a.max ? ratio(a.max) : '-']);
      case 'weekday': return intern(['weekday']);
      case 'session_tail': return intern(['tail', a.last.ms]);
      case 'completed_trend': return intern(['trend', a.frame.ms]);
      default: throw new QueryError('capability','No native study implementation for ' + node.name);
    }
  }
  const requests = plans.map(({plan}) => {
    if (plan.measures.some(m => m.name !== 'close_return' || m.version !== 1)) {
      throw new QueryError('capability', 'Native studies measure close_return@1.');
    }
    const find = emit(plan.find);
    const filters = plan.wheres.map(emit);
    const context = filters.length === 0 ? '-' : filters.length === 1 ? filters[0] : intern(['and', ...filters]);
    const group = plan.group ? emit(plan.group) : '-';
    return [find, context, group, ...plan.columns.map(({h}) => h)].join(' ');
  });
  const wire = ['filang-study-v1',nodes.size,...nodes.keys(),...requests].join('\t');
  if (Buffer.byteLength(wire) + 1 > 1_048_576) throw new QueryError('query', 'The compiled batch exceeds 1 MiB.');
  return { wire, canonical: checked.canonical, candidates: plans.map(c => c.label) };
}
