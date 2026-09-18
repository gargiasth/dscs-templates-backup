import { test, expect } from '@playwright/test';
import { deployed, navLink, roleOf } from './support';

// Suite 1 — Shared UI, identity & route guards (docs/TEST-PLAN.md).
// Role-sensitive: requires deployed per-user auth.
test.describe('SHARED — identity & route guards', () => {
  test.skip(!deployed, 'Role-sensitive; set DLP_BASE_URL and provide auth storage states.');

  // SHARED-01
  test('SHARED-01 identity badge shows the signed-in user, no role switcher', async ({ page }, testInfo) => {
    await page.goto('/');
    const header = page.locator('header');
    await expect(header.getByText('@')).toBeVisible();
    const pill = roleOf(testInfo) === 'steward' ? 'Steward' : 'Analyst';
    await expect(header.getByText(pill, { exact: true })).toBeVisible();
    // No user picker / role dropdown anywhere in the header.
    await expect(header.getByRole('combobox')).toHaveCount(0);
  });

  // SHARED-02
  test('SHARED-02 steward badge + steward nav links', async ({ page }, testInfo) => {
    test.skip(roleOf(testInfo) !== 'steward', 'steward project only');
    await page.goto('/');
    await expect(page.locator('header').getByText('Steward', { exact: true })).toBeVisible();
    await expect(navLink(page, 'Steward Queue')).toBeVisible();
    await expect(navLink(page, 'Audit')).toBeVisible();
  });

  // SHARED-03
  test('SHARED-03 analyst badge, steward links hidden', async ({ page }, testInfo) => {
    test.skip(roleOf(testInfo) !== 'analyst', 'analyst project only');
    await page.goto('/');
    await expect(page.locator('header').getByText('Analyst', { exact: true })).toBeVisible();
    await expect(navLink(page, 'Steward Queue')).toHaveCount(0);
    await expect(navLink(page, 'Audit')).toHaveCount(0);
  });

  // SHARED-04
  test('SHARED-04 analyst is guarded from /steward-queue', async ({ page }, testInfo) => {
    test.skip(roleOf(testInfo) !== 'analyst', 'analyst project only');
    await page.goto('/steward-queue');
    await expect(page.getByText(/Stewards only/)).toBeVisible();
  });

  // SHARED-05
  test('SHARED-05 analyst is guarded from /audit', async ({ page }, testInfo) => {
    test.skip(roleOf(testInfo) !== 'analyst', 'analyst project only');
    await page.goto('/audit');
    await expect(page.getByText(/Stewards only/)).toBeVisible();
  });

  // SHARED-06
  test('SHARED-06 steward can open both guarded pages', async ({ page }, testInfo) => {
    test.skip(roleOf(testInfo) !== 'steward', 'steward project only');
    await page.goto('/steward-queue');
    await expect(page.getByRole('heading', { name: 'Steward Queue' })).toBeVisible();
    await page.goto('/audit');
    await expect(page.getByRole('heading', { name: 'Audit Log' })).toBeVisible();
  });

  // SHARED-07
  test('SHARED-07 no client-side identity state', async ({ page }) => {
    await page.goto('/');
    const keys = await page.evaluate(() => Object.keys(window.localStorage));
    expect(keys).not.toContain('dlp_user');
    expect(keys).not.toContain('dlp_role');
  });

  // SHARED-09
  test('SHARED-09 home menu collapse toggles', async ({ page }) => {
    await page.goto('/');
    const collapse = page.getByRole('button', { name: 'Collapse menu' });
    await expect(collapse).toBeVisible();
    await collapse.click();
    await expect(page.getByRole('button', { name: 'Expand menu' })).toBeVisible();
  });
});

// SHARED-08 — responsive navigation (mobile viewport).
test.describe('SHARED — mobile navigation', () => {
  test.skip(!deployed, 'Role-sensitive; set DLP_BASE_URL and provide auth storage states.');
  test.use({ viewport: { width: 390, height: 844 } });

  test('SHARED-08 mobile sheet exposes navigation', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: 'Open navigation' }).click();
    await expect(page.getByRole('dialog').getByText('Navigation')).toBeVisible();
    await expect(page.getByRole('dialog').getByRole('link', { name: 'Home' })).toBeVisible();
  });
});
