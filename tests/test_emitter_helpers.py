"""
Tests for utilities/emitter_helpers.py

Run from the repo root:
    pytest tests/test_emitter_helpers.py

Each test is tagged with the "path" it exercises:
    - Happy path   : valid input, expected output
    - Angry path   : invalid input, raises the right error
    - Desolate path: empty input (empty lists/dicts)
    - Delinquent   : malformed input, wrong types or placeholder sentinels
    - Forgetful    : optional fields missing from the input
"""

from utilities.emitter_helpers import (
    _var_safe,
    _var_ref,
    _volume_path,
    _task_key,
    _collect_variables,
)


# HAPPY + DELINQUENT + DESOLATE — one function, every path in a single test.
#   "MyName"       → happy  (normal input)
#   "my-name.py"   → delinquent (special chars need sanitizing)
#   "--hello--"    → delinquent (leading/trailing special chars)
#   ""             → desolate (empty input triggers fallback)
def test_var_safe_sanitizes_input():
    assert _var_safe("MyName")       == "myname"
    assert _var_safe("my-name.py")   == "my_name_py"
    assert _var_safe("--hello--")    == "hello"
    assert _var_safe("")             == "stage"   # fallback


# HAPPY PATH — valid name wrapped in bundle variable syntax.
def test_var_ref_wraps_name_in_bundle_syntax():
    assert _var_ref("catalog") == "${var.catalog}"


# HAPPY PATH — standard UC dict + subfolder composes the expected volume path.
def test_volume_path_composes_from_uc_dict():
    uc = {"catalog": "etl_cms", "schema": "ohdsi_cdm", "volume": "ohdsi_volume"}
    result = _volume_path(uc, "synpuf_raw")
    assert result == "/Volumes/etl_cms/ohdsi_cdm/ohdsi_volume/synpuf_raw"


# HAPPY + DELINQUENT — convention holds, including when segments contain unsafe chars.
def test_task_key_follows_layer_stage_convention():
    # happy — clean segments
    assert _task_key("bronze", "get_raw", "download") == "bronze_get_raw_download"
    # delinquent — mixed case + special chars still produce a safe key
    assert _task_key("Bronze", "Get-Raw", "Script.1") == "bronze_get_raw_script_1"


# HAPPY PATH — minimal spec; UC vars + one subfolder var are collected correctly.
def test_collect_variables_from_minimal_spec():
    spec = {
        "project": "demo",
        "unity_catalog": {"catalog": "c", "schema": "s", "volume": "v"},
        "stages": [{
            "name": "bronze",
            "sources": [{"data_upload_type": "custom_script", "subfolder_name": "raw"}],
        }],
    }
    variables = _collect_variables(spec)

    # Unity Catalog creates three top-level variables
    assert variables["catalog"]["default"] == "c"
    assert variables["schema"]["default"]  == "s"
    assert variables["volume"]["default"]  == "v"

    # Subfolder creates a *_subfolder_path variable with the volume path
    assert variables["raw_subfolder_path"]["default"] == "/Volumes/c/s/v/raw"