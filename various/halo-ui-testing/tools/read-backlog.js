/*
 * read-backlog.js  —  the Excel backlog as the test-case store (TCMS stand-in)
 * ---------------------------------------------------------------------------
 * Reads the "Test backlog" sheet from backlog/playwright-test-backlog.xlsx and
 * returns the test cases. Shared by the record/generate tools and the reporter,
 * so everything reads one source of truth.
 *
 * .xlsx needs the SheetJS package:  npm install xlsx
 * A .csv path is also accepted and parsed with zero dependencies.
 */

const fs = require('fs');
const path = require('path');

const PROJECT_ROOT = path.join(__dirname, '..');
const DEFAULT_BACKLOG = path.join(PROJECT_ROOT, 'backlog', 'playwright-test-backlog.xlsx');
const SHEET = process.env.BACKLOG_SHEET || 'Test backlog';
const GEN_OK = ['web ui - good candidate', 'web ui - needs sample images'];

function slug(s){return String(s).toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-+|-+$/g,'').slice(0,60);}

function resolveBacklog(file) {
  if (!file) file = process.env.BACKLOG || DEFAULT_BACKLOG;
  if (!path.isAbsolute(file)) file = path.join(PROJECT_ROOT, file);
  return file;
}

function parseCSV(text) {
  const rows = []; let row = [], field = '', i = 0, inQ = false;
  text = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  while (i < text.length) {
    const c = text[i];
    if (inQ) {
      if (c === '"' && text[i + 1] === '"') { field += '"'; i += 2; continue; }
      if (c === '"') { inQ = false; i++; continue; }
      field += c; i++; continue;
    }
    if (c === '"') { inQ = true; i++; continue; }
    if (c === ',') { row.push(field); field = ''; i += 1; continue; }
    if (c === '\n') { row.push(field); rows.push(row); row = []; field = ''; i += 1; continue; }
    field += c; i++;
  }
  if (field.length || row.length) { row.push(field); rows.push(row); }
  return rows;
}

function rowsFromXlsx(file) {
  let XLSX;
  try { XLSX = require('xlsx'); }
  catch { throw new Error("Reading .xlsx needs SheetJS. Run:  npm install xlsx   (or point at a .csv export instead)."); }
  const wb = XLSX.readFile(file);
  const ws = wb.Sheets[SHEET] || wb.Sheets[wb.SheetNames[0]];
  if (!ws) throw new Error(`Sheet "${SHEET}" not found in ${file}.`);
  return XLSX.utils.sheet_to_json(ws, { header: 1, blankrows: false, defval: '' })
    .map(r => r.map(c => (c == null ? '' : String(c))));
}

function load(file) {
  file = resolveBacklog(file);
  if (!fs.existsSync(file)) return { error: `Cannot find ${file}.`, cases: [], byId: {} };

  let rows;
  try { rows = file.toLowerCase().endsWith('.csv') ? parseCSV(fs.readFileSync(file, 'utf8')) : rowsFromXlsx(file); }
  catch (e) { return { error: e.message, cases: [], byId: {} }; }

  const header = (rows.shift() || []).map(h => String(h).trim());
  // Accept a few header synonyms so any backlog works: the original HALO names
  // ('Indica code', 'Bug / fix description') and the cleaner names used for a
  // fresh site ('Ref', 'Behaviour to verify' / 'Test case' / 'Description').
  const col = (...names) => {
    for (const n of names) {
      const i = header.findIndex(h => h.toLowerCase().startsWith(n.toLowerCase()));
      if (i >= 0) return i;
    }
    return -1;
  };
  const idx = {
    id:col('Test ID'), code:col('Indica code', 'Ref'), product:col('Product'), area:col('Area'),
    test:col('Testability'), prio:col('Priority'),
    desc:col('Bug', 'Behaviour', 'Test case', 'Description'), vers:col('Seen in', 'App version'),
    pre:col('Precondition'), steps:col('Steps'), exp:col('Expected'), status:col('Status'),
  };
  const cases = [];
  for (const r of rows) {
    const id = (r[idx.id] || '').trim();
    if (!id) continue;
    const code = (r[idx.code] || 'nocode').trim();
    const testability = (r[idx.test] || '').trim().toLowerCase();
    cases.push({
      id, code,
      product: r[idx.product] || '', area: r[idx.area] || '',
      testability: r[idx.test] || '', priority: r[idx.prio] || '',
      desc: (r[idx.desc] || '').trim(), versions: r[idx.vers] || '',
      pre: (r[idx.pre] || '').trim(), steps: (r[idx.steps] || '').trim(),
      exp: (r[idx.exp] || '').trim(), status: r[idx.status] || '',
      uiCandidate: GEN_OK.includes(testability),
      file: `${id}.spec.js`,
    });
  }
  const byId = cases.reduce((a, c) => (a[c.id] = c, a), {});
  return { cases, byId, source: file };
}

module.exports = { load, slug, PROJECT_ROOT, DEFAULT_BACKLOG, resolveBacklog };
