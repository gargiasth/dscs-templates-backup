"""
Tests for utilities/sql_read.py

Run from the repo root:
    pytest tests/test_sql_read.py

Each test is tagged with the "path" it exercises:
    - Happy path   : valid input, expected output
    - Angry path   : invalid input, raises the right error
    - Desolate path: empty input (empty lists/dicts)
    - Delinquent   : malformed input, wrong types or placeholder sentinels
    - Forgetful    : optional fields missing from the input
"""

import pytest
from pathlib import Path

from utilities.sql_read import read_sql_file, parse_statements, extract_table_names


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def simple_ddl():
    return "CREATE TABLE person (person_id INTEGER PRIMARY KEY, name VARCHAR(100));"


@pytest.fixture
def multi_ddl():
    return """
    CREATE TABLE person (person_id INTEGER);
    CREATE TABLE visit_occurrence (visit_id INTEGER);
    CREATE TABLE condition_occurrence (condition_id INTEGER);
    """


@pytest.fixture
def qualified_ddl():
    return """
    CREATE TABLE etl_cms.ohdsi_cdm.person (person_id INTEGER);
    CREATE TABLE ohdsi_cdm.visit_occurrence (visit_id INTEGER);
    """


# ── Happy path ───────────────────────────────────────────────────────────────

class TestHappyPath:
    """Valid inputs that should produce the expected output."""

    # read_sql_file
    def test_read_sql_file_returns_content(self, tmp_path):
        path = tmp_path / "test.sql"
        path.write_text("CREATE TABLE foo (id INTEGER);", encoding="utf-8")
        assert "CREATE TABLE foo" in read_sql_file(path)

    def test_read_sql_file_strips_bom(self, tmp_path):
        path = tmp_path / "bom.sql"
        path.write_bytes(b"\xef\xbb\xbfCREATE TABLE foo (id INTEGER);")
        text = read_sql_file(path)
        assert not text.startswith("\ufeff")
        assert text.startswith("CREATE TABLE foo")

    # parse_statements
    def test_parse_single_statement(self, simple_ddl):
        assert len(parse_statements(simple_ddl)) == 1

    def test_parse_multiple_statements(self, multi_ddl):
        assert len(parse_statements(multi_ddl)) == 3

    def test_parse_different_dialect(self):
        sql = "CREATE TABLE foo (id INT);"
        assert len(parse_statements(sql, source_dialect="databricks")) == 1

    # extract_table_names
    def test_extract_single_table_name(self, simple_ddl):
        assert extract_table_names(simple_ddl) == ["person"]

    def test_extract_multiple_names_preserves_order(self, multi_ddl):
        assert extract_table_names(multi_ddl) == [
            "person", "visit_occurrence", "condition_occurrence",
        ]

    def test_extract_strips_schema_qualifier(self, qualified_ddl):
        assert extract_table_names(qualified_ddl) == ["person", "visit_occurrence"]


# ── Angry path ───────────────────────────────────────────────────────────────

class TestAngryPath:
    """Invalid inputs that should raise an error."""

    def test_read_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            read_sql_file(tmp_path / "does_not_exist.sql")

    def test_read_directory_raises(self, tmp_path):
        # Passing a directory instead of a file
        with pytest.raises((IsADirectoryError, PermissionError)):
            read_sql_file(tmp_path)


# ── Desolate path ────────────────────────────────────────────────────────────

class TestDesolatePath:
    """Empty inputs — empty strings, empty files."""

    def test_read_empty_file_returns_empty_string(self, tmp_path):
        path = tmp_path / "empty.sql"
        path.write_text("", encoding="utf-8")
        assert read_sql_file(path) == ""

    def test_parse_empty_string_returns_empty_list(self):
        assert parse_statements("") == []

    def test_parse_whitespace_only_returns_empty_list(self):
        assert parse_statements("   \n\n   ") == []

    def test_parse_comments_only_returns_empty_list(self):
        assert parse_statements("-- just a comment\n-- another") == []

    def test_extract_empty_sql_returns_empty_list(self):
        assert extract_table_names("") == []

    def test_extract_no_create_table_returns_empty_list(self):
        assert extract_table_names("SELECT * FROM person;") == []


# ── Delinquent path ──────────────────────────────────────────────────────────

class TestDelinquentPath:
    """Malformed inputs — gibberish, wrong statement types, bad SQL."""

    def test_parse_gibberish_does_not_raise(self):
        # error_level=IGNORE means we skip bad input instead of raising
        result = parse_statements("this is not sql at all 12345!@#")
        assert isinstance(result, list)

    def test_parse_psql_backslash_commands_do_not_crash(self):
        # \COPY and \cd are psql client commands, not SQL
        sql = r"\COPY person FROM 'data.csv';"
        result = parse_statements(sql)
        assert isinstance(result, list)

    def test_extract_ignores_create_index(self):
        sql = """
        CREATE TABLE foo (id INTEGER);
        CREATE INDEX idx_foo ON foo (id);
        """
        assert extract_table_names(sql) == ["foo"]

    def test_extract_ignores_create_view(self):
        sql = """
        CREATE TABLE foo (id INTEGER);
        CREATE VIEW foo_view AS SELECT * FROM foo;
        """
        assert extract_table_names(sql) == ["foo"]

    def test_extract_malformed_sql_returns_empty(self):
        assert extract_table_names("garbage not sql") == []


# ── Forgetful path ───────────────────────────────────────────────────────────

class TestForgetfulPath:
    """Optional fields missing — defaults should fill in."""

    def test_parse_default_dialect_is_postgres(self, simple_ddl):
        # source_dialect omitted — should still parse
        assert len(parse_statements(simple_ddl)) == 1

    def test_extract_default_dialect_is_postgres(self, simple_ddl):
        # source_dialect omitted — should still extract
        assert extract_table_names(simple_ddl) == ["person"]