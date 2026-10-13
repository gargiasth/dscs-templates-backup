import { test, expect } from '@playwright/test';
import { deployed, roleOf } from './support';

// Suite 5 — Audit (docs/TEST-PLAN.md). Steward project (except AUDIT-05).
test.describe('AUDIT — /audit', () => {
  test.skip(!deployed, 'Role-sensitive; set DLP_BASE_URL and provide auth storage states.');

  // AUDIT-05 — analyst guarded.
  test('AUDIT-05 analyst is blocked from audit', async ({ page }, testInfo) => {
    test.skip(roleOf(testInfo) !== 'analyst', 'analyst project only');
    await page.goto('/audit');
    await expect(page.getByText(/Stewards only/)).toBeVisible();
  });

  test.describe('as steward', () => {
    test.beforeEach(async ({ page }, testInfo) => {
      test.skip(roleOf(testInfo) !== 'steward', 'steward project only');
      await page.goto('/audit');
      await expect(page.getByRole('heading', { name: 'Audit Log' })).toBeVisible();
    });

    // AUDIT-01
    test('AUDIT-01 app-reported events table renders', async ({ page }) => {
      await expect(page.getByText('App-Reported Events')).toBeVisible();
      await expect(page.getByRole('columnheader', { name: 'Timestamp' })).toBeVisible();
      await expect(page.getByRole('columnheader', { name: 'Outcome' })).toBeVisible();
    });

    // AUDIT-02
    test('AUDIT-02 outcome filter narrows events', async ({ page }) => {
      await page.getByPlaceholder('Search by user, action, or resource').fill('submit');
      await page.getByRole('combobox').first().click();
      await page.getByRole('option', { name: 'Submitted' }).click();
      await expect(page.getByRole('heading', { name: 'Audit Log' })).toBeVisible();
    });

    // AUDIT-04
    test('AUDIT-04 platform audit panel is present for stewards', async ({ page }) => {
      await expect(page.getByText('Platform Audit Log')).toBeVisible();
      await expect(page.getByText('Platform log may lag several minutes.')).toBeVisible();
    });

    // AUDIT-06
    test('AUDIT-06 scope-limit note present', async ({ page }) => {
      await expect(page.getByText('Scope of this layer')).toBeVisible();
    });
  });
});
