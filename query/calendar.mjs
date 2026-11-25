// NYSE's regular sessions for the bench's cube windows, read from Vaquum's field-data-api: the service Cube reads
// its calendar from, and the one place calendar information comes from (Vaquum/field-data-api#23). The bench keeps
// no calendar and no calendar rule of its own.
//
// The service publishes the sessions themselves as `nyse_sessions` (projection market_sessions/1): one record per
// session day with its New York date, weekday, open and close, complete over a declared coverage of New York dates.
// A date in coverage with no record is not a session; a date outside coverage the service says nothing about, so
// the engine answers "unknown" there, with its own reason. This file only rewrites those records into the engine's
// calendar text (`setCalendar(tsv, {table})`): a coverage line, then one row per session (New York midnight, close,
// weekday), all in UTC milliseconds. The engine pins the table's id and the SHA-256 of that text in each run's
// manifest. Like Cube, it pins one publication and reads every page under that pin, checked to be that publication's.
import { createHash } from 'node:crypto';

export class CalendarError extends Error {}

const SOURCE = 'nyse_sessions';
const PROJECTION = 'market_sessions/1';
const ZONE = 'America/New_York';
const PAGE_LIMIT = 1000;
const MAX_OFFSET = 100_000;
const DATE = /^\d{4}-\d{2}-\d{2}$/;
const HEX64 = /^[0-9a-f]{64}$/;
const WEEKDAYS = ['mon', 'tue', 'wed', 'thu', 'fri'];

const parts = new Intl.DateTimeFormat('en-US', {
  timeZone: ZONE, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit',
});
/** The New York civil date and time of day at a UTC instant. */
function newYork(ms) {
  const p = Object.fromEntries(parts.formatToParts(ms).map(({ type, value }) => [type, value]));
  return { date: `${p.year}-${p.month}-${p.day}`, minute: Number(p.hour) * 60 + Number(p.minute), second: Number(p.second) };
}
/** The UTC instant at which a New York civil date begins. */
function newYorkMidnight(date) {
  const [y, m, d] = date.split('-').map(Number);
  const wall = Date.UTC(y, m - 1, d);
  let t = wall;
  for (let i = 0; i < 2; i++) {
    const seen = newYork(t);
    const [sy, sm, sd] = seen.date.split('-').map(Number);
    t -= Date.UTC(sy, sm - 1, sd, 0, seen.minute, seen.second) - wall;
  }
  const back = newYork(t);
  if (back.date !== date || back.minute !== 0 || back.second !== 0) throw new CalendarError(`New York has no midnight on ${date}`);
  return t;
}
const civilWeekday = (date) => { const [y, m, d] = date.split('-').map(Number); return (new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7; };
const instant = (text) => (typeof text === 'string' && /Z$|[+-]\d{2}:\d{2}$/.test(text) ? Date.parse(text) : NaN);

/**
 * The engine's nyse_regular table from one pinned `nyse_sessions` dataset: its records and the meta of its pages.
 * Nothing is inferred: a record that does not read as one session inside the declared coverage is refused.
 */
export function nyseTable(records, meta) {
  const start = meta?.coverage?.start; const end = meta?.coverage?.end;
  if (meta?.exchange !== 'XNYS' || meta?.timezone !== ZONE) throw new CalendarError('field-data-api’s nyse_sessions is not XNYS on New York time');
  if (!DATE.test(start ?? '') || !DATE.test(end ?? '') || !(start < end)) throw new CalendarError('field-data-api’s nyse_sessions declares no coverage');
  const from = newYorkMidnight(start); const to = newYorkMidnight(end);
  const lines = [`${from}\t${to}`];
  let previous = ''; let early = 0;
  for (const r of records) {
    const date = r?.date;
    if (!DATE.test(date ?? '') || date < start || date >= end) throw new CalendarError(`session ${date} is outside the declared coverage ${start} … ${end}`);
    if (date <= previous) throw new CalendarError(`sessions are not one per date in order at ${date}`);
    previous = date;
    const wd = WEEKDAYS.indexOf(r.weekday);
    if (wd < 0 || wd !== civilWeekday(date)) throw new CalendarError(`session ${date} names weekday ${r.weekday}`);
    const day = newYorkMidnight(date);
    const open = instant(r.open_at); const close = instant(r.close_at);
    if (!(day <= open && open < close && newYork(close).date === date && close - day < 86_400_000)) {
      throw new CalendarError(`session ${date} opens or closes outside its New York day`);
    }
    if (r.kind === 'early_close') early++;
    else if (r.kind !== 'regular') throw new CalendarError(`session ${date} is of kind ${r.kind}`);
    lines.push(`${day}\t${close}\t${WEEKDAYS[wd]}`);
  }
  const tsv = lines.join('\n') + '\n';
  return {
    tsv, from, to, coverage: { start, end }, sessions: records.length, earlyCloses: early,
    closures: Array.isArray(meta.closures) ? meta.closures.length : null, tsvSha256: createHash('sha256').update(tsv).digest('hex'),
  };
}

/** A reader of one field-data-api. It holds the table it built and reads again only when the published sessions change. */
export function fieldDataCalendar({ url, token = null, fetch: get = fetch, now = Date.now, maxAgeMs = 60_000 }) {
  const base = String(url).replace(/\/+$/, '');
  if (!/^https?:\/\/[^/?#@\s]+$/.test(base)) throw new CalendarError('FIELD_DATA_URL must be an HTTP(S) origin without credentials, path, query or fragment');
  let held = null; let checkedAt = -Infinity; let pending = null;

  async function ask(path, query = {}) {
    const q = new URLSearchParams(Object.entries(query).filter(([, v]) => v !== null && v !== undefined).map(([k, v]) => [k, String(v)]));
    const headers = { Accept: 'application/json', 'User-Agent': 'filang-query/1' };
    if (token) headers.Authorization = `Bearer ${token}`;
    let res;
    try { res = await get(`${base}${path}${q.size ? `?${q}` : ''}`, { headers, redirect: 'error', signal: AbortSignal.timeout(15_000) }); }
    catch (e) { throw new CalendarError(`field-data-api did not answer: ${e.message}`); }
    const body = await res.json().catch(() => null);
    if (!res.ok || body === null || typeof body !== 'object') {
      throw new CalendarError(`field-data-api answered ${res.status}${body?.error ? `: ${typeof body.error === 'string' ? body.error : body.error.code ?? 'error'}` : ''}`);
    }
    return body;
  }

  async function read() {
    const snap = await ask('/v1/snapshots/latest');
    const pin = snap.snapshot_id; const listed = snap.datasets?.[SOURCE];
    if (!HEX64.test(pin ?? '')) throw new CalendarError('field-data-api answered no publication to pin');
    if (!listed?.dataset_id || !['ok', 'stale'].includes(listed.status)) {
      throw new CalendarError(`field-data-api publishes no ${SOURCE} (status ${listed?.status ?? 'none'})`);
    }
    if (held && held.provenance.dataset_id === listed.dataset_id) return held;
    const records = []; let first = null; let offset = 0;
    for (;;) {
      const page = await ask(`/v1/data/${SOURCE}`, { snapshot_id: pin, limit: PAGE_LIMIT, offset });
      if (page.snapshot_id !== pin || page.source !== SOURCE || page.dataset_id !== listed.dataset_id) {
        throw new CalendarError(`field-data-api answered a ${SOURCE} page from another publication`);
      }
      if (page.data?.projection_version !== PROJECTION || !Array.isArray(page.data.records)) throw new CalendarError(`field-data-api answered a ${SOURCE} page that is not ${PROJECTION}`);
      first ??= page;
      records.push(...page.data.records);
      const next = page.page?.next_offset;
      if (next === null || next === undefined) {
        if (Number.isInteger(page.page?.total) && records.length !== page.page.total) throw new CalendarError(`field-data-api’s ${SOURCE} pages do not add up to its total`);
        break;
      }
      if (!Number.isInteger(next) || next <= offset || next > MAX_OFFSET) throw new CalendarError(`field-data-api’s ${SOURCE} pages do not advance`);
      offset = next;
    }
    const meta = first.data.meta ?? {};
    if (!HEX64.test(meta.revision_id ?? '')) throw new CalendarError(`field-data-api’s ${SOURCE} has no content revision to pin`);
    const table = nyseTable(records, meta);
    return {
      // The engine pins this id beside the SHA-256 of the text: the source, and the content revision it was built from.
      // The text comes last, so a reader of the first few kilobytes (the deploy log) sees the id and provenance.
      table: `field-data-api.${SOURCE}.${meta.revision_id.slice(0, 16)}`,
      provenance: {
        source: 'field-data-api', route: `/v1/data/${SOURCE}`, projection: PROJECTION, snapshot_id: pin, published_at: snap.published_at ?? null,
        dataset_id: listed.dataset_id, status: listed.status, revision_id: meta.revision_id, exchange: meta.exchange,
        coverage: table.coverage, sessions: table.sessions, early_closes: table.earlyCloses, closures: table.closures,
        tsv_sha256: table.tsvSha256,
      },
      tsv: table.tsv,
    };
  }

  /**
   * The nyse_regular table, as { table, tsv, provenance }. The publication is asked again at most every maxAgeMs.
   * When the service cannot answer after a table was read, that table is kept: it stays pinned to the publication
   * its provenance names. Before any table was read, the service's failure is the answer.
   */
  async function nyse() {
    if (held && now() - checkedAt < maxAgeMs) return held;
    pending ??= read().then((answer) => { held = answer; checkedAt = now(); return answer; })
      .catch((e) => { if (!held || !(e instanceof CalendarError)) throw e; checkedAt = now(); return held; })
      .finally(() => { pending = null; });
    return pending;
  }

  return { nyse };
}
