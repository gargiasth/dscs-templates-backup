"""
Tests for utilities/compiler.py

Run from the repo root:
    pytest tests/test_compiler.py

Each test is tagged with the "path" it exercises:
    - Happy path   : valid input, expected output
    - Angry path   : invalid input, raises the right error
    - Desolate path: empty input (empty lists/dicts)
    - Delinquent   : malformed input, wrong types or placeholder sentinels
    - Forgetful    : optional fields missing from the input

These are integration tests: compile_bundle writes real files to disk
(via tmp_path), and we check the output tree is correct and the YAMLs
are parseable. Mocking the sub-emitters would hide real wiring issues
between them.
"""

import inspect
import json
from pathlib import Path

import pytest
import yaml

from utilities.compiler import compile_bundle


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def minimal_spec_dict():
    """Smallest spec that produces one wrapper + one task."""
    return {
        "project": "demo",
        "unity_catalog": {"catalog": "c", "schema": "s", "volume": "v"},
        "stages": [{
            "name": "fetch",
            "layer": "bronze",
            "sources": [{
                "data_upload_type": "custom_script",
                "subfolder_name": "raw",
                "scripts": [{
                    "file": "download.py",
                    "path": "src/download.py",
                    "parameters": [],
                }],
            }],
            "entry_point": {
                "file": "download.py",
                "path": "src/download.py",
                "parameters": [],
            },
        }],
    }


@pytest.fixture
def minimal_spec_path(minimal_spec_dict, tmp_path):
    """A minimal spec written to a tmp file. Returns its path."""
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(minimal_spec_dict), encoding="utf-8")
    return path


@pytest.fixture
def output_dir(tmp_path):
    """Isolated output directory inside tmp_path."""
    return tmp_path / "output"


# ── Happy path ───────────────────────────────────────────────────────────────

class TestHappyPath:
    """Valid inputs that should produce the expected output."""

    def test_returns_dict_with_expected_keys(self, minimal_spec_path, output_dir):
        result = compile_bundle(minimal_spec_path, output_dir)
        assert set(result.keys()) == {"wrappers", "databricks_yml", "jobs_yml"}

    def test_creates_databricks_yml(self, minimal_spec_path, output_dir):
        result = compile_bundle(minimal_spec_path, output_dir)
        assert result["databricks_yml"].exists()
        assert result["databricks_yml"].name == "databricks.yml"

    def test_creates_jobs_yml_under_resources(self, minimal_spec_path, output_dir):
        result = compile_bundle(minimal_spec_path, output_dir)
        assert result["jobs_yml"].exists()
        # Path should be <output_dir>/resources/databricks_jobs.yml
        assert result["jobs_yml"].parent.name == "resources"
        assert result["jobs_yml"].name == "databricks_jobs.yml"

    def test_creates_wrappers_under_utilities_wrappers(self, minimal_spec_path, output_dir):
        result = compile_bundle(minimal_spec_path, output_dir)
        assert len(result["wrappers"]) == 1
        wrapper_path = result["wrappers"][0]
        assert wrapper_path.exists()
        # Should land in <output_dir>/utilities/wrappers/
        assert wrapper_path.parent.name == "wrappers"
        assert wrapper_path.parent.parent.name == "utilities"

    def test_wrapper_filename_uses_run_prefix(self, minimal_spec_path, output_dir):
        result = compile_bundle(minimal_spec_path, output_dir)
        assert result["wrappers"][0].name.startswith("run_")

    def test_databricks_yml_is_parseable(self, minimal_spec_path, output_dir):
        result = compile_bundle(minimal_spec_path, output_dir)
        parsed = yaml.safe_load(result["databricks_yml"].read_text())
        assert parsed["bundle"]["name"] == "demo"

    def test_jobs_yml_is_parseable(self, minimal_spec_path, output_dir):
        result = compile_bundle(minimal_spec_path, output_dir)
        parsed = yaml.safe_load(result["jobs_yml"].read_text())
        tasks = parsed["resources"]["jobs"]["demo"]["tasks"]
        assert len(tasks) == 1

    def test_accepts_string_paths(self, minimal_spec_path, output_dir):
        """Both args accept str, not just Path."""
        result = compile_bundle(str(minimal_spec_path), str(output_dir))
        assert result["databricks_yml"].exists()

    def test_creates_output_dir_if_missing(self, minimal_spec_path, tmp_path):
        """Output dir doesn't need to exist beforehand."""
        new_dir = tmp_path / "does" / "not" / "exist" / "yet"
        assert not new_dir.exists()
        compile_bundle(minimal_spec_path, new_dir)
        assert new_dir.exists()

    def test_every_task_points_at_an_existing_wrapper(self, minimal_spec_path, output_dir):
        """Each task's python_file must resolve to a wrapper the compiler actually wrote."""
        result = compile_bundle(minimal_spec_path, output_dir)
        parsed = yaml.safe_load(result["jobs_yml"].read_text())

        for task in parsed["resources"]["jobs"]["demo"]["tasks"]:
            python_file = task["spark_python_task"]["python_file"]
            wrapper = (result["jobs_yml"].parent / python_file).resolve()
            assert wrapper.exists(), f"{task['task_key']} points at missing {wrapper}"
            
# ── Angry path ───────────────────────────────────────────────────────────────

class TestAngryPath:
    """Invalid inputs that should raise an error."""

    def test_missing_spec_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            compile_bundle(tmp_path / "nope.json", tmp_path / "out")

    def test_invalid_json_raises(self, tmp_path, output_dir):
        bad_spec = tmp_path / "bad.json"
        bad_spec.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            compile_bundle(bad_spec, output_dir)

    def test_spec_missing_project_raises(self, tmp_path, output_dir):
        bad_spec = tmp_path / "no_project.json"
        bad_spec.write_text(json.dumps({"stages": []}), encoding="utf-8")
        with pytest.raises(ValueError, match="project"):
            compile_bundle(bad_spec, output_dir)


# ── Desolate path ────────────────────────────────────────────────────────────

class TestDesolatePath:
    """Empty inputs — empty stages, nothing to generate."""

    def test_empty_stages_still_writes_yamls(self, tmp_path, output_dir):
        spec = {
            "project": "demo",
            "unity_catalog": {"catalog": "c", "schema": "s", "volume": "v"},
            "stages": [],
        }
        spec_path = tmp_path / "empty.json"
        spec_path.write_text(json.dumps(spec), encoding="utf-8")

        result = compile_bundle(spec_path, output_dir)
        assert result["databricks_yml"].exists()
        assert result["jobs_yml"].exists()
        assert result["wrappers"] == []

    def test_empty_stages_jobs_yml_has_no_tasks(self, tmp_path, output_dir):
        spec = {
            "project": "demo",
            "unity_catalog": {"catalog": "c", "schema": "s", "volume": "v"},
            "stages": [],
        }
        spec_path = tmp_path / "empty.json"
        spec_path.write_text(json.dumps(spec), encoding="utf-8")

        result = compile_bundle(spec_path, output_dir)
        parsed = yaml.safe_load(result["jobs_yml"].read_text())
        tasks = parsed["resources"]["jobs"]["demo"]["tasks"]
        assert tasks == []


# ── Delinquent path ──────────────────────────────────────────────────────────

class TestDelinquentPath:
    """Malformed stages — sentinels, bad extensions. Compiler should skip, not crash."""

    def test_stage_with_sentinel_entry_point_produces_no_wrapper(self, tmp_path, output_dir):
        spec = {
            "project": "demo",
            "unity_catalog": {"catalog": "c", "schema": "s", "volume": "v"},
            "stages": [{
                "name": "gold",
                "layer": "gold",
                "sources": [],
                "entry_point": "entry_point_default",  # sentinel string
            }],
        }
        spec_path = tmp_path / "sentinel.json"
        spec_path.write_text(json.dumps(spec), encoding="utf-8")

        result = compile_bundle(spec_path, output_dir)
        assert result["wrappers"] == []
        # databricks.yml and jobs YAML should still land fine
        assert result["databricks_yml"].exists()
        assert result["jobs_yml"].exists()

    def test_stage_with_unsupported_extension_produces_no_wrapper(self, tmp_path, output_dir):
        spec = {
            "project": "demo",
            "unity_catalog": {"catalog": "c", "schema": "s", "volume": "v"},
            "stages": [{
                "name": "weird",
                "layer": "bronze",
                "sources": [],
                "entry_point": {
                    "file": "data.csv",   # not .py or .sql
                    "path": "data.csv",
                    "parameters": [],
                },
            }],
        }
        spec_path = tmp_path / "weird.json"
        spec_path.write_text(json.dumps(spec), encoding="utf-8")

        result = compile_bundle(spec_path, output_dir)
        assert result["wrappers"] == []
        parsed = yaml.safe_load(result["jobs_yml"].read_text())
        assert parsed["resources"]["jobs"]["demo"]["tasks"] == []


# ── Forgetful path ───────────────────────────────────────────────────────────

class TestForgetfulPath:
    """Optional fields missing — both args should have sensible defaults."""

    def test_both_args_have_defaults(self):
        """compile_bundle() should be callable with no args."""
        sig = inspect.signature(compile_bundle)
        for name in ("spec_path", "output_dir"):
            assert sig.parameters[name].default is not inspect.Parameter.empty, (
                f"{name!r} should have a default value"
            )

    def test_defaults_point_at_sensible_paths(self):
        """Defaults should be Path objects, not None."""
        from utilities.compiler import DEFAULT_SPEC_PATH, DEFAULT_OUTPUT_DIR
        assert isinstance(DEFAULT_SPEC_PATH, Path)
        assert isinstance(DEFAULT_OUTPUT_DIR, Path)