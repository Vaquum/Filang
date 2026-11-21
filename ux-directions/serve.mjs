// Static server for the Filang query bench prototype.
// Serves this folder, plus the study engine and its pinned recording read-only from the
// query-builder checkout, so the bench runs real Filang queries on the recorded tape.
import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { extname, join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = fileURLToPath(new URL('.', import.meta.url));
const STUDY = resolve(process.env.FILANG_STUDY || join(HERE, '../../filang-candle-relationships/study'));
const DATA = resolve(process.env.FILANG_STUDY_DATA || join(STUDY, '../data/study'));
const port = Number(process.env.PORT || process.argv[2] || 8790);

const mime = new Map([
  ['.html', 'text/html; charset=utf-8'], ['.css', 'text/css; charset=utf-8'],
  ['.js', 'text/javascript; charset=utf-8'], ['.mjs', 'text/javascript; charset=utf-8'],
  ['.json', 'application/json; charset=utf-8'], ['.csv', 'text/csv; charset=utf-8'],
  ['.svg', 'image/svg+xml'],
]);
const studyAsset = /^(?:(?:src|composer|extensions)\/(?:[\w.-]+\/)*[\w.-]+\.(?:js|json)|[\w-]+\.json)$/;

function locate(path) {
  if (path === 'study/recorded-bars.csv') return join(DATA, 'recorded-bars.csv');
  if (path.startsWith('study/')) {
    const rest = path.slice(6);
    return studyAsset.test(rest) ? join(STUDY, rest) : null;
  }
  const file = resolve(HERE, path);
  return file === HERE.replace(/\/$/, '') || file.startsWith(HERE.endsWith(sep) ? HERE : HERE + sep) ? file : null;
}

createServer(async (req, res) => {
  try {
    if (!['GET', 'HEAD'].includes(req.method)) { res.writeHead(405); return res.end(); }
    let path = decodeURIComponent(new URL(req.url, 'http://127.0.0.1').pathname).slice(1);
    if (path.split('/').some((s) => s === '..')) { res.writeHead(400); return res.end(); }
    let file = locate(path);
    if (file && !path.startsWith('study/')) {
      const info = await stat(file).catch(() => null);
      if (info?.isDirectory()) {
        if (path && !path.endsWith('/')) { res.writeHead(302, { Location: '/' + path + '/' }); return res.end(); }
        file = join(file, 'index.html');
      }
    }
    if (!file) { res.writeHead(404); return res.end('Not found'); }
    const body = await readFile(file);
    res.writeHead(200, { 'Content-Type': mime.get(extname(file)) || 'application/octet-stream', 'Cache-Control': 'no-cache' });
    res.end(req.method === 'HEAD' ? undefined : body);
  } catch (e) {
    res.writeHead(e.code === 'ENOENT' ? 404 : 500);
    res.end(e.code === 'ENOENT' ? 'Not found' : 'Server error');
    if (e.code !== 'ENOENT') console.error(e);
  }
}).listen(port, '127.0.0.1', () => console.log(`Filang query bench on http://127.0.0.1:${port}/ · engine ${STUDY}`));
