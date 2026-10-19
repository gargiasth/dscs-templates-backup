"""
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
    translate(sql, read, dialect) -> list[dict]
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
) -> list[dict]:
    """Translate SQL from the `read` dialect into statements the `dialect` platform can run.

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

    log.info("translating SQL: %s → %s", read, dialect)

    # Source-specific preprocessing (strip psql backslash commands sqlglot can't parse)
    if read == "postgres":
        sql = _strip_psql_client_prefixes(sql)

    statements_ast = parse_statements(sql, source_dialect=read)
    translate_statement = _TRANSLATORS[dialect]

    results = []
    for ast in statements_ast:
        translated_sql = translate_statement(ast)
        unsupported_reason = _check_unsupported(translated_sql, dialect=dialect)
        results.append({
            "sql": translated_sql,
            "unsupported_reason": unsupported_reason,
        })

    log.info(
        "translated %d statement(s), %d flagged as unsupported for %s",
        len(results),
        sum(1 for r in results if r["unsupported_reason"]),
        dialect,
    )
    return results


# ── Per-dialect translators ──────────────────────────────────────────────────
#
# Each function takes a parsed AST statement and returns a SQL string in the
# target dialect, with every preprocessing and postprocessing step applied.
# This is where ALL dialect-specific knowledge lives — one place per dialect.

def _translate_statement_for_databricks(ast: exp.Expression) -> str:
    """Databricks: strip NULL constraints, emit, then append USING DELTA to CREATE TABLE."""
    _remove_standalone_null_constraints(ast)
    translated = ast.sql(dialect="databricks")
    translated = _append_using_delta(translated)
    return translated


def _translate_statement_for_snowflake(ast: exp.Expression) -> str:
    """Snowflake: no preprocessing or postprocessing yet — basic sqlglot translation."""
    return ast.sql(dialect="snowflake")


# Dialect registry. The keys of this dict are the only values `dialect=` accepts.
_TRANSLATORS = {
    "databricks": _translate_statement_for_databricks,
    "snowflake":  _translate_statement_for_snowflake,
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