import { randomUUID } from 'node:crypto';
import { analytics, createApp, getExecutionContext, server } from '@databricks/appkit';
import { WorkspaceClient } from '@databricks/sdk-experimental';
import type express from 'express';
import { z } from 'zod';

const EXPORT_REQUESTS_TABLE = 'governed.default.export_requests';
const AUDIT_EVENTS_TABLE = 'governed.default.audit_events';
const DECISION_VIEW = 'governed.default.export_decision';
const STUDY_CATALOG_TABLE = 'governed.default.study_catalog';
const STEWARDS_GROUP = 'bdc-stewards';
const FILE_PREVIEW_PAGE_SIZE = 20;

// Governed per-request export artifacts. The raw tables are NOT granted to
// analysts/stewards — they are reachable ONLY through the app's download
// endpoint, which re-validates the caller before streaming.
const EXPORT_OUTPUTS_SCHEMA = 'governed.export_outputs';
// How long an approved export stays downloadable before it expires.
const EXPORT_TTL_DAYS = 7;
// Safety cap on streamed rows so a download can never dump an unbounded table.
const EXPORT_ROW_CAP = 100000;

const IS_DEV = process.env.NODE_ENV !== 'production';

// A structured (never free-form SQL) cohort filter: a single validated
// column/operator/value. Applied safely at artifact generation — the column is
// whitelisted against the real source schema and the value is escaped.
const cohortFilterSchema = z.object({
  column: z.string().min(1),
  op: z.enum(['eq', 'ne', 'lt', 'lte', 'gt', 'gte', 'contains']),
  value: z.string().default(''),
});

const submitRequestSchema = z.object({
  dataset: z.string().min(1),
  justification: z.string().default(''),
  format: z.string().default('csv'),
  // The "cohort definition" (PIC-SURE Query-ID analog): which variables to
  // include and an optional row filter. Data is not materialized here — this
  // is a pointer applied only when a steward approves.
  selected_columns: z.array(z.string()).default([]),
  cohort_filter: cohortFilterSchema.nullish(),
});

const stewardActionSchema = z.object({
  comment: z.string().default(''),
});

type SqlParam = { name: string; value: string; type?: string };

/**
 * Identity comes ONLY from the Databricks Apps proxy headers — never from the
 * request body. In dev (no reverse proxy) we fall back to a fixed identity.
 */
function forwardedEmail(req: express.Request): string | null {
  return req.header('x-forwarded-email') || (IS_DEV ? 'alice@example.com' : null);
}

/**
 * Mint a WorkspaceClient authenticated as the end user (OBO) from the
 * forwarded access token. Production requests without a token get null
 * (callers must reject with 401). In dev, fall back to the service principal
 * so local testing works — matching AppKit's own dev-mode OBO fallback.
 */
function userClient(req: express.Request): { client: WorkspaceClient; obo: boolean } | null {
  const token = req.header('x-forwarded-access-token');
  if (token) {
    const host = process.env.DATABRICKS_HOST;
    if (!host) throw new Error('DATABRICKS_HOST is not configured.');
    return { client: new WorkspaceClient({ host, token, authType: 'pat' }), obo: true };
  }
  if (IS_DEV) {
    console.warn('[obo] no x-forwarded-access-token; dev fallback to service principal');
    return { client: getExecutionContext().client, obo: false };
  }
  return null;
}

async function executeStatementWith(client: WorkspaceClient, statement: string, parameters: SqlParam[] = []) {
  const { warehouseId } = getExecutionContext();
  if (!warehouseId) {
    throw new Error('DATABRICKS_WAREHOUSE_ID is not configured for this app.');
  }

  const response = await client.statementExecution.executeStatement({
    warehouse_id: await warehouseId,
    statement,
    parameters,
    wait_timeout: '30s',
  });

  if (response.status?.state !== 'SUCCEEDED') {
    throw new Error(`Statement ${response.status?.state}: ${JSON.stringify(response.status?.error ?? {})}`);
  }

  const columns = response.manifest?.schema?.columns?.map((c) => c.name ?? '') ?? [];
  const rows = response.result?.data_array ?? [];
  return rows.map((row) => {
    const record: Record<string, string | null> = {};
    columns.forEach((col, idx) => {
      record[col] = row[idx] ?? null;
    });
    return record;
  });
}

/**
 * Like executeStatementWith, but polls getStatement until the query reaches a
 * terminal state instead of failing at the 30s wait_timeout. Needed for slow
 * queries (e.g. system.access.audit on a cold warehouse), which reliably
 * exceed 30s and would otherwise surface as an empty/failed panel.
 */
async function executeStatementWithPolling(
  client: WorkspaceClient,
  statement: string,
  parameters: SqlParam[] = [],
  { maxWaitMs = 110_000, pollIntervalMs = 2_000 }: { maxWaitMs?: number; pollIntervalMs?: number } = {},
) {
  const { warehouseId } = getExecutionContext();
  if (!warehouseId) {
    throw new Error('DATABRICKS_WAREHOUSE_ID is not configured for this app.');
  }

  let response = await client.statementExecution.executeStatement({
    warehouse_id: await warehouseId,
    statement,
    parameters,
    wait_timeout: '30s',
    on_wait_timeout: 'CONTINUE',
  });

  const deadline = Date.now() + maxWaitMs;
  while (response.status?.state === 'PENDING' || response.status?.state === 'RUNNING') {
    if (Date.now() > deadline) {
      throw new Error(`Statement timed out after ${Math.round(maxWaitMs / 1000)}s (state ${response.status?.state}).`);
    }
    await new Promise((resolve) => setTimeout(resolve, pollIntervalMs));
    const statementId = response.statement_id;
    if (!statementId) throw new Error('Missing statement_id while polling.');
    response = await client.statementExecution.getStatement({ statement_id: statementId });
  }

  if (response.status?.state !== 'SUCCEEDED') {
    throw new Error(`Statement ${response.status?.state}: ${JSON.stringify(response.status?.error ?? {})}`);
  }

  const columns = response.manifest?.schema?.columns?.map((c) => c.name ?? '') ?? [];
  const rows = response.result?.data_array ?? [];
  return rows.map((row) => {
    const record: Record<string, string | null> = {};
    columns.forEach((col, idx) => {
      record[col] = row[idx] ?? null;
    });
    return record;
  });
}

/** Service-principal execution (writes to app-owned tables). */
async function executeStatement(statement: string, parameters: SqlParam[] = []) {
  return executeStatementWith(getExecutionContext().client, statement, parameters);
}

/**
 * Re-check the caller's export decision server-side using THEIR credentials.
 * The view is current_user()-scoped, so the caller's UC identity — not
 * anything the client sent — determines the result.
 */
async function decisionForDataset(client: WorkspaceClient, datasetId: string): Promise<string | null> {
  const rows = await executeStatementWith(client, `SELECT decision FROM ${DECISION_VIEW} WHERE dataset_id = :dataset_id`, [
    { name: 'dataset_id', value: datasetId, type: 'STRING' },
  ]);
  return (rows[0]?.decision as string | undefined) ?? null;
}

/**
 * Resolve a dataset's UC volume directory from study_catalog with the caller's
 * own credentials. Returns null when the column/value is absent.
 */
async function resolveVolumeLocation(client: WorkspaceClient, datasetId: string): Promise<string | null> {
  const rows = await executeStatementWith(
    client,
    `SELECT volume_location FROM ${STUDY_CATALOG_TABLE} WHERE dataset_id = :dataset_id`,
    [{ name: 'dataset_id', value: datasetId, type: 'STRING' }],
  );
  const loc = (rows[0]?.volume_location as string | null | undefined) ?? null;
  const trimmed = loc?.trim();
  return trimmed ? trimmed.replace(/\/+$/, '') : null;
}

/** List files (not directories) in a UC volume directory as the caller. */
async function listVolumeFiles(client: WorkspaceClient, location: string): Promise<{ name: string; size: number }[]> {
  const escaped = location.replace(/'/g, "''");
  const rows = await executeStatementWith(client, `LIST '${escaped}'`);
  return rows
    .map((r) => ({
      name: (r.name as string | null) ?? '',
      size: Number(r.size ?? 0),
    }))
    // LIST returns a trailing slash on directories; keep only real files.
    .filter((f) => f.name && !f.name.endsWith('/'));
}

/**
 * Build a read_files(...) source expression for a validated absolute path.
 * The path is injected as an escaped string literal because read_files does
 * not reliably accept a bound parameter for its path argument.
 */
function buildReadFiles(path: string, fileName: string): string {
  const escaped = path.replace(/'/g, "''");
  const ext = fileName.slice(fileName.lastIndexOf('.') + 1).toLowerCase();
  let options = "format => 'csv', header => true";
  if (ext === 'parquet') options = "format => 'parquet'";
  else if (ext === 'json' || ext === 'jsonl') options = "format => 'json'";
  else if (ext === 'tsv') options = "format => 'csv', header => true, sep => '\\t'";
  return `read_files('${escaped}', ${options})`;
}

/**
 * Resolve a dataset's volume directory + consent context from study_catalog.
 * The consent metadata is what travels into the exported rows (#1). Runs with
 * whatever credentials are passed (SP during artifact generation).
 */
async function resolveDatasetMeta(
  client: WorkspaceClient,
  datasetId: string,
): Promise<{ location: string | null; consentGroup: string; accessTier: string; dbgapStatus: string } | null> {
  const rows = await executeStatementWith(
    client,
    `SELECT volume_location, consent_group, access_tier, dbgap_status
       FROM ${STUDY_CATALOG_TABLE} WHERE dataset_id = :dataset_id`,
    [{ name: 'dataset_id', value: datasetId, type: 'STRING' }],
  );
  const row = rows[0];
  if (!row) return null;
  const loc = (row.volume_location ?? '').trim();
  return {
    location: loc ? loc.replace(/\/+$/, '') : null,
    consentGroup: row.consent_group ?? '',
    accessTier: row.access_tier ?? '',
    dbgapStatus: row.dbgap_status ?? '',
  };
}

/** Column names of a source expression, read from the result manifest. */
async function describeSourceColumns(client: WorkspaceClient, source: string): Promise<string[]> {
  const { warehouseId } = getExecutionContext();
  if (!warehouseId) throw new Error('DATABRICKS_WAREHOUSE_ID is not configured for this app.');
  const response = await client.statementExecution.executeStatement({
    warehouse_id: await warehouseId,
    statement: `SELECT * FROM ${source} LIMIT 0`,
    wait_timeout: '30s',
  });
  if (response.status?.state !== 'SUCCEEDED') {
    throw new Error(`Statement ${response.status?.state}: ${JSON.stringify(response.status?.error ?? {})}`);
  }
  return (response.manifest?.schema?.columns ?? []).map((c) => c.name ?? '').filter(Boolean);
}

// read_files adds this synthetic column for schema inference; never export it.
const RESERVED_EXPORT_COLS = new Set(['_rescued_data']);

function quoteIdent(name: string): string {
  return `\`${name.replace(/`/g, '``')}\``;
}

/**
 * Build a SELECT projection from a whitelist. Only columns that actually exist
 * in the source schema are emitted (backtick-quoted); anything else is dropped.
 * Empty/none -> "*". This is the ONLY way requested columns reach the SQL.
 */
function buildProjection(available: string[], requested: string[]): string {
  if (!requested || requested.length === 0) return '*';
  const byLower = new Map(available.map((c) => [c.toLowerCase(), c]));
  const seen = new Set<string>();
  const picked: string[] = [];
  for (const r of requested) {
    const actual = byLower.get(r.trim().toLowerCase());
    if (!actual || RESERVED_EXPORT_COLS.has(actual.toLowerCase()) || seen.has(actual)) continue;
    seen.add(actual);
    picked.push(actual);
  }
  return picked.length === 0 ? '*' : picked.map(quoteIdent).join(', ');
}

const FILTER_SQL_OPS: Record<string, string> = { eq: '=', ne: '!=', lt: '<', lte: '<=', gt: '>', gte: '>=' };

/**
 * Build a safe WHERE predicate from a structured filter. The column is
 * whitelisted against the real schema, the operator is from a fixed set, and
 * the value is a string-escaped literal (or a validated number) — no raw user
 * SQL is ever interpolated.
 */
function buildCohortFilter(
  available: string[],
  filter: { column: string; op: string; value: string } | null | undefined,
): string | null {
  if (!filter?.column || !filter.op) return null;
  const byLower = new Map(available.map((c) => [c.toLowerCase(), c]));
  const col = byLower.get(filter.column.trim().toLowerCase());
  if (!col) return null;
  const q = quoteIdent(col);
  const raw = String(filter.value ?? '');
  const esc = raw.replace(/'/g, "''");
  if (filter.op === 'contains') return `CAST(${q} AS STRING) ILIKE '%${esc}%'`;
  const sqlOp = FILTER_SQL_OPS[filter.op];
  if (!sqlOp) return null;
  if (filter.op === 'eq' || filter.op === 'ne') return `CAST(${q} AS STRING) ${sqlOp} '${esc}'`;
  const num = Number(raw);
  if (!Number.isFinite(num)) return null;
  return `try_cast(${q} AS DOUBLE) ${sqlOp} ${num}`;
}

/** Parse the stored cohort definition columns off a request row. */
function parseStoredColumns(v: unknown): string[] {
  if (typeof v !== 'string' || !v.trim()) return [];
  try {
    const a = JSON.parse(v);
    return Array.isArray(a) ? a.filter((x): x is string => typeof x === 'string') : [];
  } catch {
    return [];
  }
}

function parseStoredFilter(v: unknown): { column: string; op: string; value: string } | null {
  if (typeof v !== 'string' || !v.trim()) return null;
  try {
    const o = JSON.parse(v);
    if (o && typeof o.column === 'string' && typeof o.op === 'string') {
      return { column: o.column, op: o.op, value: String(o.value ?? '') };
    }
  } catch {
    /* ignore malformed */
  }
  return null;
}

/** Verify group membership with the caller's own credentials. */
async function isSteward(client: WorkspaceClient): Promise<boolean> {
  const rows = await executeStatementWith(client, `SELECT is_account_group_member('${STEWARDS_GROUP}') AS is_steward`);
  return rows[0]?.is_steward === 'true';
}

async function getExportRequest(requestId: string) {
  const rows = await executeStatement(`SELECT * FROM ${EXPORT_REQUESTS_TABLE} WHERE request_id = :request_id`, [
    { name: 'request_id', value: requestId, type: 'STRING' },
  ]);
  return rows[0] ?? null;
}

async function writeAuditEvent(event: { user: string; action_type: string; resource: string; outcome: string; details: unknown }) {
  await executeStatement(
    `INSERT INTO ${AUDIT_EVENTS_TABLE} (event_id, \`timestamp\`, \`user\`, action_type, resource, outcome, details)
     VALUES (:event_id, CAST(:timestamp AS TIMESTAMP), :user, :action_type, :resource, :outcome, :details)`,
    [
      { name: 'event_id', value: randomUUID(), type: 'STRING' },
      { name: 'timestamp', value: new Date().toISOString(), type: 'STRING' },
      { name: 'user', value: event.user, type: 'STRING' },
      { name: 'action_type', value: event.action_type, type: 'STRING' },
      { name: 'resource', value: event.resource, type: 'STRING' },
      { name: 'outcome', value: event.outcome, type: 'STRING' },
      { name: 'details', value: JSON.stringify(event.details), type: 'STRING' },
    ],
  );
}

/** Deterministic, injection-safe table name for a request's export artifact. */
function outputTableFor(requestId: string): string {
  return `${EXPORT_OUTPUTS_SCHEMA}.req_${requestId.replace(/[^a-zA-Z0-9]/g, '_')}`;
}

/**
 * Materialize a per-request governed Delta table from the dataset's source
 * files (real CTAS -> real UC lineage) and tag it with request provenance.
 * Runs entirely as the app service principal. Returns null when the dataset
 * has no resolvable source files (nothing to export).
 *
 * Applies the request's cohort definition (#3): a validated column projection
 * and an optional structured row filter, both checked against the real source
 * schema so no raw user SQL is interpolated. Appends consent columns (#1) so
 * every exported row carries its dbGaP consent group + access context, the way
 * BDC's `_consents_` column travels with the exported CSV.
 */
async function generateExportArtifact(
  requestId: string,
  datasetId: string,
  provenance: {
    submitter: string;
    steward: string;
    expiresAt: string;
    selectedColumns?: string[];
    cohortFilter?: { column: string; op: string; value: string } | null;
  },
): Promise<{ table: string; rowCount: number; projected: boolean; filtered: boolean } | null> {
  const sp = getExecutionContext().client;
  const meta = await resolveDatasetMeta(sp, datasetId);
  if (!meta?.location) return null;
  const files = await listVolumeFiles(sp, meta.location);
  if (files.length === 0) return null;

  const table = outputTableFor(requestId);
  // Directory read; format is inferred from a representative file. Column
  // mapping lets the merged source schema keep names that would otherwise be
  // illegal Delta identifiers (spaces, etc.) across heterogeneous CSVs.
  const source = buildReadFiles(meta.location, files[0].name);

  // Cohort definition, validated against the ACTUAL source columns.
  const available = await describeSourceColumns(sp, source);
  const projection = buildProjection(available, provenance.selectedColumns ?? []);
  const where = buildCohortFilter(available, provenance.cohortFilter ?? null);

  // Consent metadata that rides along in every exported row.
  const lit = (v: string) => `'${(v ?? '').replace(/'/g, "''")}'`;
  const consentCols = [
    `${lit(meta.consentGroup)} AS _consent_group`,
    `${lit(datasetId)} AS _dbgap_accession`,
    `${lit(meta.accessTier)} AS _access_tier`,
    `${lit(provenance.submitter)} AS _exported_for`,
    `${lit(provenance.expiresAt)} AS _access_expires_at`,
    `${lit(requestId)} AS _request_id`,
    `current_timestamp() AS _exported_at`,
  ].join(', ');

  await executeStatement(
    `CREATE OR REPLACE TABLE ${table}
       TBLPROPERTIES ('delta.columnMapping.mode' = 'name')
     AS SELECT ${projection}, ${consentCols}
        FROM ${source}${where ? ` WHERE ${where}` : ''}
        LIMIT ${EXPORT_ROW_CAP}`,
  );

  const tag = (k: string, v: string) => `'${k.replace(/'/g, "''")}' = '${(v ?? '').replace(/'/g, "''")}'`;
  await executeStatement(
    `ALTER TABLE ${table} SET TAGS (${[
      tag('request_id', requestId),
      tag('dataset', datasetId),
      tag('consent_group', meta.consentGroup),
      tag('access_tier', meta.accessTier),
      tag('submitter', provenance.submitter),
      tag('approved_by', provenance.steward),
      tag('expires_at', provenance.expiresAt),
      tag('cohort_filtered', where ? 'true' : 'false'),
      tag('cohort_projected', projection === '*' ? 'false' : 'true'),
    ].join(', ')})`,
  );

  const cnt = await executeStatement(`SELECT count(*) AS n FROM ${table}`);
  return { table, rowCount: Number(cnt[0]?.n ?? 0), projected: projection !== '*', filtered: Boolean(where) };
}

/** Serialize result rows to a downloadable CSV string (RFC-4180 quoting). */
function rowsToCsv(columns: string[], rows: Record<string, string | null>[]): string {
  const esc = (v: string | null) => {
    const s = v ?? '';
    return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const lines = [columns.map(esc).join(',')];
  for (const r of rows) lines.push(columns.map((c) => esc(r[c])).join(','));
  return lines.join('\r\n');
}

/**
 * Read the REAL workspace egress/download configuration. Values are reported
 * as-is; anything unreadable is reported as unavailable with the actual API
 * error, never fabricated.
 */
async function readExfilState() {
  const { client } = getExecutionContext();

  let resultsDownload: { value: boolean | null; error?: string };
  try {
    const conf = await client.workspaceConf.getStatus({ keys: 'enableResultsDownloading' });
    const raw = (conf as Record<string, string | null>)['enableResultsDownloading'];
    // Unset (null) means the workspace default, which is enabled.
    resultsDownload = { value: raw === null || raw === undefined ? true : raw === 'true' };
  } catch (e) {
    resultsDownload = { value: null, error: e instanceof Error ? e.message : String(e) };
  }

  let ipAccessLists: { available: boolean; enabled?: boolean; listCount?: number; error?: string };
  try {
    const lists: unknown[] = [];
    for await (const l of client.ipAccessLists.list()) lists.push(l);
    ipAccessLists = { available: true, listCount: lists.length };
  } catch (e) {
    ipAccessLists = { available: false, error: e instanceof Error ? e.message : String(e) };
  }

  return { resultsDownload, ipAccessLists, checkedAt: new Date().toISOString() };
}

await createApp({
  plugins: [server(), analytics({})],
  onPluginsReady(appkit) {
    appkit.server.extend((app) => {
      // Identity: resolved from the Databricks Apps proxy header in production,
      // falls back to a fixed dev user locally (no forwarded headers in dev mode).
      app.get('/api/me', (req, res) => {
        const email = forwardedEmail(req);
        if (!email) {
          res.status(401).json({ error: 'no_identity' });
          return;
        }
        res.json({ user: email });
      });

      // ---------------------------------------------------------------------
      // Fresh, UNCACHED reads for the request-tracking views.
      //
      // The analytics plugin caches every query result in-memory for 1 hour
      // (queryDefaults.ttl = 3600), and the client SSE hook never refetches —
      // so a newly submitted request would not appear in a steward's queue (or
      // the submitter's list) until the cache expired or the app restarted.
      // These endpoints run the SAME row-filtered, on-behalf-of SQL directly,
      // bypassing the cache, so the UI can poll/refresh and see writes
      // immediately. Enforcement is unchanged: OBO + the steward_queue row
      // filter / `submitter = current_user()`.
      // ---------------------------------------------------------------------
      app.get('/api/steward-queue', async (req, res) => {
        const caller = userClient(req);
        if (!forwardedEmail(req) || !caller) {
          res.status(401).json({ error: 'no_identity' });
          return;
        }
        try {
          const rows = await executeStatementWith(
            caller.client,
            `SELECT request_id, submitter, dataset, justification, format, status, created_at,
                    steward, steward_comment, approved_at, rejected_at, output_url,
                    study_name, access_tier, dbgap_status, consent_group,
                    submitter_role, submitter_expiration_ts, submitter_decision, submitter_decision_basis,
                    selected_columns, cohort_filter
             FROM governed.default.steward_queue
             ORDER BY created_at DESC`,
          );
          // executeStatementWith returns every cell as a string; coerce the one
          // numeric column so the client's expiry formatting behaves.
          res.json(rows.map((r) => ({ ...r, submitter_expiration_ts: Number(r.submitter_expiration_ts ?? 0) })));
        } catch (e) {
          console.error('steward_queue read failed:', e);
          res.status(500).json({ error: 'query_failed' });
        }
      });

      app.get('/api/my-requests', async (req, res) => {
        const caller = userClient(req);
        if (!forwardedEmail(req) || !caller) {
          res.status(401).json({ error: 'no_identity' });
          return;
        }
        try {
          const rows = await executeStatementWith(
            caller.client,
            `SELECT r.request_id, r.submitter, r.dataset, r.justification, r.format, r.status, r.created_at,
                    r.steward, r.steward_comment, r.approved_at, r.rejected_at, r.output_url, r.output_table,
                    r.expires_at, r.selected_columns, r.cohort_filter,
                    sc.consent_group
             FROM ${EXPORT_REQUESTS_TABLE} r
             LEFT JOIN governed.default.study_catalog sc ON sc.dataset_id = r.dataset
             WHERE r.submitter = current_user()
             ORDER BY r.created_at DESC`,
          );
          res.json(rows);
        } catch (e) {
          console.error('my_requests read failed:', e);
          res.status(500).json({ error: 'query_failed' });
        }
      });

      // Platform audit trail (Unity Catalog's own system.access.audit),
      // filtered to governed.default objects. Read OBO (UC enforces system-table
      // access per caller) with polling, because this query routinely exceeds
      // the 30s wait_timeout on a cold warehouse — the cause of the panel
      // previously showing nothing. The real error is surfaced to the client.
      app.get('/api/platform-audit', async (req, res) => {
        const caller = userClient(req);
        if (!forwardedEmail(req) || !caller) {
          res.status(401).json({ error: 'no_identity' });
          return;
        }
        try {
          const rows = await executeStatementWithPolling(
            caller.client,
            `SELECT
               CAST(event_time AS STRING) AS event_time,
               COALESCE(user_identity.email, '') AS user_email,
               service_name,
               action_name,
               COALESCE(request_params['full_name_arg'], request_params['name_arg'], '') AS target,
               CAST(response.status_code AS STRING) AS status_code
             FROM system.access.audit
             WHERE event_date >= current_date() - INTERVAL 30 DAYS
               AND (
                 request_params['full_name_arg'] LIKE 'governed.default.%'
                 OR request_params['name_arg'] LIKE 'governed%'
               )
             ORDER BY event_time DESC
             LIMIT 200`,
          );
          res.json(rows);
        } catch (e) {
          console.error('platform_audit read failed:', e);
          res.status(500).json({ error: e instanceof Error ? e.message : 'query_failed' });
        }
      });

      app.post('/api/export_requests', async (req, res) => {
        const parsed = submitRequestSchema.safeParse(req.body);
        if (!parsed.success) {
          res.status(400).json({ error: 'invalid_request' });
          return;
        }

        const submitter = forwardedEmail(req);
        const caller = userClient(req);
        if (!submitter || !caller) {
          res.status(401).json({ error: 'no_identity' });
          return;
        }

        try {
          // Server-side re-validation with the CALLER's credentials — the UI
          // disabling the button is cosmetic; this is the enforcement point.
          const decision = await decisionForDataset(caller.client, parsed.data.dataset);
          if (decision !== 'granted') {
            await writeAuditEvent({
              user: submitter,
              action_type: 'submit_export',
              resource: parsed.data.dataset,
              outcome: 'blocked',
              details: { reason: 'export_decision', decision: decision ?? 'no_record' },
            });
            res.status(403).json({ error: 'access_denied', decision: decision ?? 'no_record' });
            return;
          }

          const requestId = randomUUID();
          const createdAt = new Date().toISOString();
          const record = {
            id: requestId,
            submitter,
            ...parsed.data,
            status: 'pending',
            created_at: createdAt,
          };

          const selectedColumnsJson = JSON.stringify(parsed.data.selected_columns ?? []);
          const cohortFilterJson = parsed.data.cohort_filter ? JSON.stringify(parsed.data.cohort_filter) : null;
          // A parameter marker can't carry NULL, so emit a literal NULL when
          // there is no filter and only bind :cohort_filter otherwise.
          const cohortFilterExpr = cohortFilterJson === null ? 'NULL' : ':cohort_filter';
          await executeStatement(
            `INSERT INTO ${EXPORT_REQUESTS_TABLE}
               (request_id, submitter, dataset, justification, format, status, created_at, selected_columns, cohort_filter)
             VALUES (:request_id, :submitter, :dataset, :justification, :format, :status, CAST(:created_at AS TIMESTAMP),
                     :selected_columns, ${cohortFilterExpr})`,
            [
              { name: 'request_id', value: requestId, type: 'STRING' },
              { name: 'submitter', value: submitter, type: 'STRING' },
              { name: 'dataset', value: record.dataset, type: 'STRING' },
              { name: 'justification', value: record.justification, type: 'STRING' },
              { name: 'format', value: record.format, type: 'STRING' },
              { name: 'status', value: record.status, type: 'STRING' },
              { name: 'created_at', value: record.created_at, type: 'STRING' },
              { name: 'selected_columns', value: selectedColumnsJson, type: 'STRING' },
              ...(cohortFilterJson === null ? [] : [{ name: 'cohort_filter', value: cohortFilterJson, type: 'STRING' }]),
            ],
          );

          await writeAuditEvent({
            user: submitter,
            action_type: 'submit_export',
            resource: record.dataset,
            outcome: 'submitted',
            details: record,
          });

          res.status(201).json(record);
        } catch (e) {
          console.error('submit_export failed:', e);
          res.status(400).json({ error: 'invalid_request' });
        }
      });

      const stewardAction = (kind: 'approve' | 'reject') => async (req: express.Request, res: express.Response) => {
        const parsed = stewardActionSchema.safeParse(req.body ?? {});
        if (!parsed.success) {
          res.status(400).json({ error: 'invalid_request' });
          return;
        }

        const steward = forwardedEmail(req);
        const caller = userClient(req);
        if (!steward || !caller) {
          res.status(401).json({ error: 'no_identity' });
          return;
        }

        try {
          const id = String(req.params.id);
          // Group membership is verified with the caller's own credentials —
          // hiding the button client-side is not the enforcement point.
          if (!(await isSteward(caller.client))) {
            await writeAuditEvent({
              user: steward,
              action_type: `${kind}_export`,
              resource: id,
              outcome: 'blocked',
              details: { reason: 'not_a_steward', group: STEWARDS_GROUP },
            });
            res.status(403).json({ error: 'not_a_steward' });
            return;
          }

          const existing = await getExportRequest(id);
          if (!existing) {
            res.status(404).json({ error: 'not_found' });
            return;
          }

          const stewardComment = parsed.data.comment;
          const actedAt = new Date().toISOString();

          if (kind === 'approve') {
            const dataset = String(existing.dataset ?? '');
            const expiresAt = new Date(Date.now() + EXPORT_TTL_DAYS * 86_400_000).toISOString();

            // Generate the REAL controlled artifact. If the dataset has no
            // source files we still approve, but with no downloadable output.
            let artifact: { table: string; rowCount: number; projected: boolean; filtered: boolean } | null = null;
            let artifactError: string | null = null;
            try {
              artifact = await generateExportArtifact(id, dataset, {
                submitter: String(existing.submitter ?? ''),
                steward,
                expiresAt,
                selectedColumns: parseStoredColumns(existing.selected_columns),
                cohortFilter: parseStoredFilter(existing.cohort_filter),
              });
            } catch (e) {
              artifactError = e instanceof Error ? e.message : String(e);
              console.error('export artifact generation failed:', artifactError);
            }

            const outputTable = artifact?.table ?? null;
            // output_url doubles as the "download available" flag for the client;
            // only set it when a real artifact exists.
            const outputUrl = outputTable ? `/api/exports/${id}/download` : null;

            const hasOutput = outputTable ? 'true' : 'false';
            await executeStatement(
              `UPDATE ${EXPORT_REQUESTS_TABLE}
               SET status = 'approved',
                   steward = :steward,
                   steward_comment = :steward_comment,
                   approved_at = CAST(:acted_at AS TIMESTAMP),
                   output_url = CASE WHEN :has_output = 'true' THEN :output_url ELSE NULL END,
                   output_table = CASE WHEN :has_output = 'true' THEN :output_table ELSE NULL END,
                   expires_at = CASE WHEN :has_output = 'true' THEN CAST(:expires_at AS TIMESTAMP) ELSE NULL END
               WHERE request_id = :request_id`,
              [
                { name: 'steward', value: steward, type: 'STRING' },
                { name: 'steward_comment', value: stewardComment, type: 'STRING' },
                { name: 'acted_at', value: actedAt, type: 'STRING' },
                { name: 'output_url', value: outputUrl ?? '', type: 'STRING' },
                { name: 'output_table', value: outputTable ?? '', type: 'STRING' },
                { name: 'has_output', value: hasOutput, type: 'STRING' },
                { name: 'expires_at', value: expiresAt, type: 'STRING' },
                { name: 'request_id', value: id, type: 'STRING' },
              ],
            );
            await writeAuditEvent({
              user: steward,
              action_type: 'approve_export',
              resource: dataset,
              outcome: 'approved',
              details: {
                id,
                output_table: outputTable,
                expires_at: outputTable ? expiresAt : null,
                row_count: artifact?.rowCount ?? null,
                cohort_projected: artifact?.projected ?? false,
                cohort_filtered: artifact?.filtered ?? false,
                artifact_error: artifactError,
              },
            });
            res.json({
              ...existing,
              status: 'approved',
              steward,
              steward_comment: stewardComment,
              approved_at: actedAt,
              output_url: outputUrl,
              output_table: outputTable,
              expires_at: outputTable ? expiresAt : null,
            });
          } else {
            await executeStatement(
              `UPDATE ${EXPORT_REQUESTS_TABLE}
               SET status = 'rejected',
                   steward = :steward,
                   steward_comment = :steward_comment,
                   rejected_at = CAST(:acted_at AS TIMESTAMP)
               WHERE request_id = :request_id`,
              [
                { name: 'steward', value: steward, type: 'STRING' },
                { name: 'steward_comment', value: stewardComment, type: 'STRING' },
                { name: 'acted_at', value: actedAt, type: 'STRING' },
                { name: 'request_id', value: id, type: 'STRING' },
              ],
            );
            await writeAuditEvent({
              user: steward,
              action_type: 'reject_export',
              resource: existing.dataset ?? '',
              outcome: 'rejected',
              details: { id },
            });
            res.json({ ...existing, status: 'rejected', steward, steward_comment: stewardComment, rejected_at: actedAt });
          }
        } catch (e) {
          console.error(`${kind}_export failed:`, e);
          res.status(400).json({ error: 'invalid_request' });
        }
      };

      app.post('/api/export_requests/:id/approve', stewardAction('approve'));
      app.post('/api/export_requests/:id/reject', stewardAction('reject'));

      // App-mediated, expiring, re-validated download. The approved artifact
      // is streamed BY the app after re-checking, in order: status, ownership,
      // expiry, the caller's LIVE export_decision (OBO — catches revoked
      // access), and the real workspace results-download setting. Every denial
      // writes a distinct audit row. The raw governed.export_outputs table is
      // never granted to users, so this endpoint is the only path to the bytes.
      app.get('/api/exports/:id/download', async (req, res) => {
        const user = forwardedEmail(req);
        const caller = userClient(req);
        if (!user || !caller) {
          res.status(401).json({ error: 'no_identity' });
          return;
        }

        const id = String(req.params.id);
        // TODO(egress): once volume-copy and SBFS-mount paths are implemented,
        // derive egress_path from the request instead of hardcoding it here.
        // Ideally this becomes a first-class `egress_path` column on
        // governed.default.audit_events (see sql/001_governance.sql) rather than
        // a details field.
        const egressPath = 'direct_download';
        const deny = async (status: number, error: string, reason: string, extra: Record<string, unknown> = {}) => {
          await writeAuditEvent({
            user,
            action_type: 'download_export',
            resource: String((extra.dataset as string | undefined) ?? ''),
            outcome: 'blocked',
            details: { id, reason, egress_path: egressPath, ...extra },
          });
          res.status(status).json({ error, reason });
        };

        try {
          const existing = await getExportRequest(id);
          if (!existing || existing.status !== 'approved' || !existing.output_table) {
            res.status(404).json({ error: 'not_found' });
            return;
          }
          const dataset = String(existing.dataset ?? '');
          const outputTable = String(existing.output_table);

          if (existing.submitter !== user && !IS_DEV) {
            await deny(403, 'not_your_request', 'caller is not the submitter of this request', { dataset });
            return;
          }

          const expiresAt = existing.expires_at ? new Date(String(existing.expires_at)) : null;
          if (expiresAt && Number.isFinite(expiresAt.getTime()) && Date.now() > expiresAt.getTime()) {
            await deny(410, 'export_expired', 'the approved export has expired', { dataset, expires_at: existing.expires_at });
            return;
          }

          // Live re-check with the caller's OWN credentials — an approval that
          // has since been revoked (permission removed/expired) is denied here.
          const decision = await decisionForDataset(caller.client, dataset);
          if (decision !== 'granted') {
            await deny(403, 'access_revoked', 'caller no longer has a granted export decision for this dataset', {
              dataset,
              decision: decision ?? 'no_record',
            });
            return;
          }

          const state = await readExfilState();
          if (state.resultsDownload.value === false) {
            await deny(403, 'downloads_disabled', 'results downloading is disabled in this workspace', { dataset });
            return;
          }

          // Stream the artifact itself (service principal reads the app-owned
          // table; the user never touches it directly).
          const rawRows = await executeStatement(`SELECT * FROM ${outputTable} LIMIT ${EXPORT_ROW_CAP}`);
          const rows = rawRows.map(({ _rescued_data, ...rest }) => rest);
          const columns = rows.length > 0 ? Object.keys(rows[0]) : [];
          const format = String(existing.format ?? 'csv').toLowerCase();
          const isJson = format === 'json' || format === 'jsonl';

          await writeAuditEvent({
            user,
            action_type: 'download_export',
            resource: dataset,
            outcome: 'allowed',
            details: { id, output_table: outputTable, row_count: rows.length, format: isJson ? 'json' : 'csv', egress_path: egressPath },
          });

          if (isJson) {
            res.setHeader('Content-Type', 'application/json');
            res.setHeader('Content-Disposition', `attachment; filename="export_${id}.json"`);
            res.send(JSON.stringify(rows, null, 2));
          } else {
            res.setHeader('Content-Type', 'text/csv');
            res.setHeader('Content-Disposition', `attachment; filename="export_${id}.csv"`);
            res.send(rowsToCsv(columns, rows));
          }
        } catch (e) {
          console.error('download failed:', e);
          res.status(400).json({ error: 'download_failed' });
        }
      });

      // List the data files for a dataset's UC volume directory. Runs OBO and
      // is gated on the caller's export decision being 'granted' — hiding the
      // UI is not the enforcement point.
      app.get('/api/study-files', async (req, res) => {
        const dataset = String(req.query.dataset ?? '');
        const caller = userClient(req);
        if (!dataset || !caller) {
          res.status(caller ? 400 : 401).json({ error: caller ? 'invalid_request' : 'no_identity' });
          return;
        }
        try {
          if ((await decisionForDataset(caller.client, dataset)) !== 'granted') {
            res.status(403).json({ error: 'access_denied' });
            return;
          }
          const location = await resolveVolumeLocation(caller.client, dataset);
          if (!location) {
            res.json({ files: [] });
            return;
          }
          res.json({ files: await listVolumeFiles(caller.client, location) });
        } catch (e) {
          console.error('study-files list failed:', e);
          res.status(400).json({ error: 'list_failed' });
        }
      });

      // Preview one file: first (paginated) rows + total row count, OBO and
      // decision-gated. The file name is validated against the dataset's own
      // volume listing before the path is built server-side (no traversal).
      app.get('/api/study-files/preview', async (req, res) => {
        const dataset = String(req.query.dataset ?? '');
        const file = String(req.query.file ?? '');
        const page = Math.max(1, Number.parseInt(String(req.query.page ?? '1'), 10) || 1);
        // The (potentially expensive) total row count is only computed when the
        // client asks for it — once per file, not on every page turn.
        const wantCount = String(req.query.count ?? '') === '1';
        const caller = userClient(req);
        if (!dataset || !file || !caller) {
          res.status(caller ? 400 : 401).json({ error: caller ? 'invalid_request' : 'no_identity' });
          return;
        }
        if (file.includes('/') || file.includes('\\')) {
          res.status(400).json({ error: 'invalid_file' });
          return;
        }
        try {
          if ((await decisionForDataset(caller.client, dataset)) !== 'granted') {
            res.status(403).json({ error: 'access_denied' });
            return;
          }
          const location = await resolveVolumeLocation(caller.client, dataset);
          if (!location) {
            res.status(404).json({ error: 'no_files' });
            return;
          }
          // Only allow a file that actually exists in this dataset's directory.
          const files = await listVolumeFiles(caller.client, location);
          if (!files.some((f) => f.name === file)) {
            res.status(404).json({ error: 'file_not_found' });
            return;
          }

          const source = buildReadFiles(`${location}/${file}`, file);
          const offset = (page - 1) * FILE_PREVIEW_PAGE_SIZE;
          const rawRows = await executeStatementWith(
            caller.client,
            `SELECT * FROM ${source} LIMIT ${FILE_PREVIEW_PAGE_SIZE} OFFSET ${offset}`,
          );
          let total: number | null = null;
          if (wantCount) {
            const totalRows = await executeStatementWith(caller.client, `SELECT count(*) AS n FROM ${source}`);
            total = Number(totalRows[0]?.n ?? 0);
          }
          // read_files adds a _rescued_data column for schema inference; hide it.
          const rows = rawRows.map(({ _rescued_data, ...rest }) => rest);
          const columns = rows.length > 0 ? Object.keys(rows[0]) : [];

          if (wantCount) {
            await writeAuditEvent({
              user: forwardedEmail(req) ?? 'unknown',
              action_type: 'preview_study_file',
              resource: `${dataset}/${file}`,
              outcome: 'allowed',
              details: { dataset, file, total },
            });
          }

          res.json({ columns, rows, total, page, pageSize: FILE_PREVIEW_PAGE_SIZE });
        } catch (e) {
          console.error('study-files preview failed:', e);
          res.status(400).json({ error: 'preview_failed' });
        }
      });
    });
  },
});
