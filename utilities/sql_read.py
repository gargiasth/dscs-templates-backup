"""
Orion Launchpad — SQL file reading and parsing utilities.

Pure Python, no Databricks dependency. Used by:
- The Streamlit intake form, to preview the table names a DDL file will create
- sql_translate.py, which calls parse_statements() as its first step
- create_tables.py, to know which tables to check and create

Public entry points:
    read_sql_file(path) -> str
    parse_statements(sql, source_dialect) -> list
    extract_table_names(sql, source_dialect) -> list[str]
"""

import logging
from pathlib import Path

import sqlglot
from sqlglot import exp
from sqlglot.errors import ErrorLevel

from utilities.logger import setup_logging

setup_logging()
log = logging.getLogger(__name__)


def read_sql_file(path) -> str:
    """Read a DDL file as text.

    Uses utf-8-sig encoding so any BOM at the start is stripped — DDL files
    exported from Windows tools often carry one.
    """
    text = Path(path).read_text(encoding="utf-8-sig")
    log.info("read %d chars from %s", len(text), path)
    return text


def parse_statements(sql: str, source_dialect: str = "postgres") -> list:
    """Parse a SQL string into a list of sqlglot AST statements.

    error_level=IGNORE means statements that sqlglot can't parse (e.g. psql
    client commands like \\COPY or \\cd) are skipped rather than raising —
    the function returns everything it could parse.
    """
    try:
        parsed = sqlglot.parse(
            sql,
            read=source_dialect,
            error_level=ErrorLevel.IGNORE,
        )
    except Exception as e:
        log.warning("sqlglot failed to parse SQL as %s: %s", source_dialect, e)
        return []

    # sqlglot returns None for empty statements between semicolons; drop them
    statements = [stmt for stmt in parsed if stmt is not None]
    log.info("parsed %d statement(s) from SQL", len(statements))
    return statements


def extract_table_names(sql: str, source_dialect: str = "postgres") -> list[str]:
    """Return bare table names from every CREATE TABLE statement in the SQL.

    Fully-qualified names (schema.table, catalog.schema.table) are reduced
    to the bare table name — the gold_tables list in the spec uses bare
    names, so this matches that convention.
    """
    statements = parse_statements(sql, source_dialect=source_dialect)

    names = []
    for stmt in statements:
        if isinstance(stmt, exp.Create) and (stmt.kind or "").upper() == "TABLE":
            table_node = stmt.find(exp.Table)
            if table_node is not None:
                names.append(table_node.name)

    log.info("extracted %d table name(s) from SQL", len(names))
    return names