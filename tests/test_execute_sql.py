"""
Tests for utilities/sql_execute.py

Run from the repo root:
    pytest tests/test_sql_execute.py

Each test is tagged with the "path" it exercises:
    - Happy path   : valid input, expected output
    - Angry path   : invalid input, raises the right error
    - Desolate path: empty input (empty lists/dicts)
    - Delinquent   : malformed input, wrong types or placeholder sentinels
    - Forgetful    : optional fields missing from the input

No real Spark is used. execute_statements accepts a `spark` argument, so the
tests pass in a FakeSpark that records every SQL string and can be told to
fail on specific statements.
"""

import sys
import types

import pytest


# sql_execute imports pyspark at module level. If pyspark isn't installed
# (e.g. on a CI runner), register a minimal stand-in so the import succeeds.
# The tests never touch the real SparkSession.
if "pyspark" not in sys.modules:
    try:
        import pyspark  # noqa: F401
    except ImportError:
        _pyspark = types.ModuleType("pyspark")
        _pyspark_sql = types.ModuleType("pyspark.sql")
        _pyspark_sql.SparkSession = object
        _pyspark.sql = _pyspark_sql
        sys.modules["pyspark"] = _pyspark
        sys.modules["pyspark.sql"] = _pyspark_sql

from utilities import sql_execute
from utilities.sql_execute import execute_statements


# ── Fake Spark ───────────────────────────────────────────────────────────────

class FakeSpark:
    """Records every spark.sql() call. Raises for any statement in `fail_on`."""

    def __init__(self, fail_on=()):
        self.calls = []
        self.fail_on = set(fail_on)

    def sql(self, statement):
        self.calls.append(statement)
        if statement in self.fail_on:
            raise RuntimeError(f"boom: {statement}")


@pytest.fixture
def spark():
    return FakeSpark()


# ── Happy path ───────────────────────────────────────────────────────────────

class TestHappyPath:
    """Valid inputs that should produce the expected output."""

    def test_runs_use_catalog_and_schema_before_statements(self, spark):
        execute_statements(["SELECT 1"], catalog="c", schema="s", spark=spark)
        assert spark.calls == ["USE CATALOG c", "USE SCHEMA s", "SELECT 1"]

    def test_runs_statements_in_order(self, spark):
        execute_statements(["A", "B", "C"], spark=spark)
        assert spark.calls == ["A", "B", "C"]

    def test_summary_counts_all_succeeded(self, spark):
        summary = execute_statements(["A", "B"], spark=spark)
        assert summary == {"total": 2, "succeeded": 2, "failed": 0, "failures": []}

    def test_creates_session_when_none_passed(self, monkeypatch):
        fake = FakeSpark()

        class FakeBuilder:
            @staticmethod
            def getOrCreate():
                return fake

        class FakeSparkSession:
            builder = FakeBuilder

        monkeypatch.setattr(sql_execute, "SparkSession", FakeSparkSession)
        execute_statements(["A"])
        assert fake.calls == ["A"]


# ── Angry path ───────────────────────────────────────────────────────────────

class TestAngryPath:
    """Failures — catalog/schema errors stop everything; statement errors don't."""

    def test_bad_catalog_raises_before_any_statement(self):
        spark = FakeSpark(fail_on={"USE CATALOG nope"})
        with pytest.raises(RuntimeError):
            execute_statements(["A"], catalog="nope", spark=spark)
        assert "A" not in spark.calls

    def test_failed_statement_does_not_stop_the_rest(self):
        spark = FakeSpark(fail_on={"B"})
        summary = execute_statements(["A", "B", "C"], spark=spark)
        assert spark.calls == ["A", "B", "C"]
        assert summary["succeeded"] == 2
        assert summary["failed"] == 1

    def test_failure_records_index_preview_and_error(self):
        spark = FakeSpark(fail_on={"B"})
        summary = execute_statements(["A", "B"], spark=spark)
        index, preview, error = summary["failures"][0]
        assert index == 2            # 1-based position in the list
        assert preview == "B"
        assert "boom" in error


# ── Desolate path ────────────────────────────────────────────────────────────

class TestDesolatePath:
    """Empty inputs."""

    def test_empty_list_returns_zero_summary(self, spark):
        summary = execute_statements([], spark=spark)
        assert summary == {"total": 0, "succeeded": 0, "failed": 0, "failures": []}
        assert spark.calls == []

    def test_empty_list_still_sets_catalog_and_schema(self, spark):
        execute_statements([], catalog="c", schema="s", spark=spark)
        assert spark.calls == ["USE CATALOG c", "USE SCHEMA s"]


# ── Delinquent path ──────────────────────────────────────────────────────────

class TestDelinquentPath:
    """Awkward statements — long, multi-line."""

    def test_preview_is_truncated_to_80_chars(self):
        long_stmt = "X" * 200
        spark = FakeSpark(fail_on={long_stmt})
        summary = execute_statements([long_stmt], spark=spark)
        assert len(summary["failures"][0][1]) == 80

    def test_preview_replaces_newlines(self):
        stmt = "CREATE TABLE a\n(x INT)"
        spark = FakeSpark(fail_on={stmt})
        summary = execute_statements([stmt], spark=spark)
        assert "\n" not in summary["failures"][0][1]


# ── Forgetful path ───────────────────────────────────────────────────────────

class TestForgetfulPath:
    """Optional catalog/schema omitted — no USE statements for the missing one."""

    def test_no_catalog_or_schema_runs_no_use(self, spark):
        execute_statements(["A"], spark=spark)
        assert spark.calls == ["A"]

    def test_schema_only(self, spark):
        execute_statements(["A"], schema="s", spark=spark)
        assert spark.calls == ["USE SCHEMA s", "A"]

    def test_catalog_only(self, spark):
        execute_statements(["A"], catalog="c", spark=spark)
        assert spark.calls == ["USE CATALOG c", "A"]