"""
load_to_gold.py

Loads the ETL's finished output CSVs (in etl_cms_silver.etl_output)
into the actual OMOP CDM v5 tables in ohdsi_cdm.

Usage:
    python load_to_gold.py <sample_number> [table_name]

If table_name is given, loads just that one table -- useful for
testing against a small file before running the full set.
"""
import os
import sys

from dotenv import load_dotenv

_snowflake_root = os.path.dirname(os.path.dirname(os.path.abspath(sys.argv[0])))
sys.path.insert(0, _snowflake_root)

from utils_snowflake.connection import get_connection
from utils_snowflake.load_to_table import ensure_file_format, copy_into_table

OUTPUT_TABLES = [
    "person", "observation", "observation_period", "specimen", "death",
    "visit_occurrence", "visit_cost", "condition_occurrence",
    "procedure_occurrence", "procedure_cost", "drug_exposure", "drug_cost",
    "device_exposure", "device_cost", "measurement_occurrence", "location",
    "care_site", "provider", "payer_plan_period",
]

if __name__ == "__main__":
    load_dotenv()
    sample_number = sys.argv[1] if len(sys.argv) > 1 else "1"
    tables_to_load = [sys.argv[2]] if len(sys.argv) > 2 else OUTPUT_TABLES

    database = os.environ["SNOWFLAKE_DATABASE"]
    silver_schema = os.environ["SNOWFLAKE_SILVER_SCHEMA"]
    gold_schema = os.environ["SNOWFLAKE_SCHEMA"]
    output_stage = os.environ["SNOWFLAKE_ETL_OUTPUT_STAGE"]

    conn = get_connection()   # <-- this line is what defines `conn`
    try:
        cur = conn.cursor()
        cur.execute(f"USE DATABASE {database}")
        ensure_file_format(conn, silver_schema, "omop_csv_format",
            file_type="CSV",
            field_delimiter=",",
            skip_header=1,
            null_if=[""],
            empty_field_as_null=True,
            field_optionally_enclosed_by='"',
        )

        for table in tables_to_load:
            stage_path = f"@{silver_schema}.{output_stage}/output/{table}_{sample_number}.csv"
            print(f"Loading {stage_path} -> {gold_schema}.{table}")
            result = copy_into_table(conn, stage_path, gold_schema, table, silver_schema, "omop_csv_format")
            print(f"  {result}")
    finally:
        conn.close()

    print("Done.")