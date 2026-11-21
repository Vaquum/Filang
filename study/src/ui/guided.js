// Guided editor: renders the parsed question with controls generated from registry signatures.
// Every edit produces a new AST; the app prints it to canonical text and re-parses it, so both
// editors always share one parsed structure, one validator and one evaluator.

import { h } from './dom.js';
import { printExpr, parseLiteral, parseExpression, setAt, removeAt, getAt } from '../lang.js';
import { ENUMS } from '../registry.js';
import { nodeLabel, argFor, whereExample } from '../assist.js';
import { ratFromText, ratToDecimalText } from '../num.js';

const DUR_LADDER = ['15m', '30m', '45m', '1h', '2h', '4h', '6h', '8h', '12h', '24h', '48h', '72h'];
const durMs = (t) => { const m = /^(\d+)([mhd])$/.exec(t); return m ? Number(m[1]) * { m: 60000, h: 3600000, d: 86400000 }[m[2]] : NaN; };

function nextValue(node, used = []) {
  const taken = new Set(used.map((n) => printExpr(n)));
  if (node.k === 'dur') {
    const next = DUR_LADDER.find((d) => durMs(d) > node.ms && !taken.has(d)) || `${node.amount * 2}${node.unit}`;
    return parseLiteral(next).node;
  }
  if (node.k === 'pct' || node.k === 'num') {
    const r = ratFromText(node.text, false);
    const step = node.k === 'pct' ? { num: 1n, den: 1n } : { num: 1n, den: 100n };
    let cur = r;
    for (let k = 0; k < 50; k++) {
      cur = { num: cur.num * step.den + step.num * cur.den, den: cur.den * step.den };
      const txt = ratToDecimalText(cur) + (node.k === 'pct' ? '%' : '');
      if (!taken.has(txt)) return parseLiteral(txt).node;
    }
  }
  if (node.k === 'id') {
    const e = Object.values(ENUMS).find((en) => en.values.includes(node.name));
    if (e) { const v = e.values.find((x) => !taken.has(x) && x !== node.name); if (v) return { k: 'id', name: v }; }
  }
  return null;
}

const enumForCall = (n) => (n && n.k === 'call' ? (n.name === 'weekday' ? ENUMS.SessionDay : n.name === 'completed_trend' ? ENUMS.Trend : null) : null);

export function renderGuided(root, opts) {
  const { ast, errors = [], registry: reg, env, onEdit, onInspect, letNames = [] } = opts;
  let uid = 0;
  const id = (p) => `g-${p}-${++uid}`;
  const commit = (newAst, what) => onEdit(newAst, what);
  const edit = (path, node, what) => commit(setAt(ast, path, node), what);
  const errFor = (node) => (node && node.start !== undefined ? errors.find((e) => e.start >= node.start && e.end <= node.end) : null);

  // ---------------- scalar editors
  function literalInput(node, path, labelText, accept, what) {
    const iid = id('lit');
    const err = errFor(node);
    const input = h('input', {
      id: iid, type: 'text', class: 'g-input', value: printExpr(node), size: Math.max(4, printExpr(node).length + 1),
      'aria-label': labelText, spellcheck: 'false', 'aria-invalid': err ? 'true' : null, title: err ? err.message : null,
    });
    const msg = h('span', { class: 'g-msg', role: 'alert' });
    const apply = () => {
      const r = parseLiteral(input.value);
      if (r.error || !accept.includes(r.node.k)) {
        input.setAttribute('aria-invalid', 'true');
        msg.textContent = r.error || `expected ${accept.map((k) => ({ dur: 'a duration (30m)', pct: 'a percentage (35%)', num: 'a number (0.35)', str: 'a string', id: 'a name' }[k])).join(' or ')}`;
        return;
      }
      if (printExpr(r.node) === printExpr(node)) return;
      edit(path, r.node, `${what}: ${printExpr(node)} → ${printExpr(r.node)}`);
    };
    input.addEventListener('change', apply);
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); apply(); } });
    return h('span', { class: 'g-lit' }, input, msg);
  }

  function enumSelect(node, path, e, labelText) {
    const sel = h('select', { class: 'g-select', 'aria-label': labelText },
      e.values.map((v) => h('option', { value: v, selected: v === node.name }, `${v} — ${e.labels[v]}`)));
    if (!e.values.includes(node.name)) sel.prepend(h('option', { value: node.name, selected: true }, `${node.name} (not a value)`));
    sel.addEventListener('change', () => edit(path, { k: 'id', name: sel.value }, `${labelText}: ${node.name} → ${sel.value}`));
    return sel;
  }

  function scalarEditor(node, path, ctx) {
    const lbl = ctx.label || 'value';
    if (node.k === 'id' && letNames.includes(node.name)) {
      return h('span', { class: 'g-ref', title: 'value comes from a let binding (edit it there)' }, '→ ', h('code', null, node.name), ' (let)');
    }
    if (ctx.type === 'Calendar' || (node.k === 'id' && env.calendars.has(node.name))) {
      if (env.calendars.size === 1 && env.calendars.has(node.name)) {
        return h('code', { class: 'g-code', title: 'the only registered calendar (pinned table)' }, node.name);
      }
      const sel = h('select', { class: 'g-select', 'aria-label': lbl }, [...env.calendars.keys()].map((c) => h('option', { value: c, selected: c === node.name }, c)));
      if (!env.calendars.has(node.name)) sel.prepend(h('option', { selected: true, value: node.name }, `${node.name} (unknown)`));
      sel.addEventListener('change', () => edit(path, { k: 'id', name: sel.value }, `${lbl} → ${sel.value}`));
      return sel;
    }
    if (ctx.enum && node.k === 'id') return enumSelect(node, path, ctx.enum, lbl);
    if (ctx.type === 'Duration' || node.k === 'dur') return literalInput(node, path, `${lbl} (duration)`, ['dur'], lbl);
    if (ctx.type === 'Ratio' || node.k === 'pct') return literalInput(node, path, `${lbl} (ratio: 35% or 0.35)`, ['pct', 'num'], lbl);
    if (node.k === 'num') return literalInput(node, path, `${lbl} (number)`, ['num'], lbl);
    if (node.k === 'str' && ctx.type === 'State') return namedSelect(node, path, 'state', lbl);
    return h('code', { class: 'g-code' }, printExpr(node));
  }

  function sweepButton(node, path, label) {
    const nv = nextValue(node, [node]);
    if (!nv || (node.k === 'id' && !Object.values(ENUMS).some((e) => e.values.includes(node.name)))) return null;
    return h('button', {
      type: 'button', class: 'g-btn', title: 'turn this value into a sweep: each choice runs as its own candidate',
      onclick: () => edit(path, { k: 'choices', items: [node, nv] }, `${label}: ${printExpr(node)} → {${printExpr(node)} | ${printExpr(nv)}}`),
    }, '+ sweep');
  }

  function valueEditor(node, path, ctx) {
    const lbl = ctx.label || 'value';
    if (node.k === 'choices') {
      return h('span', { class: 'g-choices', role: 'group', 'aria-label': `${lbl}: sweep choices` },
        h('span', { class: 'g-tag', title: 'choices: each value is its own candidate run (one sweep axis)' }, 'sweep'),
        node.items.map((it, k) => h('span', { class: 'g-chip' },
          scalarEditor(it, [...path, 'items', k], { ...ctx, label: `${lbl} choice ${k + 1}` }),
          h('button', {
            type: 'button', class: 'g-x', 'aria-label': `remove choice ${printExpr(it)}`,
            onclick: () => (node.items.length > 2
              ? commit(removeAt(ast, [...path, 'items', k]), `${lbl}: remove choice ${printExpr(it)}`)
              : edit(path, node.items[1 - k], `${lbl}: {…} → ${printExpr(node.items[1 - k])}`)),
          }, '×'))),
        (() => {
          const nv = nextValue(node.items[node.items.length - 1], node.items);
          return nv ? h('button', { type: 'button', class: 'g-btn', onclick: () => edit([...path, 'items'], [...node.items, nv], `${lbl}: add choice ${printExpr(nv)}`) }, '+ choice') : null;
        })());
    }
    if (node.k === 'vec') {
      return h('span', { class: 'g-vector', role: 'group', 'aria-label': `${lbl}: vector` },
        h('span', { class: 'g-tag', title: 'vector: one argument; each value becomes a column in the same run' }, 'columns'),
        node.items.map((it, k) => h('span', { class: 'g-chip' },
          scalarEditor(it, [...path, 'items', k], { ...ctx, label: `${lbl} value ${k + 1}` }),
          node.items.length > 1 ? h('button', { type: 'button', class: 'g-x', 'aria-label': `remove ${printExpr(it)}`, onclick: () => commit(removeAt(ast, [...path, 'items', k]), `${lbl}: remove ${printExpr(it)}`) }, '×') : null)),
        (() => {
          const nv = nextValue(node.items[node.items.length - 1], node.items);
          return nv ? h('button', { type: 'button', class: 'g-btn', onclick: () => edit([...path, 'items'], [...node.items, nv], `${lbl}: add column ${printExpr(nv)}`) }, '+ column') : null;
        })());
    }
    const parts = [scalarEditor(node, path, ctx)];
    if (ctx.list && node.k === 'dur') {
      const nv = nextValue(node, [node]);
      if (nv) parts.push(h('button', { type: 'button', class: 'g-btn', title: 'a vector is one argument; each value becomes a column', onclick: () => edit(path, { k: 'vec', items: [node, nv] }, `${lbl}: ${printExpr(node)} → [${printExpr(node)}, ${printExpr(nv)}]`) }, '+ column'));
    }
    if (!(node.k === 'id' && letNames.includes(node.name)) && ctx.type !== 'Calendar' && ctx.type !== 'State' && !(node.k === 'str')) {
      const sb = sweepButton(node, path, lbl);
      if (sb) parts.push(sb);
    }
    return h('span', { class: 'g-value' }, parts);
  }

  // ---------------- named definitions & calls
  function namedSelect(node, path, kind, lbl) {
    const names = [...reg.named].filter(([, nd]) => nd.kind === kind).map(([n]) => n);
    if (names.length === 1 && names[0] === node.value) {
      return h('code', { class: 'g-code', title: `the only named ${kind} definition` }, JSON.stringify(node.value));
    }
    const sel = h('select', { class: 'g-select', 'aria-label': lbl }, names.map((n) => h('option', { value: n, selected: n === node.value }, n)));
    if (!names.includes(node.value)) sel.prepend(h('option', { value: node.value, selected: true }, `${node.value} (unknown)`));
    sel.addEventListener('change', () => edit(path, { k: 'str', value: sel.value }, `${lbl} → "${sel.value}"`));
    return sel;
  }

  function namedEditor(node, path, kind, lbl) {
    const nd = reg.named.get(node.value);
    const err = errFor(node);
    return h('div', { class: `g-named${err ? ' g-has-err' : ''}` },
      h('div', { class: 'g-call-head' },
        namedSelect(node, path, kind, lbl),
        nd ? h('button', { type: 'button', class: 'g-btn', title: 'replace the immutable named definition by the equivalent typed call so its parameters become editable', onclick: () => {
          const def = reg.get(nd.def);
          const args = def.params.map((p) => `${p.name}: ${nd.args[p.name] ?? p.default}`).join(', ');
          edit(path, parseExpression(`${nd.def}(${args})`).ast, `"${node.value}" → ${nd.def}(${args})`);
        } }, 'edit parameters') : null,
        nd ? h('button', { type: 'button', class: 'linkish', onclick: () => onInspect(nd.def, node.value) }, 'definition') : null),
      h('div', { class: 'g-friendly' }, nodeLabel(node, reg)),
      err ? h('div', { class: 'g-err', role: 'note' }, err.message) : null);
  }

  function callEditor(node, path, slotKind) {
    const def = reg.get(node.name);
    const err = errFor({ start: node.nameStart, end: node.nameEnd }) || (def ? null : errFor(node));
    if (!def || def.status === 'planned') {
      return h('div', { class: 'g-call g-has-err' }, h('code', null, printExpr(node)),
        h('div', { class: 'g-err' }, err ? err.message : def ? `${def.name} is planned (design example), not executable` : `unknown function ${node.name}`),
        def ? h('button', { type: 'button', class: 'linkish', onclick: () => onInspect(def.name) }, 'definition') : null);
    }
    const rows = [];
    const usedArgs = new Set();
    for (const p of def.params) {
      const a = argFor(node, def, p.name);
      const ai = a ? node.args.indexOf(a) : -1;
      if (a) usedArgs.add(ai);
      const pid = id('p');
      let editor;
      if (a) {
        const vpath = [...path, 'args', ai, 'value'];
        if (p.type === 'State') editor = stateEditor(a.value, vpath, `${def.name} ${p.name}`);
        else editor = valueEditor(a.value, vpath, { type: p.type, list: p.list, label: `${def.name} ${p.name}` });
      } else {
        editor = h('span', { class: 'g-default' }, p.required ? h('span', { class: 'g-err' }, 'required — missing') : `default ${p.default}`);
      }
      const ctl = [];
      if (!a) {
        const val = p.default || (p.type === 'Duration' ? '30m' : p.type === 'Calendar' ? [...env.calendars.keys()][0] : p.type === 'State' ? '"Quiet range"' : '35%');
        ctl.push(h('button', { type: 'button', class: 'g-btn', onclick: () => {
          const lit = parseExpression(val).ast;
          commit(setAt(ast, [...path, 'args'], [...node.args, { name: p.name, value: lit }]), `${def.name}: set ${p.name}: ${val}`);
        } }, p.required ? `add ${p.name}` : 'set'));
      } else if (!p.required) {
        ctl.push(h('button', { type: 'button', class: 'g-x', 'aria-label': `reset ${p.name} to default ${p.default}`, title: `reset to default ${p.default}`, onclick: () => commit(removeAt(ast, [...path, 'args', ai]), `${def.name}: reset ${p.name}`) }, '×'));
      }
      rows.push(h('div', { class: 'g-param' },
        h('span', { class: 'g-pname', id: pid, title: `${p.type}${p.list ? ' or [..]' : ''} — ${p.doc}` }, p.name, a && a.name === null ? h('span', { class: 'g-pos' }, ' (positional)') : null),
        editor, ctl));
    }
    node.args.forEach((a, ai) => {
      if (usedArgs.has(ai)) return;
      rows.push(h('div', { class: 'g-param g-has-err' }, h('span', { class: 'g-pname' }, a.name || '(positional)'),
        h('code', null, printExpr(a.value)), h('span', { class: 'g-err' }, a.name ? ` not an argument of ${def.name}` : ` ${def.name} takes no positional argument`),
        h('button', { type: 'button', class: 'g-btn', onclick: () => commit(removeAt(ast, [...path, 'args', ai]), `${def.name}: remove ${a.name || 'positional argument'}`) }, 'remove')));
    });
    const own = errors.find((e) => e.start === node.start && e.end === node.end);
    return h('div', { class: `g-call${own ? ' g-has-err' : ''}`, 'data-kind': slotKind || def.kind },
      h('div', { class: 'g-call-head' },
        h('span', { class: 'g-friendly' }, nodeLabel(node, reg)),
        h('button', { type: 'button', class: 'linkish', onclick: () => onInspect(def.name) }, `${def.name}@${def.version}`),
        def.status === 'extension' ? h('span', { class: 'g-tag ext' }, 'extension') : null),
      h('div', { class: 'g-params' }, rows),
      own ? h('div', { class: 'g-err' }, own.message) : null);
  }

  function stateEditor(node, path, lbl) {
    if (node.k === 'str') return namedEditor(node, path, 'state', lbl);
    if (node.k === 'call') {
      const box = callEditor(node, path, 'state');
      const names = [...reg.named].filter(([, nd]) => nd.kind === 'state' && nd.def === node.name);
      if (names.length) box.querySelector('.g-call-head').appendChild(h('button', { type: 'button', class: 'g-btn', onclick: () => edit(path, { k: 'str', value: names[0][0] }, `→ "${names[0][0]}"`) }, `use "${names[0][0]}"`));
      return box;
    }
    return valueEditor(node, path, { label: lbl });
  }

  // ---------------- boolean expressions
  function boolEditor(node, path) {
    switch (node.k) {
      case 'call': return callEditor(node, path);
      case 'str': return namedEditor(node, path, reg.named.get(node.value) ? reg.named.get(node.value).kind : 'state', 'named definition');
      case 'cmp': {
        const e = enumForCall(node.left) || enumForCall(node.right);
        const side = (n, p) => (n.k === 'call' ? callEditor(n, p) : valueEditor(n, p, { enum: e, label: 'value' }));
        const op = h('select', { class: 'g-select', 'aria-label': 'comparison' }, ['=', '!='].map((o) => h('option', { value: o, selected: node.op === o }, o === '=' ? 'is' : 'is not')));
        if (!['=', '!='].includes(node.op)) op.prepend(h('option', { selected: true, value: node.op }, node.op));
        op.addEventListener('change', () => edit([...path, 'op'], op.value, `comparison ${node.op} → ${op.value}`));
        const own = errors.find((x) => x.start >= node.start && x.end <= node.end && !(x.start >= node.left.start && x.end <= node.left.end));
        return h('div', { class: 'g-cmp' }, side(node.left, [...path, 'left']), op, side(node.right, [...path, 'right']), own ? h('div', { class: 'g-err' }, own.message) : null);
      }
      case 'and': case 'or': {
        const other = node.k === 'and' ? 'or' : 'and';
        return h('div', { class: 'g-bool' },
          node.items.map((it, k) => [
            k > 0 ? h('button', { type: 'button', class: 'g-op', title: `switch to ${other}`, onclick: () => edit(path, { ...node, k: other }, `${node.k} → ${other}`) }, node.k) : null,
            h('div', { class: 'g-operand' }, boolEditor(it, [...path, 'items', k]),
              h('button', { type: 'button', class: 'g-x', 'aria-label': `remove operand ${printExpr(it)}`, onclick: () => (node.items.length > 2 ? commit(removeAt(ast, [...path, 'items', k]), `remove ${printExpr(it)}`) : edit(path, node.items[1 - k], `remove ${printExpr(it)}`)) }, '×')),
          ]));
      }
      case 'not':
        return h('div', { class: 'g-not' }, h('span', { class: 'g-op' }, 'not'), boolEditor(node.item, [...path, 'item']),
          h('button', { type: 'button', class: 'g-btn', onclick: () => edit(path, node.item, 'remove not') }, 'remove not'));
      default:
        return h('div', { class: 'g-raw' }, h('code', null, printExpr(node)), h('span', { class: 'g-muted' }, ' edit this in the Text tab'));
    }
  }

  // ---------------- clause cards
  const card = (title, body, tools, kind) => h('div', { class: `g-card ${kind || ''}` }, h('div', { class: 'g-card-head' }, h('span', { class: 'g-clause' }, title), tools ? h('span', { class: 'g-tools' }, tools) : null), body);
  const out = [];

  out.push(card('on', h('div', { class: 'g-on' }, h('code', null, `${ast.on.instrument.name} ${ast.on.bar.text}`),
    h('span', { class: 'g-muted' }, ` — ${env.recording.instrument} ${env.recording.barText} is the only enabled recording (${env.recording.venue}, ${env.recording.rangeText})`),
    errFor(ast.on.instrument) || errFor(ast.on.bar) ? h('div', { class: 'g-err' }, (errFor(ast.on.instrument) || errFor(ast.on.bar)).message) : null)));

  ast.lets.forEach((b, k) => {
    const used = new RegExp(`\\b${b.name}\\b`).test([ast.find, ...ast.wheres, ast.group, ...ast.measures].filter(Boolean).map((n) => printExpr(n)).join(' '));
    out.push(card(`let ${b.name}`, h('div', { class: 'g-let' }, valueEditor(b.value, ['lets', k, 'value'], { label: `let ${b.name}` }),
      h('div', { class: 'g-muted' }, b.value.k === 'choices' ? 'one sweep axis, however many times it is referenced' : 'a scalar binding')),
    used ? null : h('button', { type: 'button', class: 'g-btn', onclick: () => commit(removeAt(ast, ['lets', k]), `remove let ${b.name}`) }, 'remove')));
  });

  const events = [
    ...[...reg.named].filter(([, nd]) => nd.kind === 'event').map(([n]) => ({ key: `named:${n}`, label: `"${n}" (named)`, text: JSON.stringify(n) })),
    ...reg.implemented().filter((f) => f.kind === 'event').map((f) => ({ key: `fn:${f.name}`, label: `${f.name}(…)`, text: f.example })),
  ];
  const curKey = ast.find.k === 'str' ? `named:${ast.find.value}` : ast.find.k === 'call' ? `fn:${ast.find.name}` : '';
  const evSel = h('select', { class: 'g-select', 'aria-label': 'event definition' }, events.map((e) => h('option', { value: e.key, selected: e.key === curKey }, e.label)));
  if (!events.some((e) => e.key === curKey)) evSel.prepend(h('option', { selected: true, value: '' }, printExpr(ast.find)));
  evSel.addEventListener('change', () => { const e = events.find((x) => x.key === evSel.value); if (e) edit(['find'], parseExpression(e.text).ast, `find → ${e.text}`); });
  const findBody = ast.find.k === 'str' ? namedEditor(ast.find, ['find'], 'event', 'find') : ast.find.k === 'call' ? callEditor(ast.find, ['find'], 'event') : ast.find.k === 'choices' ? valueEditor(ast.find, ['find'], { label: 'find' }) : boolEditor(ast.find, ['find']);
  out.push(card('find', h('div', null, h('div', { class: 'g-row' }, h('span', { class: 'g-muted' }, 'event: '), evSel), findBody), null, 'find'));

  ast.wheres.forEach((w, k) => {
    const tools = [
      h('button', { type: 'button', class: 'g-btn', onclick: () => commit(removeAt(ast, ['wheres', k]), `remove where #${k + 1}`) }, 'remove'),
    ];
    if (!ast.group) {
      const grp = w.k === 'cmp' && enumForCall(w.left) ? w.left : w.k === 'cmp' && enumForCall(w.right) ? w.right : (w.k === 'call' || w.k === 'str') ? w : null;
      if (grp) tools.unshift(h('button', { type: 'button', class: 'g-btn', title: 'keep every match and split it into buckets instead of filtering', onclick: () => commit({ ...ast, wheres: ast.wheres.filter((_, j) => j !== k), group: grp }, `where #${k + 1} → group by ${printExpr(grp)}`) }, 'make it a group'));
    }
    const compound = w.k !== 'call' && w.k !== 'str';
    out.push(card(`where #${k + 1}`, h('div', null, compound ? h('div', { class: 'g-friendly g-clause-label' }, nodeLabel(w, reg)) : null, boolEditor(w, ['wheres', k]), h('code', { class: 'g-canon' }, printExpr(w))), tools, 'where'));
  });

  const condTemplates = [
    ...reg.implemented().filter((f) => f.kind === 'condition' || f.kind === 'categorical').map((f) => ({ label: `${f.title}${f.status === 'extension' ? ' (extension)' : ''} — ${whereExample(f)}`, text: whereExample(f) })),
    ...[...reg.named].filter(([, nd]) => nd.kind === 'state').map(([n]) => ({ label: `"${n}" sampled at the anchor`, text: JSON.stringify(n) })),
  ];
  const addSel = h('select', { class: 'g-select', 'aria-label': 'add a where condition' }, h('option', { value: '' }, '+ add a where condition…'), condTemplates.map((c, k) => h('option', { value: String(k) }, c.label)));
  addSel.addEventListener('change', () => { const c = condTemplates[Number(addSel.value)]; if (c) commit({ ...ast, wheres: [...ast.wheres, parseExpression(c.text).ast] }, `add where ${c.text}`); });
  out.push(h('div', { class: 'g-add' }, addSel));

  if (ast.group) {
    const g = ast.group;
    const e = enumForCall(g);
    const tools = [h('button', { type: 'button', class: 'g-btn', onclick: () => commit({ ...ast, group: null }, 'remove group by') }, 'remove')];
    const vals = e ? e.values : ['true', 'false'];
    const fsel = h('select', { class: 'g-select', 'aria-label': 'bucket to keep as a filter' }, vals.map((v) => h('option', { value: v }, e ? `${v} — ${e.labels[v]}` : v)));
    const fbtn = h('button', { type: 'button', class: 'g-btn', onclick: () => {
      const v = fsel.value;
      const cond = e ? { k: 'cmp', op: '=', left: g, right: { k: 'id', name: v } } : v === 'true' ? g : { k: 'not', item: g };
      commit({ ...ast, group: null, wheres: [...ast.wheres, cond] }, `group by ${printExpr(g)} → where ${printExpr(cond)}`);
    } }, 'turn into filter');
    out.push(card('group by', h('div', null, g.k !== 'call' && g.k !== 'str' ? h('div', { class: 'g-friendly g-clause-label' }, nodeLabel(g, reg)) : null, boolEditorOrCat(g), h('div', { class: 'g-row' }, h('span', { class: 'g-muted' }, 'keep only bucket '), fsel, fbtn), h('code', { class: 'g-canon' }, printExpr(g))), tools, 'group'));
  } else {
    const groupTemplates = reg.implemented().filter((f) => f.kind === 'categorical' || f.kind === 'condition').map((f) => ({ label: `${f.title} — ${f.kind === 'categorical' ? f.example.replace(/\s*=.*$/, '') : f.example}`, text: f.kind === 'categorical' ? f.example.replace(/\s*=.*$/, '') : f.example }));
    const gsel = h('select', { class: 'g-select', 'aria-label': 'add group by' }, h('option', { value: '' }, '+ group by…'), groupTemplates.map((c, k) => h('option', { value: String(k) }, c.label)));
    gsel.addEventListener('change', () => { const c = groupTemplates[Number(gsel.value)]; if (c) commit({ ...ast, group: parseExpression(c.text).ast }, `group by ${c.text}`); });
    out.push(h('div', { class: 'g-add' }, gsel));
  }

  function boolEditorOrCat(g) { return g.k === 'call' ? callEditor(g, ['group']) : boolEditor(g, ['group']); }

  ast.measures.forEach((m, k) => {
    const tools = ast.measures.length > 1 ? [h('button', { type: 'button', class: 'g-btn', onclick: () => commit(removeAt(ast, ['measures', k]), `remove measure #${k + 1}`) }, 'remove')] : null;
    out.push(card(`measure #${k + 1}`, h('div', null, m.k === 'call' ? callEditor(m, ['measures', k], 'outcome') : h('code', null, printExpr(m)), h('code', { class: 'g-canon' }, printExpr(m))), tools, 'measure'));
  });

  root.replaceChildren(...out);
  return { getAt: (p) => getAt(ast, p) };
}
