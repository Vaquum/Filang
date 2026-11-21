// Install the existing, immutable recording and Composer tapes outside source control.
import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { DATA, STUDY } from './native/inputs.mjs';

const [lab] = process.argv.slice(2);
if (!lab) throw Error('Pass the root of the original study recording.');
const pin = JSON.parse(await readFile(resolve(STUDY,'recording-lock.json'),'utf8'));
const paths = ['recorded-bars.csv','composer/bars','composer/activity'];
const assets = await Promise.all(paths.map(async (name) => {
  const bytes = await readFile(resolve(lab,name));
  if (createHash('sha256').update(bytes).digest('hex') !== pin.files[name])
    throw Error(name + ' differs from the pinned study asset.');
  return [name.split('/').at(-1),bytes];
}));
await mkdir(DATA,{recursive:true});
await Promise.all(assets.map(([name,bytes]) => writeFile(resolve(DATA,name),bytes)));
console.log('Installed the verified study recording in ' + DATA);
