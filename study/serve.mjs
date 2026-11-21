import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { extname, join } from 'node:path';
import { compile, QueryError } from './native/compiler.mjs';
import { DATA, loadInputs, STUDY } from './native/inputs.mjs';
import { startWorker } from './native/worker.mjs';

const port = Number(process.argv[2] || 8764);
if (!Number.isInteger(port) || port < 1 || port > 65535) throw Error('Expected a localhost port.');
const {bundle,assets} = loadInputs();
const native = await startWorker(bundle,assets.get('recorded-bars.csv'));
const mime = new Map([['.html','text/html'],['.css','text/css'],['.js','text/javascript'],['.json','application/json']]);
const assetsPattern = /^(?:index\.html|language\.html|[a-z-]+\.css|(?:composer|extensions|src)\/(?:[\w.-]+\/)*[\w.-]+\.(?:html|css|js|json))$/;
const json = (res, status, value) => {
  res.writeHead(status,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'});
  res.end(JSON.stringify(value));
};

const server = createServer(async (req,res) => {
  try {
    const browserHost = req.headers.host;
    if (browserHost !== '127.0.0.1:' + port && browserHost !== 'localhost:' + port)
      return json(res,403,{error:'Use the loopback study origin.'});
    const path = decodeURIComponent(new URL(req.url, 'http://127.0.0.1').pathname).slice(1);
    if (path === 'api/filang/evaluate' && req.method === 'POST') {
      if (req.headers.origin && req.headers.origin !== 'http://' + browserHost)
        return json(res,403,{error:'Use the loopback study origin.'});
      if (req.headers['content-type']?.split(';')[0] !== 'application/json')
        return json(res,415,{error:'Use application/json.'});
      const chunks = [];
      let length = 0;
      for await (const chunk of req) {
        length += chunk.length;
        if (length <= 131072) chunks.push(chunk);
      }
      if (length > 131072) return json(res,413,{error:'Study request exceeds 128 KiB.'});
      let data;
      try { data = JSON.parse(Buffer.concat(chunks).toString('utf8')); }
      catch { return json(res,400,{error:'Invalid JSON.'}); }
      if (!data || typeof data !== 'object') return json(res,400,{error:'Expected a study object.'});
      const checked = compile(bundle,data);
      const answer = await native.evaluate(checked.wire);
      if (answer.error) return json(res,422,{kind:'query',error:answer.error});
      const pins = {source:bundle.digest,calendar:bundle.sessionsDigest,engine:answer.engine,work:answer.work};
      return json(res,200,answer.results.length === 1
        ? {...pins,...answer.results[0]}
        : {...pins,labels:checked.candidates,results:answer.results});
    }
    if (!['GET','HEAD'].includes(req.method)) return json(res,405,{error:'Method unavailable.'});
    const name = path === '' ? 'index.html' : path === 'composer/' ? 'composer/index.html' : path;
    const body = assets.has(name) ? assets.get(name)
      : assetsPattern.test(name) && !name.split('/').some(s => s === '.' || s === '..')
        ? await readFile(join(STUDY,name)) : null;
    if (!body) return json(res,404,{error:'Asset not found.'});
    const type = name.endsWith('.csv') ? 'text/csv' : mime.get(extname(name)) || 'application/octet-stream';
    res.writeHead(200,{'Content-Type':type,'Content-Length':body.length,'Cache-Control':'no-cache'});
    res.end(req.method === 'HEAD' ? undefined : body);
  } catch (e) {
    if (e instanceof QueryError) return json(res,422,{kind:e.kind,error:e.message,diagnostics:e.diagnostics});
    if (e.code === 'ENOENT') return json(res,404,{error:'Asset not found.'});
    if (e instanceof URIError) return json(res,400,{error:'Invalid request path.'});
    console.error(e);
    if (!res.headersSent) json(res,500,{error:'Filang study execution failed. See the local server output.'});
  }
});
for (const sig of ['SIGTERM','SIGINT']) process.once(sig,() => {
  native.close();
  server.close();
});
server.on('error', (error) => { native.close(); throw error; });
server.listen(port,'127.0.0.1',() => console.log('Filang study on http://127.0.0.1:' + port + '/ · ' + DATA));
