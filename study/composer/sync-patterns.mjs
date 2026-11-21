// Verify vendored assets offline, or update all of them from one explicit Composer commit.
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {readFileSync,writeFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
const files=['patterns.js','pattern-browser.js','matcher.js'];
const local=name=>new URL(name,import.meta.url);
const digest=data=>createHash('sha256').update(data).digest('hex');
const lockFile=local('patterns-lock.json');
const [command,repo,revision]=process.argv.slice(2);
if(command==='--update'){
  if(!repo||!/^[0-9a-f]{40}$/.test(revision||'')) throw new Error('Supply the Composer checkout and a full commit SHA.');
  const assets=files.map(name=>execFileSync('git',['-C',repo,'show',revision+':'+name]));
  for(const [i,name] of files.entries()) writeFileSync(local(name),assets[i]);
  writeFileSync(lockFile,JSON.stringify({repository:'Vaquum/Composer',revision,files:Object.fromEntries(files.map((f,i)=>[f,digest(assets[i])]))},null,2)+'\n');
}else if(command) throw new Error('Use no arguments to verify or --update CHECKOUT SHA.');
const lock=JSON.parse(readFileSync(lockFile,'utf8'));
for(const f of files){
  if(digest(readFileSync(local(f)))!==lock.files[f]) throw new Error('Asset differs from the Composer pin: '+fileURLToPath(local(f)));
}
console.log('Composer pattern assets verified at '+lock.revision.slice(0,12));
