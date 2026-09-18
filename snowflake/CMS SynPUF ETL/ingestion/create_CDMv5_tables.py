"""
Create the OMOP CDM v5 tables on Snowflake.
"""
import os
import sys

from dotenv import load_dotenv

_snowflake_root = os.path.dirname(os.path.dirname(os.path.abspath(sys.argv[0])))
sys.path.insert(0, _snowflake_root)

from utils_snowflake.connection import get_connection
from spcs.utils_snowflake.execute_sql_file import run_sql_file

SQL_PATH = os.path.join(_snowflake_root, "..","src", "SQL", "create_CDMv5_tables.sql")


if __name__ == "__main__":
    load_dotenv()
    database = os.environ["SNOWFLAKE_DATABASE"]
    schema = os.environ["SNOWFLAKE_SCHEMA"]

    conn = get_connection()
    try:
        n = run_sql_file(conn, database, schema, SQL_PATH)
    finally:
        conn.close()
    print(f"Done — ran {n} statements against {database}.{schema}")
    print(f"Done — ran {n} statements against {database}.{schema}")
