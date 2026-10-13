-- 001_governance.sql
-- Real Unity Catalog enforcement for the Data Export Portal.
--
-- Prerequisites (account console / SCIM — cannot be done in SQL):
--   * Account-level groups `bdc-analysts` and `bdc-stewards` exist and are
--     assigned to this workspace.
--   * Test users are added/removed from those groups to exercise the app —
--     membership is the ONLY role switch; the app has no client-side role state.
--
-- Everything below is idempotent (CREATE OR REPLACE / GRANT).

-- ---------------------------------------------------------------------------
-- 1. Baseline table grants (groups, not individuals)
-- ---------------------------------------------------------------------------
GRANT USE CATALOG ON CATALOG governed TO `bdc-analysts`;
GRANT USE CATALOG ON CATALOG governed TO `bdc-stewards`;
GRANT USE SCHEMA ON SCHEMA governed.default TO `bdc-analysts`;
GRANT USE SCHEMA ON SCHEMA governed.default TO `bdc-stewards`;

GRANT SELECT ON TABLE governed.default.study_catalog TO `bdc-analysts`;
GRANT SELECT ON TABLE governed.default.study_catalog TO `bdc-stewards`;

GRANT SELECT, MODIFY ON TABLE governed.default.export_requests TO `bdc-analysts`;
GRANT SELECT, MODIFY ON TABLE governed.default.export_requests TO `bdc-stewards`;

GRANT SELECT ON TABLE governed.default.audit_events TO `bdc-stewards`;

-- Read access to the study data-file volume so a GRANTED analyst's OBO
-- read_files() preview on the Submit page actually succeeds. Target whatever
-- volume(s) study_catalog.volume_location points at; adjust the name if you
-- store the files elsewhere. (The Submit preview is gated on export_decision
-- being 'granted', but the read still runs OBO, so the volume grant is
-- required for the granted path to work.)
GRANT READ VOLUME ON VOLUME governed.default.study_catalog_files TO `bdc-analysts`;
GRANT READ VOLUME ON VOLUME governed.default.study_catalog_files TO `bdc-stewards`;

-- ---------------------------------------------------------------------------
-- 2. Self-enforcing decision view — NO user parameter anywhere.
--    (Replaces the previous governed.default.export_decision view, which
--    computed decisions for ALL users; this one is current_user()-scoped.)
--    Resolves permissions with current_user() only. Covers every dataset in
--    study_catalog:
--      * open_access       -> granted (no DAR required)
--      * unregistered      -> flagged_for_review
--      * controlled_access -> granted only when the caller has a matching,
--                             unexpired permission row for the dataset's
--                             consent group; denied otherwise.
--    expiration_ts is epoch seconds (BIGINT).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW governed.default.export_decision AS
SELECT
  sc.dataset_id,
  sc.access_tier,
  sc.dbgap_status,
  current_user()                            AS user_id,
  COALESCE(p.role, '')                      AS role,
  COALESCE(p.expiration_ts, 0)              AS expiration_ts,
  CASE
    WHEN sc.access_tier = 'open_access' THEN 'granted'
    WHEN sc.access_tier = 'unregistered' THEN 'flagged_for_review'
    WHEN p.user_id IS NOT NULL AND (p.expiration_ts IS NULL OR p.expiration_ts > unix_timestamp()) THEN 'granted'
    WHEN p.user_id IS NOT NULL THEN 'denied'
    ELSE 'denied'
  END AS decision,
  CASE
    WHEN sc.access_tier = 'open_access' THEN 'Public/open-access dataset — no DAR required'
    WHEN sc.access_tier = 'unregistered' THEN 'Dataset not yet linked to a dbGaP study — no consent group to verify against'
    WHEN p.user_id IS NOT NULL AND (p.expiration_ts IS NULL OR p.expiration_ts > unix_timestamp()) THEN 'Approved DAR matches dataset consent group and has not expired'
    WHEN p.user_id IS NOT NULL THEN 'DAR for this dataset/consent group has expired'
    ELSE 'No matching approved DAR found for this dataset/consent group'
  END AS decision_basis
FROM governed.default.study_catalog sc
LEFT JOIN governed.default.user_dbgap_permissions p
  ON  p.dataset_id    = sc.dataset_id
  AND p.consent_group = sc.consent_group
  AND p.user_id       = current_user();

GRANT SELECT ON VIEW governed.default.export_decision TO `bdc-analysts`;
GRANT SELECT ON VIEW governed.default.export_decision TO `bdc-stewards`;

-- ---------------------------------------------------------------------------
-- 3. All-users decision view for stewards. Row-filtered by group membership:
--    returns ZERO rows for anyone outside bdc-stewards, regardless of what
--    the app requests.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW governed.default.export_decision_all AS
SELECT
  sc.dataset_id,
  sc.access_tier,
  sc.dbgap_status,
  COALESCE(p.user_id, '')      AS user_id,
  COALESCE(p.role, '')         AS role,
  COALESCE(p.expiration_ts, 0) AS expiration_ts,
  CASE
    WHEN sc.access_tier = 'open_access' THEN 'granted'
    WHEN sc.access_tier = 'unregistered' THEN 'flagged_for_review'
    WHEN p.user_id IS NOT NULL AND (p.expiration_ts IS NULL OR p.expiration_ts > unix_timestamp()) THEN 'granted'
    WHEN p.user_id IS NOT NULL THEN 'denied'
    ELSE 'denied'
  END AS decision,
  CASE
    WHEN sc.access_tier = 'open_access' THEN 'Public/open-access dataset — no DAR required'
    WHEN sc.access_tier = 'unregistered' THEN 'Dataset not yet linked to a dbGaP study — no consent group to verify against'
    WHEN p.user_id IS NOT NULL AND (p.expiration_ts IS NULL OR p.expiration_ts > unix_timestamp()) THEN 'Approved DAR matches dataset consent group and has not expired'
    WHEN p.user_id IS NOT NULL THEN 'DAR for this dataset/consent group has expired'
    ELSE 'No matching approved DAR found for this dataset/consent group'
  END AS decision_basis
FROM governed.default.study_catalog sc
LEFT JOIN governed.default.user_dbgap_permissions p
  ON  p.dataset_id    = sc.dataset_id
  AND p.consent_group = sc.consent_group
WHERE is_account_group_member('bdc-stewards');

GRANT SELECT ON VIEW governed.default.export_decision_all TO `bdc-analysts`;
GRANT SELECT ON VIEW governed.default.export_decision_all TO `bdc-stewards`;

-- ---------------------------------------------------------------------------
-- 4. Row-filtered steward queue. Zero rows for non-stewards regardless of
--    what the app requests.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW governed.default.steward_queue AS
SELECT
  r.request_id,
  r.submitter,
  r.dataset,
  r.justification,
  r.format,
  r.status,
  r.created_at,
  r.steward,
  r.steward_comment,
  r.approved_at,
  r.rejected_at,
  r.output_url,
  r.selected_columns,
  r.cohort_filter,
  sc.study_name,
  sc.access_tier,
  sc.dbgap_status,
  sc.consent_group,
  COALESCE(p.role, '')          AS submitter_role,
  COALESCE(p.expiration_ts, 0)  AS submitter_expiration_ts,
  CASE
    WHEN sc.access_tier = 'open_access' THEN 'granted'
    WHEN sc.access_tier = 'unregistered' THEN 'flagged_for_review'
    WHEN p.user_id IS NOT NULL AND (p.expiration_ts IS NULL OR p.expiration_ts > unix_timestamp()) THEN 'granted'
    WHEN p.user_id IS NOT NULL THEN 'denied'
    ELSE 'denied'
  END AS submitter_decision,
  CASE
    WHEN sc.access_tier = 'open_access' THEN 'Public/open-access dataset — no DAR required'
    WHEN sc.access_tier = 'unregistered' THEN 'Dataset not yet linked to a dbGaP study — no consent group to verify against'
    WHEN p.user_id IS NOT NULL AND (p.expiration_ts IS NULL OR p.expiration_ts > unix_timestamp()) THEN 'Approved DAR matches dataset consent group and has not expired'
    WHEN p.user_id IS NOT NULL THEN 'DAR for this dataset/consent group has expired'
    ELSE 'No matching approved DAR found for this dataset/consent group'
  END AS submitter_decision_basis
FROM governed.default.export_requests r
LEFT JOIN governed.default.study_catalog sc
  ON sc.dataset_id = r.dataset
LEFT JOIN governed.default.user_dbgap_permissions p
  ON  p.dataset_id    = sc.dataset_id
  AND p.consent_group = sc.consent_group
  AND p.user_id       = r.submitter
WHERE r.status = 'pending'
  AND is_account_group_member('bdc-stewards');

GRANT SELECT ON VIEW governed.default.steward_queue TO `bdc-analysts`;
GRANT SELECT ON VIEW governed.default.steward_queue TO `bdc-stewards`;

-- ---------------------------------------------------------------------------
-- 4b. Role-scoped app audit log. Stewards see EVERY app-reported event;
--     analysts see ONLY their own (user = current_user()). The row filter is
--     enforced in the view and the app queries it OBO, so current_user() and
--     group membership evaluate as the end user — an analyst cannot widen the
--     result set from the client. Analysts get SELECT on this VIEW only, never
--     on the base audit_events table (which stays steward-only, see §1).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW governed.default.audit_events_scoped AS
SELECT
  event_id,
  `timestamp`,
  `user`,
  action_type,
  resource,
  outcome,
  details
FROM governed.default.audit_events
WHERE is_account_group_member('bdc-stewards')
   OR `user` = current_user();

GRANT SELECT ON VIEW governed.default.audit_events_scoped TO `bdc-analysts`;
GRANT SELECT ON VIEW governed.default.audit_events_scoped TO `bdc-stewards`;

-- ---------------------------------------------------------------------------
-- 5. Platform audit log access (system.access must already be enabled at the
--    metastore level — it is on this workspace).
--
--    NOTE: these grants require MANAGE on the system catalog (metastore
--    admin). They FAILED when run as a workspace admin on this workspace —
--    a metastore admin must run them. Until then, the Platform Audit Log
--    panel only works for users who already have system-table access
--    (queries run OBO, so UC enforces this per user either way).
-- ---------------------------------------------------------------------------
GRANT USE CATALOG ON CATALOG system TO `bdc-stewards`;
GRANT USE SCHEMA ON SCHEMA system.access TO `bdc-stewards`;
GRANT SELECT ON TABLE system.access.audit TO `bdc-stewards`;

-- ---------------------------------------------------------------------------
-- 5b. Real controlled-output artifacts.
--
--     On approval the app materializes a per-request governed Delta table under
--     governed.export_outputs (CTAS from the study's source files) and streams
--     it back through the app at download time — after re-validating status,
--     expiry, submitter, the caller's live export_decision (OBO), and the
--     workspace results-download setting. There is deliberately NO grant on
--     export_outputs to analysts/stewards: the raw artifact is reachable ONLY
--     through the app, which is the enforcement point.
--
--     The app runs as its service principal (application/client id below) for
--     these writes, so the SP — not the groups — needs privileges here. Replace
--     the id if you redeploy the app under a different service principal.
--     App service principal: app-60i4y0 dlp-demo
-- ---------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS governed.export_outputs
  COMMENT 'Per-request controlled export artifacts, reachable only via the app.';

GRANT USE SCHEMA ON SCHEMA governed.export_outputs TO `f359d298-69b8-4fb5-ae24-46eda7fe60a8`;
GRANT CREATE TABLE ON SCHEMA governed.export_outputs TO `f359d298-69b8-4fb5-ae24-46eda7fe60a8`;
GRANT MODIFY ON SCHEMA governed.export_outputs TO `f359d298-69b8-4fb5-ae24-46eda7fe60a8`;
GRANT SELECT ON SCHEMA governed.export_outputs TO `f359d298-69b8-4fb5-ae24-46eda7fe60a8`;

-- The SP runs the CTAS from read_files() on the source volume, so it needs the
-- same READ VOLUME the OBO callers already have, plus SELECT on study_catalog
-- to resolve each dataset's volume_location during artifact generation.
GRANT READ VOLUME ON VOLUME governed.default.study_catalog_files TO `f359d298-69b8-4fb5-ae24-46eda7fe60a8`;
GRANT SELECT ON TABLE governed.default.study_catalog TO `f359d298-69b8-4fb5-ae24-46eda7fe60a8`;

-- Columns that track the generated artifact and its lifetime. Run once;
-- re-running errors because the columns already exist (Databricks ALTER TABLE
-- does not support ADD COLUMNS IF NOT EXISTS).
ALTER TABLE governed.default.export_requests
  ADD COLUMNS (output_table STRING, expires_at TIMESTAMP);

-- Cohort definition (PIC-SURE Query-ID analog): the variables the requester
-- chose to include (JSON array) and an optional structured row filter (JSON
-- {column, op, value}). Stored as data only; the app re-validates them against
-- the real source schema and builds safe SQL at artifact generation time.
ALTER TABLE governed.default.export_requests
  ADD COLUMNS (selected_columns STRING, cohort_filter STRING);

-- TODO(egress): the app currently records which of the three egress paths
-- (direct_download / volume_copy / sbfs_mount) an event used inside the
-- audit_events.details JSON. Promote this to a first-class column so it is
-- queryable/filterable without JSON parsing, e.g.:
--   ALTER TABLE governed.default.audit_events ADD COLUMNS (egress_path STRING);
-- Only direct_download is functional today; volume_copy and sbfs_mount are
-- planned. Remember to update audit_events_scoped and any audit views/queries.

-- ---------------------------------------------------------------------------
-- 6. Demo seed: the permissions table only contains synthetic users
--    (jane.doe@example.org etc.), so a real logged-in user would be denied
--    everything controlled. Seed one unexpired grant for the demo account so
--    real current_user() evaluation can show BOTH granted (phs000298) and
--    denied (phs000710) controlled-access outcomes.
-- ---------------------------------------------------------------------------
MERGE INTO governed.default.user_dbgap_permissions t
USING (
  SELECT 'DBC_PROFILE' AS user_id,
         'phs000298'              AS dataset_id,
         'c2'                     AS consent_group,
         'downloader'             AS role,
         CAST(4102444800 AS BIGINT) AS expiration_ts,
         'steward'                AS poc_role
) s
ON t.user_id = s.user_id AND t.dataset_id = s.dataset_id AND t.consent_group = s.consent_group
WHEN NOT MATCHED THEN INSERT *;

-- ---------------------------------------------------------------------------
-- 7. poc_role hygiene: for REAL workspace users, poc_role must mirror actual
--    account-group membership (bdc-stewards -> 'steward', bdc-analysts only ->
--    'analyst'; membership in both -> 'steward', the highest role, wins).
--    is_account_group_member() only evaluates for the current caller, so this
--    cannot be derived in SQL for arbitrary rows — run scripts/sync_poc_role.sh
--    after changing group membership. Synthetic demo users (no real account)
--    keep their seeded poc_role. Note the app itself never reads poc_role for
--    authorization; UC group membership is the source of truth.
-- ---------------------------------------------------------------------------
