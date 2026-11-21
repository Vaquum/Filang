import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH, headless: true });
const url = process.argv[2] || 'http://127.0.0.1:8764/';
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
const errors = [];
page.on('pageerror', (e) => errors.push(e.message));
const query = () => page.locator('#query').inputValue();
async function verified(count) {
  await page.waitForFunction(
    () => document.querySelector('#native').textContent.startsWith('Filang verified'),
    null,
    { timeout: 30000 },
  );
  if (count != null)
    assert.equal(
      (await page.locator('#cohort-summary .number').innerText()).replaceAll(',', ''),
      String(count),
    );
}
async function choose(action, term, title, selector = '#dialog') {
  await action.click();
  const area = page.locator(selector);
  await area.getByRole('combobox').fill(term);
  await area
    .getByRole('option')
    .filter({ has: page.locator('.choice-title', { hasText: new RegExp('^' + title + '$') }) })
    .first()
    .click();
}
try {
  await page.goto(url);
  await verified(439);
  await choose(page.getByRole('button', { name: 'Either pattern…' }), 'tsutsumi-sen', 'Engulfing');
  await verified();
  const unionCount = Number((await page.locator('#cohort-summary .number').innerText()).replaceAll(',', ''));
  assert.ok(unionCount >= 2783 && unionCount < 439 + 2783);
  assert.match(await query(), / or /);
  await page.getByRole('button', { name: 'Remove Engulfing from pattern' }).click();
  await verified(439);
  await choose(page.getByRole('button', { name: 'Both patterns…' }), 'tsutsumi-sen', 'Engulfing');
  await verified(439 + 2783 - unionCount);
  await page.getByRole('button', { name: 'Remove Engulfing from pattern' }).click();
  await verified(439);
  const inline = page.getByRole('combobox', { name: 'Find a pattern' });
  await inline.fill('包み線');
  await page.locator('.inline-options [role=option]').first().waitFor();
  assert.match(await page.locator('.inline-options').innerText(), /2,783 matches/);
  await inline.press('Enter');
  await verified(2783);
  assert.match(await query(), /Engulfing/);
  await choose(page.getByRole('button', { name: '+ Filter', exact: true }), 'weekday', 'Session weekday');
  await verified(393);
  assert.match(await query(), /where weekday\(nyse_regular\) = fri/);
  await inline.fill('包み線');
  assert.match(await page.locator('.inline-options').innerText(), /393 matches/);
  await inline.press('Escape');
  await choose(
    page.getByRole('button', { name: '+ Grouping', exact: true }),
    'trend',
    'Completed higher-timeframe trend',
  );
  await verified(393);
  assert.match(await query(), /group by completed_trend/);
  const filter = page
    .locator('.clause-section')
    .filter({ has: page.getByRole('button', { name: '+ Filter', exact: true }) });
  await filter.getByRole('button', { name: 'Adjust', exact: true }).click();
  const weekday = page.getByLabel('session day', { exact: true });
  await weekday.fill('invalid_day');
  await page.getByRole('button', { name: 'Apply changes' }).click();
  assert.ok(await page.locator('#dialog .picker-error').innerText());
  await weekday.fill('{mon | fri}');
  await page.getByRole('button', { name: 'Apply changes' }).click();
  await verified();
  assert.equal(await page.locator('#candidates button').count(), 2);
  await filter.getByRole('button', { name: 'Negate', exact: true }).click();
  await verified();
  assert.match(await query(), /where not /);
  await choose(filter.getByRole('button', { name: 'Or…' }), 'session tail', 'Session tail');
  await verified();
  assert.match(await query(), / or session_tail\(/);
  await page.getByRole('button', { name: /Remove filter/ }).click();
  await verified(2783);
  await page.getByRole('button', { name: /Remove grouping/ }).click();
  await page.getByRole('button', { name: /Remove outcome/ }).click();
  await verified(2783);
  await choose(page.getByRole('button', { name: 'New question' }), 'channel', 'Channel breakout');
  await verified(461);
  assert.doesNotMatch(await query(), /measure|where|group by/);
  await page.locator('#builder').getByRole('button', { name: 'Adjust', exact: true }).click();
  await page.getByLabel('over', { exact: true }).fill('{12h | 18h}');
  await page.getByText('Share as a named parameter').click();
  await page.getByLabel('Parameter name for over').fill('span');
  await page.getByRole('button', { name: 'Apply changes' }).click();
  await verified();
  assert.match(await query(), /let span = \{12h \| 18h\}/);
  await choose(page.getByRole('button', { name: '+ Outcome', exact: true }), 'return', 'Close return');
  await verified();
  await page.getByRole('button', { name: 'New question' }).click();
  await page.locator('#dialog [role=combobox]').fill('not-a-real-pattern');
  assert.equal(await page.locator('#dialog [role=option]').count(), 0);
  await page.locator('#dialog [role=combobox]').press('Escape');
  assert.match(await query(), /let span/);
  await page.getByText('Agent definitions', { exact: true }).click();
  const artifact = JSON.parse(
    await readFile(new URL('../extensions/quiet_friday_close.v1.json', import.meta.url), 'utf8'),
  );
  artifact.id = 'builder_condition';
  artifact.title = 'Custom closing window';
  await page
    .locator('#installations input[type=file]')
    .setInputFiles({
      name: 'builder.json',
      mimeType: 'application/json',
      buffer: Buffer.from(JSON.stringify(artifact)),
    });
  await page.getByRole('button', { name: 'Use builder_condition@1 in question' }).waitFor();
  await choose(
    page.getByRole('button', { name: '+ Filter', exact: true }),
    'Custom closing',
    'Custom closing window',
  );
  await verified();
  assert.match(await query(), /where builder_condition\(\)/);
  await page.locator('.formal > summary').click();
  const field = page.locator('#query');
  await field.fill('on BTCUSDT 15m\nfind "ハン');
  await page.locator('#formal-menu [role=option]').first().waitFor();
  await field.press('ArrowDown');
  await field.press('Enter');
  await verified(439);
  assert.match(await query(), /Hammer/i);
  const link = await page.locator('#builder a').getAttribute('href');
  assert.equal(new URL(link).searchParams.get('pattern'), 'hammer');
  await page.goto(url + '?pattern=bullish-engulfing');
  await verified(1402);
  for (const width of [320, 390, 768]) {
    await page.setViewportSize({ width, height: 844 });
    await page.getByRole('button', { name: 'New question' }).click();
    assert.ok(
      await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
      'overflow at ' + width,
    );
    await page.locator('#dialog [role=combobox]').fill('hammer');
    await page.locator('#dialog [role=combobox]').press('Escape');
  }
  assert.deepEqual(errors, []);
  console.log(
    'Verified bilingual search, live match previews, from-scratch building, parameters, sweeps, logic, grouping, outcomes, installed definitions, formal completions, transfers and responsive controls.',
  );
} finally {
  await browser.close();
}
