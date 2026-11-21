// Editing tokens retain incomplete words/strings so a replacement can span both
// sides of the caret. The formal parser and checker own executable semantics.
import { parseExpression, parseLiteral, printExpr } from './lang.js';
import { Checker, literalKey } from './check.js';

const clauseWords = new Set(['on', 'let', 'find', 'where', 'group', 'measure']);
const closes = { '(': ')', '[': ']', '{': '}' };
const scalarWords = /^[\p{L}\p{N}_]/u;
const scan = /--[^\n]*|"(?:\\[^\n]|[^"\\\n\r])*"?|[\p{L}\p{N}_][\p{L}\p{N}_.%]*|!=|<=|>=|[^\s]/gu;

function tokensOf(text) {
  const tokens = [];
  const stack = [];
  for (const match of text.matchAll(scan)) {
    const v = match[0];
    const token = { v, i: tokens.length, start: match.index, end: match.index + v.length, parent: stack.at(-1), close: null };
    if (v === closes[token.parent?.v]) {
      token.parent.close = token;
      stack.pop();
    }
    tokens.push(token);
    if (Object.hasOwn(closes, v)) stack.push(token);
  }
  return tokens;
}

function word(t) {
  return !!t && scalarWords.test(t.v);
}
function quoted(t) {
  return !!t && t.v.startsWith('"');
}
function normalized(s) {
  return String(s).normalize('NFKC').toLowerCase().replace(/["_]+/g, ' ').replace(/\s+/g, ' ').trim();
}
const raw = (text, arr) => (arr.length ? text.slice(arr[0].start, arr.at(-1).end) : '');
const choice = (label, insert, kind, detail, extra = {}) => ({ label, insert, kind, detail, aliases: [], ...extra });

function callExample(def) {
  if (def.status === 'extension') return `${def.name}()`;
  return def.example || `${def.name}()`;
}

function exprOptions(role, env) {
  const reg = env.registry;
  const items = [];
  const named = new Map();
  for (const [name, nd] of reg.named) {
    if (role === 'measure' || (role === 'find' && nd.kind !== 'event') || (role === 'state' && nd.kind !== 'state')) continue;
    const canonical = nd.canonicalName || name;
    if (!named.has(canonical)) named.set(canonical, { nd, aliases: new Set() });
    const aliases = named.get(canonical).aliases;
    for (const alias of [name, nd.def, ...(nd.aliases || [])])
      if (typeof alias === 'string' && alias !== canonical) aliases.add(alias);
  }
  const namedItems = [...named].map(([name, { nd, aliases }]) =>
    choice(
      name,
      JSON.stringify(name),
      nd.kind === 'event' ? 'pattern' : 'state',
      [nd.ja || `${nd.def}@${nd.version}`, nd.patternId ? reg.getPattern(nd.patternId)?.patternRule : null]
        .filter(Boolean)
        .join(' · '),
      { aliases: [...aliases] }
    )
  );
  const allowed =
    {
      find: ['event'],
      state: ['state'],
      measure: ['outcome'],
      where: ['condition', 'categorical', 'state', 'event'],
      by: ['categorical', 'condition', 'state', 'event'],
    }[role] || [];
  for (const kind of allowed) {
    if (kind === 'state' || kind === 'event')
      items.push(...namedItems.filter(x => x.kind === (kind === 'event' ? 'pattern' : 'state')));
    for (const def of reg.implemented()) {
      if (def.kind !== kind || (def.requires || []).some(k => !env.recording.caps.has(k))) continue;
      // A catalogue name is already the selectable, complete detector. It can
      // still be found by its ASCII function name or Japanese aliases.
      if (def.patternId && named.has(def.canonicalName)) continue;
      let insert = callExample(def);
      if (def.kind === 'categorical') {
        const tree = parseExpression(insert).ast;
        const call = tree?.k === 'cmp' ? tree.left : tree;
        if (role === 'by' && call) insert = printExpr(call);
        if (role === 'where' && tree?.k !== 'cmp') {
          const e = reg.enumOf(def.result);
          if (e) insert += ' = ' + e.values[0];
        }
      }
      items.push(choice(def.name, insert, def.kind, def.title, { aliases: [def.title, def.name], def }));
    }
  }
  if (role === 'find') {
    const patterns = namedItems.filter(x => x.kind === 'pattern');
    if (patterns.length >= 2) {
      const sweep =
        '{' +
        patterns
          .slice(0, 2)
          .map(x => x.insert)
          .join(' | ') +
        '}';
      items.push(choice('Compare two patterns', sweep, 'sweep', 'Run a separate study for each pattern'));
    }
  }
  if (role === 'where' || role === 'by') {
    const base = items.find(i => i.kind === 'state') || items.find(i => i.kind === 'condition');
    if (base) items.push(choice('not', 'not ' + base.insert, 'operator', 'Exclude closes satisfying this condition'));
    const session = items.find(i => i.label === 'session_tail'),
      day = items.find(i => i.label === 'weekday');
    if (session && day) {
      const weekday = role === 'by' ? day.insert + ' = fri' : day.insert;
      items.push(
        choice(
          'Grouped conditions',
          '(' + weekday + ' and ' + session.insert + ')',
          'operator',
          'Combine conditions in parentheses'
        )
      );
    }
  }
  return items;
}

function argValue(call, def, param) {
  return call?.args?.find(a => (a.name || def.positional) === param.name)?.value;
}
function sampleFor(param, def) {
  const template = parseExpression(callExample(def)).ast;
  const arg = argValue(template?.k === 'cmp' ? template.left : template, def, param);
  return param.default || (arg ? printExpr(arg) : null);
}

function bindingValues(tokens, text) {
  const map = new Map();
  for (const t of tokens.filter(t => !t.parent && t.v === 'let')) {
    const name = tokens[t.i + 1];
    if (!word(name) || tokens[t.i + 2]?.v !== '=') continue;
    const value = [];
    for (const x of tokens.slice(t.i + 3)) {
      if (!x.parent && clauseWords.has(x.v)) break;
      value.push(x);
    }
    const node = parseExpression(raw(text, value)).ast;
    if (node) map.set(name.v, node.k === 'choices' ? node.items : [node]);
  }
  return map;
}

function scalarOptions(param, def, env, bindings, listMode, used = new Set(), typed = '') {
  if (!param) return [];
  if (['Level','Price','Event'].includes(param.type)) {
    if (listMode) return [];
    if (param.type === 'Event') return exprOptions('find',env).filter(x => x.def?.name !== def.name);
    return env.registry.implemented()
      .filter(d => d.result === 'Level' || param.type === 'Price' && d.result === 'Price')
      .map(d => choice(d.name,d.example,'value',d.title,{aliases:[d.title]}));
  }
  const check = new Checker(env, () => {});
  const resolved = { calendar: { name: env.calendars.keys().next().value } };
  const accepts = n => {
    if (!n) return false;
    return param.type === 'State' ? !!check.arg(n, param, def, resolved) : !!check.scalar(n, param, def, resolved);
  };
  if (param.type === 'State') {
    const items = exprOptions('state', env).filter(x => !listMode || (x.kind === 'state' && x.insert.startsWith('"')));
    for (const [name, nodes] of bindings)
      if (!listMode && nodes.every(accepts)) items.push(choice(name, name, 'binding', 'Bound state'));
    return items;
  }
  const sample = sampleFor(param, def);
  const initial = sample ? parseExpression(sample).ast : null;
  const values = new Set(initial?.k === 'vec' ? initial.items.map(n => printExpr(n)) : sample ? [sample] : []);
  const presets = {
    Duration: ['15m', '30m', '1h', '2h', '4h', '6h', '12h', '18h', '24h', '48h', '72h', '7d'],
    Ratio: ['1%', '2%', '2.5%', '3%', '5%', '25%', '35%', '45%', '50%', '75%', '100%'],
    Number: ['0', '1', '2', '3'],
    Calendar: [...env.calendars.keys()],
    G1: env.selectedG1 ? [JSON.stringify(env.selectedG1)] : [],
  };
  for (const value of env.registry.enumOf(param.type)?.values || presets[param.type] || []) values.add(value);
  // Presets demonstrate units; any literal allowed by the datatype and domain
  // can complete the slot, including a trader's own duration or G1 drawing.
  if (typed) {
    values.add(param.type === 'G1' ? JSON.stringify(typed) : typed);
    if (/^[1-9][0-9]*$/.test(typed) && param.type === 'Duration') {
      for (const unit of ['m', 'h', 'd']) values.add(typed + unit);
    }
    if (/^\d+(?:\.\d+)?$/.test(typed) && param.type === 'Ratio') values.add(typed + '%');
  }
  const items = [];
  for (const value of values) {
    const node = parseLiteral(value).node;
    if (!accepts(node) || used.has(literalKey(node))) continue;
    items.push(choice(value, value, 'value', param.doc));
  }
  if (listMode !== '{') {
    for (const [name, nodes] of bindings)
      if (nodes.every(n => accepts(n) && !used.has(literalKey(n))))
        items.push(choice(name, name, 'binding', 'Use the declared value of ' + name));
  }
  if (!listMode) {
    const singles = items.filter(x => x.kind === 'value').map(x => x.insert);
    if (singles.length >= 2) {
      const pair = singles.slice(0, 2);
      if (param.list) {
        const vector = '[' + pair.join(', ') + ']';
        items.unshift(choice(vector, vector, 'vector', 'Measure both horizons in one study'));
      }
      const sweep = '{' + pair.join(' | ') + '}';
      items.push(choice(sweep, sweep, 'sweep', 'Run one candidate per value'));
    }
  }
  return items;
}

function enumItems(def, env, bindings, used) {
  const e = def && env.registry.enumOf(def.result);
  if (!e) return [];
  const items = e.values
    .filter(v => !used?.has('id:' + v))
    .map(v => choice(v, v, 'value', e.labels[v], { aliases: [e.labels[v]] }));
  if (!used) {
    for (const [name, nodes] of bindings)
      if (nodes.every(n => n.k === 'id' && e.values.includes(n.name)))
        items.push(choice(name, name, 'binding', 'Use the declared ' + e.title));
    items.push(
      choice(
        'Compare ' + e.title + ' values',
        '{' + e.values.slice(0, 2).join(' | ') + '}',
        'sweep',
        'Run one candidate for each category'
      )
    );
  }
  return items;
}

// Restrict options after a complete clause using the next clause to the right.
// A trader can edit an earlier filter with a later group/measure still present.
function following(role, next, env, currentMeasures, allowsBoolean = true) {
  const head = next?.v;
  const out = [];
  function clause(label, text, detail) {
    out.push(choice(label, text, 'clause', detail));
  }
  if (role === 'on' || role === 'let') {
    if (head !== 'find' && head !== 'let') clause('find', 'find ', 'Choose an event');
    clause('let', 'let ', 'Bind a fixed value or sweep');
    return out;
  }
  if (['find', 'where'].includes(role)) clause('where', 'where ', 'Filter the matching closes');
  if (role === 'find') {
    out.push(
      choice('and', 'and ', 'operator', 'Require both events at the same close'),
      choice('or', 'or ', 'operator', 'Find either event at the same close')
    );
  } else if (allowsBoolean && (role === 'where' || role === 'by')) {
    out.push(
      choice('and', 'and ', 'operator', 'Require another condition'),
      choice('or', 'or ', 'operator', 'Accept another condition')
    );
  }
  if (['find', 'where'].includes(role) && !['where', 'group'].includes(head))
    clause('group by', 'group by ', 'Partition matches by a category');
  if (!['where', 'group'].includes(head)) {
    const measure = exprOptions('measure', env).find(x => x.label === 'close_return');
    if (measure) {
      const available = ['1h', '4h', '12h', '24h', '48h', '7d'].filter(x => !currentMeasures.has(parseLiteral(x).node.ms));
      if (available.length)
        clause(
          'measure',
          'measure close_return(after: ' +
            (available.length > 1 ? '[' + available.slice(0, 2).join(', ') + ']' : available[0]) +
            ')',
          'Add forward returns at new horizons'
        );
    } else clause('measure', 'measure ', 'Measure an outcome');
  }
  return out;
}

function otherHorizons(tokens, editing, text) {
  const used = new Set();
  for (const t of tokens.filter(t => t.v === 'measure' && !t.parent)) {
    const name = tokens[t.i + 1],
      open = tokens[t.i + 2];
    if (name?.v !== 'close_return' || !open?.close || (editing >= t.start && editing < open.close.end)) continue;
    const call = parseExpression(text.slice(name.start, open.close.end)).ast;
    const node = call?.args?.find(a => a.name === 'after')?.value;
    for (const n of node?.k === 'vec' ? node.items : [node]) if (n?.k === 'dur') used.add(n.ms);
  }
  return used;
}

function atCursor(text, caret, selectionEnd) {
  const all = tokensOf(text);
  const insideComment = all.some(t => t.v.startsWith('--') && t.start <= caret && caret <= t.end);
  const tokens = all.filter(t => !t.v.startsWith('--'));
  // Comment removal changes array indices, but does not change nesting.
  tokens.forEach((t, i) => {
    t.i = i;
  });
  let from = caret,
    to = selectionEnd,
    prefix = '';
  let token = tokens.find(t => t.start < caret && caret <= t.end);
  if (caret === selectionEnd && !(word(token) || quoted(token))) {
    const right = tokens.find(t => t.start === caret);
    if (right && !clauseWords.has(right.v)) token = right;
  }
  if (caret === selectionEnd && token?.start === caret && token.close) {
    to = token.close.end;
  } else if (caret === selectionEnd && token && (word(token) || quoted(token))) {
    const completeKeyword = clauseWords.has(token.v) || ['and', 'or', 'not', 'by'].includes(token.v);
    const finishedQuote = quoted(token) && token.v.length > 1 && token.v.endsWith('"');
    if (!(caret === token.end && (completeKeyword || finishedQuote))) {
      from = token.start;
      to = token.end;
      prefix = text.slice(from, caret).replace(/^"/, '');
    }
  }
  return { tokens, insideComment, from, to, prefix };
}

function expressionChoices(role, env, bindings, horizons) {
  const items = exprOptions(role, env);
  if (env.selectedG1) {
    const selected = JSON.stringify(env.selectedG1),
      detector = items.find(i => i.label === 'exact_g1');
    if (detector && new Checker(env, () => {}).scalar(parseLiteral(selected).node, detector.def.params[0], detector.def, {})) {
      detector.insert = 'exact_g1(' + selected + ')';
    }
  }
  // A binding can be the event/state itself or a typed parameter of a new call.
  const check = new Checker(env, () => {});
  for (const [name, nodes] of bindings) {
    if (role !== 'measure' && nodes.every(n => check.slot(n, role === 'by' ? 'group' : role))) {
      items.unshift(choice(name, name, 'binding', 'Use the declared ' + name));
    }
    for (const item of items.filter(i => i.def)) {
      const schema = item.def,
        ast = parseExpression(item.insert).ast;
      const call = ast?.k === 'cmp' ? ast.left : ast;
      if (call?.k !== 'call') continue;
      for (const param of schema.params) {
        if (!nodes.every(n => check.arg(n, param, schema, { calendar: { name: env.calendars.keys().next().value } }))) continue;
        const args = call.args.filter(a => (a.name || schema.positional) !== param.name);
        const ref = { k: 'id', name };
        const changed = { ...call, args: [...args, { name: param.name, value: ref }] };
        const insert = printExpr(ast === call ? changed : { ...ast, left: changed });
        items.push(
          choice(schema.name + ' with ' + name, insert, schema.kind, 'Use ' + name + ' as ' + param.name, {
            aliases: [name, schema.name],
          })
        );
      }
    }
  }
  if (role !== 'measure' || !horizons.size) return items;
  return items.flatMap(x => {
    if (x.label !== 'close_return') return [x];
    const free = ['1h', '4h', '12h', '24h', '48h', '7d'].filter(v => !horizons.has(parseLiteral(v).node.ms));
    return free.length ? [{ ...x, insert: 'close_return(after: ' + free[0] + ')' }] : [];
  });
}

/** All options are ordered and carry their own character replacement span. */
export function queryCompletions(text, caret, env, selectionEnd = caret) {
  let { tokens, insideComment, from, to, prefix } = atCursor(text, caret, selectionEnd);
  // Multi-word catalog searches may begin before the token containing the caret.
  const roleStart = tokens.findLast(t => t.end <= from && ['find', 'where', 'and', 'or', 'by', 'not'].includes(t.v));
  if (roleStart && prefix) {
    const parts = tokens.filter(t => t.start >= roleStart.end && t.start < to);
    if (parts.length > 1 && parts.every(t => word(t) && !clauseWords.has(t.v) && t.v !== 'by')) {
      from = parts[0].start;
      prefix = text.slice(from, caret);
    }
  }
  const ans = (context, items = []) => ({ context, items });
  if (insideComment) return ans('Comment');
  const left = tokens.filter(t => t.end <= from),
    prev = left.at(-1);
  const next = tokens.find(t => t.start >= to);
  const opener = left.findLast(t => Object.hasOwn(closes, t.v) && (!t.close || t.close.start >= from));
  const clause = left.findLast(t => !t.parent && clauseWords.has(t.v));
  const section = clause?.v === 'group' ? 'by' : clause?.v;
  const siblings = tokens.filter(t => t.parent === opener && t !== opener?.close);
  const bindings = bindingValues(tokens, text);
  const nextClause = tokens.find(t => t.start >= to && !t.parent && clauseWords.has(t.v));
  const horizons = otherHorizons(tokens, from, text);
  let context = 'Question',
    options = [];

  const set = (name, items) => {
    context = name;
    options = items;
  };

  // A vector or sweep inherits its slot from its enclosing call or comparison.
  const inList = opener && ['[', '{'].includes(opener.v);
  const callOpen = inList ? opener.parent : opener;
  const def = callOpen && env.registry.get(tokens[callOpen.i - 1]?.v);
  if (def && def.status !== 'planned' && callOpen.v === '(') {
    const direct = tokens.filter(t => t.parent === callOpen && t !== callOpen.close);
    const lastComma = direct.findLast(t => t.v === ',' && t.end <= (inList ? opener.start : from));
    const segment = direct.filter(t => t.start >= (lastComma?.end ?? callOpen.end));
    const key = segment[0],
      colon = segment[1];
    const named = colon?.v === ':';
    const param = def.params.find(p => p.name === (named ? key.v : def.positional));
    const editingKey = !inList && (!named || from < colon.end);
    const usedKeys = new Set(direct.filter((t, i) => direct[i + 1]?.v === ':' && (t !== key || !editingKey)).map(t => t.v));
    if (lastComma && !direct.slice(0, direct.indexOf(lastComma)).some(t => t.v === ':') && def.positional)
      usedKeys.add(def.positional);
    const exclude =
      def.name === 'close_return' && param?.name === 'after' ? new Set([...horizons].map(ms => 'dur:' + ms)) : new Set();
    const valueStart = named ? colon.end : (lastComma?.end ?? callOpen.end);
    const valueAlready = direct.some(t => t.end <= from && t.start >= valueStart && t.v !== ',' && (t !== opener || !inList));
    if (!named && !lastComma && valueAlready && def.positional) usedKeys.add(def.positional);
    const argEnd = segment.find(t => t.v === ',')?.start ?? callOpen.close?.start ?? text.length;
    const existing = named && editingKey ? parseExpression(text.slice(colon.end, argEnd)).ast : null;
    const checker = new Checker(env, () => {});
    const groupKeys = () =>
      def.params
        .filter(
          p =>
            !usedKeys.has(p.name) &&
            (!existing ||
              existing.k === 'choices' ||
              (existing.k === 'id' && bindings.has(existing.name)) ||
              checker.arg(existing, p, def, {}))
        )
        .map(p => {
          const sample = scalarOptions(p, def, env, bindings, false)[0]?.insert || sampleFor(p, def);
          const insert = named && from < colon.end ? p.name : p.name + ': ' + (sample || '');
          return choice(p.name + ':', insert, 'parameter', p.doc, { aliases: [p.name] });
        });
    if (inList) {
      const used = new Set(
        siblings
          .filter(t => (t.end <= from || t.start >= to) && (quoted(t) || word(t)))
          .map(t => parseLiteral(t.v).node)
          .filter(Boolean)
          .map(literalKey)
      );
      for (const key of exclude) used.add(key);
      set(param?.name || 'Value', scalarOptions(param, def, env, bindings, opener.v, used, prefix));
      if (prev && prev.parent === opener && !['|', ','].includes(prev.v) && !prefix) {
        const separator = opener.v === '[' ? ',' : '|';
        const items = [choice(separator, separator + ' ', 'operator', opener.v === '[' ? 'Add a column' : 'Add a candidate')];
        if (!opener.close && (separator === ',' || siblings.some(t => t.v === '|')))
          items.push(choice(closes[opener.v], closes[opener.v], 'operator', 'Finish these values'));
        set('Values', items);
      }
    } else if (!editingKey && !valueAlready) {
      set(param?.name || 'Value', scalarOptions(param, def, env, bindings, false, exclude, prefix));
    } else if (!editingKey || (valueAlready && !prefix && !named)) {
      const options = groupKeys().map(x => ({ ...x, insert: ', ' + x.insert }));
      if (!callOpen.close && def.params.every(p => !p.required || usedKeys.has(p.name)))
        options.push(choice(')', ')', 'operator', 'Finish this call'));
      set('Arguments', options);
    } else {
      const pos =
        !lastComma && def.positional && !named ? scalarOptions(param, def, env, bindings, false, exclude, prefix) : [];
      set(def.title, [...pos, ...groupKeys()]);
    }
  } else if (
    callOpen?.v === '(' &&
    word(tokens[callOpen.i - 1]) &&
    !['and', 'or', 'not', 'find', 'where', 'by'].includes(tokens[callOpen.i - 1].v)
  ) {
    set('Unresolved call', []);
  } else if (section === 'let' && (!opener || inList)) {
    const name = tokens[clause.i + 1],
      eq = tokens[clause.i + 2];
    if (!name || from <= name.start)
      set('Binding', [choice('lookback', 'lookback = {12h | 24h}', 'binding', 'Name a duration sweep')]);
    else if (!eq || from < eq.end) set('Binding value', [choice('=', '= 12h', 'operator', 'Assign a scalar or a sweep')]);
    else if (prev === eq || inList || from <= tokens[clause.i + 3]?.start) {
      const catValues = env.registry.implemented().flatMap(d => env.registry.enumOf(d.result)?.values || []);
      const names = [...new Set([...env.registry.named].map(([n, d]) => d.canonicalName || n))];
      const values = [
        '12h',
        '24h',
        '48h',
        '2.5%',
        '35%',
        '1',
        ...catValues,
        ...env.calendars.keys(),
        ...names.map(n => JSON.stringify(n)),
      ];
      if (!inList) values.push('{12h | 24h}', '{2% | 3%}');
      set(
        'Binding value',
        values.map(v => choice(v, v, v.startsWith('{') ? 'sweep' : 'value', 'Bind this value'))
      );
    } else set('Next clause', following(section, nextClause, env, horizons));
  } else if (inList && opener.v === '{' && !['=', '!='].includes(tokens[opener.i - 1]?.v)) {
    const role = ['find', 'where', 'by'].includes(section) ? section : 'where';
    const used = new Set(siblings.filter(t => t.end <= from || t.start >= to).map(t => t.v));
    set(
      'Pattern choices',
      exprOptions(role, env).filter(i => i.insert.startsWith('"') && !used.has(i.insert))
    );
  } else if (prev?.v === '=' || prev?.v === '!=' || (inList && section !== 'let')) {
    const op = inList ? left[left.indexOf(opener) - 1] : prev;
    const ending = tokens[op?.i - 1];
    const fn = ending?.v === ')' ? env.registry.get(tokens[(ending.parent?.i ?? 0) - 1]?.v) : null;
    const used = inList ? new Set(siblings.filter(t => t.end <= from || t.start >= to).map(t => 'id:' + t.v)) : null;
    const values = enumItems(fn, env, bindings, used);
    if (!inList) {
      const names = bindings.get(ending?.v)?.map(n => n.name) || [ending?.v];
      for (const item of exprOptions('by', env).filter(i => i.kind === 'categorical')) {
        const cat = env.registry.enumOf(item.def.result);
        if (item.def.result === fn?.result || names.every(v => cat.values.includes(v))) values.push(item);
      }
    }
    set('Comparison value', values);
  } else if (!clause) {
    set('Market', [
      choice(
        'on',
        'on ' + env.recording.instrument + ' ' + env.recording.barText + '\n',
        'clause',
        'Start with the recorded market'
      ),
    ]);
  } else if (section === 'on') {
    const market = tokens[clause.i + 1],
      frame = tokens[clause.i + 2];
    if (!market || from <= market.start)
      set('Market', [choice(env.recording.instrument, env.recording.instrument, 'market', env.recording.venue)]);
    else if (!frame || from <= frame.start)
      set('Timeframe', [choice(env.recording.barText, env.recording.barText, 'duration', 'Recorded bar interval')]);
    else set('Next clause', following(section, nextClause, env, horizons));
  } else if (prev?.v === 'group') {
    set('Group', [choice('by', 'by ', 'clause', 'Choose the grouping dimension')]);
  } else if (['find', 'where', 'by', 'measure', 'and', 'or', 'not', '('].includes(prev?.v)) {
    const role = ['and', 'or', 'not', '('].includes(prev.v)
      ? section === 'find'
        ? 'find'
        : section === 'by' && prev.v === '('
          ? 'by'
          : 'where'
      : prev.v;
    set(role, prev.v === 'not' && role === 'find' ? [] : expressionChoices(role, env, bindings, horizons));
  } else {
    const f = prev?.v === ')' ? env.registry.get(tokens[(prev.parent?.i ?? 0) - 1]?.v) : null;
    const cats = f && env.registry.enumOf(f.result);
    if (cats && ['where', 'by'].includes(section)) {
      const compare = ['=', '!='].map(op => choice(op, op + ' ' + cats.values[0], 'operator', 'Compare ' + cats.title));
      set('Compare', section === 'by' ? [...compare, ...following(section, nextClause, env, horizons, false)] : compare);
    } else {
      set('Next clause', following(section, nextClause, env, horizons));
    }
  }

  // Inside a Boolean group only another operand or the closing parenthesis is
  // legal; study-level clauses resume after the group closes.
  if (opener?.v === '(' && !def && context === 'Next clause') {
    options = options.filter(x => x.kind === 'operator');
    if (!opener.close) options.push(choice(')', ')', 'operator', 'Finish the grouped expression'));
  }
  const filter = normalized(prefix);
  const existingCall = next?.v === '(' && (from !== to || prefix) ? next : null;
  const search = x => [x.label, x.insert, ...(x.aliases || []), x.detail].map(normalized);
  const canFinishCall = def?.status !== 'planned' && def && !inList && !callOpen.close && (!next || clauseWords.has(next.v));
  const mapped = options
    .map(x => {
      let stop = to,
        insert = x.insert;
      if (existingCall && !['parameter', 'value', 'clause'].includes(x.kind)) {
        stop = existingCall.close?.end ?? to;
        const fn = x.def?.name;
        if (fn && text.slice(from, to) === fn) {
          insert = fn;
          stop = to;
        }
        if (existingCall.close && ['=', '!='].includes(tokens[existingCall.close.i + 1]?.v) && !(fn && insert === fn)) {
          const rhs = tokens[existingCall.close.i + 2];
          const original = env.registry.get(text.slice(from, to));
          if (x.def?.kind === 'categorical' && original?.result === x.def.result)
            insert = insert.replace(/\s+(?:=|!=)\s+\w+$/, '');
          else if (rhs && !clauseWords.has(rhs.v)) stop = (rhs.close || tokens[rhs.i + 1]?.close || rhs).end;
        }
      }
      if (canFinishCall && ['value', 'parameter', 'binding', 'sweep', 'vector', 'state'].includes(x.kind)) {
        const before = text.slice(tokens[callOpen.i - 1].start, from);
        const call = parseExpression(before + insert + ')').ast;
        if (call?.k === 'call' && def.params.every(p => !p.required || argValue(call, def, p))) insert += ')';
      }
      if (!filter || search(x).some(s => s.includes(filter))) {
        const score = filter
          ? Math.min(...search(x).map(s => (s === filter ? 0 : s.startsWith(filter) ? 1 : s.includes(filter) ? 2 : 3)))
          : 0;
        return { ...x, from, to: stop, insert, score };
      }
      return null;
    })
    .filter(Boolean)
    .sort((a, b) => a.score - b.score);
  const items = mapped.map(({ def, score, ...item }) => item);
  if (prefix && caret === to && from < caret && !opener && !existingCall && !next) {
    const exact = items.some(x => normalized(x.label) === filter || normalized(x.insert) === filter);
    const canRefine =
      (section === 'on' && context === 'Timeframe') ||
      (['find', 'where', 'by'].includes(section) && (context === section || context === 'Comparison value'));
    if (exact && canRefine)
      items.push(...following(section, nextClause, env, horizons).map(x => ({ ...x, from: caret, to: caret })));
  }
  return ans(context, items);
}

export function applyCompletion(text, item) {
  let insert = item.insert;
  if (item.from > 0 && /[\p{ID_Continue}")\]}%]/u.test(text[item.from - 1]) && /^[\p{ID_Continue}"{]/u.test(insert))
    insert = ' ' + insert;
  if (item.to < text.length && /[\p{ID_Continue}")\]}%]$/u.test(insert) && /^[\p{ID_Continue}"]/u.test(text.slice(item.to)))
    insert += ' ';
  if (/\s$/.test(insert) && /^\s/.test(text.slice(item.to))) insert = insert.trimEnd();
  const caret = item.from + insert.length;
  return { text: text.slice(0, item.from) + insert + text.slice(item.to), caret };
}
