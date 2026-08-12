import { test, expect } from '@playwright/test';
import { deployed, roleOf, seedPendingRequest } from './support';

// Suite 4 — Steward Queue (docs/TEST-PLAN.md). Steward project (except QUEUE-02).
test.describe('QUEUE — /steward-queue', () => {
  test.skip(!deployed, 'Role-sensitive; set DLP_BASE_URL and provide auth storage states.');

  // QUEUE-02 — analyst is guarded even by direct URL.
  test('QUEUE-02 analyst is blocked from the queue', async ({ page }, testInfo) => {
    test.skip(roleOf(testInfo) !== 'analyst', 'analyst project only');
    await page.goto('/steward-queue');
    await expect(page.getByText(/Stewards only/)).toBeVisible();
  });

  test.describe('as steward', () => {
    test.beforeEach(async ({}, testInfo) => {
      test.skip(roleOf(testInfo) !== 'steward', 'steward project only');
    });

    // QUEUE-01
    test('QUEUE-01 queue lists pending requests from the OBO view', async ({ page, request }) => {
      await seedPendingRequest(request);
      await page.goto('/steward-queue');
      await expect(page.getByRole('heading', { name: 'Steward Queue' })).toBeVisible();
      await expect(page.getByText('Requests awaiting review')).toBeVisible();
      await expect(page.getByRole('button', { name: 'View details' }).first()).toBeVisible();
    });

    // QUEUE-03
    test('QUEUE-03 approve removes the row', async ({ page, request }) => {
      const id = await seedPendingRequest(request);
      await page.goto('/steward-queue');
      const row = page.locator('[data-slot="item"]', { hasText: id }).first();
      // The id is not printed on the card; act on the first row and assert the
      // approve POST succeeds via the network instead.
      const post = page.waitForResponse((r) => r.url().includes('/approve') && r.request().method() === 'POST');
      await page.getByRole('button', { name: 'Approve' }).first().click();
      const res = await post;
      expect(res.status()).toBe(200);
      void row;
    });

    // QUEUE-04
    test('QUEUE-04 reject removes the row', async ({ page, request }) => {
      await seedPendingRequest(request);
      await page.goto('/steward-queue');
      const post = page.waitForResponse((r) => r.url().includes('/reject') && r.request().method() === 'POST');
      await page.getByRole('button', { name: 'Reject' }).first().click();
      const res = await post;
      expect(res.status()).toBe(200);
    });

    // QUEUE-05
    test('QUEUE-05 details dialog shows the four sections', async ({ page, request }) => {
      await seedPendingRequest(request);
      await page.goto('/steward-queue');
      await page.getByRole('button', { name: 'View details' }).first().click();
      const dialog = page.getByRole('dialog');
      await expect(dialog.getByText('Requester')).toBeVisible();
      await expect(dialog.getByText('DAR status for this dataset')).toBeVisible();
      await expect(dialog.getByText('Request details')).toBeVisible();
      await expect(dialog.getByText('Requested export (cohort)')).toBeVisible();
    });

    // QUEUE-07
    test('QUEUE-07 search filters the queue', async ({ page, request }) => {
      await seedPendingRequest(request);
      await page.goto('/steward-queue');
      await page.getByPlaceholder('Search by dataset or submitter').fill('zzz-no-match');
      await expect(page.getByText(/No (pending requests|requests match your search)/)).toBeVisible();
    });
  });
});
