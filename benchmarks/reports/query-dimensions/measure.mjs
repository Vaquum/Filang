import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {resolve} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

const {chromium} = await import(pathToFileURL(resolve(process.env.PLAYWRIGHT_MODULE)).href);

const baseline = process.argv[2];
const root = fileURLToPath(new URL('../../../', import.meta.url));
const roots = [resolve(baseline), root];
const ports = [];
const servers = [];
const data = resolve(process.env.FILANG_STUDY_DATA || root + '/data/study');
const engine = resolve(process.env.FILANG_QUERY_ENGINE_DIR || root + '/target/engine-dist/browser');
const pinned = (await readFile(data + '/recorded-bars.csv', 'utf8')).trimEnd().split('\n').slice(1);
const rows = pinned.map((row, i) => {
  const volume = 500000 + 100000 * (i % 11);
  return `${row},${volume},${volume * (3 + i % 5) / 10},${10 + (i % 21)}`;
});
const columns = 'open_ms,open,high,low,close,base_volume,volume,taker_buy_volume,trade_count';
const recording = (count, name) => {
  const selected = rows.slice(-count);
  const csv = columns + '\n' + selected.join('\n') + '\n';
  return { csv, provenance: { instrument: 'BTCUSDT Binance spot', interval_ms: 900000, columns: columns.split(','),
    row_count: selected.length, source: 'cube', window_name: name, through: '2025-06-01T00:00:00.000Z',
    csv_sha256: createHash('sha256').update(csv).digest('hex') } };
};
const barsets = {'30d': recording(rows.length, '30 days'), '7d': recording(672, '7 days')};
const browser = await chromium.launch({executablePath:process.env.CHROME, headless: true, args:['--disable-background-networking']});
const errors = [];
const waitAnswer = page => page.waitForFunction(() => !!document.querySelector('#readout > b') && !document.querySelector('#status').classList.contains('err'));
const waitLoaded = page => page.waitForFunction(() => /ms · sha256/.test(document.querySelector('#status').textContent));
async function pageFor(i) {
  const context = await browser.newContext({viewport:{width:1440,height:900}, serviceWorkers:'block'});
  await context.route(url => url.hostname !== '127.0.0.1', route => route.abort());
  await context.route('**/bars/windows', route => route.fulfill({json:{cube:true,default:'30d',windows:[{key:'7d',name:'7 days'},{key:'30d',name:'30 days'}]}}));
  await context.route('**/bars?w=*', route => route.fulfill({json:barsets[new URL(route.request().url()).searchParams.get('w')]}));
  const page = await context.newPage();
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', msg => { if (msg.type() === 'error' && msg.text().includes('Error:')) errors.push(msg.text()); });
  return {context, page, url: ports[i]};
}
const dimensionQuery = 'on BTCUSDT 15m\nfind hammer\nwhere candle_relation(volume(), is: above, right: volume(bars_ago: 1))\nmeasure close_return(after: 1h)';
const code = 'g1:o:0,1,3,4,u;2,3,5,6,u|volume:0,1|delta:0,2/1';
const drawingQuery = `on BTCUSDT 15m\nfind chained_g1(${JSON.stringify(code)})\nmeasure close_return(after: 1h)`;

async function smoke() {
  const {context,page,url} = await pageFor(1);
  try {
    await page.goto(url + '/#q=' + encodeURIComponent(dimensionQuery) + '&w=30d');
    await waitAnswer(page);
    await page.locator('[data-dim="volume"]').waitFor();
    assert.equal(await page.locator('[data-dim]').count(), 1);
    await page.getByRole('button', {name:/Lanes/}).click();
    for (const label of ['Trades','Delta','Trade size','Net taker imbalance']) {
      await page.getByRole('option', {name:label,exact:true}).click();
    }
    assert.deepEqual(await page.locator('[data-dim]').evaluateAll(els=>els.map(el=>el.dataset.dim)), ['volume','trades','delta','size','imbalance']);
    await page.reload();
    await waitAnswer(page);
    assert.equal(await page.locator('[data-dim]').count(), 5);
    await page.locator('#right .sec button').first().click();
    assert.equal(await page.locator('[data-dim]').count(), 5);
    assert.match(await page.locator('#right').innerText(), /Facts at this close/i);
    await page.locator('#right summary').getByText('Dimension facts').click();
    await page.locator('#right details[open] dl').waitFor();
    assert.equal(await page.locator('#right details[open] dt').count(), 5);
    await page.locator('#add').focus();
    await page.waitForFunction(() => {
      const counts = [...document.querySelectorAll('.pop [data-count]')];
      return counts.length > 0 && counts.every(cell => /[0-9]/.test(cell.textContent));
    });
    await page.locator('#add').blur();
    await page.getByRole('button', {name:/Lanes/}).click();
    for (const label of ['Volume','Trades','Delta','Trade size','Net taker imbalance']) {
      await page.getByRole('option', {name:label,exact:true}).click();
    }
    assert.equal(await page.locator('[data-dim]').count(), 0);
    assert.equal(new URLSearchParams(new URL(page.url()).hash.slice(1)).get('ln'), '');
    await page.reload();
    await waitAnswer(page);
    assert.equal(await page.locator('[data-dim]').count(), 0);
    await page.getByRole('button', {name:/Window/}).click();
    await page.getByRole('menuitemradio', {name:/Pinned recording/}).click();
    await page.locator('.lane.refused .refusal').waitFor();
    assert.match(await page.locator('.lane.refused .refusal').first().innerText(), /no counters/);
    assert.equal(await page.getByRole('button', {name:/Lanes/}).count(), 0);
    await page.reload();
    await page.locator('.lane.refused .refusal').waitFor();
    const grouping = 'on BTCUSDT 15m\nfind hammer\ngroup by candle_relation(delta(), is: above, right: 0)';
    await page.goto(url + '/?test=group#q=' + encodeURIComponent(grouping) + '&w=pinned');
    await page.locator('[data-lane="x:g"] .refusal').waitFor();
    assert.match(await page.locator('[data-lane="x:g"] .refusal').innerText(), /no counters/);
    let p = await context.newPage();
    await p.goto(url + '/#q=' + encodeURIComponent(drawingQuery) + '&w=30d');
    await waitAnswer(p);
    const sent = new URL(await p.locator('#to-composer').getAttribute('href')).searchParams.get('drawing');
    assert.deepEqual(JSON.parse(sent).dimensions, ['volume:0,1','delta:0,2/1']);
    assert.match(await p.locator('#lanes').innerText(), /bar 1 < zero < bar 2/);
    console.log(JSON.stringify({smoke:true, browser:browser.version(), errors}));
    assert.deepEqual(errors, []);
  } finally { await context.close(); }
}

async function sample(i) {
  const {context,page,url} = await pageFor(i);
  try {
    await page.addInitScript(() => {
      const observer = new MutationObserver(() => {
        if (document.querySelector('#readout > b')) { window.firstAnswerMs = performance.now(); observer.disconnect(); }
      });
      observer.observe(document, {childList:true,subtree:true});
    });
    await page.goto(url + '/#w=7d', {waitUntil:'domcontentloaded'});
    await waitAnswer(page);
    const first = await page.evaluate(() => window.firstAnswerMs);
    const readout = () => page.locator('#readout > b').innerText();
    const initial = await readout();
    const windowMs = await page.evaluate(async () => {
      const button = [...document.querySelectorAll('#encbar button')].find(b => b.textContent.startsWith('Window'));
      button.click();
      const target = [...document.querySelectorAll('.pop button')].find(b => b.textContent.startsWith('30 days'));
      const elapsed = new Promise(resolve => {
        const status = document.querySelector('#status');
        const o = new MutationObserver(() => { if (/ms · sha256/.test(status.textContent)) { o.disconnect(); resolve(performance.now() - start); } });
        o.observe(status,{childList:true,subtree:true});
      });
      const start = performance.now();
      target.click();
      return elapsed;
    });
    await waitLoaded(page);
    const windowAnswer = await readout();
    return await page.evaluate(({first,windowMs,initial,windowAnswer}) => {
      const open = name => [...document.querySelectorAll('#encbar button')].find(b => b.textContent.startsWith(name)).click();
      const pick = label => [...document.querySelectorAll('.pop button')].find(b => b.textContent.startsWith(label));
      let questions = 0;
      const receipts = [];
      for (const label of ['Hammers by 4h trend','Quiet Friday close','Breakout with the trend','Failed break of the prior low']) {
        open('Question');
        const option = pick(label);
        const start = performance.now(); option.click(); questions += performance.now() - start;
        receipts.push([document.querySelector('#readout > b').textContent, new URLSearchParams(location.hash.slice(1)).get('q')]);
      }
      const start = performance.now();
      document.querySelector('#right .sec button').click(); const firstClose = performance.now() - start;
      const next = [];
      for (let j = 0; j < 2; j++) {
        const t = performance.now();
        document.dispatchEvent(new KeyboardEvent('keydown',{key:'.',bubbles:true}));
        next.push(performance.now() - t);
      }
      const t = performance.now(); document.querySelector('#add').focus(); const add = performance.now() - t;
      return {first,windowMs,questions,firstClose,next,add,receipts:[initial, windowAnswer, ...receipts],lanes:document.querySelectorAll('[data-dim]').length};
    },{first,windowMs,initial,windowAnswer});
  } finally { await context.close(); }
}
try {
  for (const cwd of roots) {
    const server = spawn(process.execPath, ['query/serve.mjs'], {cwd, env:{...process.env, PORT:'0', FILANG_QUERY_ENGINE_DIR:engine, CUBE_URL:''}});
    servers.push(server);
    ports.push(/http:\/\/127\.0\.0\.1:\d+/.exec(String((await once(server.stdout, 'data'))[0]))[0]);
  }
  if (process.argv.includes('--smoke')) await smoke();
  else {
    let expected;
    for (let trial = 0; trial < Number(process.env.FILANG_BROWSER_CYCLES || 9); trial++) {
      for (const i of (trial % 2 ? [1,0] : [0,1])) {
        const m = await sample(i);
        expected ??= m.receipts;
        assert.deepEqual(m.receipts, expected);
        assert.equal(m.lanes, 0);
        console.log(JSON.stringify({trial, build:['baseline','candidate'][i], ...m}));
      }
    }
    assert.deepEqual(errors, []);
  }
} finally {
  for (const server of servers) server.kill();
  await browser.close();
}
