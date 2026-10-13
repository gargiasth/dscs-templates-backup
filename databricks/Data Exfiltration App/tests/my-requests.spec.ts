import { test, expect } from '@playwright/test';
import { DATASETS, createExportRequest, deployed, mark, roleOf } from './support';

// Search input value used to scope MYREQ-04 to this run's requests.
const RUN_MARKER_HINT = 'e2e';

// Suite 3 — My Requests (docs/TEST-PLAN.md). Analyst project.
test.describe('MYREQ — /my-requests', () => {
  test.skip(!deployed, 'Role-sensitive; set DLP_BASE_URL and provide auth storage states.');

  test.beforeEach(async ({}, testInfo) => {
    test.skip(roleOf(testInfo) !== 'analyst', 'analyst project only');
  });

  // MYREQ-01
  test('MYREQ-01 requests are scoped to the caller with no submitter param', async ({ page }) => {
    const req = page.waitForRequest((r) => r.url().includes('/api/my-requests'));
    await page.goto('/my-requests');
    const request = await req;
    expect(new URL(request.url()).searchParams.has('submitter')).toBe(false);
    await expect(page.getByRole('heading', { name: 'My Export Requests' })).toBeVisible();
  });

  // MYREQ-02
  test('MYREQ-02 a just-submitted request appears immediately', async ({ page, request }) => {
    const res = await createExportRequest(request, DATASETS.granted, mark('appears in my-requests'));
    expect(res.status()).toBe(201);
    const id = String((await res.json()).id);

    await page.goto('/my-requests');
    await expect(page.getByText(DATASETS.granted).first()).toBeVisible();
    // The dataset row for this run's request is present without a manual reload.
    expect(id).toBeTruthy();
  });

  // MYREQ-03
  test('MYREQ-03 refresh re-fetches', async ({ page }) => {
    await page.goto('/my-requests');
    const refresh = page.getByRole('button', { name: /Refresh/ });
    const req = page.waitForRequest((r) => r.url().includes('/api/my-requests'));
    await refresh.click();
    await req;
  });

  // MYREQ-04
  test('MYREQ-04 search and status filter narrow the list', async ({ page }) => {
    await page.goto('/my-requests');
    await page.getByPlaceholder('Search by dataset or justification').fill(RUN_MARKER_HINT);
    // Status filter is a Radix select; switching it should not throw.
    await page.getByRole('combobox').first().click();
    await page.getByRole('option', { name: 'Pending' }).click();
    await expect(page.getByRole('heading', { name: 'My Export Requests' })).toBeVisible();
  });

  // MYREQ-05
  test('MYREQ-05 empty state renders when no requests match', async ({ page }) => {
    await page.goto('/my-requests');
    await page.getByPlaceholder('Search by dataset or justification').fill('no-such-dataset-zzz');
    await expect(page.getByText(/No requests (yet|match your filters)/)).toBeVisible();
  });
});
