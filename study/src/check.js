// Validation and resolution: bindings, sweep axes, candidates, signatures, types, domains.
// Produces one typed plan per candidate. Shared by the text editor, the guided editor and Node tests.

import { parse, parseExpression, parseLiteral, printExpr, printQuestion, diag, msToText } from './lang.js';
import { ratFromText, ratCmp, ratKey, ratToPercentText, ratToDecimalText } from './num.js';
import { ENUMS, suggest, typeText, CAPABILITY_TEXT } from './registry.js';

import { parseG1 } from './g1.js';

export const MAX_CANDIDATES = 64;

const SCALAR_KINDS = new Set(['dur', 'num', 'pct', 'str', 'id']);
export const isScalarLiteral = (n) => SCALAR_KINDS.has(n.k);
export const isBoolType = (t) => t === 'Condition' || t === 'State' || t === 'Event';
export const isCatType = (t) => typeof t === 'string' && t.startsWith('Cat:');
export const enumOfType = (t) => (isCatType(t) ? ENUMS[t.slice(4)] : null);

export function litDesc(n) {
  switch (n.k) {
    case 'dur': return `the duration ${n.text}`;
    case 'num': return `the number ${n.text}`;
    case 'pct': return `the percentage ${n.text}%`;
    case 'str': return `the string ${JSON.stringify(n.value)}`;
    case 'id': return `the name ${n.name}`;
    case 'vec': return `the vector ${printExpr(n)}`;
    case 'choices': return `the choices ${printExpr(n)}`;
    case 'call': return `the call ${n.name}(…)`;
    default: return `the expression ${printExpr(n)}`;
  }
}

export function literalKey(n) {
  switch (n.k) {
    case 'dur': return 'dur:' + n.ms;
    case 'num': return 'rat:' + ratKey(ratFromText(n.text, false));
    case 'pct': return 'rat:' + ratKey(ratFromText(n.text, true));
    case 'str': return 'str:' + n.value;
    case 'id': return 'id:' + n.name;
    default: return null;
  }
}

export function canonValue(v) {
  if (!v) return '?';
  switch (v.t) {
    case 'G1': return JSON.stringify(v.text);
    case 'Duration': return msToText(v.ms);
    case 'Ratio': return ratToPercentText(v.rat);
    case 'Number': return ratToDecimalText(v.rat);
    case 'Calendar': return `${v.name}/${v.table}`;
    case 'List': return `[${v.items.map(canonValue).join(',')}]`;
    default: return v.identity || '?';
  }
}

export function displayValue(v) {
  if (!v) return '?';
  switch (v.t) {
    case 'G1': case 'Duration': case 'Ratio': case 'Number': return v.text;
    case 'Calendar': return v.name;
    case 'List': return v.items.map(displayValue).join(', ');
    default: return v.named ? `"${v.named}"` : v.label;
  }
}

export function identityOf(name, version, args) {
  const keys = Object.keys(args).sort();
  return `${name}@${version}(${keys.map((k) => `${k}=${canonValue(args[k])}`).join(',')})`;
}

function typeDesc(p) {
  const t = p.type;
  const who = p.named ? `"${p.named}"` : p.text;
  if (t === 'Event') return `${who} is an Event`;
  if (t === 'State') return `${who} is a State (a series sampled at every 15m close)`;
  if (t === 'Condition') return `${who} is a condition`;
  if (t === 'Outcome') return `${who} is an outcome measured after the anchor`;
  if (isCatType(t)) { const e = enumOfType(t); return `${who} is a categorical ${e.title} (${e.values.join(', ')})`; }
  return `${who} has type ${t}`;
}

function substituteIds(node, map) {
  switch (node.k) {
    case 'id': return map.has(node.name) ? { ...map.get(node.name) } : node;
    case 'call': return { ...node, args: node.args.map((a) => ({ ...a, value: substituteIds(a.value, map) })) };
    case 'vec': case 'choices': case 'and': case 'or': return { ...node, items: node.items.map((x) => substituteIds(x, map)) };
    case 'not': return { ...node, item: substituteIds(node.item, map) };
    case 'cmp': return { ...node, left: substituteIds(node.left, map), right: substituteIds(node.right, map) };
    default: return node;
  }
}

// ---------------------------------------------------------------- type checker

export class Checker {
  constructor(env, sink, letNames = []) {
    this.env = env;
    this.reg = env.registry;
    this.sink = sink;
    this.letNames = letNames;
  }

  err(kind, message, node, hint) {
    const extra = node && node.viaLet ? { related: { start: node.refStart, end: node.refEnd, note: `value of let ${node.viaLet}, used here` } } : undefined;
    this.sink(diag(kind, message, node.start ?? 0, node.end ?? 0, hint, extra));
    return null;
  }

  question(q) {
    const rec = this.env.recording;
    if (q.on.instrument.name !== rec.instrument) {
      this.err('capability', `no recording for ${q.on.instrument.name}; this prototype has ${rec.instrument} (${rec.venue}, ${rec.rangeText})`, q.on.instrument);
    }
    if (q.on.bar.ms !== rec.barMs) {
      this.err('capability', `${q.on.bar.text} bars are not enabled; the recording provides ${rec.barText} bars and aggregation is not part of this prototype`, q.on.bar);
    }
    const find = this.slot(q.find, 'find');
    const wheres = q.wheres.map((w) => this.slot(w, 'where'));
    const group = q.group ? this.slot(q.group, 'group') : null;
    const measures = q.measures.map((m) => this.slot(m, 'measure'));
    const columns = [];
    const seen = new Map();
    measures.forEach((m, mi) => {
      if (!m) return;
      for (const c of outcomeColumns(m)) {
        if (seen.has(c.key)) {
          this.err('type', `horizon ${c.text} is already measured by measure #${seen.get(c.key) + 1}`, c.span || q.measures[mi]);
          continue;
        }
        seen.set(c.key, mi);
        columns.push({ ...c, measure: mi });
      }
    });
    return { find, wheres, group, measures, columns };
  }

  slot(node, which) {
    if (which === 'find' && (node.k === 'and' || node.k === 'or')) {
      const items = node.items.map((item) => this.slot(item, 'find'));
      if (items.some((item) => !item)) return null;
      // Same-close composition is associative, commutative and idempotent.
      const terms = [...new Set(items.flatMap((p) => p.op === node.k ? p.terms : [p.identity]))].sort();
      const identity = terms.length === 1 ? terms[0] : `events.${node.k}@1(${terms.join('|')})`;
      const text = printExpr(node);
      return { op: node.k, kind: 'event', type: 'Event', items, terms, identity, text,
        label: text, start: node.start, end: node.end };
    }
    const p = this.expr(node);
    if (!p) return null;
    const t = p.type;
    if (which === 'find' && t !== 'Event') {
      return this.err('type', `find needs an Event; ${typeDesc(p)}`, node,
        'conditions and states belong in where clauses; find takes an event such as "Wick rejection" or channel_breakout(over: 12h)');
    }
    if (which === 'where' && !isBoolType(t)) {
      let hint = null;
      if (isCatType(t)) hint = `compare it with a value, e.g. ${p.text} = ${enumOfType(t).values[0]}, or use it in group by`;
      if (t === 'Outcome') hint = `outcomes use bars after the anchor, so they cannot filter; use measure ${p.text}`;
      return this.err('type', `where needs a condition; ${typeDesc(p)}`, node, hint);
    }
    if (which === 'group' && !isBoolType(t) && !isCatType(t)) {
      return this.err('type', `group by needs a categorical or Boolean value known at the anchor; ${typeDesc(p)}`, node,
        t === 'Outcome' ? 'outcomes are measured after the anchor; use measure instead' : null);
    }
    if (which === 'measure' && t !== 'Outcome') {
      return this.err('type', `measure needs an outcome; ${typeDesc(p)}`, node, 'e.g. measure close_return(after: [1h, 4h])');
    }
    return p;
  }

  expr(node) {
    switch (node.k) {
      case 'str': return this.named(node);
      case 'call': return this.call(node);
      case 'and': case 'or': {
        const items = node.items.map((x) => this.boolOperand(x, node.k));
        if (items.some((x) => !x)) return null;
        return { op: node.k, items, type: 'Condition', text: printExpr(node), label: items.map((x) => x.label).join(` ${node.k} `), start: node.start, end: node.end };
      }
      case 'not': {
        const item = this.boolOperand(node.item, 'not');
        if (!item) return null;
        return { op: 'not', item, type: 'Condition', text: printExpr(node), label: `not (${item.label})`, start: node.start, end: node.end };
      }
      case 'cmp': return this.compare(node);
      case 'id': return this.bareId(node);
      case 'vec': return this.err('type', 'a vector is only allowed as an argument whose signature accepts a list, e.g. close_return(after: [1h, 4h])', node);
      case 'choices': return this.err('sweep', 'choices must be resolved before type checking', node);
      default: return this.err('type', `${litDesc(node)} is a value, not a condition, event or outcome`, node);
    }
  }

  boolOperand(x, opName) {
    const p = this.expr(x);
    if (!p) return null;
    if (!isBoolType(p.type)) {
      const hint = isCatType(p.type) ? `compare it with a value, e.g. ${p.text} = ${enumOfType(p.type).values[0]}` : null;
      return this.err('type', `'${opName}' combines conditions; ${typeDesc(p)}`, x, hint);
    }
    return p;
  }

  bareId(node) {
    const name = node.name;
    if (this.env.calendars.has(name)) {
      return this.err('type', `${name} is a calendar, not a condition`, node, `use it inside a call, e.g. weekday(${name}) = fri or session_tail(${name}, last: 30m)`);
    }
    const e = Object.values(ENUMS).find((en) => en.values.includes(name));
    if (e) {
      const ex = e.name === 'Trend' ? `completed_trend(frame: 4h) = ${name}` : `weekday(nyse_regular) = ${name}`;
      return this.err('type', `${name} is a ${e.title} value, not a condition`, node, `compare it, e.g. ${ex}`);
    }
    const f = this.reg.get(name);
    if (f?.patternId) return this.finishDef(f, {}, {}, node);
    const named = this.reg.getNamed(name);
    if (named?.patternId) return this.finishDef(this.reg.getPattern(named.patternId), {}, {}, node, name);
    if (f) return this.err('type', `${name} is a function; call it with parentheses`, node, f.example ? `e.g. ${f.example}` : null);
    const pool = [...this.letNames, ...this.env.calendars.keys(), ...Object.values(ENUMS).flatMap((en) => en.values),
      ...this.reg.list((def) => def.patternId).map((def) => def.name)];
    const s = suggest(name, pool);
    return this.err('name', `unresolved name ${name}`, node, s.length ? `did you mean ${s.join(' or ')}?` : 'use a registered candle pattern, let binding, calendar or enum value');
  }

  named(node) {
    const nd = this.reg.getNamed(node.value);
    if (!nd) {
      const s = suggest(node.value, [...this.reg.named.keys()]);
      return this.err('name', `no definition named ${JSON.stringify(node.value)}`, node,
        s.length ? `did you mean ${s.map((x) => JSON.stringify(x)).join(' or ')}?` : 'choose a registered name from the catalog');
    }
    const def = nd.patternId ? this.reg.getPattern(nd.patternId) : this.reg.get(nd.def);
    if (!def || def.version !== nd.version) return this.err('registry', `"${node.value}" pins ${nd.def}@${nd.version}, which is not in this registry`, node);
    const args = {};
    const argSource = {};
    for (const p of def.params) {
      const lit = parseLiteral(nd.args[p.name] ?? p.default).node;
      args[p.name] = this.scalar({ ...lit, start: node.start, end: node.end }, p, def, args);
      argSource[p.name] = 'preset';
    }
    return this.finishDef(def, args, argSource, node, node.value);
  }

  call(node) {
    const def = this.reg.get(node.name) || this.reg.getPattern(this.reg.getNamed(node.name)?.patternId);
    const span = { start: node.nameStart, end: node.nameEnd };
    if (!def) {
      const s = suggest(node.name, this.reg.list().map((f) => f.name));
      return this.err('name', `unknown function ${node.name}`, span, s.length ? `did you mean ${s.join(' or ')}?` : null);
    }
    if (def.status === 'planned') {
      const caps = this.env.recording.caps;
      const missing = (def.requires || []).filter((c) => !caps.has(c));
      const capText = missing.length
        ? ` It requires ${missing.map((c) => `${c} (${CAPABILITY_TEXT[c] || c})`).join(' and ')}; this recording provides ${[...caps].map((c) => CAPABILITY_TEXT[c] || c).join(', ')}.`
        : '';
      return this.err('capability', `${node.name} is a planned capability (design example), not executable in this prototype.${capText}`, span, def.note);
    }
    const missingCaps = (def.requires || []).filter((c) => !this.env.recording.caps.has(c));
    if (missingCaps.length) {
      return this.err('capability', `${node.name} requires ${missingCaps.map((c) => CAPABILITY_TEXT[c] || c).join(', ')}, which this recording does not provide`, span);
    }
    const byName = new Map();
    let ok = true;
    for (const a of node.args) {
      let pname = a.name;
      if (pname === null) {
        if (!def.positional) {
          this.err('signature', `${def.name} takes no positional argument; name it (${def.params.map((p) => p.name + ':').join(', ')})`, a);
          ok = false;
          continue;
        }
        pname = def.positional;
      }
      const param = def.params.find((p) => p.name === pname);
      if (!param) {
        const s = suggest(pname, def.params.map((p) => p.name));
        this.err('signature', `unknown argument ${pname} for ${def.name}`, { start: a.nameStart, end: a.nameEnd },
          `${s.length ? `did you mean ${s.join(' or ')}? ` : ''}${def.name} accepts: ${def.params.map((p) => `${p.name}: ${typeText(p)}`).join(', ')}`);
        ok = false;
        continue;
      }
      if (byName.has(pname)) {
        this.err('signature', `duplicate argument ${pname} for ${def.name}${a.name === null || byName.get(pname).name === null ? ' (the positional argument is ' + def.positional + ')' : ''}`, a);
        ok = false;
        continue;
      }
      byName.set(pname, a);
    }
    const args = {};
    const argSource = {};
    for (const p of def.params) {
      const a = byName.get(p.name);
      if (!a) {
        if (p.required) {
          this.err('signature', `missing required argument ${p.name}: ${typeText(p)} for ${def.name}`, node, `${p.doc}${def.example ? `; e.g. ${def.example}` : ''}`);
          ok = false;
        } else if (p.default !== undefined) {
          const lit = parseLiteral(p.default).node;
          args[p.name] = this.scalar({ ...lit, start: node.start, end: node.end }, p, def, args);
          argSource[p.name] = 'default';
        }
        continue;
      }
      const v = this.arg(a.value, p, def, args);
      if (v === null) ok = false;
      args[p.name] = v;
      argSource[p.name] = 'given';
    }
    if (!ok) return null;
    return this.finishDef(def, args, argSource, node, null, byName);
  }

  finishDef(def, args, argSource, node, named, byName) {
    if (Object.values(args).some((v) => v === null)) return null;
    if (def.orderedBounds) {
      const [min, max] = def.orderedBounds;
      if (args[min] && args[max] && ratCmp(args[min].rat, args[max].rat) > 0) {
        return this.err('domain', `${min} must be at most ${max}`, node);
      }
    }
    const plan = {
      op: 'def', name: def.name, version: def.version, kind: def.kind, type: def.result, def,
      args, argSource, named, identity: identityOf(def.id || def.name, def.version, args),
      text: printExpr(node), start: node.start, end: node.end,
    };
    const disp = {};
    for (const [k, v] of Object.entries(args)) disp[k] = displayValue(v);
    plan.label = def.template ? def.template(disp) : def.name;
    if (named && !def.patternId) plan.label = `${named}: ${plan.label}`;
    if (def.composed) {
      const map = new Map();
      for (const p of def.params) {
        const given = byName && byName.get(p.name);
        map.set(p.name, given ? stripRef(given.value) : parseLiteral(p.default).node);
      }
      const inst = substituteIds(def.composed.bodyAst, map);
      const child = new Checker(this.env, (d) => this.sink({ ...d, message: `${def.name}@${def.version} body: ${d.message}`, start: node.start, end: node.end, related: undefined }), []);
      const body = child.expr(inst);
      if (!body) return null;
      if (!isBoolType(body.type)) return this.err('registry', `${def.name}@${def.version} body is not a condition`, node);
      plan.body = body;
      plan.bodyText = printExpr(inst);
    }
    return plan;
  }

  arg(valueNode, param, def, resolved) {
    if (param.type === 'Price' || param.type === 'Level') {
      const p = this.expr(valueNode);
      if (!p) return null;
      if (p.type === 'Level' || (param.type === 'Price' && p.type === 'Price')) return p;
      return this.err('type', `${def.name} ${param.name} needs ${param.type === 'Level' ? 'a prior high or low' : 'a candle price or prior level'}`, valueNode);
    }
    if (param.type === 'State') {
      const p = this.expr(valueNode);
      if (!p) return null;
      if (p.type !== 'State') {
        return this.err('type', `${def.name} ${param.name}: needs a State; ${typeDesc(p)}`, valueNode, 'e.g. "Quiet range" or quiet_range(width_max: 2%)');
      }
      return p;
    }
    if (param.list) {
      if (valueNode.k === 'vec') {
        const items = [];
        const seen = new Map();
        for (const it of valueNode.items) {
          if (it.k === 'vec') { this.err('type', 'vectors cannot be nested', it); return null; }
          const v = this.scalar(it, param, def, resolved);
          if (!v) return null;
          const key = canonValue(v);
          if (seen.has(key)) { this.err('type', `duplicate ${param.name} value ${v.text} in the vector (same as ${seen.get(key)})`, it); return null; }
          seen.set(key, v.text);
          items.push(v);
        }
        return { t: 'List', items, vector: true };
      }
      const one = this.scalar(valueNode, param, def, resolved);
      return one ? { t: 'List', items: [one], vector: false } : null;
    }
    if (valueNode.k === 'vec') {
      return this.err('type', `${def.name} ${param.name}: takes a single ${param.type}; a vector is one argument and is only accepted where the signature allows a list`, valueNode,
        `to run each value as a separate candidate, use choices: {${valueNode.items.map((x) => printExpr(x)).join(' | ')}}`);
    }
    return this.scalar(valueNode, param, def, resolved);
  }

  scalar(node, param, def, resolved) {
    const where = `${def.name} ${param.name}:`;
    const span = { start: node.start, end: node.end };
    const dom = param.domain || {};
    if (isCatType(param.type)) {
      if (node.k !== 'id') return this.err('type', `${where} choose a ${enumOfType(param.type).title}`, node);
      const val = this.enumValue(node, {type:param.type});
      return val ? {...val, identity: val.value} : null;
    }
    switch (param.type) {
      case 'G1': {
        if (node.k !== 'str') return this.err('type', `${where} expects a quoted G1 code`, node);
        try {
          return { t: 'G1', text: node.value, pattern: parseG1(node.value), ...span };
        } catch (err) {
          return this.err('domain', err.message, node);
        }
      }
      case 'Duration': {
        if (node.k !== 'dur') {
          return this.err('type', `${where} expects a duration such as ${param.default || '30m'}; got ${litDesc(node)}`, node,
            node.k === 'num' ? `add a unit: ${node.text}m, ${node.text}h or ${node.text}d` : null);
        }
        const bar = this.env.recording.barMs;
        const barText = this.env.recording.barText;
        if (dom.barMultiple && node.ms % bar !== 0) {
          const lo = Math.max(bar, Math.floor(node.ms / bar) * bar);
          return this.err('domain', `${where} ${node.text} is not a whole number of ${barText} bars`, node, `use a multiple of ${barText}, e.g. ${msToText(lo)} or ${msToText(lo + bar)}`);
        }
        if (dom.minMs && node.ms < dom.minMs) return this.err('domain', `${where} ${node.text} is below the minimum ${msToText(dom.minMs)}`, node);
        if (dom.maxMs && node.ms > dom.maxMs) return this.err('domain', `${where} ${node.text} exceeds the maximum ${msToText(dom.maxMs)}`, node);
        if (dom.dividesDay && 86_400_000 % node.ms !== 0) {
          return this.err('domain', `${where} ${node.text} does not divide 24h, so its bars cannot be UTC-aligned`, node, 'use e.g. 1h, 2h, 4h, 6h, 8h, 12h or 1d');
        }
        if (dom.maxShortestSession) {
          const cal = resolved && resolved.calendar && this.env.calendars.get(resolved.calendar.name);
          if (cal && node.ms > cal.shortestSessionMs) {
            return this.err('domain', `${where} ${node.text} is longer than the shortest ${resolved.calendar.name} session in the pinned table (${msToText(cal.shortestSessionMs)}); a tail must lie inside the session`, node);
          }
        }
        return { t: 'Duration', ms: node.ms, text: node.text, ...span };
      }
      case 'Ratio': {
        if (node.k !== 'pct' && node.k !== 'num') {
          return this.err('type', `${where} expects a ratio such as ${param.default || '35%'} or 0.35; got ${litDesc(node)}`, node);
        }
        const rat = ratFromText(node.text, node.k === 'pct');
        const text = printExpr(node);
        if (dom.ratioMax !== undefined && ratCmp(rat, ratFromText(dom.ratioMax)) > 0) {
          return this.err('domain', `${where} ${text} is above ${ratToPercentText(ratFromText(dom.ratioMax))}`, node, node.k === 'num' ? `a plain number is a ratio (0.35 = 35%); did you mean ${node.text}%?` : null);
        }
        if (dom.ratioMin !== undefined) {
          const c = ratCmp(rat, ratFromText(dom.ratioMin));
          if (c < 0 || (c === 0 && dom.ratioMinExclusive)) return this.err('domain', `${where} ${text} must be ${dom.ratioMinExclusive ? 'greater than' : 'at least'} ${ratToPercentText(ratFromText(dom.ratioMin))}`, node);
        }
        return { t: 'Ratio', rat, text, ...span };
      }
      case 'Number': {
        if (node.k !== 'num') return this.err('type', `${where} expects a plain number; got ${litDesc(node)}`, node);
        const rat = ratFromText(node.text);
        if (dom.wholeMax !== undefined && (rat.den !== 1n || rat.num > BigInt(dom.wholeMax))) {
          return this.err('domain', `${where} choose a whole number from 0 to ${dom.wholeMax}`, node);
        }
        return { t: 'Number', rat, text: node.text, ...span };
      }
      case 'Calendar': {
        if (node.k !== 'id') return this.err('type', `${where} expects a calendar name such as nyse_regular; got ${litDesc(node)}`, node);
        const cal = this.env.calendars.get(node.name);
        if (!cal) {
          const s = suggest(node.name, [...this.env.calendars.keys()]);
          return this.err('name', `unknown calendar ${node.name}`, node, `${s.length ? `did you mean ${s.join(' or ')}? ` : ''}registered calendars: ${[...this.env.calendars.keys()].join(', ')}`);
        }
        return { t: 'Calendar', name: node.name, table: cal.id, ...span };
      }
      default:
        return this.err('registry', `${where} unsupported parameter type ${param.type}`, node);
    }
  }

  compare(node) {
    const op = node.op;
    const idSide = (n) => n.k === 'id' && !this.env.calendars.has(n.name);
    let left = null;
    let right = null;
    if (idSide(node.left) && !idSide(node.right)) {
      right = this.cmpOperand(node.right);
      if (!right) return null;
      left = this.enumValue(node.left, right);
    } else if (idSide(node.right)) {
      left = this.cmpOperand(node.left);
      if (!left) return null;
      if (idSide(node.left)) return this.err('type', 'a comparison needs a per-bar value on one side, e.g. weekday(nyse_regular) = fri', node);
      right = this.enumValue(node.right, left);
    } else {
      left = this.cmpOperand(node.left);
      right = left && this.cmpOperand(node.right);
      if (left && right && left.type !== right.type) {
        return this.err('type', `cannot compare ${left.type.replace('Cat:', '')} with ${right.type.replace('Cat:', '')}`, node);
      }
    }
    if (!left || !right) return null;
    const cat = isCatType(left.type) ? left : right;
    const e = enumOfType(cat.type);
    if (op !== '=' && op !== '!=') {
      return this.err('type', `'${op}' needs ordered values; ${e.title} values are unordered`, { start: node.opStart, end: node.opEnd }, 'use = or !=');
    }
    const other = cat === left ? right : left;
    const otherLabel = other.op === 'enum' ? e.labels[other.value] : other.label;
    return {
      op: 'cmp', cmp: op, left, right, type: 'Condition', text: printExpr(node),
      label: `${cat.label} ${op === '=' ? 'is' : 'is not'} ${otherLabel}`, start: node.start, end: node.end,
    };
  }

  cmpOperand(n) {
    if (['dur', 'num', 'pct', 'str'].includes(n.k)) {
      return this.err('type', `${litDesc(n)} cannot be compared here: comparisons in this prototype test a categorical value against one of its values (e.g. completed_trend(frame: 4h) = up); there are no numeric per-bar values`, n);
    }
    const p = this.expr(n);
    if (!p) return null;
    if (!isCatType(p.type)) {
      return this.err('type', `only categorical values can be compared; ${typeDesc(p)}`, n, isBoolType(p.type) ? 'combine conditions with and / or / not instead' : null);
    }
    return p;
  }

  enumValue(idNode, other) {
    const e = enumOfType(other.type);
    if (!e) return this.err('type', `cannot compare with ${idNode.name}`, idNode);
    if (!e.values.includes(idNode.name)) {
      if (e.never && e.never[idNode.name]) return this.err('type', `${idNode.name} never occurs: ${e.never[idNode.name]}`, idNode, `values: ${e.values.join(', ')}`);
      const s = suggest(idNode.name, e.values);
      return this.err('name', `${idNode.name} is not a ${e.title} value`, idNode, `${s.length ? `did you mean ${s.join(' or ')}? ` : ''}values: ${e.values.join(', ')}`);
    }
    return { op: 'enum', enumName: e.name, value: idNode.name, type: `Enum:${e.name}`, text: idNode.name, label: e.labels[idNode.name], start: idNode.start, end: idNode.end };
  }
}

function stripRef(n) {
  const { viaLet, refStart, refEnd, ...rest } = n;
  return rest;
}

/** Columns produced by an outcome plan (one per requested horizon). */
export function outcomeColumns(plan) {
  if (!plan || plan.op !== 'def' || plan.kind !== 'outcome') return [];
  const list = plan.args.after;
  return list.items.map((v) => ({
    key: `${plan.name}@${plan.version}:${v.ms}`,
    def: plan.name,
    h: v.ms,
    text: v.text,
    label: `${plan.name === 'close_return' ? 'return' : plan.name} ${v.text}`,
    span: { start: v.start, end: v.end },
  }));
}

// ---------------------------------------------------------------- analysis (bindings, axes, candidates)

export function analyze(src, env) {
  const { ast, error } = parse(src);
  if (error) return { ok: false, src, ast: null, errors: [error], axes: [], candidates: [], canonical: null };
  return analyzeAst(ast, src, env);
}

export function analyzeAst(ast, src, env) {
  const errors = [];
  const seenErr = new Set();
  const sink = (d) => {
    const key = `${d.kind}|${d.start}|${d.end}|${d.message}`;
    if (!seenErr.has(key)) { seenErr.add(key); errors.push(d); }
  };
  const E = (kind, message, node, hint) => sink(diag(kind, message, node.start, node.end, hint));
  const reg = env.registry;

  // ---- bindings
  const lets = new Map();
  for (const b of ast.lets) {
    const nameSpan = { start: b.nameStart, end: b.nameEnd };
    if (lets.has(b.name)) { E('binding', `duplicate binding ${b.name}`, nameSpan); continue; }
    let clash = null;
    if (env.calendars.has(b.name)) clash = 'a registered calendar';
    else if (reg.isEnumValue(b.name)) clash = 'a registered enum value';
    else if (reg.get(b.name) && !reg.get(b.name).patternId) clash = 'a registered function';
    if (clash) { E('binding', `let ${b.name} conflicts with ${clash} of the same name`, nameSpan, 'choose another name'); continue; }
    const v = b.value;
    if (v.k === 'choices') {
      for (const it of v.items) if (!isScalarLiteral(it)) E('sweep', `choices must contain scalar literals (durations, numbers, percentages, strings or names), not ${litDesc(it)}`, it);
    } else if (!isScalarLiteral(v)) {
      E('binding', `let ${b.name} must be a scalar literal (e.g. 12h, 2%, "Quiet range") or choices of literals such as {12h | 24h}; got ${litDesc(v)}`, v);
    }
    lets.set(b.name, { b, uses: 0, choices: v.k === 'choices' });
  }
  for (const b of ast.lets) {
    const items = b.value.k === 'choices' ? b.value.items : [b.value];
    for (const it of items) {
      if (it.k === 'id' && lets.has(it.name)) E('binding', `let ${b.name} cannot refer to the binding ${it.name}; bindings are literals (no references or cycles)`, it);
    }
  }

  // ---- walk the body: references, inline choices, nesting rules
  const inline = [];
  const walk = (node, ctx) => {
    switch (node.k) {
      case 'id': {
        const l = lets.get(node.name);
        if (l) l.uses++;
        break;
      }
      case 'choices': {
        if (ctx.inVector) { E('sweep', 'choices cannot appear inside a vector (no nested lists or sweeps); a vector is one argument, choices make separate candidates', node); break; }
        for (const it of node.items) {
          if (!isScalarLiteral(it)) E('sweep', `choices must contain scalar literals (durations, numbers, percentages, strings or names), not ${litDesc(it)}`, it);
          else if (it.k === 'id' && lets.has(it.name)) E('sweep', `choices cannot refer to the binding ${it.name}`, it);
        }
        inline.push({ node, label: ctx.label });
        break;
      }
      case 'vec':
        for (const it of node.items) walk(it, { ...ctx, inVector: true });
        break;
      case 'call': {
        const def = reg.get(node.name);
        for (const a of node.args) walk(a.value, { label: `${node.name}.${a.name || (def && def.positional) || 'arg'}` });
        break;
      }
      case 'and': case 'or':
        for (const it of node.items) walk(it, ctx);
        break;
      case 'not':
        walk(node.item, ctx);
        break;
      case 'cmp':
        walk(node.left, { label: `${node.op} ${printExpr(node.right)}` });
        walk(node.right, { label: `${printExpr(node.left)} ${node.op}` });
        break;
      default: break;
    }
  };
  walk(ast.find, { label: 'find' });
  ast.wheres.forEach((w, i) => walk(w, { label: `where #${i + 1}` }));
  if (ast.group) walk(ast.group, { label: 'group by' });
  ast.measures.forEach((m, i) => walk(m, { label: `measure #${i + 1}` }));

  for (const [name, l] of lets) {
    if (l.uses === 0) E('binding', `let ${name} is never used`, { start: l.b.nameStart, end: l.b.nameEnd }, `reference ${name} in the question or remove the binding`);
  }

  // ---- axes in source order
  const axes = [];
  for (const [name, l] of lets) {
    if (l.choices) axes.push({ kind: 'let', name, label: name, node: l.b.value, values: l.b.value.items, start: l.b.start, end: l.b.end });
  }
  const labelCount = new Map();
  for (const a of inline) labelCount.set(a.label, (labelCount.get(a.label) || 0) + 1);
  const labelSeen = new Map();
  for (const a of inline) {
    let label = a.label;
    if (labelCount.get(label) > 1) { const k = (labelSeen.get(label) || 0) + 1; labelSeen.set(label, k); label = `${label} (${k})`; }
    axes.push({ kind: 'inline', name: null, label, node: a.node, values: a.node.items, start: a.node.start, end: a.node.end });
  }
  axes.sort((x, y) => x.start - y.start);
  axes.forEach((a, i) => { a.index = i; });

  for (const ax of axes) {
    const seen = new Map();
    for (const it of ax.values) {
      const key = literalKey(it);
      if (key === null) continue;
      if (seen.has(key)) E('sweep', `duplicate choice ${printExpr(it)} in ${ax.label} (same value as ${printExpr(seen.get(key))})`, it, 'each choice must be a distinct value');
      else seen.set(key, it);
    }
  }
  let total = 1;
  for (const ax of axes) {
    total *= ax.values.length;
    if (total > MAX_CANDIDATES) {
      E('sweep', `this question expands to ${axes.reduce((p, a) => p * a.values.length, 1)} candidate runs (${axes.map((a) => `${a.label}: ${a.values.length}`).join(' × ')}); the limit is ${MAX_CANDIDATES}`, ax.node);
      break;
    }
  }

  const canonical = printQuestion(ast);
  if (errors.length) return { ok: false, src, ast, errors, axes, candidates: [], canonical };

  // ---- candidates (Cartesian product, first axis outermost)
  const combos = [];
  const idx = new Array(axes.length).fill(0);
  for (;;) {
    combos.push(idx.slice());
    let k = axes.length - 1;
    while (k >= 0) { idx[k]++; if (idx[k] < axes[k].values.length) break; idx[k] = 0; k--; }
    if (k < 0) break;
  }
  const letNames = [...lets.keys()];
  const candidates = [];
  for (const combo of combos) {
    const choiceSel = new Map();
    const letVals = new Map();
    for (const [name, l] of lets) if (!l.choices) letVals.set(name, l.b.value);
    axes.forEach((ax, i) => {
      const v = ax.values[combo[i]];
      if (ax.kind === 'let') letVals.set(ax.name, v);
      else choiceSel.set(ax.node, v);
    });
    const subst = (node) => {
      switch (node.k) {
        case 'choices': return choiceSel.get(node);
        case 'id': {
          if (!letVals.has(node.name)) return node;
          return { ...letVals.get(node.name), viaLet: node.name, refStart: node.start, refEnd: node.end };
        }
        case 'call': return { ...node, args: node.args.map((a) => ({ ...a, value: subst(a.value) })) };
        case 'vec': case 'and': case 'or': return { ...node, items: node.items.map(subst) };
        case 'not': return { ...node, item: subst(node.item) };
        case 'cmp': return { ...node, left: subst(node.left), right: subst(node.right) };
        default: return node;
      }
    };
    const resolvedAst = {
      ...ast, lets: [], find: subst(ast.find), wheres: ast.wheres.map(subst),
      group: ast.group ? subst(ast.group) : null, measures: ast.measures.map(subst),
    };
    const assignment = axes.map((ax, i) => ({ axis: ax.label, axisIndex: i, value: printExpr(ax.values[combo[i]]), valueIndex: combo[i] }));
    const checker = new Checker(env, sink, letNames);
    const plan = checker.question(resolvedAst);
    candidates.push({
      index: candidates.length,
      label: assignment.length ? assignment.map((a) => `${a.axis}=${a.value}`).join(', ') : 'single run',
      assignment,
      resolvedAst,
      resolvedText: printQuestion(resolvedAst),
      plan,
    });
  }
  if (errors.length) return { ok: false, src, ast, errors, axes, candidates: [], canonical };
  return { ok: true, src, ast, errors: [], axes, candidates, canonical };
}

// ---------------------------------------------------------------- extensions (agent-authored compositions)

const EXT_TYPES = new Set(['Duration', 'Ratio', 'Number']);

/**
 * Register a versioned composition (e.g. "Quiet Friday close") from an artifact object.
 * The body is an expression in the same language; its parameters are typed and defaulted.
 * Returns { ok, errors, def }.
 */
export function registerExtension(registry, artifact, env) {
  const errors = [];
  const fail = (m) => { errors.push(m); return { ok: false, errors, def: null }; };
  if (!artifact || artifact.artifact !== 'limen.sfd.definition') return fail('not a limen.sfd.definition artifact');
  const { id, version, kind, params, body } = artifact;
  if (!/^[a-z_][a-z0-9_]*$/.test(id || '')) return fail(`bad id ${id}`);
  if (!Number.isInteger(version) || version < 1) return fail('version must be a positive integer');
  if (kind !== 'condition') return fail('only condition compositions are supported in this prototype');
  if (/_v[0-9]+$/.test(id)) return fail('an extension family id cannot end with a version suffix');
  const alias = version === 1 ? id : `${id}_v${version}`;
  const base = registry.get(id);
  const existing = registry.get(alias);
  if ((existing && !existing.patternId) || (base && !base.patternId && base.status !== 'extension')) return fail(`${id}@${version} is already registered or reserved`);
  for (const dep of artifact.depends || []) {
    if (dep.calendar) {
      const cal = env.calendars.get(dep.calendar);
      if (!cal) return fail(`dependency calendar ${dep.calendar} is not registered`);
      if (cal.id !== dep.table) return fail(`dependency calendar ${dep.calendar} pins ${dep.table} but ${cal.id} is loaded`);
      continue;
    }
    const d = registry.getVersion(dep.name, dep.version);
    if (!d || d.version !== dep.version) return fail(`dependency ${dep.name}@${dep.version} is not available (found ${d ? d.name + '@' + d.version : 'nothing'})`);
  }
  const ps = [];
  for (const p of params || []) {
    if (!/^[a-z_][a-z0-9_]*$/.test(p.name || '')) return fail(`bad parameter name ${p.name}`);
    if (!EXT_TYPES.has(p.type)) return fail(`parameter ${p.name}: unsupported type ${p.type}`);
    if (env.calendars.has(p.name) || registry.isEnumValue(p.name)) return fail(`parameter ${p.name} shadows a registered name`);
    if (typeof p.default !== 'string' || parseLiteral(p.default).error) return fail(`parameter ${p.name} needs a literal default (extension parameters are defaulted in this prototype)`);
    ps.push({ name: p.name, type: p.type, default: p.default, required: false, domain: p.domain || {}, doc: p.doc || '' });
  }
  const parsed = parseExpression(body);
  if (parsed.error) return fail(`body: ${parsed.error.message} at offset ${parsed.error.start}`);
  const hasChoice = (n) => {
    switch (n.k) {
      case 'choices': return true;
      case 'call': return n.args.some((a) => hasChoice(a.value));
      case 'vec': case 'and': case 'or': return n.items.some(hasChoice);
      case 'not': return hasChoice(n.item);
      case 'cmp': return hasChoice(n.left) || hasChoice(n.right);
      default: return false;
    }
  };
  if (hasChoice(parsed.ast)) return fail('a composition body cannot contain choices');
  const tpl = artifact.label || id;
  const def = {
    name: alias, id, version, kind: 'condition', result: 'Condition', status: 'extension',
    title: artifact.title || id,
    summary: artifact.meaning || '',
    params: ps,
    requires: ['bars.ohlc', 'calendar'],
    formula: [`${id}(${ps.map((p) => p.name).join(', ')}) := ${body}`],
    anchor: 'the anchor t',
    availability: artifact.availability || 'as its components',
    missing: artifact.missing || 'strong Kleene combination of its components',
    template: (a) => tpl.replace(/\{(\w+)\}/g, (_, k) => (a[k] !== undefined ? a[k] : k)),
    example: artifact.example || `${alias}()`,
    composed: { bodyAst: parsed.ast, bodyText: body },
    artifact,
  };
  // type-check the body with default arguments before accepting it
  const probe = new Checker({ ...env, registry }, (d) => errors.push(`body check: ${d.message}`), []);
  const map = new Map(ps.map((p) => [p.name, parseLiteral(p.default).node]));
  const res = probe.expr(substituteIds(parsed.ast, map));
  if (errors.length) return { ok: false, errors, def: null };
  if (!res || !isBoolType(res.type)) return fail('body is not a condition');
  // Each direct component needs a version pin. A component that is itself an
  // extension checks its own dependency closure when it enters the registry.
  const required = new Set();
  function collect(p) {
    if (!p) return;
    if (p.op === 'def') {
      required.add(`${p.def.id || p.name}@${p.version}`);
      for (const arg of Object.values(p.args)) {
        if (arg.op) collect(arg);
        if (arg.t === 'Calendar') required.add(`${arg.name}/${arg.table}`);
      }
    }
    (p.items || []).forEach(collect);
    [p.item, p.left, p.right].forEach(collect);
  }
  collect(res);
  const pinned = new Set((artifact.depends || []).map((d) => d.calendar ? `${d.calendar}/${d.table}` : `${registry.getVersion(d.name, d.version)?.id || d.name}@${d.version}`));
  for (const key of required) if (!pinned.has(key)) return fail(`missing dependency pin for ${key}`);
  registry.addFunction(def);
  registry.extensions.push(def);
  return { ok: true, errors: [], def };
}
