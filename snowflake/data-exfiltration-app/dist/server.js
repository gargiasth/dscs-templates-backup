import { randomUUID } from "node:crypto";
import path from "node:path";
import express from "express";
import helmet from "helmet";
import { z } from "zod";
import { AsyncLocalStorage } from "node:async_hooks";
import { readFileSync } from "node:fs";
import snowflake from "snowflake-sdk";

//#region server/snowflake.ts
snowflake.configure({ logLevel: "ERROR" });
const callerStore = new AsyncLocalStorage();
/** Run `fn` with the given caller token bound to the async context. */
function runWithCaller(callerToken, fn) {
	return callerStore.run({ callerToken }, fn);
}
function currentCallerToken() {
	return callerStore.getStore()?.callerToken ?? null;
}
/** Thrown when a caller-rights query is attempted without a caller token. */
var NoIdentityError = class extends Error {
	constructor() {
		super("no_identity");
		this.name = "NoIdentityError";
	}
};
const SESSION_TOKEN_PATH = process.env.SNOWFLAKE_TOKEN_PATH ?? "/snowflake/session/token";
/**
* Read the rotating service OAuth token. In the App Runtime container this is
* the token file; for local development a token may be provided via
* SNOWFLAKE_OAUTH_TOKEN. Returns null when neither is available.
*/
function readServiceToken() {
	try {
		const fromFile = readFileSync(SESSION_TOKEN_PATH, "utf8").trim();
		if (fromFile) return fromFile;
	} catch {}
	const fromEnv = process.env.SNOWFLAKE_OAUTH_TOKEN?.trim();
	return fromEnv ? fromEnv : null;
}
function baseConnectionOptions() {
	const account = process.env.SNOWFLAKE_ACCOUNT;
	if (!account) throw new Error("SNOWFLAKE_ACCOUNT is not configured; cannot open a Snowflake connection.");
	const options = {
		account,
		authenticator: "OAUTH",
		token: ""
	};
	const host = process.env.SNOWFLAKE_HOST;
	if (host) options.host = host;
	const warehouse = process.env.SNOWFLAKE_WAREHOUSE;
	if (warehouse) options.warehouse = warehouse;
	return options;
}
/** Compose the token for the requested execution mode. */
function tokenFor(callersRights) {
	const service = readServiceToken();
	if (!service) throw new Error("Snowflake service token is unavailable (not running in App Runtime and no local token set).");
	if (!callersRights) return service;
	const caller = currentCallerToken();
	if (!caller) throw new NoIdentityError();
	return `${service}.${caller}`;
}
function connect(conn) {
	return new Promise((resolve, reject) => {
		conn.connect((err) => err ? reject(err) : resolve());
	});
}
function destroy(conn) {
	return new Promise((resolve) => {
		conn.destroy(() => resolve());
	});
}
function run(conn, sqlText, binds) {
	return new Promise((resolve, reject) => {
		conn.execute({
			sqlText,
			binds,
			complete: (err, _stmt, rows) => {
				if (err) reject(err);
				else resolve(rows ?? []);
			}
		});
	});
}
/**
* Execute a single statement on a fresh connection and return the result rows
* (objects keyed by column name). Owner or caller mode per `opts.callersRights`.
*/
async function querySnowflake(sql, opts = {}) {
	const token = tokenFor(opts.callersRights ?? false);
	const conn = snowflake.createConnection({
		...baseConnectionOptions(),
		token
	});
	try {
		await connect(conn);
		return await run(conn, sql, opts.binds ?? []);
	} catch (e) {
		const code = e instanceof Error ? e.name : "error";
		console.error(`[snowflake] query failed (${code})`);
		throw e;
	} finally {
		await destroy(conn);
	}
}
/**
* Run a sequence of OWNER-rights statements on one connection inside a
* transaction. Commits on success, rolls back and rethrows on any error, so
* request + audit writes stay atomic. Caller tokens are never used here.
*/
async function withOwnerTransaction(fn) {
	const token = tokenFor(false);
	const conn = snowflake.createConnection({
		...baseConnectionOptions(),
		token
	});
	const tx = { exec: (sql, binds = []) => run(conn, sql, binds) };
	try {
		await connect(conn);
		await run(conn, "BEGIN", []);
		try {
			const result = await fn(tx);
			await run(conn, "COMMIT", []);
			return result;
		} catch (inner) {
			try {
				await run(conn, "ROLLBACK", []);
			} catch {}
			throw inner;
		}
	} catch (e) {
		const code = e instanceof Error ? e.name : "error";
		console.error(`[snowflake] transaction failed (${code})`);
		throw e;
	} finally {
		await destroy(conn);
	}
}

//#endregion
//#region server/sql.ts
/** Double-quote a Snowflake identifier part, escaping embedded quotes. */
function quoteIdent(name) {
	return `"${name.replace(/"/g, "\"\"")}"`;
}
const IDENT_PART = /^[A-Za-z_][A-Za-z0-9_$]*$/;
/**
* Validate and re-quote a possibly-qualified identifier (DB.SCHEMA.TABLE).
* Returns a safe double-quoted form, or null if any part is not a plain
* identifier. Used for STUDY_CATALOG.SOURCE_TABLE, which is governed data but
* still must never be interpolated unchecked.
*/
function safeQualifiedName(raw) {
	if (!raw) return null;
	const trimmed = raw.trim();
	if (!trimmed) return null;
	const parts = trimmed.split(".");
	if (parts.length === 0 || parts.length > 3) return null;
	const quoted = [];
	for (const part of parts) {
		const p = part.trim();
		if (!IDENT_PART.test(p)) return null;
		quoted.push(quoteIdent(p.toUpperCase()));
	}
	return quoted.join(".");
}
/** Deterministic, injection-safe output table for a request's export artifact. */
function outputTableFor(requestId, outputDatabase, outputSchema) {
	const sanitized = requestId.replace(/[^a-zA-Z0-9]/g, "_").toUpperCase();
	return `${quoteIdent(outputDatabase)}.${quoteIdent(outputSchema)}.${quoteIdent(`REQ_${sanitized}`)}`;
}
const RESERVED_EXPORT_COLS = new Set(["_rescued_data"]);
/**
* Build a SELECT projection from a whitelist. Only columns that actually exist
* in the source schema are emitted (double-quoted). Empty/none -> "*".
*/
function buildProjection(available, requested) {
	if (!requested || requested.length === 0) return "*";
	const byLower = new Map(available.map((c) => [c.toLowerCase(), c]));
	const seen = /* @__PURE__ */ new Set();
	const picked = [];
	for (const r of requested) {
		const actual = byLower.get(r.trim().toLowerCase());
		if (!actual || RESERVED_EXPORT_COLS.has(actual.toLowerCase()) || seen.has(actual)) continue;
		seen.add(actual);
		picked.push(actual);
	}
	return picked.length === 0 ? "*" : picked.map(quoteIdent).join(", ");
}
const FILTER_SQL_OPS = {
	eq: "=",
	ne: "!=",
	lt: "<",
	lte: "<=",
	gt: ">",
	gte: ">="
};
/**
* Build a parameterized WHERE predicate from a structured filter. The column is
* whitelisted against the real schema and the operator is from a fixed set; the
* VALUE is returned as a `?` bind, never interpolated.
*/
function buildCohortFilter(available, filter) {
	if (!filter?.column || !filter.op) return null;
	const col = new Map(available.map((c) => [c.toLowerCase(), c])).get(filter.column.trim().toLowerCase());
	if (!col) return null;
	const q = quoteIdent(col);
	const raw = String(filter.value ?? "");
	if (filter.op === "contains") return {
		clause: `${q}::STRING ILIKE ?`,
		binds: [`%${raw}%`]
	};
	const sqlOp = FILTER_SQL_OPS[filter.op];
	if (!sqlOp) return null;
	if (filter.op === "eq" || filter.op === "ne") return {
		clause: `${q}::STRING ${sqlOp} ?`,
		binds: [raw]
	};
	const num = Number(raw);
	if (!Number.isFinite(num)) return null;
	return {
		clause: `TRY_CAST(${q} AS DOUBLE) ${sqlOp} ?`,
		binds: [num]
	};
}
function buildConsentColumns(ctx) {
	return {
		clause: [
			"? AS \"_CONSENT_GROUP\"",
			"? AS \"_DBGAP_ACCESSION\"",
			"? AS \"_ACCESS_TIER\"",
			"? AS \"_EXPORTED_FOR\"",
			"? AS \"_ACCESS_EXPIRES_AT\"",
			"? AS \"_REQUEST_ID\"",
			"CURRENT_TIMESTAMP() AS \"_EXPORTED_AT\""
		].join(", "),
		binds: [
			ctx.consentGroup,
			ctx.dbgapAccession,
			ctx.accessTier,
			ctx.exportedFor,
			ctx.accessExpiresAt,
			ctx.requestId
		]
	};
}
const TAG_VALUE_OK = /^[A-Za-z0-9_./: -]{0,256}$/;
/**
* Build `ALTER TABLE <t> SET TAG ...` statements. DDL can't bind, so values are
* inlined after validation; anything failing the safe pattern is dropped.
*/
function buildSetTagStatement(table, tagDatabase, tagSchema, tags) {
	const assignments = [];
	for (const [name, value] of Object.entries(tags)) {
		if (value == null || !TAG_VALUE_OK.test(value)) continue;
		const tagRef = `${quoteIdent(tagDatabase)}.${quoteIdent(tagSchema)}.${quoteIdent(name)}`;
		assignments.push(`${tagRef} = '${value.replace(/'/g, "''")}'`);
	}
	if (assignments.length === 0) return null;
	return `ALTER TABLE ${table} SET TAG ${assignments.join(", ")}`;
}
/**
* Coerce an unknown SQL cell/value to a string without ever producing
* "[object Object]". Objects/arrays are JSON-encoded; nullish becomes "".
*/
function asText(v) {
	if (v == null) return "";
	if (typeof v === "string") return v;
	if (typeof v === "number" || typeof v === "boolean" || typeof v === "bigint") return String(v);
	if (v instanceof Date) return v.toISOString();
	if (typeof v === "object") return JSON.stringify(v);
	return "";
}
/** Serialize result rows to a downloadable CSV string (RFC-4180 quoting). */
function rowsToCsv(columns, rows) {
	const esc = (v) => {
		const s = asText(v);
		return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, "\"\"")}"` : s;
	};
	const lines = [columns.map(esc).join(",")];
	for (const r of rows) lines.push(columns.map((c) => esc(r[c])).join(","));
	return lines.join("\r\n");
}
/** Parse the stored cohort definition columns off a request row. */
function parseStoredColumns(v) {
	if (typeof v !== "string" || !v.trim()) return [];
	try {
		const a = JSON.parse(v);
		return Array.isArray(a) ? a.filter((x) => typeof x === "string") : [];
	} catch {
		return [];
	}
}
function parseStoredFilter(v) {
	if (typeof v !== "string" || !v.trim()) return null;
	try {
		const o = JSON.parse(v);
		if (o && typeof o === "object" && !Array.isArray(o)) {
			const rec = o;
			if (typeof rec.column === "string" && typeof rec.op === "string") return {
				column: rec.column,
				op: rec.op,
				value: asText(rec.value)
			};
		}
	} catch {}
	return null;
}
/** Clamp a positive integer for safe inlining into LIMIT/OFFSET. */
function safeInt(value, fallback, max) {
	const n = Number.parseInt(String(value), 10);
	if (!Number.isFinite(n) || n < 0) return fallback;
	return Math.min(n, max);
}

//#endregion
//#region server/server.ts
const CORE_DB = process.env.BDC_CORE_DATABASE ?? "BDC_GOVERNED";
const CORE_SCHEMA = process.env.BDC_CORE_SCHEMA ?? "CORE";
const OUTPUT_DB = process.env.BDC_OUTPUT_DATABASE ?? "BDC_GOVERNED";
const OUTPUT_SCHEMA = process.env.BDC_OUTPUT_SCHEMA ?? "EXPORT_OUTPUTS";
const TAG_DB = process.env.BDC_TAG_DATABASE ?? "BDC_GOVERNANCE";
const TAG_SCHEMA = process.env.BDC_TAG_SCHEMA ?? "POLICIES";
const STEWARD_ROLE = process.env.BDC_STEWARD_ROLE ?? "BDC_STEWARD";
const ANALYST_ROLE = process.env.BDC_ANALYST_ROLE ?? "BDC_ANALYST";
const EXPORT_TTL_DAYS = safeInt(process.env.EXPORT_TTL_DAYS, 7, 3650);
const EXPORT_ROW_CAP = safeInt(process.env.EXPORT_MAX_ROWS, 1e5, 1e5);
const FILE_PREVIEW_PAGE_SIZE = 20;
const CORE = `${CORE_DB}.${CORE_SCHEMA}`;
const EXPORT_REQUESTS = `${CORE}.EXPORT_REQUESTS`;
const AUDIT_EVENTS = `${CORE}.AUDIT_EVENTS`;
const STUDY_CATALOG = `${CORE}.STUDY_CATALOG`;
const EXPORT_DECISION = `${CORE}.EXPORT_DECISION`;
const MY_EXPORT_REQUESTS = `${CORE}.MY_EXPORT_REQUESTS`;
const STEWARD_QUEUE = `${CORE}.STEWARD_QUEUE`;
const AUDIT_EVENTS_SCOPED = `${CORE}.AUDIT_EVENTS_SCOPED`;
const PLATFORM_ACCESS_AUDIT = `${CORE}.PLATFORM_ACCESS_AUDIT`;
const cohortFilterSchema = z.object({
	column: z.string().min(1),
	op: z.enum([
		"eq",
		"ne",
		"lt",
		"lte",
		"gt",
		"gte",
		"contains"
	]),
	value: z.string().default("")
});
const submitRequestSchema = z.object({
	dataset: z.string().min(1),
	justification: z.string().default(""),
	format: z.string().default("csv"),
	selected_columns: z.array(z.string()).default([]),
	cohort_filter: cohortFilterSchema.nullish()
});
const stewardActionSchema = z.object({ comment: z.string().default("") });
/** Lowercase result-object keys (Snowflake returns UPPERCASE column names). */
function lowerRows(rows) {
	return rows.map((row) => {
		const out = {};
		for (const [k, v] of Object.entries(row)) out[k.toLowerCase()] = v;
		return out;
	});
}
function coerceBool(v) {
	return v === true || v === "true" || v === "TRUE" || v === 1;
}
/** Resolve the signed-in user via a caller-rights CURRENT_USER() query. */
async function callerIdentity() {
	try {
		const u = (await querySnowflake("SELECT CURRENT_USER() AS \"user\"", { callersRights: true }))[0]?.user;
		return u ? String(u) : null;
	} catch (e) {
		if (e instanceof NoIdentityError) return null;
		throw e;
	}
}
/** Verify steward role membership with the caller's own session. */
async function callerIsSteward() {
	return coerceBool((await querySnowflake("SELECT IS_ROLE_IN_SESSION(?) AS \"is_steward\"", {
		callersRights: true,
		binds: [STEWARD_ROLE]
	}))[0]?.is_steward);
}
/** The caller's live export decision for a dataset (caller-rights view). */
async function decisionForDataset(datasetId) {
	return lowerRows(await querySnowflake(`SELECT DECISION FROM ${EXPORT_DECISION} WHERE DATASET_ID = ?`, {
		callersRights: true,
		binds: [datasetId]
	}))[0]?.decision ?? null;
}
/** Dataset consent context + governed SOURCE_TABLE (validated + quoted). */
async function resolveDatasetMeta(datasetId, callersRights) {
	const row = lowerRows(await querySnowflake(`SELECT SOURCE_TABLE, CONSENT_GROUP, ACCESS_TIER, DBGAP_STATUS FROM ${STUDY_CATALOG} WHERE DATASET_ID = ?`, {
		callersRights,
		binds: [datasetId]
	}))[0];
	if (!row) return null;
	return {
		sourceTable: safeQualifiedName(row.source_table ?? null),
		consentGroup: asText(row.consent_group),
		accessTier: asText(row.access_tier),
		dbgapStatus: asText(row.dbgap_status)
	};
}
/** Column names of the source table, via INFORMATION_SCHEMA (owner-rights). */
async function describeSourceColumns(sourceTable) {
	const parts = sourceTable.split(".").map((p) => p.replace(/^"|"$/g, ""));
	let db = CORE_DB;
	let schema = CORE_SCHEMA;
	let table;
	if (parts.length === 3) [db, schema, table] = parts;
	else if (parts.length === 2) [schema, table] = parts;
	else [table] = parts;
	return lowerRows(await querySnowflake(`SELECT COLUMN_NAME FROM ${db}.INFORMATION_SCHEMA.COLUMNS
       WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? ORDER BY ORDINAL_POSITION`, { binds: [schema, table] })).map((r) => String(r.column_name)).filter(Boolean);
}
function buildAuditInsert(event) {
	return {
		sql: `INSERT INTO ${AUDIT_EVENTS} (EVENT_ID, "TIMESTAMP", "USER", ACTION_TYPE, RESOURCE, OUTCOME, DETAILS)
          VALUES (?, CURRENT_TIMESTAMP(), ?, ?, ?, ?, ?)`,
		binds: [
			randomUUID(),
			event.user,
			event.action_type,
			event.resource,
			event.outcome,
			JSON.stringify(event.details)
		]
	};
}
/** Owner-rights standalone audit write (used outside a transaction). */
async function writeAuditEvent(event) {
	const { sql, binds } = buildAuditInsert(event);
	await querySnowflake(sql, { binds });
}
async function getExportRequest(requestId) {
	return lowerRows(await querySnowflake(`SELECT * FROM ${EXPORT_REQUESTS} WHERE REQUEST_ID = ?`, { binds: [requestId] }))[0] ?? null;
}
/**
* Materialize a per-request governed table from the dataset's SOURCE_TABLE
* (owner-rights CTAS) and tag it with request provenance. Applies the request's
* validated column projection and structured row filter (`?` binds), and
* appends consent columns to every row. Returns null when the dataset has no
* usable SOURCE_TABLE. Tag application is best-effort (non-fatal).
*/
async function generateExportArtifact(requestId, datasetId, provenance) {
	const meta = await resolveDatasetMeta(datasetId, false);
	if (!meta?.sourceTable) return null;
	const src = meta.sourceTable;
	const available = await describeSourceColumns(src);
	const projection = buildProjection(available, provenance.selectedColumns);
	const filter = buildCohortFilter(available, provenance.cohortFilter ?? null);
	const consent = buildConsentColumns({
		consentGroup: meta.consentGroup,
		dbgapAccession: datasetId,
		accessTier: meta.accessTier,
		exportedFor: provenance.submitter,
		accessExpiresAt: provenance.expiresAt,
		requestId
	});
	const table = outputTableFor(requestId, OUTPUT_DB, OUTPUT_SCHEMA);
	await querySnowflake(`CREATE OR REPLACE TABLE ${table} AS SELECT ${projection}, ${consent.clause} FROM ${src}${filter ? ` WHERE ${filter.clause}` : ""} LIMIT ${EXPORT_ROW_CAP}`, { binds: [...consent.binds, ...filter?.binds ?? []] });
	const tagSql = buildSetTagStatement(table, TAG_DB, TAG_SCHEMA, {
		DBGAP_ACCESSION: datasetId,
		CONSENT_GROUP: meta.consentGroup,
		DATA_TIER: meta.accessTier,
		EXPORT_REQUEST_ID: requestId,
		EXPORT_STATUS: "approved",
		COHORT_FILTERED: filter ? "true" : "false",
		COHORT_PROJECTED: projection === "*" ? "false" : "true"
	});
	if (tagSql) try {
		await querySnowflake(tagSql);
	} catch {
		console.error("[export] tag application skipped (tag objects may be undefined)");
	}
	const cnt = lowerRows(await querySnowflake(`SELECT COUNT(*) AS N FROM ${table}`));
	return {
		table,
		rowCount: Number(cnt[0]?.n ?? 0),
		projected: projection !== "*",
		filtered: Boolean(filter)
	};
}
const app = express();
app.use(express.json());
app.use(helmet({ contentSecurityPolicy: false }));
app.use((req, _res, next) => {
	runWithCaller(req.header("Sf-Context-Current-User-Token") ?? null, () => next());
});
app.get("/healthz", (_req, res) => {
	res.status(200).json({ status: "ok" });
});
app.get("/api/me", async (_req, res) => {
	try {
		const user = await callerIdentity();
		if (!user) {
			res.status(401).json({ error: "no_identity" });
			return;
		}
		res.json({ user });
	} catch {
		res.status(401).json({ error: "no_identity" });
	}
});
app.get("/api/identity", async (_req, res) => {
	try {
		const row = (await querySnowflake("SELECT CURRENT_USER() AS \"user_email\", IS_ROLE_IN_SESSION(?) AS \"is_steward\", IS_ROLE_IN_SESSION(?) AS \"is_analyst\"", {
			callersRights: true,
			binds: [STEWARD_ROLE, ANALYST_ROLE]
		}))[0];
		if (!row?.user_email) {
			res.status(401).json({ error: "no_identity" });
			return;
		}
		res.json([{
			user_email: String(row.user_email),
			is_steward: coerceBool(row.is_steward),
			is_analyst: coerceBool(row.is_analyst)
		}]);
	} catch {
		res.status(401).json({ error: "no_identity" });
	}
});
app.get("/api/study-catalog", async (_req, res) => {
	try {
		const rows = lowerRows(await querySnowflake(`SELECT DATASET_ID, STUDY_NAME, CONSENT_GROUP, ACCESS_TIER, DBGAP_STATUS FROM ${STUDY_CATALOG} ORDER BY STUDY_NAME`, { callersRights: true }));
		res.json(rows);
	} catch (e) {
		respondQueryError(res, e, "study_catalog");
	}
});
app.get("/api/export-decision", async (_req, res) => {
	try {
		const rows = lowerRows(await querySnowflake(`SELECT DATASET_ID, ACCESS_TIER, DBGAP_STATUS, USER_ID, ROLE, <REAL_COL> AS EXPIRATION_TS, DECISION, DECISION_BASIS
         FROM ${EXPORT_DECISION}`, { callersRights: true }));
		res.json(rows.map((r) => ({
			...r,
			expiration_ts: Number(r.expiration_ts ?? 0)
		})));
	} catch (e) {
		respondQueryError(res, e, "export_decision");
	}
});
app.get("/api/my-requests", async (_req, res) => {
	try {
		const rows = lowerRows(await querySnowflake(`SELECT * FROM ${MY_EXPORT_REQUESTS}`, { callersRights: true }));
		res.json(sortByDesc(rows, "created_at"));
	} catch (e) {
		respondQueryError(res, e, "my_requests");
	}
});
app.get("/api/steward-queue", async (_req, res) => {
	try {
		const rows = lowerRows(await querySnowflake(`SELECT * FROM ${STEWARD_QUEUE}`, { callersRights: true }));
		res.json(sortByDesc(rows, "created_at").map((r) => ({
			...r,
			submitter_expiration_ts: Number(r.submitter_expiration_ts ?? 0)
		})));
	} catch (e) {
		respondQueryError(res, e, "steward_queue");
	}
});
app.get("/api/audit-events", async (_req, res) => {
	try {
		const rows = lowerRows(await querySnowflake(`SELECT * FROM ${AUDIT_EVENTS_SCOPED}`, { callersRights: true }));
		res.json(sortByDesc(rows, "timestamp"));
	} catch (e) {
		respondQueryError(res, e, "audit_events");
	}
});
app.get("/api/platform-audit", async (_req, res) => {
	try {
		const rows = lowerRows(await querySnowflake(`SELECT
           TO_VARCHAR(EVENT_TIME) AS EVENT_TIME,
           COALESCE(USER_EMAIL, '') AS USER_EMAIL,
           SERVICE_NAME,
           ACTION_NAME,
           COALESCE(TARGET, '') AS TARGET,
           TO_VARCHAR(STATUS_CODE) AS STATUS_CODE
         FROM ${PLATFORM_ACCESS_AUDIT}
         ORDER BY EVENT_TIME DESC
         LIMIT 200`, { callersRights: true }));
		res.json(rows);
	} catch (e) {
		respondQueryError(res, e, "platform_audit");
	}
});
app.post("/api/export_requests", async (req, res) => {
	const parsed = submitRequestSchema.safeParse(req.body);
	if (!parsed.success) {
		res.status(400).json({ error: "invalid_request" });
		return;
	}
	let submitter;
	try {
		submitter = await callerIdentity();
	} catch {
		res.status(401).json({ error: "no_identity" });
		return;
	}
	if (!submitter) {
		res.status(401).json({ error: "no_identity" });
		return;
	}
	try {
		const decision = await decisionForDataset(parsed.data.dataset);
		if (decision !== "granted") {
			await writeAuditEvent({
				user: submitter,
				action_type: "submit_export",
				resource: parsed.data.dataset,
				outcome: "blocked",
				details: {
					reason: "export_decision",
					decision: decision ?? "no_record"
				}
			});
			res.status(403).json({
				error: "access_denied",
				decision: decision ?? "no_record"
			});
			return;
		}
		const requestId = randomUUID();
		const selectedColumnsJson = JSON.stringify(parsed.data.selected_columns ?? []);
		const cohortFilterJson = parsed.data.cohort_filter ? JSON.stringify(parsed.data.cohort_filter) : null;
		const record = {
			id: requestId,
			submitter,
			dataset: parsed.data.dataset,
			justification: parsed.data.justification,
			format: parsed.data.format,
			status: "pending",
			selected_columns: parsed.data.selected_columns,
			cohort_filter: parsed.data.cohort_filter ?? null
		};
		await withOwnerTransaction(async (tx) => {
			await tx.exec(`INSERT INTO ${EXPORT_REQUESTS}
           (REQUEST_ID, SUBMITTER, DATASET, JUSTIFICATION, FORMAT, STATUS, CREATED_AT, SELECTED_COLUMNS, COHORT_FILTER)
         VALUES (?, ?, ?, ?, ?, 'pending', CURRENT_TIMESTAMP(), ?, ?)`, [
				requestId,
				submitter,
				parsed.data.dataset,
				parsed.data.justification,
				parsed.data.format,
				selectedColumnsJson,
				cohortFilterJson
			]);
			const audit = buildAuditInsert({
				user: submitter,
				action_type: "submit_export",
				resource: parsed.data.dataset,
				outcome: "submitted",
				details: { ...record }
			});
			await tx.exec(audit.sql, audit.binds);
		});
		res.status(201).json(record);
	} catch {
		console.error("[submit_export] failed");
		res.status(400).json({ error: "invalid_request" });
	}
});
function stewardAction(kind) {
	return async (req, res) => {
		const parsed = stewardActionSchema.safeParse(req.body ?? {});
		if (!parsed.success) {
			res.status(400).json({ error: "invalid_request" });
			return;
		}
		let steward;
		try {
			steward = await callerIdentity();
		} catch {
			res.status(401).json({ error: "no_identity" });
			return;
		}
		if (!steward) {
			res.status(401).json({ error: "no_identity" });
			return;
		}
		try {
			const id = String(req.params.id);
			if (!await callerIsSteward()) {
				await writeAuditEvent({
					user: steward,
					action_type: `${kind}_export`,
					resource: id,
					outcome: "blocked",
					details: {
						reason: "not_a_steward",
						role: STEWARD_ROLE
					}
				});
				res.status(403).json({ error: "not_a_steward" });
				return;
			}
			const existing = await getExportRequest(id);
			if (!existing) {
				res.status(404).json({ error: "not_found" });
				return;
			}
			const stewardComment = parsed.data.comment;
			if (kind === "approve") {
				const dataset = asText(existing.dataset);
				const expiresAt = new Date(Date.now() + EXPORT_TTL_DAYS * 864e5).toISOString();
				let artifact = null;
				let artifactError = false;
				try {
					artifact = await generateExportArtifact(id, dataset, {
						submitter: asText(existing.submitter),
						expiresAt,
						selectedColumns: parseStoredColumns(existing.selected_columns),
						cohortFilter: parseStoredFilter(existing.cohort_filter)
					});
				} catch {
					artifactError = true;
					console.error("[approve] artifact generation failed");
				}
				const outputTable = artifact?.table ?? null;
				const outputUrl = outputTable ? `/api/exports/${id}/download` : null;
				const hasOutput = outputTable ? "true" : "false";
				await withOwnerTransaction(async (tx) => {
					await tx.exec(`UPDATE ${EXPORT_REQUESTS}
             SET STATUS = 'approved',
                 STEWARD = ?,
                 STEWARD_COMMENT = ?,
                 APPROVED_AT = CURRENT_TIMESTAMP(),
                 OUTPUT_URL = CASE WHEN ? = 'true' THEN ? ELSE NULL END,
                 OUTPUT_TABLE = CASE WHEN ? = 'true' THEN ? ELSE NULL END,
                 EXPIRES_AT = CASE WHEN ? = 'true' THEN DATEADD(day, ?, CURRENT_TIMESTAMP()) ELSE NULL END
             WHERE REQUEST_ID = ?`, [
						steward,
						stewardComment,
						hasOutput,
						outputUrl ?? "",
						hasOutput,
						outputTable ?? "",
						hasOutput,
						EXPORT_TTL_DAYS,
						id
					]);
					const audit = buildAuditInsert({
						user: steward,
						action_type: "approve_export",
						resource: dataset,
						outcome: "approved",
						details: {
							id,
							output_table: outputTable,
							expires_at: outputTable ? expiresAt : null,
							row_count: artifact?.rowCount ?? null,
							cohort_projected: artifact?.projected ?? false,
							cohort_filtered: artifact?.filtered ?? false,
							artifact_error: artifactError
						}
					});
					await tx.exec(audit.sql, audit.binds);
				});
				res.json({
					...existing,
					status: "approved",
					steward,
					steward_comment: stewardComment,
					output_url: outputUrl,
					output_table: outputTable,
					expires_at: outputTable ? expiresAt : null
				});
			} else {
				await withOwnerTransaction(async (tx) => {
					await tx.exec(`UPDATE ${EXPORT_REQUESTS}
             SET STATUS = 'rejected', STEWARD = ?, STEWARD_COMMENT = ?, REJECTED_AT = CURRENT_TIMESTAMP()
             WHERE REQUEST_ID = ?`, [
						steward,
						stewardComment,
						id
					]);
					const audit = buildAuditInsert({
						user: steward,
						action_type: "reject_export",
						resource: asText(existing.dataset),
						outcome: "rejected",
						details: { id }
					});
					await tx.exec(audit.sql, audit.binds);
				});
				res.json({
					...existing,
					status: "rejected",
					steward,
					steward_comment: stewardComment
				});
			}
		} catch {
			console.error(`[${kind}_export] failed`);
			res.status(400).json({ error: "invalid_request" });
		}
	};
}
app.post("/api/export_requests/:id/approve", stewardAction("approve"));
app.post("/api/export_requests/:id/reject", stewardAction("reject"));
app.get("/api/exports/:id/download", async (req, res) => {
	let user;
	try {
		user = await callerIdentity();
	} catch {
		res.status(401).json({ error: "no_identity" });
		return;
	}
	if (!user) {
		res.status(401).json({ error: "no_identity" });
		return;
	}
	const id = String(req.params.id);
	const egressPath = "direct_download";
	const deny = async (status, error, reason, extra = {}) => {
		await writeAuditEvent({
			user,
			action_type: "download_export",
			resource: asText(extra.dataset),
			outcome: "blocked",
			details: {
				id,
				reason,
				egress_path: egressPath,
				...extra
			}
		});
		res.status(status).json({
			error,
			reason
		});
	};
	try {
		const existing = await getExportRequest(id);
		if (!existing || existing.status !== "approved" || !existing.output_table) {
			res.status(404).json({ error: "not_found" });
			return;
		}
		const dataset = asText(existing.dataset);
		const outputTable = outputTableFor(id, OUTPUT_DB, OUTPUT_SCHEMA);
		const isOwner = existing.submitter === user;
		const isSteward = isOwner ? false : await callerIsSteward();
		if (!isOwner && !isSteward) {
			await deny(403, "not_your_request", "caller is neither the submitter nor a steward", { dataset });
			return;
		}
		const expiresAt = existing.expires_at ? new Date(asText(existing.expires_at)) : null;
		if (expiresAt && Number.isFinite(expiresAt.getTime()) && Date.now() > expiresAt.getTime()) {
			await deny(410, "export_expired", "the approved export has expired", {
				dataset,
				expires_at: existing.expires_at
			});
			return;
		}
		const decision = await decisionForDataset(dataset);
		if (decision !== "granted") {
			await deny(403, "access_revoked", "caller no longer has a granted export decision for this dataset", {
				dataset,
				decision: decision ?? "no_record"
			});
			return;
		}
		const rows = lowerRows(await querySnowflake(`SELECT * FROM ${outputTable} LIMIT ${EXPORT_ROW_CAP}`));
		const columns = rows.length > 0 ? Object.keys(rows[0]) : [];
		const format = (asText(existing.format) || "csv").toLowerCase();
		const isJson = format === "json" || format === "jsonl";
		await writeAuditEvent({
			user,
			action_type: "download_export",
			resource: dataset,
			outcome: "allowed",
			details: {
				id,
				row_count: rows.length,
				format: isJson ? "json" : "csv",
				egress_path: egressPath
			}
		});
		if (isJson) {
			res.setHeader("Content-Type", "application/json");
			res.setHeader("Content-Disposition", `attachment; filename="export_${id}.json"`);
			res.send(JSON.stringify(rows, null, 2));
		} else {
			res.setHeader("Content-Type", "text/csv");
			res.setHeader("Content-Disposition", `attachment; filename="export_${id}.csv"`);
			res.send(rowsToCsv(columns, rows));
		}
	} catch {
		console.error("[download] failed");
		res.status(400).json({ error: "download_failed" });
	}
});
app.get("/api/study-files", async (req, res) => {
	const dataset = asText(req.query.dataset);
	if (!dataset) {
		res.status(400).json({ error: "invalid_request" });
		return;
	}
	try {
		if (await decisionForDataset(dataset) !== "granted") {
			res.status(403).json({ error: "access_denied" });
			return;
		}
		const meta = await resolveDatasetMeta(dataset, true);
		if (!meta?.sourceTable) {
			res.json({ files: [] });
			return;
		}
		res.json({ files: [{
			name: sourceTableFileName(meta.sourceTable),
			size: 0
		}] });
	} catch (e) {
		respondQueryError(res, e, "study_files");
	}
});
app.get("/api/study-files/preview", async (req, res) => {
	const dataset = asText(req.query.dataset);
	const file = asText(req.query.file);
	const page = safeInt(req.query.page, 1, 1e6) || 1;
	const wantCount = asText(req.query.count) === "1";
	if (!dataset || !file) {
		res.status(400).json({ error: "invalid_request" });
		return;
	}
	if (file.includes("/") || file.includes("\\")) {
		res.status(400).json({ error: "invalid_file" });
		return;
	}
	try {
		if (await decisionForDataset(dataset) !== "granted") {
			res.status(403).json({ error: "access_denied" });
			return;
		}
		const meta = await resolveDatasetMeta(dataset, true);
		if (!meta?.sourceTable) {
			res.status(404).json({ error: "no_files" });
			return;
		}
		if (sourceTableFileName(meta.sourceTable) !== file) {
			res.status(404).json({ error: "file_not_found" });
			return;
		}
		const offset = (page - 1) * FILE_PREVIEW_PAGE_SIZE;
		const rawRows = await querySnowflake(`SELECT * FROM ${meta.sourceTable} LIMIT ${FILE_PREVIEW_PAGE_SIZE} OFFSET ${offset}`, { callersRights: true });
		let total = null;
		if (wantCount) {
			const cnt = lowerRows(await querySnowflake(`SELECT COUNT(*) AS N FROM ${meta.sourceTable}`, { callersRights: true }));
			total = Number(cnt[0]?.n ?? 0);
		}
		const rows = rawRows;
		const columns = rows.length > 0 ? Object.keys(rows[0]) : [];
		if (wantCount) await writeAuditEvent({
			user: await callerIdentity() ?? "unknown",
			action_type: "preview_study_file",
			resource: `${dataset}/${file}`,
			outcome: "allowed",
			details: {
				dataset,
				file,
				total
			}
		});
		res.json({
			columns,
			rows,
			total,
			page,
			pageSize: FILE_PREVIEW_PAGE_SIZE
		});
	} catch (e) {
		respondQueryError(res, e, "study_files_preview");
	}
});
const clientDir = path.resolve(import.meta.dirname, "../client/dist");
app.use(express.static(clientDir));
app.use((req, res, next) => {
	if (req.method !== "GET" || req.path.startsWith("/api/")) {
		next();
		return;
	}
	res.sendFile(path.join(clientDir, "index.html"));
});
if (!process.env.VITEST) {
	const PORT = Number(process.env.PORT ?? 8080);
	app.listen(PORT, "0.0.0.0", () => {
		console.log(`Data Exfiltration App listening on 0.0.0.0:${PORT}`);
	});
}
function respondQueryError(res, e, label) {
	if (e instanceof NoIdentityError) {
		res.status(401).json({ error: "no_identity" });
		return;
	}
	console.error(`[${label}] read failed`);
	res.status(500).json({ error: "query_failed" });
}
function sortByDesc(rows, key) {
	return [...rows].sort((a, b) => asText(b[key]).localeCompare(asText(a[key])));
}
/** A stable, non-path pseudo-filename for a dataset's SOURCE_TABLE. */
function sourceTableFileName(quotedSourceTable) {
	const parts = quotedSourceTable.split(".").map((p) => p.replace(/^"|"$/g, ""));
	return parts[parts.length - 1];
}

//#endregion
export { app };