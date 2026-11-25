// NYSE's regular sessions for the bench's cube windows, read from Vaquum's field-data-api: the service Cube reads
// its calendar from (Vaquum/field-data-api, docs/calendar.md and docs/api.md). The bench keeps no calendar of its own.
//
// The service publishes NYSE's exceptions, not its sessions: the New York dates NYSE is closed and the instants it
// closes early, each with its source, inside the civil-date scope its supplied calendar declares. Within that scope
// a New York weekday it does not list as closed is a regular session, closing at 16:00 New York unless it lists an
// early close. Outside the scope it says nothing, so the table covers the scope only and the engine answers
// "unknown" there, with its own reason. Nothing here writes a date: every exception and the scope are the service's.
//
// Like Cube, it pins one publication and reads every page under that pin, checked to be that publication's.
// The table it builds is the engine's calendar text (`setCalendar(tsv, {table})`): a coverage line, then one row per
// session (New York midnight, close, weekday), all in UTC milliseconds. The engine pins the table's id and the
// SHA-256 of that text in each run's manifest.
import { createHash } from 'node:crypto';

export class CalendarError extends Error {}

const ZONE = 'America/New_York';
const DAY_MS = 86_400_000;
const PAGE_LIMIT = 1000;
const MAX_OFFSET = 100_000;
const DATE = /^\d{4}-\d{2}-\d{2}$/;
const HEX64 = /^[0-9a-f]{64}$/;
// NYSE's regular session is 09:30 to 16:00 New York, Monday to Friday (nyse.com/trade/hours-calendars). The engine's
// table needs the close only; the open bounds what an early close can be.
const OPEN_MINUTE = 9 * 60 + 30;
const CLOSE_MINUTE = 16 * 60;
const WEEKDAYS = ['mon', 'tue', 'wed', 'thu', 'fri'];
export const RULE = 'Regular sessions are the New York weekdays in the calendar’s scope that field-data-api does not list as NYSE closed; '
  + 'each closes at 16:00 New York unless it lists an NYSE early close for that day.';

const parts = new Intl.DateTimeFormat('en-US', {
  timeZone: ZONE, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit',
});
/** The New York civil date and minute of the day at a UTC instant. */
function newYork(ms) {
  const p = Object.fromEntries(parts.formatToParts(ms).map(({ type, value }) => [type, value]));
  return { date: `${p.year}-${p.month}-${p.day}`, minute: Number(p.hour) * 60 + Number(p.minute), second: Number(p.second) };
}
/** The UTC instant of a minute of a New York civil date. Throws where New York has no such minute. */
function atNewYork(date, minute) {
  const [y, m, d] = date.split('-').map(Number);
  const wall = Date.UTC(y, m - 1, d, 0, minute);
  let t = wall;
  for (let i = 0; i < 2; i++) {
    const seen = newYork(t);
    const [sy, sm, sd] = seen.date.split('-').map(Number);
    t -= Date.UTC(sy, sm - 1, sd, 0, seen.minute, seen.second) - wall;
  }
  const back = newYork(t);
  if (back.date !== date || back.minute !== minute || back.second !== 0) throw new CalendarError(`New York has no ${date} minute ${minute}`);
  return t;
}
const civil = (date) => { const [y, m, d] = date.split('-').map(Number); return Date.UTC(y, m - 1, d); };
const dateOf = (ms) => new Date(ms).toISOString().slice(0, 10);
/** 0 for Monday … 6 for Sunday, of a civil date. */
const weekday = (date) => (new Date(civil(date)).getUTCDay() + 6) % 7;

/**
 * The engine's nyse_regular table from one pinned field-data-api calendar: its NYSE market-holiday records and the
 * meta of the page they came on. Refuses anything it cannot read as an NYSE closure or early close in scope.
 */
export function nyseTable(records, meta) {
  const input = meta?.input_metadata ?? {};
  const start = input.source_scope_start; const end = input.source_scope_end;
  if (!DATE.test(start ?? '') || !DATE.test(end ?? '') || civil(start) > civil(end)) {
    throw new CalendarError('field-data-api’s calendar declares no civil-date scope, so it cannot say which days NYSE trades');
  }
  const closed = new Map(); const early = new Map(); let cancelled = 0;
  const inScope = (date) => civil(start) <= civil(date) && civil(date) <= civil(end);
  for (const r of records) {
    const v = r?.values ?? {};
    if (v.category !== 'market_holiday' || v.context?.source_id !== 'NYSE') continue;
    const id = String(r.id);
    if (v.status === 'cancelled') { cancelled++; continue; }
    if (v.status !== 'scheduled') throw new CalendarError(`NYSE record ${id} has status ${v.status}`);
    if (v.schedule_certainty !== 'confirmed') throw new CalendarError(`NYSE record ${id} is ${v.schedule_certainty ?? 'unspecified'}, not confirmed`);
    if (v.context?.source_timezone !== ZONE) throw new CalendarError(`NYSE record ${id} is not on New York time`);
    const s = v.schedule ?? {};
    let date;
    if (s.kind === 'date' && /^NYSE markets closed\b/.test(v.title ?? '') && DATE.test(s.date ?? '')) {
      date = s.date;
      if (closed.has(date)) throw new CalendarError(`field-data-api lists NYSE closed twice on ${date}`);
      closed.set(date, id);
    } else if (s.kind === 'instant' && /^NYSE early close\b/.test(v.title ?? '')) {
      const at = Date.parse(s.at);
      if (!Number.isFinite(at)) throw new CalendarError(`NYSE record ${id} has no readable instant`);
      const local = newYork(at);
      date = local.date;
      if (local.minute <= OPEN_MINUTE || local.minute >= CLOSE_MINUTE) throw new CalendarError(`NYSE record ${id} closes early outside the regular session`);
      if (early.has(date)) throw new CalendarError(`field-data-api lists two NYSE early closes on ${date}`);
      early.set(date, { at, id });
    } else {
      throw new CalendarError(`NYSE record ${id} (“${v.title}”) is neither a closure nor an early close`);
    }
    if (!inScope(date)) throw new CalendarError(`NYSE record ${id} is on ${date}, outside the calendar’s scope ${start} … ${end}`);
    if (weekday(date) > 4) throw new CalendarError(`NYSE record ${id} falls on a weekend`);
  }
  for (const date of early.keys()) if (closed.has(date)) throw new CalendarError(`field-data-api lists NYSE both closed and closing early on ${date}`);

  const from = atNewYork(start, 0);
  const to = atNewYork(dateOf(civil(end) + DAY_MS), 0);
  const lines = [`${from}\t${to}`];
  let sessions = 0;
  for (let day = civil(start); day <= civil(end); day += DAY_MS) {
    const date = dateOf(day); const wd = weekday(date);
    if (wd > 4 || closed.has(date)) continue;
    lines.push(`${atNewYork(date, 0)}\t${early.get(date)?.at ?? atNewYork(date, CLOSE_MINUTE)}\t${WEEKDAYS[wd]}`);
    sessions++;
  }
  const tsv = lines.join('\n') + '\n';
  return {
    tsv, sessions, from, to, scope: { start, end },
    closed: [...closed.keys()].sort(),
    earlyCloses: [...early].map(([date, { at }]) => ({ date, close: new Date(at).toISOString() })).sort((a, b) => a.date.localeCompare(b.date)),
    cancelled, tsvSha256: createHash('sha256').update(tsv).digest('hex'),
  };
}

/** A reader of one field-data-api. It holds the calendar it built and reads again only when the publication's calendar changes. */
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
    const pin = snap.snapshot_id; const calendar = snap.calendar;
    if (!HEX64.test(pin ?? '')) throw new CalendarError('field-data-api answered no publication to pin');
    if (!calendar?.dataset_id || !['ok', 'stale'].includes(calendar.status)) {
      throw new CalendarError(`field-data-api has no published calendar (status ${calendar?.status ?? 'none'})`);
    }
    if (held && held.provenance.dataset_id === calendar.dataset_id) return held;
    const records = []; let first = null; let offset = 0;
    for (;;) {
      const page = await ask('/v1/calendar', { snapshot_id: pin, category: 'market_holiday', limit: PAGE_LIMIT, offset });
      if (page.snapshot_id !== pin || page.source !== 'calendar' || page.dataset_id !== calendar.dataset_id) {
        throw new CalendarError('field-data-api answered a calendar page from another publication');
      }
      if (page.data?.projection_version !== 'calendar/1' || !Array.isArray(page.data.records)) throw new CalendarError('field-data-api answered a calendar page it does not describe as calendar/1');
      first ??= page;
      records.push(...page.data.records);
      const next = page.page?.next_offset;
      if (next === null || next === undefined) {
        if (Number.isInteger(page.page?.total) && records.length !== page.page.total) throw new CalendarError('field-data-api’s calendar pages do not add up to its total');
        break;
      }
      if (!Number.isInteger(next) || next <= offset || next > MAX_OFFSET) throw new CalendarError('field-data-api’s calendar pages do not advance');
      offset = next;
    }
    const meta = first.data.meta ?? {};
    const revision = meta.revision_id;
    if (!HEX64.test(revision ?? '')) throw new CalendarError('field-data-api’s calendar has no content revision to pin');
    const table = nyseTable(records, meta);
    const input = meta.input_metadata ?? {};
    return {
      // The engine pins this id beside the SHA-256 of the text: the source, and the calendar content it was built from.
      table: `field-data-api.nyse.${revision.slice(0, 16)}`,
      tsv: table.tsv,
      provenance: {
        source: 'field-data-api', route: '/v1/calendar?category=market_holiday', snapshot_id: pin, published_at: snap.published_at ?? null,
        dataset_id: calendar.dataset_id, status: calendar.status, revision_id: revision,
        input: { source_sha256: input.source_sha256 ?? null, source_as_of: input.source_as_of ?? null, imported_at: input.imported_at ?? null, import_format: input.import_format ?? null },
        scope: table.scope, coverage: { from: new Date(table.from).toISOString(), to: new Date(table.to).toISOString(), end: 'exclusive' },
        sessions: table.sessions, closed: table.closed, early_closes: table.earlyCloses, cancelled: table.cancelled,
        rule: RULE, tsv_sha256: table.tsvSha256,
      },
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
