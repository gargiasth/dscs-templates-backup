"""
Tests for validation/input_validator.py

Run from the repo root:
    pytest tests/test_input_validator.py

Each test builds input folders in tmp_path, so nothing touches Databricks.
"""

import pytest

from validation.input_validator import validate_inputs, check_inputs, InputValidationError


def write(path, text, encoding="utf-8"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding=encoding)
    return path


@pytest.fixture
def raw(tmp_path):
    """A good input folder: one CSV in a subfolder, like synpuf_raw/DE_1/."""
    write(tmp_path / "synpuf_raw" / "DE_1" / "beneficiary.csv", "id,year\n1,2008\n2,2009\n")
    return tmp_path / "synpuf_raw"


def errors(inputs, **kw):
    return validate_inputs(inputs, **kw).errors


# ── Happy path ───────────────────────────────────────────────────────────────

class TestHappyPath:

    def test_good_folder_passes(self, raw):
        report = validate_inputs([(raw, "upstream task bronze_fetch_py")])
        assert report.errors == [] and report.warnings == []

    def test_check_inputs_does_not_raise_when_fine(self, raw):
        check_inputs([(raw, "manual upload")])

    def test_tab_separated_csv_is_detected(self, tmp_path):
        # Athena OMOP vocabulary files: .csv extension, tab delimiter
        write(tmp_path / "vocab" / "CONCEPT.csv", "concept_id\tconcept_name\n1\tAspirin\n")
        assert errors([(tmp_path / "vocab", "manual upload")]) == []

    def test_bom_is_accepted(self, tmp_path, caplog):
        write(tmp_path / "in" / "a.csv", "﻿id,name\n1,x\n")
        with caplog.at_level("INFO"):
            assert errors([(tmp_path / "in", "manual upload")]) == []
        assert "byte-order mark" in caplog.text

    def test_runnable_sql_passes(self, tmp_path):
        write(tmp_path / "ddl" / "t.sql", "CREATE TABLE a (x INT);")
        assert errors([(tmp_path / "ddl", "manual upload")]) == []


# ── Angry path ───────────────────────────────────────────────────────────────

class TestAngryPath:

    def test_missing_folder_names_upstream_task(self, tmp_path):
        errs = errors([(tmp_path / "nope", "upstream task bronze_fetch_py")])
        assert len(errs) == 1
        assert "not found" in errs[0] and "bronze_fetch_py completed successfully" in errs[0]

    def test_missing_folder_manual_upload_hint(self, tmp_path):
        errs = errors([(tmp_path / "nope", "manual upload")])
        assert "Upload the files" in errs[0]

    def test_check_inputs_raises_with_every_error(self, tmp_path):
        with pytest.raises(InputValidationError) as e:
            check_inputs([(tmp_path / "a", "manual upload"), (tmp_path / "b", "manual upload")])
        assert len(e.value.errors) == 2

    def test_wrong_field_count_names_the_line(self, tmp_path):
        write(tmp_path / "in" / "a.csv", "id,name\n1,x\n2\n")
        errs = errors([(tmp_path / "in", "manual upload")])
        assert len(errs) == 1 and "line 3: 1 field(s), header has 2" in errs[0]

    def test_duplicate_header_case_insensitive(self, tmp_path):
        write(tmp_path / "in" / "a.csv", "id,ID\n1,2\n")
        assert any("appears more than once" in e for e in errors([(tmp_path / "in", "manual upload")]))

    def test_empty_header_name(self, tmp_path):
        write(tmp_path / "in" / "a.csv", "id,,name\n1,2,3\n")
        assert any("column 2 has no name" in e for e in errors([(tmp_path / "in", "manual upload")]))

    def test_sql_with_nothing_runnable(self, tmp_path):
        write(tmp_path / "ddl" / "t.sql", "CREATE SEQUENCE s;")
        assert any("no statements that can run" in e for e in errors([(tmp_path / "ddl", "manual upload")]))


# ── Desolate path ────────────────────────────────────────────────────────────

class TestDesolatePath:

    def test_no_inputs_is_fine(self):
        assert errors([]) == []

    def test_empty_folder(self, tmp_path):
        (tmp_path / "in").mkdir()
        assert "is empty" in errors([(tmp_path / "in", "manual upload")])[0]

    def test_folder_with_only_zero_byte_files_is_empty(self, tmp_path):
        write(tmp_path / "in" / "a.csv", "")
        assert "is empty" in errors([(tmp_path / "in", "manual upload")])[0]

    def test_header_but_no_rows(self, tmp_path):
        write(tmp_path / "in" / "a.csv", "id,name\n")
        write(tmp_path / "in" / "b.csv", "id\n1\n")          # keeps the folder non-empty
        assert any("no data rows" in e for e in errors([(tmp_path / "in", "manual upload")]))


# ── Delinquent path ──────────────────────────────────────────────────────────

class TestDelinquentPath:

    def test_not_utf8_is_a_warning(self, tmp_path):
        p = tmp_path / "in" / "a.csv"
        p.parent.mkdir()
        p.write_bytes(b"id,name\n1,\xff\xfe\n")
        report = validate_inputs([(tmp_path / "in", "manual upload")])
        assert report.errors == []
        assert any("not valid UTF-8" in w for w in report.warnings)

    def test_other_file_types_are_skipped(self, tmp_path):
        p = tmp_path / "in" / "DE1_0_2008_Beneficiary_Summary_File_Sample_1.zip"
        p.parent.mkdir()
        p.write_bytes(b"PK\x03\x04 not really a zip")
        assert errors([(tmp_path / "in", "manual upload")]) == []

    def test_plain_text_txt_is_skipped(self, tmp_path):
        write(tmp_path / "in" / "README.txt", "This folder holds the raw files")
        assert errors([(tmp_path / "in", "manual upload")]) == []

    def test_row_errors_are_capped_then_summarised(self, tmp_path):
        write(tmp_path / "in" / "a.csv", "a,b\n" + "1\n" * 15)
        errs = errors([(tmp_path / "in", "manual upload")])
        assert len(errs) == 11 and "5 more line(s)" in errs[-1]


# ── Forgetful path ───────────────────────────────────────────────────────────

class TestForgetfulPath:

    def test_only_first_max_rows_are_checked(self, tmp_path):
        # the bad row is past the limit, so it isn't seen
        write(tmp_path / "in" / "a.csv", "a,b\n" + "1,2\n" * 5 + "bad\n")
        assert errors([(tmp_path / "in", "manual upload")], max_rows=5) == []
        assert errors([(tmp_path / "in", "manual upload")], max_rows=10) != []


# ── Platform ─────────────────────────────────────────────────────────────────

class TestPlatform:

    def test_sequence_runs_on_snowflake_but_not_databricks(self, tmp_path):
        write(tmp_path / "ddl" / "t.sql", "CREATE SEQUENCE s;")
        inputs = [(tmp_path / "ddl", "manual upload")]
        assert errors(inputs, platform="snowflake") == []
        assert any("can run on databricks" in e for e in errors(inputs, platform="databricks"))

    def test_unknown_platform_is_an_error(self, raw):
        assert any("not supported" in e for e in errors([(raw, "manual upload")], platform="foundry"))