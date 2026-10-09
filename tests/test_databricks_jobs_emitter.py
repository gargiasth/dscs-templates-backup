"""
Tests for utilities/databricks_jobs_emitter.py

Run from the repo root:
    pytest tests/test_databricks_jobs_emitter.py

Each test is tagged with the "path" it exercises:
    - Happy path   : valid input, expected output
    - Angry path   : invalid input, raises the right error
    - Desolate path: empty input (empty lists/dicts)
    - Delinquent   : malformed input, wrong types or placeholder sentinels
    - Forgetful    : optional fields missing from the input
"""

import pytest
import yaml

from utilities.databricks_jobs_emitter import build_jobs_yml


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def spec_one_task():
    """Spec with a single custom_script source → one task."""
    return {
        "project": "demo",
        "unity_catalog": {"catalog": "c", "schema": "s", "volume": "v"},
        "stages": [{
            "name": "get_raw",
            "layer": "bronze",
            "sources": [{
                "data_upload_type": "custom_script",
                "subfolder_name": "raw",
                "scripts": [{"file": "fetch.py", "parameters": ["all"]}],
            }],
        }],
    }


@pytest.fixture
def spec_two_stages():
    """Spec with bronze stage feeding silver via an auto source → tests dependency chain."""
    return {
        "project": "demo",
        "unity_catalog": {"catalog": "c", "schema": "s", "volume": "v"},
        "stages": [
            {
                "name": "fetch",
                "layer": "bronze",
                "sources": [{
                    "data_upload_type": "custom_script",
                    "subfolder_name": "raw",
                    "scripts": [{"file": "download.py", "parameters": []}],
                }],
            },
            {
                "name": "transform",
                "layer": "silver",
                "sources": [{"data_upload_type": "auto", "from": "fetch"}],
                "scripts": [{"file": "etl.py", "path": "src/etl.py", "parameters": []}],
                "destination": {"type": "volume", "subfolder_name": "clean"},
            },
        ],
    }


# ── Tests ─────────────────────────────────────────────────────────────────────

# HAPPY PATH — single stage, single script → single task with the right python_file.
def test_happy_path_single_task(spec_one_task):
    """One stage with one script produces exactly one task."""
    parsed = yaml.safe_load(build_jobs_yml(spec_one_task))
    tasks = parsed["resources"]["jobs"]["demo"]["tasks"]
    assert len(tasks) == 1
    assert tasks[0]["spark_python_task"]["python_file"] == "../src/fetch.py"


# HAPPY PATH — upstream/downstream wiring via `auto` sources creates depends_on.
def test_happy_path_two_stages_create_dependency_chain(spec_two_stages):
    """An `auto` source makes the downstream task depend on the upstream task."""
    parsed = yaml.safe_load(build_jobs_yml(spec_two_stages))
    tasks = parsed["resources"]["jobs"]["demo"]["tasks"]

    silver_task = next(t for t in tasks if t["task_key"].startswith("silver_"))
    assert silver_task["depends_on"] == [{"task_key": "bronze_fetch_download"}]


# ANGRY PATH — missing required field raises ValueError.
def test_raises_when_project_missing():
    """Missing 'project' is a bug in the caller — fail loud, not silent."""
    with pytest.raises(ValueError, match="project"):
        build_jobs_yml({})


# HAPPY PATH — convention check: task_key = <layer>_<stage>_<script_stem>.
def test_task_key_follows_layer_stage_file_convention(spec_one_task):
    """Convention: <layer>_<stage>_<script_stem>."""
    parsed = yaml.safe_load(build_jobs_yml(spec_one_task))
    tasks = parsed["resources"]["jobs"]["demo"]["tasks"]
    assert tasks[0]["task_key"] == "bronze_get_raw_fetch"


# HAPPY PATH — destination path is auto-prepended before user-provided params.
def test_destination_path_is_auto_prepended_to_params(spec_two_stages):
    """The destination subfolder var ref is auto-prepended before user-provided params."""
    parsed = yaml.safe_load(build_jobs_yml(spec_two_stages))
    tasks = parsed["resources"]["jobs"]["demo"]["tasks"]

    silver_task = next(t for t in tasks if t["task_key"].startswith("silver_"))
    params = silver_task["spark_python_task"]["parameters"]
    assert params[0] == "${var.clean_subfolder_path}"

