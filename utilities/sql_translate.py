r"""
Orion Launchpad — SQL dialect translation.

Takes SQL in a source dialect and translates it to the target platform's
dialect, with per-platform preprocessing and postprocessing applied where
sqlglot's default translation isn't enough.

Parameter names mirror sqlglot's own API:
    read     — the input dialect (what the SQL was written in)
    dialect  — the output dialect (what to emit)

Adding a new target dialect:
    1. Write _translate_statement_for_<name>(ast) — handle all AST + text ops for it
    2. Register it in _TRANSLATORS at the bottom of this file
    3. (If needed) add dialect-specific checks to _check_unsupported()

Public entry point:
    translate(sql, read, dialect, params=None) -> list[dict]

psql \COPY (load a file into a table) is not SQL, so sqlglot can't translate it.
Each \COPY line is turned into the target's own bulk-load statement instead
(Databricks: COPY INTO). The folder the files are in comes from params["data_dir"].
"""

import logging
import re

from sqlglot import exp

from utilities.sql_read import parse_statements
from utilities.logger import setup_logging

setup_logging()
log = logging.getLogger(__name__)


# ── Public API ───────────────────────────────────────────────────────────────

def translate(
    sql: str,
    read: str,
    dialect: str,
    params: dict | None = None,
) -> list[dict]:
    """Translate SQL from the `read` dialect into statements the `dialect` platform can run.

    params: named values from the stage (NAME=value). Used by:
        data_dir -- the folder \\COPY loads its files from

    Returns a list of per-statement dicts:
        [
            {"sql": "<translated SQL>", "unsupported_reason": None or "<reason>"},
            ...
        ]

    The caller decides what to do with unsupported statements (skip, log,
    attempt anyway). This function never silently drops them — it marks
    them with a reason so the caller can report the decision.
    """
    if dialect not in _TRANSLATORS:
        raise ValueError(
            f"dialect must be one of {sorted(_TRANSLATORS)}, got {dialect!r}"
        )
    params = params or {}

    log.info("translating SQL: %s → %s", read, dialect)

    # psql \COPY lines are handled by hand; the SQL between them goes through sqlglot.
    # Walking the file in order keeps statements in the order they were written.
    results, pos = [], 0
    copies = list(_PSQL_COPY.finditer(sql)) if read == "postgres" else []
    for m in copies:
        results += _translate_chunk(sql[pos:m.start()], read, dialect)
        results.append(_translate_psql_copy(m, dialect, params.get("data_dir")))
        pos = m.end()
    results += _translate_chunk(sql[pos:], read, dialect)

    log.info(
        "translated %d statement(s), %d flagged as unsupported for %s",
        len(results),
        sum(1 for r in results if r["unsupported_reason"]),
        dialect,
    )
    return results


def _translate_chunk(sql: str, read: str, dialect: str) -> list[dict]:
    """Run ordinary SQL through sqlglot and the dialect's translator."""
    if not sql.strip():
        return []

    # Source-specific preprocessing (strip psql backslash commands sqlglot can't parse)
    if read == "postgres":
        sql = _strip_psql_client_prefixes(sql)
        if not sql.strip():
            return []

    translate_statement = _TRANSLATORS[dialect]
    results = []
    for ast in parse_statements(sql, source_dialect=read):
        translated_sql = translate_statement(ast)
        if not translated_sql.strip():
            continue
        results.append({
            "sql": translated_sql,
            "unsupported_reason": _check_unsupported(translated_sql, dialect=dialect),
        })
    return results


# ── psql \COPY → the target's bulk load ─────────────────────────────────────
#
# \COPY table [(col, ...)] FROM 'file' [WITH] [DELIMITER E','] [CSV] [HEADER] [QUOTE E'\b'];
# Like psql, the load is by column POSITION: the header row (if any) is skipped,
# not matched to column names.

_PSQL_COPY = re.compile(
    r"^[ \t]*\\copy\s+(?P<table>[\w.\"]+)\s*(?:\((?P<cols>[^)]*)\))?"
    r"\s+from\s+'(?P<file>[^']*)'(?P<opts>[^;\n]*);?[ \t\r]*$",
    re.IGNORECASE | re.MULTILINE,
)
_OPT_DELIMITER = re.compile(r"DELIMITER\s+E?'((?:\\.|[^'])*)'", re.IGNORECASE)
_OPT_QUOTE     = re.compile(r"QUOTE\s+E?'((?:\\.|[^'])*)'", re.IGNORECASE)


def _translate_psql_copy(m: re.Match, dialect: str, data_dir: str | None) -> dict:
    table = m.group("table").replace('"', "").lower()
    cols  = [c.strip().strip('"').lower() for c in (m.group("cols") or "").split(",") if c.strip()]
    file  = m.group("file").replace("\\", "/").rsplit("/", 1)[-1]     # psql's path is local; keep the name
    opts  = m.group("opts") or ""

    load = {
        "table":     table,
        "columns":   cols,
        "file":      file,
        "csv":       bool(re.search(r"\bCSV\b", opts, re.IGNORECASE)),
        "header":    bool(re.search(r"\bHEADER\b", opts, re.IGNORECASE)),
        "delimiter": (_OPT_DELIMITER.search(opts) or [None, None])[1],
        "quote":     (_OPT_QUOTE.search(opts) or [None, None])[1],
    }
    original = m.group(0).strip()

    render = _COPY_RENDERERS.get(dialect)
    if render is None:
        return {"sql": original,
                "unsupported_reason": f"loading files with \\COPY is not written for {dialect} yet"}
    if not data_dir:
        return {"sql": original,
                "unsupported_reason": "loads a file with \\COPY: add a parameter named data_dir "
                                      "set to the folder the files are in"}
    rendered = render(load, data_dir)
    if rendered is None:
        return {"sql": original,
                "unsupported_reason": f"data_dir {data_dir!r} is not a folder {dialect} can load from"
                                      + (" (use a stage, e.g. @my_stage/folder)" if dialect == "snowflake" else "")}
    return {"sql": rendered, "unsupported_reason": None}


def _copy_for_databricks(load: dict, data_dir: str) -> str:
    """COPY INTO, loading by position like psql. Re-runs skip files already loaded."""
    stem, dot, ext = load["file"].partition(".")
    ext = dot + ext if dot else ""
    # 'person.csv' also matches 'person_2.csv' (the ETL adds the sample number),
    # but not 'person_xyz.csv' -- so 'observation' never picks up 'observation_period_2.csv'.
    pattern = f"{stem}{{{ext},_[0-9]*{ext}}}"

    options = {"header": "false"}
    if load["header"]:
        options["skipRows"] = "1"
    delimiter = load["delimiter"] if load["delimiter"] is not None else ("," if load["csv"] else "\\t")
    options["delimiter"] = delimiter
    if load["quote"] is not None and load["quote"].startswith("\\") and load["quote"] not in ("\\'", '\\"'):
        options["quote"] = ""        # E'\b' etc.: psql trick to switch quoting off
    elif load["quote"] is not None:
        options["quote"] = load["quote"]
    if not load["csv"]:
        options["quote"] = ""        # psql text format has no quoting

    target  = f"{load['table']} ({', '.join(load['columns'])})" if load["columns"] else f"{load['table']} BY POSITION"
    fmt     = ", ".join(f"'{k}' = '{v}'" for k, v in options.items())
    folder  = data_dir.rstrip("/").replace("'", "\\'")
    return (f"COPY INTO {target} FROM '{folder}' FILEFORMAT = CSV "
            f"PATTERN = '{pattern}' FORMAT_OPTIONS ({fmt})")


# ── Per-dialect translators ──────────────────────────────────────────────────
#
# Each function takes a parsed AST statement and returns a SQL string in the
# target dialect, with every preprocessing and postprocessing step applied.
# This is where ALL dialect-specific knowledge lives — one place per dialect.

def _translate_statement_for_databricks(ast: exp.Expression) -> str:
    """Databricks: strip NULL constraints, emit, then append USING DELTA to CREATE TABLE."""
    _remove_standalone_null_constraints(ast)
    translated = ast.sql(dialect="databricks", comments=False)
    translated = _append_using_delta(translated)
    return translated


def _translate_statement_for_snowflake(ast: exp.Expression) -> str:
    """Snowflake: no preprocessing or postprocessing yet — basic sqlglot translation."""
    return ast.sql(dialect="snowflake", comments=False)


def _copy_for_snowflake(load: dict, data_dir: str) -> str | None:
    """COPY INTO from a stage, loading by position like psql. Re-runs skip files already loaded.

    data_dir must be a stage path, e.g. @orion_stage/silver_output. Returns None if it isn't.
    """
    if not data_dir.startswith("@"):
        return None
    stem, dot, ext = load["file"].partition(".")
    ext = dot + ext if dot else ""
    # PATTERN is a regex on the file's path inside the stage. Same matching as Databricks:
    # 'person.csv' and 'person_2.csv', never 'person_xyz.csv'.
    pattern = f"(.*/)?{re.escape(stem)}(_[0-9]+)?{ext.replace('.', '[.]')}"

    fmt = ["TYPE = CSV"]
    if load["header"]:
        fmt.append("SKIP_HEADER = 1")
    delimiter = load["delimiter"] if load["delimiter"] is not None else ("," if load["csv"] else "\\t")
    fmt.append(f"FIELD_DELIMITER = '{delimiter}'")
    quote = load["quote"]
    if load["csv"] and quote is not None and not quote.startswith("\\"):
        fmt.append(f"FIELD_OPTIONALLY_ENCLOSED_BY = '{quote}'")   # otherwise NONE, Snowflake's default
    elif load["csv"] and quote is None:
        fmt.append("FIELD_OPTIONALLY_ENCLOSED_BY = '\"'")          # psql CSV quotes with " by default

    stage = data_dir.rstrip("/") + "/"
    if load["columns"]:
        # Snowflake needs a SELECT to load into chosen columns: $1 is the file's first field, ...
        fields = ", ".join(f"${i}" for i in range(1, len(load["columns"]) + 1))
        source = f"(SELECT {fields} FROM {stage})"
        target = f"{load['table']} ({', '.join(load['columns'])})"
    else:
        source, target = stage, load["table"]
    return (f"COPY INTO {target} FROM {source} "
            f"PATTERN = '{pattern}' FILE_FORMAT = ({' '.join(fmt)})")


# Dialect registry. The keys of this dict are the only values `dialect=` accepts.
_TRANSLATORS = {
    "databricks": _translate_statement_for_databricks,
    "snowflake":  _translate_statement_for_snowflake,
}

# How each dialect bulk-loads a file (for psql \COPY). A renderer returns None when
# data_dir isn't something that platform can load from.
_COPY_RENDERERS = {
    "databricks": _copy_for_databricks,
    "snowflake":  _copy_for_snowflake,
}


# ── Source-specific preprocessing ────────────────────────────────────────────

def _strip_psql_client_prefixes(sql: str) -> str:
    r"""Strip psql client-command backslash prefixes from Postgres SQL.

    psql prefixes client-side commands with a backslash. Most have standard
    SQL equivalents once the prefix is stripped (\COPY → COPY). Some have no
    SQL equivalent at all — those get their lines dropped entirely so
    sqlglot never sees them.
    """
    # Commands whose lines should be DROPPED entirely (no SQL equivalent).
    REMOVE = {"cd"}

    # First pass: drop lines beginning with a REMOVE-listed command
    kept_lines = []
    for line in sql.split("\n"):
        stripped = line.strip()
        if stripped.startswith("\\"):
            match = re.match(r"\\([A-Za-z]+)", stripped)
            if match and match.group(1).lower() in REMOVE:
                continue  # skip line entirely
        kept_lines.append(line)

    cleaned = "\n".join(kept_lines)

    # Second pass: strip backslash from remaining commands (\COPY → COPY)
    return re.sub(r"\\([A-Za-z]+)\b", r"\1", cleaned)


# ── Databricks-specific helpers ──────────────────────────────────────────────

def _remove_standalone_null_constraints(tree: exp.Expression) -> None:
    """In-place: strip explicit NULL column constraints.

    Postgres accepts `col TYPE NULL` as a redundant permissive marker, but
    Databricks rejects it. sqlglot preserves these by default; we walk the
    tree and pop them.
    """
    for constraint in tree.find_all(exp.NotNullColumnConstraint):
        if constraint.args.get("allow_null"):
            constraint.pop()


def _append_using_delta(statement: str) -> str:
    """Append `USING DELTA` to CREATE TABLE statements for Databricks."""
    if statement.strip().upper().startswith("CREATE TABLE"):
        return statement.rstrip(";") + " USING DELTA"
    return statement


# ── Unsupported-statement checks ─────────────────────────────────────────────

def _check_unsupported(statement: str, dialect: str) -> str | None:
    """Return a reason string if the target dialect can't run this statement, else None."""
    upper = statement.strip().upper()

    if dialect == "databricks":
        if upper.startswith("CREATE SEQUENCE"):
            return (
                "CREATE SEQUENCE has no Delta equivalent — Databricks pipelines "
                "typically assign IDs in the ETL layer rather than via SQL sequences. "
                "See docs for GENERATED ALWAYS AS IDENTITY if sequence behavior is required.")

        if "NEXTVAL" in upper:
            return "nextval() function does not exist in Delta"

    # Snowflake supports sequences and nextval natively; nothing to flag yet.
    # Add dialect-specific checks here as they come up.

    return None