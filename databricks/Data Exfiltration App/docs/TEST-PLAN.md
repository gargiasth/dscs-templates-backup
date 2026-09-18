# DLP Demo — Playwright Test Cases & UAT Plan

Automation-oriented test cases for the Data Export Portal under **real Unity Catalog enforcement**. Companion to [`SPEC.md`](./SPEC.md). Each case is written so it can be translated directly into a Playwright spec (`tests/*.spec.ts`) or generated with `npx playwright codegen`. Cases carry a stable ID, priority, role, test type, data setup, cleanup, and generation notes.

> **Scope note.** The app has six routes only: `/`, `/submit`, `/my-requests`, `/steward-queue` (steward), `/audit` (steward), `/about`. There is **no** `/access-decisions` page and **no** `/api/exfil/check` endpoint. Egress/download enforcement lives entirely in `GET /api/exports/:id/download`. Earlier drafts of this plan referenced those removed surfaces; they have been dropped. Locators below are taken from [`client/src/App.tsx`](../client/src/App.tsx) and routes from [`server/server.ts`](../server/server.ts).

---

## 0. Test foundation

### 0.1 Environments

| Environment | Identity behavior | Use for |
| --- | --- | --- |
| **Deployed Databricks App** (proxied) | Real `x-forwarded-email` + `x-forwarded-access-token` injected by the Apps proxy; OBO queries evaluate as the signed-in user | All role-sensitive UI + authorization suites (SHARED, SUBMIT, MYREQ, QUEUE, AUDIT, API) |
| **Local `npm run dev`** (unproxied) | `forwardedEmail` falls back to `alice@example.com`; `userClient` falls back to the service principal (see [`server/server.ts`](../server/server.ts) `IS_DEV` branches) | SMOKE only. **Not** valid for role/OBO assertions — every caller looks like the SP, so decisions are not per-user. |

Because the proxy always injects headers in production and dev always falls back to a fixed identity, the `401 no_identity` branch is **not reachable through either normal channel**. Those cases (see API suite) are marked *harness-only* and should be covered by a server integration test that omits forwarded headers, not by Playwright against a live deploy.

### 0.2 Accounts, roles, and Playwright projects

Roles are **Unity Catalog account-group membership** — there is no in-app switch. Provision two real accounts and capture an authenticated `storageState` for each via the Databricks OAuth sign-in flow (a global setup that signs in once and writes `.auth/<role>.json`). Do **not** attempt to forge proxy/OBO headers in browser tests — the proxy overwrites them.

| Playwright project | Account | Group membership | Expected badge |
| --- | --- | --- | --- |
| `analyst` | analyst test user | `bdc-analysts` only | Analyst |
| `steward` | steward test user | `bdc-analysts` + `bdc-stewards` | Steward |

```ts
// playwright.config.ts (sketch)
projects: [
  { name: 'setup', testMatch: /auth\.setup\.ts/ },
  { name: 'analyst', dependencies: ['setup'], use: { storageState: '.auth/analyst.json' } },
  { name: 'steward', dependencies: ['setup'], use: { storageState: '.auth/steward.json' } },
]
```

Each case lists the project(s) it runs under. API cases reuse the same `storageState` via `page.request` / a `request` fixture so calls traverse the proxy and inherit the caller's identity.

### 0.3 Seeded data expectations

From [`sql/001_governance.sql`](../sql/001_governance.sql) and [`sql/002_mock_consent_grants.sql`](../sql/002_mock_consent_grants.sql). Bind tests to a decision **class**, and use these concrete IDs where a specific row is needed:

| Fixture | Value | Decision for a matching seeded user |
| --- | --- | --- |
| Controlled, granted dataset | `phs000298` (consent group `c2`) | `granted` for a user with an unexpired `user_dbgap_permissions` row |
| Controlled, denied dataset | `phs000710` (consent group `c1`) | `denied` for a user with no matching permission |
| Open-access dataset | any `study_catalog` row with `access_tier = 'open_access'` | `granted`, no DAR |
| Unregistered dataset | any `access_tier = 'unregistered'` | `flagged_for_review` |
| Consent row-filter cohort | `governed.default.framingham_cohort` | Real accounts see **0 rows** unless a grant row is added (seed grants use fictional `@bdc-demo.org` emails) |

> The demo seed grants `phs000298` to a specific account (`nina.mezu@axleinfo.com`). For a portable suite, seed one `granted` and one `denied` controlled dataset for **your** analyst/steward test accounts before running SUBMIT/QUEUE/API cases, or parameterize the dataset IDs.

### 0.4 Run isolation & cleanup

- Tag every request created by tests with a unique run marker inside the justification, e.g. `justification = "e2e run <RUN_ID>: <text>"`, so created rows are identifiable.
- Approval/download cases must **create** their own request in the same run and thread the returned `request_id` (the "Query ID") through subsequent steps — never depend on a pre-existing row.
- Teardown: delete test-created rows from `governed.default.export_requests` (and any `governed.export_outputs.req_<id>` artifacts) by run marker via a SQL teardown step. `audit_events` rows are append-only; leave them and filter by marker when asserting.
- Prefer `test.describe.serial` for create -> approve -> download chains.

### 0.5 Deterministic vs environment-administered

- **Default CI suites** (SMOKE, SHARED, SUBMIT, MYREQ, QUEUE, AUDIT, API) are deterministic given seeded data and captured auth state.
- **Environment-administered suite** (ENV) covers actions that require a metastore/account admin or have propagation lag: group-membership toggles, the workspace results-download setting, `system.access.audit` latency, and warehouse cold-start. Run these **serially**, outside the parallel CI lane, and gate them behind an explicit tag (e.g. `@env`).

### 0.6 Locator conventions

Use supported Playwright locators only: `getByRole`, `getByText`, `getByLabel`, `getByPlaceholder`. Do **not** use `getByLabelText` (React Testing Library only — throws at runtime). Radix `Select` renders a button trigger + listbox: open with `getByRole('combobox')` / the trigger's label, then choose `getByRole('option', { name })`. Keep asserted result sets small (the analytics event payload cap is 1 MB); prefer `LIMIT`/aggregated seed data.

---

## Suite 0 — Smoke (`@smoke`)

Aligned with [`tests/smoke.spec.ts`](../tests/smoke.spec.ts). Runs in dev or deployed. Analyst project (default role).

| ID | Priority | Project | Type | Steps | Expected |
| --- | --- | --- | --- | --- | --- |
| SMOKE-01 | P0 | analyst | UI | `goto('/')` | Text `Axle Data Export Portal` and `How it works` visible; no page/console errors captured. |
| SMOKE-02 | P0 | analyst | UI | On `/`, read `getByRole('navigation')` | For an analyst, nav shows `Home`, `Submit Request`, `My Requests`, `About`; **both** `Steward Queue` **and** `Audit` are absent (they share the same `isSteward` gate). For a steward, both appear. |
| SMOKE-03 | P1 | analyst | UI | `goto('/about')` | About heading and "What this demonstrates" content render; no errors. |

> **Existing-spec bug to reconcile:** [`tests/smoke.spec.ts`](../tests/smoke.spec.ts) asserts the `Audit` link is visible while treating the session as analyst, but `Audit` and `Steward Queue` are gated by the same `isSteward` check ([`App.tsx`](../client/src/App.tsx) L607–616) — so an analyst sees neither and a steward sees both. The current assertion (Audit visible, Steward Queue hidden) can never both hold; update the spec to gate the `Audit`/`Steward Queue` assertions on the run's role, and fix the stale "Access Decisions" comment.

Generation note: extend the existing smoke spec's home assertions; keep its console/pageerror capture hooks.

---

## Suite 1 — Shared UI, identity & route guards (SHARED)

| ID | Priority | Project | Type | Preconditions | Steps | Expected |
| --- | --- | --- | --- | --- | --- | --- |
| SHARED-01 | P0 | analyst, steward | UI | signed in | `goto('/')`; read the identity badge in the header | Badge shows the real signed-in email; **no** user picker or role dropdown anywhere. |
| SHARED-02 | P0 | steward | UI | steward account | Observe badge + nav | Badge pill reads `Steward`; nav shows `Steward Queue` and `Audit`. |
| SHARED-03 | P0 | analyst | UI | analyst account | Observe badge + nav | Badge pill reads `Analyst`; `Steward Queue` and `Audit` links absent. |
| SHARED-04 | P0 | analyst | UI | analyst | `goto('/steward-queue')` directly | `403 — Stewards only` alert with `bdc-stewards` copy; no queue data. |
| SHARED-05 | P0 | analyst | UI | analyst | `goto('/audit')` directly | Same `403 — Stewards only` guard; no audit tables render. |
| SHARED-06 | P1 | steward | UI | steward | `goto('/steward-queue')` and `/audit` | Pages render (no 403 guard). |
| SHARED-07 | P1 | analyst | UI | — | Inspect `localStorage` and any POST body via `page.on('request')` while submitting | No `dlp_user`/`dlp_role` keys; no request body carries a user identifier. |
| SHARED-08 | P2 | analyst | UI | mobile viewport (`use: { viewport }` or a project) | Click hamburger (`getByRole('button', { name: 'Open navigation' })`) | Sheet titled `Navigation` opens with the same links + identity badge. |
| SHARED-09 | P2 | analyst | UI | — | On `/`, click `getByRole('button', { name: 'Collapse menu' })` | Left menu collapses (button label toggles to `Expand menu`). |
| SHARED-10 | P2 | analyst, steward | UI | — | Visit each visible route | No console errors / failed requests captured (reuse smoke hooks). |

Generation note: for SHARED-04/05, assert `getByText('403 — Stewards only')`. The security boundary is UC row filtering, not this guard — the guard is presentation only.

---

## Suite 2 — Submit Request (SUBMIT) — route `/submit`

Analyst project unless noted. Uses seeded granted/denied/open/unregistered datasets (0.3).

| ID | Priority | Project | Type | Preconditions | Steps | Expected |
| --- | --- | --- | --- | --- | --- | --- |
| SUBMIT-01 | P0 | analyst | UI | catalog seeded | `goto('/submit')`; open the `Dataset` select (`getByLabel('Dataset')` trigger) | Options list `study_catalog` entries (study name + `dataset_id`). |
| SUBMIT-02 | P0 | analyst | UI | granted dataset seeded | Select the granted dataset | PermissionWidget shows `Granted`-style label + basis; Tier line rendered. |
| SUBMIT-03 | P0 | analyst | UI | denied dataset seeded | Select the denied dataset | PermissionWidget shows denied label + basis; `Submit` button disabled; inline `Access denied for this dataset — you cannot submit an export request.` |
| SUBMIT-04 | P1 | analyst | UI | unregistered dataset | Select it | PermissionWidget shows the `flagged_for_review` label + "no consent group to verify" basis. |
| SUBMIT-05 | P0 | analyst | UI | granted dataset | Select granted; type an 8-char justification; click `Submit` | Client validation blocks: `Please provide at least 12 characters of justification.`; no POST fired. |
| SUBMIT-06 | P0 | analyst | UI + network | granted dataset | Select granted; enter `>=12`-char justification with run marker; click `Submit` | `POST /api/export_requests` -> `201`; success text `Request submitted successfully.`; `Request submitted — Query ID` card with a `Copy` button; form resets. |
| SUBMIT-07 | P1 | analyst | UI | after SUBMIT-06 | Click `Copy` in the Query ID card | Clipboard contains the request id; button label flips to `Copied` (grant clipboard permission in config). |
| SUBMIT-08 | P1 | analyst | UI + network | granted dataset with source files | Select granted | Right panel `Data files` renders; `File` select (`getByLabel('File')`) populated; `Total rows:` shown; a preview table appears (`GET /api/study-files` + `/preview` return 200). |
| SUBMIT-09 | P2 | analyst | UI | granted dataset, multi-file | Change the `File` select; page through with the pager | Preview swaps columns/rows for the new file; pagination updates rows. |
| SUBMIT-10 | P1 | analyst | UI | no dataset selected / denied dataset | Observe right column | Placeholder card: `Select a granted dataset to preview its data files here.` (or dataset-specific variant); no preview fetch. |
| SUBMIT-11 | P2 | analyst | UI | granted notebook (`.ipynb`) dataset | Select it, pick the notebook file | Non-tabular notice ("is a Python notebook … exported via **Volumes** only"); no row preview. |

Generation note: the client sends only `{dataset, justification, format}` (see [`App.tsx`](../client/src/App.tsx) submit handler ~L1661). Assert the intercepted POST body has **no** `submitter` field.

---

## Suite 3 — My Requests (MYREQ) — route `/my-requests`

| ID | Priority | Project | Type | Preconditions | Steps | Expected |
| --- | --- | --- | --- | --- | --- | --- |
| MYREQ-01 | P0 | analyst | UI + network | at least one own request | `goto('/my-requests')` | `GET /api/my-requests` fires with **no** submitter param; only the caller's rows render (scoped by `current_user()`). |
| MYREQ-02 | P0 | analyst | UI | just submitted in same run (SUBMIT-06) | Navigate from Submit to My Requests | The just-submitted request is already present (uncached live endpoint); no manual reload needed. |
| MYREQ-03 | P1 | analyst | UI | own requests exist | Click `Refresh` (`getByRole('button', { name: /Refresh/ })`) | Re-fetch occurs; spinner state toggles; rows consistent. |
| MYREQ-04 | P1 | analyst | UI | mixed statuses | Use the status filter select (`All statuses` -> `Pending`/`Approved`/`Rejected`) and the search box (placeholder `Search by dataset or justification`) | Rows filter accordingly; stat band counts (`Total/Pending/Approved/Rejected`) match. |
| MYREQ-05 | P2 | analyst | UI | no requests / no matches | Fresh account or impossible filter | Empty state `No requests yet` (none) or `No requests match your filters` (filtered). |
| MYREQ-06 | P1 | analyst | UI | request submitted with a cohort filter/variables | View the row | `N variables` and/or a row-filter badge render inline on the row. |
| MYREQ-07 | P1 | analyst, steward | UI | an approved request with an artifact (create+approve in-run) | View the row | Status `approved`; `Export via` selector (`getByLabel(/Export via/)`) present; choosing an option (e.g. `Volumes`) reveals its educational description + FedRAMP-boundary note. This control does **not** download bytes. |
| MYREQ-08 | P2 | analyst | UI | an approved request past its `expires_at` | View the row | `Expired` badge shown next to status; `Expires <date>` text present. (Manipulate `expires_at` via SQL to force this.) |

Generation note: the current UI has **no** in-page Download button — `output_url` (`/api/exports/:id/download`) is exercised by the API suite, not the UI. Do not assert a UI download click.

---

## Suite 4 — Steward Queue (QUEUE) — route `/steward-queue`, steward only

| ID | Priority | Project | Type | Preconditions | Steps | Expected |
| --- | --- | --- | --- | --- | --- | --- |
| QUEUE-01 | P0 | steward | UI + network | a pending request exists | `goto('/steward-queue')` | `GET /api/steward-queue` returns pending rows (OBO, row-filtered to stewards); `Requests awaiting review` count matches list. |
| QUEUE-02 | P0 | analyst | UI | analyst | `goto('/steward-queue')` | `403 — Stewards only` guard; the underlying view returns 0 rows regardless (belt-and-suspenders with SHARED-04). |
| QUEUE-03 | P0 | steward | UI + network | pending request created in-run | On a row, click `Approve` | `POST …/approve` -> `200`; row leaves the queue; queue re-pulls automatically. |
| QUEUE-04 | P0 | steward | UI + network | pending request created in-run | On a row, click `Reject` | `POST …/reject` -> `200`; row leaves the queue. |
| QUEUE-05 | P1 | steward | UI | pending request | Click `View details` | Dialog opens with four sections: `Requester`, `DAR status for this dataset`, `Request details`, `Requested export (cohort)`; approve/reject also available in the dialog footer. |
| QUEUE-06 | P1 | steward | UI | pending row with enriched context | In the row/dialog | Live submitter decision badge shown; consent group + access tier + dbGaP status present in details. |
| QUEUE-07 | P1 | steward | UI | queue has rows | Use search (placeholder `Search by dataset or submitter`) | List filters by dataset/submitter/justification. |
| QUEUE-08 | P2 | steward | UI | queue empty | Fresh queue | Empty state `No pending requests`. |
| QUEUE-09 | P1 | steward | UI | approve/reject in-run | After acting | Cohort details in the dialog reflect selected variables ("All variables" or list) and the row filter ("None (all rows)" or the described filter). |

---

## Suite 5 — Audit (AUDIT) — route `/audit`, steward only

| ID | Priority | Project | Type | Preconditions | Steps | Expected |
| --- | --- | --- | --- | --- | --- | --- |
| AUDIT-01 | P0 | steward | UI | app events exist | `goto('/audit')` | `App-Reported Events` table with columns `Timestamp, User, Action, Resource, Outcome, Details`; stat band renders. |
| AUDIT-02 | P1 | steward | UI | mixed outcomes | Use search (`Search by user, action, or resource`) + outcome filter (`submitted/approved/rejected/blocked/allowed`) | Rows filter accordingly; `Details` renders readable text (objects stringified). |
| AUDIT-03 | P1 | steward | UI | after a SUBMIT/QUEUE action in-run | Refresh `/audit`, filter by the run marker | The corresponding `submitted`/`approved`/`rejected` event is present with the acting user = the real forwarded email. |
| AUDIT-04 | P1 | steward | UI + network | steward has `system.access.audit` access | Scroll to `Platform Audit Log` | Second panel labeled `Platform Audit Log` with the `system.access.audit` badge and note `Platform log may lag several minutes.`; served by `GET /api/platform-audit`. |
| AUDIT-05 | P0 | analyst | UI | analyst | Attempt `/audit` | Guarded (see SHARED-05); the `PlatformAuditPanel` never renders for non-stewards. |
| AUDIT-06 | P2 | steward | UI | scope note | Bottom of page | `Scope of this layer` note present (stated governance boundary). |

> No `Egress path` column exists in the current audit table; do not assert it.

---

## Suite 6 — API authorization & contract (API)

Drive with an authenticated `request` context that traverses the proxy (`page.request` after signing in), so calls inherit the caller's identity/OBO token. Endpoints and codes from [`server/server.ts`](../server/server.ts). Assert status + JSON `error` code; do **not** assert implementation-only headers.

### 6.1 Identity & live reads

| ID | Priority | Project | Request | Expected |
| --- | --- | --- | --- | --- |
| API-01 | P0 | analyst | `GET /api/me` | `200 { user: <forwarded email> }`. |
| API-02 | P0 | steward | `GET /api/steward-queue` | `200` array of pending rows (row-filtered to stewards); `submitter_expiration_ts` is a number. |
| API-03 | P0 | analyst | `GET /api/steward-queue` | `200 []` — UC row filter returns zero rows for non-stewards (not an error). |
| API-04 | P0 | analyst | `GET /api/my-requests` | `200` array scoped to caller (`submitter = current_user()`). |
| API-05 | P1 | steward | `GET /api/platform-audit` | `200` array (may be slow; endpoint polls past the 30s wait). If the caller lacks system-table access, expect a `500` whose body carries the real UC error message. |
| API-05b | P1 | analyst | `GET /api/platform-audit` | The endpoint has **no server-side steward check** — the app does not return `403`. The analyst gets whatever UC allows OBO: typically `200 []` or a `500` bearing the real access error. The steward-only visibility is enforced by (a) UC per-caller access and (b) the UI panel hiding for non-stewards, not by an app gate on this route. |

### 6.2 Create request

| ID | Priority | Project | Request | Expected |
| --- | --- | --- | --- | --- |
| API-06 | P0 | analyst | `POST /api/export_requests` `{dataset:<granted>, justification:"e2e <RUN_ID> ok"}` | `201` record; `submitter` = forwarded email; status `pending`. |
| API-07 | P0 | analyst | `POST /api/export_requests` `{dataset:<denied>, justification:"e2e <RUN_ID>"}` | `403 access_denied` (server re-ran `export_decision` OBO); a `blocked` `submit_export` audit event is written. |
| API-08 | P0 | analyst | `POST /api/export_requests` `{}` (missing `dataset`) | `400 invalid_request` (zod). |
| API-09 | P0 | analyst | `POST /api/export_requests` with extra `{submitter:"someone.else@x.org", dataset:<granted>, justification:"e2e <RUN_ID>"}` | `201`; created record's `submitter` is the forwarded email, **not** the body value. |
| API-09b | P1 | analyst | `POST /api/export_requests` `{dataset:<granted>, justification:"e2e"}` (short justification) | `201`. The `>=12`-char rule is **client-only** (`submitRequestSchema` accepts empty); the server's enforcement point is the OBO `export_decision` re-check, not justification length. Distinguishes SUBMIT-05 (client) from server behavior. |

### 6.3 Steward actions

| ID | Priority | Project | Request | Expected |
| --- | --- | --- | --- | --- |
| API-10 | P0 | steward | `POST /api/export_requests/:id/approve` (id created in-run) | `200` updated; status `approved`; on success an `export_outputs` artifact + `expires_at` are set (when the dataset has source files). |
| API-11 | P0 | steward | `POST /api/export_requests/:id/reject` (id created in-run) | `200` updated; status `rejected`. |
| API-12 | P0 | analyst | `POST /api/export_requests/:id/approve` | `403 not_a_steward` (server verified `is_account_group_member('bdc-stewards')` OBO); `blocked` audit event written. |
| API-13 | P1 | steward | `POST /api/export_requests/<unknown-uuid>/approve` | `404 not_found`. |

### 6.4 Download / egress boundary

| ID | Priority | Project | Request | Expected |
| --- | --- | --- | --- | --- |
| API-14 | P0 | analyst | `GET /api/exports/:id/download` for an **approved, non-expired** own request (create+approve in-run) | `200`; `Content-Disposition: attachment`; CSV/JSON body. |
| API-15 | P0 | analyst | `GET /api/exports/:id/download` for a **not-approved / no-artifact** request | `404 not_found`. |
| API-16 | P1 | analyst-B | `GET /api/exports/:id/download` for a request owned by **another** analyst | `403 not_your_request` (needs a second analyst account; skip if unavailable). |
| API-17 | P1 | analyst | `GET /api/exports/:id/download` for an approved request whose `expires_at` is in the past (force via SQL) | `410 export_expired`. |
| API-18 | P1 | analyst | `GET /api/exports/:id/download` after the caller's live `export_decision` is no longer `granted` (revoke the seeded permission) | `403 access_revoked`. |
| API-19 | P1 | analyst | `GET /api/exports/:id/download` while workspace `enableResultsDownloading` is off (ENV-03) | `403 downloads_disabled`. |

Each denial writes a distinct `blocked` audit event; assert the matching event where practical. The raw `governed.export_outputs` table is never granted to users — the endpoint is the only path to the bytes.

### 6.5 Study files (OBO, decision-gated)

| ID | Priority | Project | Request | Expected |
| --- | --- | --- | --- | --- |
| API-20 | P1 | analyst | `GET /api/study-files?dataset=<granted>` | `200 { files: [...] }`. |
| API-21 | P0 | analyst | `GET /api/study-files?dataset=<denied>` | `403 access_denied`. |
| API-22 | P1 | analyst | `GET /api/study-files` (missing `dataset`) | `400 invalid_request`. |
| API-23 | P1 | analyst | `GET /api/study-files/preview?dataset=<granted>&file=<real>&page=1&count=1` | `200 { columns, rows, total, page, pageSize }`. |
| API-24 | P0 | analyst | `GET /api/study-files/preview?dataset=<denied>&file=x` | `403 access_denied`. |
| API-25 | P0 | analyst | `GET /api/study-files/preview?dataset=<granted>&file=../etc/passwd` | `400 invalid_file` (path with `/` or `\` rejected). |
| API-26 | P1 | analyst | `GET /api/study-files/preview?dataset=<granted>&file=<not-in-dir>` | `404 file_not_found`. |

### 6.6 Harness-only (not automatable against the proxied deploy)

| ID | Priority | Type | Request | Expected |
| --- | --- | --- | --- | --- |
| API-27 | P2 | server integration (no forwarded headers) | any endpoint without identity headers, production mode | `401 no_identity`. Cover in a server-side integration test; the Apps proxy always injects headers, so Playwright against a live deploy cannot reach this branch. |

---

## Suite 7 — Environment-administered / governance (ENV) `@env`

Run serially, admin-operated, outside the parallel lane. These exercise real platform controls, not app state.

| ID | Priority | Type | Steps | Expected |
| --- | --- | --- | --- | --- |
| ENV-01 | P0 | group toggle | Remove the account from `bdc-stewards` in the account console; wait ~1 min for propagation; reload `/`. Re-add and repeat. | Badge, nav links, `/steward-queue` + `/audit` access, and `steward_queue` rows all flip together — with **zero** app/config/storage changes. |
| ENV-02 | P1 | group toggle | As newly-demoted analyst, `GET /api/steward-queue` | Returns `200 []` (row filter), independent of the client guard. |
| ENV-03 | P0 | workspace setting | Disable `enableResultsDownloading` in admin settings; retry API-14/API-19; re-enable and confirm reverse | Download flips to `403 downloads_disabled` when off, `200` when on — no app change involved. |
| ENV-04 | P2 | platform log latency | Query a `governed.default.%` object in a SQL editor (outside the app); wait a few minutes; refresh `/audit` Platform panel | The platform log eventually shows the event even though the app never wrote it — the two logs are independent. |
| ENV-05 | P2 | data-layer SQL | As steward and as analyst run `SELECT count(*) FROM governed.default.steward_queue` and `… export_decision_all` | Steward sees rows; non-steward gets `0` rows (not an error) — verifies the UC row filters directly. |
| ENV-06 | P2 | data-layer SQL | Run `SELECT * FROM governed.default.export_decision` as each account | One row per dataset, decisions scoped to `current_user()`; `phs000298` granted / `phs000710` denied for the seeded account; no user parameter anywhere. |
| ENV-07 | P2 | consent row filter | On `/` or via SQL, read `governed.default.framingham_cohort` as a real account | `0` rows unless a matching grant row is added (seed grants use fictional `@bdc-demo.org` emails) — the deny path is enforcement working, not an error. |

---

## Appendix A — Route ↔ locator quick reference

| Route | Key stable locators |
| --- | --- |
| `/` | `getByText('Axle Data Export Portal')`, `getByText('How it works')`, `getByRole('button', { name: 'Collapse menu' })` |
| header (all) | identity badge email + `Steward`/`Analyst` pill; `getByRole('button', { name: 'Open navigation' })` (mobile) |
| `/submit` | `getByRole('heading', { name: 'Submit Export Request' })`, `getByLabel('Dataset')`, `getByLabel('Justification')`, `getByRole('button', { name: 'Submit' })`, `getByText('Request submitted — Query ID')`, `getByLabel('File')` |
| `/my-requests` | `getByRole('heading', { name: 'My Export Requests' })`, `getByPlaceholder('Search by dataset or justification')`, `getByRole('button', { name: /Refresh/ })`, `getByLabel(/Export via/)` |
| `/steward-queue` | `getByRole('heading', { name: 'Steward Queue' })`, `getByRole('button', { name: 'View details' })`, `Approve`, `Reject`, `getByPlaceholder('Search by dataset or submitter')` |
| `/audit` | `getByRole('heading', { name: 'Audit Log' })`, `getByText('App-Reported Events')`, `getByText('Platform Audit Log')`, `getByPlaceholder('Search by user, action, or resource')` |
| steward guard | `getByText('403 — Stewards only')` |
| `/about` | `getByRole('heading', { name: 'Axle Data Export Portal' })`, `getByText('What this demonstrates')` |

## Appendix B — Regression / build (manual)

| ID | Steps | Expected |
| --- | --- | --- |
| BUILD-01 | `npm run build` | Succeeds using committed `analytics.d.ts`; no warm warehouse required. |
| BUILD-02 | `npm run test:smoke` | Home page loads; nav renders (Suite 0). |
