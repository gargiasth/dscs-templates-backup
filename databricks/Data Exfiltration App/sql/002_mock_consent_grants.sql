-- =============================================================================
-- 002_mock_consent_grants.sql
-- MOCK consent-grants layer standing in for a Gen3/Fence -> dbGaP authorization
-- sync we do NOT have API access to in this demo.
--
-- IMPORTANT: This is NOT a live integration.
--   * The grant DATA is seeded by hand (see the `source` column, which literally
--     reads 'manual_seed_no_fence_access').
--   * The ENFORCEMENT MECHANISM (the has_active_consent row filter) is REAL and
--     would work identically against a live Fence-synced table later.
-- Only the provenance of the grant rows is mocked; the governance logic is not.
--
-- In the real BDC ecosystem, Gen3's Fence service resolves dbGaP approvals into
-- resources shaped like `study_id.consent_group` (e.g. phs001826.c2), synced
-- periodically from dbGaP telemetry files. Here we seed consent_tag values by
-- hand instead of faking that sync.
-- =============================================================================

CREATE CATALOG IF NOT EXISTS bdc_governance;
CREATE SCHEMA IF NOT EXISTS bdc_governance.dbgap_sync;

-- ---------------------------------------------------------------------------
-- TASK 1: the mock grants table. CREATE OR REPLACE so re-running reseeds
-- cleanly. `source` is always 'manual_seed_no_fence_access' for now.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE bdc_governance.dbgap_sync.user_consent_grants (
  user_email  STRING,
  consent_tag STRING,
  granted_at  TIMESTAMP,
  revoked_at  TIMESTAMP,   -- nullable; NULL means still active
  source      STRING       -- always 'manual_seed_no_fence_access' for now
)
COMMENT 'MOCK dbGaP/Fence consent grants. Rows seeded by hand (no Fence API access) - see the source column. Enforcement via has_active_consent() is real and would work identically against a live-synced table.';

INSERT INTO bdc_governance.dbgap_sync.user_consent_grants VALUES
  ('alice.researcher@bdc-demo.org', 'tutorial-biolincc_framingham', TIMESTAMP '2026-06-01 00:00:00', CAST(NULL AS TIMESTAMP),         'manual_seed_no_fence_access'),
  ('bob.pi@bdc-demo.org',           'tutorial-biolincc_framingham', TIMESTAMP '2026-05-15 00:00:00', CAST(NULL AS TIMESTAMP),         'manual_seed_no_fence_access'),
  ('carol.revoked@bdc-demo.org',    'tutorial-biolincc_framingham', TIMESTAMP '2026-01-10 00:00:00', TIMESTAMP '2026-07-10 00:00:00', 'manual_seed_no_fence_access'),
  ('dave.otherstudy@bdc-demo.org',  'other_study_not_in_demo',      TIMESTAMP '2026-06-01 00:00:00', CAST(NULL AS TIMESTAMP),         'manual_seed_no_fence_access');

-- ---------------------------------------------------------------------------
-- TASK 2: the REAL row-filter function. Returns TRUE when the CURRENT user has
-- an active (non-revoked) grant whose consent_tag matches the row's tag.
-- The same function would apply unchanged to a live Fence-synced grants table.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION bdc_governance.dbgap_sync.has_active_consent(row_consent_tag STRING)
RETURNS BOOLEAN
RETURN EXISTS (
  SELECT 1 FROM bdc_governance.dbgap_sync.user_consent_grants g
  WHERE g.user_email = current_user()
    AND g.consent_tag = row_consent_tag
    AND (g.revoked_at IS NULL OR g.revoked_at > current_timestamp())
);

-- ---------------------------------------------------------------------------
-- TASK 3: apply the row filter to the demo cohort table.
--
-- NAMING-MISMATCH NOTE (flagged and resolved): the demo had NO table with a
-- `_consents_` column and NO persistent Framingham cohort export. The
-- controlled datasets in study_catalog are phs000298 (c2) / phs000710 (c1),
-- and exports are ephemeral per-request tables under governed.export_outputs
-- with a `_consent_group` column. Per an explicit decision, we create a
-- persistent, consent-gated Framingham demo table carrying the `_consents_`
-- column (values = the Fence-style tag) and apply the row filter to it.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE governed.default.framingham_cohort (
  subject_id STRING,
  sex        STRING,
  age        INT,
  sysbp      DOUBLE,
  diabp      DOUBLE,
  bmi        DOUBLE,
  cur_smoker BOOLEAN,
  glucose    INT,
  diabetes   BOOLEAN,
  cvd_event  BOOLEAN,
  _consents_ STRING
)
COMMENT 'Synthetic Framingham-style demo cohort for the mock consent-grants row-filter demo. _consents_ carries the Fence-style consent tag; row-filtered by bdc_governance.dbgap_sync.has_active_consent.';

-- 8 rows tagged for the Framingham consent group + 2 rows tagged for a different
-- study, so the demo shows consent-GROUP-level (not project-level) filtering:
--   alice / bob -> 8 rows   carol (revoked) -> 0   dave (other tag) -> 2
INSERT INTO governed.default.framingham_cohort VALUES
  ('F001','F',61,132,84,28.5,false, 87,false,true, 'tutorial-biolincc_framingham'),
  ('F002','M',55,145,95,30.1,true,  92,false,true, 'tutorial-biolincc_framingham'),
  ('F003','F',48,128,80,24.3,false, 78,false,false,'tutorial-biolincc_framingham'),
  ('F004','M',67,150,90,27.8,false,110,true, true, 'tutorial-biolincc_framingham'),
  ('F005','F',52,138,88,26.0,true,  85,false,false,'tutorial-biolincc_framingham'),
  ('F006','M',44,120,76,23.1,false, 80,false,false,'tutorial-biolincc_framingham'),
  ('F007','F',59,142,92,31.4,true,  99,true, true, 'tutorial-biolincc_framingham'),
  ('F008','M',63,135,85,29.2,false, 90,false,false,'tutorial-biolincc_framingham'),
  ('O001','F',50,130,82,25.5,false, 88,false,false,'other_study_not_in_demo'),
  ('O002','M',58,140,89,28.0,true,  95,true, true, 'other_study_not_in_demo');

-- The real enforcement: identical to what a live-synced grants table would drive.
ALTER TABLE governed.default.framingham_cohort
  SET ROW FILTER bdc_governance.dbgap_sync.has_active_consent ON (_consents_);

-- ---------------------------------------------------------------------------
-- Grants so the app can read OBO (as the logged-in analyst/steward) and the
-- service principal can read for app-owned operations. Row-filter evaluation
-- needs EXECUTE on the function and SELECT on the grants table.
-- ---------------------------------------------------------------------------
GRANT USE CATALOG ON CATALOG bdc_governance TO `bdc-analysts`;
GRANT USE CATALOG ON CATALOG bdc_governance TO `bdc-stewards`;
GRANT USE CATALOG ON CATALOG bdc_governance TO `f359d298-69b8-4fb5-ae24-46eda7fe60a8`;
GRANT USE SCHEMA ON SCHEMA bdc_governance.dbgap_sync TO `bdc-analysts`;
GRANT USE SCHEMA ON SCHEMA bdc_governance.dbgap_sync TO `bdc-stewards`;
GRANT USE SCHEMA ON SCHEMA bdc_governance.dbgap_sync TO `f359d298-69b8-4fb5-ae24-46eda7fe60a8`;
GRANT EXECUTE ON FUNCTION bdc_governance.dbgap_sync.has_active_consent TO `bdc-analysts`;
GRANT EXECUTE ON FUNCTION bdc_governance.dbgap_sync.has_active_consent TO `bdc-stewards`;
GRANT EXECUTE ON FUNCTION bdc_governance.dbgap_sync.has_active_consent TO `f359d298-69b8-4fb5-ae24-46eda7fe60a8`;
GRANT SELECT ON TABLE bdc_governance.dbgap_sync.user_consent_grants TO `bdc-analysts`;
GRANT SELECT ON TABLE bdc_governance.dbgap_sync.user_consent_grants TO `bdc-stewards`;
GRANT SELECT ON TABLE bdc_governance.dbgap_sync.user_consent_grants TO `f359d298-69b8-4fb5-ae24-46eda7fe60a8`;
GRANT SELECT ON TABLE governed.default.framingham_cohort TO `bdc-analysts`;
GRANT SELECT ON TABLE governed.default.framingham_cohort TO `bdc-stewards`;
GRANT SELECT ON TABLE governed.default.framingham_cohort TO `f359d298-69b8-4fb5-ae24-46eda7fe60a8`;

-- NOTE (real-account caveat): the seed grants use fictional @bdc-demo.org
-- emails, while the row filter keys on current_user() = the real logged-in
-- account. In the deployed app, real accounts therefore hit the DENY path
-- (0 rows) unless a grant row is added for a real account. This is intentional
-- for the demo; add a real grant explicitly if an in-app ALLOW demo is needed.
