import { test, expect } from '@playwright/test';
import { DATASETS, deployed, mark, roleOf, selectOption } from './support';

// Suite 2 — Submit Request (docs/TEST-PLAN.md). Analyst project.
test.describe('SUBMIT — /submit', () => {
  test.skip(!deployed, 'Role-sensitive; set DLP_BASE_URL and provide auth storage states.');

  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(roleOf(testInfo) !== 'analyst', 'analyst project only');
    await page.goto('/submit');
    await expect(page.getByRole('heading', { name: 'Submit Export Request' })).toBeVisible();
  });

  // SUBMIT-01
  test('SUBMIT-01 dataset dropdown lists catalog entries', async ({ page }) => {
    await page.getByLabel('Dataset').click();
    await expect(page.getByRole('option').first()).toBeVisible();
  });

  // SUBMIT-02
  test('SUBMIT-02 granted dataset enables submit', async ({ page }) => {
    await selectOption(page, 'Dataset', new RegExp(DATASETS.granted));
    await expect(page.getByText('Granted')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Submit' })).toBeEnabled();
  });

  // SUBMIT-03
  test('SUBMIT-03 denied dataset disables submit with inline message', async ({ page }) => {
    await selectOption(page, 'Dataset', new RegExp(DATASETS.denied));
    await expect(page.getByRole('button', { name: 'Submit' })).toBeDisabled();
    await expect(
      page.getByText('Access denied for this dataset — you cannot submit an export request.'),
    ).toBeVisible();
  });

  // SUBMIT-04
  test('SUBMIT-04 unregistered dataset is flagged for review', async ({ page }) => {
    test.skip(!DATASETS.unregistered, 'Set DLP_UNREGISTERED_DATASET to run.');
    await selectOption(page, 'Dataset', new RegExp(DATASETS.unregistered));
    await expect(page.getByText('Flagged')).toBeVisible();
  });

  // SUBMIT-05
  test('SUBMIT-05 client blocks short justification', async ({ page }) => {
    await selectOption(page, 'Dataset', new RegExp(DATASETS.granted));
    await page.getByLabel('Justification').fill('too short');
    await page.getByRole('button', { name: 'Submit' }).click();
    await expect(page.getByText('Please provide at least 12 characters of justification.')).toBeVisible();
  });

  // SUBMIT-06
  test('SUBMIT-06 successful submit returns a Query ID', async ({ page }) => {
    await selectOption(page, 'Dataset', new RegExp(DATASETS.granted));
    await page.getByLabel('Justification').fill(mark('successful submit'));

    const post = page.waitForResponse(
      (r) => r.url().includes('/api/export_requests') && r.request().method() === 'POST',
    );
    await page.getByRole('button', { name: 'Submit' }).click();
    const res = await post;
    expect(res.status()).toBe(201);
    // The client never sends a submitter field.
    expect(res.request().postDataJSON()).not.toHaveProperty('submitter');

    await expect(page.getByText('Request submitted successfully.')).toBeVisible();
    await expect(page.getByText('Request submitted — Query ID')).toBeVisible();
    await expect(page.getByRole('button', { name: /Copy/ })).toBeVisible();
  });

  // SUBMIT-07
  test('SUBMIT-07 Query ID copy button confirms', async ({ page, context }) => {
    await context.grantPermissions(['clipboard-read', 'clipboard-write']);
    await selectOption(page, 'Dataset', new RegExp(DATASETS.granted));
    await page.getByLabel('Justification').fill(mark('copy query id'));
    await page.getByRole('button', { name: 'Submit' }).click();
    await expect(page.getByText('Request submitted — Query ID')).toBeVisible();
    await page.getByRole('button', { name: /Copy/ }).click();
    await expect(page.getByRole('button', { name: 'Copied' })).toBeVisible();
  });

  // SUBMIT-08
  test('SUBMIT-08 granted dataset shows data-file preview', async ({ page }) => {
    await selectOption(page, 'Dataset', new RegExp(DATASETS.granted));
    await expect(page.getByText('Data files')).toBeVisible();
    // A dataset with source files exposes a File selector + row total.
    await expect(page.getByText(/Total rows:/)).toBeVisible();
  });

  // SUBMIT-10
  test('SUBMIT-10 no preview until a granted dataset is chosen', async ({ page }) => {
    await expect(page.getByText('Select a granted dataset to preview its data files here.')).toBeVisible();
  });
});
