import { test, expect } from '@playwright/test';
import { randomUUID } from 'node:crypto';
import { DATASETS, actOnRequest, createExportRequest, deployed, mark, roleOf } from './support';

// Suite 6 — API authorization & contract (docs/TEST-PLAN.md).
// Uses the project's authenticated `request` fixture so calls traverse the
// proxy and inherit the caller's identity/OBO token.
test.describe('API — authorization & contract', () => {
  test.skip(!deployed, 'Auth-sensitive; set DLP_BASE_URL and provide auth storage states.');

  // ── 6.1 Identity & live reads ──────────────────────────────────────────────

  // API-01
  test('API-01 GET /api/me returns the forwarded user', async ({ request }) => {
    const res = await request.get('/api/me');
    expect(res.status()).toBe(200);
    expect((await res.json()).user).toContain('@');
  });

  // API-02 / API-03
  test('API-02/03 steward-queue is row-filtered by group', async ({ request }, testInfo) => {
    const res = await request.get('/api/steward-queue');
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(Array.isArray(body)).toBe(true);
    if (roleOf(testInfo) === 'analyst') {
      expect(body.length).toBe(0); // UC returns zero rows for non-stewards.
    }
  });

  // API-04
  test('API-04 my-requests is scoped to the caller', async ({ request }) => {
    const res = await request.get('/api/my-requests');
    expect(res.status()).toBe(200);
    expect(Array.isArray(await res.json())).toBe(true);
  });

  // API-05 / API-05b — no server-side steward gate on this route.
  test('API-05 platform-audit is not app-gated by role', async ({ request }) => {
    const res = await request.get('/api/platform-audit');
    // 200 (allowed by UC) or 500 (real UC access error) — never a 403 from the app.
    expect([200, 500]).toContain(res.status());
    expect(res.status()).not.toBe(403);
  });

  // ── 6.2 Create request ─────────────────────────────────────────────────────

  // API-06 / API-09 — submitter is derived server-side, body value ignored.
  test('API-06/09 create granted request derives submitter', async ({ request }) => {
    const res = await request.post('/api/export_requests', {
      data: { dataset: DATASETS.granted, justification: mark('api create'), submitter: 'someone.else@example.org' },
      headers: { 'Content-Type': 'application/json' },
    });
    expect(res.status()).toBe(201);
    const body = await res.json();
    expect(body.submitter).not.toBe('someone.else@example.org');
    expect(String(body.submitter)).toContain('@');
    expect(body.status).toBe('pending');
  });

  // API-07
  test('API-07 create denied request is blocked', async ({ request }, testInfo) => {
    test.skip(roleOf(testInfo) !== 'analyst', 'run as an account denied for DLP_DENIED_DATASET');
    const res = await createExportRequest(request, DATASETS.denied, mark('api denied'));
    expect(res.status()).toBe(403);
    expect((await res.json()).error).toBe('access_denied');
  });

  // API-08
  test('API-08 create with missing dataset is invalid', async ({ request }) => {
    const res = await request.post('/api/export_requests', {
      data: { justification: mark('no dataset') },
      headers: { 'Content-Type': 'application/json' },
    });
    expect(res.status()).toBe(400);
    expect((await res.json()).error).toBe('invalid_request');
  });

  // API-09b — server accepts a short justification (12-char rule is client-only).
  test('API-09b server accepts short justification', async ({ request }) => {
    const res = await createExportRequest(request, DATASETS.granted, 'e2e');
    expect(res.status()).toBe(201);
  });

  // ── 6.3 Steward actions ─────────────────────────────────────────────────────

  // API-10 / API-11 — steward approves/rejects a request created in-run.
  test('API-10 steward approves', async ({ request }, testInfo) => {
    test.skip(roleOf(testInfo) !== 'steward', 'steward project only');
    const created = await createExportRequest(request, DATASETS.granted, mark('api approve'));
    expect(created.status()).toBe(201);
    const id = String((await created.json()).id);
    const res = await actOnRequest(request, id, 'approve');
    expect(res.status()).toBe(200);
    expect((await res.json()).status).toBe('approved');
  });

  test('API-11 steward rejects', async ({ request }, testInfo) => {
    test.skip(roleOf(testInfo) !== 'steward', 'steward project only');
    const created = await createExportRequest(request, DATASETS.granted, mark('api reject'));
    expect(created.status()).toBe(201);
    const id = String((await created.json()).id);
    const res = await actOnRequest(request, id, 'reject');
    expect(res.status()).toBe(200);
    expect((await res.json()).status).toBe('rejected');
  });

  // API-12 — analyst cannot approve.
  test('API-12 analyst approve is forbidden', async ({ request }, testInfo) => {
    test.skip(roleOf(testInfo) !== 'analyst', 'analyst project only');
    const created = await createExportRequest(request, DATASETS.granted, mark('api not-steward'));
    expect(created.status()).toBe(201);
    const id = String((await created.json()).id);
    const res = await actOnRequest(request, id, 'approve');
    expect(res.status()).toBe(403);
    expect((await res.json()).error).toBe('not_a_steward');
  });

  // API-13 — unknown id (steward).
  test('API-13 approve unknown id is 404', async ({ request }, testInfo) => {
    test.skip(roleOf(testInfo) !== 'steward', 'steward project only');
    const res = await actOnRequest(request, randomUUID(), 'approve');
    expect(res.status()).toBe(404);
    expect((await res.json()).error).toBe('not_found');
  });

  // ── 6.4 Download / egress boundary ──────────────────────────────────────────

  // API-14 — full create -> approve -> download chain as steward (also submitter).
  test('API-14 approved own request downloads', async ({ request }, testInfo) => {
    test.skip(roleOf(testInfo) !== 'steward', 'steward acts as submitter + approver for a single-context chain');
    const created = await createExportRequest(request, DATASETS.granted, mark('api download'));
    expect(created.status()).toBe(201);
    const id = String((await created.json()).id);
    const approved = await actOnRequest(request, id, 'approve');
    expect(approved.status()).toBe(200);

    const dl = await request.get(`/api/exports/${id}/download`);
    // 200 when an artifact was materialized; a dataset with no source files
    // yields no artifact and thus 404 — accept both, but never a 5xx.
    expect([200, 404]).toContain(dl.status());
    if (dl.status() === 200) {
      expect(dl.headers()['content-disposition']).toContain('attachment');
    }
  });

  // API-15 — not-approved request cannot be downloaded.
  test('API-15 download of a pending request is 404', async ({ request }) => {
    const created = await createExportRequest(request, DATASETS.granted, mark('api dl pending'));
    expect(created.status()).toBe(201);
    const id = String((await created.json()).id);
    const dl = await request.get(`/api/exports/${id}/download`);
    expect(dl.status()).toBe(404);
  });

  // API-17 / API-18 / API-19 — require SQL/admin manipulation; documented, not automated here.
  test('API-17 expired download returns 410', async () => {
    test.skip(true, 'Requires backdating expires_at via SQL; see docs/TEST-PLAN.md §6.4 + ENV-03.');
  });
  test('API-18 revoked access returns 403 access_revoked', async () => {
    test.skip(true, 'Requires revoking the seeded permission; see docs/TEST-PLAN.md §6.4.');
  });
  test('API-19 downloads-disabled returns 403', async () => {
    test.skip(true, 'Requires toggling enableResultsDownloading; see docs/TEST-PLAN.md ENV-03.');
  });

  // ── 6.5 Study files ─────────────────────────────────────────────────────────

  // API-20
  test('API-20 study-files lists a granted dataset', async ({ request }) => {
    const res = await request.get(`/api/study-files?dataset=${encodeURIComponent(DATASETS.granted)}`);
    expect(res.status()).toBe(200);
    expect(await res.json()).toHaveProperty('files');
  });

  // API-21
  test('API-21 study-files denies a denied dataset', async ({ request }, testInfo) => {
    test.skip(roleOf(testInfo) !== 'analyst', 'run as an account denied for DLP_DENIED_DATASET');
    const res = await request.get(`/api/study-files?dataset=${encodeURIComponent(DATASETS.denied)}`);
    expect(res.status()).toBe(403);
    expect((await res.json()).error).toBe('access_denied');
  });

  // API-22
  test('API-22 study-files without dataset is invalid', async ({ request }) => {
    const res = await request.get('/api/study-files');
    expect(res.status()).toBe(400);
    expect((await res.json()).error).toBe('invalid_request');
  });

  // API-24
  test('API-24 preview denies a denied dataset', async ({ request }, testInfo) => {
    test.skip(roleOf(testInfo) !== 'analyst', 'run as an account denied for DLP_DENIED_DATASET');
    const res = await request.get(
      `/api/study-files/preview?dataset=${encodeURIComponent(DATASETS.denied)}&file=x.csv&page=1&count=1`,
    );
    expect(res.status()).toBe(403);
  });

  // API-25 — path traversal rejected before any decision check.
  test('API-25 preview rejects a path-like file name', async ({ request }) => {
    const res = await request.get(
      `/api/study-files/preview?dataset=${encodeURIComponent(DATASETS.granted)}&file=${encodeURIComponent('../etc/passwd')}&page=1`,
    );
    expect(res.status()).toBe(400);
    expect((await res.json()).error).toBe('invalid_file');
  });

  // API-26 — a file not present in the dataset directory.
  test('API-26 preview of a missing file is 404', async ({ request }) => {
    const res = await request.get(
      `/api/study-files/preview?dataset=${encodeURIComponent(DATASETS.granted)}&file=definitely-not-here.csv&page=1`,
    );
    // 404 file_not_found when the dataset has a resolvable volume; 404 no_files
    // when it has none — both are 404.
    expect(res.status()).toBe(404);
  });
});
