/*
 * update-backlog-status.js  —  write run results back into the Excel backlog
 * --------------------------------------------------------------------------
 * Closes the loop inside the sheet itself. Reads the execution log written by
 * backlog-reporter.js (test-executions.csv), takes the LATEST result per Test
 * ID, and updates the backlog's Status column in place — matching on Test ID,
 * preserving the workbook's formatting, tabs, and dropdowns.
 *
 * Run it AFTER a test run (the Streamlit panel does this for you):
 *
 *   npx playwright test
 *   node tools/update-backlog-status.js
 *
 * Options:
 *   node tools/update-backlog-status.js [backlog.xlsx] [--log test-executions.csv]
 *                                 [--sheet "Test backlog"] [--no-color]
 *
 * Status mapping:  passed → Passing · failed/timedOut/interrupted → Needs fix
 *                  skipped → Skipped
 *
 * Note: close the workbook in Excel first — Excel locks the file and the save
 * will fail with the file open.
 */

const fs = require('fs');
const path = require('path');
const ExcelJS = require('exceljs');
const { PROJECT_ROOT, DEFAULT_BACKLOG, resolveBacklog } = require('./read-backlog');

const args = process.argv.slice(2);
const noColor = args.includes('--no-color');
const opt = (flag, def) => { const i = args.indexOf(flag); return i >= 0 ? args[i + 1] : def; };
const backlog = resolveBacklog(
  args.find(a => !a.startsWith('--') && a.toLowerCase().endsWith('.xlsx'))
  || process.env.BACKLOG || DEFAULT_BACKLOG
);
const logFile = path.resolve(PROJECT_ROOT, opt('--log', process.env.EXECUTIONS_LOG || 'test-executions.csv'));
const sheetName = opt('--sheet', process.env.BACKLOG_SHEET || 'Test backlog');

function parseCSV(text) {
  const rows = []; let row = [], f = '', i = 0, q = false;
  text = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  while (i < text.length) {
    const c = text[i];
    if (q) { if (c === '"' && text[i+1] === '"') { f += '"'; i += 2; continue; }
             if (c === '"') { q = false; i++; continue; } f += c; i++; continue; }
    if (c === '"') { q = true; i++; continue; }
    if (c === ',') { row.push(f); f = ''; i++; continue; }
    if (c === '\n') { row.push(f); rows.push(row); row = []; f = ''; i++; continue; }
    f += c; i++;
  }
  if (f.length || row.length) { row.push(f); rows.push(row); }
  return rows;
}

const STATUS_MAP = { passed:'Passing', failed:'Needs fix', timedOut:'Needs fix', interrupted:'Needs fix', skipped:'Skipped' };
const FILL = { 'Passing':'FFC6EFCE', 'Needs fix':'FFF8CBAD', 'Skipped':'FFF2F2F2' };

function latestByTestId(logPath) {
  if (!fs.existsSync(logPath)) throw new Error(`Execution log not found: ${logPath}. Run the tests first.`);
  const rows = parseCSV(fs.readFileSync(logPath, 'utf8'));
  const header = (rows.shift() || []).map(h => h.trim());
  const ci = n => header.findIndex(h => h.toLowerCase().startsWith(n.toLowerCase()));
  const iTs = ci('Run timestamp'), iId = ci('Test ID'), iSt = ci('Status');
  const latest = {};
  for (const r of rows) {
    const id = (r[iId] || '').trim(); if (!id) continue;
    const ts = r[iTs] || '';
    if (!latest[id] || ts > latest[id].ts) latest[id] = { ts, status: (r[iSt] || '').trim() };
  }
  return latest;
}

async function main() {
  if (!fs.existsSync(backlog)) { console.error(`Backlog not found: ${backlog}`); process.exit(1); }
  const latest = latestByTestId(logFile);

  const wb = new ExcelJS.Workbook();
  await wb.xlsx.readFile(backlog);
  const ws = wb.getWorksheet(sheetName);
  if (!ws) { console.error(`Sheet "${sheetName}" not found in ${backlog}.`); process.exit(1); }

  const headerRow = ws.getRow(1);
  let idCol = 0, statusCol = 0, lastRunCol = 0, maxCol = 0;
  headerRow.eachCell((cell, col) => {
    maxCol = Math.max(maxCol, col);
    const h = String(cell.value || '').toLowerCase();
    if (h.startsWith('test id')) idCol = col;
    else if (h.startsWith('status')) statusCol = col;
    else if (h.startsWith('last run')) lastRunCol = col;
  });
  if (!idCol || !statusCol) { console.error('Could not find "Test ID" and/or "Status" columns in the header row.'); process.exit(1); }

  if (!lastRunCol) {
    lastRunCol = maxCol + 1;
    const src = headerRow.getCell(statusCol);
    const dst = headerRow.getCell(lastRunCol);
    dst.value = 'Last run (auto)';
    dst.style = JSON.parse(JSON.stringify(src.style));
    ws.getColumn(lastRunCol).width = 22;
  }

  const stamp = new Date().toISOString().slice(0, 16).replace('T', ' ');
  let updated = 0; const unmatched = [];
  const seen = new Set();

  ws.eachRow((row, rn) => {
    if (rn === 1) return;
    const id = String(row.getCell(idCol).value || '').trim();
    if (!id) return;
    seen.add(id);
    const res = latest[id];
    if (!res) return;
    const label = STATUS_MAP[res.status] || res.status || 'Unknown';
    const sc = row.getCell(statusCol);
    sc.value = label;
    if (!noColor && FILL[label]) {
      sc.style = { ...sc.style, fill: { type: 'pattern', pattern: 'solid', fgColor: { argb: FILL[label] } } };
    }
    row.getCell(lastRunCol).value = stamp;
    updated++;
  });

  for (const id of Object.keys(latest)) if (!seen.has(id)) unmatched.push(id);

  try {
    await wb.xlsx.writeFile(backlog);
  } catch (e) {
    console.error(`\nCould not save ${backlog}: ${e.message}`);
    console.error('If the file is open in Excel, close it and run this again.');
    process.exit(1);
  }

  console.log(`Updated ${updated} Status cell(s) in ${path.basename(backlog)} (sheet "${sheetName}").`);
  if (unmatched.length) console.log(`No matching row for ${unmatched.length} logged ID(s): ${unmatched.slice(0,10).join(', ')}${unmatched.length>10?'…':''}`);
}

main().catch(e => { console.error(e.message); process.exit(1); });
