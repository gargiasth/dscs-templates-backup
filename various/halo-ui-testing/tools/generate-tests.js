/*
 * generate-tests.js  —  turn the Excel backlog into Playwright skeleton specs
 * ---------------------------------------------------------------------------
 * Reads the "Test backlog" sheet of backlog/playwright-test-backlog.xlsx (via
 * read-backlog.js) and writes one skeleton .spec.js per UI-testable row into
 * ./tests. Each skeleton carries the precondition / steps / expected as a
 * checklist, plus <<<CODEGEN>>> markers where a recording is spliced in.
 *
 * It does NOT produce a finished test. Selectors come from codegen; the
 * assertion is written by hand (or with a colleague). This tool builds the frame.
 *
 * RUN:  node tools/generate-tests.js                 (reads the .xlsx by default)
 *       node tools/generate-tests.js myfile.xlsx     (or a .csv export)
 *       node tools/generate-tests.js --all           (include every row, not just UI candidates)
 *       node tools/generate-tests.js --force         (overwrite recorded specs too)
 *
 * Already-recorded specs are left alone unless --force is passed.
 */

const fs = require('fs');
const path = require('path');
const { load, PROJECT_ROOT } = require('./read-backlog');

function jsSafe(s){ return String(s).replace(/[\\`$]/g,'\\$&'); }

function isRecorded(filePath) {
  if (!fs.existsSync(filePath)) return false;
  const src = fs.readFileSync(filePath, 'utf8');
  const mt = src.match(/\/\/ <<<CODEGEN>>>\n([\s\S]*?)\n\s*\/\/ <<<END CODEGEN>>>/);
  const body = (mt ? mt[1] : '').trim();
  return Boolean(body && !body.startsWith('// TODO'));
}

const args = process.argv.slice(2);
const includeAll = args.includes('--all');
const force = args.includes('--force');
const file = args.find(a => !a.startsWith('--'));

const { error, cases } = load(file);
if (error) { console.error(error); process.exit(1); }

const outDir = path.join(PROJECT_ROOT, 'tests');
fs.mkdirSync(outDir, { recursive: true });

let written = 0, skipped = 0, preserved = 0;
for (const c of cases) {
  if (!includeAll && !c.uiCandidate) { skipped++; continue; }
  const dest = path.join(outDir, c.file);
  if (!force && isRecorded(dest)) { preserved++; continue; }

  const title = c.desc.split('.')[0].slice(0, 70) || `${c.id} check`;
  const preLine  = c.pre   ? `//   Precondition: ${c.pre}`   : `//   Precondition: TODO — describe where the test must start`;
  const stepLine = c.steps ? `//   Steps: ${c.steps}`         : `//   Steps: TODO — list exactly what to click / type`;
  const expLine  = c.exp   ? `//   Expected: ${c.exp}`        : `//   Expected: TODO — what on screen proves the fix held`;

  const out = `// ${c.id} (${c.code}) — skeleton. Recorded clicks go between the CODEGEN markers.
// Area: ${c.area} | Product: ${c.product}
// ${jsSafe(c.desc)}
//
${preLine}
${stepLine}
${expLine}
//
// The last section is the pass/fail check. Recording does not write that line —
// pair with a colleague to replace the placeholder assertion. See docs/learning-path.md.

import { test, expect } from '@playwright/test';

test('${c.id} (${c.code}): ${jsSafe(title)}', async ({ page }) => {
  // Opens the App URL from config.json (or APP_URL). Change it in the control panel.
  await page.goto('/');

  // --- Recorded clicks / typing --------------------------------------------
  // <<<CODEGEN>>>
  // TODO(codegen): the recorded clicks/typing go here
  // <<<END CODEGEN>>>

  // --- Pass/fail check (assertion) -----------------------------------------
  // Replace this with a real check of the Expected result, for example:
  //   await expect(page.getByRole('heading', { name: 'the heading you expect' })).toBeVisible();
  expect(true, 'assertion not written yet — see docs/learning-path.md').toBeTruthy();
});
`;
  fs.writeFileSync(dest, out, 'utf8');
  written++;
}

console.log(`Generated ${written} skeleton spec(s) in ./tests  (${skipped} non-UI rows skipped, ${preserved} recorded spec(s) kept).`);
