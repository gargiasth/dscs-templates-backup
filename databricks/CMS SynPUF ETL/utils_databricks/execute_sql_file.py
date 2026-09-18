"""
Utility for executing SQL against a Spark session.

Takes SQL text or a file path, splits into statements, executes each,
reports which succeeded and which failed.
"""
import os
from pyspark.sql import SparkSession


def execute_sql_file(sql_source, catalog=None, schema=None, spark=None):
    """
    Execute SQL statements from a file path or a SQL string.
    
    Splits SQL text on semicolons and executes statements sequentially.
    Continues on failure — reports both successes and failures at the end.
    
    Args:
        sql_source: Path to a SQL file, or a SQL string directly.
        catalog: If provided, sets the active catalog before executing.
        schema: If provided, sets the active schema before executing.
        spark: Optional Spark session. If None, gets or creates one.
    
    Returns:
        dict with keys:
            total: total statement count
            succeeded: count of successful statements
            failed: count of failed statements
            failures: list of (statement_index, statement_preview, error_message) tuples
    """
    if spark is None:
        spark = SparkSession.builder.getOrCreate()
    
    if catalog:
        spark.sql(f"USE CATALOG {catalog}")
    if schema:
        spark.sql(f"USE SCHEMA {schema}")
    
    # Accept either a file path or a SQL string
    if os.path.exists(sql_source):
        with open(sql_source, 'r') as f:
            sql_text = f.read()
        source_label = sql_source
    else:
        sql_text = sql_source
        source_label = "<inline SQL>"
    
    statements = [s.strip() for s in sql_text.split(';') if s.strip()]
    
    print(f"Executing {len(statements)} SQL statements from {source_label}")
    if catalog and schema:
        print(f"Target: {catalog}.{schema}")
    
    succeeded = 0
    failed = 0
    failures = []
    
    for i, stmt in enumerate(statements, 1):
        preview = stmt[:80].replace('\n', ' ')
        try:
            spark.sql(stmt)
            print(f"  [{i}/{len(statements)}] OK: {preview}...")
            succeeded += 1
        except Exception as e:
            print(f"  [{i}/{len(statements)}] FAILED: {e}")
            failed += 1
            failures.append((i, preview, str(e)))
    
    print(f"\nSummary: {succeeded} succeeded, {failed} failed out of {len(statements)} total")
    
    return {
        "total": len(statements),
        "succeeded": succeeded,
        "failed": failed,
        "failures": failures,
    }