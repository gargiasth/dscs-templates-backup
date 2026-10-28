"""
Orion Launchpad — generates one Python wrapper file per stage.

The wrapper is what Databricks actually runs. It connects to the user's
entry-point:
  - .py  → wrapper subprocess-runs the script
  - .sql → wrapper reads, translates, and executes via spark.sql()

Around the script, the wrapper runs Orion's checks when the task passes
ORION_INPUT / ORION_OUTPUT parameters (added by the jobs emitter):
  before: input folders exist and hold valid files; the output folder is
          writable; the script is pointed at a holding folder next to it
  after:  the holding folder has data and nothing clashes with files already
          in the output folder; then the files are moved in

Wrapper filename matches the task_key so emitter and generator agree:
    run_<task_key>.py
"""

import json
import logging
from pathlib import Path

from utilities.emitter_helpers import _task_key, PREFLIGHT_KEY
from utilities.logger import setup_logging

setup_logging()
log = logging.getLogger(__name__)


def produce_wrapper(stage: dict, wrapper_depth: int) -> str | None:
    """Return wrapper source code for one stage, or None to skip."""
    entry = stage.get("entry_point")
    if not isinstance(entry, dict):
        return None

    script_path = entry.get("path")
    if not script_path:
        return None

    file_name  = entry.get("file", script_path)
    stage_name = stage.get("name", "unnamed")
    repo_root  = "_HERE" + ".parent" * (wrapper_depth + 1)

    if file_name.endswith(".py"):
        return _PY_TEMPLATE.format(
            stage_name=stage_name,
            script_file=file_name,
            script_path=script_path,
            repo_root=repo_root,
        )

    if file_name.endswith(".sql"):
        return _SQL_TEMPLATE.format(
            stage_name=stage_name,
            sql_file=file_name,
            sql_path=script_path,
            repo_root=repo_root,
        )

    log.warning("stage %r: unsupported extension %r", stage_name, file_name)
    return None


def write_all_wrappers(spec: dict, output_dir, wrapper_prefix: str, wrapper_depth: int) -> list[Path]:
    """Write a wrapper for every stage. Returns the paths written."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    written = []
    for stage in spec.get("stages", []):
        code = produce_wrapper(stage, wrapper_depth)
        if code is None:
            continue

        task_key = _task_key(
            stage.get("layer", ""),
            stage["name"],
            stage["entry_point"]["file"],
        )
        path = output_dir / f"{wrapper_prefix}{task_key}.py"
        path.write_text(code, encoding="utf-8")
        written.append(path)
        log.info("wrote %s", path)

    # One job-start check, only if there is something for it to protect.
    if written:
        path = output_dir / f"{wrapper_prefix}{PREFLIGHT_KEY}.py"
        path.write_text(produce_preflight_wrapper(wrapper_depth), encoding="utf-8")
        written.insert(0, path)
        log.info("wrote %s", path)

    return written


def produce_preflight_wrapper(wrapper_depth: int) -> str:
    """Source of run_orion_preflight.py — the Databricks starter for preflight_validator.preflight()."""
    return _PREFLIGHT_TEMPLATE.format(repo_root="_HERE" + ".parent" * (wrapper_depth + 1))
# ── Templates ────────────────────────────────────────────────────────────────

_PY_TEMPLATE = '''"""Wrapper for stage: {stage_name} — entry-point: {script_file}"""
import os, re, subprocess, sys
from pathlib import Path

# Databricks serverless runs this file with exec(), where __file__ isn't set.
# The compiled code still knows its own file name, so fall back to that.
try:
    _HERE = Path(__file__)
except NameError:
    import inspect
    _HERE = Path(inspect.currentframe().f_code.co_filename)

_REPO_ROOT = {repo_root}
_SCRIPT = _REPO_ROOT / "{script_path}"

# ── Orion checks: ORION_INPUT / ORION_OUTPUT parameters are for the wrapper, not the script ──
orion_inputs, orion_output, rest = [], None, []
for a in sys.argv[1:]:
    if a.startswith("ORION_INPUT="):
        path, _, who = a[len("ORION_INPUT="):].partition("|")
        orion_inputs.append((path, who or "an earlier step"))
    elif a.startswith("ORION_OUTPUT="):
        orion_output = a[len("ORION_OUTPUT="):]
    else:
        rest.append(a)

if orion_inputs or orion_output:
    sys.path.insert(0, str(_REPO_ROOT))      # so `validation` and `utilities` import on Databricks
    from validation.input_validator import check_inputs, InputValidationError
    from validation.output_validator import prepare_output, finish_output, OutputValidationError
    try:
        if orion_inputs:
            check_inputs(orion_inputs, platform="databricks")
        if orion_output:
            # The script writes to a holding folder; Orion moves the files in afterwards,
            # refusing any that would overwrite a file already in the output folder.
            orion_staging = str(prepare_output(orion_output, platform="databricks"))
            import re as _re
            _out = _re.compile(_re.escape(orion_output.rstrip("/")) + r"(?=/|$)")
            rest = [_out.sub(lambda _m: orion_staging, a) for a in rest]
    except (InputValidationError, OutputValidationError) as e:
        sys.exit(f"Orion check failed before running the script:\\n{{e}}")

# ── NAME=value parameters become environment variables; the rest are CLI args ──
env  = dict(os.environ)

# Let the script import its sibling modules however it does locally: `import constants`
# (its own folder) or `from python_etl.constants import ...` (a folder above). Every
# folder from the script's own up to, not including, the repo root goes on PYTHONPATH.
_paths, _d = [], _SCRIPT.parent
while _d != _REPO_ROOT and _REPO_ROOT in _d.parents:
    _paths.append(str(_d))
    _d = _d.parent
if env.get("PYTHONPATH"):
    _paths.append(env["PYTHONPATH"])
env["PYTHONPATH"] = os.pathsep.join(_paths)

args = []
for a in rest:
    m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", a)
    if m:
        env[m.group(1)] = m.group(2)
    else:
        args.append(a)

subprocess.run([sys.executable, str(_SCRIPT), *args], env=env, check=True)

if orion_output:
    try:
        finish_output(orion_output, orion_staging)
    except OutputValidationError as e:
        sys.exit(f"Orion check failed after running the script:\\n{{e}}")
'''

_SQL_TEMPLATE = '''"""Wrapper for stage: {stage_name} — entry-point: {sql_file}"""
import sys
from pathlib import Path

# Databricks serverless runs this file with exec(), where __file__ isn't set.
# The compiled code still knows its own file name, so fall back to that.
try:
    _HERE = Path(__file__)
except NameError:
    import inspect
    _HERE = Path(inspect.currentframe().f_code.co_filename)

_REPO_ROOT = {repo_root}
sys.path.insert(0, str(_REPO_ROOT))          # so `utilities` imports on Databricks

from utilities.sql_read import read_sql_file
from utilities.sql_translate import translate
from utilities.sql_execute import execute_statements

_SQL_PATH = _REPO_ROOT / "{sql_path}"

# ── Orion checks: ORION_INPUT / ORION_OUTPUT parameters are for the wrapper, not the script ──
orion_inputs, orion_output, rest = [], None, []
for a in sys.argv[1:]:
    if a.startswith("ORION_INPUT="):
        path, _, who = a[len("ORION_INPUT="):].partition("|")
        orion_inputs.append((path, who or "an earlier step"))
    elif a.startswith("ORION_OUTPUT="):
        orion_output = a[len("ORION_OUTPUT="):]
    else:
        rest.append(a)

if orion_inputs or orion_output:
    sys.path.insert(0, str(_REPO_ROOT))      # so `validation` and `utilities` import on Databricks
    from validation.input_validator import check_inputs, InputValidationError
    from validation.output_validator import prepare_output, finish_output, OutputValidationError
    try:
        if orion_inputs:
            check_inputs(orion_inputs, platform="databricks")
        if orion_output:
            # The script writes to a holding folder; Orion moves the files in afterwards,
            # refusing any that would overwrite a file already in the output folder.
            orion_staging = str(prepare_output(orion_output, platform="databricks"))
            import re as _re
            _out = _re.compile(_re.escape(orion_output.rstrip("/")) + r"(?=/|$)")
            rest = [_out.sub(lambda _m: orion_staging, a) for a in rest]
    except (InputValidationError, OutputValidationError) as e:
        sys.exit(f"Orion check failed before running the script:\\n{{e}}")

if len(rest) < 2:
    sys.exit("usage: <wrapper> <catalog> <schema>")
catalog = rest[0]
schema  = rest[1]
# Any further NAME=value parameters are handed to the translator (e.g. data_dir for \\COPY)
params  = dict(a.split("=", 1) for a in rest[2:] if "=" in a)

results    = translate(read_sql_file(_SQL_PATH), read="postgres", dialect="databricks", params=params)
for item in results:
    if item["unsupported_reason"]:
        print(f"skipped: {{item['unsupported_reason']}} -- {{item['sql'][:80]}}")
statements = [item["sql"] for item in results if not item["unsupported_reason"]]
if not statements:
    sys.exit("Nothing to run: every statement in this SQL file was skipped (reasons above).")

summary = execute_statements(statements, catalog=catalog, schema=schema)
if summary["failed"]:
    sys.exit(1)

if orion_output:
    try:
        finish_output(orion_output, orion_staging)
    except OutputValidationError as e:
        sys.exit(f"Orion check failed after running the script:\\n{{e}}")
'''

_PREFLIGHT_TEMPLATE = '''"""Orion preflight — checks the catalog, schema, volumes and folders exist; creates missing ones."""
import sys
from pathlib import Path

# Databricks serverless runs this file with exec(), where __file__ isn't set.
# The compiled code still knows its own file name, so fall back to that.
try:
    _HERE = Path(__file__)
except NameError:
    import inspect
    _HERE = Path(inspect.currentframe().f_code.co_filename)

sys.path.insert(0, str({repo_root}))        # so `validation` and `utilities` import on Databricks

from pyspark.sql import SparkSession
from validation.preflight_validator import preflight, ValidationError

# ORION_FOLDER=<path> parameters are folders to create; everything else is catalog, schema, volumes
folders = [a[len("ORION_FOLDER="):] for a in sys.argv[1:] if a.startswith("ORION_FOLDER=")]
names   = [a for a in sys.argv[1:] if not a.startswith("ORION_FOLDER=")]
if len(names) < 3:
    sys.exit("usage: <wrapper> <catalog> <schema> <volume> [<volume> ...] [ORION_FOLDER=<path> ...]")
catalog, schema, *volumes = names

try:
    preflight(SparkSession.builder.getOrCreate(), catalog, schema, volumes,
              platform="databricks", folders=folders)
except ValidationError as e:
    sys.exit(f"preflight failed: {{e}}")
'''


if __name__ == "__main__":
    import argparse
    from utilities.compiler import WRAPPER_DIR, WRAPPER_PREFIX

    parser = argparse.ArgumentParser(description="Generate wrappers for an orion.json spec.")
    parser.add_argument("spec_path", help="Path to orion.json")
    parser.add_argument("output_dir", help="Where to write wrappers")
    args = parser.parse_args()

    spec = json.loads(Path(args.spec_path).read_text(encoding="utf-8"))
    for p in write_all_wrappers(spec, Path(args.output_dir), WRAPPER_PREFIX, len(WRAPPER_DIR.parts)):
        print(p)