import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { BINARY } from './inputs.mjs';

export async function startWorker(bundle, csv) {
  const dir = await mkdtemp(join(tmpdir(),'filang-study-'));
  const bars = join(dir,'bars.csv');
  const calendar = join(dir,'calendar.tsv');
  const cal = bundle.cal;
  const rows = cal.sessions.map(s => [s.dayStart,s.close,s.weekday].join('\t'));
  const queue = [];
  let child;
  let failed;
  const fail = (error) => {
    if (failed) return;
    failed = error;
    for (const next of queue.splice(0)) next.reject(error);
  };
  try {
    await Promise.all([
      writeFile(bars,csv),
      writeFile(calendar, [[cal.covStart,cal.covEnd].join('\t'), ...rows].join('\n') + '\n'),
    ]);
    child = spawn(BINARY,['study','--bars',bars,'--calendar',calendar,'--interval-ms',String(bundle.rec.barMs)],
      {stdio:['pipe','pipe','inherit']});
    const ready = new Promise((resolve,reject) => queue.push({resolve,reject}));
    child.on('error',fail);
    child.on('exit', (code,signal) => fail(Error('Filang study process exited (' + (signal || code) + ').')));
    child.stdin.on('error',fail);
    createInterface({input:child.stdout}).on('line', line => {
      const waiting = queue.shift();
      if (!waiting) { fail(Error('Unsolicited native study response.')); return; }
      try {
        waiting.resolve(JSON.parse(line));
      } catch (e) {
        waiting.reject(e);
        fail(e);
      }
    });
    const handshake = await ready;
    if (handshake.ready !== 'filang-study-source-v1') throw Error('Unexpected native study protocol.');
  } catch (e) {
    child?.stdin.end();
    throw e;
  } finally {
    await rm(dir,{recursive:true,force:true});
  }
  return {
    evaluate(wire) {
      if (failed) return Promise.reject(failed);
      if (queue.length >= 8) return Promise.reject(Error('Filang study is busy. Retry the question.'));
      return new Promise((resolve,reject) => {
        queue.push({resolve,reject});
        child.stdin.write(wire + '\n');
      });
    },
    close() { child.stdin.end(); },
  };
}
