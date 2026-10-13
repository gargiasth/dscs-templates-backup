/*
 * backlog-reporter.js  —  logs each test run back against the Excel backlog
 * ------------------------------------------------------------------------
 * The write-back half of the loop. After a `npx playwright test` run, it takes
 * each result, reads the Test ID from the spec's title (e.g. "GDC-001 (HP-01): …"),
 * enriches it from the backlog sheet, and appends one row per execution to
 * test-executions.csv — the run log that stands in for a TCMS's execution store.
 *
 * The backlog sheet itself is never modified by this reporter: it is the
 * test-CASE store. Executions accumulate separately. Status cells in Excel are
 * updated later by update-backlog-status.js.
 *
 * Wire it up in playwright.config.js:
 *   reporter: [['list'], ['html', { open: 'never' }], ['./tools/backlog-reporter.js']]
 */

const fs = require('fs');
const path = require('path');
const { load, PROJECT_ROOT } = require('./read-backlog');

const OUT = process.env.EXECUTIONS_LOG
  ? path.resolve(PROJECT_ROOT, process.env.EXECUTIONS_LOG)
  : path.join(PROJECT_ROOT, 'test-executions.csv');
const HEADER = ['Run timestamp','Test ID','Indica code','Area','Status','Duration (s)','Spec file','Browser','Error','Trace','Bug description'];

function q(v){ v = v == null ? '' : String(v); return /[",\n]/.test(v) ? '"' + v.replace(/"/g,'""') + '"' : v; }

class BacklogReporter {
  constructor() { this.rows = []; this.byId = {}; }

  onBegin() {
    try { this.byId = load().byId || {}; } catch { this.byId = {}; }
  }

  onTestEnd(test, result) {
    const m = test.title.match(/\b([A-Z]{2,}-\d+)\b/);
    const id = m ? m[1] : '';
    const c = this.byId[id] || {};
    const trace = (result.attachments || []).find(a => a.name === 'trace');
    this.rows.push([
      new Date().toISOString(),
      id,
      c.code || '',
      c.area || '',
      result.status,                         // passed | failed | timedOut | skipped
      (result.duration / 1000).toFixed(1),
      path.basename(test.location ? test.location.file : ''),
      (test.parent && test.parent.project && test.parent.project().name) || '',
      result.error ? (result.error.message || '').split('\n')[0].slice(0, 300) : '',
      trace ? trace.path : '',
      c.desc || '',
    ]);
  }

  onEnd(result) {
    const exists = fs.existsSync(OUT);
    const lines = [];
    if (!exists) lines.push(HEADER.map(q).join(','));
    for (const r of this.rows) lines.push(r.map(q).join(','));
    fs.appendFileSync(OUT, lines.join('\n') + '\n', 'utf8');

    const pass = this.rows.filter(r => r[4] === 'passed').length;
    const fail = this.rows.length - pass;
    const unmapped = this.rows.filter(r => !r[1]).length;
    console.log(`\n[backlog-reporter] ${this.rows.length} execution(s) → ${OUT}  (${pass} passed, ${fail} not passed` +
      (unmapped ? `, ${unmapped} with no Test ID in the title` : '') + `)`);
    console.log(`[backlog-reporter] overall run status: ${result.status}`);
  }
}

module.exports = BacklogReporter;
