# Databricks Data Download Prevention — POC Spec

> **Demo target:** 07/13 | **Hosted on:** Databricks Apps (Streamlit) | **Catalog:** Unity Catalog

---

## Screens & Functionalities

| # | Screen | Role | Functionalities |
|---|--------|------|-----------------|
| 1 | **Role / Persona Selector** | All | Simulated persona toggle (Analyst or Steward/Admin). Display role permissions summary. Route to appropriate home screen. Note: Databricks SSO handles real auth — this is a demo toggle layered on top, or derived from workspace group membership via `WorkspaceClient().current_user.me()`. |
| 2 | **Analyst — Data Workspace** | Analyst | Browse and query approved analysis views only (raw layer not visible). Display results in read-only in-browser table (no download button). Trigger access-denied state + audit log entry if raw data path is attempted. Trigger governance-block state if unmanaged export is attempted. |
| 3 | **Analyst — Submit Export Request** | Analyst | Form: dataset/query selection, intended use/justification, output format, recipient info. Submit creates a pending record in the `export_requests` Delta table. Confirmation message on submission. Audit event written on submit. |
| 4 | **Analyst — My Export Requests** | Analyst | List of analyst's own requests filtered by `submitter = current_user()`. Status badges: Pending / Approved / Rejected. View request details and steward rejection comments. For Approved: show governed download link (only legitimate export path). Log download event to audit table. |
| 5 | **Steward — Export Request Queue** | Steward/Admin | List all pending export requests (submitter, dataset, justification, timestamp). Drill into request detail. Approve action: marks approved, triggers controlled output generation, logs decision. Reject action: requires rejection reason, marks rejected, logs decision. Status indicators on all rows. |
| 6 | **Steward — Audit Log** | Steward/Admin | Chronological log queried from `audit_events` Delta table. Event types: login/role selection, dataset access, blocked attempts (raw data / unmanaged export), export submissions, approval/rejection decisions, controlled downloads. Columns: timestamp, user, role, action type, resource, outcome. Filter by event type or role. Read-only — no edit or delete. |
| 7 | **Steward — Dashboard / Home** | Steward/Admin | Count of pending export requests with link to queue. Count of recent blocked access attempts. Recent audit activity feed (last N events). Quick-nav to Export Request Queue and Audit Log. |

---

## Access Control Behaviors

| Behavior | Where Enforced | Notes |
|----------|---------------|-------|
| Raw data blocked for Analyst | Unity Catalog `GRANT` at table level | Real query failure — not a UI-only hide |
| Row/column masking on approved views | Unity Catalog dynamic views using `current_user()` | Masks or filters sensitive fields by role |
| Unmanaged export blocked | Unity Catalog: no `WRITE` on external locations for analyst group | Analyst cannot `COPY INTO` or write DataFrames to arbitrary storage |
| No direct notebook/cluster access for Analyst | Databricks workspace permissions | Closes off the bypass path entirely |
| SQL Warehouse download restriction | Warehouse config | Restricts result downloads from SQL editor even outside the app |
| Governed export path only | App workflow + Delta table | Only path data leaves system: Submit → Approve → Controlled output |

---

## Data Layer Structure

| Layer | Table / View | Accessible By | Notes |
|-------|-------------|---------------|-------|
| Raw controlled data | `catalog.restricted.raw_biomedical` | Steward only | Synthetic fields: participant_id, study_id, phenotype, consent_group, sensitive_indicators |
| Approved analysis views | `catalog.approved.analysis_view` | Analyst + Steward | Dynamic view over raw; masks/filters via `current_user()` |
| Export requests | `catalog.governed.export_requests` | App service principal | Columns: request_id, submitter, dataset, justification, format, status, timestamps, steward_comment |
| Audit events | `catalog.governed.audit_events` | App service principal (write), Steward (read) | Columns: event_id, timestamp, user, role, action_type, resource, outcome |
| Controlled export output | `catalog.export_outputs.*` | Approved analyst (scoped, time-limited) | Generated only after steward approval |

---

## Development Considerations for Cursor

### Framework & Runtime

| Topic | Decision / Note |
|-------|----------------|
| App framework | Streamlit (fastest build, native Databricks examples) |
| Data queries | Databricks SQL connector → Serverless SQL Warehouse (near-zero cold start) |
| Query execution identity | Run as logged-in user (not service principal) to enforce Unity Catalog grants correctly |
| Session state | Use `st.session_state` for UI state; persist all workflow state (requests, audit) to Delta tables |
| App compute vs data compute | App runs on App compute; queries route to SQL Warehouse — no direct Spark inside the app process |

### Authentication

| Topic | Note |
|-------|------|
| Login | Databricks SSO handles auth before app loads — no custom login screen needed |
| Current user | Retrieve via `WorkspaceClient().current_user.me()` at app startup |
| Role derivation | Map Databricks workspace groups (`analyst-group`, `steward-group`) to app roles, or use demo persona toggle for POC |

### Secrets & Config

| Item | Approach |
|------|----------|
| Warehouse URL, catalog name | Databricks Secrets or App-level environment variables |
| Tokens / credentials | Databricks Secrets only — never hardcode |
| File paths | Unity Catalog managed storage or external locations — do not use `/dbfs/` paths from Apps |

### Audit Logging

| Approach | Recommendation |
|----------|---------------|
| Custom `audit_events` Delta table | Write from app on each significant event; immediately queryable for live demo screen ✅ |
| Databricks built-in audit logs | Comprehensive but have latency; not suitable for real-time demo display ❌ |

### State & Multi-User

| Concern | Solution |
|---------|----------|
| Export request persistence | Write to `export_requests` Delta table — not held in memory or session state |
| Analyst sees only own requests | `WHERE submitter = current_user()` in query or via Unity Catalog dynamic view |
| Steward sees all requests | No row filter applied for steward role |
| Session reruns (Streamlit) | Protect state with `st.session_state` guards; re-query Delta tables as source of truth |

### Demo Day Gotchas

| Risk | Mitigation |
|------|-----------|
| SQL Warehouse cold start kills demo | Pre-warm warehouse before demo; use Serverless tier |
| Sweta's account not in workspace | Confirm workspace access before demo day |
| DBFS path assumptions | Use Unity Catalog managed paths throughout — no `/dbfs/` references |
| UI-only access control looks cosmetic | Enforce at Unity Catalog layer so denials are real warehouse errors, not hidden buttons |

---

## File / Module Structure (Suggested)

```
app/
├── main.py                   # Streamlit entrypoint, role routing
├── auth.py                   # Current user + role resolution
├── pages/
│   ├── analyst_workspace.py  # Data Workspace screen
│   ├── analyst_requests.py   # My Export Requests screen
│   ├── submit_request.py     # Submit Export Request form
│   ├── steward_queue.py      # Export Request Queue
│   ├── steward_audit.py      # Audit Log screen
│   └── steward_dashboard.py  # Steward Home/Dashboard
├── data/
│   ├── queries.py            # All SQL queries (parameterized)
│   └── warehouse.py          # SQL Warehouse connection setup
├── services/
│   ├── audit.py              # Audit event writer
│   └── export_workflow.py    # Submit / approve / reject logic
└── config.py                 # Env vars, secret references, constants
```
