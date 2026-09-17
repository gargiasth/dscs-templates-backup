"""
Reads a Postgres SQL script, translates it to Snowflake dialect via
sqlglot, and executes the result against an open Snowflake connection.

Usage:
    python execute_sql.py <database> <schema> <sql_path>
"""
import os
import sys

from dotenv import load_dotenv

_snowflake_root = os.path.dirname(os.path.dirname(os.path.abspath(sys.argv[0])))
sys.path.insert(0, _snowflake_root)

from utils_snowflake.connection import get_connection
from utils_snowflake.sql_translation import translate_postgres_to_snowflake


def execute_statements(conn, statements: list[str], label: str = "statement") -> None:
    cur = conn.cursor()
    total = len(statements)
    for i, stmt in enumerate(statements, start=1):
        cur.execute(stmt)
        print(f"  [{i}/{total}] {label} executed")


def run_sql_file(conn, database: str, schema: str, sql_path: str) -> int:
    cur = conn.cursor()
    cur.execute(f"USE DATABASE {database}")
    cur.execute(f"USE SCHEMA {schema}")

    with open(sql_path, "r") as f:
        postgres_sql = f.read()

    statements = translate_postgres_to_snowflake(postgres_sql)
    print(f"Translated {len(statements)} statements for Snowflake.")
    execute_statements(conn, statements, label="statement")
    return len(statements)


def parse_args():
    if len(sys.argv) != 4:
        print("Usage: python execute_sql.py <database> <schema> <sql_path>")
        sys.exit(1)
    return sys.argv[1], sys.argv[2], sys.argv[3]


if __name__ == "__main__":
    load_dotenv()
    database, schema, sql_path = parse_args()
    conn = get_connection()
    try:
        n = run_sql_file(conn, database, schema, sql_path)
    finally:
        conn.close()
    print(f"Done — ran {n} statements against {database}.{schema}")