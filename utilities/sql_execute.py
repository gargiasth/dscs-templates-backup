"""
Orion Launchpad - Execute translated SQL statements against Spark.

Takes a list of SQL statements, optionally sets catalog/schema, runs each
one, continues on failure, reports a summary. Used by the SQL wrapper
template in generate_wrapper.py.

Public API:
    execute_statements(statements, catalog=None, schema=None, spark=None) -> dict
"""

import logging

from pyspark.sql import SparkSession

from utilities.logger import setup_logging

setup_logging()
log = logging.getLogger(__name__)


def execute_statements(statements, catalog=None, schema=None, spark=None) -> dict:
    """Execute each statement in order. Continues on failure.

    Args:
        statements: list of SQL strings to execute.
        catalog:    if provided, runs USE CATALOG before executing.
        schema:     if provided, runs USE SCHEMA before executing.
        spark:      optional Spark session. If None, gets or creates one.

    Returns a summary dict:
        {
            "total":     int,
            "succeeded": int,
            "failed":    int,
            "failures":  [(index, preview, error), ...],
        }
    """
    if spark is None:
        spark = SparkSession.builder.getOrCreate()

    if catalog:
        spark.sql(f"USE CATALOG {catalog}")
        log.info("set catalog to %s", catalog)
    if schema:
        spark.sql(f"USE SCHEMA {schema}")
        log.info("set schema to %s", schema)

    total     = len(statements)
    succeeded = 0
    failed    = 0
    failures  = []

    for i, stmt in enumerate(statements, 1):
        preview = stmt[:80].replace("\n", " ")
        try:
            spark.sql(stmt)
            succeeded += 1
            log.info("[%d/%d] OK: %s", i, total, preview)
        except Exception as e:
            failed += 1
            failures.append((i, preview, str(e)))
            log.warning("[%d/%d] FAILED: %s", i, total, e)

    log.info("summary: %d succeeded, %d failed out of %d", succeeded, failed, total)

    return {
        "total":     total,
        "succeeded": succeeded,
        "failed":    failed,
        "failures":  failures,
    }