"""
Tests for utilities/sql_translate.py

Run from the repo root:
    pytest tests/test_sql_translate.py

Each test is tagged with the "path" it exercises:
    - Happy path   : valid input, expected output
    - Angry path   : invalid input, raises the right error
    - Desolate path: empty input (empty lists/dicts)
    - Delinquent   : malformed input, wrong types or placeholder sentinels
    - Forgetful    : optional fields missing from the input
"""

from pathlib import Path

import pytest

from utilities.sql_translate import translate, _strip_psql_client_prefixes


# Real OHDSI DDL checked into the repo. Skip the real-world test if it's missing.
SAMPLE_DDL_PATH = Path(__file__).parent / "test_data" / "create_CDMv5_tables.sql"


def _pg_to_databricks(sql: str) -> list[dict]:
    return translate(sql, read="postgres", dialect="databricks")


# ── Happy path ───────────────────────────────────────────────────────────────

class TestHappyPath:
    """Valid inputs that should produce the expected output."""

    def test_returns_one_result_per_statement(self):
        results = _pg_to_databricks("CREATE TABLE a (x INT); CREATE TABLE b (y INT);")
        assert len(results) == 2

    def test_result_has_sql_and_unsupported_reason_keys(self):
        result = _pg_to_databricks("CREATE TABLE a (x INT);")[0]
        assert set(result) == {"sql", "unsupported_reason"}
        assert result["unsupported_reason"] is None

    def test_databricks_create_table_gets_using_delta(self):
        result = _pg_to_databricks("CREATE TABLE a (x INT);")[0]
        assert result["sql"].endswith("USING DELTA")

    def test_databricks_strips_standalone_null_but_keeps_not_null(self):
        sql = _pg_to_databricks("CREATE TABLE a (x INTEGER NULL, y INTEGER NOT NULL);")[0]["sql"]
        assert "x INT," in sql            # NULL marker removed
        assert "y INT NOT NULL" in sql     # NOT NULL kept

    def test_databricks_keeps_if_not_exists(self):
        sql = _pg_to_databricks("CREATE TABLE IF NOT EXISTS a (x INT);")[0]["sql"]
        assert sql.startswith("CREATE TABLE IF NOT EXISTS a")

    def test_insert_passes_through_without_using_delta(self):
        result = _pg_to_databricks("INSERT INTO a VALUES (1);")[0]
        assert result["sql"] == "INSERT INTO a VALUES (1)"
        assert result["unsupported_reason"] is None

    def test_snowflake_has_no_databricks_postprocessing(self):
        sql = translate("CREATE TABLE a (x INTEGER NULL);", read="postgres", dialect="snowflake")[0]["sql"]
        assert "USING DELTA" not in sql
        assert "NULL" in sql               # Snowflake keeps the NULL marker

    def test_real_ohdsi_ddl_translates(self):
        if not SAMPLE_DDL_PATH.exists():
            pytest.skip(f"sample DDL not found at {SAMPLE_DDL_PATH}")
        results = _pg_to_databricks(SAMPLE_DDL_PATH.read_text(encoding="utf-8-sig"))
        runnable = [r for r in results if not r["unsupported_reason"]]
        assert len(runnable) == 39         # 38 CREATE TABLE + 1 INSERT
        assert len(results) - len(runnable) == 2   # the two commented-out sequence lines


# ── Angry path ───────────────────────────────────────────────────────────────

class TestAngryPath:
    """Invalid inputs that should raise an error."""

    def test_unknown_target_dialect_raises(self):
        with pytest.raises(ValueError, match="dialect must be one of"):
            translate("CREATE TABLE a (x INT);", read="postgres", dialect="oracle")


# ── Desolate path ────────────────────────────────────────────────────────────

class TestDesolatePath:
    """Empty inputs."""

    def test_empty_string_returns_empty_list(self):
        assert _pg_to_databricks("") == []

    def test_comments_only_returns_empty_list(self):
        assert _pg_to_databricks("-- just a comment\n-- another") == []


# ── Delinquent path ──────────────────────────────────────────────────────────

class TestDelinquentPath:
    """Statements the target can't run, and psql client commands."""

    def test_create_sequence_flagged_unsupported_on_databricks(self):
        result = _pg_to_databricks("CREATE SEQUENCE s;")[0]
        assert "CREATE SEQUENCE" in result["unsupported_reason"]

    def test_nextval_flagged_unsupported_on_databricks(self):
        result = _pg_to_databricks("SELECT nextval('s');")[0]
        assert "nextval" in result["unsupported_reason"]

    def test_unsupported_statements_are_marked_not_dropped(self):
        results = _pg_to_databricks("CREATE TABLE a (x INT); CREATE SEQUENCE s;")
        assert len(results) == 2
        assert [r["unsupported_reason"] is None for r in results] == [True, False]

    def test_sequence_not_flagged_on_snowflake(self):
        result = translate("CREATE SEQUENCE s;", read="postgres", dialect="snowflake")[0]
        assert result["unsupported_reason"] is None

    def test_strip_psql_drops_cd_lines(self):
        cleaned = _strip_psql_client_prefixes("\\cd /tmp\nCREATE TABLE a (x INT);")
        assert "cd" not in cleaned
        assert "CREATE TABLE a" in cleaned

    def test_strip_psql_turns_backslash_copy_into_copy(self):
        cleaned = _strip_psql_client_prefixes("\\COPY a FROM 'x.csv';")
        assert cleaned == "COPY a FROM 'x.csv';"

    @pytest.mark.xfail(strict=True, reason=(
        "Known bug: a leading /* comment */ is attached to the statement, so "
        "_append_using_delta's startswith('CREATE TABLE') check misses it."
    ))
    def test_create_table_after_block_comment_gets_using_delta(self):
        sql = _pg_to_databricks("/* header */ CREATE TABLE a (x INT);")[0]["sql"]
        assert sql.endswith("USING DELTA")


# ── Forgetful path ───────────────────────────────────────────────────────────

class TestForgetfulPath:
    """Optional preprocessing only runs for the source dialect that needs it."""

    def test_psql_prefixes_only_stripped_for_postgres_source(self):
        # postgres source: \COPY is stripped to COPY, so it parses.
        assert len(_pg_to_databricks("\\COPY a FROM 'x.csv';")) == 1
        # Any other source: no stripping, sqlglot can't parse \COPY, so it's skipped.
        assert translate("\\COPY a FROM 'x.csv';", read="databricks", dialect="databricks") == []