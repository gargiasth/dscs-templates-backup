"""
Tests for utilities/databricks_yml_emitter.py

Run from the repo root:
    pytest tests/test_databricks_yml_emitter.py

Each test is tagged with the "path" it exercises:
    - Happy path   : valid input, expected output
    - Angry path   : invalid input, raises the right error
    - Desolate path: empty input (empty lists/dicts)
    - Delinquent   : malformed input, wrong types or placeholder sentinels
    - Forgetful    : optional fields missing from the input
"""

import json
from pathlib import Path

import pytest
import yaml

from utilities.databricks_yml_emitter import build_databricks_yml


# ── Path constants ────────────────────────────────────────────────────────────
# These mirror what the compiler passes in at runtime. Define them once here
# so every test uses the same values and assertions can reference them.

RESOURCES_DIR = "resources"

# Sample spec lives alongside the tests. Skip the real-world test if it
# hasn't been checked in yet (CI runners won't have it otherwise).
SAMPLE_SPEC_PATH = Path(__file__).parent / "test_data" / "sample_OrionConfig.json"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def minimal_spec():
    """Smallest spec that doesn't crash the emitter."""
    return {
        "project": "demo",
        "unity_catalog": {"catalog": "c", "schema": "s", "volume": "v"},
        "stages": [],
    }


@pytest.fixture
def sample_spec():
    """The real OHDSI sample spec checked into the repo."""
    if not SAMPLE_SPEC_PATH.exists():
        pytest.skip(f"sample spec not found at {SAMPLE_SPEC_PATH}")
    return json.loads(SAMPLE_SPEC_PATH.read_text())


# ── Tests ─────────────────────────────────────────────────────────────────────

# HAPPY PATH — valid minimal input, YAML structure is as expected.
def test_happy_path_minimal_spec(minimal_spec):
    """Minimal spec produces parseable YAML with the right bundle name."""
    output = build_databricks_yml(minimal_spec, RESOURCES_DIR)
    parsed = yaml.safe_load(output)
    assert parsed["bundle"]["name"] == "demo"
    assert parsed["include"]        == [f"{RESOURCES_DIR}/*.yml"]


# HAPPY PATH — real-world input (OHDSI sample) builds correctly end-to-end.
def test_happy_path_full_sample_spec(sample_spec):
    """The real OHDSI sample builds and declares the Unity Catalog variables."""
    output = build_databricks_yml(sample_spec, RESOURCES_DIR)
    parsed = yaml.safe_load(output)
    for key in ("catalog", "schema", "volume"):
        assert key in parsed["variables"]


# ANGRY PATH — invalid input (missing required field) must raise ValueError.
def test_raises_when_project_missing():
    """Missing 'project' is a bug in the caller — fail loud, not silent."""
    with pytest.raises(ValueError, match="project"):
        build_databricks_yml({}, RESOURCES_DIR)


# FORGETFUL PATH — optional field (workspace_url) omitted; emitter skips its block.
def test_omits_targets_when_no_workspace_url(minimal_spec):
    """Without a workspace URL, the targets block is skipped entirely."""
    parsed = yaml.safe_load(build_databricks_yml(minimal_spec, RESOURCES_DIR))
    assert "targets" not in parsed


# DESOLATE PATH — empty stages list; emitter should still produce valid YAML.
def test_handles_empty_stages(minimal_spec):
    """Empty stages still produces valid YAML — just no stage-derived variables."""
    minimal_spec["stages"] = []
    parsed = yaml.safe_load(build_databricks_yml(minimal_spec, RESOURCES_DIR))
    # Only the three UC vars should exist
    assert set(parsed["variables"].keys()) == {"catalog", "schema", "volume"}


# HAPPY PATH — custom resources_dir flows through to the include glob.
def test_custom_resources_dir(minimal_spec):
    """Passing a different resources_dir shows up in the include glob."""
    parsed = yaml.safe_load(build_databricks_yml(minimal_spec, "jobs"))
    assert parsed["include"] == ["jobs/*.yml"]