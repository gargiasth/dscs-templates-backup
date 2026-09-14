"""
Create the OMOP CDM v5 tables on Databricks.

Reads a Postgres DDL file, translates via sql_translation, executes
via execute_sql_file.

Usage:
    python create_omop_tables_databricks.py <catalog> <schema> <sql_path>
"""
import os
import sys

_repo_root = os.path.dirname(os.path.dirname(os.path.abspath(sys.argv[0])))
sys.path.insert(0, _repo_root)

from utils_databricks.sql_translation import (
    append_using_delta,
    is_unsupported,
    translate_postgres_to_databricks,
)
from utils_databricks.execute_sql_file import execute_sql_file


def parse_args():
    if len(sys.argv) != 4:
        print("Usage: create_omop_tables_databricks.py <catalog> <schema> <sql_path>")
        sys.exit(1)
    return sys.argv[1], sys.argv[2], sys.argv[3]


def main():
    catalog, schema, sql_path = parse_args()

    print(f"Catalog:    {catalog}")
    print(f"Schema:     {schema}")
    print(f"SQL source: {sql_path}")

    with open(sql_path, 'r') as f:
        postgres_sql = f.read()

    statements = translate_postgres_to_databricks(postgres_sql)
    print(f"Translated {len(statements)} statements from Postgres to Databricks SQL")

    # Apply USING DELTA and check for known-unsupported statements
    processed_statements = []
    for i, stmt in enumerate(statements, 1):
        stmt = append_using_delta(stmt)
        reason = is_unsupported(stmt)
        if reason:
            print(f"Statement {i} known-unsupported ({reason}) — attempting anyway")
        processed_statements.append(stmt)

    # Join back into SQL text for the executor
    databricks_sql = ";\n".join(processed_statements) + ";"

    result = execute_sql_file(databricks_sql, catalog=catalog, schema=schema)

    # Exit 0 even with failures (sequences expected to fail, don't block downstream)
    sys.exit(0)


if __name__ == "__main__":
    main()