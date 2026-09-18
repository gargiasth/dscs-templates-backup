"""
Reusable Postgres → Databricks SQL translation.

The core function `translate_postgres_to_databricks(sql_text)` takes a
string of Postgres DDL and returns a list of Databricks SQL statements,
one per parsed statement.

Uses sqlglot for parsing and generation. Handles specific dialect gaps
that sqlglot's default translation doesn't cover:
  - Standalone NULL constraints on columns
  - psql client command prefixes (\COPY → COPY, etc.)

No Databricks or Spark dependency — pure Python. Can be used offline,
in tests, or in any environment that runs Python.
"""
import re
from typing import List, Optional

import sqlglot
from sqlglot import exp


def translate_postgres_to_databricks(postgres_sql: str) -> List[str]:
    """Parse Postgres SQL, apply Databricks-specific adjustments, regenerate.

    Args:
        postgres_sql: Raw Postgres SQL source (potentially multi-statement).

    Returns:
        List of Databricks-dialect SQL statements. One per parseable
        statement in the input. Sqlglot parse failures are excluded.
    """
    postgres_sql = _strip_psql_client_prefixes(postgres_sql)
    trees = sqlglot.parse(postgres_sql, read="postgres")
    statements = []
    for tree in trees:
        if tree is None:
            continue
        _remove_standalone_null_constraints(tree)
        statements.append(tree.sql(dialect="databricks"))
    return statements


def _remove_standalone_null_constraints(tree: exp.Expression) -> None:
    """In-place: strip explicit NULL column constraints.

    Postgres accepts `col TYPE NULL` (redundant permissive marker) but
    Databricks rejects it. sqlglot preserves these by default; we
    walk the tree and pop them.
    """
    for constraint in tree.find_all(exp.NotNullColumnConstraint):
        if constraint.args.get("allow_null"):
            constraint.pop()


def _strip_psql_client_prefixes(sql: str) -> str:
    r"""Strip psql client-command backslash prefixes.

    psql prefixes client-side commands with a backslash. Most have standard
    SQL equivalents once the prefix is stripped (\COPY → COPY). Some have
    no Databricks equivalent — those go in REMOVE and their lines are
    dropped entirely so sqlglot never sees them.
    """
    # Commands whose lines should be DROPPED entirely (no Databricks equivalent).
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

def append_using_delta(statement: str) -> str:
    """Append USING DELTA to CREATE TABLE statements."""
    if statement.strip().upper().startswith("CREATE TABLE"):
        return statement.rstrip(";") + " USING DELTA"
    return statement


def is_unsupported(statement: str) -> Optional[str]:
    """Return a reason string if this statement doesn't translate to Delta.

    Returns None if the statement is fine to execute.
    """
    upper = statement.strip().upper()
    if upper.startswith("CREATE SEQUENCE"):
        return "CREATE SEQUENCE has no Delta equivalent"
    if "NEXTVAL" in upper:
        return "nextval() function does not exist in Delta"
    return None