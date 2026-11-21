import { h, mount } from './ui/dom.js';
import { printExpr, parseExpression, printQuestion } from './lang.js';

const expression = (s) => {
  const parsed = parseExpression(s);
  if (parsed.error) throw Error(parsed.error.message);
  return parsed.ast;
};
const field = (title, ...content) =>
  h('div', { class: 'field' }, h('span', { class: 'field-label' }, title), ...content);
const line = (...children) => h('div', { class: 'control-line' }, ...children);
const hint = (s) => h('p', null, s);
const arg = (node, key) => node?.args?.find((a) => a.name === key)?.value;
function select(label, options, current, onchange) {
  const all = options.some(([v]) => v === current) ? options : [...options, [current, current]];
  return h(
    'select',
    { 'aria-label': label, onchange: (e) => onchange(e.target.value) },
    all.map(([v, s]) => h('option', { value: v, selected: v === current }, s)),
  );
}
function replaceArg(call, key, value) {
  const node = expression(value);
  const a = call.args.find((v) => v.name === key);
  if (a) a.value = node;
  else call.args.push({ name: key, value: node });
}
const horizons = [
  ['', 'Occurrences only'],
  ['after: 1h', 'Return after 1 hour'],
  ['after: 4h', 'Return after 4 hours'],
  ['after: [1h, 4h]', 'Returns after 1h and 4h'],
];
export const DEFAULT_SOURCE = Date.parse('2025-03-28T19:30:00Z');
export const FRIDAY =
  'on BTCUSDT 15m\nfind "Wick rejection"\nwhere quiet_friday_close(last: 1h)\nmeasure close_return(after: [1h, 4h])';

export function drawSource(canvas, rec, t) {
  const slot = rec.slotClosingAt(t);
  if (!rec.has(slot)) return;
  const o = rec.O[slot],
    c = rec.C[slot],
    high = rec.H[slot],
    low = rec.L[slot];
  const ctx = canvas.getContext('2d'),
    x = canvas.width / 2;
  const y = (p) => 6 + ((high - p) / (high - low || 1)) * (canvas.height - 12);
  ctx.strokeStyle = ctx.fillStyle = c >= o ? '#356c4b' : '#a55345';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(x, y(high));
  ctx.lineTo(x, y(low));
  ctx.stroke();
  ctx.fillRect(x - 7, Math.min(y(c), y(o)), 14, Math.max(2, Math.abs(y(c) - y(o))));
}

export function renderControls(el, { analysis, env, candidate, source, composerLink, edit }) {
  const ast = analysis.ast;
  function update(action) {
    const next = structuredClone(ast);
    action(next);
    edit(printQuestion(next));
  }
  const resolved = analysis.candidates[candidate].plan;
  const sourceInfo = source.anchor ? env.cal.describe(source.anchor) : 'Composer drawing';
  const canvas = h('canvas', { width: 54, height: 68, 'aria-hidden': 'true' });
  const market = field(
    'Market',
    line(h('strong', null, 'BTCUSDT'), h('span', { class: 'small' }, 'Binance spot · 15m')),
  );
  const find = ast.find;
  const isBreak = find.k === 'call' && find.name === 'channel_breakout';
  const exact = find.k === 'call' && find.name === 'exact_g1';
  const wick =
    (find.k === 'str' && find.value === 'Wick rejection') ||
    (find.k === 'call' && find.name === 'wick_rejection');
  let finder;
  if (wick || exact) {
    const defaultWick = find.k === 'call' && wick ? printExpr(find) : '"Wick rejection"';
    finder = field(
      'Find',
      h(
        'div',
        { class: 'source' },
        source.anchor ? h('span', { class: 'glyph' }, canvas) : null,
        h(
          'div',
          null,
          h('strong', null, source.anchor ? 'Selected candle' : 'Selected drawing'),
          hint(sourceInfo),
        ),
      ),
      line(
        select(
          'Match rule',
          [
            ['exact', 'Exact G1 twins'],
            ['wick', 'Wick rejection'],
          ],
          exact ? 'exact' : 'wick',
          (v) =>
            update(
              (q) =>
                (q.find = expression(v === 'exact' ? `exact_g1(${JSON.stringify(source.g1)})` : defaultWick)),
            ),
        ),
      ),
      hint(
        exact
          ? 'Matches the endpoint order, ties and chosen orientation.'
          : `Body ≤ ${resolved.find.args.body_max.text} and lower wick ≥ ${resolved.find.args.wick_min.text} of the candle range.`,
      ),
      h('a', { href: composerLink, class: 'composer-action' }, 'Open in Composer ↗'),
    );
  } else if (isBreak) {
    let v = arg(find, 'over');
    const binding = v?.k === 'id' && ast.lets.find((b) => b.name === v.name);
    if (binding) v = binding.value;
    finder = field(
      'Find',
      h('strong', null, 'Channel breakout'),
      line(
        select(
          'Prior high lookback',
          [
            ['12h', 'Prior 12h high'],
            ['18h', 'Prior 18h high'],
            ['24h', 'Prior 24h high'],
            ['{12h | 24h}', 'Compare 12h and 24h'],
          ],
          printExpr(v),
          (s) =>
            update((q) => {
              if (binding) q.lets.find((b) => b.name === binding.name).value = expression(s);
              else replaceArg(q.find, 'over', s);
            }),
        ),
      ),
      hint('The trigger closes above the preceding channel.'),
    );
  } else finder = field('Find', h('code', { class: 'wrap' }, printExpr(find)));
  let when;
  const context = ast.wheres[0];
  if (
    ast.wheres.length === 1 &&
    context.k === 'call' &&
    ['quiet_friday_close', 'quiet_friday_close_v2'].includes(context.name)
  ) {
    const v2 = context.name.endsWith('_v2');
    const tail = arg(context, 'last');
    when = field(
      'When',
      h('strong', null, 'Quiet Friday close'),
      line(
        select(
          'Range definition',
          [
            ['v1', 'Rolling quiet · v1'],
            ['v2', 'Whole-range containment · v2'],
          ],
          v2 ? 'v2' : 'v1',
          (s) =>
            update((q) => {
              const prev = q.wheres[0];
              const last = arg(prev, 'last');
              const width = arg(prev, 'width_max');
              const dur = arg(prev, 'quiet_for') || arg(prev, 'over');
              const name = s === 'v2' ? 'quiet_friday_close_v2' : 'quiet_friday_close';
              q.wheres[0] = expression(
                name +
                  '(' +
                  [
                    last && 'last: ' + printExpr(last),
                    dur && 'quiet_for: ' + printExpr(dur),
                    width && 'width_max: ' + printExpr(width),
                  ]
                    .filter(Boolean)
                    .join(', ') +
                  ')',
              );
            }),
        ),
      ),
      line(
        select(
          'Session window',
          [
            ['30m', 'Final 30 minutes'],
            ['1h', 'Final hour'],
            ['{30m | 1h}', 'Compare 30m and 1h'],
          ],
          tail ? printExpr(tail) : '1h',
          (s) => update((q) => replaceArg(q.wheres[0], 'last', s)),
        ),
      ),
      hint(
        v2
          ? `One ${resolved.wheres[0].args.quiet_for.text} envelope, at most ${resolved.wheres[0].args.width_max.text} of the latest close.`
          : `Every rolling 4h range stays within ${resolved.wheres[0].args.width_max.text} for ${resolved.wheres[0].args.quiet_for.text}.`,
      ),
      h(
        'details',
        { class: 'tune' },
        h('summary', null, 'Adjust range'),
        line(
          select(
            'Maximum range width',
            [
              ['2%', '2% width'],
              ['2.5%', '2.5% width'],
              ['3%', '3% width'],
              ['6%', '6% width'],
              ['{2% | 2.5% | 3%}', 'Compare widths'],
            ],
            arg(context, 'width_max') ? printExpr(arg(context, 'width_max')) : '2.5%',
            (s) => update((q) => replaceArg(q.wheres[0], 'width_max', s)),
          ),
          select(
            'Range duration',
            [
              ['24h', '24 hours'],
              ['48h', '48 hours'],
              ['72h', '72 hours'],
            ],
            arg(context, 'quiet_for') ? printExpr(arg(context, 'quiet_for')) : '48h',
            (s) => update((q) => replaceArg(q.wheres[0], 'quiet_for', s)),
          ),
        ),
      ),
    );
  } else if (
    isBreak &&
    (ast.group?.name === 'completed_trend' ||
      (context?.k === 'cmp' && context.left?.name === 'completed_trend'))
  ) {
    const grouped = !!ast.group;
    const condition = grouped ? printExpr(ast.group) : printExpr(context.left);
    const current = grouped ? 'group' : context.right?.name;
    when = field(
      'When',
      select(
        '4h bar direction',
        [
          ['group', 'Group by 4h bar direction'],
          ['up', 'Keep up bars'],
          ['down', 'Keep down bars'],
          ['flat', 'Keep flat bars'],
        ],
        current,
        (s) =>
          update((q) => {
            if (q.group) {
              q.group = null;
              if (s !== 'group') q.wheres.push(expression(condition + ' = ' + s));
            } else if (s === 'group') {
              q.wheres.shift();
              q.group = expression(condition);
            } else q.wheres[0] = expression(condition + ' = ' + s);
          }),
      ),
      hint('Uses the latest completed four-hour bar.'),
    );
  } else
    when = field(
      'When',
      hint(
        [...ast.wheres.map(printable), ...(ast.group ? ['Group by ' + printExpr(ast.group)] : [])].join(
          ' · ',
        ) || 'Every recorded bar',
      ),
    );
  const simple =
    ast.measures.length === 0 || (ast.measures.length === 1 && ast.measures[0].name === 'close_return');
  const show = simple
    ? field(
        'Show',
        select(
          'Show outcomes',
          horizons,
          ast.measures.length
            ? 'after: ' + printExpr(arg(ast.measures[0], 'after') || ast.measures[0].args[0].value)
            : '',
          (v) => update((q) => (q.measures = v ? [expression('close_return(' + v + ')')] : [])),
        ),
      )
    : field('Show', hint(ast.measures.map(printable).join(', ')));
  mount(el, market, finder, when, show);
  if (canvas.isConnected) drawSource(canvas, env.rec, source.anchor);
}
const printable = (n) => printExpr(n);
