import { priceControl } from './price-control.js';
import { h, mount, nextId } from './ui/dom.js';
import { parseExpression, printExpr, printQuestion } from './lang.js';
import { analyze } from './check.js';
import { argFor, nodeLabel } from './assist.js';
import { queryCompletions } from './query-completions.js';
import { optionList } from './study-menu.js';
import { isoUTC } from './data.js';
import { eventSeries } from './engine.js';
import { ENUMS } from './registry.js';

const action = (text, click, attrs = {}) => h('button', { type: 'button', onclick: click, ...attrs }, text);
const norm = (s) =>
  String(s || '')
    .normalize('NFKD')
    .replace(/\p{Diacritic}/gu, '')
    .toLowerCase()
    .replace(/[_-]/g, ' ');
const expr = (text) => {
  const parsed = parseExpression(text);
  if (parsed.error) throw Error(parsed.error.message);
  return parsed.ast;
};
const kind = { find: 'pattern', where: 'filter', group: 'grouping', measure: 'outcome' };
const clause = { find: 'find', where: 'where', group: 'group by', measure: 'measure' };
const source = (q) => 'on ' + q.on.instrument.name + ' ' + q.on.bar.text;
const definition = (node, reg) => {
  if (!node) return null;
  if (node.k === 'cmp') return definition(node.left, reg) || definition(node.right, reg);
  const name = node.name ?? node.value;
  if (typeof name !== 'string') return null;
  if (node.k === 'call') return reg.get(name);
  const named = reg.getNamed(name);
  return named?.patternId ? reg.getPattern(named.patternId) : reg.get(named?.def || name);
};
function label(node, reg) {
  if (node.k === 'not') return 'Not ' + label(node.item, reg);
  if (node.k === 'and' || node.k === 'or')
    return node.items.map((n) => label(n, reg)).join(' ' + node.k + ' ');
  const def = definition(node, reg);
  return def?.canonicalName || def?.title || node.value || printExpr(node);
}
function prefix(q, slot) {
  const lets = q.lets.map((b) => 'let ' + b.name + ' = ' + printExpr(b.value));
  const lines = [source(q), ...lets];
  if (slot !== 'find') lines.push('find ' + printExpr(q.find));
  return [...lines, clause[slot] + ' '].join('\n');
}
function replaceSlot(q, slot, i, e) {
  if (slot === 'find' || slot === 'group') q[slot] = e;
  else {
    const a = slot === 'where' ? q.wheres : q.measures;
    if (e) a.splice(i ?? a.length, i == null ? 0 : 1, e);
    else a.splice(i, 1);
  }
}
function prune(q) {
  const ids = new Set();
  function visit(n) {
    if (n === null || typeof n !== 'object') return;
    if (n.k === 'id') ids.add(n.name);
    Object.values(n).forEach(visit);
  }
  [q.find, ...q.wheres, q.group, ...q.measures].forEach(visit);
  q.lets = q.lets.filter((b) => ids.has(b.name));
  return q;
}
function applyValid(q, env, edit) {
  const text = printQuestion(prune(q));
  const analysis = analyze(text, env);
  if (!analysis.ok) throw Error(analysis.errors.map((e) => e.message).join(' '));
  if (!edit(text)) throw Error('The query could not run.');
}

function parameters(root, reg) {
  const fields = [];
  function visit(n, write) {
    if (n.k === 'cmp') {
      const left = definition(n.left, reg),
        right = definition(n.right, reg);
      const type = (left || right)?.result;
      if (type?.startsWith('Cat:')) {
        const en = ENUMS[type.slice(4)];
        fields.push({ name: 'Comparison', value: n.op, choices: ['=', '!='], put: (v) => (n.op = v) });
        if (!left || !right) {
          const key = left ? 'right' : 'left';
          fields.push({
            name: en.title,
            value: printExpr(n[key]),
            values: en.values,
            doc: 'One value, or compare choices such as {' + en.values.slice(0, 2).join(' | ') + '}.',
            put: (v) => (n[key] = expr(v)),
          });
        }
      }
      visit(n.left, (x) => (n.left = x));
      visit(n.right, (x) => (n.right = x));
      return;
    }
    if (n.k === 'and' || n.k === 'or') {
      n.items.forEach((x, i) => visit(x, (v) => (n.items[i] = v)));
      return;
    }
    if (n.k === 'not') {
      visit(n.item, (x) => (n.item = x));
      return;
    }
    const def = definition(n, reg);
    if (!def || !def.params.length) return;
    const named = reg.getNamed(n.value ?? n.name);
    let call = n.k === 'call' ? n : expr(def.name + '()');
    if (call !== n && named?.args) {
      call.args = Object.entries(named.args).map(([name, value]) => ({ name, value: expr(value) }));
    }
    for (const p of def.params) {
      const arg = argFor(call, def, p.name);
      if (p.type === 'State' && arg?.value.k === 'call') visit(arg.value, (v) => (arg.value = v));
      fields.push({
        name: p.name,
        param: p,
        def,
        value: arg ? printExpr(arg.value) : p.default || '',
        doc: p.doc,
        put: (v) => {
          if (!v && !p.required) {
            call.args = call.args.filter((a) => a !== arg);
            write(call);
            return;
          }
          if (arg) arg.value = expr(v);
          else call.args.push({ name: p.name, value: expr(v) });
          write(call);
        },
      });
    }
  }
  visit(root, (x) => Object.assign(root, x));
  return fields;
}

function candleSample(rec, end, bars) {
  if (!bars || !Number.isInteger(end)) return null;
  const first = end - bars + 1;
  const indices = Array.from({ length: bars }, (_, i) => first + i);
  if (!indices.every((i) => rec.has(i))) return null;
  const high = Math.max(...indices.map((i) => rec.H[i])),
    low = Math.min(...indices.map((i) => rec.L[i]));
  const name =
    'Recorded ' +
    (bars === 1 ? 'candle' : bars + '-candle pattern') +
    ' ending ' +
    isoUTC(rec.closeTime(end));
  const canvas = h('canvas', {
    class: 'candle-sample',
    width: 88,
    height: 72,
    role: 'img',
    'aria-label': name,
    title: name,
  });
  const ctx = canvas.getContext('2d');
  const y = (p) => (high === low ? 36 : 7 + ((high - p) * 58) / (high - low));
  indices.forEach((i, k) => {
    const x = 44 + (k - (bars - 1) / 2) * 27;
    ctx.strokeStyle = ctx.fillStyle = rec.C[i] >= rec.O[i] ? '#28664b' : '#a04c3e';
    ctx.lineWidth = 2.5;
    ctx.beginPath();
    ctx.moveTo(x, y(rec.H[i]));
    ctx.lineTo(x, y(rec.L[i]));
    ctx.stroke();
    ctx.fillRect(
      x - 7,
      Math.min(y(rec.O[i]), y(rec.C[i])),
      14,
      Math.max(2, Math.abs(y(rec.O[i]) - y(rec.C[i]))),
    );
  });
  return canvas;
}

export function setupBuilder(host, { state, edit, openDialog, closeDialog, getComposerURL }) {
  const env = state.env.env,
    reg = env.registry;
  const dialog = document.getElementById('dialog');
  let opener = null;
  function show(trigger, ...nodes) {
    opener = trigger;
    dialog.classList.add('builder-dialog');
    openDialog(...nodes);
  }
  dialog.addEventListener('close', () => {
    if (!dialog.classList.contains('builder-dialog')) return;
    dialog.classList.remove('builder-dialog');
    const target = opener?.isConnected
      ? opener
      : [...host.querySelectorAll('[data-focus]')].find((b) => b.dataset.focus === opener?.dataset.focus);
    target?.focus({ preventScroll: true });
  });
  function chooser(slot, i, trigger, { fresh = false, join = null, inline = null } = {}) {
    const q = structuredClone(state.analysis.ast);
    if (fresh) {
      q.lets = [];
      q.wheres = [];
      q.group = null;
      q.measures = [];
    }
    const base = prefix(q, slot);
    const items = queryCompletions(base, base.length, env).items;
    const unique = new Map();
    const change = (candidate, n) => {
      if (join) {
        const existing = slot === 'find' ? candidate.find : candidate.wheres[i];
        n = { k: join, items: [existing, n] };
      }
      replaceSlot(candidate, slot, i, n);
    };
    function add(item, value = item.insert) {
      const parsed = parseExpression(value);
      if (parsed.error) return;
      const n = parsed.ast,
        d = definition(n, reg);
      const key = d?.patternId ? 'pattern:' + d.patternId : printExpr(n);
      if (unique.has(key)) return;
      const draft = structuredClone(q);
      change(draft, n);
      const analysis = analyze(printQuestion(prune(draft)), env);
      if (!analysis.ok) return;
      let count, first, sample;
      if (slot === 'find') {
        const vals = eventSeries(state.env.ctx, analysis.candidates[0].plan.find).vals;
        count = 0;
        function observe(i) {
          if (vals[i] !== 1) return;
          count++;
          first ??= i;
        }
        if (fresh) {
          for (let i = 0; i < vals.length; i++) observe(i);
        } else for (const row of state.run.results[0].populations.eligible.rows) observe(row.i);
        // A union's first match can belong to its other branch.
        if (!join) sample = candleSample(state.env.rec, first, d?.patternBars);
      }
      const name = label(n, reg);
      const aliases = [...new Set([...(item.aliases || []), ...(d?.aliases || []), d?.ja].filter(Boolean))];
      const detail = [
        d?.ja,
        d?.patternBars ? d.patternBars + (d.patternBars === 1 ? ' candle' : ' candles') : '',
        d?.patternId ? d.summary : printExpr(n),
      ]
        .filter(Boolean)
        .join(' · ');
      unique.set(key, {
        label: name,
        detail,
        count,
        sample,
        search: norm([name, item.label, item.detail, value, ...aliases].join(' ')),
        value,
      });
    }
    items.forEach((item) => add(item));
    // A second outcome must use a different horizon. Offer the first available valid ones.
    if (slot === 'measure' && !unique.size) {
      for (const f of reg
        .implemented()
        .filter((f) => f.kind === 'outcome' && f.params.some((p) => p.name === 'after'))) {
        for (const t of ['15m', '30m', '1h', '2h', '4h', '8h', '12h', '1d', '2d', '7d']) {
          const insert = f.name + '(after: ' + t + ')';
          add({ insert, label: f.title, detail: t });
        }
      }
    }
    const all = [...unique.values()];
    const search =
      inline?.search ||
      h('input', {
        class: 'picker-search',
        type: 'text',
        role: 'combobox',
        'aria-label': 'Search ' + kind[slot] + ' choices',
        placeholder:
          slot === 'find'
            ? 'Search patterns in English or Japanese…'
            : 'Search available ' + kind[slot] + ' choices…',
        autocomplete: 'off',
        spellcheck: 'false',
      });
    const feedback = h('p', { class: 'picker-error', role: 'alert' });
    const count = h('small', { class: 'picker-count', role: 'status' });
    const leave = () => {
      if (inline) {
        menu.destroy();
        search.removeEventListener('input', filter);
        mount(inline.panel);
        inline.done();
      } else closeDialog();
    };
    const menu = optionList(search, {
      label: kind[slot] + ' choices',
      dismiss: leave,
      onPick: (entry) => {
        try {
          const next = structuredClone(q);
          change(next, expr(entry.value));
          applyValid(next, env, (text) => edit(text, { startFresh: fresh }));
          leave();
          if (inline) host.querySelector('.clause-pick')?.focus({ preventScroll: true });
        } catch (e) {
          feedback.textContent = e.message;
        }
      },
    });
    function filter() {
      const words = norm(search.value.trim()).split(/\s+/).filter(Boolean);
      const rows = all.filter((x) => words.every((word) => x.search.includes(word)));
      if (words.length)
        rows.sort(
          (a, b) => Number(norm(b.label).startsWith(words[0])) - Number(norm(a.label).startsWith(words[0])),
        );
      count.textContent =
        rows.length +
        (rows.length === 1 ? ' choice' : ' choices') +
        (slot === 'find'
          ? ' · matches ' +
            (fresh || !q.wheres.length ? 'on this recording' : 'with your filters') +
            (!fresh && state.run.results.length > 1 ? ' · first parameter combination' : '')
          : '');
      menu.show(rows);
    }
    search.addEventListener('input', filter);
    const headline = fresh
      ? 'Start a new question'
      : join === 'or'
        ? 'Match either ' + kind[slot]
        : join === 'and'
          ? 'Require both patterns'
          : 'Choose a ' + kind[slot];
    if (inline) mount(inline.panel, count, menu.list, feedback);
    else show(trigger, h('h2', null, headline), search, count, menu.list, feedback);
    filter();
    if (!inline) search.focus();
    return leave;
  }
  function tweak(node, trigger, binding = false) {
    // Locate the same AST node in the clone using its source location.
    function locate(item) {
      if (!item || typeof item !== 'object') return null;
      if (item.k === node.k && item.start === node.start && item.end === node.end) return item;
      for (const value of Object.values(item)) {
        const hit = locate(value);
        if (hit) return hit;
      }
      return null;
    }
    const q = state.analysis.ast;
    function fieldsFor(draft) {
      const copy = locate(draft);
      return binding
        ? [
            {
              name: copy.name,
              value: printExpr(copy.value),
              doc: 'A scalar value or a set of choices shared by every reference.',
              put: (v) => (copy.value = expr(v)),
            },
          ]
        : parameters(copy, reg);
    }
    const fields = fieldsFor(structuredClone(q));
    const feedback = h('p', { class: 'picker-error', role: 'alert' });
    const inputs = fields.map((field) => {
      const id = nextId('arg');
      if (['Price','Level'].includes(field.param?.type)) {
        return { field, ...priceControl(id, field) };
      }
      const valueLabels = ENUMS[field.param?.type?.slice(4)]?.labels;
      const choices = field.choices || (valueLabels && Object.hasOwn(valueLabels, field.value) ? Object.keys(valueLabels) : null);
      const input = choices
        ? h(
            'select',
            { id },
            choices.map((value) => h('option', { value, selected: value === field.value }, valueLabels?.[value] || value)),
          )
        : h('input', {
            id,
            class: 'arg-input',
            value: field.value,
            spellcheck: 'false',
            autocomplete: 'off',
          });
      const fieldLabel = field.param?.caption || field.name.replaceAll('_', ' ');
      let suggestions = field.values || [];
      if (field.param) {
        const base =
          prefix(
            q,
            field.def.kind === 'outcome' ? 'measure' : field.def.kind === 'event' ? 'find' : 'where',
          ) +
          field.def.name +
          '(' +
          field.name +
          ': ';
        suggestions = queryCompletions(base + ')', base.length, env).items.map((x) => x.insert);
      }
      const samples = [...new Set(suggestions.filter(Boolean))];
      let share = null;
      if (!binding && ['Duration', 'Ratio'].includes(field.param?.type) && !field.param.list) {
        share = h('input', {
          class: 'binding-name',
          placeholder: 'e.g. lookback',
          'aria-label': 'Parameter name for ' + fieldLabel,
          autocomplete: 'off',
        });
      }
      const list = h(
        'div',
        { class: 'param-picks' },
        samples.map((v) =>
          action(v, () => {
            input.value = v;
            input.dispatchEvent(new Event('input'));
            input.focus();
          }),
        ),
      );
      return {
        field,
        input,
        share,
        focus: () => input.focus(),
        el: h(
          'div',
          { class: 'param-field' },
          h('label', { for: id }, fieldLabel),
          input,
          field.doc && h('small', null, field.doc),
          samples.length && !choices ? h('details', null, h('summary', null, 'Choose a value'), list) : null,
          share && h('details', null, h('summary', null, 'Share as a named parameter'), share),
        ),
      };
    });
    const apply = () => {
      // Rebuild the draft on each submit so a failed attempt cannot accumulate changes.
      const draft = structuredClone(q);
      const edits = fieldsFor(draft);
      try {
        for (const [index, { input, share }] of inputs.entries()) {
          const field = edits[index];
          if (share?.value.trim()) {
            const name = share.value.trim();
            if (!/^[A-Za-z_][A-Za-z_0-9]*$/.test(name) || draft.lets.some((b) => b.name === name))
              throw Error('Choose a new parameter name made of letters, digits and underscores.');
            draft.lets.push({ name, value: expr(input.value) });
            field.put(name);
          } else if (input.value !== field.value) field.put(input.value.trim());
        }
        applyValid(draft, env, edit);
        closeDialog();
      } catch (e) {
        feedback.textContent = e.message;
      }
    };
    const form = h(
      'form',
      {
        class: 'param-form',
        onsubmit: (e) => {
          e.preventDefault();
          apply();
        },
      },
      inputs.map((x) => x.el),
      feedback,
      h('button', { class: 'primary', type: 'submit' }, 'Apply changes'),
    );
    show(trigger, h('h2', null, binding ? 'Edit ' + node.name : 'Adjust ' + label(node, reg)), form);
    inputs[0]?.focus();
  }
  function render() {
    const q = state.analysis.ast;
    const commit = (fn) => {
      const next = structuredClone(q);
      fn(next);
      applyValid(next, env, edit);
    };
    function row(slot, n, i) {
      const title = label(n, reg);
      const def = definition(n, reg);
      const set = (text, change, cls = '', id = text) => {
        const b = action(text, () => change(b), { class: cls, 'data-focus': [slot, i, id].join('-') });
        return b;
      };
      const parts = [set(title, (b) => chooser(slot, i, b), 'clause-pick', 'choose')];
      if (slot === 'find' && def?.patternBars) {
        const first = state.run.results[state.candidate].matches[0]?.i;
        const sample = candleSample(state.env.rec, first, def.patternBars);
        if (sample) parts[0].prepend(sample);
      }
      const adjustable = parameters(structuredClone(n), reg).length;
      if (adjustable) parts.push(set('Adjust', (b) => tweak(n, b), 'text-btn'));
      if (slot !== 'find') parts.push(set('×', () => commit((a) => replaceSlot(a, slot, i, null)), 'remove'));
      if (slot !== 'find') parts.at(-1).setAttribute('aria-label', 'Remove ' + kind[slot] + ' ' + title);
      parts[0].setAttribute('aria-label', 'Change ' + kind[slot] + ' ' + title);
      const fine = def?.patternId
        ? [def.ja, def.patternBars + (def.patternBars === 1 ? ' candle' : ' candles')]
            .filter(Boolean)
            .join(' · ')
        : nodeLabel(n, reg).replaceAll('nyse_regular', 'NYSE regular');
      const controls =
        slot === 'find'
          ? h(
              'div',
              { class: 'logic-tools' },
              set('Either pattern…', (b) => chooser('find', null, b, { join: 'or' }), 'text-btn'),
              set('Both patterns…', (b) => chooser('find', null, b, { join: 'and' }), 'text-btn'),
            )
          : slot === 'where' &&
            h(
              'div',
              { class: 'logic-tools' },
              set('Or…', (b) => chooser('where', i, b, { join: 'or' }), 'text-btn'),
              set(
                n.k === 'not' ? 'Undo NOT' : 'Negate',
                () =>
                  commit((a) => {
                    const x = a.wheres[i];
                    a.wheres[i] = x.k === 'not' ? x.item : { k: 'not', item: x };
                  }),
                'text-btn',
              ),
            );
      const branches =
        (slot === 'where' || slot === 'find') && n.items && ['and', 'or'].includes(n.k)
          ? h(
              'div',
              { class: 'branch-picks' },
              n.items.map((item, index) => {
                const name = label(item, reg);
                return action(
                  name + ' ×',
                  () =>
                    commit((a) => {
                      const node = slot === 'find' ? a.find : a.wheres[i];
                      node.items.splice(index, 1);
                      replaceSlot(a, slot, i, node.items.length === 1 ? node.items[0] : node);
                    }),
                  { 'aria-label': 'Remove ' + name + ' from ' + kind[slot] },
                );
              }),
            )
          : null;
      return h(
        'div',
        { class: 'clause-row' },
        h('div', { class: 'clause-actions' }, parts),
        h('small', { class: 'clause-code' }, fine),
        branches,
        controls,
      );
    }
    const add = (name, slot) => {
      const b = action('+ ' + name, () => chooser(slot, null, b), {
        class: 'add-clause',
        'data-focus': 'add-' + slot,
      });
      return b;
    };
    const section = (name, rows, extra) =>
      h(
        'div',
        { class: 'clause-section' },
        h('div', { class: 'clause-head' }, h('span', null, name), extra),
        rows,
      );
    const pattern = definition(q.find, reg);
    const search = h('input', {
      class: 'picker-search inline-search',
      role: 'combobox',
      'aria-label': 'Find a pattern',
      'aria-expanded': 'false',
      placeholder: 'Search patterns in English or Japanese…',
      autocomplete: 'off',
      spellcheck: 'false',
    });
    const panel = h('div', { class: 'inline-options' });
    let dismiss = null;
    const open = () => {
      if (!dismiss)
        dismiss = chooser('find', null, search, {
          inline: {
            search,
            panel,
            done: () => {
              dismiss = null;
              search.value = '';
              search.setAttribute('aria-expanded', 'false');
            },
          },
        });
    };
    search.addEventListener('focus', open);
    search.addEventListener('input', open);
    search.addEventListener('click', open);
    search.addEventListener('blur', () => dismiss?.());
    const bindings = q.lets.map((binding) => {
      const b = action(binding.name + ' = ' + printExpr(binding.value), () => tweak(binding, b, true), {
        class: 'binding-chip',
        'data-focus': binding.name,
      });
      return b;
    });
    mount(
      host,
      h(
        'div',
        { class: 'builder-market' },
        h('span', { class: 'market-dot', 'aria-hidden': 'true' }),
        h('strong', null, q.on.instrument.name),
        h('span', null, q.on.bar.text + ' · Binance spot'),
      ),
      section(
        'Find',
        row('find', q.find, null),
        h(
          'a',
          { href: getComposerURL(), class: 'text-btn' },
          pattern?.patternId ? 'Explore in Composer ↗' : 'Draw in Composer ↗',
        ),
      ),
      pattern?.patternId && h('p', { class: 'pattern-description' }, pattern.summary),
      search,
      panel,
      section(
        'Filter',
        q.wheres.map((n, i) => row('where', n, i)),
        add('Filter', 'where'),
      ),
      section('Group by', q.group && row('group', q.group, null), !q.group && add('Grouping', 'group')),
      section(
        'Measure',
        q.measures.map((n, i) => row('measure', n, i)),
        add('Outcome', 'measure'),
      ),
      bindings.length ? section('Shared parameters', h('div', { class: 'bindings' }, bindings)) : null,
    );
  }
  return { render, newQuestion: (trigger) => chooser('find', null, trigger, { fresh: true }) };
}
