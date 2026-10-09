import { expect, type APIRequestContext, type Locator, type Page, type TestInfo } from '@playwright/test';

/**
 * Shared helpers for the Playwright suites generated from docs/TEST-PLAN.md.
 * Locators and expected strings are sourced from client/src/App.tsx and route
 * behavior from server/server.ts.
 */

// Deployed, per-user auth mode. Role-sensitive specs require this; in local dev
// every caller shares one ambient identity, so those specs skip themselves.
export const deployed = !!process.env.DLP_BASE_URL;

// A per-run marker so requests/audit rows created by tests are identifiable and
// can be cleaned up externally by SQL (see docs/TEST-PLAN.md §0.4).
export const RUN_ID = process.env.DLP_RUN_ID || `local-${Date.now()}`;

// Seeded datasets (docs/TEST-PLAN.md §0.3). Override per workspace via env.
export const DATASETS = {
  granted: process.env.DLP_GRANTED_DATASET || 'phs000298',
  denied: process.env.DLP_DENIED_DATASET || 'phs000710',
  open: process.env.DLP_OPEN_DATASET || '',
  unregistered: process.env.DLP_UNREGISTERED_DATASET || '',
};

export type Role = 'analyst' | 'steward';

export function roleOf(testInfo: TestInfo): Role {
  return testInfo.project.name === 'steward' ? 'steward' : 'analyst';
}

/** Build a justification carrying the run marker (>=12 chars). */
export function mark(text: string): string {
  return `e2e ${RUN_ID}: ${text}`;
}

/** The header identity badge scope — avoids matching "Steward"/"Analyst" text elsewhere. */
export function identityBadge(page: Page): Locator {
  return page.locator('header');
}

/** Header navigation link by visible name. */
export function navLink(page: Page, name: string): Locator {
  return page.locator('header').getByRole('link', { name });
}

/**
 * Open a Radix Select (by its associated label) and choose an option whose
 * accessible name matches `optionName`.
 */
export async function selectOption(page: Page, label: string | RegExp, optionName: string | RegExp) {
  await page.getByLabel(label).click();
  await page.getByRole('option', { name: optionName }).click();
}

/** POST a new export request via the API (submitter is derived server-side). */
export async function createExportRequest(
  request: APIRequestContext,
  dataset: string,
  justification: string,
) {
  return request.post('/api/export_requests', {
    data: { dataset, justification },
    headers: { 'Content-Type': 'application/json' },
  });
}

/** Approve/reject an export request via the API. */
export async function actOnRequest(
  request: APIRequestContext,
  id: string,
  kind: 'approve' | 'reject',
  comment = '',
) {
  return request.post(`/api/export_requests/${id}/${kind}`, {
    data: { comment },
    headers: { 'Content-Type': 'application/json' },
  });
}

/** Create a pending request and return its id, failing loudly if the seed is wrong. */
export async function seedPendingRequest(request: APIRequestContext, dataset = DATASETS.granted): Promise<string> {
  const res = await createExportRequest(request, dataset, mark('seed pending'));
  expect(res.status(), 'seed request should be granted+created (check DLP_GRANTED_DATASET seed)').toBe(201);
  const body = await res.json();
  return String(body.id);
}
