/*
 * record-case.js  —  record ONE test case with codegen and splice it in
 * --------------------------------------------------------------------
 * Headless single-case version of the launcher: no server, no dropdown. Given a
 * Test ID, it launches codegen against the app, waits while you perform the
 * steps, then splices the recording into that case's skeleton between the
 * <<<CODEGEN>>> markers. The Streamlit control panel calls this per case, and
 * it also works on its own.
 *
 *   node tools/record-case.js GDC-005 --url https://your-web-app.example/
 *   (--url, APP_URL, HALO_URL, or config.json appUrl — in that order)
 */

const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const { load, PROJECT_ROOT, DEFAULT_BACKLOG } = require('./read-backlog');
const { requireAppUrl } = require('./app-config');

const TESTS_DIR = path.join(PROJECT_ROOT, 'tests');

function extractBody(recorded) {
  const lines = recorded.replace(/\r\n/g, '\n').split('\n');
  const start = lines.findIndex(l => /async\s*\(\s*\{\s*page/.test(l) && /=>\s*\{/.test(l));
  if (start === -1) return null;
  let end = -1;
  for (let i = lines.length - 1; i > start; i--) { if (/^\s*\}\s*\)\s*;?\s*$/.test(lines[i])) { end = i; break; } }
  if (end === -1) return null;
  return lines.slice(start + 1, end)
    .filter(l => !/await\s+page\.goto\(/.test(l))
    .map(l => l.replace(/\s+$/, ''))
    .filter(l => l.trim().length)
    .join('\n');
}

function spliceIntoSkeleton(file, body) {
  const p = path.join(TESTS_DIR, file);
  if (!fs.existsSync(p)) return { ok: false, msg: `Skeleton not found: tests/${file}. Generate skeletons first.` };
  const src = fs.readFileSync(p, 'utf8');
  const re = /(\/\/ <<<CODEGEN>>>\n)([\s\S]*?)(\n\s*\/\/ <<<END CODEGEN>>>)/;
  if (!re.test(src)) return { ok: false, msg: `Markers not found in tests/${file}. Regenerate skeletons.` };
  const indented = body.split('\n').map(l => l.length ? '  ' + l.replace(/^\s+/, '') : l).join('\n');
  fs.writeFileSync(p, src.replace(re, `$1${indented}$3`), 'utf8');
  return { ok: true, msg: `Recording mapped into tests/${file}.` };
}

function recordCase(caseObj, url) {
  return new Promise(resolve => {
    fs.mkdirSync(TESTS_DIR, { recursive: true });
    const tmp = path.join(TESTS_DIR, `.codegen-tmp-${caseObj.id}.js`);
    try { if (fs.existsSync(tmp)) fs.unlinkSync(tmp); } catch {}
    const child = spawn('npx', ['playwright', 'codegen', '--output', tmp, url], { shell: true, stdio: 'inherit', cwd: PROJECT_ROOT });
    child.on('error', err => resolve({ ok: false, msg: `Could not launch codegen: ${err.message}` }));
    child.on('close', () => {
      if (!fs.existsSync(tmp)) return resolve({ ok: false, msg: 'Codegen closed with no recording saved.' });
      const body = extractBody(fs.readFileSync(tmp, 'utf8'));
      try { fs.unlinkSync(tmp); } catch {}
      if (!body) return resolve({ ok: false, msg: 'Could not parse the recording (unexpected codegen format).' });
      resolve(spliceIntoSkeleton(caseObj.file, body));
    });
  });
}

async function main() {
  const args = process.argv.slice(2);
  const id = args.find(a => !a.startsWith('--'));
  const opt = (f, d) => { const i = args.indexOf(f); return i >= 0 ? args[i + 1] : d; };
  const backlog = opt('--backlog', process.env.BACKLOG || DEFAULT_BACKLOG);
  let url;
  try { url = requireAppUrl(opt('--url')); }
  catch (e) { console.error(e.message); process.exit(1); }
  if (!id) { console.error('Usage: node tools/record-case.js <TestID> [--backlog x.xlsx] [--url https://...]'); process.exit(2); }

  const { byId, error } = load(backlog);
  if (error) { console.error(error); process.exit(1); }
  const c = byId[id];
  if (!c) { console.error(`Test ID "${id}" not found in ${backlog}.`); process.exit(1); }

  const res = await recordCase(c, url);
  console.log(res.msg);
  process.exit(res.ok ? 0 : 1);
}

if (require.main === module) main();
module.exports = { extractBody, spliceIntoSkeleton };
