"""
Tests for validation/spec_validator.py

Run from the repo root:
    pytest tests/test_spec_validator.py

Each test is tagged with the "path" it exercises:
    - Happy path   : valid input, expected output
    - Angry path   : invalid input, raises the right error
    - Desolate path: empty input (empty lists/dicts)
    - Delinquent   : malformed input, wrong types or placeholder sentinels
    - Forgetful    : optional fields missing from the input
"""

import copy

import pytest

from validation.spec_validator import validate_spec, SpecValidationError


@pytest.fixture
def good_spec():
    return {
        "project": "etl-cms-ohdsi",
        "runtime": {"workspace_url": "https://dbc-1234.cloud.databricks.com"},
        "unity_catalog": {
            "catalog": "etl_cms", "schema": "ohdsi_cdm", "volume": "ohdsi_volume",
            "folders": [{"volume": "ohdsi_volume", "subfolder": "omop_vocabulary"}],
        },
        "stages": [
            {"name": "bronze", "layer": "bronze", "sources": [],
             "entry_point": {"file": "get.py", "path": "src/get.py", "parameters": ["1"]},
             "destination": {"type": "volume", "subfolder_name": "synpuf_raw"}},
            {"name": "silver", "layer": "silver",
             "sources": [{"data_upload_type": "auto", "from": "bronze"},
                         {"data_upload_type": "manual", "subfolder_name": "omop_vocabulary"}],
             "entry_point": {"file": "etl.py", "path": "src/etl.py", "parameters": []},
             "destination": {"type": "volume", "subfolder_name": "etl_output"}},
        ],
    }


def errors_of(spec):
    return validate_spec(spec).errors


# ── Happy path ───────────────────────────────────────────────────────────────

class TestHappyPath:

    def test_valid_spec_has_no_errors_or_warnings(self, good_spec):
        report = validate_spec(good_spec)
        assert report.errors == []
        assert report.warnings == []

    def test_error_lists_every_problem_at_once(self, good_spec):
        good_spec["project"] = "bad name"
        good_spec["unity_catalog"]["schema"] = ""
        assert len(errors_of(good_spec)) == 2

    def test_spec_validation_error_is_a_value_error(self):
        # the compiler raises this; existing callers catching ValueError still work
        assert issubclass(SpecValidationError, ValueError)


# ── Angry path ───────────────────────────────────────────────────────────────

class TestAngryPath:

    def test_missing_project(self, good_spec):
        del good_spec["project"]
        assert any(e.startswith("project:") for e in errors_of(good_spec))

    def test_missing_unity_catalog(self, good_spec):
        del good_spec["unity_catalog"]
        assert "unity_catalog: is required" in errors_of(good_spec)

    def test_workspace_url_must_be_https(self, good_spec):
        good_spec["runtime"]["workspace_url"] = "www.example.com"
        assert any("must start with https://" in e for e in errors_of(good_spec))

    def test_unknown_layer_type(self, good_spec):
        good_spec["stages"][0]["layer"] = "brnze"
        assert any(".layer" in e for e in errors_of(good_spec))

    def test_entry_point_must_be_py_or_sql(self, good_spec):
        good_spec["stages"][0]["entry_point"]["file"] = ".env.example"
        assert any("must be a .py or .sql file" in e for e in errors_of(good_spec))

    def test_upstream_stage_must_exist(self, good_spec):
        good_spec["stages"][1]["sources"][0]["from"] = "raw"
        assert any("'raw' does not exist" in e for e in errors_of(good_spec))

    def test_upstream_stage_must_come_first(self, good_spec):
        good_spec["stages"].reverse()
        assert any("must come before this stage" in e for e in errors_of(good_spec))

    def test_stage_names_clash_after_sanitising(self, good_spec):
        clone = copy.deepcopy(good_spec["stages"][0])
        clone["name"] = "Bronze"          # becomes 'bronze' in task keys
        good_spec["stages"].append(clone)
        assert any("clashes with 'bronze'" in e for e in errors_of(good_spec))

    def test_duplicate_folder(self, good_spec):
        good_spec["unity_catalog"]["folders"].append(
            {"volume": "ohdsi_volume", "subfolder": "omop_vocabulary"})
        assert any("declared more than once" in e for e in errors_of(good_spec))


# ── Desolate path ────────────────────────────────────────────────────────────

class TestDesolatePath:

    def test_empty_stages_is_fine(self, good_spec):
        good_spec["stages"] = []
        assert errors_of(good_spec) == []

    def test_empty_dict_reports_required_fields(self):
        errs = errors_of({})
        assert any(e.startswith("project:") for e in errs)
        assert "unity_catalog: is required" in errs
        assert any(e.startswith("stages:") for e in errs)


# ── Delinquent path ──────────────────────────────────────────────────────────

class TestDelinquentPath:

    @pytest.mark.parametrize("field", ["catalog", "schema", "volume"])
    def test_intake_placeholders_are_errors(self, good_spec, field):
        good_spec["unity_catalog"][field] = f"{field}_default"
        assert any("placeholder" in e for e in errors_of(good_spec))

    def test_placeholder_tables_is_an_error(self, good_spec):
        good_spec["stages"][1]["destination"] = {"type": "tables", "tables": "tables_default"}
        assert any("no tables selected" in e for e in errors_of(good_spec))

    def test_bad_subfolder_name(self, good_spec):
        good_spec["stages"][0]["destination"]["subfolder_name"] = "../escape"
        assert any("subfolder_name" in e for e in errors_of(good_spec))

    def test_spec_not_a_dict(self):
        assert errors_of(["not", "a", "spec"]) == ["spec: must be a JSON object"]

    def test_parameters_must_be_strings(self, good_spec):
        good_spec["stages"][0]["entry_point"]["parameters"] = [1, 2]
        assert any("list of strings" in e for e in errors_of(good_spec))


# ── Forgetful path ───────────────────────────────────────────────────────────

class TestForgetfulPath:

    def test_no_entry_point_is_a_warning_not_an_error(self, good_spec):
        good_spec["stages"][1]["entry_point"] = "entry_point_default"
        report = validate_spec(good_spec)
        assert report.errors == []
        assert any("will produce no task" in w for w in report.warnings)

    def test_no_workspace_url_is_a_warning(self, good_spec):
        del good_spec["runtime"]
        report = validate_spec(good_spec)
        assert report.errors == []
        assert any("workspace_url" in w for w in report.warnings)

    def test_no_folders_key_is_fine(self, good_spec):
        del good_spec["unity_catalog"]["folders"]
        assert errors_of(good_spec) == []


# ── Logging ──────────────────────────────────────────────────────────────────

def test_problems_are_logged(good_spec, caplog):
    good_spec["project"] = "bad name"
    good_spec["stages"][1]["entry_point"] = "entry_point_default"
    with caplog.at_level("INFO", logger="validation.spec_validator"):
        validate_spec(good_spec)
    levels = {r.levelname for r in caplog.records}
    assert {"ERROR", "WARNING", "INFO"} <= levels
    assert "1 error(s), 1 warning(s)" in caplog.text


# ── Entry-point files on disk ────────────────────────────────────────────────

@pytest.fixture
def repo(tmp_path):
    """A fake repo root with the two scripts good_spec points at."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "get.py").write_text("print('get')\n", encoding="utf-8")
    (tmp_path / "src" / "etl.py").write_text("print('etl')\n", encoding="utf-8")
    return tmp_path


class TestEntryFiles:

    def test_files_present_no_errors(self, good_spec, repo):
        report = validate_spec(good_spec, repo_root=repo)
        assert report.errors == [] and report.warnings == []

    def test_no_repo_root_skips_file_checks(self, good_spec):
        # nothing on disk, but no repo_root given -> not checked
        assert errors_of(good_spec) == []

    def test_missing_file(self, good_spec, repo):
        (repo / "src" / "etl.py").unlink()
        errors = validate_spec(good_spec, repo_root=repo).errors
        assert len(errors) == 1 and "file not found" in errors[0]

    def test_path_is_a_folder(self, good_spec, repo):
        good_spec["stages"][0]["entry_point"]["path"] = "src"
        good_spec["stages"][0]["entry_point"]["file"] = "src.py"   # keep the extension check happy
        errors = validate_spec(good_spec, repo_root=repo).errors
        assert any("is a folder" in e for e in errors)

    def test_python_syntax_error(self, good_spec, repo):
        (repo / "src" / "get.py").write_text("def broken(:\n", encoding="utf-8")
        errors = validate_spec(good_spec, repo_root=repo).errors
        assert len(errors) == 1 and "syntax error at line 1" in errors[0]

    def test_empty_file_is_a_warning(self, good_spec, repo):
        (repo / "src" / "get.py").write_text("", encoding="utf-8")
        report = validate_spec(good_spec, repo_root=repo)
        assert report.errors == []
        assert any("file is empty" in w for w in report.warnings)

    def test_not_utf8(self, good_spec, repo):
        (repo / "src" / "get.py").write_bytes(b"\xff\xfe\x00bad")
        errors = validate_spec(good_spec, repo_root=repo).errors
        assert any("not UTF-8" in e for e in errors)

    def test_sql_file_is_not_parsed_as_python(self, good_spec, repo):
        good_spec["stages"][0]["entry_point"] = {"file": "t.sql", "path": "src/t.sql", "parameters": []}
        (repo / "src" / "t.sql").write_text("CREATE TABLE a (x INT);", encoding="utf-8")
        assert validate_spec(good_spec, repo_root=repo).errors == []

    def test_windows_backslash_path(self, good_spec, repo):
        good_spec["stages"][0]["entry_point"]["path"] = "src\\get.py"
        # on Linux a backslash is part of the name, so only run where it is a separator
        import os
        if os.sep == "\\":
            assert validate_spec(good_spec, repo_root=repo).errors == []


# ── Variable references in parameters ───────────────────────────────────────

def _params(spec, stage, params):
    spec["stages"][stage]["entry_point"]["parameters"] = params


class TestVarRefs:

    def test_declared_vars_are_fine(self, good_spec):
        # catalog, destination folder and a registry folder are all declared
        _params(good_spec, 1, ["${var.catalog}",
                               "OUT=${var.etl_output_subfolder_path}",
                               "VOCAB=${var.omop_vocabulary_subfolder_path}/v5"])
        assert errors_of(good_spec) == []

    def test_undeclared_var_is_an_error(self, good_spec):
        _params(good_spec, 1, ["${var.synpuf_raw_subfolder_pth}"])   # typo
        errors = errors_of(good_spec)
        assert len(errors) == 1 and "is not declared" in errors[0]

    @pytest.mark.parametrize("bad", ["{var.catalog}", "$var.catalog", "${var.catalog", "${catalog}"])
    def test_malformed_refs_are_errors(self, good_spec, bad):
        _params(good_spec, 1, [bad])
        errors = errors_of(good_spec)
        assert any("malformed" in e for e in errors)

    def test_python_format_braces_are_not_flagged(self, good_spec):
        _params(good_spec, 1, ["SYNPUF_DIR_FORMAT=DE_{0}"])
        assert errors_of(good_spec) == []

    def test_hardcoded_volume_path_is_a_warning(self, good_spec):
        _params(good_spec, 1, ["OUT=/Volumes/etl_cms/ohdsi_cdm/ohdsi_volume/etl_output/control"])
        report = validate_spec(good_spec)
        assert report.errors == []
        assert any("use ${var.etl_output_subfolder_path}" in w for w in report.warnings)


# ── SQL entry points ────────────────────────────────────────────────────────

class TestSqlEntry:

    def _sql_stage(self, good_spec, repo, sql):
        good_spec["stages"][0]["entry_point"] = {"file": "t.sql", "path": "src/t.sql", "parameters": []}
        (repo / "src" / "t.sql").write_text(sql, encoding="utf-8")
        return validate_spec(good_spec, repo_root=repo)

    def test_runnable_sql_is_fine(self, good_spec, repo):
        report = self._sql_stage(good_spec, repo, "CREATE TABLE a (x INT);")
        assert report.errors == [] and report.warnings == []

    def test_unsupported_statement_is_a_warning(self, good_spec, repo):
        report = self._sql_stage(good_spec, repo, "CREATE TABLE a (x INT); CREATE SEQUENCE s;")
        assert report.errors == []
        assert any("will be skipped" in w for w in report.warnings)

    def test_nothing_runnable_is_an_error(self, good_spec, repo):
        report = self._sql_stage(good_spec, repo, "CREATE SEQUENCE s;")
        assert any("no statements that can run" in e for e in report.errors)

    def test_comments_only_is_an_error(self, good_spec, repo):
        report = self._sql_stage(good_spec, repo, "-- nothing here\n")
        assert any("no statements that can run" in e for e in report.errors)