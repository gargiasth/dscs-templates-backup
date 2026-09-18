# Access Control Checklist — Databricks Environment Setup

**Scope:** Configuration steps to enforce "compute allowed, exfiltration blocked" for the POC — Free Edition (zero-cost validation) and Sandbox (funded/full workspace, closer to a real deployment). Each item notes whether it's available as a *real, enforced* control or a *demo-only workaround* in each environment. Where FE can't enforce something, say so plainly — don't let the demo imply FE proves more than it does.

**Legend:** ✅ enforced control · ⚠️ workaround/simulated · ❌ not available

---

## 1. Identity & Authentication

- [ ] Confirm how users authenticate into the workspace
  - **Free Edition:** ✅ email OTP / Google / Microsoft sign-in handles auth automatically — no custom login screen needed
  - **Sandbox:** ✅ SSO via SAML/OIDC against your IdP; SCIM syncs users/groups automatically
- [ ] Define Analyst and Steward personas as real identities (not just app-level labels)
  - **Free Edition:** ⚠️ FE has no SSO/SCIM and no account console — you can't provision real IdP-backed groups. Use two real Free Edition user accounts (or workspace-local groups) mapped to `analyst-group` / `steward-group`, and be explicit in the demo that group membership is manual here.
  - **Sandbox:** ✅ SCIM-provisioned account-level groups, synced from IdP
- [ ] Retrieve current user identity in-app via `WorkspaceClient().current_user.me()` rather than a custom login form
  - Both environments: ✅

---

## 2. Unity Catalog Foundation

- [ ] Confirm Unity Catalog is enabled (default for any workspace created after Nov 2023)
  - Both environments: ✅
- [ ] Create catalog/schema structure mirroring real consent-group boundaries (e.g. `restricted`, `approved`, `governed`, `export_outputs` schemas)
  - Both environments: ✅ — this is the same regardless of tier
- [ ] Metastore admin role assignment
  - **Free Edition:** ⚠️ one metastore per account, no account console — admin role is effectively "whoever owns the FE account"
  - **Sandbox:** ✅ dedicated metastore admin role, separable from workspace admins

---

## 3. Table-Level Grants (the core access boundary)

- [ ] `GRANT SELECT` on approved views only to the analyst group — **do not grant SELECT on raw tables**
  - Both environments: ✅ real Unity Catalog `GRANT`, enforced at query time, not a UI hide
- [ ] Confirm analyst query against a raw table fails with a real permissions error (not silently filtered)
  - Both environments: ✅ — this is the test that proves it's not cosmetic
- [ ] Steward group retains `SELECT` on raw + approved + governance tables
  - Both environments: ✅

---

## 4. Row-Level & Column-Level Security

- [ ] Build dynamic views over raw tables using `current_user()` to mask/filter sensitive fields
  - Both environments: ✅ supported; note the Databricks Runtime requirement — dynamic views on **standard/shared** access mode compute (not single-user clusters, which don't support them)
- [ ] Verify masking behaves differently per persona (analyst sees masked fields, steward sees raw)
  - Both environments: ✅

---

## 5. Compute Access Mode (closing the notebook/cluster bypass)

- [ ] Confirm compute uses **standard** or **dedicated** access mode — never a legacy single-user cluster with Table ACLs bypassed
  - Both environments: ✅
- [ ] Restrict analyst persona to **no direct notebook or interactive cluster access** — app-only
  - **Free Edition:** ⚠️ FE gives every user notebook access by default; there's no account-level compute policy to lock this down per group. You enforce this by *convention* (the analyst's app has no notebook link) rather than a hard platform block.
  - **Sandbox:** ✅ cluster/notebook access can be restricted per group via workspace permissions and compute policies

---

## 6. Export / Download Prevention (the headline control)

- [ ] No `WRITE` grant on any external location for the analyst group — blocks `COPY INTO` / DataFrame writes to arbitrary storage
  - **Free Edition:** ✅ *by default* — FE doesn't support custom workspace storage locations or external locations at all, so this path is closed without any configuration
  - **Sandbox:** ✅ but requires deliberate configuration — external locations exist and must be explicitly withheld from the analyst group
- [ ] Restrict result downloads from the SQL editor / SQL Warehouse
  - **Free Edition:** ⚠️ verify directly in workspace admin settings — FE has "no compliance enforcement or security customization," so this may not be exposed as an admin-configurable toggle. Don't assert it's enforced until you've checked it live.
  - **Sandbox:** ✅ configurable at the SQL Warehouse / workspace level
- [ ] No native download button (`st.download_button` or equivalent) on raw or unapproved views in the app UI
  - Both environments: ✅ (this is app-code, not a platform setting — cheap to get right, and worth stating clearly that this alone is *not* the control, Unity Catalog grants above are)
- [ ] Only legitimate export path: analyst submits request → steward approves → controlled output generated
  - Both environments: ✅ — build this as app workflow + a `governed.export_requests` Delta table, not in-memory state

---

## 7. Network & Egress Controls

- [ ] Outbound network restrictions from compute to arbitrary internet destinations
  - **Free Edition:** ⚠️ FE already restricts outbound internet access to a limited set of trusted domains by default — real, but not something you configured or can tune; say so plainly rather than taking credit for it as "your" control
  - **Sandbox:** ✅ context-based network policies let you explicitly allow/deny egress destinations per identity, with dry-run mode to test before enforcing
- [ ] Private connectivity (no public internet path to storage)
  - **Free Edition:** ❌ not available — "no private networking configurations" is an explicit FE limitation
  - **Sandbox:** ✅ PrivateLink / VPC peering available on Enterprise tier

---

## 8. Audit Logging

- [ ] Custom `governed.audit_events` Delta table, written to by the app on every significant action (query, blocked attempt, export request, approval)
  - Both environments: ✅ — recommended over built-in audit logs for a live demo screen, since built-in logs have delivery latency
- [ ] Databricks built-in audit logs (system tables) as the durable, comprehensive record behind the custom table
  - **Free Edition:** ⚠️ verify availability — audit log delivery to external cloud storage is typically an Enterprise-tier capability; FE may only expose in-workspace system table access, if that
  - **Sandbox:** ✅ full audit log delivery to your security monitoring system

---

## 9. Secrets & App Configuration

- [ ] Warehouse URL, catalog name, tokens stored in Databricks Secrets — never hardcoded in app code
  - Both environments: ✅
- [ ] Databricks Apps deployment: confirm resource limits before demo day
  - **Free Edition:** ⚠️ max 3 apps per account, each auto-stops after 24 hours of running — restart before any scheduled demo
  - **Sandbox:** ✅ no such cap

---

## 10. Pre-Demo Verification Script

Run these as literal negative tests immediately before showing it live — this is what makes the "n0 one's shown me a working demo" objection land as answered:

- [ ] Log in as analyst → confirm raw table query fails with a real permission error
- [ ] Attempt `COPY INTO` / write to external location as analyst → confirm it's rejected at the warehouse, not just hidden in UI
- [ ] Confirm no download button renders anywhere on unapproved views
- [ ] Submit an export request as analyst → confirm it lands in the steward's queue, not just a local toast message
- [ ] Approve as steward → confirm analyst now sees a controlled output and the action is in the audit log
- [ ] Reject as steward → confirm analyst sees the rejection reason, not a silent failure
- [ ] Pull up the audit log screen → confirm every one of the above actions is present with timestamp, user, and outcome

---

## One thing to say out loud in the room

Free Edition proves the *governance model* — the grants, the masking, the workflow, the audit trail — all real and enforced by Unity Catalog, not app-layer theater. What Free Edition does **not** prove is the *platform hardening* around it — private networking, SSO/SCIM-driven group management, audit log delivery to external monitoring, FISMA/NIST-grade compliance controls. That's the honest line between "here's the working control" and "here's what a funded build would additionally need to satisfy CADR." Keeping that distinction explicit is what makes this credible pre-work for an RFI rather than an overclaim.
