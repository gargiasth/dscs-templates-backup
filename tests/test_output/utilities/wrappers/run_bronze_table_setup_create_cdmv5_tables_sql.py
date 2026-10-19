"""Wrapper for stage: table_setup — entry-point: create_CDMv5_tables.sql"""
from pathlib import Path
from pyspark.sql import SparkSession

from utilities.sql_read import read_sql_file
from utilities.sql_translate import translate

spark = SparkSession.builder.getOrCreate()
_SQL_PATH = Path(__file__).parent.parent.parent / "tests/test_data/create_CDMv5_tables.sql"

for item in translate(read_sql_file(_SQL_PATH), read="postgres", dialect="databricks"):
    if not item["unsupported_reason"]:
        spark.sql(item["sql"])
