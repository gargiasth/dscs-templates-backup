import { test, expect } from '@playwright/test';
import { writeFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';

// Suite 0 — Smoke (docs/TEST-PLAN.md). Role-agnostic: runs in local dev or
// against a deployed app. Only asserts surfaces that do not depend on role,
// because `Steward Queue` and `Audit` share the same `isSteward` gate
// (client/src/App.tsx L607-616) and are covered by the role-aware suites.

let testArtifactsDir: string;
let consoleLogs: string[] = [];
let consoleErrors: string[] = [];
let pageErrors: string[] = [];
let failedRequests: string[] = [];

// SMOKE-01
test('smoke - app loads and displays home page', async ({ page }) => {
  await page.goto('/');

  await expect(page.getByText('Axle Data Export Portal').first()).toBeVisible();
  await expect(page.getByText('How it works')).toBeVisible();
});

// SMOKE-02 — role-agnostic nav links only.
test('smoke - core navigation renders', async ({ page }) => {
  await page.goto('/');
  const nav = page.locator('header').getByRole('navigation');
  await expect(nav.getByRole('link', { name: 'Home' })).toBeVisible();
  await expect(nav.getByRole('link', { name: 'Submit Request' }).first()).toBeVisible();
  await expect(nav.getByRole('link', { name: 'My Requests' })).toBeVisible();
  await expect(nav.getByRole('link', { name: 'About' })).toBeVisible();
  // NOTE: `Steward Queue` and `Audit` are steward-gated; asserted in shared.spec.ts.
});

// SMOKE-03
test('smoke - about page loads', async ({ page }) => {
  await page.goto('/about');
  await expect(page.getByRole('heading', { name: 'Axle Data Export Portal' })).toBeVisible();
  await expect(page.getByText('What this demonstrates')).toBeVisible();
});

// ── Lifecycle hooks (capture console/page errors + screenshots) ──────────────

test.beforeEach(async ({ page }) => {
  consoleLogs = [];
  consoleErrors = [];
  pageErrors = [];
  failedRequests = [];

  testArtifactsDir = join(process.cwd(), '.smoke-test');
  mkdirSync(testArtifactsDir, { recursive: true });

  page.on('console', (msg) => {
    const type = msg.type();
    const text = msg.text();
    if (!text.trim() || /^%[osd]$/.test(text.trim())) return;
    const location = msg.location();
    const locationStr = location.url ? ` at ${location.url}:${location.lineNumber}:${location.columnNumber}` : '';
    consoleLogs.push(`[${type}] ${text}${locationStr}`);
    if (type === 'error') consoleErrors.push(`${text}${locationStr}`);
  });

  page.on('pageerror', (error) => {
    pageErrors.push(`Page error: ${error.message}\nStack: ${error.stack || 'No stack trace available'}`);
  });

  page.on('requestfailed', (request) => {
    failedRequests.push(`Failed request: ${request.url()} - ${request.failure()?.errorText}`);
  });
});

test.afterEach(async ({ page }, testInfo) => {
  const testName = testInfo.title.replace(/ /g, '-').toLowerCase();
  const screenshotPath = join(testArtifactsDir, `${testName}-app-screenshot.png`);
  await page.screenshot({ path: screenshotPath, fullPage: true });

  const logsPath = join(testArtifactsDir, `${testName}-console-logs.txt`);
  const allLogs = [
    '=== Console Logs ===',
    ...consoleLogs,
    '\n=== Console Errors (React errors) ===',
    ...consoleErrors,
    '\n=== Page Errors ===',
    ...pageErrors,
    '\n=== Failed Requests ===',
    ...failedRequests,
  ];
  writeFileSync(logsPath, allLogs.join('\n'), 'utf-8');

  await page.close();
});
