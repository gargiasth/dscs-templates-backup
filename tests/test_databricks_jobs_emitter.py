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


# ── Path constants ────────────────────────────────────────────────────────────
# These mirror what the compiler passes in at runtime. Define them once here
# so each test can use the same values and assertions can reference the
# expected wrapper path directly.

WRAPPER_DIR    = "../utilities/wrappers"
WRAPPER_PREFIX = "run_"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def spec_one_task():
    """One stage with an entry_point → one task."""
    return {
        "project": "demo",
        "unity_catalog": {"catalog": "c", "schema": "s", "volume": "v"},
        "stages": [{
            "name": "get_raw",
            "layer": "bronze",
            "entry_point": {"file": "fetch.py", "path": "src/fetch.py", "parameters": ["all"]},
        }],
    }


@pytest.fixture
def spec_two_stages():
    """Bronze feeds silver via an auto source → tests the dependency chain."""
    return {
        "project": "demo",
        "unity_catalog": {"catalog": "c", "schema": "s", "volume": "v"},
        "stages": [
            {
                "name": "fetch",
                "layer": "bronze",
                "entry_point": {"file": "download.py", "path": "src/download.py", "parameters": []},
            },
            {
                "name": "transform",
                "layer": "silver",
                "sources": [{"data_upload_type": "auto", "from": "fetch"}],
                "entry_point": {"file": "etl.py", "path": "src/etl.py", "parameters": ["1"]},
                "destination": {"type": "volume", "subfolder_name": "clean"},
            },
        ],
    }


# ── Tests ─────────────────────────────────────────────────────────────────────

# HAPPY PATH — single stage, single script → single task pointing at the wrapper.
def test_happy_path_single_task(spec_one_task):
    """One stage with one script produces exactly one task that points at the wrapper."""
    parsed = yaml.safe_load(build_jobs_yml(spec_one_task, WRAPPER_DIR, WRAPPER_PREFIX))
    tasks = parsed["resources"]["jobs"]["demo"]["tasks"]
    assert len(tasks) == 2
    assert tasks[1]["spark_python_task"]["python_file"] == (
        f"{WRAPPER_DIR}/{WRAPPER_PREFIX}bronze_get_raw_fetch_py.py"
    )


# HAPPY PATH — upstream/downstream wiring via `auto` sources creates depends_on.
def test_happy_path_two_stages_create_dependency_chain(spec_two_stages):
    """An `auto` source makes the downstream task depend on the upstream task."""
    parsed = yaml.safe_load(build_jobs_yml(spec_two_stages, WRAPPER_DIR, WRAPPER_PREFIX))
    tasks = parsed["resources"]["jobs"]["demo"]["tasks"]

    silver_task = next(t for t in tasks if t["task_key"].startswith("silver_"))
    assert silver_task["depends_on"] == [{"task_key": "bronze_fetch_download_py"}]


# ANGRY PATH — missing required field raises ValueError.
def test_raises_when_project_missing():
    """Missing 'project' is a bug in the caller — fail loud, not silent."""
    with pytest.raises(ValueError, match="project"):
        build_jobs_yml({}, WRAPPER_DIR, WRAPPER_PREFIX)


# HAPPY PATH — convention check: task_key = <layer>_<stage>_<script_stem>.
def test_task_key_follows_layer_stage_file_convention(spec_one_task):
    """Convention: <layer>_<stage>_<script_stem>."""
    parsed = yaml.safe_load(build_jobs_yml(spec_one_task, WRAPPER_DIR, WRAPPER_PREFIX))
    tasks = parsed["resources"]["jobs"]["demo"]["tasks"]
    assert tasks[1]["task_key"] == "bronze_get_raw_fetch_py"


# HAPPY PATH — parameters are passed through exactly as entered; Orion's check params come after.
def test_parameters_passed_through_unchanged(spec_two_stages):
    """entry_point.parameters reach the task unchanged, followed by the ORION_OUTPUT check param."""
    parsed = yaml.safe_load(build_jobs_yml(spec_two_stages, WRAPPER_DIR, WRAPPER_PREFIX))
    tasks = parsed["resources"]["jobs"]["demo"]["tasks"]

    silver_task = next(t for t in tasks if t["task_key"].startswith("silver_"))
    assert silver_task["spark_python_task"]["parameters"] == [
        "1", "ORION_OUTPUT=${var.clean_subfolder_path}"]


# HAPPY PATH — custom wrapper_dir and wrapper_prefix are respected in the output.
def test_custom_wrapper_dir_and_prefix(spec_one_task):
    """Passing different wrapper_dir/wrapper_prefix values flows through to python_file."""
    parsed = yaml.safe_load(
        build_jobs_yml(spec_one_task, "../lib/runners", "exec_")
    )
    tasks = parsed["resources"]["jobs"]["demo"]["tasks"]
    assert tasks[1]["spark_python_task"]["python_file"] == (
        "../lib/runners/exec_bronze_get_raw_fetch_py.py"
    )

# HAPPY PATH — .sql entry points get catalog and schema as their first two params.
def test_sql_task_gets_catalog_and_schema():
    """The SQL wrapper needs catalog/schema as argv[1] and argv[2]."""
    spec = {
        "project": "demo",
        "stages": [{
            "name": "setup",
            "layer": "bronze",
            "entry_point": {"file": "ddl.sql", "path": "ddl.sql", "parameters": []},
        }],
    }
    parsed = yaml.safe_load(build_jobs_yml(spec, WRAPPER_DIR, WRAPPER_PREFIX))
    params = parsed["resources"]["jobs"]["demo"]["tasks"][1]["spark_python_task"]["parameters"]
    assert params == ["${var.catalog}", "${var.schema}"]

# ── Orion input/output check parameters ─────────────────────────────────────

def _io_spec():
    return {
        "project": "demo",
        "unity_catalog": {"catalog": "c", "schema": "s", "volume": "v",
                          "folders": [{"volume": "v", "subfolder": "vocab"}]},
        "stages": [
            {"name": "fetch", "layer": "bronze",
             "entry_point": {"file": "get.py", "path": "src/get.py", "parameters": []},
             "destination": {"type": "volume", "subfolder_name": "raw"}},
            {"name": "etl", "layer": "silver",
             "sources": [{"data_upload_type": "auto", "from": "fetch"},
                         {"data_upload_type": "manual", "subfolder_name": "vocab"}],
             "entry_point": {"file": "etl.py", "path": "src/etl.py", "parameters": ["1"]},
             "destination": {"type": "volume", "subfolder_name": "out"}},
            {"name": "load", "layer": "gold",
             "sources": [{"data_upload_type": "auto", "from": "etl"}],
             "entry_point": {"file": "load.py", "path": "src/load.py", "parameters": []},
             "destination": {"type": "tables", "tables": ["person"]}},
        ],
    }


def _params_of(spec, prefix):
    parsed = yaml.safe_load(build_jobs_yml(spec, WRAPPER_DIR, WRAPPER_PREFIX))
    task = next(t for t in parsed["resources"]["jobs"]["demo"]["tasks"] if t["task_key"].startswith(prefix))
    return task["spark_python_task"]["parameters"]


def test_output_folder_becomes_orion_output():
    assert _params_of(_io_spec(), "bronze_") == ["ORION_OUTPUT=${var.raw_subfolder_path}"]


def test_upstream_and_manual_inputs_become_orion_input():
    assert _params_of(_io_spec(), "silver_") == [
        "1",
        "ORION_INPUT=${var.raw_subfolder_path}|upstream task bronze_fetch_get_py",
        "ORION_INPUT=${var.vocab_subfolder_path}|manual upload",
        "ORION_OUTPUT=${var.out_subfolder_path}",
    ]


def test_tables_destination_has_no_orion_output():
    # gold writes tables, so only its upstream folder is checked
    assert _params_of(_io_spec(), "gold_") == [
        "ORION_INPUT=${var.out_subfolder_path}|upstream task silver_etl_etl_py"]


def test_upstream_without_output_folder_is_not_checked(spec_two_stages):
    # fetch has no destination subfolder, so there is no folder to check for transform
    params = _params_of(spec_two_stages, "silver_")
    assert not any(p.startswith("ORION_INPUT=") for p in params)



def test_preflight_creates_every_folder_the_spec_names():
    parsed = yaml.safe_load(build_jobs_yml(_io_spec(), WRAPPER_DIR, WRAPPER_PREFIX))
    preflight = parsed["resources"]["jobs"]["demo"]["tasks"][0]
    assert preflight["spark_python_task"]["parameters"] == [
        "${var.catalog}", "${var.schema}", "${var.volume}",
        "ORION_FOLDER=${var.vocab_subfolder_path}",
        "ORION_FOLDER=${var.raw_subfolder_path}",
        "ORION_FOLDER=${var.out_subfolder_path}",
    ]


# ── Environment dependencies ─────────────────────────────────────────────────

def _deps(spec, **kw):
    parsed = yaml.safe_load(build_jobs_yml(spec, WRAPPER_DIR, WRAPPER_PREFIX, **kw))
    return parsed["resources"]["jobs"]["demo"]["environments"][0]["spec"]["dependencies"]


def test_sqlglot_is_always_a_dependency(spec_one_task):
    assert _deps(spec_one_task) == ["sqlglot"]


def test_requirements_are_added_once(spec_one_task, tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("python-dotenv\nsqlglot\npandas==2.2.2\n")
    assert _deps(spec_one_task, requirements_path=req) == ["sqlglot", "python-dotenv", "pandas==2.2.2"]


def test_requirements_skip_comments_blanks_and_pip_options(spec_one_task, tmp_path, caplog):
    req = tmp_path / "requirements.txt"
    req.write_text("# deps\n\npandas  # data\n-r other.txt\n")
    assert _deps(spec_one_task, requirements_path=req) == ["sqlglot", "pandas"]
    assert "skipped pip option" in caplog.text


def test_missing_requirements_file_warns(spec_one_task, tmp_path, caplog):
    assert _deps(spec_one_task, requirements_path=tmp_path / "nope.txt") == ["sqlglot"]
    assert "not found" in caplog.text