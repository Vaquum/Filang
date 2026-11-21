// Opt-in practice. Results belong to this browser tab.
import { h } from './ui/dom.js';
import { analyze } from './check.js';
import { runCandidate } from './engine.js';

const KEY = 'limen.sfd.practice.1';
const HOUR = 3600000;
const ANCHOR = Date.parse('2025-03-28T19:30:00Z');
const TASK =
  'Build one BTCUSDT 15m study of closes above the prior 18-hour high. Include every qualifying close. Group by the direction of the latest completed four-hour bar and read close returns one and four hours later.';
const practiceQuery = 'on BTCUSDT 15m\nfind "Wick rejection"\nwhere quiet_friday_close(last: {30m | 1h})';

export function checkPrediction(env, change, reason) {
  const a = analyze(practiceQuery, env.env);
  if (!a.ok || a.candidates.length !== 2)
    throw Error('The pinned Friday practice question could not be evaluated.');
  const membership = a.candidates.map((c) => runCandidate(env.ctx, c).matches.some((r) => r.t === ANCHOR));
  const expected = membership[0] === membership[1] ? 'same' : membership[0] ? 'leaves' : 'enters';
  return { change: change === expected, reason: reason === 'edge' };
}
export function isTransferResult(run) {
  if (run?.results?.length !== 1) return false;
  const r = run.results[0],
    plan = r.cand.plan;
  return (
    plan.find.name === 'channel_breakout' &&
    plan.find.args.over.ms === 18 * HOUR &&
    plan.wheres.length === 0 &&
    plan.group?.name === 'completed_trend' &&
    plan.group.args.frame.ms === 4 * HOUR &&
    plan.columns.length === 2 &&
    plan.columns.every((c) => c.def === 'close_return') &&
    new Set(plan.columns.map((c) => c.h)).size === 2 &&
    plan.columns.every((c) => [HOUR, 4 * HOUR].includes(c.h)) &&
    r.groups?.reduce((n, g) => n + g.count, 0) === r.matches.length
  );
}
function select(label, options) {
  const input = h(
    'select',
    { 'aria-label': label },
    h('option', { value: '' }, 'Choose an answer'),
    options.map(([v, l]) => h('option', { value: v }, l)),
  );
  return { input, field: h('label', null, label, ' ', input) };
}
const action = (name, fn) => h('button', { type: 'button', onclick: fn }, name);
const row = (...items) => h('div', { class: 'btn-row' }, ...items);
const duration = (ms) => {
  const s = Math.max(0, Math.floor(ms / 1000));
  return Math.floor(s / 60) + 'm ' + (s % 60) + 's';
};

export function setupPractice(button, { state, openDialog, closeDialog, hasPendingEdits }) {
  let record = null,
    storage;
  try {
    storage = window.sessionStorage;
    const saved = JSON.parse(storage.getItem(KEY));
    if (
      saved?.version === 1 &&
      Number.isFinite(saved.started) &&
      ['predict', 'transfer', 'done'].includes(saved.stage)
    )
      record = saved;
  } catch {
    storage = null;
  }
  function persist() {
    if (storage) {
      try {
        storage.setItem(KEY, JSON.stringify(record));
      } catch {
        storage = null;
      }
    }
    button.textContent =
      record?.stage === 'done' ? 'Practice results' : record ? 'Resume practice' : 'Practice';
  }
  function start() {
    record = {
      version: 1,
      stage: 'predict',
      started: Date.now(),
      predictionFirst: null,
      transferFirst: null,
      usedExample: false,
    };
    persist();
    open();
  }
  function complete(at) {
    if (record.transferFirst === null) record.transferFirst = true;
    record.finished = at;
    record.stage = 'done';
    persist();
  }
  function onRun() {
    if (record?.stage === 'transfer' && isTransferResult(state.run)) complete(Date.now());
  }
  function prediction() {
    const change = select('The March 28 close', [
      ['same', 'Keeps its previous membership'],
      ['enters', 'Enters the matching cases'],
      ['leaves', 'Leaves the matching cases'],
    ]);
    const reason = select('Reason', [
      ['open', 'The opening time chooses the session window.'],
      ['edge', 'The close sits on the excluded start of the half-hour window.'],
      ['close', 'The close sits on the excluded end of the session.'],
    ]);
    if (record.change) change.input.value = record.change;
    if (record.reason) reason.input.value = record.reason;
    const update = () => {
      record.change = change.input.value;
      record.reason = reason.input.value;
      persist();
    };
    change.input.addEventListener('change', update);
    reason.input.addEventListener('change', update);
    const status = h('p', { role: 'status', class: 'small' });
    openDialog(
      h('h2', null, 'Predict a change'),
      h(
        'p',
        null,
        'On Friday, March 28, the selected wick closes at 15:30 New York time. All other conditions pass. The session closes at 16:00. What happens to this occurrence if you widen the final 30 minutes to one hour?',
      ),
      change.field,
      reason.field,
      status,
      row(
        action('Check prediction', () => {
          if (!change.input.value || !reason.input.value) {
            status.textContent = 'Choose both answers.';
            return;
          }
          const judged = checkPrediction(state.env, change.input.value, reason.input.value);
          if (record.predictionFirst === null) record.predictionFirst = { ...judged, at: Date.now() };
          if (judged.change && judged.reason) {
            record.stage = 'transfer';
            record.transferStarted = Date.now();
            persist();
            open();
          } else {
            persist();
            status.textContent = 'The two answers do not yet explain the recorded change. Try again.';
          }
        }),
        action('Resume later', closeDialog),
      ),
    );
  }
  function transfer() {
    const currentStatus = h('p', { role: 'status', class: 'small' });
    openDialog(
      h('h2', null, 'Build a different study'),
      h('p', null, TASK),
      h(
        'p',
        { class: 'small' },
        'Edit and run the study, then reopen Practice. Time runs until the first correct evaluation. Loading the breakout example is recorded as assistance.',
      ),
      currentStatus,
      row(
        action('Work on study', closeDialog),
        action('Check current study', () => {
          if (hasPendingEdits()) {
            currentStatus.textContent = 'Run the edited question before checking it.';
            return;
          }
          const correct = isTransferResult(state.run);
          if (record.transferFirst === null) record.transferFirst = correct;
          if (correct) {
            complete(Date.now());
            open();
          } else {
            persist();
            currentStatus.textContent =
              'The evaluated study does not yet answer the transfer question. Continue editing.';
          }
        }),
      ),
    );
  }
  function results() {
    const p = record.predictionFirst,
      score = Number(p.change) + Number(p.reason);
    openDialog(
      h('h2', null, 'Practice results'),
      h(
        'p',
        null,
        'March 28 entered when the window widened. The 15:30 close is exactly the excluded start of the 30-minute window.',
      ),
      h(
        'ul',
        null,
        h('li', null, 'Prediction and explanation on first submission · ' + score + ' / 2'),
        h(
          'li',
          null,
          'Transfer on first submitted check · ' +
            (record.transferFirst ? 'correct' : 'correct after another attempt'),
        ),
        h(
          'li',
          null,
          'Transfer time to first correct evaluation · ' + duration(record.finished - record.transferStarted),
        ),
        h('li', null, 'Total elapsed time · ' + duration(record.finished - record.started)),
        h(
          'li',
          null,
          record.usedExample
            ? 'The breakout example was loaded during transfer.'
            : 'No breakout example was loaded during transfer.',
        ),
      ),
      row(action('Done', closeDialog), action('Start again', start)),
    );
  }
  function open() {
    if (!record) {
      openDialog(
        h('h2', null, 'Practice'),
        h(
          'p',
          null,
          'Predict one change to the Friday study, explain it, then build a different study. The timer starts when you begin. First answers and later corrections are kept in this tab.',
        ),
        row(action('Start practice', start)),
      );
      return;
    }
    if (record.stage === 'predict') prediction();
    else if (record.stage === 'transfer') transfer();
    else results();
  }
  document.getElementById('examples')?.addEventListener(
    'change',
    (e) => {
      if (record?.stage === 'transfer' && e.target.value === 'breakout') {
        record.usedExample = true;
        persist();
      }
    },
    true,
  );
  button.addEventListener('click', open);
  persist();
  return { onRun };
}
