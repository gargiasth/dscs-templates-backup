# DLP Demo — Functional Specification

**App:** `dlp-demo` — Data Download Prevention POC ("Data Export Portal")
**Platform:** Databricks Apps (AppKit — Express server + React/TypeScript client)
**Data layer:** Unity Catalog schema `governed.default`, queried through a Databricks SQL Warehouse.

---

## 1. Purpose

A governed data-export workflow enforced by **real Unity Catalog mechanisms** — not app state:

- **Identity** comes from the Databricks Apps proxy (`x-forwarded-email` / `x-forwarded-access-token`). The client never supplies a user identifier for any authorization decision.
- **Roles** are Unity Catalog account-group memberships: `bdc-analysts` and `bdc-stewards`. The app renders a read-only badge; changing a role means changing group membership in the account console.
- **Authorization decisions** are computed live by a `current_user()`-scoped UC view — re-runnable by anyone, with no parameters to spoof.
- **Enforcement** happens in three layers: UC row-filtered views (zero rows for non-stewards), server-side OBO re-validation on every write, and route guards in the client (presentation only).
- **Audit** is dual: app-written events in `governed.default.audit_events`, plus Unity Catalog's own `system.access.audit` platform log.
- **Egress boundary** covers three paths — direct download / CLI (enforced today), copy to a connected external cloud Volume, and SBFS mount (both planned) — backed by real workspace configuration (results-download setting, IP access lists / network policies), not anything the app simulates. The download path re-validates this boundary on every request.
- **Controlled exports** are real, expiring artifacts: approval materializes a per-request governed Delta table under `governed.export_outputs` (with UC lineage + provenance tags), and downloads are app-mediated and re-validated (status, ownership, expiry, live export decision, workspace download setting). The raw artifact table is never granted to users — the app is the only path to the bytes.
- **Cohort pointer, not files** (PIC-SURE Query-ID analog): a request carries a *cohort definition* (variables + an optional structured row filter), not data. Nothing is materialized until a steward approves, at which point the definition is re-validated against the live schema and applied. **Consent travels with the data** — every exported row is appended with its dbGaP consent group and access context (mirroring BDC's `_consents_` column), and the artifact is tagged accordingly.
- **No credential hand-off**: there is no token to reveal, copy, or paste. Identity is the forwarded OAuth token; access changes the instant group membership or a dbGaP permission changes.

> **Scope assumption.** This app operates *downstream* of the dbGaP/DAC governance chain (Consent → DAR → DAC Approval → DUA issued). Those steps are assumed already complete; the app does not perform them. It consumes their outcome — an approved, time-bounded dbGaP permission (`governed.default.user_dbgap_permissions`) — and enforces it on every access.

> **Positioning.** The UI copy targets technical decision-makers and stakeholders. It frames Databricks + Unity Catalog as a consent-group-aware governance layer that sits *beneath* BDC's existing tools (PIC-SURE, Seven Bridges, Terra, etc.) — not beside them as one more environment — so the same consent-group check applies regardless of which tool initiated a request. It does **not** overstate the gap: BDC already re-checks dbGaP status (losing approval locks a whole *project* to read-only). The gap this demo targets is **granularity** — BDC enforces at the project level, never at the level of the individual file, record, or consent group — and **egress coverage**: the same check should apply at the moment data moves through any of the three egress paths, not just at sign-in. The three paths are named explicitly throughout: (1) direct download / CLI, (2) copy to a connected external cloud Volume (the researcher's own AWS/GCP/Azure account), and (3) SBFS mount (project files mounted as a local filesystem). Only path 1 is functional today; 2 and 3 are surfaced as "coming soon". The `/about` page, per-page "How Unity Catalog enforces this" callouts, the header tagline, and the Home hero carry this framing; operational page copy stays task-focused.

> **Stated scope limit.** This layer governs what can be *exposed* via download, volume copy, or SBFS mount. It cannot reach data once it has already left the platform through one of these paths. This is shown honestly in the UI (About page and Activity Log footer) as a boundary of platform-side governance, not a defect.

---

## 2. Architecture

| Layer | Technology |
| --- | --- |
| Client | React 19, React Router 7, Tailwind CSS, `@databricks/appkit-ui` components |
| Server | Express via `@databricks/appkit` (`server()` + `analytics({})` plugins) |
| Data reads (cached) | AppKit analytics plugin. `*.obo.sql` queries execute **on-behalf-of-user** (caller's OAuth token, requires `user_api_scopes: [sql]` in `databricks.yml`); `*.sql` queries execute as the app service principal. Results are cached in-memory per user for 1 hour |
| Data reads (live) | The volatile request-tracking views (**steward queue**, **my requests**) are served from dedicated **uncached** OBO Express routes so writes appear immediately (see §7.1) |
| Data writes | Custom Express routes running parameterized SQL. Writes execute as the SP **after** re-validating the caller via an OBO query |
| Validation | `zod` schemas on all mutation endpoints |

### 2.1 Source files

- `client/src/App.tsx` — entire client (routing, layout, pages, components).
- `server/server.ts` — Express routes, OBO re-validation, audit helper, workspace-state reader.
- `config/queries/*.sql` / `*.obo.sql` — analytics read queries.
- `sql/001_governance.sql` — UC migration: grants, views, demo seed.

---

## 3. Unity Catalog objects

### 3.1 Groups (account-level)

| Group | Meaning |
| --- | --- |
| `bdc-analysts` | Can browse the catalog and submit/track export requests |
| `bdc-stewards` | Additionally sees the steward queue, all users' access decisions, audit access, and the platform audit log |

### 3.2 Grants (to groups, never individuals)

| Object | bdc-analysts | bdc-stewards |
| --- | --- | --- |
| `governed.default.study_catalog` | SELECT | SELECT |
| `governed.default.export_requests` | SELECT, MODIFY | SELECT, MODIFY |
| `governed.default.audit_events` | — | SELECT |
| `governed.default.export_decision` (view) | SELECT | SELECT |
| `governed.default.export_decision_all` (view) | SELECT (returns 0 rows) | SELECT |
| `governed.default.steward_queue` (view) | SELECT (returns 0 rows) | SELECT |
| `system.access.audit` | — | SELECT (requires a **metastore admin** to grant; see note in `sql/001_governance.sql`) |

### 3.3 Views (all in `sql/001_governance.sql`)

- **`export_decision`** — parameterless, self-enforcing. Joins `study_catalog` to `user_dbgap_permissions` on dataset + consent group **and `p.user_id = current_user()`**. Decisions: `open_access` → `granted`; `unregistered` → `flagged_for_review`; `controlled_access` → `granted` only with a matching unexpired permission row, else `denied`. `expiration_ts` is epoch seconds.
- **`export_decision_all`** — same computation for **all** users, with `WHERE is_account_group_member('bdc-stewards')` — zero rows for non-stewards regardless of what the app requests.
- **`steward_queue`** — `export_requests WHERE status = 'pending' AND is_account_group_member('bdc-stewards')` — zero rows for non-stewards.

> The former `export_decision` view computed decisions for all users with no self-scoping; it was replaced in place. The `user_dbgap_permissions` table also carries a demo seed row for the demo account (see migration §6) so real `current_user()` evaluation can show both granted and denied controlled-access outcomes.

**`poc_role` column.** The app never reads `poc_role` for authorization — UC group membership is the source of truth. The column is kept consistent for real workspace users: `bdc-stewards` members get `'steward'`, `bdc-analysts`-only members get `'analyst'`, and users in both groups get `'steward'` (highest role wins). Because `is_account_group_member()` only evaluates for the current caller, this cannot be a SQL view over arbitrary rows; run `scripts/sync_poc_role.sh` after changing group membership. Synthetic demo users keep their seeded values.

### 3.4 Analytics queries (`config/queries/`)

| Query | Execution | Returns |
| --- | --- | --- |
| `study_catalog_all.sql` | SP | Dataset catalog for the Submit dropdown |
| `export_requests_all.sql` | SP | All requests (Home page stats) |
| `audit_events_all.sql` | SP | App-written audit events |
| `export_decision.obo.sql` | **OBO** | Caller's own decisions (current_user()-scoped view) |
| `export_decision_all.obo.sql` | **OBO** | All users' decisions — UC returns 0 rows unless caller is a steward |
| `steward_queue.obo.sql` | **OBO** | Pending requests — UC returns 0 rows unless caller is a steward. *Canonical SQL; the UI now reads this data via the uncached `GET /api/steward-queue` route (§7.1) so new requests appear immediately* |
| `my_export_requests.obo.sql` | **OBO** | `export_requests WHERE submitter = current_user()`. *Canonical SQL; the UI now reads this data via the uncached `GET /api/my-requests` route (§7.1)* |
| `is_steward.obo.sql` | **OBO** | `current_user()`, `is_account_group_member('bdc-stewards'/'bdc-analysts')` |
| `system_audit_governed.obo.sql` | **OBO** | Last 30 days of `system.access.audit` filtered to `governed.default.%` objects |

---

## 4. Identity & roles (client)

- `IdentityContext` holds `{ user, isSteward, loading, error }` — **read-only**. `user` comes from the `is_steward` OBO query (`current_user()`), with `GET /api/me` as display fallback. There is no localStorage identity, no user picker, and no role dropdown.
- The header shows an identity badge: email + "Steward"/"Analyst" pill resolved from `is_account_group_member('bdc-stewards')`.
- **Role changes require zero app changes**: add/remove the user from `bdc-stewards` in the account console, reload, and the badge, nav, and all row-filtered data change together.

### 4.1 Steward-only routes

`/steward-queue` and `/audit` are wrapped in `RequireSteward`, which renders a **403 — Stewards only** alert for non-members (direct URL included). This guard is presentation; the security boundary is the UC row-filtered views and the server-side membership checks, which hold even if the client is bypassed entirely.

---

## 5. Pages

### 5.1 Home (`/`)
Hero, stat band (SP queries), Explore cards filtered by `isSteward`, two-column How-it-works (Analyst / Steward), and the downstream-scope note.

### 5.1a About (`/about`)
Static, no backend calls. Frames the demo for technical decision-makers: the "beneath BDC's tools, not beside them" positioning (acknowledging BDC's real project-level re-check and targeting the granularity + egress-coverage gap, naming the three egress paths), the downstream-of-DAC governance chain, a **"Credentials: no token to leak"** card contrasting the legacy token hand-off (reveal → paste into a secret store) with this app's forwarded-identity/OBO model, a mapping of each enforcement layer (identity, roles, decision views, row filtering, server re-validation, dual audit, egress controls, expiring artifacts) to its concrete UC mechanism, and a stated scope-limit note.

### 5.2 Submit Request (`/submit`)
- Dataset dropdown from `study_catalog_all`.
- `PermissionWidget` reads the caller's decision from the **OBO `export_decision`** query (no parameters).
- Submit button disabled when the decision is `denied`; the client sends `{dataset, justification, format, selected_columns, cohort_filter}` — **no submitter field**.
- A 403 from the server renders "Blocked server-side: your Unity Catalog export decision for this dataset is not 'granted'."
- **Cohort definition (Query-ID pointer).** When access is granted and the data preview has loaded, a *Refine cohort (optional)* panel lets the requester pick the **variables** to include (toggle chips; empty = all) and one **structured row filter** (`column` + operator + value — never free-form SQL). This is a *pointer*, not data: nothing is materialized here. On submit the server returns a **Query ID** (the `request_id`), shown with a copy button and the framing *"share this pointer, not a file — data materializes only after a steward approves."* The cohort is stored as JSON on the request (`selected_columns`, `cohort_filter`) and applied at approval.

### 5.3 My Requests (`/my-requests`)
- Rows scoped to `current_user()` by the warehouse (includes `expires_at`), read live from **`GET /api/my-requests`** (uncached OBO) via the `useLiveResource` hook: fetch on mount, visibility-aware polling (20s), and a manual **Refresh** button — so a request submitted on the previous screen is already present.
- Each row shows its cohort pointer inline when set: a *N variables* badge and/or the row-filter (`column op value`).
- Approved requests with a generated artifact show their expiry (`Expires <date>`, or an **Expired** badge once past `expires_at`) and an **Export via** dropdown (`ExportPathSelector`) offering four Unity Catalog export mechanisms — D2D Delta Sharing, Lakehouse Federation, Iceberg / UC REST API, Volumes. Each shows an inline description, a **BDC-fit** chip (*Most aligned* / *Also strong* / *Narrower fit*), and the shared FedRAMP-boundary note. This control is **educational**: it does not produce a raw file export.
- Selecting a path reveals a **Preview recipient view** button that opens an `ExportRecipeDialog` — a request-shaped, clearly **Simulated** "connection recipe" showing how a platform *outside* Databricks would consume the governed artifact via that path: a code/CLI/config snippet (federation SQL, `databricks fs` for Volumes, `curl` credential-vend for Iceberg REST, `delta_sharing` for D2D) plus a simulated recipient result, with the best-fit BDC consumer named. It substitutes this request's dataset, consent group, selected columns, and artifact table (`output_table`, else `governed.export_outputs.req_<id>`) into the snippet — **no cross-platform call is made and no data leaves the platform**.
- To shape these recipes, `GET /api/my-requests` also returns `output_table` and (via a `LEFT JOIN` to `study_catalog`) `consent_group`.

### 5.4 Steward Queue (`/steward-queue`) — steward only
- Read live from **`GET /api/steward-queue`** (uncached OBO) via `useLiveResource`: fetch on mount, visibility-aware polling (15s), a manual **Refresh** button, and an automatic re-pull after approve/reject — so newly submitted requests surface without a reload. The **OBO `steward_queue`** view still UC row-filters to zero rows for non-stewards. The view is **enriched** beyond the raw request columns with study context (`study_name`, `access_tier`, `dbgap_status`, `consent_group`) and the submitter's **live** DAR/access decision (`submitter_role`, `submitter_expiration_ts`, `submitter_decision`, `submitter_decision_basis`), computed with the same CASE logic as `export_decision` but scoped to `r.submitter` (via a `LEFT JOIN` to `study_catalog` + `user_dbgap_permissions`).
- Each pending row shows a visible **consent-group badge** (from the enriched `consent_group`) alongside the format/decision badges; the page's enforcement note states that approval re-validates that consent-group tag, not just project-level dbGaP status.
- Each request has a **View details** button opening a modal with four sections: **Requester** (account, dbGaP role, permission expiry), **DAR status for this dataset** (live decision badge + basis, access tier, dbGaP status, consent group), **Request details** (full justification, format, submitted date, request id), and **Requested export (cohort)** — the variables selected (or "All variables"), the row filter (or "None"), and a note that consent columns are appended to every row. The view exposes `selected_columns` and `cohort_filter` for this. Approve/Reject are available in the list and inside the modal.
- Approve/Reject send only an optional comment; steward identity is resolved server-side, and membership is re-verified server-side (403 `not_a_steward` otherwise). Showing the live decision is intentional: it reveals when a DAR was valid at submit but has since expired/been revoked.
- **On approval the app generates a real controlled output**: a per-request governed Delta table `governed.export_outputs.req_<id>` via `CREATE TABLE ... AS SELECT <projection>, <consent columns> FROM read_files(<dataset source dir>) [WHERE <filter>]` (real Unity Catalog lineage). The **cohort definition is applied here**, re-validated against the live source schema: the projection is a whitelist of real, backtick-quoted columns (empty → `*`), and the filter is built from the structured `{column, op, value}` (whitelisted column, fixed operator set, escaped/validated value) — **no stored string is ever executed as SQL**. **Consent travels with the data**: every row gets appended `_consent_group`, `_dbgap_accession`, `_access_tier`, `_exported_for`, `_access_expires_at`, `_request_id`, `_exported_at` (mirroring BDC's `_consents_` column). The table is tagged with `request_id`, `dataset`, `consent_group`, `access_tier`, `submitter`, `approved_by`, `expires_at`, `cohort_filtered`, `cohort_projected`. `output_table`, `output_url`, and `expires_at` (approval + `EXPORT_TTL_DAYS`, default 7) are stored on the request. Datasets with no source files are still approved but produce no downloadable artifact.

### 5.5 Audit (`/audit`)
Two clearly labeled panels, plus a stated **scope-limit footer** (same note as the About page):
1. **App-Reported Events** — `governed.default.audit_events` (SP query), with search + outcome filter (`submitted/approved/rejected/blocked/allowed`). Includes an **Egress path** column derived from `details.egress_path` (currently `direct_download` for download events; `—` otherwise). This lives in the `details` JSON today; a `TODO` in `sql/001_governance.sql` proposes promoting it to a first-class `egress_path` column.
2. **Platform Audit Log** — steward-only panel over **OBO `system_audit_governed`** (`system.access.audit` filtered to `governed.default.%`, `event_time DESC`), with the visible note *"Platform log may lag several minutes."* Columns: event time, user, service, action, target, status code.

### 5.6 Consent-Gated Data (`/consent`)
Demonstrates a **mock dbGaP/Fence consent-grants layer** driving a **real Unity Catalog row filter** — consent-group-level enforcement (not just project-level). Read live from **`GET /api/consent-demo`** (uncached OBO) so the row filter is evaluated as the real caller via `current_user()`.
- **Honest "mocked" label (never a live sync):** a prominent callout states *"Consent grants: manually seeded (no Fence API access)"* and points at the `source` column (`manual_seed_no_fence_access`). Only the grant data's *provenance* is mocked; the enforcement is real.
- **Your view of the Framingham cohort:** the rows of `governed.default.framingham_cohort` the caller can see after the row filter runs; an empty state explains the deny path ("this is the enforcement working, not an error").
- **Seeded consent grants:** the contents of `bdc_governance.dbgap_sync.user_consent_grants`, including the `source` column, so provenance is unmistakable.

**Data layer (`sql/002_mock_consent_grants.sql`).** A separate catalog `bdc_governance`, schema `dbgap_sync`:
- `user_consent_grants(user_email, consent_tag, granted_at, revoked_at, source)` — hand-seeded; `source` is always `manual_seed_no_fence_access`. Four rows demo allow (alice, bob), revoked-deny (carol), and wrong-tag-deny (dave).
- `has_active_consent(row_consent_tag)` — SQL UDF returning `EXISTS` of an active (non-revoked), matching grant for `current_user()`. The mechanism is identical to what a live Fence-synced grants table would drive.
- `governed.default.framingham_cohort` — a synthetic Framingham cohort carrying a `_consents_` column (8 rows tagged `tutorial-biolincc_framingham`, 2 tagged `other_study_not_in_demo`), with `SET ROW FILTER has_active_consent ON (_consents_)`.

> **Naming-mismatch note (resolved by decision):** the demo had no pre-existing `_consents_` column and no persistent Framingham table; the controlled datasets are `phs000298`/`phs000710` (`c#` consent groups), and per-request exports use a `_consent_group` column. A dedicated consent-gated `framingham_cohort` table was created for this demo rather than silently retagging existing data.
>
> **Real-account caveat:** the seed grants use fictional `@bdc-demo.org` emails while the filter keys on the real `current_user()`, so deployed real accounts hit the deny path (0 rows) unless a grant row is added for a real account. Intentional for the demo; add an explicit grant if an in-app allow demo is needed.

---

## 6. Egress / download boundary

There is no interactive exfiltration panel. The download boundary is enforced by real workspace configuration (results-download setting, IP access lists / network policies) and re-checked on every download (see `GET /api/exports/:id/download` in §7 — `403 downloads_disabled` when the real `enableResultsDownloading` setting is off). The `export_outputs` artifact table is never granted to users, so the app is the only path to the bytes.

---

## 7. Server API (`server/server.ts`)

Identity for every route comes from forwarded headers only. `userClient(req)` mints a caller-scoped `WorkspaceClient` from `x-forwarded-access-token` (production: 401 without it; dev: SP fallback, matching AppKit's own behavior).

| Method + path | Body | Success | Enforcement |
| --- | --- | --- | --- |
| `GET /api/me` | — | `200 {user}` | `x-forwarded-email`; dev fallback `alice@example.com`; else 401 |
| `GET /api/steward-queue` | — | `200 [rows]` | **Uncached** OBO read of `steward_queue` (row-filtered to stewards); `submitter_expiration_ts` coerced to number. 401 without identity |
| `GET /api/my-requests` | — | `200 [rows]` | **Uncached** OBO read of `export_requests WHERE submitter = current_user()`. 401 without identity |
| `GET /api/consent-demo` | — | `200 {cohort, grants}` | **Uncached** OBO read of `framingham_cohort` (UC row filter `has_active_consent` applied per caller) + the mock `user_consent_grants`. 401 without identity |
| `POST /api/export_requests` | `dataset, justification, format, selected_columns[], cohort_filter?` | `201 {record}` | **OBO re-check** of `export_decision` for the dataset; not `granted` → `403 access_denied` + `blocked` audit event. Submitter = forwarded email. Cohort stored as JSON (`selected_columns`, `cohort_filter`); applied/re-validated only at approval |
| `POST /api/export_requests/:id/approve` | `comment?` | `200 {updated}` | **OBO re-check** of `is_account_group_member('bdc-stewards')`; false → `403 not_a_steward` + `blocked` audit event. `404` if missing. Generates the governed `export_outputs` artifact (CTAS + tags), stores `output_table`/`expires_at` |
| `POST /api/export_requests/:id/reject` | `comment?` | `200 {updated}` | Same steward check |
| `GET /api/exports/:id/download` | — | `200` streamed CSV/JSON (`Content-Disposition: attachment`) | Re-validated in order (each denial audited `blocked`): 404 if not approved / no artifact; 403 `not_your_request` unless caller is submitter; **410 `export_expired`** past `expires_at`; **403 `access_revoked`** when the caller's live OBO `export_decision` is no longer `granted`; **403 `downloads_disabled`** when the real workspace setting is off. The SP reads the app-owned `export_outputs` table (never granted to users) and the app streams the bytes |

**Error contract:** invalid body → `400 invalid_request`; missing identity → `401 no_identity`; authorization failures → `403` with a specific error code as above.

### 7.1 Data freshness — why the request views are not read through the analytics cache

**Symptom.** A request submitted by an analyst did not appear in the steward queue (or the analyst's own list) until minutes/hours later or an app restart.

**Root cause (assessment).** The write path is synchronous and immediate — `POST /api/export_requests` runs the `INSERT` inline and only returns `201` after Unity Catalog commits, so there is no database/UC write lag. The lag was entirely in the *read* path:

- The AppKit **analytics plugin caches every query result in-memory for 1 hour** (`queryDefaults.ttl = 3600`, not overridable through `analytics({})` in this version). The cache key is per user + query + parameters.
- The client **`useAnalyticsQuery` hook fetches once and never refetches** — no polling, no refetch-on-focus, no post-mutation invalidation.
- Net effect: the first render of the steward queue was cached for up to an hour; a request submitted afterwards was invisible until the entry expired or the app process restarted (clearing the in-memory cache).
- A secondary, one-time contributor is SQL warehouse **cold-start** on the first query after idle.

**Fix.** The two volatile, write-driven views bypass the analytics cache entirely:

- **Server:** dedicated **uncached** Express routes `GET /api/steward-queue` and `GET /api/my-requests` run the same row-filtered, on-behalf-of SQL directly (`executeStatementWith(userClient(req).client, …)`). Enforcement is unchanged — the `steward_queue` view still row-filters to stewards, and `my-requests` still filters `submitter = current_user()`.
- **Client:** a small `useLiveResource(url, { intervalMs })` hook fetches on mount, polls only while the tab is visible (steward queue 15s, my requests 20s — the visibility gate avoids keeping the warehouse warm on background tabs), exposes a manual **Refresh** button, and the steward queue re-pulls immediately after an approve/reject.

**Not changed.** The Home-page stat band and the app-events audit table still use the cached analytics path (aggregate/overview data where a short staleness window is acceptable). The same live-endpoint pattern can be extended to them if needed.

---

## 8. Build & deployment

- `databricks.yml` sets `user_api_scopes: [sql]` — required for OBO query execution.
- `npm run build` does not require a live warehouse (committed `analytics.d.ts`); `npm run typegen` regenerates types and needs the warehouse.
- Apply `sql/001_governance.sql` once per workspace (metastore admin needed for the `system` catalog grants).
- Deploy via `databricks bundle deploy`.

## 9. Known limitations

- Serverless network policies (account-level, Enterprise tier) are not available on this workspace; the download re-validation therefore relies on the controls that *are* real here (results-download setting, IP access lists).
- The `system.access.audit` grants to `bdc-stewards` require a metastore admin; until granted, the platform panel works only for users with pre-existing system-table access (the OBO query enforces this per caller either way).
- Home-page stats and the app-events audit table run as the SP (aggregate/demo visibility); all permission-sensitive data paths are OBO.
- The analytics plugin's 1-hour in-memory result cache is not configurable in this AppKit version, so the write-driven request views deliberately bypass it via uncached live endpoints (§7.1); other read surfaces accept a short staleness window.
