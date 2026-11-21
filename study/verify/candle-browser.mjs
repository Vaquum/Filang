import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { COMPOSER_REVISION, drawingG1, encodeDrawing } from '../composer/drawing.js';
import { loadInputs } from '../native/inputs.mjs';

const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({executablePath:process.env.CHROME_PATH,headless:true});
const origin = process.argv[2] || 'http://127.0.0.1:8764/';
const page = await browser.newPage({viewport:{width:1400,height:980}});
const errors = [];
page.on('pageerror', e => errors.push(e.message));

async function count(n, target = page) {
  await target.waitForFunction(count => {
    const native = document.querySelector('#native').textContent;
    const found = document.querySelector('#cohort-summary .number')?.textContent.replaceAll(',','');
    return native.startsWith('Filang verified') && found === String(count);
  },n,{timeout:20000});
}
async function pick(button, filter, choice) {
  await page.getByRole('button',{name:button,exact:true}).click();
  const dialog = page.locator('#dialog');
  await dialog.getByRole('combobox').fill(filter);
  await dialog.getByRole('option').filter({hasText:choice}).first().click();
}
async function adjust(section) {
  await page.getByRole('button',{name:'Change ' + section,exact:true}).locator('..')
    .getByRole('button',{name:'Adjust',exact:true}).click();
}
try {
  await page.goto(origin);
  await count(439);
  await pick('New question','reclaim','Prior range reclaim');
  await count(842);
  await pick('+ Filter','wick share','Wick or body share');
  await count(312);
  await pick('+ Filter','range median','Range versus recent median');
  await count(126);
  assert.match(await page.locator('#chart-heading').innerText(),/Breach 2025-01-04 09:30Z.*Frozen level 97833.34/s);
  await pick('+ Outcome','close return','Close return');
  await count(126);
  assert.match(await page.locator('#case-table').innerText(),/1H RETURN/);
  await page.getByRole('button',{name:'Remove filter Range versus recent median'}).click();
  await count(312);
  await page.getByRole('button',{name:'Remove filter Wick or body share'}).click();
  await count(842);

  await adjust('pattern Prior range reclaim');
  await page.getByLabel('Earliest reclaim (candles)').fill('1');
  await page.getByLabel('Latest reclaim (candles)').fill('3');
  await page.getByRole('button',{name:'Apply changes'}).click();
  await count(432);
  assert.match(await page.locator('#chart-heading').innerText(),/Breach 2025-01-01 05:00Z.*First reclaim 2025-01-01 05:15Z.*93578.77/s);
  await adjust('pattern Prior range reclaim');
  await page.getByLabel('reference',{exact:true}).selectOption('prior_high');
  await page.getByRole('button',{name:'Apply changes'}).click();
  await count(454);

  await pick('New question','compare candle','Compare candle prices');
  await pick('+ Filter','price near','Price near a level');
  await count(1682);
  await adjust('pattern Compare candle prices');
  await page.getByLabel('left endpoint').selectOption('high');
  await page.getByLabel('right candles back').fill('2');
  await page.getByRole('button',{name:'Apply changes'}).click();
  await page.waitForFunction(()=>document.querySelector('#native').textContent.startsWith('Filang verified'));
  assert.match(await page.locator('#query').inputValue(),/price\(high\).*bars_ago: 2/s);

  const { bundle: { rec } } = loadInputs();
  const first = rec.slotClosingAt(Date.parse('2025-01-01T00:30:00Z'));
  const second = first + 1;
  const bottom = Math.min(rec.L[first], rec.L[second]);
  const top = rec.H[second];
  const drawing = {
    version: 1, revision: COMPOSER_REVISION, oriented: true,
    bars: [first, second].map(i => ({
      v: [rec.L[i], Math.min(rec.O[i], rec.C[i]), Math.max(rec.O[i], rec.C[i]), rec.H[i]]
        .map(price => 15 + 70 * (price - bottom) / (top - bottom)),
      d: rec.C[i] >= rec.O[i] ? 'u' : 'd',
    })),
    pins: [{ a: { bar: 0, part: 'H' }, b: { bar: 1, part: 'H' } }, { bar: 1, color: true }],
    skeleton: 0, stretch: 0, next: { dir: 0, measure: 'any', bps: 10, atr: 1 }, limit: 12,
  };
  const composer = new URL('composer/', origin);
  composer.searchParams.set('drawing', encodeDrawing(drawing));
  composer.searchParams.set('g1', drawingG1(drawing));
  composer.searchParams.set('question', 'on BTCUSDT 15m\nfind hammer');
  await page.goto(composer.href);
  await page.getByRole('button', { name: 'Use pins on fixed candles ↗' }).click();
  await count(4828);
  assert.match(await page.locator('#query').inputValue(), /candle_window\(candle_relation.*bars: 2\)/);
  assert.match(await page.locator('#message').innerText(), /Composer pins imported/);

  await page.getByText('Agent definitions', { exact: true }).click();
  await page.locator('#installations input[type=file]').setInputFiles(
    fileURLToPath(new URL('../examples/long_wick_reclaim.v1.json', import.meta.url)),
  );
  await pick('New question', 'long wick reclaim', 'Long-wick reclaim of a prior low');
  await count(126);
  assert.match(await page.locator('#query').inputValue(), /find long_wick_reclaim\(\)/);
  await page.locator('#save-open').click();
  await page.locator('#name').fill('Long-wick prior-low reclaim');
  await page.getByRole('button', { name: 'Save & create link' }).click();
  const href = await page.getByRole('textbox', { name: 'Saved question link' }).inputValue();
  const fresh = await browser.newPage();
  fresh.on('pageerror', e => errors.push(e.message));
  await fresh.goto(href);
  await count(126, fresh);
  assert.match(await fresh.locator('#message').innerText(), /Reopened/);
  assert.deepEqual(errors,[]);
  console.log('Verified 842/312/126 reclaims, 432 delayed reclaims, 454 high reclaims, 1,682 price comparisons, 4,828 Composer pin matches and the 126-match event in a fresh profile.');
} finally { await browser.close(); }
