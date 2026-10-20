"""
Tests for utilities/generate_wrapper.py

Run from the repo root:
    pytest tests/test_generate_wrapper.py

Each test is tagged with the "path" it exercises:
    - Happy path   : valid input, expected output
    - Angry path   : invalid input, raises the right error
    - Desolate path: empty input (empty lists/dicts)
    - Delinquent   : malformed input, wrong types or placeholder sentinels
    - Forgetful    : optional fields missing from the input
"""

import pytest
from pathlib import Path

from utilities.generate_wrapper import produce_wrapper, write_all_wrappers


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def py_stage():
    return {
        "name": "bronze",
        "layer": "bronze",
        "entry_point": {
            "file": "get_synpuf_files.py",
            "path": "src/get_synpuf_files.py",
            "parameters": ["all"],
        },
    }


@pytest.fixture
def sql_stage():
    return {
        "name": "table_setup",
        "layer": "bronze",
        "entry_point": {
            "file": "create_CDMv5_tables.sql",
            "path": "tests/test_data/create_CDMv5_tables.sql",
            "parameters": [],
        },
    }


@pytest.fixture
def multi_stage_spec(py_stage, sql_stage):
    return {"stages": [sql_stage, py_stage]}


# ── Happy path ───────────────────────────────────────────────────────────────

class TestHappyPath:
    """Valid inputs that should produce the expected output."""

    def test_py_wrapper_contains_subprocess_and_script_path(self, py_stage):
        code = produce_wrapper(py_stage, wrapper_depth=2)
        assert "subprocess" in code
        assert "src/get_synpuf_files.py" in code

    def test_sql_wrapper_imports_sql_utilities(self, sql_stage):
        code = produce_wrapper(sql_stage, wrapper_depth=2)
        assert "execute_statements" in code
        assert "read_sql_file" in code
        assert "translate" in code
        assert "tests/test_data/create_CDMv5_tables.sql" in code

    def test_wrapper_depth_2_emits_three_parents(self, py_stage):
        code = produce_wrapper(py_stage, wrapper_depth=2)
        assert "Path(__file__).parent.parent.parent" in code

    def test_wrapper_depth_0_emits_one_parent(self, py_stage):
        code = produce_wrapper(py_stage, wrapper_depth=0)
        assert "Path(__file__).parent" in code
        assert ".parent.parent" not in code

    def test_write_all_wrappers_creates_one_file_per_stage(self, multi_stage_spec, tmp_path):
        written = write_all_wrappers(
            multi_stage_spec, tmp_path,
            wrapper_prefix="run_", wrapper_depth=2,
        )
        assert len(written) == 2
        for path in written:
            assert path.exists()
            assert path.name.startswith("run_")

    def test_wrapper_filename_matches_task_key(self, multi_stage_spec, tmp_path):
        written = write_all_wrappers(
            multi_stage_spec, tmp_path,
            wrapper_prefix="run_", wrapper_depth=2,
        )
        names = {p.name for p in written}
        assert "run_bronze_table_setup_create_cdmv5_tables_sql.py" in names
        assert "run_bronze_bronze_get_synpuf_files_py.py" in names

    def test_custom_wrapper_prefix_is_respected(self, py_stage, tmp_path):
        written = write_all_wrappers(
            {"stages": [py_stage]}, tmp_path,
            wrapper_prefix="exec_", wrapper_depth=2,
        )
        assert written[0].name.startswith("exec_")

    def test_py_wrapper_splits_env_vars_from_args(self, tmp_path):
        """NAME=value params become env vars; everything else stays a CLI arg."""
        import json, subprocess, sys

        # A tiny stand-in script that prints what it received.
        script = tmp_path / "echo.py"
        script.write_text(
            "import os, sys, json\n"
            "print(json.dumps({'args': sys.argv[1:], 'out': os.environ.get('OUT_DIR')}))\n"
        )

        stage = {"name": "s", "layer": "l",
                 "entry_point": {"file": "echo.py", "path": "echo.py"}}

        # Put the wrapper one folder down, so its repo root is tmp_path.
        (tmp_path / "w").mkdir()
        wrapper = tmp_path / "w" / "run.py"
        wrapper.write_text(produce_wrapper(stage, wrapper_depth=1), encoding="utf-8")

        out = subprocess.run(
            [sys.executable, str(wrapper), "1", "OUT_DIR=/x"],
            capture_output=True, text=True, check=True,
        ).stdout
        assert json.loads(out) == {"args": ["1"], "out": "/x"}


# ── Angry path ───────────────────────────────────────────────────────────────

class TestAngryPath:
    """Invalid inputs that should raise an error."""

    def test_write_all_wrappers_raises_on_missing_name(self, tmp_path):
        # name is required for the task_key — missing it is a hard error.
        bad_stage = {
            "layer": "bronze",
            "entry_point": {"file": "x.py", "path": "src/x.py"},
        }
        with pytest.raises(KeyError):
            write_all_wrappers(
                {"stages": [bad_stage]}, tmp_path,
                wrapper_prefix="run_", wrapper_depth=2,
            )

    def test_write_all_wrappers_raises_on_entry_point_without_file(self, tmp_path):
        # produce_wrapper falls back to path for file_name, but write_all_wrappers
        # reads stage["entry_point"]["file"] directly for the task_key.
        bad_stage = {
            "name": "bronze",
            "layer": "bronze",
            "entry_point": {"path": "src/x.py"},  # no "file"
        }
        with pytest.raises(KeyError):
            write_all_wrappers(
                {"stages": [bad_stage]}, tmp_path,
                wrapper_prefix="run_", wrapper_depth=2,
            )


# ── Desolate path ────────────────────────────────────────────────────────────

class TestDesolatePath:
    """Empty inputs — empty lists, empty dicts, missing containers."""

    def test_empty_stages_list_writes_nothing(self, tmp_path):
        written = write_all_wrappers(
            {"stages": []}, tmp_path,
            wrapper_prefix="run_", wrapper_depth=2,
        )
        assert written == []

    def test_missing_stages_key_writes_nothing(self, tmp_path):
        written = write_all_wrappers(
            {}, tmp_path,
            wrapper_prefix="run_", wrapper_depth=2,
        )
        assert written == []

    def test_empty_stage_dict_returns_none(self):
        assert produce_wrapper({}, wrapper_depth=2) is None

    def test_empty_entry_point_dict_returns_none(self):
        stage = {"name": "x", "layer": "y", "entry_point": {}}
        assert produce_wrapper(stage, wrapper_depth=2) is None


# ── Delinquent path ──────────────────────────────────────────────────────────

class TestDelinquentPath:
    """Malformed inputs — wrong types, placeholder sentinels, bad extensions."""

    def test_entry_point_as_string_sentinel_returns_none(self):
        # Form sentinel from before the user picks a script.
        stage = {"name": "gold", "layer": "gold", "entry_point": "entry_point_default"}
        assert produce_wrapper(stage, wrapper_depth=2) is None

    def test_entry_point_as_list_returns_none(self):
        stage = {"name": "x", "layer": "y", "entry_point": ["bad"]}
        assert produce_wrapper(stage, wrapper_depth=2) is None

    def test_entry_point_as_none_returns_none(self):
        stage = {"name": "x", "layer": "y", "entry_point": None}
        assert produce_wrapper(stage, wrapper_depth=2) is None

    def test_unsupported_extension_returns_none_and_logs_warning(self, caplog):
        stage = {
            "name": "x",
            "layer": "y",
            "entry_point": {"file": "data.csv", "path": "data.csv"},
        }
        assert produce_wrapper(stage, wrapper_depth=2) is None
        assert "unsupported extension" in caplog.text


# ── Forgetful path ───────────────────────────────────────────────────────────

class TestForgetfulPath:
    """Optional fields missing from the input — defaults should fill in."""

    def test_missing_layer_still_produces_wrapper(self):
        stage = {
            "name": "bronze",
            "entry_point": {"file": "x.py", "path": "src/x.py"},
        }
        code = produce_wrapper(stage, wrapper_depth=2)
        assert code is not None
        assert "src/x.py" in code

    def test_missing_stage_name_defaults_to_unnamed(self):
        stage = {
            "layer": "bronze",
            "entry_point": {"file": "x.py", "path": "src/x.py"},
        }
        code = produce_wrapper(stage, wrapper_depth=2)
        assert code is not None
        assert "unnamed" in code

    def test_missing_file_falls_back_to_path(self):
        # entry_point.file is optional in produce_wrapper — path is used instead.
        stage = {
            "name": "x",
            "layer": "y",
            "entry_point": {"path": "src/thing.py"},
        }
        code = produce_wrapper(stage, wrapper_depth=2)
        assert code is not None
        assert "src/thing.py" in code

    def test_missing_entry_point_path_returns_none(self):
        stage = {
            "name": "x",
            "layer": "y",
            "entry_point": {"file": "x.py"},  # no path
        }
        assert produce_wrapper(stage, wrapper_depth=2) is None