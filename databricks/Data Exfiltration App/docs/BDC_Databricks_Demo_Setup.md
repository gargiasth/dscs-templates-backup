# BioData Catalyst × Databricks: dbGaP Authorization Demo Setup

> **Purpose:** Demonstrate how NIH dbGaP permissions, surfaced via the Researcher Auth Service (RAS), can be enforced natively inside Databricks Unity Catalog — providing authorization-level data exfiltration protection beyond network controls.

---

## Overview

NHLBI BioData Catalyst (BDC) controls access to sensitive genomic and phenotypic data through the NIH database of Genotypes and Phenotypes (dbGaP). Users must hold an approved Data Access Request (DAR) for each study they work with.

This demo shows how that approval model can be **pulled into Databricks at the authorization layer**, so that data governance travels with the data — not just with the network perimeter.

### Why this matters

| Layer | What it protects | What it misses |
|---|---|---|
| **Network controls** (VPC, Private Link, egress firewall) | Prevents data leaving the environment | Cannot stop an authorized user accessing a study they shouldn't |
| **Authorization controls** (Unity Catalog + dbGaP permissions) | Enforces per-study, per-consent-group access at the data object level | Must be combined with network controls for full coverage |

**Both layers are required. The authorization layer is where dbGaP compliance lives.**

---

## Architecture

```
Researcher (eRA Commons credentials)
        │
        ▼
NIH Researcher Auth Service (RAS)
  └── Emits GA4GH Passport Token
      └── payload: { phs_id, consent_group, role, expiry }
        │
        ▼ token
Databricks Unity Catalog
  ├── ABAC tags         → phs_id-level study access
  ├── Row filters       → per consent group (e.g. GRU, HMB, DS-CVD)
  ├── Column masks      → mask direct genomic identifiers
  └── Audit logging     → all access recorded and traceable
        │
        ▼
Audited data access — bounded by the researcher's approved DAR
```

---

## Prerequisites

Before running the demo, confirm the following are in place.

### Researcher-side
- [ ] Active [eRA Commons account](https://era.nih.gov/register-accounts/understanding-era-commons-accounts.htm)
- [ ] Approved dbGaP Data Access Request (DAR) for at least one study (e.g. `phs000298`)
- [ ] Logged into [dbGaP Authorized Access](https://dbgap.ncbi.nlm.nih.gov/aa/wga.cgi?page=login) at least once
- [ ] IT environment confirmed compliant with **NIST SP 800-171** (required as of Jan 25, 2025 for all NIH controlled-access genomic data)

### Databricks environment
- [ ] Databricks workspace with **Unity Catalog** enabled
- [ ] Admin access to configure catalog permissions, SCIM, and cluster policies
- [ ] Private Link / VPC egress controls configured (network layer — additive to auth)
- [ ] Audit logging enabled at account and workspace level

---

## Step 1 — Provision the NIH RAS / OAuth Integration

NIH RAS issues tokens via **OAuth 2.0 / OpenID Connect** carrying a GA4GH passport visa with dbGaP permissions.

```json
// Example ras_dbgap_permissions payload in the token
{
  "ras_dbgap_permissions": [
    {
      "consent_name": "General Research Use",
      "phs_id": "phs000298",
      "version": "v4",
      "participant_set": "p3",
      "consent_group": "c2",
      "role": "pi",
      "expiration": 1726262466
    }
  ]
}
```

**Action:** Register Databricks as an OAuth relying party with NIH RAS.
- RAS staging endpoint: `https://stsstg.nih.gov`
- Scopes required: `openid ga4gh_passport_v1`
- Refer to [NIH RAS Service Offerings](https://auth.nih.gov/docs/RAS/serviceofferings.html) for client registration

---

## Step 2 — Sync Users via SCIM

Configure SCIM provisioning so that dbGaP-approved researchers are automatically synced into Databricks as users/groups.

```python
# Databricks SCIM API — create a group per dbGaP study
# Map each phs_id to a Databricks group

POST /api/2.0/preview/scim/v2/Groups
{
  "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
  "displayName": "dbgap-phs000298-GRU",
  "members": [
    { "value": "<databricks_user_id>" }
  ]
}
```

> **Key rule:** Only PIs with an approved DAR, and lab members explicitly granted "designated downloader" status in dbGaP, should be synced. Collaborators listed on the DAR application do **not** automatically receive access.

---

## Step 3 — Tag Datasets with dbGaP Attributes (ABAC)

In Unity Catalog, tag each table or schema with its corresponding study and consent group metadata.

```sql
-- Tag a table with its dbGaP study identifier and consent group
ALTER TABLE biodata_catalog.topmed.whole_genome_sequences
SET TAGS ('phs_id' = 'phs000298', 'consent_group' = 'GRU', 'data_tier' = 'controlled');

-- Tag an open-access summary statistics table
ALTER TABLE biodata_catalog.topmed.summary_stats
SET TAGS ('phs_id' = 'phs000298', 'data_tier' = 'open');
```

Then configure **attribute-based access control (ABAC)** policies that grant access based on these tags, keyed to the Databricks groups created in Step 2.

```sql
-- Grant the GRU consent group to the corresponding Databricks group
GRANT SELECT ON TABLE biodata_catalog.topmed.whole_genome_sequences
TO `dbgap-phs000298-GRU`;
```

---

## Step 4 — Apply Row-Level Security (Consent Group Filtering)

Use Unity Catalog **row filters** to ensure users only see participant rows matching their approved consent group — even within a table they have table-level access to.

```sql
-- Create a row filter function keyed to consent group membership
CREATE FUNCTION biodata_catalog.governance.consent_group_filter(consent_group STRING)
RETURN is_member(CONCAT('dbgap-', current_catalog(), '-', consent_group));

-- Attach the row filter to the table
ALTER TABLE biodata_catalog.topmed.participant_phenotypes
SET ROW FILTER biodata_catalog.governance.consent_group_filter ON (consent_group);
```

---

## Step 5 — Apply Column Masks (Identifier Protection)

Use **column masks** to protect direct genomic and personal identifiers for users who have phenotypic access but not full sequencing access.

```sql
-- Mask sample IDs for users without full genomic access
CREATE FUNCTION biodata_catalog.governance.mask_sample_id(sample_id STRING)
RETURN CASE
  WHEN is_member('dbgap-phs000298-GRU') THEN sample_id
  ELSE '***MASKED***'
END;

ALTER TABLE biodata_catalog.topmed.participant_phenotypes
ALTER COLUMN sample_id
SET MASK biodata_catalog.governance.mask_sample_id;
```

---

## Step 6 — Configure Token Expiration Enforcement

dbGaP DARs expire. The RAS token carries an `expiration` field that must be enforced — access must be revoked when a DAR lapses, not just at login.

**Recommended approach:**
- Schedule a daily Databricks job to validate active RAS tokens against dbGaP
- Automatically remove users from groups (Step 2) when their token `expiration` timestamp has passed
- Log all revocations to the Unity Catalog audit table

```python
# Pseudocode: daily DAR expiry check
for user in databricks_users:
    ras_token = fetch_ras_token(user.era_commons_id)
    for permission in ras_token["ras_dbgap_permissions"]:
        if permission["expiration"] < time.time():
            remove_from_group(user, f"dbgap-{permission['phs_id']}-{permission['consent_group']}")
            log_revocation(user, permission)
```

---

## Step 7 — Verify Audit Logging

All data access must be logged. Unity Catalog system tables capture this automatically.

```sql
-- Query audit logs for controlled-access table reads
SELECT
  event_time,
  user_name,
  action_name,
  request_params.table_full_name AS table_accessed
FROM system.access.audit
WHERE action_name = 'commandSubmit'
  AND request_params.table_full_name LIKE 'biodata_catalog.topmed.%'
ORDER BY event_time DESC;
```

---

## Demo Validation Checklist

Run through each scenario to confirm the authorization model is working correctly.

| Scenario | Expected result |
|---|---|
| User with approved DAR for `phs000298 GRU` queries the whole genome table | ✅ Returns rows for their consent group only |
| Same user queries a table for `phs000301` (no DAR) | ❌ Permission denied at ABAC level |
| User with phenotype-only access queries `sample_id` column | Returns `***MASKED***` |
| DAR expiration date passes → user re-queries | ❌ Group membership removed; access denied |
| Admin queries audit log | Full record of all access attempts, including denials |

---

## Key Limitations to Communicate in the Demo

1. **Not turnkey.** The NIH RAS ↔ Databricks OAuth integration requires custom client registration and SCIM configuration — it does not work out of the box.

2. **Tagging discipline is required.** Every dataset must be tagged with `phs_id` and `consent_group` for ABAC to work. This is a data governance process, not just a technical one.

3. **Collaborator access is not automatic.** Only PIs and designated downloaders get through — external collaborators must apply through their own institution's dbGaP process.

4. **NIST 800-171 compliance is mandatory** for the compute environment hosting controlled-access data (as of Jan 25, 2025). Databricks can satisfy most controls, but the workspace configuration must be validated.

5. **Network controls are still required.** Authorization controls govern *who sees what*; network controls (VPC, Private Link, egress rules) govern *where data can travel*. Both are needed for a compliant deployment.

---

## References

- [BioData Catalyst Documentation](https://bdcatalyst.gitbook.io/biodata-catalyst-documentation)
- [NIH RAS Service Offerings](https://auth.nih.gov/docs/RAS/serviceofferings.html)
- [NIH Researcher Auth Service Initiative](https://datascience.nih.gov/researcher-auth-service-initiative)
- [Databricks Data Exfiltration Protection](https://docs.databricks.com/aws/en/security/network/data-exfiltration-protection/)
- [Unity Catalog Row Filters and Column Masks](https://docs.databricks.com/aws/en/security/network/data-exfiltration-protection/)
- [dbGaP Data Access Request Guide](https://grants.nih.gov/policy-and-compliance/policy-topics/sharing-policies/accessing-data/dbgap)
- [NIST SP 800-171 Requirements (NIH Notice NOT-OD-24-157)](https://grants.nih.gov/grants/guide/notice-files/NOT-OD-24-157.html)
