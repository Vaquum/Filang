// Run against the native server. Set PLAYWRIGHT_MODULE and CHROME_PATH for external installations.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || undefined, headless: true });
const origin = process.argv[2] || 'http://127.0.0.1:8764/';
const errors = [];
const context = await browser.newContext({ viewport: { width: 1380, height: 900 } });
function watch(p) {
  p.on('pageerror', (e) => errors.push(e.message));
  return p;
}
const p = watch(await context.newPage());
const count = (page) => page.locator('#cohort-summary .number').innerText();
async function verified(page) {
  await page.waitForFunction(
    () => document.querySelector('#native')?.textContent.startsWith('Filang verified'),
    null,
    { timeout: 25000 },
  );
}
async function check(page, n, eligible) {
  await verified(page);
  assert.equal(await count(page), String(n));
  assert.match(await page.locator('#cohort-summary').innerText(), new RegExp(eligible + ' eligible'));
}
async function save(page, title) {
  await page.locator('#save-open').click();
  await page.locator('#name').fill(title);
  await page.getByRole('button', { name: 'Save & create link' }).click();
  const href = await page.getByRole('textbox', { name: 'Saved question link' }).inputValue();
  await page.getByRole('button', { name: 'Done', exact: true }).click();
  return href;
}
try {
  await p.goto(origin);
  await p.getByLabel('Load a study').selectOption('friday');
  await p.getByText('Study shortcuts', {exact: true}).click();
  await check(p, 4, 20);
  assert.equal(await p.locator('#case-table tbody tr').count(), 4);
  assert.doesNotMatch(await p.locator('#population-notes').innerText(), /% positive/);
  await p.getByRole('button', { name: 'Without pattern · 16' }).click();
  await p.locator('#why summary').click();
  assert.match(await p.locator('#why').innerText(), /False/);
  await p.getByRole('button', { name: 'All eligible · 20' }).click();
  await p.getByLabel('Session window').selectOption('30m');
  await check(p, 2, 10);
  await p.getByLabel('Session window').selectOption('1h');
  await check(p, 4, 20);
  await p.locator('#changes summary').click();
  assert.match(await p.locator('#changes').innerText(), /2025-03-28 19:30Z/);
  await p.getByLabel('Match rule').selectOption('exact');
  await check(p, 1, 20);
  await p.getByLabel('Session window').selectOption('30m');
  await check(p, 0, 10);
  await p.getByLabel('Session window').selectOption('1h');
  await check(p, 1, 20);
  await p.getByRole('link', { name: 'Open in Composer' }).click();
  await p.locator('#send-g1:enabled').waitFor();
  await p.locator('#send-g1').click();
  await check(p, 1, 20);
  assert.match(await p.locator('#query').inputValue(), /exact_g1\("g1:o:0,1,2,2,u"\)/);
  const link = await save(p, 'March geometry');
  const fresh = await browser.newContext();
  const other = watch(await fresh.newPage());
  await other.goto(link);
  await check(other, 1, 20);
  assert.match(await other.locator('#message').innerText(), /Reopened/);
  await other.getByText('Study shortcuts', {exact:true}).click();
  await other.getByLabel('Match rule').selectOption('wick');
  await check(other, 4, 20);
  await other.getByLabel('Range definition').selectOption('v2');
  await check(other, 0, 0);
  await other.getByLabel('Show outcomes').selectOption('');
  await check(other, 0, 0);
  assert.doesNotMatch(await other.locator('#query').inputValue(), /measure/);
  await other.getByLabel('Range definition').selectOption('v1');
  await check(other, 4, 20);
  assert.doesNotMatch(await other.locator('#case-table').innerText(), /RETURN/);
  const url = new URL(link),
    params = new URLSearchParams(url.hash.slice(1)),
    packet = JSON.parse(params.get('study'));
  packet.evidence[0] = 'changed';
  url.hash = new URLSearchParams({ study: JSON.stringify(packet) }).toString();
  await other.goto(url.href);
  await other.waitForFunction(() =>
    document.querySelector('#message').textContent.includes('differ from the saved result'),
  );
  await other.goto(origin);
  await verified(other);
  await other.getByLabel('Load a study').selectOption('breakout');
  await check(other, 461, '14,496');
  await other.getByRole('button', { name: 'lookback=24h', exact: true }).click();
  await check(other, 261, '14,496');
  await other.getByText('Study shortcuts', {exact:true}).click();
  await other.getByLabel('4h bar direction').selectOption('up');
  await verified(other);
  assert.equal(await count(other), '358');
  await other.locator('.formal > summary').click();
  await other.locator('#query').fill('on BTCUSDT 15m find nonexistent()');
  await other.locator('#run').click();
  assert.match(await other.locator('#errors').innerText(), /nonexistent/);
  assert.ok(await other.locator('#save-open').isDisabled());
  await other.getByLabel('Load a study').selectOption('friday');
  await check(other, 4, 20);
  await other.getByText('Agent definitions', { exact: true }).click();
  const artifact = JSON.parse(
    await readFile(new URL('../extensions/quiet_friday_close.v2.json', import.meta.url), 'utf8'),
  );
  artifact.id = 'portable_containment';
  artifact.title = 'Portable containment';
  artifact.example = 'portable_containment_v2()';
  await other
    .locator('#installations input[type=file]')
    .setInputFiles({
      name: 'portable.json',
      mimeType: 'application/json',
      buffer: Buffer.from(JSON.stringify(artifact)),
    });
  await other.getByRole('button', { name: 'Use portable_containment@2 in question' }).click();
  await check(other, 0, 0);
  const extensionLink = await save(other, 'Portable definition');
  const clean = await browser.newContext();
  const cleanPage = watch(await clean.newPage());
  await cleanPage.goto(extensionLink);
  await check(cleanPage, 0, 0);
  assert.match(await cleanPage.locator('#message').innerText(), /Reopened/);
  await clean.close();
  await fresh.close();
  for (const w of [320, 390, 768]) {
    await p.setViewportSize({ width: w, height: 844 });
    await p.goto(origin);
    await verified(p);
    assert.ok(await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'overflow at ' + w);
  }
  assert.deepEqual(errors, []);
  console.log(
    'Passed browser journey, including Composer handoff, populations, native verification, fresh-profile replay, portable extensions, and responsive widths.',
  );
} finally {
  await browser.close();
}
