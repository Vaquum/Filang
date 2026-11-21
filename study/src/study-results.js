import { h, mount, fmtInt } from './ui/dom.js';
import { isoUTC } from './data.js';
import { pctText } from './num.js';
import { compareResults, describeChange } from './diff.js';
import { drawCandles } from './ui/chart.js';

const names = {
  matching: 'Matches',
  eligible: 'All eligible',
  nonmatching: 'Without pattern',
  unknownDetector: 'Pattern unknown',
};
const size = 8;
const sign = (v) => (v === 1 ? 'True' : v === 0 ? 'False' : 'Unknown');
const nySession = (plan) =>
  plan.wheres.some((w) => w.identity?.includes('nyse_regular') || w.text?.includes('quiet_friday_close'));
const list = document.getElementById.bind(document);

export function renderEvidence(s, onCandidate) {
  const r = s.run.results[s.candidate],
    p = r.populations;
  mount(
    list('candidates'),
    s.run.results.length > 1
      ? h(
          'div',
          { class: 'candidate-tabs' },
          s.run.results.map((c, i) =>
            h(
              'button',
              { type: 'button', 'aria-pressed': String(i === s.candidate), onclick: () => onCandidate(i) },
              c.cand.label,
            ),
          ),
        )
      : null,
  );
  const n = p.matching.count,
    e = p.eligible.count;
  mount(
    list('cohort-summary'),
    h(
      'div',
      { class: 'cohort' },
      h('span', { class: 'number' }, fmtInt(n)),
      h(
        'span',
        { class: 'statement' },
        `matching ${n === 1 ? 'close' : 'closes'} out of `,
        h('strong', null, fmtInt(e) + ' eligible'),
        nySession(r.cand.plan)
          ? ` across ${p.eligible.sessionCount} New York session dates`
          : ' recorded closes',
      ),
    ),
  );
  const d = s.basis && s.basis !== r ? compareResults(s.basis, r) : null;
  const bucket = (title, items) =>
    items.length
      ? h(
          'div',
          null,
          h('strong', null, title),
          h(
            'ul',
            null,
            items
              .slice(0, 12)
              .map((x) =>
                h(
                  'li',
                  null,
                  isoUTC(x.row.t),
                  ' · ',
                  x.reasons.map((v) => (v.other ? v.text + ' → ' + v.other.text : v.text)).join(' / ') ||
                    'Match membership changed.',
                ),
              ),
          ),
          items.length > 12 ? h('span', null, `Showing 12 of ${items.length} changes`) : null,
        )
      : null;
  mount(
    list('changes'),
    d
      ? h(
          'details',
          { class: 'change-strip' },
          h(
            'summary',
            null,
            `${fmtInt(d.added.length)} added · ${fmtInt(d.removed.length)} removed · ${fmtInt(d.kept.length)} retained`,
          ),
          h('p', null, `Compared by ${d.mode}. `, d.changes.map(describeChange).join(' · ')),
          bucket('Entered', d.added),
          bucket('Left', d.removed),
        )
      : null,
  );
  const draw = () => renderEvidence(s, onCandidate);
  mount(
    list('population-nav'),
    h(
      'div',
      { class: 'pop-tabs', 'aria-label': 'Case population' },
      Object.keys(names)
        .filter((k) => k !== 'unknownDetector' || p[k].count)
        .map((k) =>
          h(
            'button',
            {
              type: 'button',
              'aria-pressed': String(s.population === k),
              onclick: () => {
                s.population = k;
                s.page = 0;
                s.bucket = null;
                s.inspect = null;
                draw();
              },
            },
            `${names[k]} · ${fmtInt(p[k].count)}`,
          ),
        ),
    ),
  );
  const group = r.groups?.find((g) => g.key === s.bucket);
  const showGroups = r.groups && s.population === 'matching';
  mount(
    list('group-results'),
    showGroups
      ? h(
          'div',
          { class: 'group-tabs' },
          h('span', { class: 'small' }, '4h direction' === r.group.label ? '4h direction' : r.group.label),
          r.groups.map((g) =>
            h(
              'button',
              {
                type: 'button',
                'aria-pressed': String(s.bucket === g.key),
                onclick: () => {
                  s.bucket = s.bucket === g.key ? null : g.key;
                  s.page = 0;
                  s.inspect = null;
                  draw();
                },
              },
              g.key + ' · ' + g.count,
            ),
          ),
        )
      : null,
  );
  const pop = p[s.population],
    rows = showGroups && group ? group.rows : pop.rows,
    summary = showGroups && group ? group.summary : pop.summary;
  const pages = Math.max(1, Math.ceil(rows.length / size));
  s.page = Math.min(Math.max(0, s.page), pages - 1);
  const slice = rows.slice(s.page * size, (s.page + 1) * size);
  let row = rows.find((x) => x.t === s.inspect);
  if (!row && slice.length) {
    row = slice[0];
    s.inspect = row.t;
  }
  const header = h(
    'tr',
    null,
    h('th', { scope: 'col' }, 'Close · UTC'),
    h('th', { scope: 'col' }, 'Close · New York'),
    h('th', { scope: 'col' }, 'Close · USDT'),
    r.columns.map((c) => h('th', { scope: 'col' }, c.text + ' return')),
  );
  mount(
    list('case-table'),
    rows.length
      ? h(
          'table',
          { 'aria-label': names[s.population] },
          h('thead', null, header),
          h(
            'tbody',
            null,
            slice.map((x) => {
              const day = s.env.cal.dayAt(x.t);
              return h(
                'tr',
                { class: x.t === row?.t ? 'selected' : '' },
                h(
                  'td',
                  null,
                  h(
                    'button',
                    {
                      type: 'button',
                      'aria-pressed': String(x.t === row?.t),
                      onclick: () => {
                        s.inspect = x.t;
                        draw();
                      },
                    },
                    isoUTC(x.t),
                  ),
                ),
                h('td', null, day.kind === 'session' ? s.env.cal.localHM(x.t, day.s) : s.env.cal.describe(x.t)),
                h('td', null, s.env.rec.price(s.env.rec.C[x.i])),
                x.out.map((o) =>
                  h(
                    'td',
                    { class: o.status === 'observed' ? (o.value >= 0 ? 'pos' : 'neg') : '', title: o.why },
                    o.status === 'observed' ? pctText(o.value) : o.status,
                  ),
                ),
              );
            }),
          ),
        )
      : h(
          'p',
          { class: 'empty' },
          s.population === 'matching'
            ? 'No recorded closes match this question. Inspect all eligible closes to see why.'
            : 'No recorded closes in this population.',
        ),
  );
  mount(
    list('pager'),
    pages > 1
      ? [
          h(
            'button',
            {
              type: 'button',
              disabled: s.page === 0,
              onclick: () => {
                s.page--;
                s.inspect = null;
                draw();
              },
            },
            'Previous',
          ),
          h('span', null, `${s.page + 1} / ${pages}`),
          h(
            'button',
            {
              type: 'button',
              disabled: s.page === pages - 1,
              onclick: () => {
                s.page++;
                s.inspect = null;
                draw();
              },
            },
            'Next',
          ),
        ]
      : null,
  );
  const reports = summary.map((v, k) =>
    v.observed < 30
      ? `${r.columns[k].text}: ${v.positive} positive of ${v.observed} observed`
      : `${r.columns[k].text}: ${Math.round((100 * v.positive) / v.observed)}% positive · median ${pctText(v.median)} · n=${fmtInt(v.observed)}`,
  );
  const missing = summary.flatMap((v, k) =>
    v.censored || v.unknown ? [`${r.columns[k].text}: ${v.censored} censored, ${v.unknown} unknown`] : [],
  );
  mount(
    list('population-notes'),
    [
      reports.join('  /  '),
      missing.join('  /  '),
      p.unknownContextCount ? `${fmtInt(p.unknownContextCount)} closes had unknown context.` : '',
    ]
      .filter(Boolean)
      .map((t) => h('div', null, t)),
  );
  renderInspection(s, r, row);
}

function reasons(items) {
  return items.map((x) =>
    h(
      'li',
      null,
      h('strong', null, sign(x.v) + ' · '),
      x.text || '',
      x.parts?.length ? h('ul', null, reasons(x.parts)) : h('span', null, ' — ' + x.why),
    ),
  );
}
export function renderInspection(s, r, row) {
  const rec = s.env.rec;
  const i = row?.i ?? (s.source.anchor ? rec.slotClosingAt(s.source.anchor) : null);
  const canvas = list('chart');
  if (i === null || !rec.has(i)) {
    canvas.hidden = true;
    mount(list('chart-heading'), 'Select a recorded close to inspect.');
    mount(list('bar-prices'));
    mount(list('why'));
    return;
  }
  canvas.hidden = false;
  const t = rec.closeTime(i);
  mount(
    list('chart-heading'),
    h(
      'div',
      { class: 'chart-line' },
      h('span', null, isoUTC(t) + ' · ' + s.env.cal.describe(t)),
      h(
        'span',
        { class: 'case-status' },
        row
          ? row.detector === 1
            ? 'Matched pattern'
            : row.detector === 0
              ? 'Outside pattern'
              : 'Pattern unknown'
          : 'Source close',
      ),
    ),
  );
  const trace = row ? r.event.series.evidence?.(i) : null;
  const breachSlot = trace ? rec.slotClosingAt(trace.breach) : i;
  const windows = [];
  const visit = (node) => {
    if (!node) return;
    if (node.name === 'session_tail') {
      const day = s.env.cal.dayAt(t);
      if (day.kind === 'session') {
        const end = rec.slotClosingAt(day.s.close);
        windows.push({
          from: end - Math.ceil(node.args.last.ms / rec.barMs) + 1,
          to: end,
          label: 'Session window',
          tone: 2,
        });
      }
    }
    if (node.body) visit(node.body);
    node.items?.forEach(visit);
    if (node.item) visit(node.item);
  };
  r.cand.plan.wheres.forEach(visit);
  if (trace) {
    list('chart-heading').append(h('p', {class:'reclaim-trace'},
      `Breach ${isoUTC(trace.breach)} · First reclaim ${isoUTC(trace.reclaim)} · Frozen level ${rec.price(trace.level)}`));
  }
  drawCandles(canvas, {
    rec, anchorSlot:i, from:Math.min(i - 22,breachSlot - 3), to:i + 14,
    overlays: {windows, levels: trace ? [{from:breachSlot,to:i,price:trace.level,label:'Frozen level'}] : [],
      times:trace && breachSlot !== i ? [{t:trace.breach,label:'Breach'}] : []},
  });
  canvas.setAttribute(
    'aria-label',
    'Recorded 15-minute candles around ' + isoUTC(t) + '. ' + r.event.series.why(i),
  );
  mount(
    list('bar-prices'),
    h(
      'div',
      { class: 'ohlc' },
      ['O', 'H', 'L', 'C'].map((k) => h('span', null, k + ' ' + rec.price(rec[k][i]))),
    ),
  );
  const tested = r.clauses.map((c) => ({ ...c.at(i), text: c.text }));
  const anyFalse = r.event.series.vals[i] === 0 || tested.some((c) => c.v === 0);
  const pass = r.event.series.vals[i] === 1 && tested.every((c) => c.v === 1);
  mount(
    list('why'),
    h(
      'details',
      null,
      h(
        'summary',
        null,
        pass
          ? 'Why this close matched'
          : anyFalse
            ? 'Why this close was excluded'
            : 'Why membership is unknown',
      ),
      h(
        'p',
        null,
        h('strong', null, sign(r.event.series.vals[i]) + ' · ' + r.event.label + ' '),
        r.event.series.why(i),
      ),
      h('ul', null, reasons(tested)),
    ),
  );
}
