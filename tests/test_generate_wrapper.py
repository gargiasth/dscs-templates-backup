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
        assert "_HERE.parent.parent.parent" in code

    def test_wrapper_depth_0_emits_one_parent(self, py_stage):
        code = produce_wrapper(py_stage, wrapper_depth=0)
        assert "_REPO_ROOT = _HERE.parent\n" in code
        assert ".parent.parent" not in code

    def test_write_all_wrappers_creates_one_file_per_stage(self, multi_stage_spec, tmp_path):
        written = write_all_wrappers(
            multi_stage_spec, tmp_path,
            wrapper_prefix="run_", wrapper_depth=2,
        )
        assert len(written) == 3          # preflight + the two stages
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

# ── Orion checks inside the wrapper ─────────────────────────────────────────

REPO = Path(__file__).resolve().parent.parent      # so the wrapper can import `validation`

from validation.output_validator import staging_path


def _run_wrapper(tmp_path, script_body, *args):
    """Write a script + its wrapper in tmp_path and run the wrapper. Returns the CompletedProcess."""
    import os, subprocess, sys
    (tmp_path / "s.py").write_text(script_body, encoding="utf-8")
    stage = {"name": "s", "layer": "l", "entry_point": {"file": "s.py", "path": "s.py"}}
    (tmp_path / "w").mkdir(exist_ok=True)
    wrapper = tmp_path / "w" / "run.py"
    wrapper.write_text(produce_wrapper(stage, wrapper_depth=1), encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(REPO)}
    return subprocess.run([sys.executable, str(wrapper), *args],
                          capture_output=True, text=True, env=env)


class TestOrionChecks:

    # writes x.csv into the folder given as argv[1]
    WRITE_ONE = "import sys, pathlib; pathlib.Path(sys.argv[1], 'x.csv').write_text('a\\n1\\n')\n"

    def test_good_run_moves_output_in(self, tmp_path):
        out = tmp_path / "out"
        r = _run_wrapper(tmp_path, self.WRITE_ONE, str(out), f"ORION_OUTPUT={out}")
        assert r.returncode == 0, r.stderr
        assert (out / "x.csv").exists()
        assert not staging_path(out).exists()          # holding folder cleaned up

    def test_script_is_pointed_at_the_holding_folder(self, tmp_path):
        script = "import os, sys, json; print(json.dumps([sys.argv[1:], os.environ.get('OUT_DIR')]))\n"
        out = tmp_path / "out"
        r = _run_wrapper(tmp_path, script, str(out) + "/control", f"OUT_DIR={out}", f"ORION_OUTPUT={out}")
        import json
        argv, out_dir = json.loads(r.stdout.strip().splitlines()[-1])
        staging = str(staging_path(out))                # local holding folder, not on the volume
        assert argv == [staging + "/control"] and out_dir == staging

    def test_orion_params_are_not_passed_to_the_script(self, tmp_path):
        script = "import os, sys, json; print(json.dumps([sys.argv[1:], os.environ.get('ORION_INPUT')]))\n"
        inp = tmp_path / "in"; inp.mkdir(); (inp / "a.csv").write_text("a\n1\n")
        r = _run_wrapper(tmp_path, script, "1", f"ORION_INPUT={inp}|manual upload")
        assert r.returncode == 0, r.stderr
        import json
        assert json.loads(r.stdout.strip().splitlines()[-1]) == [["1"], None]

    def test_missing_input_stops_before_the_script(self, tmp_path):
        script = "open('ran.txt', 'w').write('yes')\n"
        r = _run_wrapper(tmp_path, script, f"ORION_INPUT={tmp_path / 'nope'}|upstream task bronze_x_py")
        assert r.returncode != 0
        assert "not found" in r.stderr and "bronze_x_py" in r.stderr
        assert not (tmp_path / "ran.txt").exists()

    def test_existing_files_are_fine(self, tmp_path):
        out = tmp_path / "out"; out.mkdir(); (out / "old.csv").write_text("a\n1\n")
        r = _run_wrapper(tmp_path, self.WRITE_ONE, str(out), f"ORION_OUTPUT={out}")
        assert r.returncode == 0, r.stderr
        assert (out / "old.csv").exists() and (out / "x.csv").exists()

    def test_same_name_file_is_not_overwritten(self, tmp_path):
        out = tmp_path / "out"; out.mkdir(); (out / "x.csv").write_text("old\n")
        r = _run_wrapper(tmp_path, self.WRITE_ONE, str(out), f"ORION_OUTPUT={out}")
        assert r.returncode != 0 and "same name" in r.stderr
        assert (out / "x.csv").read_text() == "old\n"

    def test_script_that_writes_nothing_fails_after(self, tmp_path):
        r = _run_wrapper(tmp_path, "pass\n", f"ORION_OUTPUT={tmp_path / 'out'}")
        assert r.returncode != 0 and "wrote nothing" in r.stderr

    def test_sql_wrapper_reads_catalog_schema_after_orion_params_removed(self):
        code = produce_wrapper({"name": "t", "layer": "b",
                                "entry_point": {"file": "a.sql", "path": "a.sql"}}, wrapper_depth=2)
        assert "catalog = rest[0]" in code and "schema  = rest[1]" in code
        assert "sys.path.insert(0, str(_REPO_ROOT))" in code


# ── Runs without __file__ (how Databricks serverless executes spark_python_task) ──

def test_wrappers_find_their_repo_root_without_dunder_file(tmp_path):
    """Databricks runs the wrapper via exec(compile(src, filename, 'exec')) with no __file__."""
    stage = {"name": "s", "layer": "l", "entry_point": {"file": "a.py", "path": "a.py"}}
    wrapper = tmp_path / "utilities" / "wrappers" / "run.py"
    wrapper.parent.mkdir(parents=True)
    code = produce_wrapper(stage, wrapper_depth=2)
    wrapper.write_text(code, encoding="utf-8")
    # run only the lines up to _REPO_ROOT, exactly the way Databricks does
    head = code.split("_SCRIPT =")[0]
    ns = {"__name__": "__main__"}
    exec(compile(head, str(wrapper), "exec"), ns)
    assert ns["_REPO_ROOT"] == tmp_path