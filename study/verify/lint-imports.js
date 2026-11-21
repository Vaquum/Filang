// Lists imported names that a module never uses (tidiness aid). Usage: node verify/lint-imports.js
import fs from 'node:fs';
import path from 'node:path';
import { ROOT } from './node-env.js';

const files = ['src/app.js', 'src/ui/guided.js', 'src/ui/chart.js', 'src/ui/dom.js', 'src/lang.js', 'src/check.js', 'src/engine.js', 'src/diff.js',
  'src/data.js', 'src/num.js', 'src/registry.js', 'src/assist.js', 'src/boot.js', 'src/coverage.js', 'src/conformance.js', 'src/examples.js'];
let n = 0;
for (const f of files) {
  const src = fs.readFileSync(path.join(ROOT, f), 'utf8');
  const body = src.split('\n').filter((l) => !l.startsWith('import ')).join('\n');
  for (const m of src.matchAll(/^import \{([^}]+)\} from '([^']+)'/gm)) {
    for (const name of m[1].split(',').map((x) => x.trim()).filter(Boolean)) {
      if (!new RegExp(`(^|[^\\w$.])${name}([^\\w$]|$)`).test(body)) { console.log(`${f}: unused import ${name} (from ${m[2]})`); n++; }
    }
  }
}
console.log(n ? `${n} unused imports` : 'no unused imports');
