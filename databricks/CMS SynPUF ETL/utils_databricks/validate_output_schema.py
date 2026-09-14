"""
Utilities for reading and validating schemas of existing Delta tables.

Used by data loading tasks to retrieve target table schemas so incoming
data (from CSVs, etc.) can be cast to matching types before writing.
"""
from pyspark.sql import SparkSession


def get_table_schema(catalog: str, schema: str, table_name: str, spark: SparkSession = None):
    """
    Read the schema of an existing Delta table.

    Args:
        catalog: Unity Catalog name (e.g., 'etl_cms')
        schema: Schema name (e.g., 'ohdsi_cdm')
        table_name: Table name (e.g., 'person')
        spark: Optional Spark session; created if not provided.

    Returns:
        pyspark.sql.types.StructType — the table's schema.
        Each field has .name, .dataType, .nullable.
    """
    if spark is None:
        spark = SparkSession.builder.getOrCreate()
    
    full_name = f"{catalog}.{schema}.{table_name}"
    return spark.table(full_name).schema


def get_column_types(catalog: str, schema: str, table_name: str, spark: SparkSession = None) -> dict:
    """
    Get a mapping of column name → data type for a table.

    Returns:
        dict mapping column name (str) → data type (pyspark.sql.types.DataType)
    """
    table_schema = get_table_schema(catalog, schema, table_name, spark)
    return {field.name: field.dataType for field in table_schema}


def print_schema_info(catalog: str, schema: str, table_name: str, spark: SparkSession = None):
    """Print a human-readable summary of a table's schema."""
    if spark is None:
        spark = SparkSession.builder.getOrCreate()
    
    full_name = f"{catalog}.{schema}.{table_name}"
    table_schema = get_table_schema(catalog, schema, table_name, spark)
    
    print(f"Table: {full_name}")
    print(f"Columns ({len(table_schema)}):")
    for field in table_schema:
        nullable = "NULL" if field.nullable else "NOT NULL"
        print(f"  {field.name:40} {str(field.dataType):20} {nullable}")