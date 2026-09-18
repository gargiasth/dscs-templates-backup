# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: GDC-001_nocode.spec.js >> GDC-001 (nocode): GDC-001 check
- Location: tests/GDC-001_nocode.spec.js:20:5

# Error details

```
Test timeout of 30000ms exceeded.
```

```
Error: locator.click: Test timeout of 30000ms exceeded.
Call log:
  - waiting for getByTestId('button-intro-warning-accept')

```

# Test source

```ts
  1  | // AUTO-GENERATED SKELETON — do not treat as finished. GDC-001 (Indica nocode)
  2  | // Area: Branding / header | Product: GDC Data Portal (web) | Seen in: 
  3  | // Bug: 
  4  | //
  5  | //   Precondition: On the home page (https://portal.gdc.cancer.gov/).
  6  | //   Steps: Note the logo top-left. Click 'Projects' to leave home, then click the logo.
  7  | //   Expected: The GDC Data Portal logo is visible; clicking it loads the home page (URL is the portal root).
  8  | //
  9  | // TO COMPLETE THIS TEST:
  10 | //   1) record it (codegen launcher, or: npx playwright codegen %HALO_URL%)
  11 | //   2) the recorded actions land in the "Steps" block below
  12 | //   3) replace the placeholder assertion with a real check of the Expected result
  13 | //   4) npx playwright test tests/GDC-001_nocode.spec.js --project=chromium
  14 | //   5) verify visually:  npx playwright test --ui
  15 | 
  16 | import { test, expect } from '@playwright/test';
  17 | 
  18 | const BASE_URL = process.env.HALO_URL || 'https://portal.gdc.cancer.gov/';
  19 | 
  20 | test('GDC-001 (nocode): GDC-001 check', async ({ page }) => {
  21 |   // --- Precondition ---------------------------------------------------------
  22 |   await page.goto(BASE_URL);
  23 |   // TODO(codegen): log in and navigate to the starting screen described above
  24 | 
  25 |   // --- Steps (recorded actions go between the markers) ----------------------
  26 |   // <<<CODEGEN>>>
> 27 |   await page.getByTestId('button-intro-warning-accept').click();
     |                                                         ^ Error: locator.click: Test timeout of 30000ms exceeded.
  28 |   await page.getByTestId('button-header-projects').click();
  29 |   await expect(page.getByTestId('text-cohort-filters')).toBeVisible();
  30 |   await expect(page.getByTestId('text-cohort-filters')).toBeVisible();
  31 |   // <<<END CODEGEN>>>
  32 | 
  33 |   // --- Expected result ------------------------------------------------------
  34 |   // TODO(assert): replace the line below with a real check of the Expected result.
  35 |   //   await expect(page.getByRole('heading', { name: 'Case List' })).toBeVisible();
  36 |   expect(true, 'assertion not written yet — see TODO(assert)').toBeTruthy();
  37 | });
  38 | 
```