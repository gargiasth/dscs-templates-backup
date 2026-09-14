"""
Load OMOP ETL output CSVs into OMOP CDM tables via Spark DataFrames.

Discovers CSVs in the output directory. For each CSV, finds the matching
table in the target schema by exact name (case-insensitive). Reads the CSV,
casts columns to match the table's schema (retrieved via
validate_output_schema), and appends to the table.

Usage:
    load_omop_output.py <catalog> <schema> <output_dir> <sample_number>
"""
import os
import sys

_repo_root = os.path.dirname(os.path.dirname(os.path.abspath(sys.argv[0])))
sys.path.insert(0, _repo_root)

from pyspark.sql import SparkSession
from utils_databricks.validate_output_schema import get_table_schema


def parse_args():
    if len(sys.argv) != 5:
        print("Usage: load_omop_output.py <catalog> <schema> <output_dir> <sample_number>")
        sys.exit(1)
    return sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]


def discover_csvs(output_dir: str, sample_number: str) -> list:
    """Find CSV files matching the `<name>_<sample_number>.csv` pattern.
    Returns [(base_name, full_path), ...]
    """
    csvs = []
    suffix = f"_{sample_number}.csv"
    for f in os.listdir(output_dir):
        if f.endswith(suffix):
            base_name = f[:-len(suffix)]
            csvs.append((base_name, os.path.join(output_dir, f)))
    return csvs


def get_tables_in_schema(spark, catalog: str, schema: str) -> list:
    """Get all table names in the given catalog.schema."""
    df = spark.sql(f"SHOW TABLES IN {catalog}.{schema}")
    return [row["tableName"] for row in df.collect()]


def find_matching_table(csv_base_name: str, table_names: list):
    """Find a table with an exact matching name (case-insensitive)."""
    csv_lower = csv_base_name.lower()
    for t in table_names:
        if t.lower() == csv_lower:
            return t
    return None


def load_csv_to_table(spark, catalog: str, schema: str, table_name: str, csv_path: str) -> int:
    """Read CSV, cast columns to match target table schema, append to table.
    Returns row count loaded.
    """
    target_schema = get_table_schema(catalog, schema, table_name, spark)

    df = spark.read.option("header", "true").csv(csv_path)

    # Cast columns present in CSV to their target types
    for field in target_schema:
        if field.name in df.columns:
            df = df.withColumn(field.name, df[field.name].cast(field.dataType))

    # Select target columns in target order (drops extras from CSV)
    ordered_cols = [f.name for f in target_schema if f.name in df.columns]
    df = df.select(*ordered_cols)

    row_count = df.count()
    df.write.mode("append").saveAsTable(f"{catalog}.{schema}.{table_name}")
    return row_count


def main():
    catalog, schema, output_dir, sample_number = parse_args()

    print(f"Catalog:       {catalog}")
    print(f"Schema:        {schema}")
    print(f"Output dir:    {output_dir}")
    print(f"Sample number: {sample_number}")
    print()

    spark = SparkSession.builder.getOrCreate()

    csvs = discover_csvs(output_dir, sample_number)
    tables = get_tables_in_schema(spark, catalog, schema)

    print(f"Found {len(csvs)} CSVs and {len(tables)} tables")
    print()

    succeeded = 0
    unmapped = 0
    empty = 0
    failed = 0

    for csv_base, csv_path in csvs:
        if os.path.getsize(csv_path) == 0:
            print(f"  SKIP {csv_base}: empty file")
            empty += 1
            continue

        table_name = find_matching_table(csv_base, tables)
        if table_name is None:
            print(f"  UNMAPPED {csv_base}: no matching table found")
            unmapped += 1
            continue

        print(f"  Loading {csv_base}.csv -> {table_name}...")
        try:
            row_count = load_csv_to_table(spark, catalog, schema, table_name, csv_path)
            print(f"    LOADED: {row_count:,} rows")
            succeeded += 1
        except Exception as e:
            print(f"    ERROR: {e}")
            failed += 1

    print()
    print(f"Summary: {succeeded} loaded, {empty} empty, {unmapped} unmapped, {failed} failed")
    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()