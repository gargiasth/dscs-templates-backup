"""Wrapper for stage: table_setup — entry-point: create_CDMv5_tables.sql"""
import sys
from pathlib import Path

from utilities.sql_read import read_sql_file
from utilities.sql_translate import translate
from utilities.sql_execute import execute_statements

_SQL_PATH = Path(__file__).parent.parent.parent / "src/CMS SynPUF ETL/SQL/create_CDMv5_tables.sql"

if len(sys.argv) < 3:
    sys.exit("usage: <wrapper> <catalog> <schema>")
catalog = sys.argv[1]
schema  = sys.argv[2]

results    = translate(read_sql_file(_SQL_PATH), read="postgres", dialect="databricks")
statements = [item["sql"] for item in results if not item["unsupported_reason"]]

summary = execute_statements(statements, catalog=catalog, schema=schema)
if summary["failed"]:
    sys.exit(1)
